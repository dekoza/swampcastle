"""
embeddings.py — Pluggable embedding backends for SwampCastle.

Supported backends:
  - onnx: all-MiniLM-L6-v2 via ONNX Runtime (default, lightweight — no torch)
  - sentence-transformers: any HuggingFace model (requires `pip install swampcastle[gpu]`)
  - ollama: any model served by a local/remote Ollama instance (no extra deps)

Config in ~/.swampcastle/config.json:
    {}                                     — uses ONNX default
    {"embedder": "onnx"}                  — canonical ONNX backend
    {"embedder": "all-MiniLM-L6-v2"}      — same as default
    {"embedder": "bge-small"}             — requires [gpu]
    {"embedder": "ollama", "embedder_options": {"model": "nomic-embed-text"}}
    {"onnx_intra_op_threads": 8, "onnx_inter_op_threads": 1, "embed_batch_size": 128}
                                          — tune canonical CPU ONNX throughput without changing the embedding contract
"""

from __future__ import annotations

import hashlib
import json
import logging
import struct
import threading
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol, runtime_checkable

from .tuning import suggest_onnx_tuning

logger = logging.getLogger("swampcastle")


# ── Protocol ──────────────────────────────────────────────────────────────────


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedding backends."""

    @property
    def dimension(self) -> int: ...

    @property
    def model_name(self) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# ── Shared helpers ────────────────────────────────────────────────────────────


_VERIFICATION_PROBE_TEXTS = (
    "SwampCastle keeps drawers verbatim for retrieval.",
    "Paths matter: /var/lib/swampcastle/castle and ~/.swampcastle/config.json",
    "SQL-ish filters include wing=project, room=auth, seq>=10.",
    "Punctuation check: commas, semicolons; quotes 'single' and \"double\".",
    "Unicode check: café naïve résumé λ-calculus 你好.",
    "Short line\nSecond line\nThird line",
    "Code-ish text: def embed(texts): return model.encode(texts)",
    "Numbers and dates: 2026-04-14, 384d, 24GB VRAM, 0.95 precision.",
)


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def fingerprint_sha256(fingerprint: dict[str, Any]) -> str:
    payload = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def get_embedder_fingerprint(embedder: Embedder) -> dict[str, Any]:
    raw = getattr(embedder, "fingerprint", None)
    if callable(raw):
        raw = raw()
    if raw is None:
        raw = {
            "backend": type(embedder).__name__.lower(),
            "model_name": getattr(embedder, "model_name", None),
            "dimension": getattr(embedder, "dimension", None),
        }
    fingerprint = dict(raw)
    fingerprint.setdefault("model_name", getattr(embedder, "model_name", None))
    fingerprint.setdefault("dimension", getattr(embedder, "dimension", None))
    return _compact_dict(fingerprint)


def build_embedding_verification_report(
    embedder: Embedder,
    texts: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    probe_texts = tuple(texts or _VERIFICATION_PROBE_TEXTS)
    vectors = embedder.embed(list(probe_texts))
    vector_hasher = hashlib.sha256()
    for vector in vectors:
        vector_hasher.update(struct.pack(f"<{len(vector)}f", *vector))

    fingerprint = get_embedder_fingerprint(embedder)
    return {
        "embedder": fingerprint,
        "fingerprint_hash": fingerprint_sha256(fingerprint),
        "probe_hash": vector_hasher.hexdigest(),
        "probe_count": len(probe_texts),
    }


# ── ONNX (default, lightweight) ───────────────────────────────────────────────

_ONNX_MODEL_NAME = "all-MiniLM-L6-v2"
_ONNX_DOWNLOAD_URL = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
_ONNX_SHA256 = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
_ONNX_ARCHIVE = "onnx.tar.gz"
_ONNX_SUBDIR = "onnx"
_ONNX_REQUIRED_FILES = (
    "config.json",
    "model.onnx",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.txt",
)
_ONNX_PROVIDERS = ("CPUExecutionProvider",)


def _onnx_model_dir() -> str:
    """Cache directory for the ONNX model files."""
    import os
    from pathlib import Path

    return str(
        Path(
            os.environ.get(
                "SWAMPCASTLE_ONNX_CACHE",
                Path.home() / ".cache" / "swampcastle" / "onnx_models" / _ONNX_MODEL_NAME,
            )
        )
        / _ONNX_SUBDIR
    )


def _ensure_onnx_model() -> str:
    """Download and extract the ONNX model if not already cached. Returns model dir."""
    import os
    import tarfile
    from pathlib import Path
    from urllib.request import Request, urlopen

    model_dir = _onnx_model_dir()
    if all(os.path.exists(os.path.join(model_dir, f)) for f in _ONNX_REQUIRED_FILES):
        return model_dir

    cache_root = str(Path(model_dir).parent)
    os.makedirs(cache_root, exist_ok=True)
    archive_path = os.path.join(cache_root, _ONNX_ARCHIVE)

    if not os.path.exists(archive_path) or not _verify_sha256(archive_path, _ONNX_SHA256):
        logger.info("Downloading ONNX model %s...", _ONNX_MODEL_NAME)
        req = Request(_ONNX_DOWNLOAD_URL)
        with urlopen(req) as resp, open(archive_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        if not _verify_sha256(archive_path, _ONNX_SHA256):
            os.remove(archive_path)
            raise RuntimeError(
                f"Downloaded ONNX model failed SHA256 verification. Delete {cache_root} and retry."
            )

    with tarfile.open(archive_path, "r:gz") as tar:
        import sys

        if sys.version_info >= (3, 12):
            tar.extractall(path=cache_root, filter="data")
        else:
            tar.extractall(path=cache_root)

    return model_dir


def _verify_sha256(path: str, expected: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest() == expected


class OnnxEmbedder:
    """Embedding via ONNX Runtime — the default, lightweight backend.

    Uses the all-MiniLM-L6-v2 model converted to ONNX format.
    No torch or sentence-transformers required. The ONNX model (~87MB)
    is downloaded once on first use and cached in ~/.cache/swampcastle/.

    This path is the canonical CPU-only embedder for deterministic multi-device
    sync. It is intentionally pinned to CPUExecutionProvider.
    """

    DIMENSION = 384
    MAX_SEQ_LENGTH = 256
    BATCH_SIZE = 32

    def __init__(
        self,
        providers: tuple[str, ...] | None = None,
        intra_op_num_threads: int | None = None,
        inter_op_num_threads: int | None = None,
    ):
        self._providers = tuple(providers or _ONNX_PROVIDERS)
        self._session = None
        self._tokenizer = None
        self._intra_op_num_threads = _positive_int_or_none(intra_op_num_threads)
        self._inter_op_num_threads = _positive_int_or_none(inter_op_num_threads)

    @property
    def model_name(self) -> str:
        return _ONNX_MODEL_NAME

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    @property
    def fingerprint(self) -> dict[str, Any]:
        return _compact_dict(
            {
                "backend": "onnx",
                "model_name": self.model_name,
                "dimension": self.dimension,
                "providers": list(self._providers),
                "asset_sha256": _ONNX_SHA256,
                "onnxruntime_version": _package_version("onnxruntime"),
                "tokenizers_version": _package_version("tokenizers"),
            }
        )

    def _load(self):
        if self._session is not None:
            return

        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError(
                "onnxruntime is required for the default embedder. "
                "Install with: pip install onnxruntime"
            )
        try:
            from tokenizers import Tokenizer
        except ImportError:
            raise ImportError(
                "tokenizers is required for the default embedder. "
                "Install with: pip install tokenizers"
            )

        import os

        available = set(ort.get_available_providers())
        missing = [provider for provider in self._providers if provider not in available]
        if missing:
            raise RuntimeError(
                "Required ONNX provider(s) unavailable: "
                f"{', '.join(missing)}. Available: {sorted(available)}"
            )

        model_dir = _ensure_onnx_model()

        so = ort.SessionOptions()
        so.log_severity_level = 3
        suggested = suggest_onnx_tuning()
        so.intra_op_num_threads = self._intra_op_num_threads or suggested["onnx_intra_op_threads"]
        so.inter_op_num_threads = self._inter_op_num_threads or suggested["onnx_inter_op_threads"]
        self._session = ort.InferenceSession(
            os.path.join(model_dir, "model.onnx"),
            providers=list(self._providers),
            sess_options=so,
        )

        self._tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=self.MAX_SEQ_LENGTH)
        self._tokenizer.enable_padding(
            pad_id=0,
            pad_token="[PAD]",
            length=self.MAX_SEQ_LENGTH,
        )
        logger.info("Loaded ONNX embedder: %s (%dd)", _ONNX_MODEL_NAME, self.DIMENSION)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        import numpy as np

        all_embeddings = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            encoded = [self._tokenizer.encode(t) for t in batch]
            input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

            output = self._session.run(
                None,
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "token_type_ids": token_type_ids,
                },
            )

            last_hidden = output[0]
            mask_expanded = np.broadcast_to(
                np.expand_dims(attention_mask, -1).astype(np.float32),
                last_hidden.shape,
            )
            embeddings = np.sum(last_hidden * mask_expanded, axis=1) / np.clip(
                mask_expanded.sum(axis=1),
                a_min=1e-9,
                a_max=None,
            )
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1e-12
            embeddings = (embeddings / norms).astype(np.float32)
            all_embeddings.append(embeddings)

        return np.concatenate(all_embeddings).tolist()


# ── Sentence Transformers (requires [gpu] extra) ─────────────────────────────


class SentenceTransformerEmbedder:
    """Embedding via sentence-transformers library.

    Works with any HuggingFace model:
      - all-MiniLM-L6-v2 (384d) — fast, decent quality
      - BAAI/bge-small-en-v1.5 (384d) — best quality-at-size for English
      - BAAI/bge-base-en-v1.5 (768d) — higher quality, larger
      - intfloat/e5-base-v2 (768d) — good general purpose
      - nomic-ai/nomic-embed-text-v1.5 (768d) — Matryoshka dimensions
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu"):
        self._model_name = model_name
        self._device = device
        self._model = None
        self._dim = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        if self._dim is None:
            self._load()
        return self._dim

    @property
    def fingerprint(self) -> dict[str, Any]:
        return _compact_dict(
            {
                "backend": "sentence-transformers",
                "model_name": self.model_name,
                "dimension": self.dimension,
                "device": self._device,
                "sentence_transformers_version": _package_version("sentence-transformers"),
                "transformers_version": _package_version("transformers"),
                "torch_version": _package_version("torch"),
            }
        )

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for this embedder. "
                "Install with: pip install swampcastle[gpu]"
            )
        self._model = SentenceTransformer(self._model_name, device=self._device)
        self._dim = self._model.get_embedding_dimension()
        logger.info("Loaded embedder: %s (%dd on %s)", self._model_name, self._dim, self._device)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        embeddings = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.tolist()


# ── Ollama ────────────────────────────────────────────────────────────────────


class OllamaEmbedder:
    """Embedding via a local or remote Ollama server.

    Useful for:
      - Running large models on a GPU server
      - Keeping the laptop dependency-light (no torch needed)
      - Using models like nomic-embed-text, mxbai-embed-large, snowflake-arctic-embed

    Requires Ollama running: ollama serve
    Pull the model first: ollama pull nomic-embed-text
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
    ):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._dim = None

    @property
    def model_name(self) -> str:
        return f"ollama/{self._model}"

    @property
    def dimension(self) -> int:
        if self._dim is None:
            probe = self._embed_batch(["dimension probe"])
            self._dim = len(probe[0])
        return self._dim

    @property
    def fingerprint(self) -> dict[str, Any]:
        return _compact_dict(
            {
                "backend": "ollama",
                "model_name": self.model_name,
                "dimension": self._dim,
                "base_url": self._base_url,
            }
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed_batch(texts)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Call Ollama /api/embed endpoint."""
        import json
        from urllib.error import URLError
        from urllib.request import Request, urlopen

        url = f"{self._base_url}/api/embed"
        payload = json.dumps({"model": self._model, "input": texts}).encode("utf-8")

        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except URLError as e:
            raise ConnectionError(
                f"Cannot reach Ollama at {self._base_url}. "
                f"Is it running? (ollama serve)\n  Error: {e}"
            ) from e

        embeddings = data.get("embeddings")
        if not embeddings:
            raise ValueError(
                f"Ollama returned no embeddings for model '{self._model}'. "
                f"Did you pull it? (ollama pull {self._model})"
            )

        if self._dim is None:
            self._dim = len(embeddings[0])
            logger.info("Ollama embedder: %s (%dd via %s)", self._model, self._dim, self._base_url)

        return embeddings


# ── Embedder cache & factory ─────────────────────────────────────────────────

_embedder_cache: dict[str, Embedder] = {}
_embedder_lock = threading.Lock()


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


MODEL_ALIASES = {
    "onnx": "onnx",
    "minilm": "all-MiniLM-L6-v2",
    "bge-small": "BAAI/bge-small-en-v1.5",
    "bge-base": "BAAI/bge-base-en-v1.5",
    "e5-base": "intfloat/e5-base-v2",
    "nomic": "nomic-ai/nomic-embed-text-v1.5",
}


def resolve_model_name(name: str) -> str:
    """Resolve a short alias to a full model name."""
    return MODEL_ALIASES.get(name, name)


def _get_or_create(cache_key: str, factory) -> Embedder:
    if cache_key not in _embedder_cache:  # unlocked read: safe on CPython (GIL)
        with _embedder_lock:
            if cache_key not in _embedder_cache:
                _embedder_cache[cache_key] = factory()
    return _embedder_cache[cache_key]


def get_embedder(config: dict | None = None) -> Embedder:
    """Factory: get or create a cached embedder from config.

    Config keys:
        embedder: backend or model name (default: "all-MiniLM-L6-v2")
        embedder_options:
            device: "cpu" | "cuda" | "mps"  (sentence-transformers)
            model: Ollama model name        (ollama backend)
            base_url: Ollama server URL     (ollama backend)
            timeout: request timeout secs   (ollama backend)

    Routing:
        - "onnx" → OnnxEmbedder (canonical CPU-only backend)
        - "ollama" → OllamaEmbedder
        - "all-MiniLM-L6-v2" + device=cpu → OnnxEmbedder
        - any non-default model or non-cpu MiniLM → SentenceTransformerEmbedder
    """
    config = config or {}
    name = config.get("embedder", "all-MiniLM-L6-v2")
    options = dict(config.get("embedder_options", {}))

    if name == "ollama":
        model = options.get("model", "nomic-embed-text")
        base_url = options.get("base_url", "http://localhost:11434")
        timeout = float(options.get("timeout", 60.0))
        cache_key = f"ollama:{model}@{base_url}"
        return _get_or_create(
            cache_key,
            lambda: OllamaEmbedder(model=model, base_url=base_url, timeout=timeout),
        )

    device = options.get("device", "cpu")
    onnx_intra = _positive_int_or_none(options.get("intra_op_num_threads"))
    onnx_inter = _positive_int_or_none(options.get("inter_op_num_threads"))
    onnx_cache_suffix = f"{onnx_intra or 'auto'}:{onnx_inter or 'auto'}"
    if name == "onnx":
        if device != "cpu":
            raise ValueError(
                "The ONNX embedder is CPU-only. Use all-MiniLM-L6-v2 with ST for cuda/mps."
            )
        if onnx_intra is None and onnx_inter is None:
            return _get_or_create(
                f"onnx:all-MiniLM-L6-v2:cpu:{onnx_cache_suffix}",
                OnnxEmbedder,
            )
        return _get_or_create(
            f"onnx:all-MiniLM-L6-v2:cpu:{onnx_cache_suffix}",
            lambda: OnnxEmbedder(
                intra_op_num_threads=onnx_intra,
                inter_op_num_threads=onnx_inter,
            ),
        )

    resolved = resolve_model_name(name)

    if resolved == "all-MiniLM-L6-v2" and device == "cpu":
        if onnx_intra is None and onnx_inter is None:
            return _get_or_create(
                f"onnx:all-MiniLM-L6-v2:cpu:{onnx_cache_suffix}",
                OnnxEmbedder,
            )
        return _get_or_create(
            f"onnx:all-MiniLM-L6-v2:cpu:{onnx_cache_suffix}",
            lambda: OnnxEmbedder(
                intra_op_num_threads=onnx_intra,
                inter_op_num_threads=onnx_inter,
            ),
        )

    cache_key = f"st:{resolved}:{device}"
    return _get_or_create(
        cache_key,
        lambda: SentenceTransformerEmbedder(model_name=resolved, device=device),
    )


def list_embedders() -> list[dict]:
    """List available embedder configurations for CLI help."""
    return [
        {
            "name": "onnx",
            "alias": "onnx",
            "dim": 384,
            "backend": "onnx",
            "notes": "Canonical CPU-only backend. Pins all-MiniLM-L6-v2 to CPUExecutionProvider.",
        },
        {
            "name": "all-MiniLM-L6-v2",
            "alias": "minilm",
            "dim": 384,
            "backend": "onnx",
            "notes": "Same canonical model as 'onnx'. CPU uses ONNX; non-CPU uses sentence-transformers.",
        },
        {
            "name": "BAAI/bge-small-en-v1.5",
            "alias": "bge-small",
            "dim": 384,
            "backend": "sentence-transformers",
            "notes": "Best quality-at-size for English. Requires [gpu].",
        },
        {
            "name": "BAAI/bge-base-en-v1.5",
            "alias": "bge-base",
            "dim": 768,
            "backend": "sentence-transformers",
            "notes": "Higher quality, larger model. Requires [gpu].",
        },
        {
            "name": "intfloat/e5-base-v2",
            "alias": "e5-base",
            "dim": 768,
            "backend": "sentence-transformers",
            "notes": "Good general purpose. Requires [gpu].",
        },
        {
            "name": "nomic-ai/nomic-embed-text-v1.5",
            "alias": "nomic",
            "dim": 768,
            "backend": "sentence-transformers",
            "notes": "Matryoshka dims (truncatable to 256/384). Requires [gpu].",
        },
        {
            "name": "ollama",
            "alias": "ollama",
            "dim": "varies",
            "backend": "ollama",
            "notes": "Any model via Ollama server. Set model + base_url in options.",
        },
    ]

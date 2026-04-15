"""Interactive wizard for global SwampCastle runtime configuration.

This command owns:
- backend selection (lance / postgres)
- castle path
- postgres connection settings
- ONNX CPU performance tuning
- personal identity setup (people, projects, usage mode)

It does NOT own:
- project-local mining config (.swampcastle.yaml)
- migration
- room detection
"""

from __future__ import annotations

import time
from pathlib import Path

from swampcastle.runtime_config import load_runtime_config, save_runtime_config
from swampcastle.tuning import detect_machine_resources, suggest_onnx_tuning


def _prompt(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"  {prompt}{suffix}: ").strip()
    if value:
        return value
    return default or ""


def _yn(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    val = input(f"  {prompt} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val.startswith("y")


# ── Backend configuration ────────────────────────────────────────────────────


def _configure_backend(config: dict) -> dict:
    print("\n  --- Storage backend ---\n")

    backend = _prompt("Backend (lance/postgres)", str(config.get("backend", "lance"))).lower()
    while backend not in {"lance", "postgres"}:
        print("  Please enter 'lance' or 'postgres'.")
        backend = _prompt("Backend (lance/postgres)", str(config.get("backend", "lance"))).lower()

    castle_path = _prompt("Castle path", str(config.get("castle_path", "")))

    updated = dict(config)
    updated.update(
        {
            "castle_path": castle_path,
            "backend": backend,
            "collection_name": config.get("collection_name", "swampcastle_chests"),
            "embedder": config.get("embedder", "onnx"),
        }
    )

    if backend == "postgres":
        database_url = _prompt("Database URL", str(config.get("database_url", "")))
        while not database_url:
            print("  PostgreSQL requires a database URL.")
            database_url = _prompt("Database URL", str(config.get("database_url", "")))
        updated["database_url"] = database_url
    else:
        updated.pop("database_url", None)

    return updated


# ── ONNX CPU tuning ──────────────────────────────────────────────────────────


def _positive_int_or_none(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _is_cpu_onnx_config(config: dict) -> bool:
    from swampcastle.embeddings import resolve_model_name

    name = str(config.get("embedder", "onnx"))
    options = dict(config.get("embedder_options", {}))
    device = str(options.get("device", config.get("embedder_device", "cpu") or "cpu")).lower()
    resolved = resolve_model_name(name)
    return device == "cpu" and (name == "onnx" or resolved == "all-MiniLM-L6-v2")


def _suggest_safe_onnx_settings(config: dict) -> dict[str, int]:
    cpu_count, total_memory_bytes = detect_machine_resources()
    suggested = suggest_onnx_tuning(cpu_count, total_memory_bytes)
    return {
        "onnx_intra_op_threads": _positive_int_or_none(config.get("onnx_intra_op_threads"))
        or suggested["onnx_intra_op_threads"],
        "onnx_inter_op_threads": _positive_int_or_none(config.get("onnx_inter_op_threads"))
        or suggested["onnx_inter_op_threads"],
        "embed_batch_size": _positive_int_or_none(config.get("embed_batch_size"))
        or suggested["embed_batch_size"],
    }


def _build_benchmark_corpus(sample_count: int = 192) -> list[str]:
    from swampcastle.embeddings import _VERIFICATION_PROBE_TEXTS

    corpus = []
    probes = list(_VERIFICATION_PROBE_TEXTS)
    for i in range(sample_count):
        base = probes[i % len(probes)]
        extra_tokens = " ".join(f"token{i % 17}_{j}" for j in range(1, (i % 24) + 2))
        corpus.append(f"{base}\nBenchmark sample {i}: {extra_tokens}")
    return corpus


def _iter_benchmark_candidates(config: dict) -> list[dict[str, int]]:
    cpu_count, total_memory_bytes = detect_machine_resources()
    safe = suggest_onnx_tuning(cpu_count, total_memory_bytes)
    current = _suggest_safe_onnx_settings(config)

    intra_candidates = sorted(
        {
            1,
            max(1, current["onnx_intra_op_threads"] // 2),
            current["onnx_intra_op_threads"],
            min(16, max(1, current["onnx_intra_op_threads"] * 2)),
            min(16, safe["onnx_intra_op_threads"]),
        }
    )
    batch_candidates = sorted(
        {
            64,
            current["embed_batch_size"],
            min(256, max(128, current["embed_batch_size"] * 2)),
            safe["embed_batch_size"],
        }
    )

    candidates = []
    for intra_threads in intra_candidates:
        for batch_size in batch_candidates:
            candidates.append(
                {
                    "onnx_intra_op_threads": intra_threads,
                    "onnx_inter_op_threads": 1,
                    "embed_batch_size": batch_size,
                }
            )
    return candidates


def _run_embedding_pipeline(embedder, documents: list[str], batch_size: int) -> None:
    for start in range(0, len(documents), batch_size):
        embedder.embed(documents[start : start + batch_size])


def _benchmark_onnx_settings(config: dict) -> dict[str, int]:
    from swampcastle.embeddings import OnnxEmbedder

    documents = _build_benchmark_corpus()
    candidates = _iter_benchmark_candidates(config)
    best_time = None
    best_settings = None

    print("\n  Running ONNX CPU benchmark...\n")
    for index, candidate in enumerate(candidates, start=1):
        print(
            "  "
            f"[{index:2}/{len(candidates)}] "
            f"intra={candidate['onnx_intra_op_threads']:>2} "
            f"inter={candidate['onnx_inter_op_threads']} "
            f"batch={candidate['embed_batch_size']:>3}"
        )
        embedder = OnnxEmbedder(
            intra_op_num_threads=candidate["onnx_intra_op_threads"],
            inter_op_num_threads=candidate["onnx_inter_op_threads"],
        )
        _run_embedding_pipeline(embedder, documents[:32], min(32, candidate["embed_batch_size"]))
        started = time.perf_counter()
        _run_embedding_pipeline(embedder, documents, candidate["embed_batch_size"])
        elapsed = time.perf_counter() - started

        if best_time is None or elapsed < best_time:
            best_time = elapsed
            best_settings = dict(candidate)

    if best_settings is None:
        raise RuntimeError("benchmark produced no candidate results")

    print(
        "\n  Best benchmark result: "
        f"intra={best_settings['onnx_intra_op_threads']}, "
        f"inter={best_settings['onnx_inter_op_threads']}, "
        f"batch={best_settings['embed_batch_size']}"
    )
    return best_settings


def _print_onnx_tuning(label: str, tuning: dict[str, int]) -> None:
    print(f"\n  {label}:")
    print(f"    ONNX intra-op threads:  {tuning['onnx_intra_op_threads']}")
    print(f"    ONNX inter-op threads:  {tuning['onnx_inter_op_threads']}")
    print(f"    Mine embed batch size:  {tuning['embed_batch_size']}")


def _save_runtime_tuning(config: dict, tuning: dict[str, int], *, label: str) -> Path:
    updated = dict(config)
    updated.update(tuning)
    config_path = save_runtime_config(updated)
    print(f"\n  {label}: {config_path}")
    return config_path


def _configure_onnx_performance(config: dict) -> dict[str, int]:
    if not _is_cpu_onnx_config(config):
        return {}

    print("\n  --- ONNX CPU performance ---\n")
    print("  SwampCastle can tune ONNX CPU threading and project mining batch size.")
    print("  These knobs improve throughput without changing the sync-safe ONNX contract.")

    if _yn(
        "Benchmark this machine to find faster ONNX settings? This can take a while on first run",
        default=False,
    ):
        try:
            benchmarked = _benchmark_onnx_settings(config)
        except Exception as exc:
            print(f"\n  Benchmark failed: {exc}")
            print("  Falling back to safe defaults.")
            benchmarked = _suggest_safe_onnx_settings(config)
            _print_onnx_tuning("Fallback safe defaults", benchmarked)
            return benchmarked
        _print_onnx_tuning("Benchmarked ONNX settings", benchmarked)
        return benchmarked

    suggested = _suggest_safe_onnx_settings(config)
    _print_onnx_tuning("Safe defaults", suggested)
    return suggested


# ── Personal identity setup ──────────────────────────────────────────────────


def _ask_mode() -> str:
    print("\n  --- Usage mode ---\n")
    print("  How are you using SwampCastle?\n")
    print("    [1]  Work      — projects, clients, colleagues, decisions")
    print("    [2]  Personal  — diary, family, health, relationships")
    print("    [3]  Both      — personal and professional mixed")
    print()

    while True:
        choice = input("  Your choice [1/2/3]: ").strip()
        if choice == "1":
            return "work"
        if choice == "2":
            return "personal"
        if choice == "3":
            return "combo"
        print("  Please enter 1, 2, or 3.")


def _ask_people(mode: str) -> list[dict]:
    people = []

    if mode in ("personal", "combo"):
        print("\n  --- People (personal) ---\n")
        print("  Who are the important people in your life?")
        print("  Format: name, relationship (e.g. 'Riley, daughter')")
        print("  Enter blank line when done.\n")
        while True:
            entry = input("  Person: ").strip()
            if not entry:
                break
            parts = [p.strip() for p in entry.split(",", 1)]
            name = parts[0]
            relationship = parts[1] if len(parts) > 1 else ""
            if name:
                people.append({"name": name, "relationship": relationship, "context": "personal"})

    if mode in ("work", "combo"):
        print("\n  --- People (work) ---\n")
        print("  Colleagues, clients, or collaborators you mention in notes?")
        print("  Format: name, role (e.g. 'Sarah, team lead')")
        print("  Enter blank line when done.\n")
        while True:
            entry = input("  Person: ").strip()
            if not entry:
                break
            parts = [p.strip() for p in entry.split(",", 1)]
            name = parts[0]
            role = parts[1] if len(parts) > 1 else ""
            if name:
                people.append({"name": name, "relationship": role, "context": "work"})

    return people


def _ask_projects() -> list[str]:
    print("\n  --- Projects ---\n")
    print("  What are your main projects? These help SwampCastle tell")
    print("  project names from ordinary words.")
    print("  Enter blank line when done.\n")
    projects = []
    while True:
        proj = input("  Project: ").strip()
        if not proj:
            break
        projects.append(proj)
    return projects


def _save_identity(
    mode: str,
    people: list[dict],
    projects: list[str],
    config_dir: Path | None = None,
    self_name: str = "",
    self_nickname: str = "",
    self_facts: list[str] | None = None,
) -> None:
    from swampcastle.runtime_config import runtime_config_dir

    from swampcastle.entity_registry import EntityRegistry

    resolved_dir = config_dir or runtime_config_dir()
    registry = EntityRegistry.load(resolved_dir)
    registry.seed(mode=mode, people=people, projects=projects, aliases={})
    if self_name:
        registry.set_self(name=self_name, nickname=self_nickname, facts=self_facts or [])

    resolved_dir.mkdir(parents=True, exist_ok=True)

    entity_codes = {}
    for person in people:
        name = person["name"]
        code = name[:3].upper()
        while code in entity_codes.values():
            code = name[:4].upper()
        entity_codes[name] = code

    lines = ["# AAAK Entity Registry", ""]
    if people:
        lines.append("## People")
        for person in people:
            name = person["name"]
            code = entity_codes[name]
            rel = person.get("relationship", "")
            lines.append(f"  {code}={name} ({rel})" if rel else f"  {code}={name}")
    if projects:
        lines.extend(["", "## Projects"])
        for proj in projects:
            lines.append(f"  {proj[:4].upper()}={proj}")

    (resolved_dir / "aaak_entities.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n  Identity saved: {registry._path}")
    print(f"  AAAK entities:  {resolved_dir / 'aaak_entities.md'}")


# ── Main wizard flow ─────────────────────────────────────────────────────────


def run_tune() -> None:
    config = load_runtime_config()

    print("  SwampCastle Tune")
    print("  Benchmark ONNX CPU ingest tuning without the full wizard.")

    if not _is_cpu_onnx_config(config):
        print("  Tune currently supports only the canonical CPU ONNX embedder path.")
        print("  Set 'embedder' to 'onnx' and keep device='cpu', then rerun this command.")
        return

    try:
        tuning = _benchmark_onnx_settings(config)
    except Exception as exc:
        print(f"\n  Benchmark failed: {exc}")
        print("  No changes were saved.")
        return

    _print_onnx_tuning("Benchmarked ONNX settings", tuning)
    _save_runtime_tuning(config, tuning, label="Saved tuned runtime config")


def run_wizard() -> None:
    config = load_runtime_config()

    print("  SwampCastle Wizard")
    print("  Configure global runtime and personal identity settings.")

    updated = _configure_backend(config)
    updated.update(_configure_onnx_performance(updated))
    _save_runtime_tuning(updated, {}, label="Saved runtime config")

    # Part 2: personal identity (optional)
    if _yn("\n  Set up personal identity? (who you are, people, projects)", default=True):
        print("\n  --- Your identity ---\n")
        print("  This helps SwampCastle recognise you in project teams")
        print("  and tag your own contributions during ingest.\n")
        self_name = _prompt("Your name")
        self_nickname = _prompt("Nickname or username (used in git, etc.)") if self_name else ""
        self_facts_raw = _prompt("Key facts about you (comma-separated, or blank)")
        self_facts = (
            [f.strip() for f in self_facts_raw.split(",") if f.strip()] if self_facts_raw else []
        )

        mode = _ask_mode()
        people = _ask_people(mode)
        projects = _ask_projects() if mode != "personal" else []
        _save_identity(
            mode,
            people,
            projects,
            self_name=self_name,
            self_nickname=self_nickname,
            self_facts=self_facts,
        )

    print("\n  Wizard complete.")

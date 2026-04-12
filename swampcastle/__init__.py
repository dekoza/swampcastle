"""Swamp Castle — Give your AI a memory. The fourth one stayed up."""

import logging
import os
import platform

from .cli import main  # noqa: E402
from .version import __version__  # noqa: E402

logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

if platform.machine() == "arm64" and platform.system() == "Darwin":
    os.environ.setdefault("ORT_DISABLE_COREML", "1")

__all__ = ["main", "__version__"]

"""CLI command handlers — split by concern."""

from swampcastle.cli.commands.shared import (
    DESKELETON_BATCH_SIZE,
    DeskeletonTargetStore,
    _print_kv,
    _print_progress,
    _print_section,
    _settings,
)
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings
from swampcastle.cli.commands.config import (
    cmd_drawbridge_run,
    cmd_drawbridge_setup,
    cmd_tune,
    cmd_wizard,
)
from swampcastle.cli.commands.internal import cmd_hook, cmd_instructions
from swampcastle.cli.commands.kg import (
    cmd_kg_accept,
    cmd_kg_extract,
    cmd_kg_reject,
    cmd_kg_review,
)
from swampcastle.cli.commands.ops import (
    cmd_armory,
    cmd_garrison,
    cmd_ni,
    cmd_parley,
    cmd_raise,
)
from swampcastle.cli.commands.query import (
    cmd_brief,
    cmd_curation_check,
    cmd_derived_rebuild,
    cmd_herald,
    cmd_seek,
    cmd_survey,
)
from swampcastle.cli.commands.write import (
    _scan_deskeleton_targets,
    cmd_cleave,
    cmd_deskeleton,
    cmd_distill,
    cmd_gather,
    cmd_project,
    cmd_reforge,
)

__all__ = [
    # Shared
    "DESKELETON_BATCH_SIZE",
    "DeskeletonTargetStore",
    "_print_kv",
    "_print_progress",
    "_print_section",
    "_settings",
    # Query
    "cmd_brief",
    "cmd_curation_check",
    "cmd_derived_rebuild",
    "cmd_herald",
    "cmd_seek",
    "cmd_survey",
    # Write
    "cmd_cleave",
    "cmd_deskeleton",
    "cmd_distill",
    "cmd_gather",
    "cmd_project",
    "cmd_reforge",
    # KG
    "cmd_kg_accept",
    "cmd_kg_extract",
    "cmd_kg_reject",
    "cmd_kg_review",
    # Config
    "cmd_drawbridge_run",
    "cmd_drawbridge_setup",
    "cmd_tune",
    "cmd_wizard",
    # Ops
    "cmd_armory",
    "cmd_garrison",
    "cmd_ni",
    "cmd_parley",
    "cmd_raise",
    # Internal
    "cmd_hook",
    "cmd_instructions",
]

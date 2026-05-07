"""Internal source adapters for SwampCastle mining."""

from .base import (
    BaseSourceAdapter,
    ConversationSourceItem,
    ConversationSourceResult,
    ProjectSourceItem,
    ProjectSourceResult,
    SourceItem,
)
from .conversation_exports import ConversationExportsAdapter
from .project_files import ProjectFilesAdapter

__all__ = [
    "BaseSourceAdapter",
    "ConversationExportsAdapter",
    "ConversationSourceItem",
    "ConversationSourceResult",
    "ProjectFilesAdapter",
    "ProjectSourceItem",
    "ProjectSourceResult",
    "SourceItem",
]

"""Vault service subpackage."""

from swampcastle.services.vault.models import DiaryReadQuery, GCCollectResult
from swampcastle.services.vault.service import VaultService

__all__ = [
    "DiaryReadQuery",
    "GCCollectResult",
    "VaultService",
]

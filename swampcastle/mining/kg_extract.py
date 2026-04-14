"""Helpers for optional KG proposal extraction during ingest."""

from __future__ import annotations

from swampcastle.services.kg_proposals import KGProposalService
from swampcastle.settings import CastleSettings
from swampcastle.storage import StorageFactory
from swampcastle.wal import WalWriter


def persist_kg_proposals_for_wing(
    *,
    palace_path: str,
    storage_factory: StorageFactory,
    collection,
    wing: str,
) -> int:
    """Extract and persist candidate triples for one wing after ingest.

    This is proposal-only extraction. It never writes accepted KG facts.
    The proposal storage layer is idempotent, so rerunning extraction on the
    same wing updates or preserves existing proposals rather than duplicating
    them.
    """
    settings = CastleSettings(castle_path=palace_path, _env_file=None)
    service = KGProposalService(
        storage_factory.open_graph(), collection, WalWriter(settings.wal_path)
    )
    return len(service.extract_from_drawers(wing=wing, dry_run=False))

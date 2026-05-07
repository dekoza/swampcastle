"""AuditService — read-only access to audit-overlay artifacts."""

from __future__ import annotations

from pathlib import Path

from swampcastle.audit.curation import (
    list_wing_notes,
    load_alias_curation,
    load_tunnel_curation,
    load_wing_note,
)
from swampcastle.audit.derived import load_catalog_cards
from swampcastle.audit.origin import load_origin_manifest, origin_manifest_path
from swampcastle.models.audit import (
    CatalogCardsResponse,
    CurationResponse,
    OriginLookupResponse,
)
from swampcastle.storage.base import CollectionStore


class AuditService:
    def __init__(self, collection: CollectionStore, castle_path: str):
        self._col = collection
        self._castle_path = castle_path

    def _resolve_origin_id_for_source_file(self, source_file: str) -> str | None:
        resolved = str(Path(source_file).expanduser().resolve())
        rows = self._col.get(where={"source_file": resolved}, limit=1, include=["metadatas"])
        if not rows.get("metadatas"):
            return None
        return rows["metadatas"][0].get("origin_id")

    def get_origin(
        self, *, origin_id: str | None = None, source_file: str | None = None
    ) -> OriginLookupResponse:
        if origin_id is not None:
            origin = load_origin_manifest(self._castle_path, origin_id)
            if origin is None:
                return OriginLookupResponse(
                    found=False,
                    resolved_by="origin_id",
                    path=str(origin_manifest_path(self._castle_path, origin_id)),
                )
            return OriginLookupResponse(
                found=True,
                resolved_by="origin_id",
                path=str(origin_manifest_path(self._castle_path, origin_id)),
                origin=origin,
            )

        assert source_file is not None
        resolved = str(Path(source_file).expanduser().resolve())
        resolved_origin_id = self._resolve_origin_id_for_source_file(resolved)
        if resolved_origin_id is None:
            return OriginLookupResponse(
                found=False,
                resolved_by="source_file",
                error=f"No stored drawer metadata found for {resolved}",
            )

        origin = load_origin_manifest(self._castle_path, resolved_origin_id)
        if origin is None:
            return OriginLookupResponse(
                found=False,
                resolved_by="source_file",
                path=str(origin_manifest_path(self._castle_path, resolved_origin_id)),
                error=f"Origin manifest {resolved_origin_id} is missing",
            )

        return OriginLookupResponse(
            found=True,
            resolved_by="source_file",
            path=str(origin_manifest_path(self._castle_path, resolved_origin_id)),
            origin=origin,
        )

    def get_curation(self, *, wing: str | None = None) -> CurationResponse:
        aliases = load_alias_curation(self._castle_path)
        tunnels = load_tunnel_curation(self._castle_path)
        notes = list_wing_notes(self._castle_path)
        wing_note = load_wing_note(self._castle_path, wing) if wing else None

        return CurationResponse(
            aliases=aliases.model_dump(),
            tunnels=tunnels.model_dump(),
            available_wing_notes=[note.wing for note in notes],
            wing_note=wing_note.model_dump() if wing_note is not None else None,
        )

    def list_catalog_cards(self, *, wing: str) -> CatalogCardsResponse:
        cards = load_catalog_cards(self._castle_path, wing)
        path = (
            Path(self._castle_path).expanduser().resolve()
            / ".swampcastle"
            / "derived"
            / "catalog"
            / f"{wing}.jsonl"
        )
        return CatalogCardsResponse(
            wing=wing,
            cards=cards,
            path=str(path),
        )

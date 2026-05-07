"""Internal adapter for conversation-export ingest."""

from __future__ import annotations


from .base import BaseSourceAdapter, ConversationSourceItem, ConversationSourceResult


class ConversationExportsAdapter(BaseSourceAdapter):
    name = "conversation_exports"
    declared_transformations = (
        "jsonl_normalize",
        "json_normalize",
    )

    def scan(self, *, limit: int = 0) -> list[ConversationSourceItem]:
        from swampcastle.mining.convo import scan_convos

        paths = scan_convos(str(self.source_path))
        if limit > 0:
            paths = paths[:limit]
        return [ConversationSourceItem(path=path) for path in paths]

    def ingest(
        self,
        item: ConversationSourceItem,
        **kwargs,
    ) -> ConversationSourceResult | None:
        from swampcastle.mining.convo import _analyze_convo_file, _source_mtime

        analysis = _analyze_convo_file(filepath=item.path, **kwargs)
        if analysis is None:
            return None

        return ConversationSourceResult(
            filepath=item.path,
            chunks=analysis["chunks"],
            room=analysis["room"],
            contributor=analysis["contributor"],
            origin=analysis["origin"],
            source_mtime=_source_mtime(str(item.path)),
        )

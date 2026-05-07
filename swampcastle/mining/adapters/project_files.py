"""Internal adapter for project-file ingest."""

from __future__ import annotations

from pathlib import Path

from .base import BaseSourceAdapter, ProjectSourceItem, ProjectSourceResult


class ProjectFilesAdapter(BaseSourceAdapter):
    name = "project_files"
    declared_transformations: tuple[str, ...] = ()

    def __init__(
        self,
        source_path: str | Path,
        *,
        respect_gitignore: bool = True,
        include_ignored: list[str] | None = None,
        only_force_included: bool = False,
    ):
        super().__init__(source_path)
        self._respect_gitignore = respect_gitignore
        self._include_ignored = include_ignored
        self._only_force_included = only_force_included

    def scan(self, *, limit: int = 0) -> list[ProjectSourceItem]:
        from swampcastle.mining.miner import scan_project

        paths = scan_project(
            str(self.source_path),
            respect_gitignore=self._respect_gitignore,
            include_ignored=self._include_ignored,
            only_force_included=self._only_force_included,
        )
        if limit > 0:
            paths = paths[:limit]
        return [ProjectSourceItem(path=path) for path in paths]

    def ingest(self, item: ProjectSourceItem, **kwargs) -> ProjectSourceResult:
        from swampcastle.mining.miner import process_file

        drawers, room = process_file(filepath=item.path, project_path=self.source_path, **kwargs)
        return ProjectSourceResult(drawers=drawers, room=room)

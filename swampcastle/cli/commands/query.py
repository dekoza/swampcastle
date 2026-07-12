"""CLI query / read command handlers: survey, curation-check, derived-rebuild, seek, herald, brief."""

from swampcastle.cli.commands.shared import _print_kv, _print_section, _settings


def cmd_survey(args):
    from swampcastle.castle import Castle
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        wings = castle.catalog.list_wings().wings
        rooms = castle.catalog.list_rooms().rooms
        _print_section("Survey")
        _print_kv("Drawers", sum(wings.values()))
        if wings:
            _print_kv("Wings", ", ".join(sorted(wings.keys())))
        if rooms:
            _print_kv("Rooms", ", ".join(sorted(rooms.keys())))


def cmd_curation_check(args):
    from swampcastle.audit.curation import (
        list_wing_notes,
        load_alias_curation,
        load_tunnel_curation,
        load_wing_note,
    )

    settings = _settings(args)
    castle_path = str(settings.castle_path)

    try:
        aliases = load_alias_curation(castle_path)
        tunnels = load_tunnel_curation(castle_path)
        note = load_wing_note(castle_path, args.wing) if getattr(args, "wing", None) else None
        notes = [note] if note is not None else list_wing_notes(castle_path)
    except ValueError as exc:
        print(f"  Error: {exc}")
        raise SystemExit(2) from exc

    _print_section("Curation")
    _print_kv("Castle", castle_path)
    _print_kv("Persona aliases", len(aliases.personas))
    _print_kv("People aliases", len(aliases.people))
    _print_kv("Project aliases", len(aliases.projects))
    _print_kv("Wing hints", len(aliases.wing_hints))
    _print_kv("Allowed tunnels", len(tunnels.allow))
    _print_kv("Denied tunnels", len(tunnels.deny))
    _print_kv("Boosted tunnels", len(tunnels.boost))

    if not notes:
        return

    for wing_note in notes:
        _print_kv("Wing note", wing_note.wing)
        for section, entries in wing_note.sections.items():
            _print_kv(section, len(entries))


def cmd_derived_rebuild(args):
    from swampcastle.audit.derived import rebuild_catalog
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)
    factory = factory_from_settings(settings)
    try:
        collection = factory.open_collection(settings.collection_name)
        summary = rebuild_catalog(
            collection, settings.castle_path, wing=getattr(args, "wing", None)
        )
    finally:
        factory.close()

    _print_section("Derived")
    _print_kv("Castle", settings.castle_path)
    if getattr(args, "wing", None):
        _print_kv("Wing filter", args.wing)
    _print_kv("Wings rebuilt", summary["wings_rebuilt"])
    _print_kv("Cards written", summary["cards_written"])
    if summary["wings"]:
        for wing, count in sorted(summary["wings"].items()):
            _print_kv(f"Catalog[{wing}]", count)


def _coerce_search_response(result, query: str):
    from swampcastle.models import SearchHit, SearchResponse

    if isinstance(result, SearchResponse):
        return result

    raw_hits = []
    for hit in getattr(result, "results", []):
        if isinstance(hit, SearchHit):
            raw_hits.append(hit)
        elif hasattr(hit, "__dict__"):
            raw_hits.append(SearchHit.model_validate(vars(hit)))
        else:
            raw_hits.append(SearchHit.model_validate(hit))

    return SearchResponse(
        query=getattr(result, "query", query),
        results=raw_hits,
        filters=getattr(
            result,
            "filters",
            {"wing": None, "room": None, "contributor": None},
        ),
        query_sanitized=getattr(result, "query_sanitized", False),
        sanitizer=getattr(result, "sanitizer", None),
    )


def cmd_seek(args):
    from swampcastle.castle import Castle
    from swampcastle.models import SearchQuery
    from swampcastle.audit.derived import write_search_trace
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)
    search_query = SearchQuery(
        query=args.query,
        wing=args.wing,
        room=args.room,
        contributor=getattr(args, "contributor", None),
        limit=args.results,
        lexical_rerank=getattr(args, "lexical_rerank", False),
        hybrid=getattr(args, "hybrid", False),
        explain=getattr(args, "explain", False) or getattr(args, "write_trace", False),
    )
    with Castle(settings, factory_from_settings(settings)) as castle:
        result = _coerce_search_response(castle.search.search(search_query), args.query)
        _print_section("Seek")
        _print_kv("Query", args.query or "")
        if args.wing:
            _print_kv("Wing", args.wing)
        if args.room:
            _print_kv("Room", args.room)
        if getattr(args, "contributor", None):
            _print_kv("Contributor", args.contributor)
        if getattr(args, "lexical_rerank", False):
            _print_kv("Lexical rerank", "yes")
        if getattr(args, "hybrid", False):
            _print_kv("Hybrid", "yes")
        if getattr(args, "explain", False):
            _print_kv("Explain", "yes")
        if not result.results:
            if getattr(args, "write_trace", False):
                trace_path = write_search_trace(settings.castle_path, search_query, result)
                _print_kv("Trace", trace_path)
            print("  No results found.")
            return
        _print_kv("Results", len(result.results))
        for i, hit in enumerate(result.results, 1):
            label = f"\n  [{i}] {hit.wing} / {hit.room}"
            if getattr(hit, "contributor", None):
                label += f" by {hit.contributor}"
            label += f"  (match: {hit.similarity})"
            print(label)
            print(f"      {hit.text[:200]}")
            if getattr(args, "explain", False):
                matched_via = getattr(hit, "matched_via", None)
                if matched_via:
                    print(f"      matched via: {matched_via}")
                dense_similarity = getattr(hit, "dense_similarity", None)
                if dense_similarity is not None:
                    print(f"      dense: {dense_similarity}")
                lexical_score = getattr(hit, "lexical_score", None)
                if lexical_score is not None:
                    print(f"      lexical: {lexical_score}")
                boosts = getattr(hit, "boosts", None) or []
                if boosts:
                    print(f"      boosts: {', '.join(boosts)}")
                origin_id = getattr(hit, "origin_id", None)
                if origin_id:
                    print(f"      origin: {origin_id}")
                source_kind = getattr(hit, "source_kind", None)
                source_platform = getattr(hit, "source_platform", None)
                if source_kind or source_platform:
                    source_bits = [bit for bit in (source_kind, source_platform) if bit]
                    print(f"      source: {' / '.join(source_bits)}")
        if getattr(args, "write_trace", False):
            trace_path = write_search_trace(settings.castle_path, search_query, result)
            _print_kv("Trace", trace_path)


def cmd_herald(args):
    """Print the stable SwampCastle protocol for agent wake-up."""
    from swampcastle.mcp.protocol import SERVER_INSTRUCTIONS

    print(SERVER_INSTRUCTIONS)


def cmd_brief(args):
    """Print a wing-scoped briefing for prompt/context injection."""
    from swampcastle.castle import Castle
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        brief = castle.catalog.brief(args.wing)

    _print_section("Brief")
    _print_kv("Wing", brief.wing)
    _print_kv("Drawers", brief.total_drawers)
    _print_kv("Files", brief.source_files)

    if brief.error:
        _print_kv("Warning", brief.error)

    if brief.total_drawers == 0:
        print("  No drawers found for that wing.")
        return

    rooms = ", ".join(
        f"{name} ({count})"
        for name, count in sorted(brief.rooms.items(), key=lambda item: (-item[1], item[0]))
    )
    _print_kv("Rooms", rooms)

    if brief.contributors:
        contributors = ", ".join(
            f"{name} ({count})"
            for name, count in sorted(
                brief.contributors.items(), key=lambda item: (-item[1], item[0])
            )
        )
        _print_kv("Contributors", contributors)

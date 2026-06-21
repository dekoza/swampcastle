"""CLI KG candidate command handlers: extract, review, accept, reject."""

import sys

from swampcastle.cli.commands.shared import _print_kv, _print_section, _settings
from swampcastle.models import CandidateReviewCommand, CandidateTripleFilter


def cmd_kg_extract(args):
    from swampcastle.castle import Castle
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)
    effective_dry_run = args.dry_run or not getattr(args, "apply", False)

    with Castle(settings, factory_from_settings(settings)) as castle:
        candidates = castle.kg_proposals.extract_from_drawers(
            wing=args.wing,
            room=args.room,
            dry_run=effective_dry_run,
            limit=args.limit,
        )

    if not candidates:
        print("  No candidate triples extracted.")
        return

    if effective_dry_run:
        print(f"  DRY RUN — would extract {len(candidates)} candidate triples.")
        if not args.dry_run and not getattr(args, "apply", False):
            print("  Preview mode is the default. Re-run with --apply to persist proposals.")
    else:
        print(f"  Extracted {len(candidates)} candidate triples.")

    for candidate in candidates[:10]:
        print(
            f"  {candidate.subject_text} --{candidate.predicate}--> {candidate.object_text} "
            f"[{candidate.modality}, conf={candidate.confidence:.2f}]"
        )
    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more")


def cmd_kg_review(args):
    from swampcastle.castle import Castle
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        proposals = castle.kg_proposals.list_proposals(
            CandidateTripleFilter(
                status=args.status,
                predicate=args.predicate,
                min_confidence=args.min_confidence,
                wing=args.wing,
                room=args.room,
                limit=args.limit,
                offset=args.offset,
            )
        )

    if getattr(args, "conflicts_only", False):
        proposals = [proposal for proposal in proposals if getattr(proposal, "conflicts_with", [])]

    if not proposals:
        print("  No candidate triples.")
        return

    _print_section("KG Review")
    _print_kv("Candidates", len(proposals))
    for candidate in proposals:
        line = (
            f"\n  {candidate.candidate_id}  [{candidate.status}]  {candidate.subject_text}"
            f" --{candidate.predicate}--> {candidate.object_text}  conf={candidate.confidence:.2f}"
        )
        if getattr(candidate, "conflicts_with", None):
            conflicts = ", ".join(candidate.conflicts_with)
            line += f"  [CONFLICT with: {conflicts}]"
        print(line)


def cmd_kg_accept(args):
    from swampcastle.castle import Castle
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        result = castle.kg_proposals.accept(
            CandidateReviewCommand(
                candidate_id=args.candidate_id,
                action=(
                    "accept_and_invalidate_conflict"
                    if getattr(args, "invalidate_conflicts", False)
                    else "accept"
                ),
                subject_text=args.subject,
                predicate=args.predicate,
                object_text=args.object,
                valid_from=args.valid_from,
                valid_to=args.valid_to,
            )
        )

    if not result.success:
        print(f"  Error: {result.error}")
        sys.exit(1)

    print(f"  Accepted {result.candidate_id} into KG as triple {result.triple_id}.")
    if result.subject_text and result.predicate and result.object_text:
        print(f"  {result.subject_text} --{result.predicate}--> {result.object_text}")
    if result.invalidated_count:
        print(f"  Invalidated {result.invalidated_count} conflicting fact(s).")


def cmd_kg_reject(args):
    from swampcastle.castle import Castle
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        result = castle.kg_proposals.reject(args.candidate_id)

    if not result.success:
        print(f"  Error: {result.error}")
        sys.exit(1)

    print(f"  Rejected {result.candidate_id}.")

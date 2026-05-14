"""Second Brain CLI.

Usage:
  python cli.py reindex          Rebuild the vector index from vault .md files
  python cli.py link             Regenerate tag pages + add Tags/Related sections
                                 to every note in the vault
  python cli.py group "<topic>"  Build a Map of Content (MOC) hub note for a topic.
                                 Searches ChromaDB, asks the active LLM to organize
                                 the matches into categories, writes to 01_Projects/.
  python cli.py status           Show vault path, provider, index size
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.config import settings
from app.services import indexer, linker, moc_builder, runtime_settings
from app.services.llm_providers import list_providers


def cmd_group(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if not topic:
        print("Topic cannot be empty.")
        return 1

    print(f'Building MOC for: "{topic}"')
    print("  searching candidates in ChromaDB...")

    try:
        result = moc_builder.build_moc(topic)
    except RuntimeError as e:
        print(f"Error: {e}")
        print('Hint: configure an API key (or run `python cli.py status` to check).')
        return 1
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    if result.get("skipped_reason"):
        print(f"  {result['skipped_reason']} — nothing written.")
        print("  Hint: run `python cli.py reindex` if your vault was just populated,")
        print("        or try a broader topic description.")
        return 1

    print(f"  considered {result['candidates_considered']} candidates")
    print(f"  organized into {result['categories']} categor"
          f"{'y' if result['categories'] == 1 else 'ies'} "
          f"({result['notes_linked']} notes linked)")
    print()
    print(f"✓ Created: {result['path']}")
    print(f"  Title:   {result['title']}")
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    print(f"Linking vault at: {settings.vault_root}")
    print("  regenerating tag indexes...")
    tag_counts = linker.regenerate_all_tag_indexes()
    print(
        f"    wrote {tag_counts['tag_pages_written']} tag page(s), "
        f"removed {tag_counts['tag_pages_removed']}."
    )
    print("  linking notes (Tags + Related sections)...")
    counts = linker.relink_all_notes(verbose=args.verbose)
    print(
        f"Done. Relinked {counts['relinked']} note(s), updated "
        f"{counts['daily_updated']} daily file(s). Skipped {counts['skipped']}, "
        f"errors {counts['errors']}."
    )
    return 0 if counts["errors"] == 0 else 1


def cmd_reindex(args: argparse.Namespace) -> int:
    print(f"Reindexing vault at: {settings.vault_root}")
    print("(first run downloads the embedding model — this may take a minute)")
    counts = indexer.reindex_vault(log_each=args.verbose)
    print(
        f"Done. Indexed {counts['indexed']} note(s) → {counts['chunks']} chunks. "
        f"Skipped {counts['skipped']}, errors {counts['errors']}."
    )
    return 0 if counts["errors"] == 0 else 1


def cmd_status(args: argparse.Namespace) -> int:
    print(f"Vault:          {settings.vault_root}")
    print(f"Chroma dir:     {settings.chroma_dir}")
    print(f"Active provider:{settings.active_provider}")
    print()
    print("Providers:")
    for p in list_providers():
        flag = "✓" if p["configured"] else " "
        print(f"  [{flag}] {p['name']:<10} {p['display']:<24} model={p['model']}")
    try:
        coll = indexer._coll()
        try:
            count = coll.count()
        except Exception:
            count = "unknown"
        print(f"\nIndex chunks:   {count}")
    except Exception as e:
        print(f"\nIndex:          (not initialized — {e})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cli", description="Second Brain command-line tools")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_reindex = sub.add_parser("reindex", help="Rebuild the vector index from vault files")
    p_reindex.add_argument("-v", "--verbose", action="store_true", help="Log each indexed file")
    p_reindex.set_defaults(func=cmd_reindex)

    p_link = sub.add_parser(
        "link",
        help="Regenerate tag pages and add Tags/Related sections to every note",
    )
    p_link.add_argument("-v", "--verbose", action="store_true", help="Log each linked file")
    p_link.set_defaults(func=cmd_link)

    p_group = sub.add_parser(
        "group",
        help='Build a Map of Content (MOC) hub note for a topic, e.g. group "startup work - X, Y, Z"',
    )
    p_group.add_argument(
        "topic",
        help='Topic description. Comma- and dash-separated terms widen the search.',
    )
    p_group.set_defaults(func=cmd_group)

    p_status = sub.add_parser("status", help="Show vault path, provider, index size")
    p_status.set_defaults(func=cmd_status)

    # Apply any persisted runtime overrides before any command runs
    runtime_settings.apply_overrides()

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
                        format="%(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

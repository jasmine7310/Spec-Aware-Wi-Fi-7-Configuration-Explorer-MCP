#!/usr/bin/env python3
"""Freeze the rules, model, harness, pinned versions and pipeline code before the held-out
campaign (issue #114), or check that nothing changed since.

    .venv/bin/python scripts/freeze_versions.py --tag checkpoint3-freeze   # write freeze.json
    .venv/bin/python scripts/freeze_versions.py --check                    # exit 1 if changed

Write freeze.json, commit it, then tag that commit (git tag checkpoint3-freeze), all
before looking at any held-out result. tests/test_freeze.py fails while a committed
freeze.json no longer matches the repo.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import freeze  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tag", help="write freeze.json for this tag name")
    group.add_argument("--check", action="store_true", help="compare freeze.json with the repo")
    args = parser.parse_args()
    if args.tag:
        data = freeze.write(args.tag)
        print(json.dumps({k: data[k] for k in (*freeze.FROZEN_KEYS, "tag", "git_commit")},
                         indent=2))
        print(f"wrote {freeze.FREEZE_JSON.name}; commit it, then: git tag {args.tag}")
        return 0
    if not freeze.FREEZE_JSON.exists():
        print("no freeze.json: nothing is frozen yet")
        return 1
    diffs = freeze.differences(json.loads(freeze.FREEZE_JSON.read_text()))
    for line in diffs:
        print("changed since the freeze:", line)
    print("frozen versions hold" if not diffs else "the held-out campaign must be rerun")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Check that the spec, the rule model and the committed runs agree (issue #76), and
write rules/validation.json (each rule's experimental validation). Nothing is run.

    .venv/bin/python scripts/check_consistency.py

Exits 1 if a check fails; the same checks run in tests/test_consistency.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import consistency as C  # noqa: E402


def main() -> int:
    failed = False
    for check in C.evidence_violations():
        failed = True
        print(f"evidence run breaks {check.rule_ids}, not labeled negative: "
              f"{check.run} ({check.test})")
    for check in C.misplaced_negatives():
        failed = True
        print(f"labeled negative experiment in an evidence folder: {check.run}")
    for check, where in C.cited_violations():
        failed = True
        what = (f"breaks {check.rule_ids}: {check.run} ({check.test})" if check
                else "isn't in any committed run folder")
        print(f"cited run {what}; cited by {', '.join(where)}")

    data = C.write()
    print(f"wrote {C.VALIDATION_JSON.relative_to(C.REPO_ROOT)}: {data['counts']}")
    for entry in data["rules"]:
        if entry["validation"] == "none":
            print(f"  no experimental validation: {entry['id']} ({entry['kind']})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

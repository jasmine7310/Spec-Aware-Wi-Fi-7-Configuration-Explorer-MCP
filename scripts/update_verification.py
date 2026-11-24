#!/usr/bin/env python3
"""Regenerate final_verification.csv (issue #116): the runs verifying each anchor family
and each side of c1-c3, and whether they ran on the frozen versions.

    .venv/bin/python scripts/update_verification.py

Rerun it after committing runs, after #114 commits freeze.json, or after changing docker/;
tests/test_verification.py fails while the file is stale.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import verification  # noqa: E402


def main() -> int:
    verification.write()
    rows = verification.rows()
    print(f"wrote {verification.VERIFICATION_CSV.name}: {len(rows)} rows "
          f"({rows[0]['reference'] if rows else 'empty'})")
    for status, n in sorted(Counter(r["status"] for r in rows).items()):
        print(f"  {status}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

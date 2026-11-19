#!/usr/bin/env python3
"""Recompute anchor_coverage.csv's campaign_runs and campaign_observed columns (issue #77)
from the committed accepted adapter runs. Nothing is run.

    .venv/bin/python scripts/update_anchor_coverage.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import anchors  # noqa: E402


def main() -> int:
    anchors.write()
    _, data = anchors.rows()
    for row in data:
        print(f"{row['family_id']} {row['name']}: {row['campaign_runs'].split(':')[0] or '0 runs'}")
        print(f"    {row['campaign_observed']}")
    print(f"wrote {anchors.ANCHOR_CSV.relative_to(anchors.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

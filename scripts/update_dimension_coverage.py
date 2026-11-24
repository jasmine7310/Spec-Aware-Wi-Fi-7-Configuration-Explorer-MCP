#!/usr/bin/env python3
"""Regenerate dimension_coverage.csv (issue #110): for every admitted dimension value in
model.json, its smoke run and the committed accepted campaign and contrast runs with that
value. Nothing is run.

    .venv/bin/python scripts/update_dimension_coverage.py
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import dimension_coverage as dc  # noqa: E402


def main() -> int:
    dc.write()
    data = dc.rows()
    for row in data:
        print(f"{row['dimension']:26} {row['value']:12} {row['status']:10} smoke {row['smoke_run']} "
              f"({row['smoke_result']}); campaign {row['campaign_runs'].split(':')[0]}; "
              f"contrast {row['contrast_runs'].split(':')[0]}; "
              f"today's harness {row['current_harness_runs']}")
    print(dict(Counter(row["status"] for row in data)))
    print(f"wrote {dc.DIMENSION_CSV.relative_to(dc.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

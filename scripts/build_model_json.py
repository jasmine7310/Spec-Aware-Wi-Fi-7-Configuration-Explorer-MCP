#!/usr/bin/env python3
"""Regenerate model.json at the repo root from explorer.model_json.build() (issue #65).

    .venv/bin/python scripts/build_model_json.py           # write model.json
    .venv/bin/python scripts/build_model_json.py --check   # exit 1 if it's out of date

Run it after changing the P0 model, rules.yaml, surface_candidates.csv's smoke_runs, the
adapter's supported actions or the pinned versions; tests/test_model_json.py fails until
you do.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import model_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="don't write; exit 1 if model.json differs from what it would be")
    args = parser.parse_args()
    path = model_json.MODEL_JSON
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != model_json.render():
            print(f"{path.name} is out of date; run scripts/build_model_json.py", file=sys.stderr)
            return 1
        print(f"{path.name} is up to date ({model_json.build()['model_digest']})")
        return 0
    model_json.write()
    model = model_json.build()
    print(f"wrote {path.name}: {len(model['dimensions'])} dimensions, "
          f"{len(model['constraints'])} constraints, {model['model_digest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Find accepted-vs-accepted contrasts (issue #71) among the committed adapter runs
(campaigns/ and contrasts/runs/) and write contrasts/contrasts.json. Nothing is run.

    .venv/bin/python scripts/find_contrasts.py                 # pairs 1 input apart
    .venv/bin/python scripts/find_contrasts.py --max-inputs 2
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import contrasts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-inputs", type=int, default=contrasts.DEFAULT_MAX_INPUTS,
                        help="most differing inputs per pair (default %(default)s)")
    args = parser.parse_args()
    data = contrasts.write(args.max_inputs)
    print(f"{data['accepted_runs']} accepted runs, {data['candidates']} candidates, "
          f"{len(data['contrasts'])} contrasts within {args.max_inputs} input(s)")
    for c in data["contrasts"]:
        print(f"  {'+'.join(c['a_runs'])} vs {'+'.join(c['b_runs'])}: "
              f"{sorted(c['input_diff'])} -> {[f['fact'] for f in c['facts']]}"
              f"{' (reproduced)' if c['reproduced'] else ''}")
    print(f"wrote {contrasts.CONTRASTS_JSON.relative_to(contrasts.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

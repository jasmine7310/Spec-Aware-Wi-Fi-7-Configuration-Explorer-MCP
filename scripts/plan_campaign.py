#!/usr/bin/env python3
"""Plan a bounded pairwise campaign (issue #66) and write campaign_plan.json and
pairwise_coverage.json at the repo root. Nothing is run; #68 runs the plan.

    .venv/bin/python scripts/plan_campaign.py                 # seed 0, budget 20
    .venv/bin/python scripts/plan_campaign.py --seed 7 --budget 16

The same seed always gives the same plan for the same model.json and evidence.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import planner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--budget", type=int, default=planner.DEFAULT_BUDGET,
                        help="most candidates to plan (default %(default)s)")
    args = parser.parse_args()
    campaign, cover = planner.write(args.seed, args.budget)
    funnel = campaign["funnel"]
    print(f"enumerated {funnel['enumerated']} -> P0 {funnel['p0_well_formed']} -> "
          f"P1 {funnel['p1']} -> executable {funnel['executable']} "
          f"(P2 {funnel['p2']}) -> planned {funnel['planned']} "
          f"({funnel['allpairspy_rows']} allpairspy + {funnel['top_up_rows']} top-up, "
          f"{funnel['cut_by_budget']} cut by the budget)")
    for name in ("modeled_admissible", "executable"):
        block = cover[name]
        print(f"{name}: {block['feasible_pairs']} feasible pairs, planned "
              f"{block['planned_feasible_pairs']} ({block['planned_pairwise_coverage']}), "
              f"covered by runs so far {block['covered_feasible_pairs']} "
              f"({block['pairwise_coverage']})")
    print(f"{len(cover['infeasible_pairs'])} infeasible pairs; "
          f"review queue {len(campaign['review_queue'])}")
    print(f"wrote {planner.CAMPAIGN_PLAN.name} and {planner.PAIRWISE_COVERAGE.name} "
          f"(seed {args.seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

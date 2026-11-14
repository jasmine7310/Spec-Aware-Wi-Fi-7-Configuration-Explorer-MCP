#!/usr/bin/env python3
"""Run the planned campaign (issue #68): every candidate in campaign_plan.json, each in
a fresh UML guest through the experiment cache. Writes campaigns/<id>/ (run folders,
results.json, rejected_cases.csv) and pruning_counts.json.

    .venv/bin/python scripts/run_campaign.py                     # id: seed<seed>-<UTC date>
    .venv/bin/python scripts/run_campaign.py --id seed0-rerun --retries 1

Needs Docker and the wifi7-env image (scripts/build-env.sh). Afterwards regenerate the
plan files so coverage counts the new runs: scripts/plan_campaign.py --seed <seed>.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import campaign, planner  # noqa: E402
from explorer.cache import Cache  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--id", help="campaign id (default: seed<seed>-<UTC date>)")
    parser.add_argument("--retries", type=int, default=1,
                        help="reruns after SETUP_FAIL / TIMEOUT (default %(default)s)")
    args = parser.parse_args()
    plan = json.loads(planner.CAMPAIGN_PLAN.read_text())
    campaign_id = args.id or f"seed{plan['seed']}-{datetime.now(timezone.utc):%Y-%m-%d}"
    cache = Cache()
    indexed = cache.rebuild()
    print(f"campaign {campaign_id}: {len(plan['candidates'])} planned candidates "
          f"(cache: {indexed} committed runs indexed)", flush=True)

    def report(candidate, cache_, **kwargs):
        from explorer.cache import run_cached
        outcome, ran = run_cached(candidate, cache_, **kwargs)
        ctx = kwargs.get("context", {})
        print(f"  {ctx.get('candidate_id')} attempt {ctx.get('attempt')}: {outcome.status:10} "
              f"run {outcome.run_id}{' (cache hit)' if ran is None else ''}"
              f"{' - ' + outcome.reason if outcome.reason else ''}", flush=True)
        return outcome, ran

    results = campaign.run(plan, campaign_id, cache=cache, retries=args.retries, runner=report)
    space = planner.Space()
    counts = campaign.pruning_counts(plan, results)
    rejected = campaign.rejected_cases(plan, results, space)
    campaign.write(campaign.CAMPAIGNS / campaign_id, plan, results, rejected, counts)
    print(f"P3: {counts['P3']}; guest boots {counts['executed']['guest_boots']}, "
          f"cache hits {counts['executed']['cache_hits']}, retries {counts['executed']['retries']}")
    print(f"wrote campaigns/{campaign_id}/ and {campaign.PRUNING_COUNTS.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

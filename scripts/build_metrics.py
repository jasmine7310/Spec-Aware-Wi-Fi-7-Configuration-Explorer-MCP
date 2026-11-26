#!/usr/bin/env python3
"""Write metrics.json: the evaluation metrics (issue #115), from committed files.
Nothing boots; takes a few seconds (the timing block times every check over the space).

    .venv/bin/python scripts/build_metrics.py

Rerun after committing runs, a campaign (e.g. #114's held-out one) or a change to the
rules, the model, the audit or the counterexample suite; tests/test_metrics.py fails
until you do.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import metrics  # noqa: E402


def main() -> int:
    data = metrics.write()
    space, est = data["space"], data["no_p1_estimate"]
    avoided = space["guest_boots_avoided"]
    print(f"space: {space['enumerated']} enumerated -> {space['p2']['executable']} executable; "
          f"{avoided['total']} boots avoided ({avoided['share_of_enumerated']:.1%}): "
          f"P0 {avoided['by_p0']}, P1 {avoided['by_p1']}, P2 {avoided['by_p2']}")
    print(f"no-P1 estimate: budget {est['budget']}, {est['expected_wasted_boots']} expected "
          f"wasted boots (sample: {est['sample']['p1_rejected']} P1-rejected)")
    for c in data["campaigns"]:
        echo = c["station_status_echo"]
        print(f"campaign {c['id']}: {c['guest_boots']} boots, {c['cache_hits']} cache hits, "
              f"{c['distinct_signatures']} distinct signatures of {c['accepted_runs']} "
              f"accepted ({echo['distinct_signatures_without_it']} without the "
              f"station_status echo), {c['wall_clock_s']:.0f} s")
    suite = data["counterexamples"]
    print(f"counterexamples: {suite['invalid_caught_at_expected_stage']}/"
          f"{suite['invalid_cases']} invalid caught, "
          f"{len(suite['permitted_wrongly_pruned'])}/{suite['permitted_cases']} permitted "
          f"wrongly pruned")
    timing = data["timing"]
    print(f"checker: {timing['ms_per_assignment_reaching_p2']} ms for an assignment through "
          f"every stage, {timing['ms_per_assignment_over_space']} ms averaged over the space "
          f"({timing['machine']['platform']})")
    print(f"held-out: {data['held_out']['campaign'] or 'none yet'}")
    print(f"wrote {metrics.METRICS_JSON.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

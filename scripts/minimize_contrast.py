#!/usr/bin/env python3
"""Minimize one accepted-vs-accepted contrast with real probes, then reproduce its final
sides (issue #73). Needs Docker and a current image (scripts/build-env.sh).

    # 1. Reduce: probes run in fresh guests through the cache, into <out>/probes/
    .venv/bin/python scripts/minimize_contrast.py minimize --a 1794812749 --b 1794557032 \\
        --facts disconnect_reasons --out contrasts/c1
    # 2. Reproduce both final sides 3 times each, into contrasts/runs/
    .venv/bin/python scripts/minimize_contrast.py verify --out contrasts/c1

--a / --b name any committed run of each side (``contrasts.accepted_runs``); the sides
are those runs' groups of repeats. Each --facts must be claimable between the two groups
(measured on both, stable within each, different), and the target is B's value. Both
steps write <out>/reduction.json; the contrast is labeled PENDING_VERIFICATION until
``verify`` shows both sides reproduce, and MINIMIZED only then.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer import contrasts, minimize  # noqa: E402
from explorer.cache import Cache  # noqa: E402

VERIFY_DIR = contrasts.CONTRASTS_DIR / "runs"


def _group(groups, run_id):
    for g in groups:
        if any(r.run_id == run_id for r in g.runs):
            return g
    sys.exit(f"run {run_id} isn't a committed accepted, legal adapter run "
             f"(contrasts.accepted_runs)")


def cmd_minimize(args):
    groups = contrasts.group(contrasts.accepted_runs())
    a, b = _group(groups, args.a), _group(groups, args.b)
    if a.harness != b.harness:
        sys.exit("the two sides ran under different harnesses; pick runs of one harness")
    diffs, unstable = contrasts.compare(a, b)
    claimed = {d.fact: d for d in diffs}
    if missing := [f for f in args.facts if f not in claimed]:
        sys.exit(f"not claimable between these sides: {missing}; claimable: {sorted(claimed)}")
    for side in (a, b):
        if not contrasts.p2_supported(side.candidate):
            sys.exit(f"side of {side.runs[0].run_id} isn't P2 SUPPORTED")
    target = {f: claimed[f].b for f in args.facts}
    out = Path(args.out)
    reduction = minimize.minimize(a.candidate, b.candidate, target, cache=Cache(),
                                  log_dir=out / "probes",
                                  context={"purpose": "issue #73 minimization"})
    data = {
        "description": ("Minimized contrast (issue #73), written by "
                        "scripts/minimize_contrast.py. Probe runs are in probes/; the "
                        "final sides' reproduction runs are in contrasts/runs/."),
        "label": "PENDING_VERIFICATION",
        "contrast": {
            "a_runs": [r.run_id for r in a.runs], "b_runs": [r.run_id for r in b.runs],
            "harness": a.harness,
            "input_diff": contrasts.input_diff(a.candidate, b.candidate),
            "claimed_facts": sorted(claimed), "unstable": unstable,
        },
        "target_facts": args.facts,
        "reduction": reduction.model_dump(mode="json"),
        "verification": None,
    }
    _write(out, data)
    print(f"{reduction.status}: minimal {[reduction.deltas[i].label for i in reduction.minimal]}"
          f"; {len(reduction.trace)} probes {reduction.counts}, {reduction.guest_runs} guest "
          f"runs, {reduction.cache_hits} cache hits")


def cmd_verify(args):
    out = Path(args.out)
    data = json.loads((out / "reduction.json").read_text())
    reduction = minimize.Reduction.model_validate(data["reduction"])
    verification = minimize.verify(reduction, args.runs, log_dir=VERIFY_DIR,
                                   context={"purpose": "issue #73 reproduction"})
    data["verification"] = verification.model_dump(mode="json")
    data["label"] = verification.label
    _write(out, data)
    for side in ("baseline", "minimal"):
        print(side, [(r.run_id, r.status, r.matches_target)
                     for r in getattr(verification, side)])
    print(verification.label, "-", verification.note)


def _write(out: Path, data: dict):
    out.mkdir(parents=True, exist_ok=True)
    (out / "reduction.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out / 'reduction.json'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("minimize", help="reduce the contrast with real probes")
    m.add_argument("--a", required=True, help="a run ID of side A (the side the probes start from)")
    m.add_argument("--b", required=True, help="a run ID of side B (whose facts are the target)")
    m.add_argument("--facts", required=True, nargs="+", help="target facts (behavior facts)")
    m.add_argument("--out", required=True, help="output folder, e.g. contrasts/c1")
    m.set_defaults(func=cmd_minimize)
    v = sub.add_parser("verify", help="reproduce both final sides in fresh guests")
    v.add_argument("--out", required=True)
    v.add_argument("--runs", type=int, default=contrasts.REPRODUCE_RUNS)
    v.set_defaults(func=cmd_verify)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

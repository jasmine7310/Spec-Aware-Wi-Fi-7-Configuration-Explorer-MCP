#!/usr/bin/env python3
"""Run each rule-passing hostap scenario through the candidate adapter (issue #79) and
compare its behavior record with that test's committed runs.

    .venv/bin/python scripts/reproduce-scenarios.py [--log-dir runs/hwsim-logs] [test ...]

For each scenario: the adapter run's P3 status and run ID, then every fact that differs
from the committed run, limited to facts both observed (explorer.adapter.compare_signatures).
Expected differences come from what hostap's tests do outside our model (e.g. the OWE
tests also connect a legacy client, dev[0]); they're listed, never hidden.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explorer.adapter import comparable_signature, compare_signatures, run_candidate  # noqa: E402
from explorer.runner import DEFAULT_LOG_DIR  # noqa: E402
from explorer.scenarios import TEST_CANDIDATES  # noqa: E402
from explorer.signatures import extract_record  # noqa: E402
from explorer.support import EVIDENCE_DIRS, passing_runs, rule_passing_tests  # noqa: E402


def committed_signature(test: str) -> tuple[str, dict]:
    run_id = sorted(passing_runs()[test])[0]
    run_dir = next(d / run_id for d in EVIDENCE_DIRS if (d / run_id).is_dir())
    return run_id, comparable_signature(extract_record(run_dir, test))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tests", nargs="*", help="default: every rule-passing scenario")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    args = parser.parse_args()
    tests = args.tests or sorted(rule_passing_tests())

    failures = 0
    for test in tests:
        run = run_candidate(TEST_CANDIDATES[test], log_dir=args.log_dir)
        print(f"\n== {test}: {run.status} (adapter run {run.run_id})"
              + (f" - {run.reason}" if run.reason else ""))
        if run.status != "ACCEPTED":
            failures += 1
            continue
        test_run, test_signature = committed_signature(test)
        diffs = compare_signatures(comparable_signature(run.record), test_signature)
        print(f"   compared with committed run {test_run}: "
              + ("no differences in facts both observed" if not diffs else
                 f"{len(diffs)} difference(s)"))
        for fact, (mine, theirs) in diffs.items():
            print(f"   - {fact}: adapter {mine!r}, test {theirs!r}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

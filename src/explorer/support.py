"""P2 support check: can the pinned environment execute this candidate?

Only committed evidence counts:

- ``SUPPORTED``: the candidate is exactly what a hostap test (or one of our
  ``_client_bp`` wrappers) sets up and does, configuration and actions alike, and that
  test has at least one passing committed run. ``run_hwsim_test`` can run it.
- ``UNRESOLVED``: no test executes this exact candidate. The result lists the committed
  runs that show each of its values executes, or none: for the admitted dimensions
  (settings, and the actions in ``PRESENCE_ACTIONS`` as absent / present), the smoke runs
  in ``surface_candidates.csv``'s ``smoke_runs``; for each action (with its command or
  operation), committed adapter runs whose recorded candidate performs it, then passing
  runs of the hostap tests that perform it. Only runs that pass the modeled rules count:
  hostap tests that break one (the plain-SAE baseline, hostap's originals with the
  client's beacon protection off) are negative experiments, and an adapter run counts only
  if its recorded validation is PASSES_MODELED_RULES. Rejected runs (``runs/rejected/``)
  are never read. Values that each ran somewhere don't prove their combination runs.
- ``UNSUPPORTED_IMPLEMENTATION``: needs real evidence that the pinned versions can't do
  it, such as a run that failed to set up. We have none recorded, so nothing returns
  this yet; it is never inferred from missing evidence.

Runs in ``runs/hwsim-logs/`` are trials and never count.
"""

from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from explorer.model import Candidate
from explorer.scenarios import TEST_CANDIDATES

REPO_ROOT = Path(__file__).resolve().parents[2]
# Committed run evidence; runs/hwsim-logs/ holds git-ignored trial runs and is skipped.
EVIDENCE_DIRS = (REPO_ROOT / "runs" / "baseline", REPO_ROOT / "runs" / "calibration",
                 REPO_ROOT / "runs" / "smoke", REPO_ROOT / "runs" / "anchors")
CANDIDATES_CSV = REPO_ROOT / "surface_candidates.csv"

P2Status = Literal["SUPPORTED", "UNRESOLVED", "UNSUPPORTED_IMPLEMENTATION"]

# Actions such as associate appear in every test; list a few runs, not all of them.
MAX_EXAMPLE_RUNS = 3


class ValueEvidence(BaseModel):
    candidate: str
    """A name from surface_candidates.csv, e.g. ap_ptk_rekey_interval or link_remove."""
    value: str
    """The candidate's value in that column's terms, e.g. 'unset', '5', 'present'."""
    run_ids: list[str]
    """Committed runs showing this value executes (up to MAX_EXAMPLE_RUNS for an action);
    empty if there are none."""


class SupportResult(BaseModel):
    status: P2Status
    test: str | None
    """The test that executes this candidate exactly (SUPPORTED only)."""
    run_ids: list[str]
    """That test's passing committed runs (SUPPORTED only)."""
    values: list[ValueEvidence]
    """Per-value run evidence (UNRESOLVED only)."""
    closest_tests: list[str]
    """Tests with this exact configuration but different actions (UNRESOLVED only)."""
    note: str


def passing_runs(evidence_dirs=EVIDENCE_DIRS) -> dict[str, list[str]]:
    """Test name -> IDs of its passing committed runs, from each run's manifest.json."""
    runs: dict[str, list[str]] = {}
    for evidence_dir in evidence_dirs:
        for manifest_path in sorted(Path(evidence_dir).glob("*/manifest.json")):
            manifest = json.loads(manifest_path.read_text())
            for result in manifest["results"]:
                if result["result"] == "PASS":
                    runs.setdefault(result["test"], []).append(manifest["run_id"])
    return runs


@lru_cache(maxsize=1)
def _cached_passing_runs() -> dict[str, list[str]]:
    return passing_runs()


def smoke_evidence(path: Path = CANDIDATES_CSV) -> dict[str, dict[str, str]]:
    """surface_candidates.csv's smoke_runs as {candidate: {value label: run_id}}."""
    with Path(path).open(newline="") as f:
        rows = list(csv.DictReader(f))
    evidence = {}
    for row in rows:
        if row["smoke_runs"]:
            pairs = (entry.strip().split("=", 1) for entry in row["smoke_runs"].split(";"))
            evidence[row["name"]] = {value: run_id for value, run_id in pairs}
    return evidence


@lru_cache(maxsize=1)
def _cached_smoke_evidence() -> dict[str, dict[str, str]]:
    return smoke_evidence()


@lru_cache(maxsize=1)
def rule_passing_tests() -> frozenset[str]:
    """Runnable tests whose config and actions pass the modeled rules (no finding)."""
    # Imported here because explorer.validate imports this module.
    from explorer.validate import (check_action_order, find_undetermined, p1_status,
                                   run_p1_checks)
    return frozenset(
        test for test, known in TEST_CANDIDATES.items()
        if p1_status(run_p1_checks(known.config) + find_undetermined(known.config)
                     + check_action_order(known)) == "PASSES_MODELED_RULES")


def _interval(seconds: int | None) -> str:
    return "unset" if seconds is None else str(seconds)


# hostapd sae_pwe values, as surface_candidates.csv labels them.
_SAE_PWE_LABEL = {None: "unset", "hash_to_element": "1", "both": "2"}

# Actions admitted as absent / present dimensions (docs/dimensions.md); their smoke runs
# are in surface_candidates.csv like a setting's.
PRESENCE_ACTIONS = ("link_remove", "rekey_gtk_now", "disable_enable_mld")


def setting_values(candidate: Candidate) -> list[tuple[str, str]]:
    """The candidate's values for the smoke-tested dimensions, as (csv name, label) pairs
    in surface_candidates.csv's terms: settings, plus the actions in PRESENCE_ACTIONS as
    absent / present."""
    ap, sta = candidate.config.ap, candidate.config.sta
    values = []
    for akm in dict.fromkeys(akm for link in ap.links for akm in link.akms):
        values.append(("ap_akm", akm))
    for akm in sta.akms:
        values.append(("sta_akm", akm))
    values.append(("ap_sae_pwe", _SAE_PWE_LABEL[ap.sae_pwe]))
    for cipher in dict.fromkeys(link.pairwise_cipher for link in ap.links):
        values.append(("ap_pairwise_cipher", cipher))
    values.append(("ap_ptk_rekey_interval", _interval(ap.ptk_rekey_interval_s)))
    values.append(("ap_gtk_rekey_interval", _interval(ap.gtk_rekey_interval_s)))
    for disabled in dict.fromkeys(link.indicate_disabled for link in ap.links):
        values.append(("ap_link_indicate_disabled", "1" if disabled else "0"))
    performed = {step.action for step in candidate.actions}
    for action in PRESENCE_ACTIONS:
        values.append((action, "present" if action in performed else "absent"))
    return values


def adapter_runs(evidence_dirs=EVIDENCE_DIRS) -> dict[str, list[dict]]:
    """Run ID -> the actions of the candidate a committed adapter run carried out.

    Only runs of the adapter test (explorer.adapter) that passed and whose recorded
    validation (``explorer_plan.explorer`` in the manifest) is PASSES_MODELED_RULES:
    a negative experiment or a REJECTED run is never evidence that a value executes."""
    from explorer.adapter import ADAPTER_TEST  # explorer.adapter imports explorer.validate
    found: dict[str, list[dict]] = {}
    for evidence_dir in evidence_dirs:
        for manifest_path in sorted(Path(evidence_dir).glob("*/manifest.json")):
            manifest = json.loads(manifest_path.read_text())
            meta = manifest.get("explorer_plan", {}).get("explorer")
            passed = any(r["test"] == ADAPTER_TEST and r["result"] == "PASS"
                         for r in manifest["results"])
            if (passed and meta and not meta["negative_experiment"]
                    and meta["validation"]["status"] == "PASSES_MODELED_RULES"):
                found[manifest["run_id"]] = meta["candidate"]["actions"]
    return found


@lru_cache(maxsize=1)
def _cached_adapter_runs() -> dict[str, list[dict]]:
    return adapter_runs()


def _key(step: dict) -> tuple[str, str]:
    """action_key() for an action recorded as JSON in a run's manifest."""
    return step["action"], step.get("command") or step.get("operation") or "present"


def action_key(step) -> tuple[str, str]:
    """(action name, its command or operation), e.g. ('sta_disconnect_reconnect',
    'DISCONNECT'); actions without one use 'present'."""
    return step.action, getattr(step, "command", None) or getattr(step, "operation", None) or "present"


def check_support(candidate: Candidate) -> SupportResult:
    """The P2 answer for one candidate (see the module docstring)."""
    runs = _cached_passing_runs()
    supported = [(test, runs[test]) for test, known in TEST_CANDIDATES.items()
                 if known == candidate and runs.get(test)]
    if supported:
        test, run_ids = max(supported, key=lambda pair: len(pair[1]))
        return SupportResult(
            status="SUPPORTED", test=test, run_ids=run_ids, values=[], closest_tests=[],
            note=(f"Executed exactly by hostap test {test}, with {len(run_ids)} passing "
                  f"committed run(s); run it with run_hwsim_test."))

    smoke = _cached_smoke_evidence()
    values = [ValueEvidence(candidate=name, value=label,
                            run_ids=[smoke[name][label]] if label in smoke.get(name, {}) else [])
              for name, label in setting_values(candidate)]
    adapter = _cached_adapter_runs()
    for name, label in dict.fromkeys(action_key(step) for step in candidate.actions):
        if name in PRESENCE_ACTIONS and label == "present":
            continue  # already listed as that dimension's "present" value above
        # Adapter runs first: each shows the action in a legal candidate of its own,
        # where a hostap test's run shows it inside that test's scenario.
        by_adapter = sorted(run for run, actions in adapter.items()
                            if (name, label) in {_key(s) for s in actions})
        performed_by = [test for test, known in TEST_CANDIDATES.items()
                        if test in rule_passing_tests()
                        and (name, label) in {action_key(s) for s in known.actions}]
        by_tests = sorted({run for test in performed_by for run in runs.get(test, [])})
        run_ids = list(dict.fromkeys(by_adapter + by_tests))[:MAX_EXAMPLE_RUNS]
        values.append(ValueEvidence(candidate=name, value=label, run_ids=run_ids))
    closest = sorted(test for test, known in TEST_CANDIDATES.items()
                     if known.config == candidate.config and runs.get(test))
    missing = [f"{v.candidate}={v.value}" for v in values if not v.run_ids]
    note = "No tested hostap scenario executes this exact candidate."
    if closest:
        note += f" {', '.join(closest)} set up this configuration with other actions."
    note += (f" No passing run under the modeled rules for: {', '.join(missing)}."
             if missing else
             " Each listed value has a passing run under the modeled rules, but not in "
             "this combination.")
    return SupportResult(status="UNRESOLVED", test=None, run_ids=[], values=values,
                         closest_tests=closest, note=note)

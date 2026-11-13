"""P2 support check: can the pinned environment execute this candidate?

Only committed evidence counts. The rules below were decided in issue #80
(docs/plan.md, Decisions):

- ``SUPPORTED``: the candidate is exactly what a hostap test (or one of our
  ``_client_bp`` wrappers) sets up and does, configuration and actions alike, and that
  test has at least one passing committed run (``run_hwsim_test`` can run it); or it is
  exactly the candidate of a committed adapter run that passed the modeled rules and was
  ACCEPTED on the pinned hostap and kernel commits under a compatible model schema
  (``model.COMPATIBLE_SCHEMA_VERSIONS``; ``run_candidate`` can run it again). One such run is enough for P2; anchors and
  contrasts need 3/3. The local image ID isn't compared: it changes on every rebuild,
  even from cache.
- ``UNRESOLVED``: no test or adapter run executes this exact candidate. The result lists
  the committed runs that show each of its values executes, or none: for the admitted dimensions
  (settings, and the actions in ``PRESENCE_ACTIONS`` as absent / present), the smoke runs
  in ``surface_candidates.csv``'s ``smoke_runs``; for each action (with its command or
  operation), committed adapter runs whose recorded candidate performs it, then passing
  runs of the hostap tests that perform it. Only runs that pass the modeled rules count:
  hostap tests that break one (the plain-SAE baseline, hostap's originals with the
  client's beacon protection off) are negative experiments, and an adapter run counts only
  if its recorded validation is PASSES_MODELED_RULES and its candidate still passes the
  modeled rules today (re-checked: a rule can be added after a run, as #88 did). Rejected
  runs (``runs/rejected/``) are never evidence. Settings that aren't admitted dimensions (``fixed_values``: AP PMF
  and beacon protection, bss_transition, the client's beacon protection and SAE groups,
  the link layout) count only with a legal committed run that used the same value.
  Values that each ran somewhere don't prove their combination runs.
  ``all_values_evidenced`` says whether every value has such a run: the campaign may run
  those candidates as labeled support probes, and only those. When a value has no run but
  a committed rejected run (``runs/rejected/``) whose candidate still passes the modeled
  rules involves it, ``recorded_refusals`` cites it. A rejected run that a rule now
  explains isn't an implementation refusal, so it isn't cited.
- ``UNSUPPORTED_IMPLEMENTATION``: needs real evidence that the pinned versions can't do
  it, such as a run that failed to set up. We have none recorded, so nothing returns
  this yet; it is never inferred from missing evidence. A refusal caused by a gap in our
  model isn't one: the gap gets modeled instead. ``ap_sae_pwe=1`` with the client's
  ``sae_pwe`` unset (``runs/rejected/1794384673``) was such a gap; since #88 the client's
  ``sae_pwe`` is a dimension and ``SEC.SAE_H2E_ONLY_NEEDS_STA_H2E`` rejects that pairing at P1.

Runs in ``runs/hwsim-logs/`` are trials and never count.
"""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from explorer.model import COMPATIBLE_SCHEMA_VERSIONS, Candidate
from explorer.scenarios import TEST_CANDIDATES

REPO_ROOT = Path(__file__).resolve().parents[2]
# Committed run evidence; runs/hwsim-logs/ holds git-ignored trial runs and is skipped.
# campaigns/ holds committed campaign runs (#68), possibly one folder per campaign, so run
# folders are found at any depth.
EVIDENCE_DIRS = (REPO_ROOT / "runs" / "baseline", REPO_ROOT / "runs" / "calibration",
                 REPO_ROOT / "runs" / "smoke", REPO_ROOT / "runs" / "anchors",
                 REPO_ROOT / "campaigns")
# Committed runs of rule-passing candidates the implementation refused; never evidence.
REJECTED_DIR = REPO_ROOT / "runs" / "rejected"
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
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
    all_values_evidenced: bool
    """True when every value has a passing committed run under the modeled rules (always
    for SUPPORTED). An UNRESOLVED candidate with True is a support probe the campaign may
    run; one with False isn't in the default campaign."""
    recorded_refusals: list[ValueEvidence]
    """Values without a passing run that a committed rejected run (runs/rejected/) involves,
    with those runs. Information only: a refusal never makes a candidate unsupported."""
    note: str


def _manifests(evidence_dirs):
    """Every run manifest under the given folders, at any depth (campaigns/ may nest)."""
    for evidence_dir in evidence_dirs:
        yield from (json.loads(path.read_text())
                    for path in sorted(Path(evidence_dir).rglob("manifest.json")))


def passing_runs(evidence_dirs=EVIDENCE_DIRS) -> dict[str, list[str]]:
    """Test name -> IDs of its passing committed runs, from each run's manifest.json."""
    runs: dict[str, list[str]] = {}
    for manifest in _manifests(evidence_dirs):
        for result in manifest["results"]:
            if result["result"] == "PASS":
                runs.setdefault(result["test"], []).append(manifest["run_id"])
    return runs


@lru_cache(maxsize=1)
def pinned_commits(dockerfile: Path = DOCKERFILE) -> dict[str, str]:
    """The pinned hostap and kernel commits, from the Dockerfile's ARG lines."""
    args = dict(re.findall(r"^ARG (\w+)=(\S+)$", Path(dockerfile).read_text(), re.MULTILINE))
    return {"hostap_commit": args["HOSTAP_COMMIT"], "kernel_commit": args["KERNEL_COMMIT"]}


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


# sae_pwe values (hostapd and wpa_supplicant number them alike), as surface_candidates.csv
# labels them.
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
    values.append(("sta_sae_pwe", _SAE_PWE_LABEL[sta.sae_pwe]))
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


class RecordedRun(BaseModel):
    """What a committed adapter run's manifest records about its candidate."""
    candidate: dict
    """The candidate as JSON (``explorer_plan.explorer.candidate``)."""
    hostap_commit: str | None
    kernel_commit: str | None
    schema_version: int | None


def _recorded(manifest: dict) -> RecordedRun | None:
    meta = manifest.get("explorer_plan", {}).get("explorer")
    if not meta:
        return None
    versions = manifest.get("versions", {})
    return RecordedRun(candidate=meta["candidate"],
                       hostap_commit=versions.get("hostap_commit"),
                       kernel_commit=versions.get("kernel_commit"),
                       schema_version=meta.get("schema_version"))


def fixed_values(candidate: Candidate) -> list[tuple[str, str]]:
    """The candidate's values for settings that aren't admitted dimensions (fixed
    settings, docs/dimensions.md), as (name, label) pairs. A candidate that changes one
    has no smoke run for it; only a legal committed run with the same value counts."""
    ap, sta = candidate.config.ap, candidate.config.sta
    return [
        ("ap_pmf", ap.pmf),
        ("ap_beacon_protection", "1" if ap.beacon_protection else "0"),
        ("ap_bss_transition", "1" if ap.bss_transition else "0"),
        ("sta_beacon_protection", "1" if sta.beacon_protection else "unset"),
        ("sta_sae_groups", " ".join(map(str, sta.sae_groups)) if sta.sae_groups else "default"),
        ("ap_link_layout", " ".join(f"link{link.link_id}:ch{link.channel}" for link in ap.links)),
    ]


def adapter_runs(evidence_dirs=EVIDENCE_DIRS) -> dict[str, RecordedRun]:
    """Run ID -> what a committed adapter run recorded, for runs that count as evidence.

    Only runs of the adapter test (explorer.adapter) that passed, whose recorded
    validation (``explorer_plan.explorer`` in the manifest) is PASSES_MODELED_RULES, and
    whose candidate still parses and passes today's modeled rules: a negative experiment
    or a REJECTED run is never evidence that a value executes."""
    from explorer.adapter import ADAPTER_TEST  # explorer.adapter imports explorer.validate
    found: dict[str, RecordedRun] = {}
    for manifest in _manifests(evidence_dirs):
        meta = manifest.get("explorer_plan", {}).get("explorer")
        passed = any(r["test"] == ADAPTER_TEST and r["result"] == "PASS"
                     for r in manifest["results"])
        if not (passed and meta and not meta["negative_experiment"]
                and meta["validation"]["status"] == "PASSES_MODELED_RULES"):
            continue
        recorded = _recorded(manifest)
        if (parsed := _parse(recorded)) is not None and passes_current_rules(parsed):
            found[manifest["run_id"]] = recorded
    return found


@lru_cache(maxsize=1)
def _cached_adapter_runs() -> dict[str, RecordedRun]:
    return adapter_runs()


def fixed_evidence() -> dict[tuple[str, str], list[str]]:
    """(fixed setting, label) -> legal committed runs that used that value: runs of the
    rule-passing hostap scenarios and counted adapter runs (adapter runs first)."""
    runs = _cached_passing_runs()
    by_adapter: dict[tuple[str, str], list[str]] = {}
    for run, recorded in sorted(_cached_adapter_runs().items()):
        if (parsed := _parse(recorded)) is not None:
            for key in fixed_values(parsed):
                by_adapter.setdefault(key, []).append(run)
    by_tests: dict[tuple[str, str], list[str]] = {}
    for test in sorted(rule_passing_tests()):
        for key in fixed_values(TEST_CANDIDATES[test]):
            by_tests.setdefault(key, []).extend(runs.get(test, []))
    return {key: list(dict.fromkeys(by_adapter.get(key, []) + sorted(by_tests.get(key, []))))
            for key in by_adapter.keys() | by_tests.keys()}


@lru_cache(maxsize=1)
def _cached_fixed_evidence() -> dict[tuple[str, str], list[str]]:
    return fixed_evidence()


def rejected_runs(rejected_dir: Path = REJECTED_DIR) -> dict[str, RecordedRun]:
    """Run ID -> what a committed rejected run recorded (runs/rejected/). Never evidence;
    P2 only cites them as recorded refusals."""
    return {manifest["run_id"]: recorded for manifest in _manifests([rejected_dir])
            if (recorded := _recorded(manifest)) is not None}


@lru_cache(maxsize=1)
def _cached_rejected_runs() -> dict[str, RecordedRun]:
    return rejected_runs()


def _parse(recorded: RecordedRun) -> Candidate | None:
    try:
        return Candidate.model_validate(recorded.candidate)
    except ValidationError:
        return None  # recorded under an older model


def _on_pinned_versions(recorded: RecordedRun) -> bool:
    """Run on the pinned hostap and kernel commits, under a schema version whose
    candidates still mean the same today (model.COMPATIBLE_SCHEMA_VERSIONS)."""
    pinned = pinned_commits()
    return (recorded.hostap_commit == pinned["hostap_commit"]
            and recorded.kernel_commit == pinned["kernel_commit"]
            and recorded.schema_version in COMPATIBLE_SCHEMA_VERSIONS)


def passes_current_rules(candidate: Candidate) -> bool:
    """Whether the candidate passes today's modeled rules (P1 settings, open questions
    and action order). A recorded verdict can be out of date: rules are added after runs."""
    from explorer.validate import (check_action_order, find_undetermined, p1_status,
                                   run_p1_checks)
    return p1_status(run_p1_checks(candidate.config) + find_undetermined(candidate.config)
                     + check_action_order(candidate)) == "PASSES_MODELED_RULES"


def _key(step: dict) -> tuple[str, str]:
    """action_key() for an action recorded as JSON in a run's manifest."""
    return step["action"], step.get("command") or step.get("operation") or "present"


def action_key(step) -> tuple[str, str]:
    """(action name, its command or operation), e.g. ('sta_disconnect_reconnect',
    'DISCONNECT'); actions without one use 'present'."""
    label = getattr(step, "command", None) or getattr(step, "operation", None) or "present"
    return step.action, label


def check_support(candidate: Candidate) -> SupportResult:
    """The P2 answer for one candidate (see the module docstring)."""
    runs = _cached_passing_runs()
    supported = [(test, runs[test]) for test, known in TEST_CANDIDATES.items()
                 if known == candidate and runs.get(test)]
    if supported:
        test, run_ids = max(supported, key=lambda pair: len(pair[1]))
        return SupportResult(
            status="SUPPORTED", test=test, run_ids=run_ids, values=[], closest_tests=[],
            all_values_evidenced=True, recorded_refusals=[],
            note=(f"Executed exactly by hostap test {test}, with {len(run_ids)} passing "
                  f"committed run(s); run it with run_hwsim_test."))
    exact = sorted(run for run, recorded in _cached_adapter_runs().items()
                   if _on_pinned_versions(recorded) and _parse(recorded) == candidate)
    if exact:
        from explorer.adapter import ADAPTER_TEST
        return SupportResult(
            status="SUPPORTED", test=ADAPTER_TEST, run_ids=exact, values=[], closest_tests=[],
            all_values_evidenced=True, recorded_refusals=[],
            note=(f"Executed exactly by {len(exact)} committed adapter run(s) "
                  f"({', '.join(exact)}) on the pinned versions; run it again with "
                  "run_candidate."))

    smoke = _cached_smoke_evidence()
    values = [ValueEvidence(candidate=name, value=label,
                            run_ids=[smoke[name][label]] if label in smoke.get(name, {}) else [])
              for name, label in setting_values(candidate)]
    adapter = _cached_adapter_runs()
    fixed_evidence = _cached_fixed_evidence()
    values += [ValueEvidence(candidate=name, value=label,
                             run_ids=fixed_evidence.get((name, label), [])[:MAX_EXAMPLE_RUNS])
               for name, label in fixed_values(candidate)]
    for name, label in dict.fromkeys(action_key(step) for step in candidate.actions):
        if name in PRESENCE_ACTIONS and label == "present":
            continue  # already listed as that dimension's "present" value above
        # Adapter runs first: each shows the action in a legal candidate of its own,
        # where a hostap test's run shows it inside that test's scenario.
        by_adapter = sorted(run for run, recorded in adapter.items() if (name, label)
                            in {_key(s) for s in recorded.candidate["actions"]})
        performed_by = [test for test, known in TEST_CANDIDATES.items()
                        if test in rule_passing_tests()
                        and (name, label) in {action_key(s) for s in known.actions}]
        by_tests = sorted({run for test in performed_by for run in runs.get(test, [])})
        run_ids = list(dict.fromkeys(by_adapter + by_tests))[:MAX_EXAMPLE_RUNS]
        values.append(ValueEvidence(candidate=name, value=label, run_ids=run_ids))
    closest = sorted(test for test, known in TEST_CANDIDATES.items()
                     if known.config == candidate.config and runs.get(test))
    refusals = recorded_refusals(candidate, values)
    missing = [f"{v.candidate}={v.value}" for v in values if not v.run_ids]
    note = ("No tested hostap scenario or committed adapter run executes this exact "
            "candidate.")
    if closest:
        note += f" {', '.join(closest)} set up this configuration with other actions."
    note += (f" No passing run under the modeled rules for: {', '.join(missing)}."
             if missing else
             " Each listed value has a passing run under the modeled rules, but not in "
             "this combination: a support probe.")
    if refusals:
        note += " Recorded refusal(s) in runs/rejected/: " + "; ".join(
            f"{r.candidate}={r.value} ({', '.join(r.run_ids)})" for r in refusals) + "."
    return SupportResult(status="UNRESOLVED", test=None, run_ids=[], values=values,
                         closest_tests=closest, all_values_evidenced=not missing,
                         recorded_refusals=refusals, note=note)


def recorded_refusals(candidate: Candidate,
                      values: list[ValueEvidence]) -> list[ValueEvidence]:
    """The values without a passing run that a committed rejected run also had."""
    missing = [(v.candidate, v.value) for v in values if not v.run_ids]
    refused: dict[tuple[str, str], list[str]] = {}
    for run, recorded in sorted(_cached_rejected_runs().items()):
        if (rejected := _parse(recorded)) is None or not passes_current_rules(rejected):
            continue  # older model, or a modeled rule now explains the refusal
        involved = (set(setting_values(rejected)) | set(fixed_values(rejected))
                    | {action_key(s) for s in rejected.actions})
        for key in missing:
            if key in involved:
                refused.setdefault(key, []).append(run)
    return [ValueEvidence(candidate=name, value=value, run_ids=runs)
            for (name, value), runs in refused.items()]

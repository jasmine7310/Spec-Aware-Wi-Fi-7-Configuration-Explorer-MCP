"""Consistency between the spec, the rule model and the run evidence (issue #76).

The mentor asked us to keep the three consistent as the space grows. Each check here
re-reads the committed files, so a new rule, run or matrix row that breaks one fails
``tests/test_consistency.py``:

- **Evidence runs pass today's rules.** Every passing run in ``support.EVIDENCE_DIRS``
  passes today's modeled rules (P1 settings, open questions, action order), or is a
  labeled negative experiment (``evidence_violations``). A rule added after a run can turn
  that run into a violation (#88 and #95 both did); P2 then quietly stops counting it, and
  this check says so out loud. There are two kinds of labeled negative:
  - an adapter run whose manifest records ``negative_experiment: true``;
  - a run of one of hostap's own tests (not one of our ``_client_bp`` wrappers) that
    breaks only the rules in ``NEGATIVE_BY_DESIGN``.
- **Cited runs pass every rule, with no exemption** (``cited_violations``). These are the
  runs a file cites as legal evidence: ``surface_candidates.csv``'s smoke runs,
  ``anchor_coverage.csv``'s runs and the sides of ``contrasts/contrasts.json``.
- **Labeled negatives stay out of the evidence folders** (``misplaced_negatives``). An
  adapter run labeled ``negative_experiment: true`` belongs in ``runs/experiments/`` or
  ``runs/rejected/``.
- **Every rule's validation is reported** (``rule_validation``), and rules with no
  experimental validation are flagged. A rule counts as validated when a committed run
  breaks it, or when a ``spec_coverage.csv`` row naming it cites runs.
  - A run that breaks a rule shows what the pinned implementation does when the rule is
    broken: it accepts the candidate (e.g. the plain-SAE baseline) or refuses it.
  - Cited runs only show the legal side executing.

  ``rules/validation.json`` records the result; ``scripts/check_consistency.py`` writes it.

Checked elsewhere, and not repeated here:
- every rule and open question has fixtures with a positive and a negative
  (``tests/test_rule_fixtures.py``);
- every standards citation in ``rules.yaml`` has a matrix row naming the rule
  (``tests/test_spec_coverage.py``);
- every admitted dimension's values have committed, passing, rule-passing smoke runs that
  show that value (``tests/test_surface_candidates.py``, ``tests/test_model_json.py``).
  ``tests/test_consistency.py`` adds the other direction: every value
  ``model_json.DIMENSIONS`` offers has a smoke run;
- ConfigSpace and the P1 predicates agree on every combination
  (``tests/test_config_space.py``, #63).
"""

from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from explorer.model import Candidate
from explorer.scenarios import CLIENT_BP_SUFFIX, TEST_CANDIDATES
from explorer.support import EVIDENCE_DIRS

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS = REPO_ROOT / "runs"
# Every folder of committed runs. runs/hwsim-logs/ holds git-ignored trials and is skipped.
COMMITTED_DIRS = (*EVIDENCE_DIRS, RUNS / "experiments", RUNS / "rejected")
SPEC_COVERAGE_CSV = REPO_ROOT / "spec_coverage.csv"
ANCHOR_COVERAGE_CSV = REPO_ROOT / "anchor_coverage.csv"
CONTRASTS_JSON = REPO_ROOT / "contrasts" / "contrasts.json"
VALIDATION_JSON = REPO_ROOT / "rules" / "validation.json"
# Folders where an adapter run labeled negative_experiment may live.
NEGATIVE_DIRS = (RUNS / "experiments", RUNS / "rejected")
STANDARDS = {"IEEE-802.11be-2024", "IEEE-802.11-2024", "WFA-WPA3"}

# The rules hostap's own tests break by design. A run of one of those tests (not of an
# adapter candidate, and not of our _client_bp wrappers) that breaks only these is a
# labeled negative experiment.
NEGATIVE_BY_DESIGN = {
    "SEC.EHT_SAE_AKM": (
        "The official baseline, hostap's eht_mld_sae_two_links, uses plain SAE between EHT "
        "devices (runs/baseline/README.md)."),
    "SEC.EHT_BEACON_PROT": (
        "hostap's other EHT tests leave the client's beacon protection off "
        "(explorer.scenarios); our _client_bp wrappers turn it on."),
}


class RunCheck(BaseModel):
    """One test result in one committed run, judged by today's rules."""
    run: str
    """The run folder, relative to the repo root."""
    run_id: str
    test: str
    result: str
    """The test's result in the manifest (PASS / FAIL / ...)."""
    rule_ids: list[str]
    """Today's findings for what the run did (rules and UND.* questions), or ["P0"] if the
    recorded candidate no longer parses."""
    labeled_negative: bool


def findings(candidate: Candidate) -> list[str]:
    """Rule and UND.* IDs today's modeled rules raise for a candidate, sorted."""
    from explorer.validate import check_action_order, find_undetermined, run_p1_checks
    found = (run_p1_checks(candidate.config) + find_undetermined(candidate.config)
             + check_action_order(candidate))
    return sorted({f.rule_id for f in found})


def _hostap_original(test: str) -> bool:
    return test in TEST_CANDIDATES and not test.endswith(CLIENT_BP_SUFFIX)


def check_runs(dirs=COMMITTED_DIRS) -> list[RunCheck]:
    """Every test result in every committed run under ``dirs``, judged by today's rules.
    A hostap test without a modeled scenario is skipped: nothing says what it did."""
    from explorer.adapter import ADAPTER_TEST
    checks = []
    for folder in dirs:
        for path in sorted(Path(folder).rglob("manifest.json")):
            manifest = json.loads(path.read_text())
            meta = manifest.get("explorer_plan", {}).get("explorer")
            for result in manifest["results"]:
                test = result["test"]
                if test == ADAPTER_TEST and meta:
                    try:
                        rule_ids = findings(Candidate.model_validate(meta["candidate"]))
                    except ValidationError:
                        rule_ids = ["P0"]
                    negative = bool(meta.get("negative_experiment"))
                elif test in TEST_CANDIDATES:
                    rule_ids = findings(TEST_CANDIDATES[test])
                    negative = (_hostap_original(test) and bool(rule_ids)
                                and set(rule_ids) <= NEGATIVE_BY_DESIGN.keys())
                else:
                    continue
                checks.append(RunCheck(
                    run=_relative(path.parent), run_id=manifest["run_id"], test=test,
                    result=result["result"], rule_ids=rule_ids, labeled_negative=negative))
    return checks


def _relative(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


@lru_cache(maxsize=1)
def _committed_checks() -> tuple[RunCheck, ...]:
    return tuple(check_runs())


def evidence_violations(dirs=EVIDENCE_DIRS) -> list[RunCheck]:
    """Passing runs in the evidence folders that break today's rules and aren't labeled
    negative experiments."""
    return [c for c in check_runs(dirs)
            if c.result == "PASS" and c.rule_ids and not c.labeled_negative]


def misplaced_negatives(dirs=EVIDENCE_DIRS) -> list[RunCheck]:
    """Adapter runs labeled negative_experiment that sit in an evidence folder."""
    from explorer.adapter import ADAPTER_TEST
    return [c for c in check_runs(dirs) if c.test == ADAPTER_TEST and c.labeled_negative]


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def cited_runs() -> dict[str, list[str]]:
    """Run ID -> where a file cites it as legal evidence: smoke runs, anchor runs and
    contrast sides."""
    from explorer.support import smoke_evidence
    cited: dict[str, list[str]] = {}
    for name, values in smoke_evidence().items():
        for label, run_id in values.items():
            cited.setdefault(run_id, []).append(f"surface_candidates.csv {name}={label}")
    with ANCHOR_COVERAGE_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for run_id in _split(row["run_ids"]):
                cited.setdefault(run_id, []).append(f"anchor_coverage.csv {row['family_id']}")
    for i, contrast in enumerate(json.loads(CONTRASTS_JSON.read_text())["contrasts"]):
        for side in ("a", "b"):
            for run_id in contrast[f"{side}_runs"]:
                cited.setdefault(run_id, []).append(f"contrasts.json contrast {i} side {side}")
    return cited


def cited_violations() -> list[tuple[RunCheck | None, list[str]]]:
    """Cited runs that break a rule today (no exemption), or that no committed folder
    holds (None), with where they're cited."""
    by_id: dict[str, list[RunCheck]] = {}
    for check in _committed_checks():
        by_id.setdefault(check.run_id, []).append(check)
    bad = []
    for run_id, where in sorted(cited_runs().items()):
        checks = by_id.get(run_id)
        if not checks:
            bad.append((None, where))
        bad += [(c, where) for c in checks or [] if c.rule_ids]
    return bad


Validation = Literal["broken_in_a_run", "cited_runs_only", "none"]


class BrokenRun(BaseModel):
    run: str
    test: str
    result: str


class RuleValidation(BaseModel):
    id: str
    kind: str
    """The rule's kind in rules.yaml, or "open_question" for an UND.* entry."""
    cites_standard: bool
    matrix_rows: list[str]
    """spec_coverage.csv rows naming it, as "document clause"."""
    fixtures: dict[str, int]
    """rules/fixtures: fixture kind -> count."""
    broken_in_runs: list[BrokenRun]
    """Committed runs (any folder) whose candidate or test breaks it today."""
    cited_runs: list[str]
    """Run IDs in the run_evidence of the matrix rows naming it."""
    validation: Validation


def rule_validation() -> list[RuleValidation]:
    """One entry per rule and open question in rules.yaml, in file order."""
    from explorer.fixtures import load_fixtures
    from explorer.rules import load_rules
    registry = load_rules()
    with SPEC_COVERAGE_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fixture_files = load_fixtures()
    broken: dict[str, list[BrokenRun]] = {}
    for check in _committed_checks():
        for rule_id in check.rule_ids:
            broken.setdefault(rule_id, []).append(
                BrokenRun(run=check.run, test=check.test, result=check.result))
    out = []
    for entry in [*registry.rules, *registry.undetermined]:
        named = [r for r in rows if entry.id in _split(r["rule_ids"])]
        cited = list(dict.fromkeys(run for r in named for run in _split(r["run_evidence"])))
        counts: dict[str, int] = {}
        for fixture in fixture_files[entry.id].fixtures if entry.id in fixture_files else []:
            counts[fixture.kind] = counts.get(fixture.kind, 0) + 1
        runs = broken.get(entry.id, [])
        out.append(RuleValidation(
            id=entry.id, kind=getattr(entry, "kind", "open_question"),
            cites_standard=any(c.doc in STANDARDS for c in entry.sources),
            matrix_rows=[f"{r['document']} {r['clause']}" for r in named],
            fixtures=dict(sorted(counts.items())), broken_in_runs=runs, cited_runs=cited,
            validation=("broken_in_a_run" if runs else
                        "cited_runs_only" if cited else "none")))
    return out


def build() -> dict:
    """The rules/validation.json report."""
    entries = rule_validation()
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.validation] = counts.get(e.validation, 0) + 1
    return {
        "description": (
            "Experimental validation of each rule and open question in rules.yaml (#76). "
            "broken_in_a_run: a committed run breaks it under today's rules, showing what "
            "the pinned implementation does then (result PASS: it accepted the candidate). "
            "cited_runs_only: only spec_coverage.csv's run_evidence, which shows the legal "
            "side executing. none: no experimental validation yet (flagged). Written by "
            "scripts/check_consistency.py."),
        "counts": dict(sorted(counts.items())),
        "unvalidated": [e.id for e in entries if e.validation == "none"],
        "rules": [e.model_dump() for e in entries],
    }


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


def write(path: Path = VALIDATION_JSON) -> dict:
    path.write_text(render())
    return json.loads(path.read_text())

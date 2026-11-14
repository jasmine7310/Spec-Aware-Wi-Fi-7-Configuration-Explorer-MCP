"""Executable rule fixtures (issue #64): ``rules/fixtures/<ID>.json``.

One file per rule or open question in ``rules.yaml``. Each fixture is a full candidate (the
same JSON ``validate_candidate`` takes), what kind of case it is, where it comes from, and
the exact outcome expected from ``validate.validate_candidate``:

- ``positive``: the rule doesn't apply (for an open question: it isn't raised). The ID is
  not among the findings; most positives pass every modeled rule.
- ``negative``: the rule applies. The ID is among the findings, unless ``enforced_by``
  names the earlier stage that rejects the case first (``SEC.PMF``: P0 has no "disabled"
  value, so the candidate is MALFORMED before P1 runs).
- ``exception``: one of the rule's listed exceptions. The ID is not among the findings.

``expect.findings`` lists every finding's rule ID (order doesn't matter), so a fixture also
pins down which other rules a case trips. ``rules.yaml``'s ``examples`` stay the
plain-language description; these are what gets executed. ``evaluate`` reports the
fixtures' accuracy and the share of negative fixtures the stages catch, the roadmap's
"rule-unit-test accuracy on curated positive/negative fixtures" and Week 6's "fraction of
reviewed invalid fixtures caught".
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "rules" / "fixtures"

Kind = Literal["positive", "negative", "exception"]
_STRICT = ConfigDict(strict=True, extra="forbid", frozen=True)


class Expect(BaseModel):
    model_config = _STRICT
    status: Literal["MALFORMED", "SPEC_RULE_VIOLATION", "SPEC_UNDETERMINED",
                    "PASSES_MODELED_RULES"]
    findings: list[str]
    """Every finding's rule ID (P0.* or a rules.yaml ID), in any order."""


class Fixture(BaseModel):
    model_config = _STRICT
    name: str
    kind: Kind
    source: str
    """Where the case comes from: a rules.yaml example or exception, or a hostap test."""
    candidate: dict
    expect: Expect
    enforced_by: str | None = None
    """For a negative caught before P1: the stage or P0 code that rejects it."""


class FixtureFile(BaseModel):
    model_config = _STRICT
    id: str
    fixtures: list[Fixture]


class Outcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_id: str
    fixture: str
    kind: Kind
    status: str
    findings: list[str]
    passed: bool
    """The actual status and findings match the fixture's expect."""


def load_fixtures(directory: Path = FIXTURES_DIR) -> dict[str, FixtureFile]:
    """ID -> its fixture file. Each file must be named after the ID it holds."""
    files = {}
    for path in sorted(Path(directory).glob("*.json")):
        data = FixtureFile.model_validate(json.loads(path.read_text()))
        if path.stem != data.id:
            raise ValueError(f"{path.name} holds fixtures for {data.id}")
        files[data.id] = data
    return files


def run(rule_id: str, fixture: Fixture) -> Outcome:
    from explorer.validate import validate_candidate  # validate imports support, etc.
    result = validate_candidate(fixture.candidate)
    findings = sorted(f.rule_id for f in result.findings)
    passed = (result.status == fixture.expect.status
              and findings == sorted(fixture.expect.findings))
    return Outcome(rule_id=rule_id, fixture=fixture.name, kind=fixture.kind,
                   status=result.status, findings=findings, passed=passed)


class Report(BaseModel):
    total: int
    passed: int
    accuracy: float
    by_kind: dict[str, list[int]]
    """kind -> [passed, total]."""
    negatives_caught: float
    """Share of negative fixtures the stages reject as expected."""
    failures: list[Outcome]


def evaluate(directory: Path = FIXTURES_DIR) -> Report:
    outcomes = [run(rule_id, fixture)
                for rule_id, data in load_fixtures(directory).items()
                for fixture in data.fixtures]
    totals = Counter(o.kind for o in outcomes)
    passed = Counter(o.kind for o in outcomes if o.passed)
    negatives = totals["negative"]
    return Report(
        total=len(outcomes), passed=sum(passed.values()),
        accuracy=round(sum(passed.values()) / len(outcomes), 4) if outcomes else 0.0,
        by_kind={kind: [passed[kind], totals[kind]] for kind in sorted(totals)},
        negatives_caught=round(passed["negative"] / negatives, 4) if negatives else 0.0,
        failures=[o for o in outcomes if not o.passed])

"""docs/rule-audit.md (#109) keeps up with rules.yaml, rules/validation.json and the planner."""

import json
import re
from pathlib import Path

from explorer.rules import load_rules

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT = REPO_ROOT / "docs" / "rule-audit.md"
VALIDATION = {"broken_in_a_run": "broken", "cited_runs_only": "cited", "none": "none"}


def _section(title):
    text = AUDIT.read_text(encoding="utf-8")
    start = text.index(f"\n## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else None]


def _table(title):
    """{first cell without backticks: [cells]} for the rows of a section's tables."""
    rows = {}
    for line in _section(title).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| `") and len(cells) > 1:
            rows[cells[0].strip("`")] = cells
    return rows


def test_every_rule_and_open_question_has_a_summary_row():
    registry = load_rules()
    expected = {r.id: r.kind for r in registry.rules}
    expected |= {u.id: "open question" for u in registry.undetermined}
    rows = _table("Summary")
    assert set(rows) == set(expected), (
        "docs/rule-audit.md's summary table must list exactly the rules and open questions "
        f"in rules.yaml: missing {sorted(set(expected) - set(rows))}, "
        f"extra {sorted(set(rows) - set(expected))}")
    for rule_id, kind in expected.items():
        assert rows[rule_id][1] == kind, rule_id


def test_validation_column_matches_rules_validation_json():
    validation = json.loads((REPO_ROOT / "rules" / "validation.json").read_text())
    recorded = {r["id"]: VALIDATION[r["validation"]] for r in validation["rules"]}
    for rule_id, cells in _table("Summary").items():
        assert cells[3].strip("*") == recorded[rule_id], rule_id


def test_pruning_counts_match_the_planner_funnel():
    funnel = json.loads((REPO_ROOT / "campaign_plan.json").read_text())["funnel"]
    by_rule = funnel["p1_rejections_by_rule"]
    rows = _table("Where pruning actually happens")
    assert {rule: int(cells[1]) for rule, cells in rows.items()} == by_rule
    text = _section("Where pruning actually happens")
    for number in (funnel["enumerated"], funnel["p1"]["SPEC_RULE_VIOLATION"],
                   funnel["p1"]["PASSES_MODELED_RULES"], funnel["p2"]["unsupported"],
                   funnel["executable"]):
        assert str(number) in text, number


def test_every_cited_finding_has_a_disposition():
    findings = _section("Findings")
    listed = set(re.findall(r"^\| (F\d+) \|", findings, re.MULTILINE))
    cited = set(re.findall(r"\bF\d+\b", _section("Summary")))
    assert cited <= listed, sorted(cited - listed)
    for line in findings.splitlines():
        if re.match(r"^\| F\d+ \|", line):
            disposition = line.strip().strip("|").split("|")[-1]
            assert re.search(r"Fixtures? added|Issue|Stated limit", disposition), line

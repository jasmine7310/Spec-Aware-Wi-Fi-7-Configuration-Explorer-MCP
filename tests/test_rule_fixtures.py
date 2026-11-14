"""The executable rule fixtures in rules/fixtures/ (issue #64)."""

import pytest

from explorer.fixtures import FIXTURES_DIR, evaluate, load_fixtures, run
from explorer.rules import load_rules

REGISTRY = load_rules()
IDS = [r.id for r in REGISTRY.rules] + [q.id for q in REGISTRY.undetermined]
FILES = load_fixtures()
CASES = [(rule_id, f) for rule_id, data in FILES.items() for f in data.fixtures]


def test_every_rule_and_question_has_a_fixture_file():
    assert sorted(FILES) == sorted(IDS)


@pytest.mark.parametrize("rule_id", IDS)
def test_each_has_a_positive_and_a_negative(rule_id):
    kinds = {f.kind for f in FILES[rule_id].fixtures}
    assert {"positive", "negative"} <= kinds, (rule_id, kinds)


@pytest.mark.parametrize("rule_id,fixture", CASES, ids=[f"{r}: {f.name}" for r, f in CASES])
def test_fixture_outcome(rule_id, fixture):
    outcome = run(rule_id, fixture)
    assert outcome.passed, (outcome.status, outcome.findings, fixture.expect)


@pytest.mark.parametrize("rule_id,fixture", CASES, ids=[f"{r}: {f.name}" for r, f in CASES])
def test_kind_matches_what_the_rule_does(rule_id, fixture):
    named = rule_id in fixture.expect.findings
    if fixture.kind == "negative":
        # The rule fires, or an earlier stage that the fixture names rejects it first.
        assert named or (fixture.enforced_by and fixture.expect.status == "MALFORMED")
    else:
        assert not named and fixture.enforced_by is None


def test_fixture_names_are_unique_per_file():
    for rule_id, data in FILES.items():
        names = [f.name for f in data.fixtures]
        assert len(names) == len(set(names)), rule_id


def test_file_name_must_match_its_id(tmp_path):
    (tmp_path / "SEC.PMF.json").write_text('{"id": "SEC.EHT_SAE_AKM", "fixtures": []}')
    with pytest.raises(ValueError, match="holds fixtures for SEC.EHT_SAE_AKM"):
        load_fixtures(tmp_path)


def test_report():
    report = evaluate(FIXTURES_DIR)
    assert report.failures == []
    assert report.accuracy == 1.0 and report.negatives_caught == 1.0
    assert report.total == sum(len(d.fixtures) for d in FILES.values())
    assert set(report.by_kind) == {"positive", "negative", "exception"}

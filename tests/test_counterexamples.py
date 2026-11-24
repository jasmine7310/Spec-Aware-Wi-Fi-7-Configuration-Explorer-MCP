"""The roadmap's counterexample suite (#108): each case pins its stage, status and rule
IDs, directly and over MCP. The cases are in ``explorer.counterexamples``; the
walk-through is ``docs/counterexamples.md``."""

import asyncio

import pytest
from mcp import Client

from explorer import counterexamples
from explorer.counterexamples import CASES
from explorer.fixtures import load_fixtures
from explorer.mcp_server import server

ROADMAP_CASES = {counterexamples.AKM, counterexamples.MALFORMED_LINK,
                 counterexamples.UNSUPPORTED, counterexamples.UNDETERMINED,
                 counterexamples.REKEY_FIRST}
BY_NAME = {case.name: case for case in CASES}


def test_every_roadmap_case_is_covered():
    assert {case.roadmap_case for case in CASES} == ROADMAP_CASES
    assert len(BY_NAME) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_case(case):
    outcome = counterexamples.check(case)
    assert outcome.passed, outcome.mismatches


def test_shared_akm_passes_only_with_the_same_rsnxe():
    passing = counterexamples.check(BY_NAME["akm_lists_differ_same_rsnxe"])
    failing = counterexamples.check(BY_NAME["akm_lists_differ_rsnxe_differs"])
    # Both pairs of lists differ and share an AKM: SEC.MLD_COMMON_SUITES objects to neither.
    for case in ("akm_lists_differ_same_rsnxe", "akm_lists_differ_rsnxe_differs"):
        links = counterexamples.candidate(BY_NAME[case])["config"]["ap"]["links"]
        lists = [set(link["akms"]) for link in links]
        assert lists[0] != lists[1] and lists[0] & lists[1]
    assert passing.rule_ids == [] and passing.role not in ("pruned", "undetermined")
    assert failing.rule_ids == ["SEC.MLD_SAME_RSNXE"]


def test_every_undetermined_entry_has_a_case():
    from explorer.rules import load_rules
    und = {entry.id for entry in load_rules().undetermined}
    covered = {rid for case in CASES if case.status == "SPEC_UNDETERMINED"
               for rid in case.rule_ids}
    assert covered == und


@pytest.mark.parametrize("case", [c for c in CASES if c.source.startswith("fixture:")
                                  and c.mutate is None], ids=lambda c: c.name)
def test_unchanged_fixture_cases_agree_with_their_fixture(case):
    # A case that reuses a fixture as is must expect what the fixture expects, so the two
    # can't drift apart.
    _, rule_id, name = case.source.split(":", 2)
    [fixture] = [f for f in load_fixtures()[rule_id].fixtures if f.name == name]
    assert fixture.expect.status == case.status
    assert sorted(fixture.expect.findings) == sorted(case.rule_ids)


def test_mutated_cases_change_only_what_they_say():
    for case in CASES:
        if case.mutate is not None:
            assert case.change, case.name
            assert counterexamples.candidate(case) != counterexamples._source_candidate(
                case.source)


def _call(tool, arguments):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, arguments)
    result = asyncio.run(go())
    assert not result.is_error, result.content[0].text
    return result.structured_content


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_case_over_mcp(case):
    data = counterexamples.candidate(case)
    checked = _call("validate_candidate", {"candidate": data})
    assert checked["status"] == case.status
    assert checked["stage_reached"] == case.stage_reached
    assert sorted(f["rule_id"] for f in checked["findings"]) == sorted(case.rule_ids)
    if case.p2 is not None:
        assert checked["p2"]["status"] == case.p2 and checked["p2"]["limit"] == case.limit
        assert case.refusal_run in checked["p2"]["run_ids"]
    why = _call("why_pruned", {"candidate": data})
    if case.role is not None:
        assert (why["role"], why["stage"]) == (case.role, case.why_stage)
    for rule_id in case.rule_ids:
        rule = _call("explain_rule", {"rule_id": rule_id})
        assert rule["id"] == rule_id
        if not rule_id.startswith("P0."):
            # The exact source behind the finding: document and location of each citation.
            assert rule["sources"] and all(s["doc"] and s["location"] for s in rule["sources"])

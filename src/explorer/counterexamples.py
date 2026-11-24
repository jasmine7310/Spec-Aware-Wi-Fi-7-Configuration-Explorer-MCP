"""The roadmap's counterexample suite for the formalization (issue #108).

Week 5 asks to "test the formalization against counterexamples so rules don't eliminate
semantically permitted cases". Each roadmap case below gets one or more ``Case``s: a
candidate and the exact outcome expected from ``validate.validate_candidate`` (status, the
stage it reaches, every finding's rule ID, and P2 where it matters) and from
``pruning.why_pruned`` (the planner's role and the stage that stops it).

Most candidates aren't new: a case points at the fixture (``rules/fixtures/<ID>.json``, by
rule ID and fixture name) or the committed run it comes from, so the suite and the rule
fixtures can't drift apart. Where the roadmap case is a variant of one (a malformed link
ID), ``mutate`` changes the fixture's candidate and ``change`` says how.

``evaluate()`` checks every case; ``tests/test_counterexamples.py`` runs it, also over MCP,
and ``docs/counterexamples.md`` is the walk-through.

The roadmap cases:

- **Different AP-link AKM lists with a shared selected AKM** must pass P1: 802.11be
  §12.6.2 lets the links' AKM lists differ (``SEC.MLD_COMMON_SUITES``'s exception). Since
  #95 that holds only when the lists give the same RSNXE (``SEC.MLD_SAME_RSNXE``: no
  per-link exception), so both directions are pinned: a shared AKM with the same RSNXE
  passes, a shared AKM with different RSNXEs fails that rule alone.
- **A malformed link ID** is ``MALFORMED`` at P0, with the P0 code of each variant.
- **A legal-but-unsupported helper**: ``DISABLE_MLD`` after ``link_remove`` passes the
  modeled rules but P2 says ``UNSUPPORTED_IMPLEMENTATION`` (``support.IMPLEMENTATION_LIMITS``),
  backed by recorded refusals, never inferred from missing evidence.
- **A missing / ambiguous requirement** is ``SPEC_UNDETERMINED``, one case per ``UND.*``
  entry: neither approved nor a violation.
- **A rekey action before association** breaks ``AO.ASSOC_REQUIRED``, a harness rule (not
  a Wi-Fi spec rule).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Case:
    name: str
    roadmap_case: str
    """The roadmap's counterexample this case covers."""
    source: str
    """``fixture:<rule ID>:<fixture name>`` or ``run:<campaign folder>/<run ID>``."""
    status: str
    """validate_candidate's status."""
    stage_reached: str
    rule_ids: tuple[str, ...]
    """Every finding's rule ID, sorted."""
    role: str | None
    """why_pruned's role; None when it depends on which runs are committed (P2)."""
    why_stage: str | None
    """why_pruned's stage (the stage that stops it), when ``role`` is pinned."""
    p2: str | None = None
    """P2's status, when the case is about P2."""
    limit: str | None = None
    """The implementation limit P2 names."""
    refusal_run: str | None = None
    """A committed refusal P2 must cite for the limit."""
    change: str | None = None
    """How ``mutate`` changes the source candidate."""
    mutate: Callable[[dict], None] | None = field(default=None, compare=False, repr=False)
    why: str = ""
    """Why this is the right outcome."""


def _set_link(index: int, **values) -> Callable[[dict], None]:
    def mutate(data: dict) -> None:
        data["config"]["ap"]["links"][index].update(values)
    return mutate


def _set_actions(actions: list[dict]) -> Callable[[dict], None]:
    def mutate(data: dict) -> None:
        data["actions"] = actions
    return mutate


AKM = "different AP-link AKM lists with a shared selected AKM"
MALFORMED_LINK = "a malformed link ID"
UNSUPPORTED = "a legal-but-unsupported helper"
UNDETERMINED = "a missing or ambiguous requirement"
REKEY_FIRST = "a rekey action before association"

_BASE = "fixture:SEC.MLD_SAME_RSNXE:SAE-EXT-KEY on both links"

CASES: tuple[Case, ...] = (
    Case(name="akm_lists_differ_same_rsnxe", roadmap_case=AKM,
         source="fixture:SEC.MLD_SAME_RSNXE:different AKM lists, same bit",
         status="PASSES_MODELED_RULES", stage_reached="P2", rule_ids=(),
         role=None, why_stage=None,
         why=("Link 0 advertises SAE-EXT-KEY and SAE, link 1 only SAE-EXT-KEY; the client "
              "selects SAE-EXT-KEY, which both links share. §12.6.2 allows different AKM "
              "lists (SEC.MLD_COMMON_SUITES's exception, the same candidate as its fixture "
              "'different AKM lists sharing an AKM'), and SAE-EXT-KEY sets the same RSNXE "
              "bit on both links. No rule may prune it. Whether it's executable depends on "
              "committed runs (P2), not on the rules, so its role isn't pinned.")),
    Case(name="akm_lists_differ_rsnxe_differs", roadmap_case=AKM,
         source="fixture:SEC.MLD_SAME_RSNXE:SAE-EXT-KEY on one link only",
         status="SPEC_RULE_VIOLATION", stage_reached="P1", rule_ids=("SEC.MLD_SAME_RSNXE",),
         role="pruned", why_stage="P1",
         why=("Link 0 advertises SAE-EXT-KEY and OWE, link 1 only OWE: the lists share OWE, "
              "so SEC.MLD_COMMON_SUITES does not object (it isn't among the findings), but "
              "only link 0 sets the SAE hash-to-element RSNXE bit. §12.6.2's same-RSNXE "
              "requirement has no per-link exception, so a shared AKM isn't enough.")),
    Case(name="link_id_repeated", roadmap_case=MALFORMED_LINK, source=_BASE,
         change="link 1's link_id set to 0 (both links have ID 0)",
         mutate=_set_link(1, link_id=0),
         status="MALFORMED", stage_reached="P0", rule_ids=("P0.INVALID_VALUE",),
         role="malformed", why_stage="P0",
         why="Link IDs identify the AP MLD's links, so they must not repeat."),
    Case(name="link_id_out_of_range", roadmap_case=MALFORMED_LINK, source=_BASE,
         change="link 1's link_id set to 15 (the model allows 0-14)",
         mutate=_set_link(1, link_id=15),
         status="MALFORMED", stage_reached="P0", rule_ids=("P0.OUT_OF_RANGE",),
         role="malformed", why_stage="P0",
         why="The model allows link IDs 0-14 (model.MAX_LINKS); 15 is outside it."),
    Case(name="link_id_negative", roadmap_case=MALFORMED_LINK, source=_BASE,
         change="link 0's link_id set to -1",
         mutate=_set_link(0, link_id=-1),
         status="MALFORMED", stage_reached="P0", rule_ids=("P0.OUT_OF_RANGE",),
         role="malformed", why_stage="P0",
         why="A link ID is never negative (-1 only means 'no link' in an action)."),
    Case(name="link_id_wrong_type", roadmap_case=MALFORMED_LINK, source=_BASE,
         change='link 0\'s link_id set to the string "0"',
         mutate=_set_link(0, link_id="0"),
         status="MALFORMED", stage_reached="P0", rule_ids=("P0.TYPE_ERROR",),
         role="malformed", why_stage="P0",
         why="P0 is strict: a string is never coerced to an integer."),
    Case(name="link_id_not_configured", roadmap_case=MALFORMED_LINK, source=_BASE,
         change="actions: associate, then link_remove on link 5 (the AP has links 0 and 1)",
         mutate=_set_actions([{"action": "associate"},
                              {"action": "link_remove", "link_id": 5, "count": 4}]),
         status="MALFORMED", stage_reached="P0", rule_ids=("P0.INVALID_VALUE",),
         role="malformed", why_stage="P0",
         why=("An action may only name a configured AP link. (Removing a link that was "
              "configured but already removed is AO.LINK_MUST_EXIST, a P1 harness rule.)")),
    Case(name="disable_mld_after_link_remove", roadmap_case=UNSUPPORTED,
         source="run:campaigns/seed0-2026-11-13/1794557044",
         status="PASSES_MODELED_RULES", stage_reached="P2", rule_ids=(),
         role="unsupported", why_stage="P2",
         p2="UNSUPPORTED_IMPLEMENTATION", limit="P2.DISABLE_MLD_AFTER_LINK_REMOVE",
         refusal_run="1794557044",
         why=("No modeled rule forbids DISABLE_MLD after LINK_REMOVE, but hostapd's "
              "DISABLE_MLD fails on the link LINK_REMOVE already disabled. The campaign run "
              "came back REJECTED with 'DISABLE_MLD failed'; P2 cites it. An implementation "
              "limit, not a Wi-Fi rule.")),
    Case(name="und_assoc_without_ap_links", roadmap_case=UNDETERMINED,
         source="fixture:UND.ASSOC_WITHOUT_AP_LINKS:associate again after every link is removed",
         status="SPEC_UNDETERMINED", stage_reached="P1",
         rule_ids=("UND.ASSOC_WITHOUT_AP_LINKS",), role="undetermined", why_stage="P1",
         why="Associating again once the AP MLD has no links left: the standard doesn't say."),
    Case(name="und_sta_state_while_mld_disabled", roadmap_case=UNDETERMINED,
         source=("fixture:UND.STA_STATE_WHILE_MLD_DISABLED:"
                 "rekey while the AP MLD is disabled, no disconnect"),
         status="SPEC_UNDETERMINED", stage_reached="P1",
         rule_ids=("UND.STA_STATE_WHILE_MLD_DISABLED",), role="undetermined", why_stage="P1",
         why="The client's state while the whole AP MLD is disabled isn't specified."),
    Case(name="und_akm_preference", roadmap_case=UNDETERMINED,
         source="fixture:UND.AKM_PREFERENCE:SAE-EXT-KEY and WPA-PSK both usable",
         status="SPEC_UNDETERMINED", stage_reached="P1",
         rule_ids=("UND.AKM_PREFERENCE",), role="undetermined", why_stage="P1",
         why="Which AKM a client must prefer when an SAE-family AKM and WPA-PSK are both usable."),
    Case(name="rekey_before_association", roadmap_case=REKEY_FIRST,
         source="fixture:AO.ASSOC_REQUIRED:rekey before associating",
         status="SPEC_RULE_VIOLATION", stage_reached="P1", rule_ids=("AO.ASSOC_REQUIRED",),
         role="pruned", why_stage="P1",
         why=("A GTK rekey needs an associated client. AO.* rules are harness rules: the "
              "candidate makes no sense as an experiment, it doesn't break a Wi-Fi rule.")),
)


def _source_candidate(source: str) -> dict:
    kind, _, rest = source.partition(":")
    if kind == "fixture":
        from explorer.fixtures import load_fixtures
        rule_id, _, name = rest.partition(":")
        matches = [f for f in load_fixtures()[rule_id].fixtures if f.name == name]
        if len(matches) != 1:
            raise KeyError(f"no fixture {name!r} in rules/fixtures/{rule_id}.json")
        return copy.deepcopy(matches[0].candidate)
    if kind == "run":
        manifest = json.loads((REPO_ROOT / rest / "manifest.json").read_text())
        return copy.deepcopy(manifest["explorer_plan"]["explorer"]["candidate"])
    raise ValueError(f"unknown source {source!r}")


def candidate(case: Case) -> dict:
    """The case's candidate JSON (the source's, changed by ``mutate``)."""
    data = _source_candidate(case.source)
    if case.mutate is not None:
        case.mutate(data)
    return data


class Outcome(BaseModel):
    name: str
    roadmap_case: str
    status: str
    stage_reached: str
    rule_ids: list[str]
    role: str
    why_stage: str | None
    p2: str | None
    limit: str | None
    recorded_refusals: list[str]
    """Committed refusals P2 cites (the implementation limit's runs)."""
    mismatches: list[str]
    """What differs from the case's expectation; empty when it passed."""

    @property
    def passed(self) -> bool:
        return not self.mismatches


def check(case: Case) -> Outcome:
    """Run one case through validate_candidate and why_pruned."""
    from explorer import pruning, validate
    data = candidate(case)
    result = validate.validate_candidate(data)
    why = pruning.why_pruned(data)
    p2 = result.p2
    # An implementation limit cites its refusals in run_ids; recorded_refusals lists
    # refusals per value for an UNRESOLVED candidate.
    refusals = sorted(set(p2.run_ids if p2 and p2.limit else []) | {
        run for value in (p2.recorded_refusals if p2 else []) for run in value.run_ids})
    out = dict(status=result.status, stage_reached=result.stage_reached,
               rule_ids=sorted(f.rule_id for f in result.findings), role=why.role,
               why_stage=why.stage, p2=p2.status if p2 else None,
               limit=p2.limit if p2 else None, recorded_refusals=refusals)
    expected = dict(status=case.status, stage_reached=case.stage_reached,
                    rule_ids=sorted(case.rule_ids))
    if case.role is not None:
        expected.update(role=case.role, why_stage=case.why_stage)
    if case.p2 is not None:
        expected.update(p2=case.p2, limit=case.limit)
    mismatches = [f"{k}: expected {v!r}, got {out[k]!r}" for k, v in expected.items()
                  if out[k] != v]
    if case.refusal_run and case.refusal_run not in refusals:
        mismatches.append(f"recorded_refusals: {case.refusal_run} missing from {refusals}")
    if case.status == "PASSES_MODELED_RULES" and why.role in ("malformed", "pruned",
                                                              "undetermined"):
        mismatches.append(f"role: a rule-passing case was pruned by the rules ({why.role})")
    return Outcome(name=case.name, roadmap_case=case.roadmap_case, **out,
                   mismatches=mismatches)


def evaluate(cases: tuple[Case, ...] = CASES) -> list[Outcome]:
    return [check(case) for case in cases]

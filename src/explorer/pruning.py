"""Why a candidate is pruned, and the permitted alternatives near it (issue #74).

The roadmap's agent chain is "why is this candidate pruned?" -> "show permitted
alternatives" -> "minimize this accepted contrast". This module answers the first two;
the MCP tools ``why_pruned`` and ``permitted_alternatives`` wrap it.

**Why pruned** (``why_pruned``) runs the stages the campaign planner runs on every
assignment (``planner.Space.assess``), and answers in the planner's terms:
- the candidate's role: ``malformed``, ``pruned``, ``undetermined``, ``unsupported``,
  ``not_run``, ``probe`` or ``supported``;
- the stage that stops it.

Only ``probe`` and ``supported`` candidates are executable. ``undetermined`` ones go to
the review queue, never the default campaign. For each rule behind the verdict it gives
the evidence:
- what the candidate does (the finding's reason);
- the rule's predicate and every cited source (document, section, page, strength,
  what it says, who checked it);
- how ConfigSpace encodes the rule, or why it's left to a P1 predicate;
- the rule's experimental validation (``consistency.rule_validation``, #76): the
  committed runs that break it and the runs its matrix rows cite.

A legal candidate gets P2's evidence instead: values without a passing run, recorded
refusals, an implementation limit.

**Permitted alternatives** (``permitted_alternatives``) change up to ``max_changes``
admitted dimensions (``model.json``) on the candidate itself, so its other settings stay
as they are. They keep only the results that pass the modeled rules (P1 settings, open
questions, action order). Each is minimal: a set of changes is skipped when a smaller set
of the same changes is already permitted, so ``max_changes=2`` adds only the repairs that
need two changes. Ranking:
1. fewest changes;
2. P2 ``SUPPORTED`` first (a committed run did exactly this), then support probes;
3. fewest changed inputs (``contrasts.input_diff``).

A dimension set on every link (``config.ap.links[*]...``) sets all links. An action
dimension set to ``absent`` removes its steps, and ``present`` appends them after the
candidate's own actions. Passing the modeled rules is never full 802.11be compliance, and
an alternative that isn't ``SUPPORTED`` hasn't run.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from explorer import config_space, model_json
from explorer.contrasts import distance, input_diff
from explorer.model import Candidate
from explorer.rules import Citation
from explorer.support import SupportResult, check_support

Role = Literal["malformed", "pruned", "undetermined", "unsupported", "not_run", "probe",
               "supported"]
EXECUTABLE = ("probe", "supported")
MAX_CHANGES = 3
MAX_EXAMPLE_RUNS = 3


# --- the candidate in the campaign space's terms ------------------------------------------


@lru_cache(maxsize=1)
def dimensions() -> dict[str, tuple[str, dict[str, Any]]]:
    """Admitted dimensions (model.json order) -> (path, label -> typed value)."""
    return {d["name"]: model_json.DIMENSIONS[d["name"]]
            for d in model_json.build()["dimensions"]}


def _config_values(config: dict, path: str) -> list[Any]:
    parts = path.split(".")[1:]                 # drop "config"
    targets = [config]
    for part in parts[:-1]:
        if part == "links[*]":
            targets = [link for t in targets for link in t["links"]]
        elif m := re.fullmatch(r"links\[(\d+)\]", part):
            targets = [t["links"][int(m[1])] for t in targets if len(t["links"]) > int(m[1])]
        else:
            targets = [t.get(part, {}) for t in targets]
    return [t.get(parts[-1]) for t in targets]


def current_label(candidate: dict, name: str) -> str:
    """The candidate's value for an admitted dimension as a model.json label, or a
    description when no label fits (e.g. links with different AKM lists)."""
    path, values = dimensions()[name]
    if path == "actions":
        steps = values["present"]
        done = [step in candidate["actions"] for step in steps]
        return "present" if all(done) else "absent" if not any(done) else "partial"
    found = _config_values(candidate["config"], path)
    for label, value in values.items():
        if found and all(v == value for v in found):
            return label
    return "other: " + json.dumps(found[0] if len(found) == 1 else found)


def set_label(candidate: dict, name: str, label: str) -> dict:
    """The candidate with one admitted dimension set to ``label`` (a copy)."""
    path, values = dimensions()[name]
    if path != "actions":
        return model_json.apply({name: label}, base=candidate)
    out = copy.deepcopy(candidate)
    steps = values["present"]
    out["actions"] = [step for step in out["actions"] if step not in steps]
    if label == "present":
        out["actions"] += copy.deepcopy(steps)
    return out


def campaign_assignment(candidate: Candidate) -> dict[str, str] | None:
    """The dimension labels when the candidate is exactly one of the campaign space's
    assignments (the F02 base with each dimension set), else None."""
    data = candidate.model_dump(mode="json")
    choices = {name: current_label(data, name) for name in dimensions()}
    if any(label not in dimensions()[name][1] for name, label in choices.items()):
        return None
    try:
        same = Candidate.model_validate(model_json.apply(choices)) == candidate
    except ValidationError:
        return None
    return choices if same else None


# --- why pruned ------------------------------------------------------------------------------


class RuleEvidence(BaseModel):
    """One finding and the evidence behind its rule."""
    rule_id: str
    stage: str
    outcome: str
    title: str
    kind: str
    """normative / guidance / dependency / harness / policy, open_question, or format."""
    reason: str
    """What this candidate does, in its own fields."""
    predicate: str | None
    sources: list[Citation]
    """Every cited source, with section, page, strength and who checked it."""
    configspace: str | None
    """How ConfigSpace encodes the rule, or why it stays a P1 predicate; None for P0
    errors, open questions and action-order rules."""
    validation: str | None
    """From rules/validation.json (#76): broken_in_a_run, cited_runs_only or none."""
    runs_breaking_it: list[str]
    """Committed runs that break the rule today (up to 3), as "folder (test result)"."""
    cited_runs: list[str]
    """Runs the rule's spec_coverage.csv rows cite (up to 3)."""


class PruneExplanation(BaseModel):
    role: Role
    """The planner's role for it; only probe and supported are executable."""
    pruned: bool
    """True when the default campaign wouldn't run it (every role but probe / supported)."""
    stage: Literal["P0", "P1", "P2"] | None
    """The stage that stops it, or None when it's executable."""
    status: str
    """validate_candidate's P0/P1 status."""
    findings: list[RuleEvidence]
    p2: SupportResult | None
    """P2's evidence, for a candidate that passes the modeled rules."""
    campaign_assignment: dict[str, str] | None
    """Its dimension labels when it's exactly one of the campaign space's assignments
    (planner.Space), so pruning_counts.json counted it the same way."""
    note: str


@lru_cache(maxsize=1)
def _validation() -> dict:
    from explorer.consistency import rule_validation
    return {entry.id: entry for entry in rule_validation()}


def _configspace(rule_id: str) -> str | None:
    encoded = [c.describe() for c in config_space.constraints() if c.rule_id == rule_id]
    if encoded:
        return "ConfigSpace " + "; ".join(encoded)
    if rule_id in config_space.PREDICATE_ONLY:
        return "P1 predicate only: " + config_space.PREDICATE_ONLY[rule_id]
    return None


def _evidence(finding) -> RuleEvidence:
    from explorer.validate import cached_rules
    if finding.stage == "P0":
        return RuleEvidence(rule_id=finding.rule_id, stage="P0", outcome=finding.outcome,
                            title=finding.title, kind=finding.kind, reason=finding.reason,
                            predicate=None, sources=[], configspace=None, validation=None,
                            runs_breaking_it=[], cited_runs=[])
    entry = cached_rules().get(finding.rule_id)
    checked = _validation().get(finding.rule_id)
    return RuleEvidence(
        rule_id=finding.rule_id, stage=finding.stage, outcome=finding.outcome,
        title=finding.title, kind=finding.kind, reason=finding.reason,
        predicate=getattr(entry, "predicate", None), sources=list(entry.sources),
        configspace=_configspace(finding.rule_id),
        validation=checked.validation if checked else None,
        runs_breaking_it=[f"{r.run} ({r.test} {r.result})"
                          for r in (checked.broken_in_runs if checked else [])][:MAX_EXAMPLE_RUNS],
        cited_runs=(checked.cited_runs if checked else [])[:MAX_EXAMPLE_RUNS])


_ROLE_NOTES = {
    "malformed": "Pruned at P0: it doesn't fit the model, so no rule was checked.",
    "pruned": "Pruned at P1: the modeled rules listed reject it.",
    "undetermined": ("Held at P1: an open question (UND.*) applies, so it goes to the review "
                     "queue, never the default campaign. Neither approved nor a violation."),
    "unsupported": ("Pruned at P2: it matches an implementation limit with recorded refusals "
                    "(p2.limit). Not a Wi-Fi rule."),
    "not_run": ("Pruned at P2: it passes the modeled rules, but some of its values have no "
                "passing committed run (p2.values with no run_ids), so the campaign doesn't "
                "run it."),
    "probe": ("Not pruned: it passes the modeled rules and every value has a passing run, "
              "though not this combination; the campaign may run it as a support probe."),
    "supported": "Not pruned: a committed run executed exactly this candidate (p2.run_ids).",
}


def why_pruned(data: object) -> PruneExplanation:
    """Why the campaign would prune a candidate (raw JSON, as validate_candidate takes),
    with the evidence behind each rule; see the module docstring."""
    from explorer.validate import validate_candidate
    result = validate_candidate(data)
    candidate = None
    if result.status == "MALFORMED":
        role: Role = "malformed"
    elif result.status == "SPEC_UNDETERMINED":
        role = "undetermined"
    elif result.status != "PASSES_MODELED_RULES":
        role = "pruned"
    else:
        support = result.p2
        role = ("supported" if support.status == "SUPPORTED" else
                "unsupported" if support.status == "UNSUPPORTED_IMPLEMENTATION" else
                "probe" if support.all_values_evidenced else "not_run")
    if role != "malformed":
        candidate = Candidate.model_validate(data)
    stage = {"malformed": "P0", "pruned": "P1", "undetermined": "P1", "unsupported": "P2",
             "not_run": "P2"}.get(role)
    note = _ROLE_NOTES[role]
    if any(f.kind in ("harness", "policy") for f in result.findings):
        note += (" AO.* and other harness/policy rules keep candidates meaningful for our "
                 "experiments; they aren't Wi-Fi specification rules.")
    return PruneExplanation(
        role=role, pruned=role not in EXECUTABLE, stage=stage, status=result.status,
        findings=[_evidence(f) for f in result.findings], p2=result.p2,
        campaign_assignment=campaign_assignment(candidate) if candidate else None,
        note=note)


# --- permitted alternatives ------------------------------------------------------------------


class Change(BaseModel):
    dimension: str
    path: str
    old: str
    """The candidate's current label (or a description when no label fits)."""
    new: str


class Alternative(BaseModel):
    changes: list[Change]
    inputs_changed: dict[str, list[Any]]
    """contrasts.input_diff(original, alternative): each changed value or action step."""
    distance: int
    p2_status: str
    run_ids: list[str]
    """For SUPPORTED: the committed runs that executed it (run it again with run_candidate)."""
    executable: bool
    """SUPPORTED, or a support probe (every value has a passing run)."""
    missing: list[str]
    """Values with no passing committed run (UNRESOLVED only)."""
    candidate: dict
    """The alternative itself, ready for validate_candidate / run_candidate."""


class AlternativesResult(BaseModel):
    original_status: str
    original_findings: list[str]
    """The rule IDs the original candidate trips (empty when it passes)."""
    max_changes: int
    considered: int
    """Distinct candidates tried within max_changes."""
    permitted: int
    """How many of them pass the modeled rules."""
    executable: int
    """How many permitted ones are SUPPORTED or support probes."""
    alternatives: list[Alternative]
    """The best ``limit`` of them, ranked as the module docstring says."""
    note: str


def permitted_alternatives(data: object, max_changes: int = 1,
                           limit: int = 10) -> AlternativesResult:
    """Candidates that pass the modeled rules within ``max_changes`` admitted-dimension
    changes of ``data``. Raises ValueError for a malformed candidate or bad arguments."""
    from explorer.validate import (check_action_order, find_undetermined, p1_status,
                                   parse_candidate, run_p1_checks)
    if not 1 <= max_changes <= MAX_CHANGES:
        raise ValueError(f"max_changes must be 1-{MAX_CHANGES}")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    parsed, malformed = parse_candidate(data)
    if parsed is None:
        raise ValueError("malformed candidate (fix it first; validate_candidate explains): "
                         + "; ".join(f"{f.rule_id}: {f.reason}" for f in malformed))
    original = parsed.model_dump(mode="json")

    def findings(candidate: Candidate) -> list:
        return (run_p1_checks(candidate.config) + find_undetermined(candidate.config)
                + check_action_order(candidate))

    original_findings = findings(parsed)
    names = list(dimensions())
    current = {name: current_label(original, name) for name in names}
    seen = {json.dumps(original, sort_keys=True)}
    found: list[tuple[tuple, Alternative]] = []
    permitted_changes: set[frozenset] = set()
    considered = 0
    for k in range(1, max_changes + 1):
        for chosen in itertools.combinations(names, k):
            options = [[label for label in dimensions()[n][1] if label != current[n]]
                       for n in chosen]
            for labels in itertools.product(*options):
                change_set = frozenset(zip(chosen, labels))
                if any(smaller < change_set for smaller in permitted_changes):
                    continue  # a subset of these changes is already permitted: not minimal
                data_alt = original
                for name, label in zip(chosen, labels):
                    data_alt = set_label(data_alt, name, label)
                try:
                    candidate = Candidate.model_validate(data_alt)
                except ValidationError:
                    continue
                key = json.dumps(candidate.model_dump(mode="json"), sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                considered += 1
                if p1_status(findings(candidate)) != "PASSES_MODELED_RULES":
                    continue
                permitted_changes.add(change_set)
                support = check_support(candidate)
                as_json = candidate.model_dump(mode="json")
                diff = input_diff(original, as_json)
                executable = support.status == "SUPPORTED" or (
                    support.status == "UNRESOLVED" and support.all_values_evidenced)
                alt = Alternative(
                    changes=[Change(dimension=n, path=dimensions()[n][0], old=current[n],
                                    new=label) for n, label in zip(chosen, labels)],
                    inputs_changed=diff, distance=distance(diff), p2_status=support.status,
                    run_ids=support.run_ids, executable=executable,
                    missing=[f"{v.candidate}={v.value}" for v in support.values
                             if not v.run_ids],
                    candidate=as_json)
                rank = (k, support.status != "SUPPORTED", not executable, alt.distance,
                        [names.index(n) for n in chosen], list(labels))
                found.append((rank, alt))
    found.sort(key=lambda pair: pair[0])
    status = p1_status(original_findings)
    if found:
        note = (f"{len(found)} of {considered} candidates within {max_changes} change(s) pass "
                "the modeled rules (not full 802.11be compliance). SUPPORTED ones have run "
                "exactly as shown; the others haven't, and executable=false means some value "
                "has no passing run yet.")
    else:
        note = (f"None of the {considered} candidates within {max_changes} change(s) pass the "
                "modeled rules; try a larger max_changes. Only admitted dimensions are "
                "changed, so a problem in a fixed setting (e.g. the link layout) can't be "
                "fixed here.")
    return AlternativesResult(
        original_status=status,
        original_findings=sorted({f.rule_id for f in original_findings}),
        max_changes=max_changes, considered=considered, permitted=len(found),
        executable=sum(alt.executable for _, alt in found),
        alternatives=[alt for _, alt in found[:limit]], note=note)

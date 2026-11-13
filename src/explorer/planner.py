"""Campaign planner (issue #66): a bounded pairwise campaign over legal candidates.

The candidate space is the F02 base (``model_json.BASE_TEST``) with each admitted
dimension of ``model.json`` set to one of its labels (``model_json.apply``). It is small
(the product of the dimensions' value counts, 4608 today), so the planner enumerates it
once and checks every full assignment with the real stages, before any guest launches:

- **P0**: the candidate parses (``model.Candidate``).
- **ConfigSpace** (``explorer.config_space``, #63): the static settings' conditions and
  forbidden clauses, each tagged with its rule. Recorded per assignment and counted in the
  funnel; ``tests/test_config_space.py`` keeps it in agreement with the P1 predicates.
- **P1**: today's modeled rules: setting rules, open questions and action order (the
  ConfigSpace rules among them, plus what ConfigSpace leaves to predicates).
  ``SPEC_RULE_VIOLATION`` assignments are pruned with their rule IDs;
  ``SPEC_UNDETERMINED`` ones go to a separate review queue, never the default campaign.
- **P2**: ``support.check_support``. Only ``SUPPORTED`` candidates and support probes
  (``UNRESOLVED`` with ``all_values_evidenced``, decided in #80) are executable; others are
  counted as not run.

allpairspy generates the pairwise design over the executable assignments. Its filter sees
partial rows and rejects one only if no executable assignment starts with it (an exact
legal-completion check, since the whole space is enumerated), never because a field isn't
filled in yet. allpairspy stops when its greedy step can't extend a row under the filter,
which leaves some feasible pairs uncovered, so the planner checks the achieved coverage
itself, as the roadmap asks, and tops it up: it adds the executable assignment that
covers the most still-uncovered pairs (ties: the first in the seeded order) until every
executable pair is planned. The seed shuffles each dimension's value order before
allpairspy runs, so a seed always gives the same plan.

Coverage (``coverage``) has two denominators, as the roadmap asks: pairs feasible after
P0/P1 (modeled-admissible) and pairs feasible after P2 (executable). A pair counts as
covered only once a candidate containing it has really run: today that means a committed
legal ACCEPTED run of exactly that candidate (P2 ``SUPPORTED``); after the campaign (#68)
its ACCEPTED runs are passed in. Planned pairs are reported separately and never counted
as covered. Each infeasible pair lists the rules that reject every assignment containing
it.

The planner enumerates rather than sampling ConfigSpace because the actions are part of
each assignment and stay out of ConfigSpace (the roadmap's split), and because at this size
enumeration is exact.
"""

from __future__ import annotations

import itertools
import json
import random
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property

from allpairspy import AllPairs
from pydantic import ValidationError

from explorer import config_space, model_json
from explorer.model import Candidate

REPO_ROOT = model_json.REPO_ROOT
CAMPAIGN_PLAN = REPO_ROOT / "campaign_plan.json"
PAIRWISE_COVERAGE = REPO_ROOT / "pairwise_coverage.json"
DEFAULT_BUDGET = 20
STRENGTH = 2  # pairwise; allpairspy's n

Row = tuple[str, ...]                             # one label per dimension, in Space.names order
Pair = tuple[tuple[str, str], tuple[str, str]]    # ((dim, label), (dim, label))


@dataclass
class Assessment:
    """What the stages say about one full assignment."""
    row: Row
    candidate: Candidate | None
    p0_errors: list[str] = field(default_factory=list)
    configspace_rule_ids: list[str] = field(default_factory=list)   # [] = ConfigSpace-valid
    p1_status: str | None = None          # PASSES_MODELED_RULES / SPEC_RULE_VIOLATION / ...
    rule_ids: list[str] = field(default_factory=list)
    p2_status: str | None = None          # SUPPORTED / UNRESOLVED
    all_values_evidenced: bool = False
    run_ids: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def legal(self) -> bool:
        return self.p1_status == "PASSES_MODELED_RULES"

    @property
    def executable(self) -> bool:
        return self.legal and (self.p2_status == "SUPPORTED" or self.all_values_evidenced)

    @property
    def role(self) -> str:
        if self.candidate is None:
            return "malformed"
        if not self.legal:
            return "undetermined" if self.p1_status == "SPEC_UNDETERMINED" else "pruned"
        if self.p2_status == "SUPPORTED":
            return "supported"
        return "probe" if self.all_values_evidenced else "not_run"


class Space:
    """The enumerated candidate space and each assignment's P0/P1/P2 verdict."""

    def __init__(self, model: dict | None = None):
        self.model = model or model_json.build()
        self.names = [d["name"] for d in self.model["dimensions"]]
        self.labels = [[v["label"] for v in d["values"]] for d in self.model["dimensions"]]

    def choices(self, row: Row) -> dict[str, str]:
        return dict(zip(self.names, row))

    def static(self, row: Row) -> dict[str, str]:
        """The row's ConfigSpace hyperparameter values: its setting dimensions, and the
        base's fixed settings (beacon protection on at both ends)."""
        hps = config_space.hyperparameter_values()
        values = {name: label for name, label in self.choices(row).items() if name in hps}
        values.update({name: "1" for name in config_space.FIXED_SETTINGS})
        return values

    def assess(self, row: Row) -> Assessment:
        from explorer.support import check_support
        from explorer.validate import (check_action_order, find_undetermined, p1_status,
                                       run_p1_checks)
        try:
            candidate = Candidate.model_validate(model_json.apply(self.choices(row)))
        except ValidationError as exc:
            return Assessment(row, None, p0_errors=[e["msg"] for e in exc.errors()])
        findings = (run_p1_checks(candidate.config) + find_undetermined(candidate.config)
                    + check_action_order(candidate))
        result = Assessment(row, candidate, p1_status=p1_status(findings),
                            rule_ids=sorted({f.rule_id for f in findings}),
                            configspace_rule_ids=config_space.violations(self.static(row)))
        if result.legal:
            support = check_support(candidate)
            result.p2_status = support.status
            result.all_values_evidenced = support.all_values_evidenced
            result.run_ids = support.run_ids
            result.missing = [f"{v.candidate}={v.value}" for v in support.values if not v.run_ids]
        return result

    @cached_property
    def assessments(self) -> dict[Row, Assessment]:
        return {row: self.assess(row) for row in itertools.product(*self.labels)}

    def rows(self, predicate) -> list[Row]:
        return [row for row, a in self.assessments.items() if predicate(a)]

    def pairs(self, row: Row) -> set[Pair]:
        return {((self.names[i], row[i]), (self.names[j], row[j]))
                for i, j in itertools.combinations(range(len(row)), 2)}

    def all_pairs(self) -> set[Pair]:
        return {((self.names[i], a), (self.names[j], b))
                for i, j in itertools.combinations(range(len(self.names)), 2)
                for a in self.labels[i] for b in self.labels[j]}

    def pairs_of(self, rows) -> set[Pair]:
        return set().union(*(self.pairs(r) for r in rows)) if rows else set()


def prefix_filter(space: Space):
    """allpairspy's filter_func: it gets the row built so far (the first k dimensions)
    and keeps it only if some executable assignment starts with it. A partial row is never
    rejected for what it leaves out, only when no legal, executable completion exists."""
    prefixes = {row[:k] for row in space.rows(lambda a: a.executable)
                for k in range(len(row) + 1)}
    return lambda partial: tuple(partial) in prefixes


def design(space: Space, seed: int) -> list[tuple[Row, str]]:
    """The seeded pairwise design over the executable assignments: allpairspy's rows,
    then the top-up that covers the pairs it left. Each row is tagged with its source."""
    executable = space.rows(lambda a: a.executable)
    rng = random.Random(seed)
    labels = [rng.sample(values, len(values)) for values in space.labels]
    extendable = prefix_filter(space)

    rows = [(tuple(r), "allpairspy")
            for r in AllPairs(labels, filter_func=extendable, n=STRENGTH)]
    target = space.pairs_of(executable)
    covered = space.pairs_of([r for r, _ in rows])
    # The whole space in the seeded order, so ties in the top-up are reproducible.
    order = sorted(executable, key=lambda r: [labels[i].index(v) for i, v in enumerate(r)])
    while not target <= covered:
        planned = {r for r, _ in rows}
        best = max((r for r in order if r not in planned),
                   key=lambda r: len(space.pairs(r) & (target - covered)))
        rows.append((best, "top_up"))
        covered |= space.pairs(best)
    return rows


def _infeasible(space: Space, feasible: set[Pair]) -> list[dict]:
    """Pairs no legal assignment has, with the rules that reject every assignment that
    has them (or, if no single rule does, every rule that rejects one of them)."""
    out = []
    for pair in sorted(space.all_pairs() - feasible):
        (d1, v1), (d2, v2) = pair
        i, j = space.names.index(d1), space.names.index(d2)
        rows = [a for row, a in space.assessments.items() if row[i] == v1 and row[j] == v2]
        common = set.intersection(*(set(a.rule_ids) for a in rows))
        out.append({"pair": {d1: v1, d2: v2},
                    "assignments": len(rows),
                    "statuses": dict(Counter(a.p1_status or "MALFORMED" for a in rows)),
                    "rule_ids": sorted(common) or sorted(set().union(*(a.rule_ids for a in rows))),
                    "every_assignment_rejected_by_these": bool(common)})
    return out


def coverage(space: Space, plan_rows: list[Row], ran_rows: list[Row]) -> dict:
    """Pairwise coverage with both denominators. ``ran_rows``: assignments with a real
    ACCEPTED legal run (only these cover pairs). ``plan_rows``: planned, reported apart."""
    legal = space.rows(lambda a: a.legal)
    executable = space.rows(lambda a: a.executable)
    covered = space.pairs_of(ran_rows)
    planned = space.pairs_of(plan_rows)

    def block(feasible: set[Pair]) -> dict:
        ratio = (lambda n: round(n / len(feasible), 4) if feasible else None)
        return {"feasible_pairs": len(feasible),
                "covered_feasible_pairs": len(covered & feasible),
                "pairwise_coverage": ratio(len(covered & feasible)),
                "planned_feasible_pairs": len(planned & feasible),
                "planned_pairwise_coverage": ratio(len(planned & feasible))}

    feasible_p1, feasible_p2 = space.pairs_of(legal), space.pairs_of(executable)
    return {
        "strength": STRENGTH,
        "dimensions": space.names,
        "all_pairs": len(space.all_pairs()),
        "modeled_admissible": block(feasible_p1),
        "executable": block(feasible_p2),
        "infeasible_pairs": _infeasible(space, feasible_p1),
        "admissible_but_not_executable_pairs": [dict(p) for p in sorted(feasible_p1 - feasible_p2)],
        "covered_by": [{"choices": space.choices(r),
                        "run_ids": space.assessments[r].run_ids} for r in ran_rows],
    }


def plan(seed: int = 0, budget: int = DEFAULT_BUDGET, space: Space | None = None) -> dict:
    """The campaign plan for one seed (see the module docstring). At most ``budget``
    candidates; if the design needs more, the rest are reported as cut, not dropped
    silently."""
    space = space or Space()
    model = space.model
    rows = design(space, seed)
    kept, cut = rows[:budget], rows[budget:]
    statuses = Counter(a.p1_status or "MALFORMED" for a in space.assessments.values())
    rules = Counter(rule for a in space.assessments.values() if not a.legal
                    for rule in a.rule_ids)
    roles = Counter(a.role for a in space.assessments.values())

    def entry(index: int, row: Row, source: str) -> dict:
        a = space.assessments[row]
        return {"id": f"c{index:02d}", "source": source, "choices": space.choices(row),
                "candidate": a.candidate.model_dump(mode="json"),
                "p1": a.p1_status, "p2": a.p2_status, "role": a.role,
                "all_values_evidenced": a.all_values_evidenced,
                "previous_runs": a.run_ids}

    return {
        "description": ("Pairwise campaign plan over the legal, executable candidates of "
                        "model.json (issue #66). Generated by scripts/plan_campaign.py; "
                        "nothing here has run. A planned pair counts as covered only after "
                        "its candidate runs (#68)."),
        "generated_by": "scripts/plan_campaign.py",
        "seed": seed,
        "budget": budget,
        "strength": STRENGTH,
        "model": {key: model[key] for key in ("schema_version", "rules_version",
                                               "model_digest", "pinned_versions")},
        "base": model_json.BASE_TEST,
        "dimensions": [{"name": n, "labels": l} for n, l in zip(space.names, space.labels)],
        "funnel": {
            "enumerated": len(space.assessments),
            "p0_well_formed": sum(a.candidate is not None for a in space.assessments.values()),
            "configspace": {
                "valid": sum(not a.configspace_rule_ids for a in space.assessments.values()),
                "rejected": sum(bool(a.configspace_rule_ids) for a in space.assessments.values()),
                "rejections_by_rule": dict(sorted(Counter(
                    rule for a in space.assessments.values()
                    for rule in a.configspace_rule_ids).items())),
            },
            "p1": dict(sorted(statuses.items())),
            "p1_rejections_by_rule": dict(sorted(rules.items())),
            "p2": {"supported": roles["supported"], "probe": roles["probe"],
                   "not_run": roles["not_run"]},
            "executable": roles["supported"] + roles["probe"],
            "planned": len(kept),
            "allpairspy_rows": sum(source == "allpairspy" for _, source in rows),
            "top_up_rows": sum(source == "top_up" for _, source in rows),
            "cut_by_budget": len(cut),
        },
        "candidates": [entry(i, row, source) for i, (row, source) in enumerate(kept, 1)],
        "cut_by_budget": [space.choices(row) for row, _ in cut],
        "review_queue": [{"choices": space.choices(r), "rule_ids": space.assessments[r].rule_ids}
                         for r in space.rows(lambda a: a.p1_status == "SPEC_UNDETERMINED")],
    }


def write(seed: int = 0, budget: int = DEFAULT_BUDGET) -> tuple[dict, dict]:
    """Write campaign_plan.json and pairwise_coverage.json at the repo root."""
    space = Space()
    campaign = plan(seed, budget, space)
    plan_rows = [tuple(c["choices"][n] for n in space.names) for c in campaign["candidates"]]
    ran = space.rows(lambda a: a.legal and a.p2_status == "SUPPORTED")
    cover = coverage(space, plan_rows, ran)
    cover["description"] = (
        "Pairwise coverage of the admitted dimensions (issue #66): feasible pairs after "
        "P0/P1 (modeled_admissible) and after P2 (executable). covered_* counts only "
        "candidates with a committed legal ACCEPTED run of exactly that candidate (P2 "
        "SUPPORTED); planned_* is campaign_plan.json, not yet run. Infeasible pairs list "
        "the rules that rule them out.")
    cover["seed"] = seed
    cover["model_digest"] = space.model["model_digest"]
    for path, data in ((CAMPAIGN_PLAN, campaign), (PAIRWISE_COVERAGE, cover)):
        path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return campaign, cover

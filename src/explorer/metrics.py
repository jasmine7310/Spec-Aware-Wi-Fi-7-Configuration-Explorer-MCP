"""Evaluation metrics (issue #115): the numbers the Checkpoint 3 report quotes, generated
from committed files so they can be re-checked.

``build()`` reads the repo and returns ``metrics.json``'s content; ``scripts/build_metrics.py``
writes it, and ``tests/test_metrics.py`` fails when the committed file is stale. Nothing
here boots a guest or invents a number: each block names where it comes from.

- ``space``: the planner's enumeration of the admitted dimensions (``planner.Space``):
  how many assignments each stage stops, so the guest boots pruning avoids. P0 stops none
  here by construction (every assignment is built from model.json's typed values); the
  counterexample suite shows what P0 catches in free-form input.
- ``no_p1_estimate``: what a campaign of the same budget would waste without P1, **by
  estimate, never by runs** (running P1-rejected candidates would be a negative
  experiment). The exact expectation from the space's shares, and a seeded sample of
  P0-well-formed assignments classified by P1 and P2.
- ``campaigns``: each committed campaign's guest boots, cache hits, P3 statuses, distinct
  signatures of its ``ACCEPTED`` runs (``campaign.outcome_stages``) and wall-clock time.
  The signatures include the ``station_status`` config echo; ``station_status_echo``
  gives the counts without it. ``held_out`` names the fresh campaign run on the frozen
  versions (#114), started after the freeze, once one is committed.
- ``pairwise``: ``pairwise_coverage.json``'s feasible pairs covered by committed runs.
- ``counterexamples``: the #108 suite: invalid cases caught at the expected stage, and
  permitted cases wrongly pruned by a rule (out of ``permitted_cases``).
- ``audit``: ``docs/rule-audit.md``'s (#109) per-rule prune / admit risk and its findings
  by disposition (fixture, issue, stated limit). Rules with a prune risk are split into
  ``possible_false_prunes`` (low or reading-dependent) and ``pruned_by_design``.
- ``undetermined``: ``SPEC_UNDETERMINED`` in the space, the suite and the registry.
- ``cache``: cache hits in the campaigns and in each minimization's probes.
- ``timing``: mean checker time per assignment and stage over the whole space, next to
  a guest boot's. Measured when the file is written, on the machine it records, so it
  varies by machine; the staleness test ignores it.
"""

from __future__ import annotations

import json
import platform
import random
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
METRICS_JSON = REPO_ROOT / "metrics.json"
AUDIT = REPO_ROOT / "docs" / "rule-audit.md"
PAIRWISE = REPO_ROOT / "pairwise_coverage.json"
SAMPLE_SEED = 0
UNTIMED = ("timing",)
"""Blocks that depend on the machine, left out of the staleness check."""


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


# --- the enumerated space ------------------------------------------------------------

def space_block(space) -> dict:
    roles = Counter(a.role for a in space.assessments.values())
    statuses = Counter(a.p1_status or "MALFORMED" for a in space.assessments.values())
    rules = Counter(r for a in space.assessments.values()
                    if a.p1_status == "SPEC_RULE_VIOLATION" for r in a.rule_ids)
    enumerated = len(space.assessments)
    well_formed = enumerated - statuses["MALFORMED"]
    passes = statuses["PASSES_MODELED_RULES"]
    unsupported = roles["unsupported"]
    executable = roles["probe"] + roles["supported"]
    return {
        "source": "planner.Space() over model.json's admitted dimensions",
        "dimensions": len(space.names),
        "enumerated": enumerated,
        "p0_well_formed": well_formed,
        "p1": {"passes_modeled_rules": passes,
               "spec_rule_violation": statuses["SPEC_RULE_VIOLATION"],
               "spec_undetermined": statuses["SPEC_UNDETERMINED"],
               "rejections_by_rule": dict(sorted(rules.items()))},
        "p2": {"unsupported_implementation": unsupported,
               "not_run": roles["not_run"], "executable": executable,
               "supported": roles["supported"], "probe": roles["probe"]},
        "guest_boots_avoided": {
            "by_p0": enumerated - well_formed,
            "by_p1": well_formed - passes,
            "by_p2": passes - executable,
            "total": enumerated - executable,
            "share_of_enumerated": _share(enumerated - executable, enumerated)},
    }


def no_p1_estimate(space, budget: int, seed: int = SAMPLE_SEED) -> dict:
    """The same budget spent on P0-well-formed assignments without P1 (an estimate)."""
    well_formed = [a for a in space.assessments.values() if a.candidate is not None]
    rejected = [a for a in well_formed if a.p1_status != "PASSES_MODELED_RULES"]
    unsupported = [a for a in well_formed if a.role == "unsupported"]
    picks = random.Random(seed).sample(well_formed, min(budget, len(well_formed)))
    sample = Counter("p1_rejected" if a.p1_status != "PASSES_MODELED_RULES"
                     else "p2_unsupported" if a.role == "unsupported"
                     else "not_run" if a.role == "not_run" else "executable" for a in picks)
    return {
        "note": ("An estimate, not runs: running P1-rejected candidates would be a negative "
                 "experiment. Without P1, a pick is a uniformly random P0-well-formed "
                 "assignment."),
        "budget": budget,
        "population": len(well_formed),
        "p1_rejected_share": _share(len(rejected), len(well_formed)),
        "expected_wasted_boots": round(budget * len(rejected) / len(well_formed), 2),
        "expected_p2_unsupported_boots": round(budget * len(unsupported) / len(well_formed), 2),
        "sample": {"seed": seed, "picks": len(picks),
                   **{k: sample[k] for k in ("p1_rejected", "p2_unsupported", "not_run",
                                              "executable")}},
    }


# --- campaigns ---------------------------------------------------------------------

def _seconds(start: str, end: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (datetime.strptime(end, fmt) - datetime.strptime(start, fmt)).total_seconds()


ECHO = "station_status"
"""The fact that echoes the configured AKM and ciphers; counted in the signatures."""


def _echo_block(campaign_dir: Path) -> dict:
    """How much of ``outcome_stages``' counts comes from the ``station_status`` echo:
    the distinct signatures without it, and the pairs that differ only in it."""
    from explorer import contrasts
    runs = contrasts.accepted_runs([campaign_dir])
    signatures = {json.dumps({k: v for k, v in run.facts.items() if k != ECHO},
                             sort_keys=True) for _, run in runs}
    pairs = contrasts.find(contrasts.group(runs), 10**6, supported=lambda _: True)
    return {"distinct_signatures_without_it": len(signatures),
            "pairs_differing_only_in_it": sum(all(f.fact == ECHO for f in c.facts)
                                              for c in pairs)}


def campaign_block(campaign_dir: Path) -> dict:
    from explorer import campaign
    results = json.loads((campaign_dir / "results.json").read_text())
    counts = json.loads((campaign_dir / "pruning_counts.json").read_text())
    plan = json.loads((campaign_dir / "campaign_plan.json").read_text())
    stages = campaign.outcome_stages(campaign_dir)
    boots = counts["executed"]["guest_boots"]
    seconds = _seconds(results["started_at"], results["finished_at"])
    return {
        "id": campaign_dir.name,
        "seed": results["seed"],
        "started_at": results["started_at"],
        # The campaign's own plan says how it was planned; None when it didn't record it.
        # ``fresh`` (no cache reads) exists since #114; earlier campaigns read the cache.
        "mode": {"build_on_runs": results.get("build_on_runs", plan.get("build_on_runs")),
                 "fresh": results.get("fresh", False)},
        "model_digest": results["model_digest"],
        "planned": len(results["results"]),
        "guest_boots": boots,
        "cache_hits": counts["executed"]["cache_hits"],
        "retries": counts["executed"]["retries"],
        "p3": counts["P3"],
        "not_run_at_launch": counts["not_run_at_launch"],
        "accepted_runs": stages["accepted_runs"],
        "distinct_signatures": stages["distinct_signatures"],
        "signature_yield_per_boot": _share(stages["distinct_signatures"], boots),
        "contrasts": stages["contrasts"],
        "station_status_echo": _echo_block(campaign_dir),
        "wall_clock_s": seconds,
        "seconds_per_boot": round(seconds / boots, 1) if boots else None,
    }


def _held_out(campaigns: list[dict]) -> dict:
    from explorer import freeze
    frozen = (json.loads(freeze.FREEZE_JSON.read_text()) if freeze.FREEZE_JSON.is_file()
              else None)
    differences = freeze.differences(frozen) if frozen else None
    # Held out: a fresh campaign, on the frozen model, started after the freeze, while
    # nothing frozen has changed since (a trial run before the freeze doesn't count).
    on_frozen = [c for c in campaigns if frozen and not differences
                 and c["mode"]["fresh"] and c["model_digest"] == frozen["model_digest"]
                 and c["started_at"] >= frozen["frozen_at"]]
    return {
        "freeze": ({"tag": frozen.get("tag"), "frozen_at": frozen["frozen_at"],
                    "model_digest": frozen["model_digest"],
                    "differences_now": differences} if frozen else None),
        "campaign": on_frozen[-1]["id"] if on_frozen else None,
        "note": ("The fresh campaign (#114: no cache reads) on the frozen model, started "
                 "after the freeze." if on_frozen
                 else "No held-out campaign is committed yet (#114): the per-campaign "
                      "numbers below are the earlier campaigns'. Regenerate after it runs."),
    }


# --- evidence from other issues ---------------------------------------------------

def pairwise_block(path: Path = PAIRWISE) -> dict:
    data = json.loads(path.read_text())
    return {"source": path.name, **{
        name: {"feasible_pairs": data[name]["feasible_pairs"],
               "covered_by_committed_runs": data[name]["covered_feasible_pairs"],
               "coverage": data[name]["pairwise_coverage"]}
        for name in ("modeled_admissible", "executable")},
        "infeasible_pairs": len(data["infeasible_pairs"])}


PRUNED_STATUSES = ("MALFORMED", "SPEC_RULE_VIOLATION", "SPEC_UNDETERMINED")


def counterexample_block() -> dict:
    from explorer import counterexamples
    outcomes = counterexamples.evaluate()
    by_case = {c.name: c for c in counterexamples.CASES}
    invalid = [o for o in outcomes if by_case[o.name].status in PRUNED_STATUSES
               or by_case[o.name].p2 == "UNSUPPORTED_IMPLEMENTATION"]
    permitted = [o for o in outcomes if by_case[o.name].status == "PASSES_MODELED_RULES"
                 and by_case[o.name].p2 is None]
    wrongly_pruned = [o.name for o in permitted if o.status in PRUNED_STATUSES]
    return {
        "source": "explorer.counterexamples (#108)",
        "cases": len(outcomes),
        "passed": sum(o.passed for o in outcomes),
        "roadmap_cases": len({o.roadmap_case for o in outcomes}),
        "invalid_cases": len(invalid),
        "invalid_caught_at_expected_stage": sum(o.passed for o in invalid),
        "invalid_by_stage": dict(Counter(
            "P2" if by_case[o.name].p2 else o.stage_reached for o in invalid)),
        "permitted_cases": len(permitted),
        "permitted_wrongly_pruned": wrongly_pruned,
        "mismatches": {o.name: o.mismatches for o in outcomes if not o.passed},
    }


def _audit_rows(title: str) -> list[list[str]]:
    text = AUDIT.read_text(encoding="utf-8")
    start = text.index(f"\n## {title}\n")
    end = text.find("\n## ", start + 1)
    rows = []
    for line in text[start:end if end != -1 else None].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and len(cells) > 2 and not set(cells[0]) <= set("-# "):
            rows.append(cells)
    return rows[1:] if rows and rows[0][0] in ("ID", "#") else rows


DISPOSITIONS = {"fixture": r"\*\*Fixtures? added", "issue": r"\*\*[Ii]ssue",
                "stated_limit": r"\*\*[Ss]tated limit"}


def audit_block() -> dict:
    rules = [r for r in _audit_rows("Summary") if r[0].startswith("`")]
    findings = [r for r in _audit_rows("Findings") if re.fullmatch(r"F\d+", r[0])]
    risk = lambda cell: re.sub(r"\s*\(.*\)$", "", cell.strip("*")).strip()   # noqa: E731
    disposition = Counter(kind for f in findings for kind, pattern in DISPOSITIONS.items()
                          if re.search(pattern, f[-1]))
    finding_text = {f[0]: f[1] for f in findings}
    # Rules with a prune risk, with the audit's reason (its prune-risk cell and the
    # findings it cites), split by whether the audit prunes them knowingly.
    pruning = [
        {"rule": r[0].strip("`"), "kind": r[1], "prunes_in_campaigns": r[2],
         "prune_risk": r[4].strip("*"),
         "findings": {f: finding_text.get(f) for f in re.findall(r"F\d+", r[6])}}
        for r in rules if risk(r[4]) not in ("none", "n/a")]
    return {
        "source": "docs/rule-audit.md (#109)",
        "rules_and_open_questions": len(rules),
        "prune_risk": dict(sorted(Counter(risk(r[4]) for r in rules).items())),
        "admit_risk": dict(sorted(Counter(risk(r[5]) for r in rules).items())),
        "validation": dict(sorted(Counter(r[3].strip("*") for r in rules).items())),
        "findings": len(findings),
        "findings_by_disposition": dict(sorted(disposition.items())),
        "possible_false_prunes": [p for p in pruning if risk(p["prune_risk"]) != "by design"],
        "pruned_by_design": [p for p in pruning if risk(p["prune_risk"]) == "by design"],
        "note": ("A finding can have several dispositions (e.g. a stated limit and a "
                 "proposed issue). Risks are the audit's reading of each predicate, not "
                 "observed false prunes. possible_false_prunes: rules whose prune risk is "
                 "low or reading-dependent. pruned_by_design: rules that knowingly prune "
                 "candidates the implementation would run (a stated limit, not a bug)."),
    }


def undetermined_block(space_data: dict, suite: dict) -> dict:
    from explorer import counterexamples
    from explorer.rules import load_rules
    return {
        "open_questions": len(load_rules().undetermined),
        "in_campaign_space": space_data["p1"]["spec_undetermined"],
        "in_counterexample_suite": sum(c.status == "SPEC_UNDETERMINED"
                                       for c in counterexamples.CASES),
        "note": ("No admitted value reaches an open question, so the campaign review queue "
                 "is empty; they apply to free-form candidates (MCP) and minimization "
                 "probes.") if space_data["p1"]["spec_undetermined"] == 0 else None,
    }


def cache_block(campaigns: list[dict]) -> dict:
    from explorer import contrasts
    minimizations = {}
    for path in sorted(contrasts.CONTRASTS_DIR.glob("*/reduction.json")):
        data = json.loads(path.read_text())
        red, verification = data["reduction"], data.get("verification") or {}
        minimizations[path.parent.name] = {
            "probes": len(red["trace"]), "guest_runs": red["guest_runs"],
            "cache_hits": red["cache_hits"],
            "verification_runs": len(verification.get("baseline", []))
            + len(verification.get("minimal", []))}
    probe_hits = sum(m["cache_hits"] for m in minimizations.values())
    probes = sum(m["probes"] for m in minimizations.values())
    return {
        "campaign_cache_hits": sum(c["cache_hits"] for c in campaigns),
        "campaign_guest_boots": sum(c["guest_boots"] for c in campaigns),
        "minimizations": minimizations,
        "minimization_probe_cache_hits": probe_hits,
        "minimization_probes": probes,
        "note": ("A cache hit is never counted as an independent run; verification and replay "
                 "runs are always forced fresh."),
    }


def runtime_block(campaigns: list[dict], cache: dict) -> dict:
    boots = sum(c["guest_boots"] for c in campaigns)
    seconds = sum(c["wall_clock_s"] for c in campaigns)
    return {
        "campaign_guest_boots": boots,
        "campaign_wall_clock_s": seconds,
        "mean_seconds_per_boot": round(seconds / boots, 1) if boots else None,
        "minimization_guest_runs": sum(m["guest_runs"] for m in cache["minimizations"].values()),
        "verification_guest_runs": sum(m["verification_runs"]
                                       for m in cache["minimizations"].values()),
        "note": "Wall clock includes guest setup and the adapter's observations.",
    }


# --- checker timing (not part of the staleness check) -----------------------------

def timing_block(space, seconds_per_boot: float | None) -> dict:
    """Mean time per assignment of each checking stage over the whole space."""
    from pydantic import ValidationError

    from explorer import config_space, model_json
    from explorer.model import Candidate
    from explorer.support import check_support
    from explorer.validate import check_action_order, find_undetermined, run_p1_checks
    totals = Counter()
    count = Counter()
    for row in space.assessments:
        t0 = time.perf_counter()
        try:
            candidate = Candidate.model_validate(model_json.apply(space.choices(row)))
        except ValidationError:
            totals["p0"] += time.perf_counter() - t0
            count["p0"] += 1
            continue
        t1 = time.perf_counter()
        config_space.violations(space.static(row))
        t2 = time.perf_counter()
        findings = (run_p1_checks(candidate.config) + find_undetermined(candidate.config)
                    + check_action_order(candidate))
        t3 = time.perf_counter()
        totals["p0"] += t1 - t0
        totals["configspace"] += t2 - t1
        totals["p1"] += t3 - t2
        count.update(["p0", "configspace", "p1"])
        if not any(f.outcome == "SPEC_RULE_VIOLATION" for f in findings):
            check_support(candidate)
            totals["p2"] += time.perf_counter() - t3
            count["p2"] += 1
    mean_ms = {stage: round(1000 * totals[stage] / count[stage], 3) for stage in totals}
    per_candidate_ms = round(sum(mean_ms.values()), 3)
    return {
        "note": ("Measured when metrics.json was written, on the machine named in "
                 "'machine'; not part of the staleness check. P2 is timed only for "
                 "assignments P1 passes, so mean_ms_per_assignment's P2 is over fewer "
                 "assignments than the other stages. ms_per_assignment_reaching_p2 sums the "
                 "stage means (one assignment through every stage); ms_per_assignment_over_"
                 "space is the total time over every enumerated assignment. "
                 "checks_per_guest_boot divides the campaigns' mean seconds per boot "
                 "(runtime, measured on the machines the campaigns ran on) by "
                 "ms_per_assignment_reaching_p2, so it mixes two machines when they differ."),
        "machine": {"platform": platform.platform(), "python": platform.python_version()},
        "mean_ms_per_assignment": mean_ms,
        "assignments_timed": dict(count),
        "ms_per_assignment_reaching_p2": per_candidate_ms,
        "ms_per_assignment_over_space": round(
            1000 * sum(totals.values()) / len(space.assessments), 3),
        "checks_per_guest_boot": (round(1000 * seconds_per_boot / per_candidate_ms)
                                  if seconds_per_boot and per_candidate_ms else None),
    }


# --- everything -------------------------------------------------------------------

def build(timing: bool = True) -> dict:
    from explorer import campaign, planner
    space = planner.Space()
    space_data = space_block(space)
    campaign_dirs = sorted(d for d in campaign.CAMPAIGNS.glob("*")
                           if (d / "results.json").is_file())
    campaigns = [campaign_block(d) for d in campaign_dirs]
    held_out = _held_out(campaigns)
    headline = next((c for c in campaigns if c["id"] == held_out["campaign"]), None)
    budget = headline["planned"] if headline else planner.DEFAULT_BUDGET
    suite = counterexample_block()
    cache = cache_block(campaigns)
    runtime = runtime_block(campaigns, cache)
    data = {
        "description": ("Evaluation metrics (issue #115), generated by "
                        "scripts/build_metrics.py from committed files; explorer.metrics "
                        "documents each block's source. tests/test_metrics.py fails when "
                        "this file is stale (the timing block excepted)."),
        "held_out": held_out,
        "space": space_data,
        "no_p1_estimate": no_p1_estimate(space, budget),
        "campaigns": campaigns,
        "campaigns_note": (
            "distinct_signatures and contrasts (campaign.outcome_stages) include the "
            "station_status fact, which echoes the configured AKM and ciphers rather than "
            "behavior. station_status_echo gives each campaign's distinct signatures "
            "without it and its pairs that differ only in it; those pairs can't start a "
            "minimization, which targets behavior facts."),
        "pairwise": pairwise_block(),
        "counterexamples": suite,
        "audit": audit_block(),
        "undetermined": undetermined_block(space_data, suite),
        "cache": cache,
        "runtime": runtime,
    }
    if timing:
        data["timing"] = timing_block(space, runtime["mean_seconds_per_boot"])
    return data


def untimed(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in UNTIMED}


def write(path: Path = METRICS_JSON) -> dict:
    data = build()
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return data

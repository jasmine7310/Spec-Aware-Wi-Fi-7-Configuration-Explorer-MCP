"""Run a planned campaign (issue #68) and publish its pruning funnel.

``run`` takes ``campaign_plan.json``'s candidates and, for each one:

1. re-checks it with today's stages (P0/P1 by ``validate_candidate``, and the adapter can
   express it), so a plan made under older rules can't launch a rule-breaking run;
2. runs it through the experiment cache (``cache.run_cached``) in a fresh UML guest;
3. reruns once on ``SETUP_FAIL`` or ``TIMEOUT``, which say nothing about the candidate
   (the #80 decision); ``REJECTED`` is a result, never retried.

With ``fresh=True`` (a held-out campaign, #114) step 2 passes ``force`` to the runner:
every candidate boots a new guest and the cache is written but never read, so no result
is a cache hit (``independent`` stays true).

Run folders go in ``campaigns/<campaign id>/`` (committed evidence, which P2 then counts);
``results.json`` there lists each candidate's attempts. ``pruning_counts`` builds the
funnel from enumerated assignments to P3 statuses, and, given ``outcome_stages``, on to
the distinct signatures of the ``ACCEPTED`` runs and the contrasts among them (#114).
``rejected_cases`` is the table of everything that didn't run or didn't come back
``ACCEPTED``, with the rule IDs or reasons. Nothing here invents an outcome: a failure is
reported as the status it got.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from explorer import adapter
from explorer.cache import Cache, run_cached
from explorer.model import Candidate

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGNS = REPO_ROOT / "campaigns"
PRUNING_COUNTS = REPO_ROOT / "pruning_counts.json"
P3_STATUSES = ("ACCEPTED", "REJECTED", "SETUP_FAIL", "TIMEOUT")
RETRY_ON = ("SETUP_FAIL", "TIMEOUT")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(plan: dict, campaign_id: str, *, cache: Cache, campaigns_dir: Path = CAMPAIGNS,
        retries: int = 1, runner=run_cached, fresh: bool = False, **run_kwargs) -> dict:
    """Run every planned candidate (see the module docstring). Returns the results."""
    from explorer.validate import validate_candidate
    if fresh:
        run_kwargs["force"] = True
    log_dir = campaigns_dir / campaign_id
    log_dir.mkdir(parents=True, exist_ok=True)
    started = _now()
    results = []
    for planned in plan["candidates"]:
        entry = {"id": planned["id"], "choices": planned["choices"], "role": planned["role"],
                 "source": planned["source"], "attempts": []}
        verdict = validate_candidate(planned["candidate"])
        if verdict.status != "PASSES_MODELED_RULES":
            entry.update(status="NOT_RUN_P1", reason="; ".join(
                f"{f.rule_id}: {f.reason}" for f in verdict.findings))
            results.append(entry)
            continue
        candidate = Candidate.model_validate(planned["candidate"])
        if reasons := adapter.unsupported(candidate):
            entry.update(status="NOT_RUN_ADAPTER", reason="; ".join(reasons))
            results.append(entry)
            continue
        outcome = None
        for attempt in range(1, retries + 2):
            context = {"campaign": campaign_id, "seed": plan["seed"],
                       "candidate_id": planned["id"], "attempt": attempt}
            outcome, ran = runner(candidate, cache, context=context, log_dir=log_dir, **run_kwargs)
            entry["attempts"].append({"run_id": outcome.run_id, "status": outcome.status,
                                      "reason": outcome.reason, "cache_hit": ran is None})
            if outcome.status not in RETRY_ON:
                break
        entry.update(status=outcome.status, reason=outcome.reason, run_id=outcome.run_id,
                     cache_hit=entry["attempts"][-1]["cache_hit"], signature=outcome.signature)
        results.append(entry)
    return {"campaign": campaign_id, "seed": plan["seed"], "budget": plan["budget"],
            "model_digest": plan["model"]["model_digest"], "plan": "campaign_plan.json",
            "build_on_runs": plan.get("build_on_runs", True), "fresh": fresh,
            "started_at": started, "finished_at": _now(), "results": results}


def outcome_stages(campaign_dir: Path, max_inputs: int = 1) -> dict:
    """The funnel's last two stages for one campaign's run folders (#114):

    - ``accepted_runs`` / ``distinct_signatures``: the campaign's ``ACCEPTED``, rule-passing
      runs on the pinned commits (``contrasts.accepted_runs``) and how many different
      signatures (``contrasts.facts``) they show. These include ``station_status``, which
      echoes the configured AKM and ciphers, so two runs with the same behavior and a
      different cipher count twice (``metrics`` reports the counts without it);
    - ``contrasts``: pairs among those runs with a claimable fact difference
      (``contrasts.find``, ``station_status`` included): ``within_max_inputs`` at most
      ``max_inputs`` inputs apart (1, as in ``contrasts.json``), ``any_distance`` with no
      bound. A pair with a behavior-fact difference is one a minimization could start from,
      as c1 did from 8 inputs; a pair that differs only in ``station_status`` isn't, since
      minimization targets behavior facts. A pairwise design spreads its candidates
      apart, so few pairs are 1 input apart. ``reproduced_3_per_side`` counts those with 3
      runs per side: a campaign runs each candidate once, so it takes extra runs
      (``contrasts/runs/``). Every side is an ACCEPTED run of exactly its candidate on the
      pinned versions, so it's P2 ``SUPPORTED`` once committed.
    """
    from explorer import contrasts
    runs = contrasts.accepted_runs([campaign_dir])
    signatures = {json.dumps(run.facts, sort_keys=True) for _, run in runs}
    pairs = contrasts.find(contrasts.group(runs), 10**6, supported=lambda _: True)
    near = [c for c in pairs if contrasts.distance(c.input_diff) <= max_inputs]
    return {"accepted_runs": len(runs), "distinct_signatures": len(signatures),
            "contrasts": {"max_inputs": max_inputs, "within_max_inputs": len(near),
                          "any_distance": len(pairs),
                          "reproduced_3_per_side": sum(c.reproduced for c in pairs)}}


def pruning_counts(plan: dict, results: dict, stages: dict | None = None) -> dict:
    """The funnel from the plan's enumeration to P3 statuses, and on to distinct
    signatures and contrasts when ``stages`` (``outcome_stages``) is given."""
    funnel = plan["funnel"]
    rows = results["results"]
    statuses = Counter(r["status"] for r in rows)
    attempts = [a for r in rows for a in r["attempts"]]
    boots = sum(not a["cache_hit"] for a in attempts)
    counts = {
        "description": ("Pruning funnel of one campaign (issue #68): candidates surviving "
                        "P0 -> ConfigSpace/P1 -> P2 -> P3, then (#114) the distinct "
                        "signatures of the ACCEPTED runs and the contrasts among them, "
                        "when present. Generated by "
                        "scripts/run_campaign.py from campaign_plan.json and the campaign's "
                        "results.json; counts only, the evidence is in campaigns/."),
        "campaign": results["campaign"],
        "seed": results["seed"],
        "model_digest": results["model_digest"],
        "enumerated": funnel["enumerated"],
        "P0": {"well_formed": funnel["p0_well_formed"],
               "malformed": funnel["enumerated"] - funnel["p0_well_formed"]},
        "configspace": funnel["configspace"],
        "P1": {"passes_modeled_rules": funnel["p1"].get("PASSES_MODELED_RULES", 0),
               "spec_rule_violation": funnel["p1"].get("SPEC_RULE_VIOLATION", 0),
               "spec_undetermined_review_queue": funnel["p1"].get("SPEC_UNDETERMINED", 0),
               "rejections_by_rule": funnel["p1_rejections_by_rule"]},
        "P2": {"supported": funnel["p2"]["supported"], "probe": funnel["p2"]["probe"],
               "unsupported_implementation": funnel["p2"].get("unsupported", 0),
               "unresolved_not_run": funnel["p2"]["not_run"], "executable": funnel["executable"]},
        "planned": {"candidates": funnel["planned"], "cut_by_budget": funnel["cut_by_budget"],
                    "already_run_before": funnel.get("already_run", 0),
                    "by_role": dict(Counter(r["role"] for r in rows))},
        "not_run_at_launch": {"p1_today": statuses["NOT_RUN_P1"],
                              "adapter": statuses["NOT_RUN_ADAPTER"]},
        "P3": {status: statuses[status] for status in P3_STATUSES},
        "executed": {"guest_boots": boots,
                     "cache_hits": sum(a["cache_hit"] for a in attempts),
                     "retries": len(attempts) - sum(1 for r in rows if r["attempts"]),
                     "distinct_candidates_run": sum(
                         1 for r in rows if any(not a["cache_hit"] for a in r["attempts"]))},
        "guest_boots_avoided_by_pruning": funnel["enumerated"] - funnel["executable"],
        "mode": {"build_on_runs": results.get("build_on_runs", True),
                 "fresh": results.get("fresh", False)},
    }
    if stages is not None:
        counts["signatures"] = {"accepted_runs": stages["accepted_runs"],
                                "distinct": stages["distinct_signatures"]}
        counts["contrasts"] = stages["contrasts"]
    return counts


def rejected_cases(plan: dict, results: dict, space) -> list[dict]:
    """Every case that didn't run or didn't come back ACCEPTED, with its rule IDs or
    reason: P1 rejections grouped by the rules they break (count and one example), the
    infeasible value pairs, then each planned candidate whose run wasn't ACCEPTED."""
    rows = []
    groups: dict[tuple, list] = {}
    for row, a in space.assessments.items():
        if not a.legal:
            groups.setdefault((a.p1_status, tuple(a.rule_ids)), []).append(row)
    for (status, rule_ids), members in sorted(groups.items(), key=lambda g: -len(g[1])):
        rows.append({"stage": "P1", "outcome": status, "rule_ids": "; ".join(rule_ids),
                     "count": len(members), "example": json.dumps(space.choices(members[0])),
                     "run_id": "", "reason": ""})
    for r in results["results"]:
        if r["status"] != "ACCEPTED":
            stage = "P3" if r["status"] in P3_STATUSES else "launch"
            rows.append({"stage": stage, "outcome": r["status"], "rule_ids": "",
                         "count": 1, "example": json.dumps(r["choices"]),
                         "run_id": r.get("run_id") or "", "reason": r.get("reason") or ""})
    return rows


def write(campaign_dir: Path, plan: dict, results: dict, rejected: list[dict],
          counts: dict) -> None:
    """The campaign's files: the plan it ran, results.json, rejected_cases.csv, and its
    funnel (also as the repo root's pruning_counts.json, the latest campaign's)."""
    (campaign_dir / "campaign_plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    (campaign_dir / "pruning_counts.json").write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")
    (campaign_dir / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    buf = io.StringIO()
    fields = ["stage", "outcome", "rule_ids", "count", "example", "run_id", "reason"]
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rejected)
    (campaign_dir / "rejected_cases.csv").write_text(buf.getvalue())
    PRUNING_COUNTS.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")

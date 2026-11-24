"""The Picire interestingness wrapper (issue #72): typed deltas between two candidates,
each probe status, cache hits, and small end-to-end reductions. A fake runner stands in
for the guest; nothing here boots Docker."""

import json

import pytest
from picire import Outcome

from explorer import adapter, contrasts
from explorer import minimize as M
from explorer.cache import Cache, CachedOutcome
from explorer.signatures import UNKNOWN, BehaviorRecord
from explorer.support import SupportResult

ASSOC = {"action": "associate"}
REKEY_GTK = {"action": "rekey_gtk_now"}
LINK_REMOVE_1 = {"action": "link_remove", "link_id": 1, "count": 4}
LINK0 = {"link_id": 0, "channel": 1, "akms": ["OWE"]}
LINK1 = {"link_id": 1, "channel": 6, "akms": ["OWE"]}


def _candidate(links=(LINK0, LINK1), actions=(ASSOC,), **ap):
    return {"config": {"ap": {"links": [dict(link) for link in links], **ap},
                       "sta": {"akms": ["OWE"]}},
            "actions": [dict(step) for step in actions]}


# Facts as the fake guest reports them: the PTK-rekey-after-link_remove contrast (#71's
# C1), with reason-15 disconnects only when both are present.
REASON_15 = {"reason": 15, "locally_generated": False}
REASON_3 = {"reason": 3, "locally_generated": True}


def _behavior(candidate):
    ap = candidate.config.ap
    removed = any(s.action == "link_remove" for s in candidate.actions)
    if ap.ptk_rekey_interval_s == 5 and removed:
        return {"disconnects": [REASON_15, REASON_3], "valid_links": "0x1"}
    return {"disconnects": [REASON_3], "valid_links": "0x1" if removed else "0x3"}


TARGET = {"disconnect_reasons": [[3, True], [15, False]]}


class FakeRunner:
    """Stands in for cache.run_cached: answers from ``behavior``, or pops queued
    (status, signature) outcomes; serves a repeated candidate as a cache hit."""

    def __init__(self, behavior=_behavior, queue=(), cache_hits=True):
        self.behavior, self.queue, self.cache_hits = behavior, list(queue), cache_hits
        self.calls, self.contexts, self.stored = [], [], {}

    def __call__(self, candidate, cache, *, context=None, **kwargs):
        key = json.dumps(candidate.model_dump(mode="json"), sort_keys=True)
        self.contexts.append(context)
        if self.cache_hits and not kwargs.get("force") and key in self.stored:
            return self.stored[key].model_copy(update={"independent": False}), None
        self.calls.append(candidate)
        status, signature = (self.queue.pop(0) if self.queue
                             else ("ACCEPTED", self.behavior(candidate)))
        outcome = CachedOutcome(key=key, run_id=str(1800000000 + len(self.calls)),
                                status=status, reason=None if status == "ACCEPTED" else "x",
                                signature=signature, run_dir=None, timeout_s=None,
                                context=context or {}, recorded_at="now")
        if status in ("ACCEPTED", "REJECTED"):
            self.stored[key] = outcome
        return outcome, object()  # a CandidateRun stand-in: a new guest run


def _support(status="SUPPORTED", evidenced=True, limit=None):
    def check(candidate):
        return SupportResult(status=status, test=None, run_ids=[], values=[],
                             closest_tests=[], all_values_evidenced=evidenced,
                             recorded_refusals=[], note=f"fake {status}", limit=limit)
    return check


def _minimizer(a, b, target=TARGET, runner=None, support=None, **kwargs):
    return M.Minimizer(a, b, target, runner=runner or FakeRunner(),
                       support=support or _support(), **kwargs)


def _ids(delta_set, *labels):
    """Delta IDs whose label starts with each prefix."""
    out = []
    for prefix in labels:
        (match,) = [d.id for d in delta_set.deltas if d.label.startswith(prefix)]
        out.append(match)
    return out


# --- typed deltas -------------------------------------------------------------------

def test_no_deltas_give_a_and_all_give_b():
    a = _candidate()
    b = _candidate(links=(LINK0, {**LINK1, "indicate_disabled": True}),
                   actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5)
    ds = M.DeltaSet(a, b)
    assert ds.apply([]) == M.normalize(a)
    assert ds.apply([d.id for d in ds.deltas]) == M.normalize(b)
    assert len(ds.deltas) == contrasts.distance(contrasts.input_diff(ds.a, ds.b)) == 3
    assert [d.kind for d in ds.deltas] == ["config", "config", "action"]


def test_omitted_defaults_are_not_deltas():
    a = _candidate()
    b = json.loads(json.dumps(a))
    b["config"]["ap"]["pmf"] = "required"  # the default, written out
    assert M.deltas(a, b) == []


def test_a_link_only_one_side_has_is_one_delta():
    a, b = _candidate(links=(LINK0,)), _candidate()
    (added,) = M.deltas(a, b)
    assert added.kind == "link" and added.b["link_id"] == 1
    (removed,) = M.deltas(b, a)
    assert removed.kind == "link" and removed.a["link_id"] == 1
    assert M.DeltaSet(b, a).apply([removed.id]) == M.normalize(a)


def test_each_one_sided_action_step_is_one_delta_placed_among_common_steps():
    a = _candidate(actions=(ASSOC, REKEY_GTK))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1, REKEY_GTK, LINK_REMOVE_1))
    ds = M.DeltaSet(a, b)
    assert [d.kind for d in ds.deltas] == ["action", "action"]
    first, _ = [d.id for d in ds.deltas]
    assert ds.apply([first])["actions"] == [ASSOC, LINK_REMOVE_1, REKEY_GTK]
    removal = M.DeltaSet(b, a)
    assert removal.apply([removal.deltas[1].id])["actions"] == [ASSOC, LINK_REMOVE_1, REKEY_GTK]


def test_a_reordering_is_one_delta():
    a = _candidate(actions=(ASSOC, REKEY_GTK, LINK_REMOVE_1))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1, REKEY_GTK))
    (order,) = M.deltas(a, b)
    assert order.kind == "actions_order"
    assert M.DeltaSet(a, b).apply([order.id])["actions"] == b["actions"]


def test_per_link_values_are_separate_deltas():
    a = _candidate()
    b = _candidate(links=({**LINK0, "pairwise_cipher": "GCMP-256"},
                          {**LINK1, "pairwise_cipher": "GCMP-256"}))
    assert [d.path for d in M.deltas(a, b)] == ["config.ap.links[0].pairwise_cipher",
                                               "config.ap.links[1].pairwise_cipher"]


# --- probe statuses -----------------------------------------------------------------

def test_p0_invalid_probe_never_runs():
    # B adds link 1 and removes it; the removal alone names a link the probe lacks.
    runner = FakeRunner()
    m = _minimizer(_candidate(links=(LINK0,)), _candidate(actions=(ASSOC, LINK_REMOVE_1)),
                   runner=runner)
    (action,) = _ids(m.delta_set, "+ actions")
    probe = m.probe([action])
    assert (probe.status, probe.stage) == ("INVALID", "P0")
    assert probe.rule_ids == ["P0.INVALID_VALUE"] and "link_id 1" in probe.reason
    assert not probe.interesting and runner.calls == []


def test_p1_invalid_probe_cites_the_rule():
    runner = FakeRunner()
    m = _minimizer(_candidate(), _candidate(beacon_protection=False), runner=runner)
    probe = m.probe([0])
    assert (probe.status, probe.stage, probe.rule_ids) == ("INVALID", "P1",
                                                            ["SEC.EHT_BEACON_PROT"])
    assert runner.calls == []


def test_action_order_invalid_probe():
    runner = FakeRunner()
    m = _minimizer(_candidate(actions=()), _candidate(actions=(ASSOC, REKEY_GTK)),
                   runner=runner)
    (rekey,) = _ids(m.delta_set, "+ actions[1]")
    probe = m.probe([rekey])
    assert (probe.status, probe.stage, probe.rule_ids) == ("INVALID", "action_order",
                                                            ["AO.ASSOC_REQUIRED"])
    assert runner.calls == []


def test_spec_undetermined_probe_is_its_own_status():
    disable = {"action": "disable_enable_mld", "command": "DISABLE_MLD"}
    runner = FakeRunner()
    m = _minimizer(_candidate(), _candidate(actions=(ASSOC, disable, REKEY_GTK)),
                   runner=runner)
    probe = m.probe([d.id for d in m.delta_set.deltas])
    assert (probe.status, probe.stage) == ("SPEC_UNDETERMINED", "action_order")
    assert probe.rule_ids == ["UND.STA_STATE_WHILE_MLD_DISABLED"]
    assert runner.calls == []


def test_p2_unsupported_probe():
    runner = FakeRunner()
    m = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5), runner=runner,
                   support=_support("UNSUPPORTED_IMPLEMENTATION", False, limit="P2.X"))
    probe = m.probe([0])
    assert (probe.status, probe.stage, probe.rule_ids, probe.p2) == (
        "UNSUPPORTED", "P2", ["P2.X"], "UNSUPPORTED_IMPLEMENTATION")
    assert runner.calls == []


def test_p2_unresolved_without_evidence_is_not_run():
    runner = FakeRunner()
    m = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5), runner=runner,
                   support=_support("UNRESOLVED", evidenced=False))
    probe = m.probe([0])
    assert (probe.status, probe.stage) == ("UNRESOLVED", "P2")
    assert runner.calls == []


def test_an_evidenced_unresolved_probe_runs_as_a_support_probe():
    runner = FakeRunner()
    m = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5), runner=runner,
                   support=_support("UNRESOLVED", evidenced=True))
    probe = m.probe([0])
    assert probe.support_probe and probe.p2 == "UNRESOLVED" and len(runner.calls) == 1
    off = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5), runner=FakeRunner(),
                     support=_support("UNRESOLVED", evidenced=True), run_support_probes=False)
    assert off.probe([0]).status == "UNRESOLVED"


def test_adapter_unsupported_probe():
    runner = FakeRunner()
    m = _minimizer(_candidate(), _candidate(actions=({"action": "scan"}, ASSOC)),
                   runner=runner)
    probe = m.probe([0])
    assert (probe.status, probe.stage) == ("UNSUPPORTED", "adapter")
    assert "not supported by the adapter" in probe.reason and runner.calls == []


@pytest.mark.parametrize("status", ["REJECTED", "SETUP_FAIL", "TIMEOUT"])
def test_p3_failures_are_their_own_status(status):
    runner = FakeRunner(queue=[(status, None), (status, None)])
    m = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5), runner=runner)
    probe = m.probe([0])
    assert (probe.status, probe.stage) == (status, "P3") and not probe.interesting
    # SETUP_FAIL / TIMEOUT say nothing about the candidate: rerun once. REJECTED is a result.
    assert len(probe.attempts) == (1 if status == "REJECTED" else 2)
    assert probe.run_ids == [a.run_id for a in probe.attempts]


def test_a_setup_fail_then_accepted_rerun_counts_the_rerun():
    runner = FakeRunner(queue=[("SETUP_FAIL", None)])
    m = _minimizer(_candidate(actions=(ASSOC, LINK_REMOVE_1)),
                   _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5),
                   runner=runner)
    probe = m.probe([0])
    assert probe.status == "INTERESTING"
    assert [a.status for a in probe.attempts] == ["SETUP_FAIL", "ACCEPTED"]


def test_an_unmeasured_target_fact_is_unknown_not_a_match_or_difference():
    runner = FakeRunner(queue=[("ACCEPTED", {"disconnects": UNKNOWN})])
    m = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5),
                   target={**TARGET, "valid_links": "0x1"}, runner=runner)
    probe = m.probe([0])
    assert probe.status == "UNKNOWN"
    assert probe.unknown == ["disconnect_reasons", "valid_links"]
    assert probe.matched == probe.differing == []


def test_unknown_wins_over_a_measured_match():
    runner = FakeRunner(queue=[("ACCEPTED", {"disconnects": [REASON_3, REASON_15]})])
    m = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5),
                   target={**TARGET, "valid_links": "0x1"}, runner=runner)
    probe = m.probe([0])
    assert probe.status == "UNKNOWN"
    assert (probe.matched, probe.unknown) == (["disconnect_reasons"], ["valid_links"])


def test_a_measured_difference_wins_over_an_unmeasured_fact():
    runner = FakeRunner(queue=[("ACCEPTED", {"disconnects": [REASON_3]})])
    m = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5),
                   target={**TARGET, "valid_links": "0x1"}, runner=runner)
    probe = m.probe([0])
    assert probe.status == "NOT_INTERESTING" and not probe.interesting
    assert (probe.differing, probe.unknown) == (["disconnect_reasons"], ["valid_links"])


def test_accepted_probes_are_interesting_only_when_every_target_fact_matches_b():
    a = _candidate(actions=(ASSOC, LINK_REMOVE_1))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5)
    m = _minimizer(a, b, target={**TARGET, "valid_links": "0x1"})
    hit, miss = m.probe([0]), m.probe([])
    assert hit.status == "INTERESTING" and hit.matched == ["disconnect_reasons", "valid_links"]
    assert miss.status == "NOT_INTERESTING" and miss.differing == ["disconnect_reasons"]
    assert m([0], ("r0", "s0")) is Outcome.FAIL and m([], ("r0", "c0")) is Outcome.PASS


def test_a_cache_hit_is_not_an_independent_run():
    runner = FakeRunner()
    a = _candidate(actions=(ASSOC, LINK_REMOVE_1))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5)
    first = _minimizer(a, b, runner=runner).probe([0])
    again = _minimizer(a, b, runner=runner).probe([0])
    assert (first.cache_hit, first.independent) == (False, True)
    assert (again.cache_hit, again.independent) == (True, False)
    assert again.status == "INTERESTING" and len(runner.calls) == 1


def test_a_repeated_subset_is_probed_once():
    runner = FakeRunner(cache_hits=False)
    m = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5), runner=runner)
    assert m.probe([0]) is m.probe([0, 0])
    assert len(runner.calls) == 1 and len(m.trace) == 1


def test_target_facts_must_be_measured():
    with pytest.raises(ValueError, match="UNKNOWN"):
        _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5),
                   target={"disconnect_reasons": UNKNOWN})
    with pytest.raises(ValueError, match="no target"):
        _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5), target={})


def test_the_real_cache_serves_a_repeated_probe(monkeypatch, tmp_path):
    """Through cache.run_cached with a fake adapter.run_candidate: the second minimizer's
    probe of the same candidate is a cache hit, with no new guest run."""
    calls = []

    def fake_run_candidate(candidate, *, metadata=None, **kwargs):
        calls.append(candidate)
        plan = {"explorer": {"timeout_s": 600, **(metadata or {})}}
        return adapter.CandidateRun(status="ACCEPTED", reason=None,
                                    run_id=str(1800000000 + len(calls)), run_dir=None,
                                    record=BehaviorRecord.model_construct(),
                                    plan=plan)

    monkeypatch.setattr(adapter, "run_candidate", fake_run_candidate)
    monkeypatch.setattr(adapter, "comparable_signature",
                        lambda record: {"disconnects": [REASON_15, REASON_3]})
    a = _candidate(actions=(ASSOC, LINK_REMOVE_1))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5)
    db = Cache(tmp_path / "cache.sqlite")
    try:
        first = M.Minimizer(a, b, TARGET, cache=db, support=_support()).probe([0])
        again = M.Minimizer(a, b, TARGET, cache=db, support=_support()).probe([0])
    finally:
        db.close()
    assert len(calls) == 1
    assert first.status == again.status == "INTERESTING"
    assert (first.independent, again.cache_hit, again.independent) == (True, True, False)
    assert again.run_ids == first.run_ids


# --- end to end ---------------------------------------------------------------------

def test_minimize_keeps_only_the_changes_that_explain_the_difference():
    # A: one link, associate only. B: link 1 added, 5 s PTK and GTK rekeys, bss_transition,
    # and link 1 removed. Only the PTK rekey plus the link removal (which needs link 1)
    # gives the reason-15 disconnect.
    a = _candidate(links=(LINK0,))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5,
                   gtk_rekey_interval_s=5, bss_transition=True)
    runner = FakeRunner()
    result = M.minimize(a, b, TARGET, runner=runner, support=_support(),
                        context={"minimization": "test"})
    ds = M.DeltaSet(a, b)
    assert len(ds.deltas) == 5
    assert result.status == "MINIMIZED"
    assert result.minimal == sorted(_ids(ds, "config.ap.ptk_rekey_interval_s",
                                         "+ config.ap.links[1]", "+ actions[1]"))
    minimal = result.minimal_candidate
    assert minimal["config"]["ap"]["ptk_rekey_interval_s"] == 5
    assert minimal["config"]["ap"]["gtk_rekey_interval_s"] is None
    assert minimal["config"]["ap"]["bss_transition"] is False
    assert minimal["actions"] == [ASSOC, LINK_REMOVE_1]

    trace = result.trace
    assert [p.config_id for p in trace[:2]] == ["target", "baseline"]
    assert trace[0].status == "INTERESTING" and trace[1].status == "NOT_INTERESTING"
    # Picire's probes include ones that remove link 1 but keep its link_remove: P0 stops
    # them before any run, and they are never interesting.
    assert result.counts.get("INVALID", 0) >= 1
    assert all(p.stage == "P0" for p in trace if p.status == "INVALID")
    assert sum(result.counts.values()) == len(trace)
    assert {p.status for p in trace} <= {"INTERESTING", "NOT_INTERESTING", "INVALID"}
    assert all(p.interesting == (p.status == "INTERESTING") for p in trace)
    # Every run in the trace was a new guest run (distinct candidates), counted once.
    assert result.guest_runs == len(runner.calls) == sum(bool(p.attempts) for p in trace)
    assert result.cache_hits == 0
    assert all(c["minimization"] == "test" for c in runner.contexts)
    assert json.loads(result.model_dump_json())["status"] == "MINIMIZED"


def test_rerunning_a_reduction_serves_every_probe_from_the_cache():
    a = _candidate(links=(LINK0,))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5)
    runner = FakeRunner()
    first = M.minimize(a, b, TARGET, runner=runner, support=_support())
    second = M.minimize(a, b, TARGET, runner=runner, support=_support())
    assert second.minimal == first.minimal
    assert second.guest_runs == 0 and second.cache_hits == first.guest_runs > 0
    assert not any(p.independent for p in second.trace)


def test_a_target_that_does_not_reproduce_stops_the_reduction():
    runner = FakeRunner(queue=[("TIMEOUT", None), ("TIMEOUT", None)])
    result = M.minimize(_candidate(), _candidate(ptk_rekey_interval_s=5), TARGET,
                        runner=runner, support=_support())
    assert result.status == "TARGET_NOT_INTERESTING"
    assert [p.status for p in result.trace] == ["TIMEOUT"]
    assert result.minimal == [] and result.minimal_candidate is None


@pytest.mark.parametrize("budget", [0, 1, 3])
def test_a_spent_budget_stops_the_reduction_before_the_next_run(budget):
    # #74: an MCP call must not boot an unbounded number of guests.
    a = _candidate(links=(LINK0,))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5,
                   gtk_rekey_interval_s=5, bss_transition=True)
    runner = FakeRunner()
    result = M.minimize(a, b, TARGET, runner=runner, support=_support(),
                        max_guest_runs=budget)
    assert result.status == "BUDGET_EXHAUSTED"
    assert result.guest_runs == len(runner.calls) == budget
    assert result.minimal == [] and result.minimal_candidate is None
    assert sum(result.counts.values()) == len(result.trace)


def test_a_budget_large_enough_changes_nothing():
    a = _candidate(links=(LINK0,))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5)
    unbounded = M.minimize(a, b, TARGET, runner=FakeRunner(), support=_support())
    bounded = M.minimize(a, b, TARGET, runner=FakeRunner(), support=_support(),
                         max_guest_runs=unbounded.guest_runs)
    assert bounded.status == "MINIMIZED" and bounded.minimal == unbounded.minimal


def test_a_negative_budget_is_refused():
    with pytest.raises(ValueError, match="can't be negative"):
        M.Minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5), TARGET,
                    runner=FakeRunner(), support=_support(), max_guest_runs=-1)


def test_a_baseline_that_already_shows_the_target_stops_the_reduction():
    a = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5)
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5, bss_transition=True)
    result = M.minimize(a, b, TARGET, runner=FakeRunner(), support=_support())
    assert result.status == "BASELINE_INTERESTING"
    assert [p.config_id for p in result.trace] == ["target", "baseline"]


def test_from_contrast_targets_b_s_claimed_facts():
    a = _candidate(actions=(ASSOC, LINK_REMOVE_1))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5)
    contrast = contrasts.Contrast(
        a_runs=["1"], b_runs=["2"], input_diff=contrasts.input_diff(a, b),
        facts=[contrasts.FactDiff(fact="disconnect_reasons", a=[[3, True]],
                                  b=[[3, True], [15, False]], evidence_a=[], evidence_b=[])],
        unstable=[], reproduced=False, harness="h", current_harness=True,
        candidate_a=a, candidate_b=b)
    result = M.from_contrast(contrast, runner=FakeRunner(), support=_support())
    assert result.target == TARGET
    assert result.status == "MINIMIZED" and result.minimal == [0]


# --- choosing the target, reading the result ----------------------------------------

SAE_LINK0 = {**LINK0, "akms": ["SAE-EXT-KEY"]}
SAE_LINK1 = {**LINK1, "akms": ["SAE-EXT-KEY"]}


def _sae_candidate(**ap):
    data = _candidate(links=(SAE_LINK0, SAE_LINK1), actions=(ASSOC, LINK_REMOVE_1), **ap)
    data["config"]["sta"]["akms"] = ["SAE-EXT-KEY"]
    return data


def _behavior_with_status(candidate):
    """_behavior plus a station_status that echoes the config (the negotiated AKM)."""
    return {**_behavior(candidate),
            "station_status": {"key_mgmt": candidate.config.sta.akms[0],
                               "wpa_state": "COMPLETED"}}


def _wide_contrast():
    # A: OWE, no PTK rekey. B: SAE-EXT-KEY on both links and the client, 5 s PTK and GTK
    # rekeys. Both remove link 1 after associating.
    a = _candidate(actions=(ASSOC, LINK_REMOVE_1))
    b = _sae_candidate(ptk_rekey_interval_s=5, gtk_rekey_interval_s=5)
    status = lambda akm: {"key_mgmt": akm, "wpa_state": "COMPLETED"}
    return contrasts.Contrast(
        a_runs=["1"], b_runs=["2"], input_diff=contrasts.input_diff(a, b),
        facts=[contrasts.FactDiff(fact="disconnect_reasons", a=[[3, True]],
                                  b=[[3, True], [15, False]], evidence_a=[], evidence_b=[]),
               contrasts.FactDiff(fact="station_status", a=status("OWE"),
                                  b=status("SAE-EXT-KEY"), evidence_a=[], evidence_b=[])],
        unstable=[], reproduced=False, harness="h", current_harness=True,
        candidate_a=a, candidate_b=b)


def test_a_fact_that_echoes_the_config_makes_the_minimizer_keep_config_deltas():
    contrast = _wide_contrast()
    ds = M.DeltaSet(contrast.candidate_a, contrast.candidate_b)
    assert len(ds.deltas) == 5
    akms = _ids(ds, "config.ap.links[0].akms", "config.ap.links[1].akms", "config.sta.akms")
    (ptk,) = _ids(ds, "config.ap.ptk_rekey_interval_s")

    every_fact = M.from_contrast(contrast, runner=FakeRunner(_behavior_with_status),
                                 support=_support())
    assert every_fact.status == "MINIMIZED"
    assert set(every_fact.target) == {"disconnect_reasons", "station_status"}
    assert every_fact.minimal == sorted(akms + [ptk])
    # Removing one AKM delta leaves the links and the client without a common AKM: the
    # probe is INVALID, not a run that failed to reproduce B. Removing the PTK rekey runs.
    assert every_fact.needed_for_validity == sorted(akms)

    behavior_only = M.from_contrast(contrast, facts=["disconnect_reasons"],
                                    runner=FakeRunner(_behavior_with_status),
                                    support=_support())
    assert behavior_only.target == TARGET
    assert behavior_only.minimal == [ptk] and behavior_only.needed_for_validity == []


def test_from_contrast_refuses_a_fact_the_contrast_does_not_claim():
    with pytest.raises(ValueError, match="not claimed"):
        M.from_contrast(_wide_contrast(), facts=["ptk_rekeys_completed"],
                        runner=FakeRunner(), support=_support())
    with pytest.raises(ValueError, match="empty"):
        M.from_contrast(_wide_contrast(), facts=[], runner=FakeRunner(), support=_support())


def test_needed_for_validity_counts_spec_undetermined_and_only_probed_removals():
    m = _minimizer(_candidate(), _candidate(ptk_rekey_interval_s=5))
    m._memo[(0, 1)] = M.Probe(index=0, config_id="x", deltas=[0, 1], candidate={},
                              status="INTERESTING", p2="UNRESOLVED", support_probe=True)
    m._memo[(1,)] = M.Probe(index=1, config_id="x", deltas=[1], candidate={},
                            status="SPEC_UNDETERMINED")
    result = M._reduction(m, "MINIMIZED", [0, 1])
    # Removing delta 0 gave SPEC_UNDETERMINED; removing delta 1 was never probed.
    assert result.needed_for_validity == [0]
    assert result.minimal_p2 == "UNRESOLVED"


def test_the_minimal_candidate_s_p2_status_is_recorded():
    a = _candidate(links=(LINK0,))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5)
    supported = M.minimize(a, b, TARGET, runner=FakeRunner(), support=_support())
    assert supported.minimal_p2 == "SUPPORTED"
    probe = M.minimize(a, b, TARGET, runner=FakeRunner(),
                       support=_support("UNRESOLVED", evidenced=True))
    assert probe.minimal_p2 == "UNRESOLVED"
    stopped = M.minimize(a, b, {"disconnect_reasons": [[3, True]]}, runner=FakeRunner(),
                         support=_support())
    assert stopped.status == "TARGET_NOT_INTERESTING" and stopped.minimal_p2 is None


# --- reproducing the final sides (#73) -------------------------------------------------

def _reduced():
    a = _candidate(actions=(ASSOC, LINK_REMOVE_1))
    b = _candidate(actions=(ASSOC, LINK_REMOVE_1), ptk_rekey_interval_s=5,
                   gtk_rekey_interval_s=5)
    result = M.minimize(a, b, TARGET, runner=FakeRunner(), support=_support())
    assert result.status == "MINIMIZED" and len(result.minimal) == 1
    return result


def test_verify_runs_each_final_side_fresh_and_labels_it_minimized():
    reduction = _reduced()
    runner = FakeRunner()            # would serve hits, but verify forces fresh runs
    v = M.verify(reduction, runner=runner, context={"why": "test"})
    assert v.label == "MINIMIZED" and v.runs == 3
    assert [r.matches_target for r in v.baseline] == [False] * 3
    assert [r.matches_target for r in v.minimal] == [True] * 3
    assert len(runner.calls) == 6 and len({r.run_id for r in v.baseline + v.minimal}) == 6
    assert [c["verify_side"] for c in runner.contexts] == ["baseline"] * 3 + ["minimal"] * 3
    assert all(c["why"] == "test" for c in runner.contexts)


def test_one_run_that_does_not_reproduce_leaves_it_pending():
    reduction = _reduced()
    calls = []

    def flaky(candidate):
        calls.append(candidate)
        if len(calls) == 5:                      # the minimal side's second run
            return {"disconnects": [REASON_3], "valid_links": "0x1"}
        return _behavior(candidate)
    v = M.verify(reduction, runner=FakeRunner(behavior=flaky))
    assert v.label == "PENDING_VERIFICATION"
    assert [r.matches_target for r in v.minimal] == [True, False, True]


def test_an_unmeasured_fact_or_a_failed_run_leaves_it_pending():
    reduction = _reduced()
    unmeasured = FakeRunner(behavior=lambda c: {"disconnects": UNKNOWN})
    v = M.verify(reduction, runner=unmeasured)
    assert v.label == "PENDING_VERIFICATION"
    assert {r.matches_target for r in v.baseline + v.minimal} == {None}
    rejected = FakeRunner(queue=[("REJECTED", None)])
    v = M.verify(reduction, runner=rejected)
    assert v.label == "PENDING_VERIFICATION" and v.baseline[0].status == "REJECTED"


def test_a_setup_fail_is_rerun_once_and_the_rerun_counts():
    reduction = _reduced()
    v = M.verify(reduction, runner=FakeRunner(queue=[("SETUP_FAIL", None)]))
    assert [r.status for r in v.baseline] == ["SETUP_FAIL", "ACCEPTED", "ACCEPTED", "ACCEPTED"]
    assert v.label == "MINIMIZED"
    twice = FakeRunner(queue=[("SETUP_FAIL", None), ("TIMEOUT", None)])
    assert M.verify(reduction, runner=twice).label == "PENDING_VERIFICATION"


def test_verify_refuses_an_unminimized_reduction_and_cache_hits():
    a = _candidate(actions=(ASSOC, LINK_REMOVE_1))
    not_reduced = M.minimize(a, _candidate(gtk_rekey_interval_s=5, actions=(ASSOC, LINK_REMOVE_1)),
                             TARGET, runner=FakeRunner(), support=_support())
    with pytest.raises(ValueError, match="TARGET_NOT_INTERESTING"):
        M.verify(not_reduced, runner=FakeRunner())
    def always_hit(candidate, cache, **kwargs):
        outcome, _ = FakeRunner()(candidate, cache, **kwargs)
        return outcome.model_copy(update={"independent": False}), None
    with pytest.raises(ValueError, match="cache hit"):
        M.verify(_reduced(), runner=always_hit)


# --- the committed minimized contrast (#73) --------------------------------------------

@pytest.mark.parametrize("name", ["c1", "c2", "c3"])
def test_committed_contrast_is_minimized_and_reread_from_its_runs(name):
    from explorer.signatures import extract_record
    folder = contrasts.CONTRASTS_DIR / name
    data = json.loads((folder / "reduction.json").read_text())
    reduction = M.Reduction.model_validate(data["reduction"])
    verification = M.Verification.model_validate(data["verification"])
    assert data["label"] == verification.label == reduction.status == "MINIMIZED"
    assert reduction.minimal_candidate == M.DeltaSet(
        reduction.candidate_a, reduction.candidate_b).apply(reduction.minimal)
    for probe in reduction.trace:                 # every probe run is committed
        for run_id in probe.run_ids:
            if probe.cache_hit:                   # an earlier run, committed where it ran
                assert any(contrasts.CONTRASTS_DIR.rglob(f"{run_id}/manifest.json")), run_id
            else:
                assert (folder / "probes" / run_id / "manifest.json").exists(), run_id
    runs = verification.baseline + verification.minimal
    assert len(verification.baseline) == len(verification.minimal) == contrasts.REPRODUCE_RUNS
    for run in runs:                              # the recorded facts match the logs
        record = extract_record(contrasts.CONTRASTS_DIR / "runs" / run.run_id,
                                adapter.ADAPTER_TEST)
        values, *_ = M._compare(adapter.comparable_signature(record), reduction.target)
        assert values == run.facts, run.run_id
    # Both final sides are now P2 SUPPORTED by their committed reproduction runs.
    assert contrasts.p2_supported(reduction.candidate_a)
    assert contrasts.p2_supported(reduction.minimal_candidate)

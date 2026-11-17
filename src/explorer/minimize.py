"""Minimize the difference between two accepted candidates (issue #72), with Picire.

Given a contrast's two sides, A and B (``contrasts.Contrast``: both ``ACCEPTED``, P2
``SUPPORTED``, with claimable fact differences), ``minimize`` finds a 1-minimal set of
whole typed changes that, applied to A, still gives B's values for the contrast's facts.

**Typed deltas** (``deltas``). Built from ``contrasts.input_diff`` on the two candidates
normalized by the P0 model (so an omitted default and an explicit one aren't a
difference):

- ``config``: one per differing config value, per AP link (e.g.
  ``config.ap.ptk_rekey_interval_s``, ``config.ap.links[1].indicate_disabled``); applied,
  it sets B's value;
- ``link``: a link only one side has, as one delta (its fields aren't separable: half a
  link isn't a link); applied, it adds B's link or removes A's;
- ``action``: one per action step only one side performs, placed by aligning the two
  action lists on their common steps (``difflib``); applied, it removes A's step or
  inserts B's at its place among the common steps. A step both sides perform at
  different places relative to the others counts as a removal and an addition;
- ``actions_order``: when both sides perform the same steps in another order
  (``input_diff``'s ``actions order``), one delta that switches to B's order.

So with no deltas applied the probe is A, with all it is B, and ``len(deltas)`` is
``contrasts.distance`` (more only for the moved-step case above). Any subset gives a
complete candidate dict; whether it is well-formed is P0's call, so a subset that, say,
adds an action naming a link the probe doesn't have is an ``INVALID`` probe.

**Interestingness** (``Minimizer.probe``). Each probe goes through every stage before any
guest run, and stops at the first that objects:

1. P0 ``validate.parse_candidate`` -> ``INVALID`` (stage ``P0``);
2. P1 ``validate.run_p1_checks``, ``find_undetermined`` and ``check_action_order``: a
   violation -> ``INVALID`` (stage ``P1`` or ``action_order``), else an open question ->
   ``SPEC_UNDETERMINED``;
3. P2 ``support.check_support``: ``UNSUPPORTED_IMPLEMENTATION`` -> ``UNSUPPORTED``;
   ``UNRESOLVED`` without every value evidenced -> ``UNRESOLVED``. ``SUPPORTED`` runs, and
   so does an ``UNRESOLVED`` support probe (every value evidenced), the #80 rule the
   campaign planner follows, unless ``run_support_probes=False``;
4. the adapter can't express it (``adapter.unsupported``) -> ``UNSUPPORTED`` (stage
   ``adapter``);
5. run through the experiment cache (``cache.run_cached``), rerunning once on
   ``SETUP_FAIL`` / ``TIMEOUT`` as the campaign does: ``REJECTED``, ``SETUP_FAIL`` and
   ``TIMEOUT`` are statuses of their own;
6. an ``ACCEPTED`` run's facts (``contrasts.facts``) are compared with B's on every target
   fact. A fact the probe didn't measure (``UNKNOWN``) is neither a match nor a
   difference: a measured target fact that differs from B's makes the probe
   ``NOT_INTERESTING``; otherwise an unmeasured one makes it ``UNKNOWN``; otherwise (all
   measured, all equal to B's) it is ``INTERESTING``. The ``unknown`` list names the
   unmeasured facts either way.

Only ``INTERESTING`` is interesting to Picire (``Outcome.FAIL``); every other status is
``Outcome.PASS`` and never counts as proof. Every probe is in the reduction trace with its
status, stage, rule IDs or reason, P2 status, run IDs and whether it came from the cache: a
cache hit (``independent=False``) is evidence of the earlier run, not a new one, and
``Reduction.guest_runs`` counts only real runs. One reduction is one run per probe; showing
the minimal change reproduces (3/3) is #73's job.

Before reducing, A (no deltas) and B (all deltas) are probed: if B isn't ``INTERESTING``
the reduction stops (``TARGET_NOT_INTERESTING``), and if A already is, there's nothing to
explain (``BASELINE_INTERESTING``).

**Budget.** ``max_guest_runs`` caps the new guest runs (each about 30 s). Before a run that
would go past it, the reduction stops with ``BUDGET_EXHAUSTED``: no ``minimal``, and the
trace holds every probe made so far. The check comes before the cache lookup, so once
the budget is spent even a probe the cache could answer isn't made (#74: an MCP call
can't boot an unbounded number of guests).

**Choosing the target.** The minimizer keeps whatever deltas the target facts need, so
target behavior, not configuration. ``from_contrast`` targets every fact the contrast
claims by default; pass ``facts=`` to pick some. A fact that echoes the config, such as
``station_status``'s ``key_mgmt`` and ciphers (they repeat the negotiated AKM and
ciphers), makes the minimizer keep the AKM / cipher deltas only to reproduce it, so it
explains the config rather than the behavior. #73 should target behavior facts such as
``disconnect_reasons`` and ``ptk_rekeys_completed``.

**Reading the result.**

- ``minimal`` is 1-minimal for the target: removing any one of its deltas gives a probe
  that isn't ``INTERESTING``. Deltas that only make sense together (each link's AKM and
  the client's AKM) are separate deltas, so a minimal delta may be there to keep the
  probe legal. ``needed_for_validity`` lists the minimal deltas whose single removal gave
  an ``INVALID`` or ``SPEC_UNDETERMINED`` probe in the trace, rather than a run that
  didn't reproduce B. A listed delta may still matter for the target: its removal was
  never run, so the trace can't tell. It is read from the trace only (no extra probes),
  so a delta whose single removal wasn't probed isn't listed.
- ``minimal_p2`` is the minimal candidate's P2 status from its probe. With
  ``run_support_probes`` it can be ``UNRESOLVED`` (it ran as a support probe): one run
  shows it executes, but it isn't ``SUPPORTED`` until #73 commits its 3 runs per side.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal

from picire import DD, Outcome
from pydantic import BaseModel

from explorer import contrasts
from explorer.model import Candidate
from explorer.signatures import UNKNOWN

ProbeStatus = Literal["INTERESTING", "NOT_INTERESTING", "INVALID", "SPEC_UNDETERMINED",
                      "UNSUPPORTED", "UNRESOLVED", "UNKNOWN", "REJECTED", "SETUP_FAIL",
                      "TIMEOUT"]
PROBE_STATUSES: tuple[str, ...] = ProbeStatus.__args__
RETRY_ON = ("SETUP_FAIL", "TIMEOUT")
"""P3 statuses that say nothing about the candidate, so the probe reruns (#80)."""

_LINK_PATH = re.compile(r"^config\.ap\.links\[(\d+)\]\.")
_SEGMENT = re.compile(r"^(\w+)(?:\[(\d+)\])?$")


class Delta(BaseModel):
    """One whole typed change from side A towards side B."""
    id: int
    kind: Literal["config", "link", "action", "actions_order"]
    label: str
    """Readable, e.g. 'config.ap.ptk_rekey_interval_s: 5 -> None' or
    '+ actions[1] link_remove (B)'."""
    path: str | None = None
    """config: the flattened path (as in ``contrasts.input_diff``); link: the links index."""
    a: Any = None
    b: Any = None


class Attempt(BaseModel):
    run_id: str | None
    status: str
    reason: str | None = None
    cache_hit: bool
    """Served from the cache (no guest booted): not an independent run."""


class Probe(BaseModel):
    """One interestingness test: a subset of deltas applied to A, and what came of it."""
    index: int
    config_id: str
    """Picire's ID for the test (e.g. 'r0 / s1'), or 'baseline' / 'target'."""
    deltas: list[int]
    candidate: dict
    status: ProbeStatus
    stage: str | None = None
    """Where it stopped: P0, P1, action_order, P2, adapter, P3 or facts."""
    rule_ids: list[str] = []
    reason: str | None = None
    p2: str | None = None
    """check_support's status (``SUPPORTED`` / ``UNRESOLVED`` / ...), once P1 passed."""
    support_probe: bool = False
    """Ran as an UNRESOLVED support probe (every value evidenced), not as SUPPORTED."""
    attempts: list[Attempt] = []
    """Each run attempt (a SETUP_FAIL / TIMEOUT is rerun once)."""
    run_ids: list[str] = []
    """The attempts' run IDs."""
    cache_hit: bool = False
    """The final outcome was served from the cache: not an independent run."""
    independent: bool = False
    """The final outcome is a new guest run made for this probe."""
    facts: dict[str, Any] = {}
    """The probe's value of each target fact (ACCEPTED only)."""
    matched: list[str] = []
    differing: list[str] = []
    unknown: list[str] = []

    @property
    def interesting(self) -> bool:
        return self.status == "INTERESTING"


class Reduction(BaseModel):
    status: Literal["MINIMIZED", "TARGET_NOT_INTERESTING", "BASELINE_INTERESTING",
                    "BUDGET_EXHAUSTED"]
    candidate_a: dict
    candidate_b: dict
    target: dict[str, Any]
    """B's value of each fact the probes must reproduce."""
    deltas: list[Delta]
    minimal: list[int]
    """Delta IDs of the 1-minimal interesting subset (MINIMIZED only)."""
    minimal_candidate: dict | None
    trace: list[Probe]
    """Every distinct probe, in the order it was tested."""
    counts: dict[str, int]
    """Probes per status."""
    guest_runs: int
    """New guest runs (attempts), cache hits excluded."""
    cache_hits: int
    needed_for_validity: list[int] = []
    """Minimal deltas whose single removal gave an INVALID / SPEC_UNDETERMINED probe in
    the trace: kept to keep the probe legal, not shown to change the behavior."""
    minimal_p2: str | None = None
    """P2 status of the minimal candidate's probe (MINIMIZED only); UNRESOLVED means it
    ran as a support probe and isn't SUPPORTED until committed runs show it."""


# --- typed deltas -----------------------------------------------------------------

def normalize(candidate: dict | Candidate) -> dict:
    """The candidate as the P0 model dumps it (every default explicit). Raises
    ``pydantic.ValidationError`` if it isn't well-formed."""
    if not isinstance(candidate, Candidate):
        candidate = Candidate.model_validate(candidate)
    return candidate.model_dump(mode="json")


def _step_key(step: dict) -> str:
    return json.dumps(step, sort_keys=True)


def _short(step: dict) -> str:
    rest = {k: v for k, v in step.items() if k != "action"}
    return step["action"] + (" " + json.dumps(rest, sort_keys=True) if rest else "")


class DeltaSet:
    """The typed deltas between two normalized candidates, and how to apply a subset of
    them to A (module docstring)."""

    def __init__(self, a: dict, b: dict):
        self.a, self.b = normalize(a), normalize(b)
        self.deltas: list[Delta] = []
        self._merged: list[tuple[str, dict, int | None]] = []
        diff = contrasts.input_diff(self.a, self.b)
        links_a, links_b = self.a["config"]["ap"]["links"], self.b["config"]["ap"]["links"]
        one_sided = set(range(min(len(links_a), len(links_b)), max(len(links_a), len(links_b))))
        for path, (va, vb) in diff.items():
            if not path.startswith("config."):
                continue
            m = _LINK_PATH.match(path)
            if m and int(m[1]) in one_sided:
                continue
            self._add("config", f"{path}: {json.dumps(va)} -> {json.dumps(vb)}",
                      path=path, a=va, b=vb)
        for index in sorted(one_sided):
            if index < len(links_b):
                self._add("link", f"+ config.ap.links[{index}] (B): {json.dumps(links_b[index], sort_keys=True)}",
                          path=str(index), b=links_b[index])
            else:
                self._add("link", f"- config.ap.links[{index}] (A): {json.dumps(links_a[index], sort_keys=True)}",
                          path=str(index), a=links_a[index])
        steps_a, steps_b = self.a["actions"], self.b["actions"]
        if "actions order" in diff:
            self._add("actions_order", "actions in B's order", a=steps_a, b=steps_b)
        elif "actions" in diff:
            matcher = difflib.SequenceMatcher(None, [_step_key(s) for s in steps_a],
                                              [_step_key(s) for s in steps_b], autojunk=False)
            for op, i1, i2, j1, j2 in matcher.get_opcodes():
                if op == "equal":
                    self._merged += [("common", s, None) for s in steps_a[i1:i2]]
                    continue
                for i in range(i1, i2):
                    d = self._add("action", f"- actions[{i}] {_short(steps_a[i])} (A)",
                                  a=steps_a[i])
                    self._merged.append(("a", steps_a[i], d.id))
                for j in range(j1, j2):
                    d = self._add("action", f"+ actions[{j}] {_short(steps_b[j])} (B)",
                                  b=steps_b[j])
                    self._merged.append(("b", steps_b[j], d.id))

    def _add(self, kind: str, label: str, **fields) -> Delta:
        delta = Delta(id=len(self.deltas), kind=kind, label=label, **fields)
        self.deltas.append(delta)
        return delta

    def apply(self, subset) -> dict:
        """A with the deltas in ``subset`` (IDs) applied: a complete candidate dict, not
        yet checked by P0."""
        chosen = set(subset)
        out = copy.deepcopy(self.a)
        removed = []
        for d in self.deltas:
            if d.id not in chosen:
                continue
            if d.kind == "config":
                _set_path(out, d.path, copy.deepcopy(d.b))
            elif d.kind == "link":
                if d.b is not None:
                    out["config"]["ap"]["links"].append(copy.deepcopy(d.b))
                else:
                    removed.append(int(d.path))
            elif d.kind == "actions_order":
                out["actions"] = copy.deepcopy(self.b["actions"])
        for index in sorted(removed, reverse=True):
            del out["config"]["ap"]["links"][index]
        if self._merged:
            out["actions"] = [copy.deepcopy(step) for side, step, d in self._merged
                              if side == "common" or (side == "a") != (d in chosen)]
        return out


def _set_path(data: dict, path: str, value: Any) -> None:
    """Set a ``contrasts.input_diff`` config path (e.g. ``config.ap.links[0].akms``)."""
    *parents, leaf = path.split(".")
    node = data
    for segment in parents:
        name, index = _SEGMENT.match(segment).groups()
        node = node[name] if index is None else node[name][int(index)]
    node[leaf] = value


def deltas(a: dict, b: dict) -> list[Delta]:
    """The typed deltas from candidate A to candidate B."""
    return DeltaSet(a, b).deltas


# --- interestingness ----------------------------------------------------------------

def _support(candidate: Candidate):
    from explorer.support import check_support
    return check_support(candidate)


def _default_runner(candidate, cache, **kwargs):
    from explorer.cache import run_cached
    return run_cached(candidate, cache, **kwargs)


def _norm_value(value: Any) -> Any:
    return json.loads(json.dumps(value))


class BudgetExhausted(Exception):
    """Raised before a guest run that would go past ``max_guest_runs``."""


class Minimizer:
    """The interestingness wrapper (module docstring). Callable as a Picire test:
    ``minimizer(config, config_id)`` with ``config`` a list of delta IDs."""

    def __init__(self, a: dict, b: dict, target: dict[str, Any], *, cache=None,
                 runner: Callable = _default_runner,
                 support: Callable = _support,
                 unsupported: Callable | None = None,
                 retries: int = 1, run_support_probes: bool = True,
                 context: dict | None = None, max_guest_runs: int | None = None,
                 **run_kwargs):
        if max_guest_runs is not None and max_guest_runs < 0:
            raise ValueError("max_guest_runs can't be negative")
        self.max_guest_runs = max_guest_runs
        self.guest_runs = 0
        if not target:
            raise ValueError("no target facts: nothing for a probe to reproduce")
        if bad := [f for f, v in target.items() if v == UNKNOWN]:
            raise ValueError(f"target facts must be measured on B, got UNKNOWN for {bad}")
        self.delta_set = DeltaSet(a, b)
        self.target = {f: _norm_value(v) for f, v in target.items()}
        if cache is None and runner is _default_runner:
            from explorer.cache import Cache
            cache = Cache()
        self.cache = cache
        self.runner = runner
        self.support = support
        if unsupported is None:
            from explorer.adapter import unsupported
        self.unsupported = unsupported
        self.retries = retries
        self.run_support_probes = run_support_probes
        self.context = context or {}
        self.run_kwargs = run_kwargs
        self.trace: list[Probe] = []
        self._memo: dict[tuple[int, ...], Probe] = {}

    def __call__(self, config, config_id) -> Outcome:
        label = " / ".join(str(part) for part in config_id) if isinstance(
            config_id, tuple) else str(config_id)
        return Outcome.FAIL if self.probe(config, label).interesting else Outcome.PASS

    def probe(self, subset, config_id: str = "") -> Probe:
        """Test one subset of deltas (memoized: picire re-asserts the current config)."""
        key = tuple(sorted(set(subset)))
        if key in self._memo:
            return self._memo[key]
        probe = self._probe(key, config_id)
        self._memo[key] = probe
        self.trace.append(probe)
        return probe

    def _probe(self, key: tuple[int, ...], config_id: str) -> Probe:
        from explorer.validate import (check_action_order, find_undetermined,
                                       parse_candidate, run_p1_checks)
        data = self.delta_set.apply(key)
        base = {"index": len(self.trace), "config_id": config_id, "deltas": list(key),
                "candidate": data}
        candidate, malformed = parse_candidate(data)
        if candidate is None:
            return Probe(**base, status="INVALID", stage="P0",
                         rule_ids=[f.rule_id for f in malformed],
                         reason="; ".join(f.message() for f in malformed))
        setting = run_p1_checks(candidate.config)
        order = check_action_order(candidate)
        questions = find_undetermined(candidate.config)
        for stage, findings in (("P1", setting), ("action_order", order)):
            violations = [f for f in findings if f.outcome == "SPEC_RULE_VIOLATION"]
            if violations:
                return Probe(**base, status="INVALID", stage=stage,
                             rule_ids=[f.rule_id for f in violations],
                             reason="; ".join(f.message() for f in violations))
        open_ = [f for f in questions + order if f.outcome == "SPEC_UNDETERMINED"]
        if open_:
            return Probe(**base, status="SPEC_UNDETERMINED",
                         stage="action_order" if open_[0] in order else "P1",
                         rule_ids=[f.rule_id for f in open_],
                         reason="; ".join(f.message() for f in open_))
        support = self.support(candidate)
        base["p2"] = support.status
        if support.status == "UNSUPPORTED_IMPLEMENTATION":
            return Probe(**base, status="UNSUPPORTED", stage="P2",
                         rule_ids=[support.limit] if support.limit else [], reason=support.note)
        support_probe = support.status != "SUPPORTED"
        if support_probe and not (support.all_values_evidenced and self.run_support_probes):
            return Probe(**base, status="UNRESOLVED", stage="P2", reason=support.note)
        base["support_probe"] = support_probe
        if reasons := self.unsupported(candidate):
            return Probe(**base, status="UNSUPPORTED", stage="adapter",
                         reason="; ".join(reasons))
        return self._run(candidate, base)

    def _run(self, candidate: Candidate, base: dict) -> Probe:
        attempts = []
        outcome = ran = None
        for attempt in range(1, self.retries + 2):
            if self.max_guest_runs is not None and self.guest_runs >= self.max_guest_runs:
                raise BudgetExhausted(f"{self.guest_runs} guest runs used")
            context = {**self.context, "minimize_probe": base["index"],
                       "deltas": base["deltas"], "attempt": attempt}
            outcome, ran = self.runner(candidate, self.cache, context=context,
                                       **self.run_kwargs)
            self.guest_runs += ran is not None
            attempts.append(Attempt(run_id=outcome.run_id, status=outcome.status,
                                    reason=outcome.reason, cache_hit=ran is None))
            if outcome.status not in RETRY_ON:
                break
        base.update(attempts=attempts, run_ids=[a.run_id for a in attempts if a.run_id],
                    cache_hit=ran is None, independent=ran is not None and outcome.independent)
        if outcome.status != "ACCEPTED":
            return Probe(**base, status=outcome.status, stage="P3", reason=outcome.reason)
        values, matched, differing, unknown = _compare(outcome.signature, self.target)
        status = "NOT_INTERESTING" if differing else "UNKNOWN" if unknown else "INTERESTING"
        return Probe(**base, status=status, stage="facts", facts=values, matched=matched,
                     differing=differing, unknown=unknown)


def _compare(signature: dict | None, target: dict[str, Any]):
    """(values, matched, differing, unknown) of a run's facts against the target facts. A
    fact the run didn't measure (``UNKNOWN``) is neither a match nor a difference."""
    observed = contrasts.facts(signature) if signature else {}
    values, matched, differing, unknown = {}, [], [], []
    for fact, wanted in target.items():
        value = observed.get(fact, UNKNOWN)
        values[fact] = value
        if value == UNKNOWN:
            unknown.append(fact)
        elif value == wanted:
            matched.append(fact)
        else:
            differing.append(fact)
    return values, matched, differing, unknown


def minimize(a: dict, b: dict, target: dict[str, Any], **kwargs) -> Reduction:
    """Reduce the deltas from A to B to a 1-minimal subset that still reproduces B's
    ``target`` facts (module docstring). ``kwargs`` go to ``Minimizer`` (``cache``,
    ``runner``, ``support``, ``retries``, ``context``, and run options such as
    ``log_dir``)."""
    m = Minimizer(a, b, target, **kwargs)
    everything = [d.id for d in m.delta_set.deltas]
    status, minimal = "MINIMIZED", []
    try:
        if not m.probe(everything, "target").interesting:
            status = "TARGET_NOT_INTERESTING"
        elif m.probe([], "baseline").interesting:
            status = "BASELINE_INTERESTING"
        else:
            minimal = sorted(DD(m)(everything))
    except BudgetExhausted:
        status, minimal = "BUDGET_EXHAUSTED", []
    return _reduction(m, status, minimal)


def from_contrast(contrast: contrasts.Contrast, facts: list[str] | None = None,
                  **kwargs) -> Reduction:
    """``minimize`` from a contrast's A to its B, targeting B's value of each claimed fact,
    or of ``facts`` (a subset of the claimed ones; module docstring, "Choosing the
    target")."""
    claimed = {f.fact: f.b for f in contrast.facts}
    if facts is not None:
        if not facts:
            raise ValueError("facts is empty: pick at least one claimed fact")
        if unclaimed := [f for f in facts if f not in claimed]:
            raise ValueError(f"not claimed by this contrast: {unclaimed}; claimed facts are "
                             f"{sorted(claimed)}")
        claimed = {f: claimed[f] for f in facts}
    return minimize(contrast.candidate_a, contrast.candidate_b, claimed, **kwargs)


def _reduction(m: Minimizer, status: str, minimal: list[int]) -> Reduction:
    needed, minimal_p2 = [], None
    if status == "MINIMIZED":
        minimal_p2 = m._memo[tuple(minimal)].p2
        for d in minimal:
            without = m._memo.get(tuple(x for x in minimal if x != d))
            if without is not None and without.status in ("INVALID", "SPEC_UNDETERMINED"):
                needed.append(d)
    return Reduction(
        needed_for_validity=needed, minimal_p2=minimal_p2,
        status=status, candidate_a=m.delta_set.a, candidate_b=m.delta_set.b,
        target=m.target, deltas=m.delta_set.deltas, minimal=minimal,
        minimal_candidate=m.delta_set.apply(minimal) if status == "MINIMIZED" else None,
        trace=m.trace, counts=dict(Counter(p.status for p in m.trace)),
        guest_runs=sum(not a.cache_hit for p in m.trace for a in p.attempts),
        cache_hits=sum(p.cache_hit for p in m.trace))


# --- reproducing the final sides (#73) -------------------------------------------------

class SideRun(BaseModel):
    """One run of a final side, made for the reproduction (never served from the cache)."""
    run_id: str | None
    status: str
    reason: str | None = None
    facts: dict[str, Any] = {}
    """The run's value of each target fact (ACCEPTED only)."""
    matches_target: bool | None = None
    """True: every target fact measured and equal to B's. False: a measured target fact
    differs. None: not ACCEPTED, or a target fact unmeasured (UNKNOWN)."""


class Verification(BaseModel):
    """The minimized contrast's two final sides, each run ``runs`` times in fresh guests:
    A as it was (``baseline``: every run must differ from the target) and A with the
    minimal deltas (``minimal``: every run must match it)."""
    label: Literal["MINIMIZED", "PENDING_VERIFICATION"]
    """MINIMIZED only when both sides gave ``runs`` ACCEPTED runs that all came out as
    expected; otherwise PENDING_VERIFICATION, never minimized."""
    runs: int
    baseline: list[SideRun]
    minimal: list[SideRun]
    """Every attempt, reruns included (a SETUP_FAIL / TIMEOUT attempt is rerun once)."""
    note: str


def verify(reduction: Reduction, runs: int = contrasts.REPRODUCE_RUNS, *, cache=None,
           runner: Callable = _default_runner, retries: int = 1,
           context: dict | None = None, **run_kwargs) -> Verification:
    """Run both final sides of a MINIMIZED reduction ``runs`` times each in fresh guests
    (``force``: never a cache hit) and check every run reproduces its side (#73)."""
    from explorer.validate import parse_candidate
    if reduction.status != "MINIMIZED":
        raise ValueError(f"nothing to verify: the reduction is {reduction.status}")
    if cache is None and runner is _default_runner:
        from explorer.cache import Cache
        cache = Cache()
    sides = {"baseline": (reduction.candidate_a, False),
             "minimal": (reduction.minimal_candidate, True)}
    results: dict[str, list[SideRun]] = {}
    complete = True
    for side, (data, expected) in sides.items():
        candidate, malformed = parse_candidate(data)
        if candidate is None:
            raise ValueError(f"{side} side isn't well-formed: {malformed}")
        results[side], finals = [], []
        for slot in range(runs):
            for attempt in range(1, retries + 2):
                outcome, ran = runner(candidate, cache, force=True,
                                      context={**(context or {}), "verify_side": side,
                                               "repeat": slot + 1, "attempt": attempt},
                                      **run_kwargs)
                if ran is None or not outcome.independent:
                    raise ValueError("verify needs fresh runs, got a cache hit")
                run = SideRun(run_id=outcome.run_id, status=outcome.status,
                              reason=outcome.reason)
                if outcome.status == "ACCEPTED":
                    values, _, differing, unknown = _compare(outcome.signature,
                                                             reduction.target)
                    run.facts = values
                    run.matches_target = (False if differing else None if unknown
                                          else True)
                results[side].append(run)
                if outcome.status not in RETRY_ON:
                    break
            finals.append(run)   # the slot's last attempt
        accepted = [r for r in finals if r.status == "ACCEPTED"]
        complete &= (len(accepted) == runs
                     and all(r.matches_target is expected for r in accepted))
    label = "MINIMIZED" if complete else "PENDING_VERIFICATION"
    note = (f"Both sides reproduced {runs}/{runs}: the baseline differs from the target "
            "in every run, the minimal candidate matches it in every run." if complete else
            "Not every run of both sides was ACCEPTED and came out as expected; see the "
            "runs. Not minimized until both sides reproduce.")
    return Verification(label=label, runs=runs, baseline=results["baseline"],
                        minimal=results["minimal"], note=note)

"""MCP server: the agent-facing interface to the explorer.

Run it over stdio (this is what ``.mcp.json`` tells Claude Code to do, through
``$WIFI7_MCP_LAUNCHER``, default ``env``; ``wsl.exe`` on the Windows side):

    .venv/bin/python -m explorer.mcp_server

``get_model`` reports only what the repo can back up (pinned versions from
``docker/Dockerfile``, implemented stages, observable behavior facts, and tests with
recorded passing runs). ``run_hwsim_test`` runs one hostap test in a fresh guest and
returns its behavior record. It only accepts tests with a passing committed run and a
known configuration (``explorer.scenarios``), so the agent can't start arbitrary tests
or commands. Before running, it applies the coded P1 rules: a test whose
configuration breaks one (e.g. plain SAE between EHT devices, 802.11be §12.12.9) only
runs as an explicitly labeled negative experiment, so it never passes for a legal
candidate. ``validate_candidate`` checks any candidate (configuration plus ordered
actions) through P0 and P1 without booting a guest, and ``explain_rule`` returns the
full registry entry behind any finding. ``plan_campaign`` / ``run_campaign`` plan and run
a bounded pairwise campaign (issue #69, over ``explorer.planner`` and ``explorer.campaign``);
``list_campaigns`` / ``get_campaign`` give the details. ``why_pruned`` and
``permitted_alternatives`` are the first two steps of the roadmap's agent chain (#74,
``explorer.pruning``); ``minimize_contrast`` is the third, over ``explorer.minimize`` (#72).
``list_contrasts`` / ``get_contrast`` / ``replay_contrast`` list and inspect contrasts by
stable ID and rerun a minimized one's final sides in fresh guests (#111).
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from explorer import adapter, campaign, model_json, planner, pruning, validate
from explorer.cache import DEFAULT_DB, Cache, run_cached
from explorer.rules import Citation, Examples, load_rules
from explorer.runner import REPO_ROOT, RunnerError, RunStatus, run_test, stale_harness
from explorer.scenarios import TEST_CONFIGS
from explorer.signatures import UNKNOWN, BehaviorRecord
from explorer.support import EVIDENCE_DIRS, SupportResult
from explorer.validate import P0_ERRORS, ValidationResult, find_undetermined, run_p1_checks

DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"

server = MCPServer(
    name="wifi7-config-explorer",
    instructions=(
        "Spec-aware Wi-Fi 7 MLO configuration explorer (CS 211 Project F). "
        "Only report what the tools return; stages marked not implemented "
        "cannot validate, run or compare candidates yet. PASSES_MODELED_RULES means "
        "only that no modeled rule objects, never full 802.11be compliance; "
        "SPEC_UNDETERMINED is neither approval nor a violation."
    ),
)


class PinnedVersions(BaseModel):
    hostap_commit: str
    kernel_commit: str
    base_image: str


class StageStatus(BaseModel):
    stage: str
    implemented: bool
    note: str


class ObservableFact(BaseModel):
    name: str
    calibrated: bool
    """False means the fact is always UNKNOWN until real runs show how to detect it."""


class RecordedRun(BaseModel):
    test: str
    run_id: str
    result: str
    evidence: str
    """Repo-relative path of the run folder."""


P1Status = Literal["PASSES_MODELED_RULES", "SPEC_RULE_VIOLATION", "SPEC_UNDETERMINED"]


class P1Finding(BaseModel):
    rule_id: str
    reason: str
    sources: list[str]
    """The normative ("shall") citations behind the rule, e.g. 'IEEE-802.11be-2024 §12.12.9'."""


class RunnableTest(BaseModel):
    test: str
    p1_status: P1Status
    """PASSES_MODELED_RULES is not full 802.11be compliance, only that no coded rule objects."""
    p1_findings: list[P1Finding]


class RuleSummary(BaseModel):
    id: str
    kind: str
    """normative / guidance / dependency / harness / policy, or open_question (UND.*)."""
    title: str


class DimensionSummary(BaseModel):
    name: str
    category: str
    """security, key or link."""
    path: str
    """Where it sits in a candidate, e.g. config.ap.sae_pwe, or actions."""
    values: list[str]
    """Its smoke-tested values as model.json labels; model.json gives the typed values."""


class Dependency(BaseModel):
    """A modeled constraint between parameters (model.json ``constraints``)."""
    id: str
    kind: str
    """normative / guidance / dependency / harness / policy."""
    role: str
    """forbidden (rules out a combination), dependency (a setting needs another) or
    action_order (AO.*, on the ordered actions)."""
    coded: bool
    """False when the rule isn't checked by code (e.g. P0 already can't express it)."""
    applies_to: list[str]
    """The dimensions / settings it ties together."""
    predicate: str


class ModelVersion(BaseModel):
    file: str
    schema_version: int
    rules_version: int
    model_digest: str
    """Changes when the schema, a dimension's values, a rule or a pinned version does."""
    dimensions: list[DimensionSummary]
    dependencies: list[Dependency]
    """The constraints between dimensions, by rule ID; explain_rule gives each in full."""


class ModelInfo(BaseModel):
    status: str
    model: ModelVersion
    """model.json: the candidate space's versions and admitted dimensions."""
    pinned_versions: PinnedVersions
    stages: list[StageStatus]
    observable_facts: list[ObservableFact]
    recorded_runs: list[RecordedRun]
    runnable_tests: list[RunnableTest]
    """Tests ``run_hwsim_test`` accepts, with what the coded P1 rules say about each."""
    rules: list[RuleSummary]
    """Every rule and open question in rules.yaml; explain_rule gives the full entry."""


class RuleExplanation(BaseModel):
    id: str
    kind: str
    """A rule kind, open_question (UND.*), or format (P0.*)."""
    status: str | None
    """draft until a person has finished checking the citations behind it."""
    title: str
    meaning: str
    predicate: str | None
    exceptions: list[str]
    sources: list[Citation]
    examples: Examples | None
    notes: list[str]


class RunReport(BaseModel):
    test: str
    p1_status: P1Status
    p1_findings: list[P1Finding]
    negative_experiment: bool
    """True when the test breaks a modeled rule and was run on request anyway."""
    status: RunStatus
    """COMPLETED (the test ran; see test_result), SETUP_FAIL or TIMEOUT."""
    run_id: str | None
    test_result: str | None
    """hostap's own PASS/FAIL/SKIP for the test, when the run completed."""
    record: BehaviorRecord | None
    run_folder: str | None
    """Where the logs are; trial runs are git-ignored, not committed evidence."""
    output_tail: str | None
    """Last console lines, only when the run didn't complete."""


STAGES = [
    StageStatus(stage="P0 structural validation", implemented=True,
                note="validate_candidate checks a candidate against the settings and action "
                     "models and reports readable P0.* errors."),
    StageStatus(stage="P1 specification rules", implemented=True,
                note="A modeled subset, not full 802.11be: ten security/setting rules, nine "
                     "action-order rules and three open questions (SPEC_UNDETERMINED), all "
                     "applied by validate_candidate and explained by explain_rule. A rule "
                     "whose status is draft (explain_rule shows it) still waits for a person "
                     "to check its citations; the others are reviewed."),
    StageStatus(stage="P2 implementation support", implemented=True,
                note="Basic: validate_candidate reports SUPPORTED when a tested hostap "
                     "scenario or a committed adapter run (pinned versions) executed the candidate "
                     "exactly, otherwise UNRESOLVED with per-value run evidence; "
                     "all_values_evidenced marks a support probe the campaign may run. "
                     "Nothing is UNSUPPORTED_IMPLEMENTATION without a recorded failure "
                     "(issue #80)."),
    StageStatus(stage="P3 execution", implemented=True,
                note="run_hwsim_test runs one approved hostap hwsim test in a fresh "
                     "UML guest and returns its behavior record; run_candidate runs any "
                     "candidate the adapter supports (ACCEPTED / REJECTED / SETUP_FAIL / "
                     "TIMEOUT)."),
    StageStatus(stage="Campaign", implemented=True,
                note="plan_campaign builds a bounded pairwise plan over the legal, executable "
                     "candidates (P0, ConfigSpace/P1 and P2 applied to every enumerated "
                     "assignment before anything boots); run_campaign re-checks each "
                     "candidate at launch and runs it through the experiment cache; "
                     "list_campaigns / get_campaign give the results."),
    StageStatus(stage="P4 compare and minimize", implemented=True,
                note="Accepted-vs-accepted contrasts are in contrasts/contrasts.json (#71). "
                     "why_pruned explains a pruned candidate with its rule evidence, "
                     "permitted_alternatives lists nearby candidates that pass the modeled "
                     "rules, and minimize_contrast reduces a contrast to its 1-minimal "
                     "changes with Picire (one run per probe). A minimized contrast "
                     "reproduced 3/3 per side is #73. list_contrasts / get_contrast give "
                     "contrasts by stable ID with their runs, facts and log lines; "
                     "replay_contrast reruns a minimized one's final sides."),
]


def pinned_versions(dockerfile: Path = DOCKERFILE) -> PinnedVersions:
    """Read the pinned commits and base image from the Dockerfile's ARG lines."""
    args = dict(re.findall(r"^ARG (\w+)=(\S+)$", dockerfile.read_text(), re.MULTILINE))
    return PinnedVersions(hostap_commit=args["HOSTAP_COMMIT"],
                          kernel_commit=args["KERNEL_COMMIT"],
                          base_image=args["UBUNTU_IMAGE"])


def observable_facts() -> list[ObservableFact]:
    """Behavior record fields, flagging those that are always UNKNOWN for now."""
    skip = {"run_id", "test"}
    return [ObservableFact(name=name, calibrated=field.default != UNKNOWN)
            for name, field in BehaviorRecord.model_fields.items() if name not in skip]


def recorded_runs(evidence_dirs=EVIDENCE_DIRS) -> list[RecordedRun]:
    """Committed runs, from each run folder's manifest.json."""
    runs = []
    for evidence_dir in evidence_dirs:
        for manifest_path in sorted(Path(evidence_dir).glob("*/manifest.json")):
            manifest = json.loads(manifest_path.read_text())
            for result in manifest["results"]:
                runs.append(RecordedRun(
                    test=result["test"], run_id=manifest["run_id"], result=result["result"],
                    evidence=str(manifest_path.parent.relative_to(REPO_ROOT))))
    return runs


def _finding_sources(rule_id: str) -> list[str]:
    """A rule's "shall" citations, or all of them if it has none (e.g. a dependency rule
    or an open question)."""
    sources = validate.cached_rules().get(rule_id).sources
    cited = [c for c in sources if c.strength == "shall"] or sources
    return [f"{c.doc} {c.location}" for c in cited]


def p1_check(test: str) -> tuple[P1Status, list[P1Finding]]:
    """What the coded P1 rules and open questions say about a hostap test's configuration."""
    config = TEST_CONFIGS[test]
    findings = run_p1_checks(config) + find_undetermined(config)
    return validate.p1_status(findings), [
        P1Finding(rule_id=f.rule_id, reason=f.reason, sources=_finding_sources(f.rule_id))
        for f in findings]


def runnable_tests(evidence_dirs=EVIDENCE_DIRS) -> list[RunnableTest]:
    """Tests with a passing committed run and a known configuration: the only ones the
    agent may start."""
    passed = {run.test for run in recorded_runs(evidence_dirs) if run.result == "PASS"}
    runnable = []
    for test in sorted(passed & TEST_CONFIGS.keys()):
        status, findings = p1_check(test)
        runnable.append(RunnableTest(
            test=test, p1_findings=findings,
            p1_status=status))
    return runnable


def rule_summaries() -> list[RuleSummary]:
    registry = load_rules()
    return [RuleSummary(id=entry.id, kind=getattr(entry, "kind", "open_question"),
                        title=entry.title)
            for entry in [*registry.rules, *registry.undetermined]]


def model_version() -> ModelVersion:
    """model.json's versions and admitted dimensions (built from the same sources the
    file is; tests/test_model_json.py keeps the file in step)."""
    built = model_json.build()
    return ModelVersion(
        file=model_json.MODEL_JSON.name,
        schema_version=built["schema_version"],
        rules_version=built["rules_version"],
        model_digest=built["model_digest"],
        dimensions=[DimensionSummary(name=d["name"], category=d["category"], path=d["path"],
                                     values=[v["label"] for v in d["values"]])
                    for d in built["dimensions"]],
        dependencies=[Dependency(**{k: c[k] for k in Dependency.model_fields})
                      for c in built["constraints"]])


@server.tool()
def get_model() -> ModelInfo:
    """Describe the explorer's current scope: model.json's versions and the admitted
    dimensions with their smoke-tested values, pinned hostap/kernel versions, which
    pipeline stages (P0-P4) are implemented, which behavior facts runs can report,
    which hostap tests have recorded runs in the repo, which tests run_hwsim_test
    accepts (with what the coded P1 rules say about each), every modeled rule and
    open question by ID, and the dependencies between dimensions (model.dependencies)."""
    return ModelInfo(
        status=("Candidates can be validated through P0, P1 and a basic P2 support check "
                "(validate_candidate), and approved hostap tests or any candidate the "
                "adapter supports run in fresh guests (run_hwsim_test, run_candidate). "
                "Bounded pairwise campaigns can be planned and run (plan_campaign, "
                "run_campaign, list_campaigns, get_campaign). why_pruned explains a pruned "
                "candidate, permitted_alternatives lists nearby legal ones, "
                "minimize_contrast reduces an accepted contrast, and list_contrasts / "
                "get_contrast / replay_contrast give and rerun contrasts (P4)."),
        model=model_version(),
        pinned_versions=pinned_versions(),
        stages=STAGES,
        observable_facts=observable_facts(),
        recorded_runs=recorded_runs(),
        runnable_tests=runnable_tests(),
        rules=rule_summaries(),
    )


@server.tool()
def validate_candidate(candidate: dict[str, Any]) -> ValidationResult:
    """Check one candidate without running it: P0 (does it fit the model?) then P1 (do
    the modeled rules accept it?). Nothing is booted.

    A candidate is {"config": {"ap": {...}, "sta": {...}}, "actions": [...]}; see
    get_model's runnable_tests and explorer.model for the fields. For example:
    {"config": {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE-EXT-KEY"]},
    {"link_id": 1, "channel": 6, "akms": ["SAE-EXT-KEY"]}]}, "sta": {"akms":
    ["SAE-EXT-KEY"]}}, "actions": [{"action": "associate"}, {"action": "rekey_gtk_now"}]}.

    status is MALFORMED (P0.* findings), SPEC_RULE_VIOLATION, SPEC_UNDETERMINED (the
    modeled rules can't decide; neither approved nor a violation) or
    PASSES_MODELED_RULES (not full 802.11be compliance). Each finding gives its stage,
    rule ID, reason, the rule's kind and its cited sources; call explain_rule for the
    full entry.

    A candidate that passes the modeled rules also gets p2, the implementation support
    check: SUPPORTED with the test name and run IDs when a tested hostap scenario executed
    it exactly (run it with run_hwsim_test), or when a committed adapter run did on the
    pinned versions (test explorer_candidate; run it with run_candidate). Otherwise
    UNRESOLVED with the committed runs behind each of its values and the closest tests.
    UNRESOLVED isn't "unsupported"; it means no run shows this exact combination. With
    all_values_evidenced true, every value has a passing legal run: a support probe. A
    value with a recorded refusal (runs/rejected/) is listed in recorded_refusals."""
    return validate.validate_candidate(candidate)


@server.tool()
def explain_rule(rule_id: str) -> RuleExplanation:
    """The full entry behind a rule ID from a finding or get_model: a rule (SEC.*,
    AO.*), an open question (UND.*) or a P0 format error (P0.*). Gives its kind
    (normative rules come from an IEEE "shall"; AO.* rules are harness/policy, not
    Wi-Fi spec rules), review status, meaning, the check in plain language,
    exceptions, every cited source (document, section, page, strength, what it says,
    who checked it) and allowed/disallowed examples."""
    if rule_id in P0_ERRORS:
        return RuleExplanation(
            id=rule_id, kind="format", status=None, title=P0_ERRORS[rule_id],
            meaning=f"The candidate doesn't fit explorer.model: {P0_ERRORS[rule_id]}.",
            predicate=None, exceptions=[], sources=[], examples=None, notes=[])
    registry = load_rules()
    try:
        entry = registry.get(rule_id)
    except KeyError:
        known = sorted([*registry.by_id, *P0_ERRORS])
        raise ToolError(f"no rule {rule_id!r}; known IDs: {known}") from None
    return RuleExplanation(
        id=entry.id, kind=getattr(entry, "kind", "open_question"), status=entry.status,
        title=entry.title, meaning=entry.meaning, predicate=getattr(entry, "predicate", None),
        exceptions=getattr(entry, "exceptions", []), sources=entry.sources,
        examples=getattr(entry, "examples", None), notes=entry.notes)


@server.tool()
def why_pruned(candidate: dict[str, Any]) -> pruning.PruneExplanation:
    """Why the campaign would prune this candidate (same JSON as validate_candidate), with
    the evidence. Nothing is booted.

    role is the planner's: malformed (P0), pruned (a modeled rule rejects it, P1),
    undetermined (an open question; held for review, P1), unsupported (an implementation
    limit with recorded refusals, P2), not_run (some value has no passing committed run,
    P2), probe or supported (executable: not pruned). Each finding gives the rule ID, what
    the candidate does, the rule's predicate, every cited source (section, page, strength,
    who checked it), how ConfigSpace encodes it, and its experimental validation: committed
    runs that break the rule (runs_breaking_it) and runs its spec-coverage rows cite. AO.*
    and other harness/policy rules aren't Wi-Fi spec rules. campaign_assignment gives its
    dimension labels when it's one of the campaign space's assignments. Next step:
    permitted_alternatives."""
    return pruning.why_pruned(candidate)


@server.tool()
def permitted_alternatives(candidate: dict[str, Any], max_changes: int = 1,
                           limit: int = 10) -> pruning.AlternativesResult:
    """Candidates near this one (same JSON as validate_candidate) that pass the modeled
    rules: up to max_changes (1-3) of model.json's admitted dimensions changed on the
    candidate itself, everything else kept. Nothing is booted; takes about a second.

    Only minimal alternatives are listed (no superset of a smaller permitted change),
    ranked by fewest changes, then P2 SUPPORTED (a committed run did exactly this; run_ids
    to rerun it with run_candidate), then support probes, then fewest changed inputs. Each
    gives the changes (old -> new label), the exact inputs that differ, P2's status and the
    full candidate. Passing the modeled rules is never full 802.11be compliance, and only a
    SUPPORTED alternative has run. Raises for a malformed candidate: fix it first."""
    try:
        return pruning.permitted_alternatives(candidate, max_changes=max_changes,
                                              limit=limit)
    except ValueError as exc:
        raise ToolError(str(exc)) from None


# --- Minimize a contrast (#74, step 3, over explorer.minimize from #72) ---------------

MAX_MINIMIZE_RUNS = 40
"""Most new guest runs one minimize_contrast call may make (about 30 s each)."""
MINIMIZE_RUNNER = run_cached
"""How a minimization probe runs (cache lookup, else a fresh guest); tests replace it."""


class MinimizeSide(BaseModel):
    run_ids: list[str]
    """The committed ACCEPTED runs of this side's candidate."""
    candidate: dict


class MinimizeProbe(BaseModel):
    config_id: str
    """Picire's ID for the test, or target (all deltas) / baseline (none)."""
    deltas: list[int]
    status: str
    """INTERESTING (reproduces every target fact), NOT_INTERESTING, INVALID, SPEC_UNDETERMINED,
    UNSUPPORTED, UNRESOLVED, UNKNOWN, REJECTED, SETUP_FAIL or TIMEOUT. Only INTERESTING
    counts as evidence."""
    stage: str | None
    rule_ids: list[str]
    run_ids: list[str]
    cache_hit: bool
    """Served from the cache: evidence of an earlier run, not a new one."""
    differing: list[str]
    unknown: list[str]


class MinimizeReport(BaseModel):
    label: str | None
    """The contrast's #73 label: PENDING_VERIFICATION whenever the reduction found a minimal
    change. This tool never verifies, so it never says MINIMIZED; that label needs both
    final sides reproduced 3/3 (scripts/minimize_contrast.py verify). None when nothing
    was reduced."""
    reduction_status: str
    """The reduction itself (minimize.Reduction.status): MINIMIZED (a 1-minimal change was
    found, one run per probe; see label), TARGET_NOT_INTERESTING (B's candidate didn't
    reproduce the target), BASELINE_INTERESTING (A already shows it) or BUDGET_EXHAUSTED
    (max_guest_runs reached first; no result)."""
    side_a: MinimizeSide
    side_b: MinimizeSide
    target: dict[str, Any]
    """B's value of each fact a probe must reproduce."""
    deltas: list[str]
    """Every typed change from A to B, as 'id: label'."""
    minimal: list[str]
    """The 1-minimal changes that still reproduce the target (MINIMIZED only)."""
    minimal_candidate: dict | None
    minimal_p2: str | None
    """P2 for the minimal candidate: UNRESOLVED means it ran once as a support probe and has
    no committed runs yet."""
    needed_for_validity: list[str]
    """Minimal changes whose removal gave an INVALID / SPEC_UNDETERMINED probe: kept to keep
    the candidate legal, not shown to change the behavior."""
    probes: list[MinimizeProbe]
    """Every probe, in order, with its run IDs: the exact evidence behind the result."""
    counts: dict[str, int]
    guest_runs: int
    cache_hits: int
    note: str


def _minimize_sides(contrast: str | None, run_a: str | None, run_b: str | None,
                    facts: list[str] | None):
    """(candidate A, runs A, candidate B, runs B, target facts) for the request."""
    from explorer import contrasts
    if (contrast is None) == (run_a is None and run_b is None):
        raise ToolError("give either contrast (a contrast ID from list_contrasts) or both "
                        "run_a and run_b (committed ACCEPTED runs), not both")
    if contrast is not None:
        entry = _found_contrasts().get(contrast)
        if entry is None:
            hint = (" (that's a minimized contrast: get_contrast shows its reduction, "
                    "replay_contrast reruns it)" if contrast in _minimized_dirs() else "")
            raise ToolError(f"no contrast {contrast!r} in contrasts/contrasts.json{hint}; "
                            f"known: {sorted(_found_contrasts())}")
        claimed = {f["fact"]: f["b"] for f in entry["facts"]}
        return (entry["candidate_a"], entry["a_runs"], entry["candidate_b"], entry["b_runs"],
                _pick_facts(claimed, facts, "claimed by this contrast"))
    if run_a is None or run_b is None:
        raise ToolError("give both run_a and run_b")
    runs = {run.run_id: (candidate, run) for candidate, run in contrasts.accepted_runs()}
    missing = [r for r in (run_a, run_b) if r not in runs]
    if missing:
        raise ToolError(f"not a committed ACCEPTED, rule-passing run on the pinned versions: "
                        f"{missing} (contrasts.accepted_runs)")
    (cand_a, a), (cand_b, b) = runs[run_a], runs[run_b]
    differing = {f: v for f, v in b.facts.items()
                 if v != UNKNOWN and a.facts.get(f, UNKNOWN) != UNKNOWN and a.facts[f] != v}
    if not differing:
        raise ToolError(f"runs {run_a} and {run_b} differ in no measured fact: nothing to "
                        "minimize")
    return cand_a, [run_a], cand_b, [run_b], _pick_facts(
        differing, facts, f"measured on both runs and different")


def _pick_facts(available: dict[str, Any], facts: list[str] | None, what: str) -> dict:
    if facts is None:
        return available
    if not facts:
        raise ToolError("facts is empty: pick at least one fact")
    if bad := [f for f in facts if f not in available]:
        raise ToolError(f"not {what}: {bad}; choose from {sorted(available)}")
    return {f: available[f] for f in facts}


@server.tool()
def minimize_contrast(contrast: str | None = None, run_a: str | None = None,
                      run_b: str | None = None, facts: list[str] | None = None,
                      max_guest_runs: int = 20) -> MinimizeReport:
    """Minimize an accepted contrast: the smallest set of typed changes from side A's
    candidate towards side B's that still reproduces B's behavior. Boots guests: about 30 s
    per new run, at most max_guest_runs (1-40); probes the cache already holds cost
    nothing.

    Pick the pair with contrast (a contrast ID from list_contrasts, e.g. "x8dc0b42566";
    its sides are reproduced 3/3) or run_a and run_b (any two committed ACCEPTED runs, e.g. a campaign
    pair several inputs apart). facts chooses which of B's facts to reproduce: by default
    every fact the contrast claims, or every fact measured on both runs that differs.
    Prefer behavior facts (disconnect_reasons, ptk_rekeys_completed, ...): a fact that echoes
    the configuration (station_status's key_mgmt and ciphers) makes the minimizer keep
    config changes just to reproduce it.

    Every probe passes P0, P1, action order, P2 and the adapter before it can boot
    anything; only a probe whose run reproduces every target fact (INTERESTING) counts.
    The result lists every probe with its status and exact run IDs. One run per probe, so
    a found minimal change is labeled PENDING_VERIFICATION, never MINIMIZED: that #73 label
    needs both final sides reproduced 3/3 in fresh guests (scripts/minimize_contrast.py
    minimize, then verify). New runs are trials in runs/hwsim-logs/ (git-ignored)."""
    from explorer import minimize
    if not 1 <= max_guest_runs <= MAX_MINIMIZE_RUNS:
        raise ToolError(f"max_guest_runs must be 1-{MAX_MINIMIZE_RUNS}")
    cand_a, runs_a, cand_b, runs_b, target = _minimize_sides(contrast, run_a, run_b, facts)
    _require_current_image()
    context = {"minimize": f"{'+'.join(runs_a)} -> {'+'.join(runs_b)}"}
    try:
        result = minimize.minimize(cand_a, cand_b, target, cache=Cache(CACHE_DB),
                                   runner=MINIMIZE_RUNNER, max_guest_runs=max_guest_runs,
                                   context=context)
    except RunnerError as exc:
        raise ToolError(f"simulation environment unavailable: {exc}") from exc
    labels = {d.id: f"{d.id}: {d.label}" for d in result.deltas}
    notes = {
        "MINIMIZED": ("PENDING_VERIFICATION: 1-minimal for the target with one run per "
                      "probe. It becomes a MINIMIZED contrast (#73) only once both final "
                      "sides reproduce 3/3 in fresh guests: scripts/minimize_contrast.py "
                      "minimize --a <run> --b <run> --facts ... --out contrasts/<id>, then "
                      "verify --out contrasts/<id>."),
        "TARGET_NOT_INTERESTING": ("B's candidate didn't reproduce the target in this run "
                                   "(see the target probe); nothing was reduced."),
        "BASELINE_INTERESTING": "A already shows the target: there's nothing to explain.",
        "BUDGET_EXHAUSTED": (f"Stopped before guest run {max_guest_runs + 1}; no result. "
                             "Probes already run are cached, so a call with a larger "
                             "max_guest_runs resumes cheaply."),
    }
    return MinimizeReport(
        label="PENDING_VERIFICATION" if result.status == "MINIMIZED" else None,
        reduction_status=result.status,
        side_a=MinimizeSide(run_ids=runs_a, candidate=result.candidate_a),
        side_b=MinimizeSide(run_ids=runs_b, candidate=result.candidate_b),
        target=result.target, deltas=list(labels.values()),
        minimal=[labels[i] for i in result.minimal],
        minimal_candidate=result.minimal_candidate, minimal_p2=result.minimal_p2,
        needed_for_validity=[labels[i] for i in result.needed_for_validity],
        probes=[MinimizeProbe(config_id=p.config_id, deltas=p.deltas, status=p.status,
                              stage=p.stage, rule_ids=p.rule_ids, run_ids=p.run_ids,
                              cache_hit=p.cache_hit, differing=p.differing, unknown=p.unknown)
                for p in result.trace],
        counts=result.counts, guest_runs=result.guest_runs, cache_hits=result.cache_hits,
        note=notes[result.status])


# --- Contrasts: list, inspect and replay (#111) ---------------------------------------

MAX_REPLAY_RUNS = 12
"""Most guest runs one replay_contrast call may make: 2 sides x 3 runs, each rerun once on
SETUP_FAIL / TIMEOUT."""
REPLAY_RUNNER = run_cached
"""How a replay run boots (always forced: never a cache hit); tests replace it."""


def _found_contrasts() -> dict[str, dict]:
    """contrasts/contrasts.json's contrasts by ID."""
    from explorer import contrasts
    return {c["id"]: c for c in json.loads(contrasts.CONTRASTS_JSON.read_text())["contrasts"]}


def _minimized_dirs() -> dict[str, Path]:
    """Minimized contrasts (contrasts/<id>/reduction.json, #73) by folder name."""
    from explorer import contrasts
    return {d.name: d for d in sorted(contrasts.CONTRASTS_DIR.iterdir())
            if (d / "reduction.json").is_file()}


def _run_folder(run_id: str | None) -> str | None:
    """Where a committed run's folder is: contrasts/runs/, a campaign, or a minimization's
    probes. None when it isn't committed."""
    from explorer import contrasts
    if not run_id:
        return None
    for parent in (contrasts.CONTRASTS_DIR / "runs", *sorted(campaign.CAMPAIGNS.glob("*")),
                   *sorted(contrasts.CONTRASTS_DIR.glob("*/probes"))):
        if (parent / run_id / "manifest.json").is_file():
            return _folder(parent / run_id)
    return None


class ContrastListing(BaseModel):
    id: str
    """Stable: a contrasts.json ID ("x..."), or a minimized contrast's folder ("c1")."""
    kind: Literal["contrast", "minimized"]
    """contrast: found by explorer.contrasts (#71), not reduced. minimized: reduced and
    verified by scripts/minimize_contrast.py (#73), with its own folder."""
    a_runs: list[str]
    b_runs: list[str]
    inputs: list[str]
    """The inputs that differ (contrast), or every typed delta from A to B (minimized)."""
    facts: list[str]
    """Claimed fact differences (contrast), or the target facts (minimized)."""
    reproduced: bool
    """contrast: >= 3 runs per side. minimized: label MINIMIZED (both final sides 3/3)."""
    current_harness: bool | None
    """contrast: both sides ran under today's harness. None for minimized (see get_contrast)."""
    label: str | None
    """minimized only: MINIMIZED or PENDING_VERIFICATION."""
    minimal: list[str]
    """minimized only: the 1-minimal changes."""


@server.tool()
def list_contrasts() -> list[ContrastListing]:
    """Every accepted-vs-accepted contrast: those in contrasts/contrasts.json (kind
    contrast, ID "x" + 10 hex digits, each pair at most one input apart) and the minimized
    ones (kind minimized, ID the folder name, e.g. "c1"). IDs are stable: they don't
    shift when contrasts are added. get_contrast gives one with its runs, facts and log
    lines; replay_contrast reruns a minimized one; minimize_contrast reduces a contrast."""
    listing = []
    for cid, c in _found_contrasts().items():
        listing.append(ContrastListing(
            id=cid, kind="contrast", a_runs=c["a_runs"], b_runs=c["b_runs"],
            inputs=sorted(c["input_diff"]), facts=[f["fact"] for f in c["facts"]],
            reproduced=c["reproduced"], current_harness=c["current_harness"], label=None,
            minimal=[]))
    for cid, d in _minimized_dirs().items():
        data = json.loads((d / "reduction.json").read_text())
        red = data["reduction"]
        labels = {x["id"]: x["label"] for x in red["deltas"]}
        listing.append(ContrastListing(
            id=cid, kind="minimized", a_runs=data["contrast"]["a_runs"],
            b_runs=data["contrast"]["b_runs"], inputs=list(labels.values()),
            facts=data["target_facts"], reproduced=data["label"] == "MINIMIZED",
            current_harness=None, label=data["label"],
            minimal=[labels[i] for i in red["minimal"]]))
    return listing


class EvidencedRun(BaseModel):
    run_id: str
    folder: str | None
    """Repo-relative run folder (logs, plan, manifest); None if it isn't committed."""


class ContrastFact(BaseModel):
    fact: str
    a: Any
    b: Any
    evidence_a: list[str]
    """Log lines A's value was read from ("folder/file:line: text")."""
    evidence_b: list[str]


class ContrastEntry(BaseModel):
    """A contrasts.json contrast in full."""
    a_runs: list[EvidencedRun]
    b_runs: list[EvidencedRun]
    input_diff: dict[str, list[Any]]
    """Candidate path -> [A's value, B's value]."""
    facts: list[ContrastFact]
    unstable: list[str]
    """Facts that differ between repeats of one side; nothing is claimed about them."""
    reproduced: bool
    harness: str | None
    current_harness: bool
    candidate_a: dict
    candidate_b: dict


class ReplayableRun(BaseModel):
    run_id: str | None
    status: str
    facts: dict[str, Any]
    """The run's value of each target fact."""
    matches_target: bool | None
    """True: matches B's value of every target fact; False: a measured one differs."""
    folder: str | None
    evidence: list[str]
    """Log lines the target facts were read from."""


class MinimizedEntry(BaseModel):
    """A minimized contrast (contrasts/<id>/reduction.json) in full."""
    folder: str
    label: str
    """MINIMIZED only when both final sides reproduced 3/3 in fresh guests."""
    a_runs: list[EvidencedRun]
    b_runs: list[EvidencedRun]
    """The original contrast's sides."""
    harness: str
    input_diff: dict[str, list[Any]]
    target: dict[str, Any]
    """B's value of each target fact."""
    deltas: list[str]
    minimal: list[str]
    """The 1-minimal changes from A that reproduce the target."""
    needed_for_validity: list[str]
    candidate_a: dict
    """The baseline side."""
    minimal_candidate: dict | None
    """The minimal side: A with the minimal changes."""
    reduction_status: str
    probes: list[MinimizeProbe]
    """The reduction trace: every probe with its status and run IDs (contrasts/<id>/probes/)."""
    counts: dict[str, int]
    baseline_runs: list[ReplayableRun]
    """The verification's runs of A (each must differ from the target)."""
    minimal_runs: list[ReplayableRun]
    """The verification's runs of the minimal candidate (each must match it)."""
    readme: str | None
    """Repo-relative path of the write-up."""


class ContrastDetails(BaseModel):
    id: str
    kind: Literal["contrast", "minimized"]
    contrast: ContrastEntry | None
    minimized: MinimizedEntry | None
    note: str


def _evidenced(run_ids: list[str]) -> list[EvidencedRun]:
    return [EvidencedRun(run_id=r, folder=_run_folder(r)) for r in run_ids]


def _side_runs(side: list[dict], facts: list[str]) -> list[ReplayableRun]:
    from explorer import contrasts
    out = []
    for run in side:
        folder = _run_folder(run.get("run_id"))
        evidence = ([line for f in facts for line in contrasts.evidence(folder, f)]
                    if folder else [])
        out.append(ReplayableRun(run_id=run.get("run_id"), status=run["status"],
                                 facts=run.get("facts") or {},
                                 matches_target=run.get("matches_target"), folder=folder,
                                 evidence=evidence))
    return out


def _minimized_entry(d: Path) -> MinimizedEntry:
    data = json.loads((d / "reduction.json").read_text())
    red, verification = data["reduction"], data.get("verification") or {}
    labels = {x["id"]: x["label"] for x in red["deltas"]}
    facts = data["target_facts"]
    readme = d / "README.md"
    return MinimizedEntry(
        folder=_folder(d), label=data["label"],
        a_runs=_evidenced(data["contrast"]["a_runs"]),
        b_runs=_evidenced(data["contrast"]["b_runs"]),
        harness=data["contrast"]["harness"], input_diff=data["contrast"]["input_diff"],
        target=red["target"], deltas=list(labels.values()),
        minimal=[labels[i] for i in red["minimal"]],
        needed_for_validity=[labels[i] for i in red["needed_for_validity"]],
        candidate_a=red["candidate_a"], minimal_candidate=red["minimal_candidate"],
        reduction_status=red["status"],
        probes=[MinimizeProbe(config_id=p["config_id"], deltas=p["deltas"], status=p["status"],
                              stage=p.get("stage"), rule_ids=p.get("rule_ids", []),
                              run_ids=p.get("run_ids", []), cache_hit=p.get("cache_hit", False),
                              differing=p.get("differing", []), unknown=p.get("unknown", []))
                for p in red["trace"]],
        counts=red["counts"],
        baseline_runs=_side_runs(verification.get("baseline", []), facts),
        minimal_runs=_side_runs(verification.get("minimal", []), facts),
        readme=_folder(readme) if readme.is_file() else None)


@server.tool()
def get_contrast(contrast_id: str) -> ContrastDetails:
    """One contrast from list_contrasts, with its evidence. Nothing is booted.

    A contrast (ID "x..."): both sides' run IDs and folders, the differing inputs, each
    claimed fact with A's and B's value and the log lines it was read from, and the facts
    that were unstable between repeats (nothing is claimed about those).

    A minimized contrast (ID e.g. "c1"): the original sides, the target facts, every typed
    delta, the 1-minimal changes, the reduction trace (every probe with its status and run
    IDs), and the 3/3 verification runs of both final sides with their facts, folders and
    log lines. replay_contrast reruns those two sides."""
    found = _found_contrasts()
    if contrast_id in found:
        c = found[contrast_id]
        entry = ContrastEntry(
            a_runs=_evidenced(c["a_runs"]), b_runs=_evidenced(c["b_runs"]),
            input_diff=c["input_diff"],
            facts=[ContrastFact(**{k: f[k] for k in ContrastFact.model_fields})
                   for f in c["facts"]],
            unstable=c["unstable"], reproduced=c["reproduced"], harness=c["harness"],
            current_harness=c["current_harness"], candidate_a=c["candidate_a"],
            candidate_b=c["candidate_b"])
        return ContrastDetails(
            id=contrast_id, kind="contrast", contrast=entry, minimized=None,
            note=("Found among committed ACCEPTED runs (contrasts/contrasts.json); claimed "
                  "facts are measured on both sides and stable in every repeat. Not reduced: "
                  "minimize_contrast(contrast=...) finds its minimal change."))
    minimized = _minimized_dirs()
    if contrast_id in minimized:
        return ContrastDetails(
            id=contrast_id, kind="minimized", contrast=None,
            minimized=_minimized_entry(minimized[contrast_id]),
            note=("Reduced with Picire and verified by scripts/minimize_contrast.py. Only "
                  "probes with status INTERESTING are evidence of the target behavior; "
                  "replay_contrast reruns both final sides in fresh guests."))
    raise ToolError(f"no contrast {contrast_id!r}; known: {sorted([*found, *minimized])}")


class ReplayReport(BaseModel):
    id: str
    committed_label: str
    """The committed verification's label; a replay never changes it."""
    replay: Literal["REPRODUCED", "NOT_REPRODUCED"]
    """REPRODUCED when every replay run of both sides came back ACCEPTED and as expected
    (the baseline differs from the target, the minimal candidate matches it)."""
    runs: int
    """Runs per side."""
    target: dict[str, Any]
    baseline_runs: list[ReplayableRun]
    minimal_runs: list[ReplayableRun]
    """Every attempt, reruns after SETUP_FAIL / TIMEOUT included."""
    same_facts_as_committed: bool
    """Every ACCEPTED replay run has the same target facts as the committed runs of its side."""
    guest_runs: int
    cache_hits: int
    """Always 0: replay runs are forced fresh, never served from the cache."""
    note: str


@server.tool()
def replay_contrast(contrast_id: str, runs: int = 3, retries: int = 1) -> ReplayReport:
    """Rerun a minimized contrast (ID from list_contrasts, e.g. "c1") and compare it with
    the committed result: its two final sides, A as it was (the baseline) and A with the
    minimal changes, each `runs` times (1-3) in fresh guests. Boots guests: about 30 s per
    run, at most 2 x runs x (retries + 1) (retries 0-1 per run, on SETUP_FAIL / TIMEOUT
    only), never more than 12. Every run is forced fresh: none is a cache hit.

    REPRODUCED means every run came back ACCEPTED and as expected: the baseline differs
    from the target in every run, the minimal candidate matches it in every run.
    same_facts_as_committed says whether the facts also equal the committed runs'. The
    replay runs are trials in runs/hwsim-logs/ (git-ignored); the committed label and
    files are never changed. Refused if the simulation image is older than the repo's
    harness files (rebuild with scripts/build-env.sh)."""
    from explorer import minimize
    minimized = _minimized_dirs()
    if contrast_id not in minimized:
        hint = (" (not minimized yet: minimize_contrast reduces it)"
                if contrast_id in _found_contrasts() else "")
        raise ToolError(f"no minimized contrast {contrast_id!r}{hint}; minimized: "
                        f"{sorted(minimized)}")
    if not 1 <= runs <= 3:
        raise ToolError("runs must be 1-3")
    if not 0 <= retries <= 1:
        raise ToolError("retries must be 0 or 1")
    data = json.loads((minimized[contrast_id] / "reduction.json").read_text())
    reduction = minimize.Reduction.model_validate(data["reduction"])
    if reduction.status != "MINIMIZED":
        raise ToolError(f"{contrast_id}'s reduction is {reduction.status}: nothing to replay")
    _require_current_image()
    folders: dict[str, str | None] = {}

    def runner(candidate, cache, **kwargs):
        outcome, ran = REPLAY_RUNNER(candidate, cache, **kwargs)
        if outcome.run_id:
            folders[outcome.run_id] = (_folder(Path(outcome.run_dir)) if outcome.run_dir
                                       else None)
        return outcome, ran

    cache = Cache(CACHE_DB)
    try:
        result = minimize.verify(reduction, runs, cache=cache, runner=runner,
                                 retries=retries, context={"replay": contrast_id})
    except RunnerError as exc:
        raise ToolError(f"simulation environment unavailable: {exc}") from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        cache.close()
    committed = data.get("verification") or {}
    expected = {side: [r["facts"] for r in committed.get(side, []) if r["status"] == "ACCEPTED"]
                for side in ("baseline", "minimal")}
    facts = data["target_facts"]

    def replayed(side_runs) -> list[ReplayableRun]:
        from explorer import contrasts
        out = []
        for r in side_runs:
            folder = folders.get(r.run_id)
            evidence = ([line for f in facts for line in contrasts.evidence(folder, f)]
                        if folder and not Path(folder).is_absolute() else [])
            out.append(ReplayableRun(run_id=r.run_id, status=r.status, facts=r.facts,
                                     matches_target=r.matches_target, folder=folder,
                                     evidence=evidence))
        return out

    same = all(r.facts in expected[side]
               for side, side_runs in (("baseline", result.baseline),
                                       ("minimal", result.minimal))
               for r in side_runs if r.status == "ACCEPTED")
    reproduced = result.label == "MINIMIZED"
    return ReplayReport(
        id=contrast_id, committed_label=data["label"],
        replay="REPRODUCED" if reproduced else "NOT_REPRODUCED", runs=runs,
        target=reduction.target, baseline_runs=replayed(result.baseline),
        minimal_runs=replayed(result.minimal), same_facts_as_committed=same,
        guest_runs=len(result.baseline) + len(result.minimal), cache_hits=0,
        note=(("Both sides reproduced: " if reproduced else
               "Not reproduced: not every run came back ACCEPTED and as expected; ") +
              f"{runs} fresh run(s) per side. The committed label ({data['label']}) and "
              "files are unchanged; replay runs are trials in runs/hwsim-logs/ (git-ignored), "
              "not evidence until a person commits them."))


@server.tool()
def run_hwsim_test(test: str, negative_experiment: bool = False) -> RunReport:
    """Run one hostap hwsim test in a fresh simulated network (a new UML guest with
    mac80211_hwsim, pinned hostap/kernel) and return the observed behavior record.
    Only tests in get_model's runnable_tests are accepted. Takes about 30 seconds.

    The test's configuration is checked against the coded P1 rules and open questions
    first. If it breaks a rule or hits an open question (p1_status SPEC_RULE_VIOLATION or
    SPEC_UNDETERMINED), the run is refused unless negative_experiment is true; such a run
    is labeled as a negative experiment and is never evidence that the configuration is
    legal. PASSES_MODELED_RULES means no coded rule objects, not
    full 802.11be compliance.

    A COMPLETED run whose test_result is FAIL is still a real observation; SETUP_FAIL
    and TIMEOUT mean nothing was observed. The run is a trial: its logs are kept under
    runs/hwsim-logs/ (git-ignored), not as committed evidence."""
    allowed = {entry.test: entry for entry in runnable_tests()}
    if test not in allowed:
        raise ToolError(f"{test!r} is not a runnable test; choose one of {sorted(allowed)}")
    entry = allowed[test]
    if entry.p1_findings and not negative_experiment:
        broken = "; ".join(f"{f.rule_id} ({', '.join(f.sources)}): {f.reason}"
                           for f in entry.p1_findings)
        raise ToolError(f"{test!r} doesn't pass the modeled rules ({entry.p1_status}): {broken}. Pass "
                        f"negative_experiment=true to run it anyway as a labeled "
                        f"negative experiment.")
    try:
        result = run_test(test)
    except RunnerError as exc:
        # The environment can't run tests at all; nothing was observed.
        raise ToolError(f"simulation environment unavailable: {exc}") from exc
    completed = result.status == "COMPLETED"
    run_folder = None
    if result.run_dir is not None:
        run_folder = (str(result.run_dir.relative_to(REPO_ROOT))
                      if result.run_dir.is_relative_to(REPO_ROOT) else str(result.run_dir))
    return RunReport(
        test=test,
        p1_status=entry.p1_status,
        p1_findings=entry.p1_findings,
        negative_experiment=bool(entry.p1_findings),
        status=result.status,
        run_id=result.record.run_id if completed else None,
        test_result=result.record.test_result if completed else None,
        record=result.record,
        run_folder=run_folder,
        output_tail=None if completed else result.output_tail,
    )


class CandidateRunReport(BaseModel):
    status: str
    """validate_candidate's status for the candidate (PASSES_MODELED_RULES, or a rule
    violation / undetermined case run as a negative experiment)."""
    findings: list[validate.ExplainedFinding]
    negative_experiment: bool
    """True when the candidate doesn't pass the modeled rules and was run on request anyway."""
    p2: SupportResult | None
    """validate_candidate's P2 result: SUPPORTED means a tested hostap scenario or a
    committed adapter run did exactly this; UNRESOLVED with all_values_evidenced means
    this run is a support probe. None when the modeled rules didn't pass the candidate."""
    p3_status: adapter.P3Status
    """ACCEPTED (every action carried out), REJECTED (hostapd/wpa_supplicant refused a
    setup step or action; see reason), SETUP_FAIL or TIMEOUT (nothing said about the
    candidate). Not a statement about the Wi-Fi spec."""
    reason: str | None
    run_id: str | None
    record: BehaviorRecord | None
    run_folder: str | None
    """Logs, the plan (explorer_plan.json) and manifest; trial runs are git-ignored."""


@server.tool()
def run_candidate(candidate: dict[str, Any], negative_experiment: bool = False) -> CandidateRunReport:
    """Run a candidate (same JSON as validate_candidate) in a fresh simulated network,
    even one no hostap test sets up, and return its P3 status and behavior record. Takes
    about 30-60 seconds.

    The candidate is validated first. Unless it passes the modeled rules, it's refused,
    or run only with negative_experiment=true and labeled as such. Settings and actions
    the adapter can't express yet (actions other than associate, link_remove,
    rekey_gtk_now, sta_disconnect_reconnect and disable_enable_mld) are refused before
    anything boots.

    The adapter observes the same way after every action (links, station status,
    traffic on each active link) and after interval rekeys, so its record can differ
    from a hostap test's own record on facts that test chose to observe differently."""
    result = validate.validate_candidate(candidate)
    if result.status == "MALFORMED":
        raise ToolError("malformed candidate: " + "; ".join(
            f"{f.rule_id}: {f.reason}" for f in result.findings))
    if result.status != "PASSES_MODELED_RULES" and not negative_experiment:
        broken = "; ".join(f"{f.rule_id}: {f.reason}" for f in result.findings)
        raise ToolError(f"the candidate doesn't pass the modeled rules ({result.status}): "
                        f"{broken}. Pass negative_experiment=true to run it anyway as a "
                        "labeled negative experiment.")
    parsed, _ = validate.parse_candidate(candidate)
    if reasons := adapter.unsupported(parsed):
        raise ToolError("the adapter can't run this candidate yet: " + "; ".join(reasons))
    _require_current_image()
    try:
        run = adapter.run_candidate(parsed)
    except RunnerError as exc:
        raise ToolError(f"simulation environment unavailable: {exc}") from exc
    run_folder = None
    if run.run_dir is not None:
        run_folder = (str(run.run_dir.relative_to(REPO_ROOT))
                      if run.run_dir.is_relative_to(REPO_ROOT) else str(run.run_dir))
    return CandidateRunReport(
        status=result.status, findings=result.findings,
        negative_experiment=result.status != "PASSES_MODELED_RULES", p2=result.p2,
        p3_status=run.status, reason=run.reason, run_id=run.run_id, record=run.record,
        run_folder=run_folder)


def _require_current_image() -> None:
    """Refuse to run on an image built from older harness files (runner.stale_harness):
    its runs would be filed under the repo's harness and could report false results."""
    try:
        stale = stale_harness()
    except RunnerError as exc:
        raise ToolError(f"simulation environment unavailable: {exc}") from exc
    if stale:
        raise ToolError(f"the wifi7-env image is older than docker/{', docker/'.join(stale)} "
                        "in the repo, so its runs wouldn't test the current code; rebuild it "
                        "with scripts/build-env.sh, then try again")


# --- Campaigns (issue #69) ---------------------------------------------------------

MAX_BUDGET = 40
"""Most candidates one plan may hold: the roadmap's campaign is about 20, so a plan can't
turn into an unbounded number of guest boots."""
MAX_RETRIES = 2
CAMPAIGN_RUNNER = run_cached
"""How run_campaign runs one candidate (cache lookup, else a fresh guest); tests replace it."""
CACHE_DB = DEFAULT_DB
_PLANS: dict[str, dict] = {}
"""Plans made by plan_campaign in this server process, by plan ID."""
_PLAN_ID = re.compile(r"^seed(?P<seed>-?\d+)-b(?P<budget>\d+)-(?P<mode>runs|fresh)-[0-9a-f]{8}$")
_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PlannedCandidate(BaseModel):
    id: str
    role: str
    """probe (every value has a passing legal run, the combination hasn't run) or
    supported (this exact candidate already ran; the cache answers it without a boot)."""
    source: str
    """allpairspy, or top_up (added to cover pairs allpairspy left)."""
    choices: dict[str, str]
    """The model.json label of each dimension; the F02 base supplies everything else."""


class PairCoverage(BaseModel):
    feasible_pairs: int
    planned_feasible_pairs: int
    """Feasible pairs some planned candidate contains (not yet run)."""
    covered_feasible_pairs: int
    """Feasible pairs a committed legal ACCEPTED run already contains."""


class CampaignPlanSummary(BaseModel):
    plan_id: str
    """Pass it to run_campaign."""
    seed: int
    budget: int
    build_on_runs: bool
    model_digest: str
    funnel: dict[str, Any]
    """Enumerated assignments surviving P0 -> ConfigSpace/P1 -> P2, with P1 rejections by
    rule ID, then planned and cut by the budget."""
    modeled_admissible: PairCoverage
    """Pairs feasible after P0/P1."""
    executable: PairCoverage
    """Pairs feasible after P2 too."""
    infeasible_pairs: int
    review_queue: int
    """SPEC_UNDETERMINED assignments: kept out of the campaign, never approved."""
    candidates: list[PlannedCandidate]
    note: str


class CandidateResult(BaseModel):
    id: str
    status: str
    """ACCEPTED / REJECTED / SETUP_FAIL / TIMEOUT, or NOT_RUN_P1 / NOT_RUN_ADAPTER when the
    launch-time re-check refused it (nothing booted)."""
    run_id: str | None
    cache_hit: bool | None
    """True when the experiment cache answered (no new guest, not an independent run)."""
    reason: str | None


class CampaignSummary(BaseModel):
    campaign_id: str
    folder: str
    """Repo-relative: run folders, results.json, rejected_cases.csv, pruning_counts.json."""
    seed: int
    started_at: str
    finished_at: str
    p3: dict[str, int]
    not_run_at_launch: dict[str, int]
    executed: dict[str, int]
    """guest_boots, cache_hits, retries, distinct_candidates_run."""
    candidates: list[CandidateResult]


class CampaignDetails(CampaignSummary):
    pruning_counts: dict[str, Any]
    rejected_cases: list[dict[str, str]]
    """Every case that didn't run or didn't come back ACCEPTED, with rule IDs or reasons."""
    candidate: dict[str, Any] | None
    """The full entry for candidate_id: choices, candidate JSON, attempts, signature."""


def _plan_id(plan: dict) -> str:
    blob = json.dumps([c["choices"] for c in plan["candidates"]] + [plan["model"]["model_digest"]],
                      sort_keys=True)
    mode = "runs" if plan["build_on_runs"] else "fresh"
    return (f"seed{plan['seed']}-b{plan['budget']}-{mode}-"
            f"{hashlib.sha256(blob.encode()).hexdigest()[:8]}")


def _make_plan(seed: int, budget: int, build_on_runs: bool) -> tuple[dict, dict]:
    """The plan and its pair coverage, as scripts/plan_campaign.py computes them, without
    writing the repo-root files. A fresh Space each time: evidence changes after runs."""
    space = planner.Space()
    plan = planner.plan(seed, budget, space, build_on_runs=build_on_runs)
    rows = [tuple(c["choices"][n] for n in space.names) for c in plan["candidates"]]
    ran = space.rows(lambda a: a.legal and a.p2_status == "SUPPORTED")
    return plan, planner.coverage(space, rows, ran)


def _pairs(block: dict) -> PairCoverage:
    return PairCoverage(feasible_pairs=block["feasible_pairs"],
                        planned_feasible_pairs=block["planned_feasible_pairs"],
                        covered_feasible_pairs=block["covered_feasible_pairs"])


@server.tool()
def plan_campaign(seed: int = 0, budget: int = planner.DEFAULT_BUDGET,
                  build_on_runs: bool = True) -> CampaignPlanSummary:
    """Plan a bounded pairwise campaign over model.json's admitted dimensions. Nothing
    boots; takes a few seconds.

    Every assignment of the dimensions (on the legal F02 base) goes through P0,
    ConfigSpace/P1 (modeled rules; SPEC_UNDETERMINED ones go to a review queue, never
    the campaign) and P2 (only SUPPORTED candidates and support probes are executable).
    allpairspy then picks candidates covering every executable pair of values, topped up
    where it falls short, at most `budget` (1-40). The same seed gives the same plan for
    the same evidence.

    build_on_runs (default) counts pairs already covered by committed runs, so the plan
    lists only what's left; an empty plan means every executable pair has run. Pass
    build_on_runs=false (or another seed) for a full fresh design; candidates that have
    already run are then answered by the cache without a boot.

    Returns a brief summary with a plan_id for run_campaign."""
    if not 1 <= budget <= MAX_BUDGET:
        raise ToolError(f"budget must be 1-{MAX_BUDGET}, got {budget}")
    plan, cover = _make_plan(seed, budget, build_on_runs)
    plan_id = _plan_id(plan)
    _PLANS[plan_id] = plan
    funnel = plan["funnel"]
    if not plan["candidates"]:
        note = ("Nothing to run: every executable pair is already covered by committed runs. "
                "Use build_on_runs=false or another seed for a fresh design.")
    else:
        note = (f"{len(plan['candidates'])} candidates planned, nothing run yet. "
                f"run_campaign(plan_id={plan_id!r}) runs them in fresh guests.")
        if funnel["cut_by_budget"]:
            note += f" {funnel['cut_by_budget']} more were cut by the budget."
    return CampaignPlanSummary(
        plan_id=plan_id, seed=seed, budget=budget, build_on_runs=build_on_runs,
        model_digest=plan["model"]["model_digest"], funnel=funnel,
        modeled_admissible=_pairs(cover["modeled_admissible"]),
        executable=_pairs(cover["executable"]),
        infeasible_pairs=len(cover["infeasible_pairs"]),
        review_queue=len(plan["review_queue"]),
        candidates=[PlannedCandidate(**{k: c[k] for k in PlannedCandidate.model_fields})
                    for c in plan["candidates"]],
        note=note)


def _find_plan(plan_id: str) -> dict:
    """A plan made earlier, or (after a server restart) the same plan made again; refused
    if the evidence or model changed in between, since that changes what's planned."""
    if plan_id in _PLANS:
        return _PLANS[plan_id]
    m = _PLAN_ID.match(plan_id)
    if not m:
        raise ToolError(f"unknown plan_id {plan_id!r}; call plan_campaign first")
    plan, _ = _make_plan(int(m["seed"]), int(m["budget"]), m["mode"] == "runs")
    if _plan_id(plan) != plan_id:
        raise ToolError(f"plan {plan_id!r} no longer matches the model and evidence (it "
                        f"would now be {_plan_id(plan)!r}); call plan_campaign again")
    _PLANS[plan_id] = plan
    return plan


def _folder(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def _summary(campaign_dir: Path, results: dict, counts: dict) -> dict:
    return dict(
        campaign_id=results["campaign"], folder=_folder(campaign_dir), seed=results["seed"],
        started_at=results["started_at"], finished_at=results["finished_at"],
        p3=counts["P3"], not_run_at_launch=counts["not_run_at_launch"],
        executed=counts["executed"],
        candidates=[CandidateResult(id=r["id"], status=r["status"], run_id=r.get("run_id"),
                                    cache_hit=r.get("cache_hit"), reason=r.get("reason"))
                    for r in results["results"]])


@server.tool()
def run_campaign(plan_id: str, campaign_id: str | None = None,
                 retries: int = 1) -> CampaignSummary:
    """Run every candidate of a plan from plan_campaign, each in a fresh simulated network
    (about 5-10 s per guest; a 20-candidate campaign takes a few minutes).

    Each candidate is re-checked at launch with today's rules (P0/P1 and what the
    adapter can express) and skipped as NOT_RUN_P1 / NOT_RUN_ADAPTER if it no longer
    passes, so a campaign never runs a rule-breaking candidate. Then the experiment cache
    answers it if the same candidate already ran under the same versions (no boot), or a
    fresh guest runs it. SETUP_FAIL / TIMEOUT are rerun up to `retries` times (0-2);
    REJECTED is a result and never retried. Refused if the simulation image is older
    than the repo's harness files (rebuild with scripts/build-env.sh).

    Writes campaigns/<campaign_id>/ (run folders, campaign_plan.json, results.json,
    rejected_cases.csv, pruning_counts.json) and the repo-root pruning_counts.json, as
    scripts/run_campaign.py does. They're evidence only once a person reviews and commits
    them. Returns a brief summary with each candidate's status and run ID; get_campaign
    gives the details."""
    if not 0 <= retries <= MAX_RETRIES:
        raise ToolError(f"retries must be 0-{MAX_RETRIES}, got {retries}")
    plan = _find_plan(plan_id)
    if not plan["candidates"]:
        raise ToolError(f"plan {plan_id!r} has no candidates; nothing to run")
    campaign_id = campaign_id or f"seed{plan['seed']}-{datetime.now(timezone.utc):%Y-%m-%dT%H%M%SZ}"
    if not _CAMPAIGN_ID.match(campaign_id):
        raise ToolError("campaign_id may use letters, digits, '.', '_' and '-' (at most 64)")
    campaign_dir = campaign.CAMPAIGNS / campaign_id
    if campaign_dir.exists():
        raise ToolError(f"{_folder(campaign_dir)} already exists; choose another campaign_id")
    _require_current_image()
    cache = Cache(CACHE_DB)
    try:
        cache.rebuild()
        results = campaign.run(plan, campaign_id, cache=cache, campaigns_dir=campaign.CAMPAIGNS,
                               retries=retries, runner=CAMPAIGN_RUNNER)
    except RunnerError as exc:
        raise ToolError(f"simulation environment unavailable: {exc}. Runs that finished "
                        f"before this are in {_folder(campaign_dir)}.") from exc
    finally:
        cache.close()
    counts = campaign.pruning_counts(plan, results)
    rejected = campaign.rejected_cases(plan, results, planner.Space())
    campaign.write(campaign_dir, plan, results, rejected, counts)
    return CampaignSummary(**_summary(campaign_dir, results, counts))


class CampaignListing(BaseModel):
    campaign_id: str
    folder: str
    seed: int
    started_at: str
    p3: dict[str, int]


def _campaign_dirs() -> list[Path]:
    return sorted(d for d in campaign.CAMPAIGNS.glob("*") if (d / "results.json").is_file())


@server.tool()
def list_campaigns() -> list[CampaignListing]:
    """Campaigns in campaigns/ (committed ones and any run_campaign wrote here), with
    their P3 counts. get_campaign gives one in detail."""
    listing = []
    for d in _campaign_dirs():
        results = json.loads((d / "results.json").read_text())
        statuses = [r["status"] for r in results["results"]]
        listing.append(CampaignListing(
            campaign_id=d.name, folder=_folder(d), seed=results["seed"],
            started_at=results["started_at"],
            p3={s: statuses.count(s) for s in campaign.P3_STATUSES}))
    return listing


@server.tool()
def get_campaign(campaign_id: str, candidate_id: str | None = None) -> CampaignDetails:
    """One campaign in detail: its pruning funnel (P0 -> ConfigSpace/P1 -> P2 -> P3), the
    rejected-cases table (P1 rejections with rule IDs, non-ACCEPTED runs with reasons) and
    each candidate's status. With candidate_id (e.g. "c03"), also that candidate's full
    entry: its choices, the candidate JSON, every attempt and its behavior signature."""
    by_id = {d.name: d for d in _campaign_dirs()}
    if campaign_id not in by_id:
        raise ToolError(f"no campaign {campaign_id!r}; known: {sorted(by_id)}")
    d = by_id[campaign_id]
    results = json.loads((d / "results.json").read_text())
    counts = json.loads((d / "pruning_counts.json").read_text())
    with (d / "rejected_cases.csv").open(newline="") as f:
        rejected = list(csv.DictReader(f))
    candidate = None
    if candidate_id is not None:
        entries = {r["id"]: r for r in results["results"]}
        if candidate_id not in entries:
            raise ToolError(f"campaign {campaign_id!r} has no candidate {candidate_id!r}; "
                            f"known: {sorted(entries)}")
        planned = {c["id"]: c for c in json.loads((d / "campaign_plan.json").read_text())["candidates"]}
        candidate = {**entries[candidate_id],
                     "candidate": planned.get(candidate_id, {}).get("candidate")}
        if run_id := candidate.get("run_id"):
            if (d / run_id).is_dir():
                candidate["run_folder"] = _folder(d / run_id)
    return CampaignDetails(**_summary(d, results, counts), pruning_counts=counts,
                           rejected_cases=rejected, candidate=candidate)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()

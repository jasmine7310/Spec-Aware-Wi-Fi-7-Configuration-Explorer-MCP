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
full registry entry behind any finding. Campaign and contrast tools are added as the
stages behind them are built.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from explorer import adapter, validate
from explorer.rules import Citation, Examples, load_rules
from explorer.runner import REPO_ROOT, RunnerError, RunStatus, run_test
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


class ModelInfo(BaseModel):
    status: str
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
                note="A modeled subset, not full 802.11be: six security/setting rules, nine "
                     "action-order rules and three open questions (SPEC_UNDETERMINED), all "
                     "applied by validate_candidate and explained by explain_rule. Every "
                     "rule's citations are checked, and they're all reviewed."),
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
    StageStatus(stage="P4 compare and minimize", implemented=False,
                note="Planned for Weeks 3-5."),
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


@server.tool()
def get_model() -> ModelInfo:
    """Describe the explorer's current scope: pinned hostap/kernel versions, which
    pipeline stages (P0-P4) are implemented, which behavior facts runs can report,
    which hostap tests have recorded runs in the repo, which tests run_hwsim_test
    accepts (with what the coded P1 rules say about each), and every modeled rule and
    open question by ID."""
    return ModelInfo(
        status=("Candidates can be validated through P0, P1 and a basic P2 support check "
                "(validate_candidate), and approved hostap tests run in fresh guests "
                "(run_hwsim_test). Campaigns and contrasts aren't built yet."),
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


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()

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
candidate. Validation, campaign and contrast tools are added as the stages behind
them are built.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from explorer.rules import load_rules
from explorer.runner import REPO_ROOT, RunnerError, RunStatus, run_test
from explorer.scenarios import TEST_CONFIGS
from explorer.signatures import UNKNOWN, BehaviorRecord
from explorer.validate import run_p1_checks

DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
# Committed run evidence; runs/hwsim-logs/ holds git-ignored trial runs and is skipped.
EVIDENCE_DIRS = (REPO_ROOT / "runs" / "baseline", REPO_ROOT / "runs" / "calibration",
                 REPO_ROOT / "runs" / "smoke", REPO_ROOT / "runs" / "anchors")

server = MCPServer(
    name="wifi7-config-explorer",
    instructions=(
        "Spec-aware Wi-Fi 7 MLO configuration explorer (CS 211 Project F). "
        "Only report what the tools return; stages marked not implemented "
        "cannot validate, run or compare candidates yet."
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


P1Status = Literal["PASSES_MODELED_RULES", "SPEC_RULE_VIOLATION"]


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


class ModelInfo(BaseModel):
    status: str
    pinned_versions: PinnedVersions
    stages: list[StageStatus]
    observable_facts: list[ObservableFact]
    recorded_runs: list[RecordedRun]
    runnable_tests: list[RunnableTest]
    """Tests ``run_hwsim_test`` accepts, with what the coded P1 rules say about each."""


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
    StageStatus(stage="P0 structural validation", implemented=False,
                note="Settings model (explorer.model.Config) exists; the action model "
                     "and readable format errors don't yet."),
    StageStatus(stage="P1 specification rules", implemented=False,
                note="Rule registry (rules.yaml) and three coded checks "
                     "(SEC.MLD_COMMON_SUITES, SEC.MLD_CLIENT_COMMON_AKM, SEC.EHT_SAE_AKM). "
                     "run_hwsim_test applies them to hostap tests; there's no tool to "
                     "validate an arbitrary candidate yet."),
    StageStatus(stage="P2 implementation support", implemented=False,
                note="Smoke runs are recorded (surface_candidates.csv smoke_runs); no "
                     "support check uses them yet."),
    StageStatus(stage="P3 execution", implemented=True,
                note="run_hwsim_test runs one approved hostap hwsim test in a fresh "
                     "UML guest and returns its behavior record."),
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


def p1_findings(test: str) -> list[P1Finding]:
    """What the coded P1 rules say about a hostap test's configuration."""
    registry = load_rules()
    findings = []
    for violation in run_p1_checks(TEST_CONFIGS[test]):
        rule = registry.get(violation.rule_id)
        findings.append(P1Finding(
            rule_id=violation.rule_id, reason=violation.reason,
            sources=[f"{c.doc} {c.location}" for c in rule.sources if c.strength == "shall"]))
    return findings


def runnable_tests(evidence_dirs=EVIDENCE_DIRS) -> list[RunnableTest]:
    """Tests with a passing committed run and a known configuration: the only ones the
    agent may start."""
    passed = {run.test for run in recorded_runs(evidence_dirs) if run.result == "PASS"}
    runnable = []
    for test in sorted(passed & TEST_CONFIGS.keys()):
        findings = p1_findings(test)
        runnable.append(RunnableTest(
            test=test, p1_findings=findings,
            p1_status="SPEC_RULE_VIOLATION" if findings else "PASSES_MODELED_RULES"))
    return runnable


@server.tool()
def get_model() -> ModelInfo:
    """Describe the explorer's current scope: pinned hostap/kernel versions, which
    pipeline stages (P0-P4) are implemented, which behavior facts runs can report,
    which hostap tests have recorded runs in the repo, and which tests
    run_hwsim_test accepts, with what the coded P1 rules say about each."""
    return ModelInfo(
        status=("Early: real hostap tests can be run (run_hwsim_test) and are checked "
                "against the coded P1 rules first, but arbitrary candidates cannot be "
                "validated yet; the validation pipeline isn't built."),
        pinned_versions=pinned_versions(),
        stages=STAGES,
        observable_facts=observable_facts(),
        recorded_runs=recorded_runs(),
        runnable_tests=runnable_tests(),
    )


@server.tool()
def run_hwsim_test(test: str, negative_experiment: bool = False) -> RunReport:
    """Run one hostap hwsim test in a fresh simulated network (a new UML guest with
    mac80211_hwsim, pinned hostap/kernel) and return the observed behavior record.
    Only tests in get_model's runnable_tests are accepted. Takes about 30 seconds.

    The test's configuration is checked against the coded P1 rules first. If it breaks
    one (p1_status SPEC_RULE_VIOLATION), the run is refused unless negative_experiment
    is true; such a run is labeled as a negative experiment and is never evidence that
    the configuration is legal. PASSES_MODELED_RULES means no coded rule objects, not
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
        raise ToolError(f"{test!r} breaks modeled rules: {broken}. Pass "
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


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()

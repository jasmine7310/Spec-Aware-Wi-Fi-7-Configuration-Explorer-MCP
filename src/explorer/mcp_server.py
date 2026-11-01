"""MCP server: the agent-facing interface to the explorer.

Run it over stdio (this is what ``.mcp.json`` tells Claude Code to do, through
``$WIFI7_MCP_LAUNCHER``, default ``env``; ``wsl.exe`` on the Windows side):

    .venv/bin/python -m explorer.mcp_server

Skeleton for now: ``get_model`` reports only what the repo can back up (pinned
versions from ``docker/Dockerfile``, implemented stages, observable behavior facts,
and tests with recorded passing runs). Validation, campaign and contrast tools are
added as the stages behind them are built.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from explorer.runner import REPO_ROOT
from explorer.signatures import UNKNOWN, BehaviorRecord

DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
# Committed run evidence; runs/hwsim-logs/ holds git-ignored trial runs and is skipped.
EVIDENCE_DIRS = (REPO_ROOT / "runs" / "baseline", REPO_ROOT / "runs" / "calibration")

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


class ModelInfo(BaseModel):
    status: str
    pinned_versions: PinnedVersions
    stages: list[StageStatus]
    observable_facts: list[ObservableFact]
    recorded_runs: list[RecordedRun]


STAGES = [
    StageStatus(stage="P0 structural validation", implemented=False,
                note="Configuration/action data models not built yet."),
    StageStatus(stage="P1 specification rules", implemented=False,
                note="Rule research in progress; no rules are encoded."),
    StageStatus(stage="P2 implementation support", implemented=False,
                note="Waits on the candidate settings list."),
    StageStatus(stage="P3 execution", implemented=True,
                note="explorer.runner.run_test() runs one hostap hwsim test in a fresh "
                     "UML guest and returns its behavior record; not yet exposed as a tool."),
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


@server.tool()
def get_model() -> ModelInfo:
    """Describe the explorer's current scope: pinned hostap/kernel versions, which
    pipeline stages (P0-P4) are implemented, which behavior facts runs can report,
    and which hostap tests have recorded runs in the repo."""
    return ModelInfo(
        status=("Skeleton: only the P3 runner and behavior records exist. "
                "No configuration model or specification rules are encoded yet, so "
                "candidates cannot be validated."),
        pinned_versions=pinned_versions(),
        stages=STAGES,
        observable_facts=observable_facts(),
        recorded_runs=recorded_runs(),
    )


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()

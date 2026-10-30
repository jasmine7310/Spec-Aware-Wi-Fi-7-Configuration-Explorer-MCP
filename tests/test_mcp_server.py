import asyncio
import json
import re

from mcp import Client, StdioServerParameters

from explorer.mcp_server import pinned_versions, server
from explorer.runner import REPO_ROOT


def _call(target, tool, arguments=None):
    async def go():
        async with Client(target) as client:
            listed = await client.list_tools()
            result = await client.call_tool(tool, arguments or {})
            return [t.name for t in listed.tools], result
    return asyncio.run(go())


def _get_model():
    tools, result = _call(server, "get_model")
    assert "get_model" in tools
    assert not result.is_error
    return result.structured_content


def test_pinned_versions_come_from_the_dockerfile():
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text()
    versions = _get_model()["pinned_versions"]

    assert f"ARG HOSTAP_COMMIT={versions['hostap_commit']}" in dockerfile
    assert f"ARG KERNEL_COMMIT={versions['kernel_commit']}" in dockerfile
    assert f"ARG UBUNTU_IMAGE={versions['base_image']}" in dockerfile
    assert re.fullmatch(r"[0-9a-f]{40}", versions["hostap_commit"])


def test_only_p3_is_reported_as_implemented():
    stages = {s["stage"].split()[0]: s["implemented"] for s in _get_model()["stages"]}
    assert stages == {"P0": False, "P1": False, "P2": False, "P3": True, "P4": False}


def test_uncalibrated_facts_are_flagged():
    facts = {f["name"]: f["calibrated"] for f in _get_model()["observable_facts"]}
    assert facts["ml_probe_handled"] is False
    assert facts["btm_request_handled"] is False
    assert facts["ptk_rekeys_completed"] is True
    assert facts["valid_links"] is True
    assert "run_id" not in facts


def test_recorded_runs_are_committed_evidence_only():
    runs = _get_model()["recorded_runs"]
    by_test = {}
    for run in runs:
        by_test.setdefault(run["test"], []).append(run)
        assert run["evidence"].startswith(("runs/baseline/", "runs/calibration/"))

    assert len(by_test["eht_mld_sae_two_links"]) == 3
    assert [r["result"] for r in by_test["eht_mld_ptk_rekey"]] == ["PASS"]
    assert [r["result"] for r in by_test["eht_mld_gtk_rekey"]] == ["PASS"]


def test_pinned_versions_parser(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("ARG UBUNTU_IMAGE=ubuntu:24.04@sha256:abc\n"
                          "FROM ${UBUNTU_IMAGE}\n"
                          "ARG HOSTAP_COMMIT=1111\nARG KERNEL_COMMIT=2222\n")
    versions = pinned_versions(dockerfile)
    assert (versions.hostap_commit, versions.kernel_commit, versions.base_image) == (
        "1111", "2222", "ubuntu:24.04@sha256:abc")


def test_server_starts_the_way_mcp_json_launches_it():
    # Same command and arguments Claude Code reads from .mcp.json, run from the repo root.
    config = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]["wifi7-explorer"]
    params = StdioServerParameters(command=config["command"], args=config["args"],
                                   cwd=str(REPO_ROOT))
    tools, result = _call(params, "get_model")

    assert tools == ["get_model"]
    assert not result.is_error
    assert result.structured_content["stages"][3]["implemented"] is True

"""The campaign MCP tools (issue #69): plan_campaign, run_campaign, list_campaigns and
get_campaign, in process and over stdio. No guest boots: run_campaign's runner is replaced
by a fake, and campaigns go to a temporary folder."""

import asyncio
import json
import os
import re

import pytest
from mcp import Client, StdioServerParameters

from explorer import campaign, mcp_server
from explorer.cache import CachedOutcome
from explorer.mcp_server import server
from explorer.runner import REPO_ROOT, RunnerError


@pytest.fixture(autouse=True)
def _current_image(monkeypatch):
    # No docker call in unit tests: assume the image matches the repo's harness
    # (tests that check the guard override this).
    if os.environ.get("WIFI7_DOCKER_TESTS") != "1":
        monkeypatch.setattr(mcp_server, "stale_harness", lambda: [])


def _call(target, tool, arguments=None):
    async def go():
        async with Client(target) as client:
            return await client.call_tool(tool, arguments or {})
    return asyncio.run(go())


def _ok(tool, arguments=None):
    result = _call(server, tool, arguments)
    assert not result.is_error, result.content
    return result.structured_content


def _error(tool, arguments=None):
    result = _call(server, tool, arguments)
    assert result.is_error
    return result.content[0].text


@pytest.fixture
def campaigns(tmp_path, monkeypatch):
    """Campaign output and the cache in tmp_path; a fake runner that records each call."""
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns")
    monkeypatch.setattr(campaign, "PRUNING_COUNTS", tmp_path / "pruning_counts.json")
    monkeypatch.setattr(mcp_server, "CACHE_DB", tmp_path / "cache.sqlite")
    monkeypatch.setattr(mcp_server, "_PLANS", {})
    calls = []
    script = []

    def runner(candidate, cache, *, context, log_dir, **kwargs):
        calls.append(context)
        status = script.pop(0) if script else "ACCEPTED"
        run_id = f"9{len(calls):09d}"
        (log_dir / run_id).mkdir(parents=True)
        outcome = CachedOutcome(key="k", run_id=run_id, status=status,
                                reason=None if status == "ACCEPTED" else "why",
                                signature={"fact": 1}, run_dir=str(log_dir / run_id),
                                timeout_s=600, context=context, recorded_at="t",
                                independent=True)
        return outcome, object()

    monkeypatch.setattr(mcp_server, "CAMPAIGN_RUNNER", runner)
    return {"dir": tmp_path / "campaigns", "calls": calls, "script": script}


# --- get_model ------------------------------------------------------------------

def test_get_model_lists_the_dependencies():
    model = _ok("get_model")["model"]
    deps = {d["id"]: d for d in model["dependencies"]}
    assert deps["SEC.SAE_PWE_NEEDS_SAE"]["role"] == "dependency"
    assert "ap_sae_pwe" in deps["SEC.SAE_PWE_NEEDS_SAE"]["applies_to"]
    assert deps["SEC.MLD_COMMON_SUITES"]["role"] == "forbidden"
    assert deps["AO.ASSOC_REQUIRED"]["role"] == "action_order"
    on_disk = json.loads((REPO_ROOT / "model.json").read_text())
    assert set(deps) == {c["id"] for c in on_disk["constraints"]}


# --- plan_campaign ----------------------------------------------------------------

def test_plan_is_a_brief_summary_with_ids():
    plan = _ok("plan_campaign", {"seed": 0, "build_on_runs": False})
    assert re.fullmatch(r"seed0-b20-fresh-[0-9a-f]{8}", plan["plan_id"])
    assert 0 < len(plan["candidates"]) <= 20
    first = plan["candidates"][0]
    assert first["id"] == "c01" and set(first) == {"id", "role", "source", "choices"}
    assert plan["funnel"]["enumerated"] == plan["funnel"]["p0_well_formed"] > 0
    assert plan["executable"]["planned_feasible_pairs"] + plan["executable"][
        "covered_feasible_pairs"] >= plan["executable"]["feasible_pairs"]
    assert "nothing run yet" in plan["note"]


def test_same_seed_same_plan():
    a = _ok("plan_campaign", {"seed": 3, "build_on_runs": False})
    b = _ok("plan_campaign", {"seed": 3, "build_on_runs": False})
    assert a["plan_id"] == b["plan_id"] and a["candidates"] == b["candidates"]


def test_budget_is_bounded():
    assert "budget must be 1-40" in _error("plan_campaign", {"budget": 41})
    assert "budget must be 1-40" in _error("plan_campaign", {"budget": 0})
    plan = _ok("plan_campaign", {"budget": 3, "build_on_runs": False})
    assert len(plan["candidates"]) == 3 and plan["funnel"]["cut_by_budget"] > 0


# --- run_campaign -----------------------------------------------------------------

def test_run_writes_the_campaign_and_returns_ids(campaigns):
    plan = _ok("plan_campaign", {"budget": 4, "build_on_runs": False})
    campaigns["script"].extend(["ACCEPTED", "REJECTED"])
    out = _ok("run_campaign", {"plan_id": plan["plan_id"], "campaign_id": "t1"})
    assert out["campaign_id"] == "t1"
    assert [c["id"] for c in out["candidates"]] == [c["id"] for c in plan["candidates"]]
    assert out["p3"]["ACCEPTED"] == 3 and out["p3"]["REJECTED"] == 1
    assert all(c["run_id"] for c in out["candidates"])
    assert len(campaigns["calls"]) == 4
    folder = campaigns["dir"] / "t1"
    for name in ("results.json", "campaign_plan.json", "pruning_counts.json", "rejected_cases.csv"):
        assert (folder / name).is_file(), name


def test_plan_survives_a_server_restart(campaigns, monkeypatch):
    plan = _ok("plan_campaign", {"budget": 2, "build_on_runs": False})
    monkeypatch.setattr(mcp_server, "_PLANS", {})   # as after a restart
    out = _ok("run_campaign", {"plan_id": plan["plan_id"], "campaign_id": "t2"})
    assert len(out["candidates"]) == 2


def test_run_refuses_bad_input(campaigns):
    assert "call plan_campaign first" in _error("run_campaign", {"plan_id": "nope"})
    assert "no longer matches" in _error("run_campaign", {"plan_id": "seed0-b2-fresh-00000000"})
    plan = _ok("plan_campaign", {"budget": 1, "build_on_runs": False})
    assert "retries must be 0-2" in _error("run_campaign", {"plan_id": plan["plan_id"], "retries": 5})
    assert "campaign_id may use" in _error("run_campaign", {"plan_id": plan["plan_id"],
                                                            "campaign_id": "../x"})
    _ok("run_campaign", {"plan_id": plan["plan_id"], "campaign_id": "dup"})
    assert "already exists" in _error("run_campaign", {"plan_id": plan["plan_id"],
                                                       "campaign_id": "dup"})


def test_an_empty_plan_doesnt_run(campaigns, monkeypatch):
    real = mcp_server._make_plan

    def empty(*args):
        plan, cover = real(*args)
        return {**plan, "candidates": []}, cover
    monkeypatch.setattr(mcp_server, "_make_plan", empty)
    plan = _ok("plan_campaign", {})
    assert "Nothing to run" in plan["note"]
    assert "no candidates" in _error("run_campaign", {"plan_id": plan["plan_id"]})
    assert campaigns["calls"] == []


def test_environment_problem_is_a_tool_error(campaigns, monkeypatch):
    def broken(*args, **kwargs):
        raise RunnerError("docker not found")
    monkeypatch.setattr(mcp_server, "CAMPAIGN_RUNNER", broken)
    plan = _ok("plan_campaign", {"budget": 1, "build_on_runs": False})
    assert "simulation environment unavailable" in _error(
        "run_campaign", {"plan_id": plan["plan_id"], "campaign_id": "t3"})


# --- list_campaigns / get_campaign --------------------------------------------------

def test_details_on_request(campaigns):
    plan = _ok("plan_campaign", {"budget": 2, "build_on_runs": False})
    campaigns["script"].extend(["REJECTED"])
    _ok("run_campaign", {"plan_id": plan["plan_id"], "campaign_id": "t4"})

    listed = _call(server, "list_campaigns").structured_content["result"]
    assert [c["campaign_id"] for c in listed] == ["t4"]
    assert listed[0]["p3"]["REJECTED"] == 1

    details = _ok("get_campaign", {"campaign_id": "t4"})
    assert details["candidate"] is None
    assert any(r["outcome"] == "REJECTED" for r in details["rejected_cases"])
    assert details["pruning_counts"]["P3"]["REJECTED"] == 1

    one = _ok("get_campaign", {"campaign_id": "t4", "candidate_id": "c01"})["candidate"]
    assert one["status"] == "REJECTED" and one["candidate"]["config"]["ap"]["links"]
    assert one["run_folder"].endswith(one["run_id"])
    assert "no candidate" in _error("get_campaign", {"campaign_id": "t4", "candidate_id": "c99"})
    assert "no campaign" in _error("get_campaign", {"campaign_id": "missing"})


def test_committed_campaigns_are_listed():
    listed = {c["campaign_id"]: c for c in
              _call(server, "list_campaigns").structured_content["result"]}
    assert "seed0-2026-11-13" in listed
    details = _ok("get_campaign", {"campaign_id": "seed0-2026-11-13", "candidate_id": "c01"})
    assert details["candidate"]["run_folder"] == "campaigns/seed0-2026-11-13/1794557032"


# --- over stdio, as Claude Code launches the server -----------------------------------

def test_plan_campaign_over_stdio():
    config = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]["wifi7-explorer"]
    expand = lambda v: re.sub(r"\$\{(\w+):-([^}]*)\}",  # noqa: E731
                              lambda m: os.environ.get(m.group(1), m.group(2)), v)
    params = StdioServerParameters(command=expand(config["command"]),
                                   args=[expand(a) for a in config["args"]], cwd=str(REPO_ROOT))
    result = _call(params, "plan_campaign", {"seed": 0, "budget": 5, "build_on_runs": False})
    assert not result.is_error
    assert len(result.structured_content["candidates"]) == 5
    listed = _call(params, "list_campaigns")
    assert not listed.is_error


# --- stale image guard ------------------------------------------------------------------

def test_a_stale_image_is_refused(campaigns, monkeypatch):
    monkeypatch.setattr(mcp_server, "stale_harness", lambda: ["test_explorer_candidate.py"])
    plan = _ok("plan_campaign", {"budget": 1, "build_on_runs": False})
    message = _error("run_campaign", {"plan_id": plan["plan_id"], "campaign_id": "t5"})
    assert "scripts/build-env.sh" in message and "test_explorer_candidate.py" in message
    assert campaigns["calls"] == [] and not (campaigns["dir"] / "t5").exists()


def test_stale_harness_compares_image_and_repo(monkeypatch):
    import hashlib
    import subprocess
    from explorer import runner
    current = hashlib.sha256((REPO_ROOT / "docker" / "test_explorer_candidate.py")
                             .read_bytes()).hexdigest()
    monkeypatch.setattr(runner, "check_environment", lambda image: None)

    def fake_docker(args, timeout_s):
        out = (f"{'0' * 64}  /opt/hostap/tests/hwsim/test_eht_client_bp.py\n"
               f"{current}  /opt/hostap/tests/hwsim/test_explorer_candidate.py\n")
        return subprocess.CompletedProcess(args, 0, out, "")
    monkeypatch.setattr(runner, "_docker", fake_docker)
    assert runner.stale_harness() == ["test_eht_client_bp.py"]

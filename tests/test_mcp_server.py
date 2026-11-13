import asyncio
import json
import os
import re

import pytest
from mcp import Client, StdioServerParameters

from explorer import adapter, mcp_server
from explorer.mcp_server import pinned_versions, server
from explorer.model import Config
from explorer.rules import load_rules
from explorer.runner import REPO_ROOT, RunnerError, RunResult
from explorer.scenarios import TEST_CONFIGS
from explorer.signatures import extract_record

BASELINE_RUN = REPO_ROOT / "runs" / "baseline" / "1793298094"
SAE_EXT_RUN = REPO_ROOT / "runs" / "smoke" / "1793897820"


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


def test_implemented_stages():
    stages = {s["stage"].split()[0]: s for s in _get_model()["stages"]}
    assert {k: s["implemented"] for k, s in stages.items()} == {
        "P0": True, "P1": True, "P2": True, "P3": True, "P4": False}
    assert "not full 802.11be" in stages["P1"]["note"]
    assert stages["P2"]["note"].startswith("Basic")


def test_get_model_lists_every_rule_and_question():
    rules = {r["id"]: r for r in _get_model()["rules"]}
    assert rules["SEC.MLD_COMMON_SUITES"]["kind"] == "normative"
    assert rules["AO.ASSOC_REQUIRED"]["kind"] == "harness"
    assert rules["UND.AKM_PREFERENCE"]["kind"] == "open_question"
    assert len(rules) == 17 + 3   # rules.yaml: 17 rules + 3 open questions


def test_get_model_matches_model_json():
    import json
    from explorer.model_json import MODEL_JSON
    on_disk = json.loads(MODEL_JSON.read_text())
    model = _get_model()["model"]
    assert model["file"] == "model.json"
    assert model["model_digest"] == on_disk["model_digest"]
    assert (model["schema_version"], model["rules_version"]) == (
        on_disk["schema_version"], on_disk["rules_version"])
    assert {d["name"]: d["values"] for d in model["dimensions"]} == {
        d["name"]: [v["label"] for v in d["values"]] for d in on_disk["dimensions"]}


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
        assert run["evidence"].startswith(
            ("runs/baseline/", "runs/calibration/", "runs/smoke/", "runs/anchors/"))

    baseline = [r for r in by_test["eht_mld_sae_two_links"]
                if r["evidence"].startswith("runs/baseline/")]
    assert len(baseline) == 3
    assert {r["result"] for r in by_test["eht_mld_ptk_rekey"]} == {"PASS"}
    assert {r["result"] for r in by_test["eht_mld_gtk_rekey"]} == {"PASS"}
    assert "eht_mld_link_removal" in by_test


def test_pinned_versions_parser(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("ARG UBUNTU_IMAGE=ubuntu:24.04@sha256:abc\n"
                          "FROM ${UBUNTU_IMAGE}\n"
                          "ARG HOSTAP_COMMIT=1111\nARG KERNEL_COMMIT=2222\n")
    versions = pinned_versions(dockerfile)
    assert (versions.hostap_commit, versions.kernel_commit, versions.base_image) == (
        "1111", "2222", "ubuntu:24.04@sha256:abc")


def _expand(value):
    # Claude Code's ${VAR:-default} expansion in .mcp.json (a set but empty VAR counts as set).
    return re.sub(r"\$\{(\w+):-([^}]*)\}",
                  lambda m: os.environ.get(m.group(1), m.group(2)), value)


def test_server_starts_the_way_mcp_json_launches_it():
    # Same command and arguments Claude Code reads from .mcp.json, run from the repo root.
    config = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]["wifi7-explorer"]
    params = StdioServerParameters(command=_expand(config["command"]),
                                   args=[_expand(a) for a in config["args"]],
                                   cwd=str(REPO_ROOT))
    tools, result = _call(params, "get_model")

    assert sorted(tools) == ["explain_rule", "get_model", "run_candidate", "run_hwsim_test",
                            "validate_candidate"]
    assert not result.is_error
    assert result.structured_content["stages"][3]["implemented"] is True

    # A real validation over stdio, as the agent would call it.
    _, result = _call(params, "validate_candidate", {"candidate": {
        "config": TEST_CONFIGS["eht_mld_sae_two_links"].model_dump(),
        "actions": [{"action": "associate"}]}})
    assert result.structured_content["status"] == "SPEC_RULE_VIOLATION"


# --- validate_candidate and explain_rule ----------------------------------------

def _validate(candidate):
    tools, result = _call(server, "validate_candidate", {"candidate": candidate})
    assert "validate_candidate" in tools
    assert not result.is_error
    return result.structured_content


def test_validate_candidate_legal():
    result = _validate({"config": TEST_CONFIGS["eht_mld_sae_ext_two_links_client_bp"].model_dump(),
                        "actions": [{"action": "associate"}, {"action": "rekey_gtk_now"}]})
    assert (result["status"], result["findings"]) == ("PASSES_MODELED_RULES", [])
    # The #61 smoke run 1794384695 (an adapter run) did exactly this candidate (#80).
    assert (result["p2"]["status"], result["p2"]["test"]) == ("SUPPORTED", "explorer_candidate")


def test_validate_candidate_supported_names_the_test_to_run():
    result = _validate({"config": TEST_CONFIGS["eht_mld_gtk_rekey_client_bp"].model_dump(),
                        "actions": [{"action": "associate"}]})
    assert (result["p2"]["status"], result["p2"]["test"]) == (
        "SUPPORTED", "eht_mld_gtk_rekey_client_bp")
    assert len(result["p2"]["run_ids"]) == 3


def test_validate_candidate_malformed_is_a_result_not_a_tool_error():
    config = TEST_CONFIGS["eht_mld_sae_ext_two_links_client_bp"].model_dump()
    config["ap"]["links"][0]["link_id"] = "0"
    result = _validate({"config": config})
    assert result["status"] == "MALFORMED"
    assert [(f["rule_id"], f["reason"]) for f in result["findings"]] == [
        ("P0.TYPE_ERROR", "config.ap.links[0].link_id must be an integer")]


def test_validate_candidate_explains_a_spec_rejection():
    config = TEST_CONFIGS["eht_mld_sae_ext_two_links_client_bp"].model_dump()
    config["ap"]["links"][0]["akms"] = ["SAE"]
    config["sta"]["akms"] = ["SAE", "SAE-EXT-KEY"]
    result = _validate({"config": config})
    finding = result["findings"][0]
    assert (result["status"], finding["rule_id"], finding["kind"]) == (
        "SPEC_RULE_VIOLATION", "SEC.MLD_COMMON_SUITES", "normative")
    assert any("§12.6.2" in s for s in finding["sources"])


def test_validate_candidate_action_order():
    result = _validate({"config": TEST_CONFIGS["eht_mld_sae_ext_two_links_client_bp"].model_dump(),
                        "actions": [{"action": "rekey_gtk_now"}]})
    assert [f["rule_id"] for f in result["findings"]] == ["AO.ASSOC_REQUIRED"]


def _explain(rule_id):
    _, result = _call(server, "explain_rule", {"rule_id": rule_id})
    return result


def test_explain_a_normative_rule():
    entry = _explain("SEC.EHT_SAE_AKM").structured_content
    assert (entry["kind"], entry["status"]) == ("normative", "reviewed")
    shall = [s for s in entry["sources"] if s["strength"] == "shall"]
    assert shall[0]["location"].startswith("§12.12.9")
    assert shall[0]["page"] == "PDF 446 (printed 445)"
    assert entry["examples"]["disallowed"]


def test_every_rule_is_reviewed_except_new_drafts():
    drafts = {"AO.BSS_TM_NEEDS_BSS_TRANSITION",  # added 2026-11-05, waiting on Michelle
              "SEC.SAE_H2E_ONLY_NEEDS_STA_H2E"}  # issue #88, 2026-11-12: citations to check
    for rule in load_rules().rules:
        expected = "draft" if rule.id in drafts else "reviewed"
        assert _explain(rule.id).structured_content["status"] == expected, rule.id


def test_explain_an_action_order_rule():
    entry = _explain("AO.NO_LINKS_LEFT").structured_content
    assert entry["kind"] == "harness"
    assert entry["predicate"]


def test_explain_an_open_question():
    entry = _explain("UND.AKM_PREFERENCE").structured_content
    assert (entry["kind"], entry["predicate"], entry["examples"]) == ("open_question", None, None)
    assert entry["sources"][0]["doc"] == "WFA-WPA3"


def test_explain_a_format_error():
    entry = _explain("P0.TYPE_ERROR").structured_content
    assert entry["kind"] == "format"


def test_explain_an_unknown_rule_is_an_error():
    result = _explain("SEC.NOT_A_RULE")
    assert result.is_error
    assert "known IDs" in result.content[0].text


# --- run_hwsim_test -----------------------------------------------------------

def _runnable():
    return {entry["test"]: entry for entry in _get_model()["runnable_tests"]}


def test_runnable_tests_are_those_with_a_passing_committed_run():
    runnable = _runnable()
    assert {"eht_mld_sae_ext_two_links_client_bp", "eht_mld_ptk_rekey", "eht_mld_gtk_rekey"} <= set(runnable)
    passed = {r["test"] for r in _get_model()["recorded_runs"] if r["result"] == "PASS"}
    assert set(runnable) <= passed


def test_runnable_tests_report_their_p1_status():
    runnable = _runnable()
    assert runnable["eht_mld_sae_ext_two_links_client_bp"]["p1_status"] == "PASSES_MODELED_RULES"
    plain_sae = runnable["eht_mld_sae_two_links"]
    assert plain_sae["p1_status"] == "SPEC_RULE_VIOLATION"
    assert [f["rule_id"] for f in plain_sae["p1_findings"]] == ["SEC.EHT_SAE_AKM"]
    assert plain_sae["p1_findings"][0]["sources"] == [
        "IEEE-802.11be-2024 §12.12.9 Security constraints for EHT"]


def test_runnable_test_with_an_open_question_is_undetermined(monkeypatch):
    akms = ["SAE-EXT-KEY", "WPA-PSK"]
    config = Config.model_validate({
        "ap": {"links": [{"link_id": 0, "channel": 1, "akms": akms},
                         {"link_id": 1, "channel": 6, "akms": akms}]},
        "sta": {"akms": akms}})
    monkeypatch.setitem(mcp_server.TEST_CONFIGS, "eht_mld_sae_ext_two_links_client_bp", config)
    monkeypatch.setattr(mcp_server, "run_test", lambda test: pytest.fail("must not run"))

    entry = _runnable()["eht_mld_sae_ext_two_links_client_bp"]
    assert entry["p1_status"] == "SPEC_UNDETERMINED"
    assert entry["p1_findings"][0]["sources"][0].startswith("WFA-WPA3 Table 3")

    _, result = _call(server, "run_hwsim_test", {"test": "eht_mld_sae_ext_two_links_client_bp"})
    assert result.is_error
    assert "UND.AKM_PREFERENCE" in result.content[0].text


def _fake_completed(monkeypatch, run_dir):
    calls = []

    def fake_run_test(test):
        calls.append(test)
        return RunResult(test=test, status="COMPLETED", run_dir=run_dir,
                         record=extract_record(run_dir, test), manifest=None,
                         exit_code=0, output_tail="")
    monkeypatch.setattr(mcp_server, "run_test", fake_run_test)
    return calls


def test_run_returns_the_behavior_record(monkeypatch):
    calls = _fake_completed(monkeypatch, SAE_EXT_RUN)

    _, result = _call(server, "run_hwsim_test", {"test": "eht_mld_sae_ext_two_links_client_bp"})

    assert not result.is_error
    report = result.structured_content
    assert calls == ["eht_mld_sae_ext_two_links_client_bp"]
    assert (report["p1_status"], report["negative_experiment"]) == ("PASSES_MODELED_RULES", False)
    assert report["status"] == "COMPLETED"
    assert report["run_id"] == "1793897820"
    assert report["test_result"] == "PASS"
    assert report["record"]["station_status"]["key_mgmt"] == "SAE-EXT-KEY"
    assert report["run_folder"] == "runs/smoke/1793897820"
    assert report["output_tail"] is None


def test_refuses_a_test_that_breaks_a_modeled_rule(monkeypatch):
    # Plain SAE between EHT devices breaks 802.11be §12.12.9 (SEC.EHT_SAE_AKM).
    monkeypatch.setattr(mcp_server, "run_test", lambda test: pytest.fail("must not run"))

    _, result = _call(server, "run_hwsim_test", {"test": "eht_mld_sae_two_links"})

    assert result.is_error
    text = result.content[0].text
    assert "SEC.EHT_SAE_AKM" in text and "§12.12.9" in text
    assert "negative_experiment=true" in text


def test_refuses_the_hostap_original_with_client_beacon_protection_off(monkeypatch):
    monkeypatch.setattr(mcp_server, "run_test", lambda test: pytest.fail("must not run"))

    _, result = _call(server, "run_hwsim_test", {"test": "eht_mld_sae_ext_two_links"})

    assert result.is_error
    assert "SEC.EHT_BEACON_PROT" in result.content[0].text


def test_negative_experiment_runs_and_is_labeled(monkeypatch):
    calls = _fake_completed(monkeypatch, BASELINE_RUN)

    _, result = _call(server, "run_hwsim_test",
                      {"test": "eht_mld_sae_two_links", "negative_experiment": True})

    assert not result.is_error
    report = result.structured_content
    assert calls == ["eht_mld_sae_two_links"]
    assert (report["p1_status"], report["negative_experiment"]) == ("SPEC_RULE_VIOLATION", True)
    assert report["test_result"] == "PASS"


def test_negative_experiment_flag_on_a_legal_test_is_not_a_label(monkeypatch):
    _fake_completed(monkeypatch, SAE_EXT_RUN)

    _, result = _call(server, "run_hwsim_test",
                      {"test": "eht_mld_sae_ext_two_links_client_bp", "negative_experiment": True})

    assert result.structured_content["negative_experiment"] is False


def test_setup_fail_reports_console_output(monkeypatch):
    monkeypatch.setattr(mcp_server, "run_test", lambda test: RunResult(
        test=test, status="SETUP_FAIL", run_dir=None, record=None, manifest=None,
        exit_code=1, output_tail="guest didn't boot"))

    _, result = _call(server, "run_hwsim_test", {"test": "eht_mld_sae_ext_two_links_client_bp"})

    report = result.structured_content
    assert (report["status"], report["run_id"], report["record"]) == ("SETUP_FAIL", None, None)
    assert report["output_tail"] == "guest didn't boot"


@pytest.mark.parametrize("test", ["eht_mld_not_a_test", "eht_mld_sae_two_links; ls", ""])
def test_rejects_tests_that_are_not_runnable(monkeypatch, test):
    monkeypatch.setattr(mcp_server, "run_test", lambda test: pytest.fail("must not run"))

    _, result = _call(server, "run_hwsim_test", {"test": test})

    assert result.is_error
    assert "not a runnable test" in result.content[0].text


def test_environment_problem_is_an_error(monkeypatch):
    def no_docker(test):
        raise RunnerError("Docker isn't running; start Docker Desktop")
    monkeypatch.setattr(mcp_server, "run_test", no_docker)

    _, result = _call(server, "run_hwsim_test", {"test": "eht_mld_sae_ext_two_links_client_bp"})

    assert result.is_error
    assert "Docker isn't running" in result.content[0].text


@pytest.mark.skipif(os.environ.get("WIFI7_DOCKER_TESTS") != "1",
                    reason="set WIFI7_DOCKER_TESTS=1 to run against the real simulation image")
def test_real_run_over_mcp():
    # SAE-EXT-KEY (AKM 24) passes the modeled rules, so it runs without the override.
    _, result = _call(server, "run_hwsim_test", {"test": "eht_mld_sae_ext_two_links_client_bp"})

    assert not result.is_error
    report = result.structured_content
    assert report["p1_status"] == "PASSES_MODELED_RULES"
    assert report["status"] == "COMPLETED"
    assert report["test_result"] == "PASS"
    assert report["record"]["valid_links"] == "0x3"
    assert report["record"]["station_status"]["key_mgmt"] == "SAE-EXT-KEY"
    assert report["run_folder"].startswith("runs/hwsim-logs/")


# --- run_candidate ----------------------------------------------------------

LEGAL = {"config": {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE-EXT-KEY"]},
                                     {"link_id": 1, "channel": 6, "akms": ["SAE-EXT-KEY"]}]},
                    "sta": {"akms": ["SAE-EXT-KEY"]}},
         "actions": [{"action": "associate"}, {"action": "rekey_gtk_now"}]}


def _no_run(monkeypatch):
    monkeypatch.setattr(adapter, "run_candidate", lambda *a, **k: pytest.fail("must not run"))


def test_run_candidate_runs_a_legal_candidate(monkeypatch):
    seen = []

    def fake_run(candidate, **kwargs):
        seen.append(candidate)
        return adapter.CandidateRun(status="ACCEPTED", reason=None, run_id="1793897820",
                                    run_dir=SAE_EXT_RUN, record=extract_record(SAE_EXT_RUN),
                                    plan={})
    monkeypatch.setattr(adapter, "run_candidate", fake_run)

    _, result = _call(server, "run_candidate", {"candidate": LEGAL})

    assert not result.is_error, result.content[0].text
    report = result.structured_content
    assert [s.action for s in seen[0].actions] == ["associate", "rekey_gtk_now"]
    assert (report["status"], report["negative_experiment"]) == ("PASSES_MODELED_RULES", False)
    assert report["p3_status"] == "ACCEPTED" and report["run_id"] == "1793897820"
    # No hostap test does associate + rekey_gtk_now alone, but the adapter run 1794384695
    # did, so P2 counts it as SUPPORTED (#80) rather than a support probe.
    assert report["p2"]["status"] == "SUPPORTED"
    assert report["run_folder"] == "runs/smoke/1793897820"


def test_run_candidate_refuses_a_rule_violation(monkeypatch):
    _no_run(monkeypatch)
    plain_sae = json.loads(json.dumps(LEGAL).replace('"SAE-EXT-KEY"', '"SAE"'))
    _, result = _call(server, "run_candidate", {"candidate": plain_sae})
    assert result.is_error
    assert "SEC.EHT_SAE_AKM" in result.content[0].text
    assert "negative_experiment=true" in result.content[0].text


def test_run_candidate_refuses_malformed_input(monkeypatch):
    _no_run(monkeypatch)
    bad = json.loads(json.dumps(LEGAL).replace('"link_id": 0', '"link_id": "0"'))
    _, result = _call(server, "run_candidate", {"candidate": bad})
    assert result.is_error and "P0.TYPE_ERROR" in result.content[0].text


def test_run_candidate_refuses_what_the_adapter_cant_express(monkeypatch):
    _no_run(monkeypatch)
    probe = {**LEGAL, "actions": [{"action": "scan"}, {"action": "ml_probe_req"}]}
    _, result = _call(server, "run_candidate", {"candidate": probe})
    assert result.is_error
    assert "can't run this candidate yet" in result.content[0].text


def test_run_candidate_negative_experiment_is_labeled(monkeypatch):
    def fake_run(candidate, **kwargs):
        return adapter.CandidateRun(status="REJECTED", reason="actions[0] associate: timed out",
                                    run_id=None, run_dir=None, record=None, plan={})
    monkeypatch.setattr(adapter, "run_candidate", fake_run)
    plain_sae = json.loads(json.dumps(LEGAL).replace('"SAE-EXT-KEY"', '"SAE"'))

    _, result = _call(server, "run_candidate",
                      {"candidate": plain_sae, "negative_experiment": True})

    report = result.structured_content
    assert report["negative_experiment"] is True
    assert report["status"] == "SPEC_RULE_VIOLATION" and report["p2"] is None
    assert (report["p3_status"], report["reason"]) == ("REJECTED", "actions[0] associate: timed out")


@pytest.mark.skipif(os.environ.get("WIFI7_DOCKER_TESTS") != "1",
                    reason="set WIFI7_DOCKER_TESTS=1 to run against the real simulation image")
def test_real_candidate_over_mcp():
    # No hostap test does exactly this: associate, then a GTK rekey on its own.
    _, result = _call(server, "run_candidate", {"candidate": LEGAL})

    assert not result.is_error, result.content[0].text
    report = result.structured_content
    assert report["p3_status"] == "ACCEPTED", report["reason"]
    assert report["record"]["gtk_rekeys_completed"] >= 1
    assert report["record"]["data_test_rx_after_last_rekey_ap_links"] == [0, 1]
    assert report["run_folder"].startswith("runs/hwsim-logs/")

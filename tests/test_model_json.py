"""Checks model.json (issue #65): up to date with the code and data it's built from, and
every value it offers really fits the model."""

import json

import pytest

from explorer import model_json
from explorer.model import SCHEMA_VERSION, Candidate
from explorer.rules import load_rules
from explorer.validate import validate_candidate

MODEL = model_json.build()


def test_model_json_is_up_to_date():
    # Regenerate with: .venv/bin/python scripts/build_model_json.py
    assert model_json.MODEL_JSON.read_text(encoding="utf-8") == model_json.render()


def test_placeholder_is_gone():
    assert not (model_json.REPO_ROOT / "src" / "model.json").exists()


def test_versions():
    assert MODEL["schema_version"] == SCHEMA_VERSION
    assert MODEL["rules_version"] == load_rules().version
    assert MODEL["pinned_versions"]["hostap_commit"] == "43ee60e13c257d33d25bfb6892b9ee38fb6e88a4"
    assert MODEL["model_digest"].startswith("sha256:")


def test_candidate_schema_is_the_p0_model():
    assert MODEL["candidate_schema"] == Candidate.model_json_schema()


def test_at_least_8_dimensions_across_security_key_and_link():
    dimensions = MODEL["dimensions"]
    assert len(dimensions) >= 8
    assert {d["category"] for d in dimensions} >= {"security", "key", "link"}
    assert all(len(d["values"]) >= 2 for d in dimensions)


def test_every_admitted_row_has_a_mapping():
    # A new admitted dimension needs an entry in model_json.DIMENSIONS.
    for row in model_json.admitted_rows():
        path, values = model_json.DIMENSIONS[row["name"]]
        missing = set(model_json._smoke_runs(row)) - set(values)
        assert not missing, f"{row['name']}: no typed value for {missing}"


@pytest.mark.parametrize("dimension", MODEL["dimensions"], ids=lambda d: d["name"])
def test_every_value_fits_the_model(dimension):
    # Each value, applied to the F02 base on its own, is a well-formed candidate.
    for value in dimension["values"]:
        data = model_json.apply({dimension["name"]: value["label"]})
        Candidate.model_validate(data)


@pytest.mark.parametrize("dimension", MODEL["dimensions"], ids=lambda d: d["name"])
def test_every_value_matches_its_smoke_run(dimension):
    # A value the adapter ran (manifest records the candidate) is the same typed value.
    from explorer.support import EVIDENCE_DIRS
    for value in dimension["values"]:
        run = next((d / value["smoke_run"] for d in EVIDENCE_DIRS
                    if (d / value["smoke_run"] / "manifest.json").is_file()), None)
        assert run is not None, value
        manifest = json.loads((run / "manifest.json").read_text())
        candidate = manifest.get("explorer_plan", {}).get("explorer", {}).get("candidate")
        if candidate is None:
            continue  # a hostap test's run; tests/test_surface_candidates.py checks those
        if dimension["path"] == "actions":
            steps = [s for s in candidate["actions"] if s["action"] != "associate"]
            present = any(s["action"] == dimension["name"] for s in steps)
            assert present == (value["label"] == "present"), (dimension["name"], value)
        else:
            expected = Candidate.model_validate(model_json.apply(
                {dimension["name"]: value["label"]}, base=candidate))
            assert expected == Candidate.model_validate(candidate), (dimension["name"], value)


def test_combined_choices_apply_together():
    data = model_json.apply({"ap_sae_pwe": "1", "sta_sae_pwe": "2", "rekey_gtk_now": "present"})
    assert data["config"]["ap"]["sae_pwe"] == "hash_to_element"
    assert data["config"]["sta"]["sae_pwe"] == "both"
    assert [s["action"] for s in data["actions"]] == ["associate", "rekey_gtk_now"]
    assert validate_candidate(data).status == "PASSES_MODELED_RULES"


def test_apply_doesnt_change_its_base():
    base = model_json.base_candidate()
    before = json.dumps(base, sort_keys=True)
    model_json.apply({"ap_pairwise_cipher": "GCMP-256", "link_remove": "present"}, base=base)
    assert json.dumps(base, sort_keys=True) == before


def test_unknown_dimension_or_label_raises():
    with pytest.raises(KeyError):
        model_json.apply({"ap_mld_link_count": "3"})
    with pytest.raises(KeyError):
        model_json.apply({"ap_sae_pwe": "0"})


def test_constraints_cover_every_rule_with_a_role():
    registry = load_rules()
    by_id = {c["id"]: c for c in MODEL["constraints"]}
    assert set(by_id) == {r.id for r in registry.rules}
    assert {q["id"] for q in MODEL["open_questions"]} == {q.id for q in registry.undetermined}
    assert by_id["SEC.MLD_COMMON_SUITES"]["role"] == "forbidden"
    assert by_id["SEC.SAE_H2E_ONLY_NEEDS_STA_H2E"]["role"] == "dependency"
    assert by_id["AO.ASSOC_REQUIRED"]["role"] == "action_order"
    # Every coded check is marked coded.
    from explorer.validate import P1_CHECKS
    assert all(by_id[rule_id]["coded"] for rule_id in P1_CHECKS)


def test_dimension_rule_ids_come_from_applies_to():
    dims = {d["name"]: d for d in MODEL["dimensions"]}
    assert "SEC.SAE_H2E_ONLY_NEEDS_STA_H2E" in dims["sta_sae_pwe"]["rule_ids"]
    assert "SEC.SAE_PWE_NEEDS_SAE" in dims["ap_sae_pwe"]["rule_ids"]


def test_actions_catalog():
    actions = {a["action"]: a for a in MODEL["actions"]}
    assert set(actions) >= {"associate", "link_remove", "ml_probe_req", "rekey_gtk_now"}
    assert actions["link_remove"]["adapter_supported"] is True
    assert actions["ml_probe_req"]["adapter_supported"] is False
    assert set(actions["link_remove"]["fields"]) == {"link_id", "count"}


def test_not_admitted_rows_are_listed_not_offered():
    names = {d["name"] for d in MODEL["dimensions"]}
    not_admitted = {r["name"] for r in MODEL["not_admitted"]}
    assert not names & not_admitted
    assert {"ap_mld_link_count", "ap_beacon_protection", "ml_probe_req"} <= not_admitted


def test_digest_ignores_evidence_but_not_values():
    changed_run = json.loads(json.dumps(MODEL))
    changed_run["dimensions"][0]["values"][0]["smoke_run"] = "1"
    assert model_json.digest(changed_run) == MODEL["model_digest"]
    changed_value = json.loads(json.dumps(MODEL))
    changed_value["dimensions"][0]["values"][0]["value"] = ["SAE"]
    assert model_json.digest(changed_value) != MODEL["model_digest"]

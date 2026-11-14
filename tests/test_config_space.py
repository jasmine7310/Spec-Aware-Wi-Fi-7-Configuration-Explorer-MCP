"""Checks the ConfigSpace encoding of the static settings (issue #63): it agrees with the P1
predicates everywhere, and every coded setting rule is either in it or documented as
predicate-only. #76 (consistency checks) reuses this agreement test instead of adding one."""

import itertools

import ConfigSpace as CS
import pytest

from explorer import config_space as C
from explorer import model_json
from explorer.model import Candidate
from explorer.rules import load_rules
from explorer.validate import P1_CHECKS, check_action_order, find_undetermined, run_p1_checks

F02 = {"ap_akm": "SAE-EXT-KEY", "sta_akm": "SAE-EXT-KEY", "ap_sae_pwe": "unset",
       "sta_sae_pwe": "unset", "ap_pairwise_cipher": "CCMP", "ap_link_indicate_disabled": "0",
       "ap_ptk_rekey_interval": "unset", "ap_gtk_rekey_interval": "unset",
       "ap_beacon_protection": "1", "sta_beacon_protection": "1"}


def _p1_rule_ids(values):
    candidate = Candidate.model_validate(C.candidate(values))
    findings = (run_p1_checks(candidate.config) + find_undetermined(candidate.config)
                + check_action_order(candidate))
    return sorted({f.rule_id for f in findings})


def _all_combinations():
    hps = C.hyperparameter_values()
    return [dict(zip(hps, combo)) for combo in itertools.product(*hps.values())]


# --- Agreement with P1 (the done-when test) ---------------------------------------

def test_configspace_and_p1_agree_on_every_combination():
    # Exhaustive: every combination of the hyperparameters' values, legal or not.
    disagreements = []
    for values in _all_combinations():
        p1 = _p1_rule_ids(values)
        if C.is_valid(values) != (not p1) or C.violations(values) != p1:
            disagreements.append((values, C.is_valid(values), C.violations(values), p1))
    assert not disagreements, disagreements[:3]


def test_valid_combinations_are_the_legal_static_space():
    valid = [v for v in _all_combinations() if C.is_valid(v)]
    assert F02 in valid
    # Beacon protection has one legal value per side, so every valid one has it on.
    assert all(v["ap_beacon_protection"] == v["sta_beacon_protection"] == "1" for v in valid)


def test_samples_from_configspace_pass_the_modeled_rules():
    for config in C.space().sample_configuration(size=40):
        values = {name: config.get(name, C.UNSET) for name in C.hyperparameter_values()}
        assert _p1_rule_ids(values) == [], values


# --- One rejection per encoded rule (negative fixtures) -----------------------------

@pytest.mark.parametrize("changes, rule_id", [
    ({"ap_akm": "OWE"}, "SEC.MLD_CLIENT_COMMON_AKM"),
    ({"sta_akm": "OWE"}, "SEC.MLD_CLIENT_COMMON_AKM"),
    ({"ap_akm": "OWE", "sta_akm": "OWE", "ap_sae_pwe": "2"}, "SEC.SAE_PWE_NEEDS_SAE"),
    ({"ap_akm": "OWE", "sta_akm": "OWE", "sta_sae_pwe": "1"}, "SEC.SAE_PWE_NEEDS_SAE"),
    ({"ap_sae_pwe": "1"}, "SEC.SAE_H2E_ONLY_NEEDS_STA_H2E"),
    ({"ap_beacon_protection": "0"}, "SEC.EHT_BEACON_PROT"),
    ({"sta_beacon_protection": "0"}, "SEC.EHT_BEACON_PROT"),
])
def test_each_encoded_rule_rejects(changes, rule_id):
    values = {**F02, **changes}
    assert not C.is_valid(values)
    assert C.violations(values) == [rule_id] == _p1_rule_ids(values)


@pytest.mark.parametrize("changes", [
    {"ap_akm": "OWE", "sta_akm": "OWE"},                 # sae_pwe inactive, unset
    {"ap_sae_pwe": "1", "sta_sae_pwe": "1"},
    {"ap_sae_pwe": "1", "sta_sae_pwe": "2"},
    {"ap_sae_pwe": "2"},                                 # no H2E-only selector
    {"ap_pairwise_cipher": "GCMP-256", "ap_gtk_rekey_interval": "5"},
])
def test_legal_settings_pass(changes):
    values = {**F02, **changes}
    assert C.is_valid(values) and C.violations(values) == [] == _p1_rule_ids(values)


def test_a_forbidden_clause_doesnt_fire_on_an_inactive_setting():
    # OWE client: its sae_pwe is inactive, so "AP H2E only with the client unset" doesn't
    # apply (P1 agrees: no SAE AKM on the client); only the AKM mismatch remains.
    values = {**F02, "sta_akm": "OWE", "ap_sae_pwe": "1"}
    assert C.violations(values) == ["SEC.MLD_CLIENT_COMMON_AKM"] == _p1_rule_ids(values)


def test_setting_an_inactive_hyperparameter_is_invalid_in_configspace_itself():
    with pytest.raises(ValueError):
        CS.Configuration(C.space(), values={**{k: v for k, v in F02.items() if "sae_pwe" not in k},
                                            "ap_akm": "OWE", "sta_akm": "OWE",
                                            "ap_sae_pwe": "2"}).check_valid_configuration()


# --- Every coded setting rule is accounted for ----------------------------------------

def test_every_coded_setting_rule_is_in_configspace_or_predicate_only():
    encoded = {c.rule_id for c in C.constraints()}
    predicate_only = set(C.PREDICATE_ONLY)
    for rule_id in P1_CHECKS:
        assert (rule_id in encoded) != (rule_id in predicate_only), rule_id
    # SEC.PMF isn't coded in P1 either (P0 has no "off" value); it's documented.
    assert "SEC.PMF" in predicate_only


def test_constraints_cite_real_rules():
    known = {r.id for r in load_rules().rules}
    assert {c.rule_id for c in C.constraints()} <= known
    assert {k for k in C.PREDICATE_ONLY if k.startswith("SEC.")} <= known


def test_hyperparameters_are_the_setting_dimensions_plus_beacon_protection():
    settings = {d["name"] for d in model_json.build()["dimensions"] if d["path"] != "actions"}
    actions = {d["name"] for d in model_json.build()["dimensions"] if d["path"] == "actions"}
    names = set(C.hyperparameter_values())
    assert names == settings | set(C.FIXED_SETTINGS)
    assert not names & actions    # actions stay out (the roadmap's split)


def test_space_carries_every_constraint():
    cs = C.space()
    kinds = [c.kind for c in C.constraints()]
    assert len(cs.conditions) == kinds.count("condition")
    assert len(cs.forbidden_clauses) == kinds.count("forbidden")


def test_model_json_records_the_encoding():
    summary = model_json.build()["configspace"]
    assert summary["status"].startswith("built")
    assert {c["rule_id"] for c in summary["constraints"]} == {c.rule_id for c in C.constraints()}
    assert set(summary["predicate_only"]) == set(C.PREDICATE_ONLY)

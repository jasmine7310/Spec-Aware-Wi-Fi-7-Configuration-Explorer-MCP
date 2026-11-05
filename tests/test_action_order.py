import pytest

from explorer.model import Candidate
from explorer.rules import load_rules
from explorer.scenarios import TEST_CONFIGS
from explorer.validate import ACTION_ORDER_QUESTIONS, ACTION_ORDER_RULES, check_action_order

ASSOC = {"action": "associate"}
SCAN = {"action": "scan"}
REKEY = {"action": "rekey_gtk_now"}
PROBE = {"action": "ml_probe_req"}
DISCONNECT = {"action": "sta_disconnect_reconnect", "command": "DISCONNECT"}
RECONNECT = {"action": "sta_disconnect_reconnect", "command": "RECONNECT"}
DISABLE = {"action": "disable_enable_mld", "command": "DISABLE_MLD"}
ENABLE = {"action": "disable_enable_mld", "command": "ENABLE_MLD"}
BSS_TM = {"action": "bss_tm_link_removal_imminent"}


def remove(link_id, count=4):
    return {"action": "link_remove", "link_id": link_id, "count": count}


def reconfig(operation, link_id):
    return {"action": "setup_link_reconfig", "operation": operation, "link_id": link_id}


def _check(actions, test="eht_mld_owe_two_links"):
    candidate = Candidate.model_validate({"config": TEST_CONFIGS[test], "actions": actions})
    return check_action_order(candidate)


# Each AO rule's allowed and disallowed examples from rules.yaml / action-order.md.
ALLOWED = {
    "AO.ASSOC_REQUIRED": [ASSOC, REKEY],
    "AO.ML_PROBE_STATE": [SCAN, PROBE],
    "AO.LINK_MUST_EXIST": [ASSOC, remove(1), remove(0)],
    "AO.NO_LINKS_LEFT": [ASSOC, remove(1), remove(0)],
    "AO.RECONFIG_DELETE_ACTIVE": [ASSOC, reconfig("delete", 1)],
    "AO.RECONFIG_ADD_ABSENT": [ASSOC, reconfig("delete", 1), reconfig("add", 1)],
    "AO.RECONNECT_AFTER_DISCONNECT": [ASSOC, DISCONNECT, RECONNECT],
    "AO.ENABLE_AFTER_DISABLE": [ASSOC, DISABLE, DISCONNECT, ENABLE, RECONNECT],
    "AO.BSS_TM_NEEDS_BSS_TRANSITION": [ASSOC, BSS_TM],
}

# Allowed examples that need a configuration other than _check's default.
ALLOWED_TEST = {"AO.BSS_TM_NEEDS_BSS_TRANSITION": "eht_mld_bss_trans_mgmt_link_removal_imminent"}

DISALLOWED = [
    ("AO.ASSOC_REQUIRED", [REKEY, ASSOC], 0),
    ("AO.ASSOC_REQUIRED", [remove(1)], 0),
    ("AO.ML_PROBE_STATE", [PROBE], 0),
    # Decided 2026-11-03: probing while associated isn't admitted.
    ("AO.ML_PROBE_STATE", [SCAN, ASSOC, PROBE], 2),
    ("AO.LINK_MUST_EXIST", [ASSOC, remove(1), remove(1)], 2),
    ("AO.NO_LINKS_LEFT", [ASSOC, remove(1), remove(0), REKEY], 3),
    ("AO.RECONFIG_DELETE_ACTIVE", [ASSOC, reconfig("delete", 1), reconfig("delete", 1)], 2),
    ("AO.RECONFIG_ADD_ABSENT", [ASSOC, reconfig("add", 1)], 1),
    ("AO.RECONNECT_AFTER_DISCONNECT", [ASSOC, RECONNECT], 1),
    ("AO.ENABLE_AFTER_DISABLE", [ASSOC, ENABLE], 1),
    # The STA was never disconnected or reconnected around the re-enable.
    ("AO.ENABLE_AFTER_DISABLE", [ASSOC, DISABLE, ENABLE, REKEY], 2),
    ("AO.ENABLE_AFTER_DISABLE", [ASSOC, DISABLE, DISCONNECT, RECONNECT], 3),
    # eht_mld_owe_two_links leaves bss_transition off.
    ("AO.BSS_TM_NEEDS_BSS_TRANSITION", [ASSOC, BSS_TM], 1),
]


@pytest.mark.parametrize("rule_id", ALLOWED)
def test_allowed_examples_pass(rule_id):
    assert _check(ALLOWED[rule_id], test=ALLOWED_TEST.get(rule_id, "eht_mld_owe_two_links")) == []


@pytest.mark.parametrize("rule_id,actions,index", DISALLOWED,
                         ids=[f"{r}-{i}" for i, (r, _, _) in enumerate(DISALLOWED)])
def test_disallowed_examples_are_rejected(rule_id, actions, index):
    violations = _check(actions)
    assert [v.rule_id for v in violations] == [rule_id]
    assert violations[0].stage == "P1"
    assert violations[0].reason.startswith(f"actions[{index}] ")


def test_every_action_order_rule_is_enforced_and_tested():
    registry_ao = {r.id for r in load_rules().rules if r.id.startswith("AO.")}
    assert set(ACTION_ORDER_RULES) == registry_ao
    assert set(ALLOWED) == registry_ao
    assert {rule for rule, _, _ in DISALLOWED} == registry_ao


# --- hostap's own sequences (test_eht.py at the pinned commit) are accepted ---

REAL_SEQUENCES = {
    "eht_mld_link_removal": [ASSOC, remove(1, 4), REKEY, remove(0, 20)],
    "eht_mld_sae_two_links_disable_enable": [ASSOC, DISABLE, DISCONNECT, ENABLE, RECONNECT],
    "eht_mld_discovery": [SCAN, PROBE, {"action": "ml_probe_req", "link_id": 1}],
    "eht_ml_setup_reconfig_AB_A_AB": [ASSOC, reconfig("delete", 1), reconfig("add", 1)],
    "eht_mld_disassociate": [ASSOC, {"action": "ap_disassociate"}],
    "eht_mld_bss_trans_mgmt_link_removal_imminent": [ASSOC, {"action": "bss_tm_link_removal_imminent"}],
}


@pytest.mark.parametrize("name", REAL_SEQUENCES)
def test_hostap_sequences_pass(name):
    assert _check(REAL_SEQUENCES[name],
                  test=name if name in TEST_CONFIGS else "eht_mld_owe_two_links") == []


# --- Decisions of 2026-11-03 (docs/plan.md, "Action model") ---

@pytest.mark.parametrize("action", ["ap_disassociate", "ap_deauthenticate"])
def test_disassociation_needs_an_explicit_associate(action):
    violations = _check([ASSOC, {"action": action}, REKEY])
    assert [v.rule_id for v in violations] == ["AO.ASSOC_REQUIRED"]
    assert "explicit associate" in violations[0].reason
    assert _check([ASSOC, {"action": action}, ASSOC, REKEY]) == []


def test_last_link_reason_cites_the_standard():
    violations = _check([ASSOC, remove(1), remove(0), REKEY])
    assert "§35.3.6.3" in violations[0].reason


def test_only_disabled_links_left_reason_cites_link_disablement():
    # Link 1 still exists but is advertised as disabled, so §35.3.6.3 isn't the clause.
    violations = _check([ASSOC, remove(0), REKEY], test="eht_mld_owe_two_links_one_disabled")
    assert [v.rule_id for v in violations] == ["AO.NO_LINKS_LEFT"]
    assert "§35.3.7.5.2" in violations[0].reason
    assert "§35.3.6.3" not in violations[0].reason


def test_associating_with_only_disabled_links_is_rejected():
    violations = _check([ASSOC, remove(0), ASSOC], test="eht_mld_owe_two_links_one_disabled")
    assert [v.rule_id for v in violations] == ["AO.NO_LINKS_LEFT"]
    assert violations[0].reason.startswith("actions[2] ")
    assert "§35.3.7.5.2" in violations[0].reason


def test_associating_with_every_configured_link_disabled_is_rejected():
    config = TEST_CONFIGS["eht_mld_owe_two_links_one_disabled"].model_dump()
    config["ap"]["links"][0]["indicate_disabled"] = True
    candidate = Candidate.model_validate({"config": config, "actions": [ASSOC]})
    assert [v.rule_id for v in check_action_order(candidate)] == ["AO.NO_LINKS_LEFT"]


def test_associating_with_an_enabled_link_left_is_allowed():
    # Removing the disabled link leaves enabled link 0.
    assert _check([ASSOC, remove(1), DISCONNECT, ASSOC, REKEY],
                  test="eht_mld_owe_two_links_one_disabled") == []


def test_reassociating_after_every_link_is_removed_is_undetermined():
    # No AP links are left; none of our sources say what associating then does.
    findings = _check([ASSOC, remove(1), remove(0), ASSOC])
    assert [(f.rule_id, f.outcome) for f in findings] == [
        ("UND.ASSOC_WITHOUT_AP_LINKS", "SPEC_UNDETERMINED")]
    assert findings[0].reason.startswith("actions[3] ")


def test_reassociating_while_a_link_remains_is_allowed():
    assert _check([ASSOC, remove(1), DISCONNECT, ASSOC, REKEY]) == []


def test_associating_while_associated_is_rejected():
    violations = _check([ASSOC, remove(1), ASSOC])
    assert [v.rule_id for v in violations] == ["AO.ASSOC_REQUIRED"]
    assert "already associated" in violations[0].reason


@pytest.mark.parametrize("actions", [[DISABLE, ASSOC], [ASSOC, DISABLE, DISCONNECT, ASSOC]])
def test_associating_while_the_mld_is_disabled_is_rejected(actions):
    assert [v.rule_id for v in _check(actions)] == ["AO.ENABLE_AFTER_DISABLE"]


def test_disabling_twice_is_rejected():
    assert [v.rule_id for v in _check([DISABLE, DISABLE])] == ["AO.ENABLE_AFTER_DISABLE"]


def test_deleting_the_last_link_by_reconfig_leaves_the_sta_unassociated():
    violations = _check([ASSOC, reconfig("delete", 1), reconfig("delete", 0), REKEY])
    assert [v.rule_id for v in violations] == ["AO.NO_LINKS_LEFT"]
    assert _check([ASSOC, reconfig("delete", 1), reconfig("delete", 0), ASSOC, REKEY]) == []


def test_adding_a_disabled_link_is_rejected():
    violations = _check([ASSOC, reconfig("add", 1)], test="eht_mld_owe_two_links_one_disabled")
    assert [v.rule_id for v in violations] == ["AO.RECONFIG_ADD_ABSENT"]
    assert "§35.3.7.5.2" in violations[0].reason


@pytest.mark.parametrize("actions", [
    [SCAN, DISABLE, PROBE],
    [DISABLE, SCAN, ENABLE, PROBE],
    [SCAN, ASSOC, remove(1), remove(0), PROBE],
    [SCAN, ASSOC, remove(1), DISCONNECT, {"action": "ml_probe_req", "link_id": 1}],
])
def test_probe_needs_the_scanned_ap_to_still_exist(actions):
    assert [v.rule_id for v in _check(actions)] == ["AO.ML_PROBE_STATE"]


def test_probe_of_a_remaining_link_after_a_removal_is_allowed():
    assert _check([SCAN, ASSOC, remove(1), DISCONNECT, PROBE]) == []


def test_actions_while_mld_disabled_without_disconnect_are_undetermined():
    # mac80211 may not notice the AP MLD going away (test_eht.py:737-739).
    findings = _check([ASSOC, DISABLE, REKEY])
    assert [(f.rule_id, f.outcome) for f in findings] == [
        ("UND.STA_STATE_WHILE_MLD_DISABLED", "SPEC_UNDETERMINED")]


def test_disconnect_while_mld_disabled_is_allowed():
    assert _check([ASSOC, DISABLE, DISCONNECT, ENABLE, RECONNECT, REKEY]) == []


def test_every_action_order_question_is_registered():
    registry = load_rules()
    assert set(ACTION_ORDER_QUESTIONS) <= {q.id for q in registry.undetermined}


# --- A link advertised as disabled isn't one of the STA's links (802.11be §35.3.7.5.2) ---

def test_disabled_link_is_not_active():
    violations = _check([ASSOC, reconfig("delete", 1)], test="eht_mld_owe_two_links_one_disabled")
    assert [v.rule_id for v in violations] == ["AO.RECONFIG_DELETE_ACTIVE"]


def test_removing_the_only_usable_link_disassociates():
    # Link 1 is disabled, so removing link 0 leaves the STA no usable link.
    violations = _check([ASSOC, remove(0), REKEY], test="eht_mld_owe_two_links_one_disabled")
    assert [v.rule_id for v in violations] == ["AO.NO_LINKS_LEFT"]


def test_only_the_first_violation_is_reported():
    assert len(_check([REKEY, REKEY, PROBE])) == 1


def test_no_actions_passes():
    assert _check([]) == []

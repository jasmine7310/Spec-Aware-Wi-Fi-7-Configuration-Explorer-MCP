import copy

import pytest

from explorer.scenarios import TEST_CONFIGS
from explorer.validate import P0_ERRORS, parse_candidate

GOOD = {"config": TEST_CONFIGS["eht_mld_owe_two_links"].model_dump(),
        "actions": [{"action": "associate"}, {"action": "link_remove", "link_id": 1, "count": 4}]}


def _messages(mutate):
    data = copy.deepcopy(GOOD)
    mutate(data)
    candidate, findings = parse_candidate(data)
    assert candidate is None
    assert all(f.stage == "P0" and f.outcome == "MALFORMED" for f in findings)
    return [f.message() for f in findings]


def test_good_candidate_parses():
    candidate, findings = parse_candidate(GOOD)
    assert findings == []
    assert candidate.actions[1].link_id == 1


# Bad inputs and the exact message the agent sees.
CASES = {
    "link_id as string": (
        lambda d: d["config"]["ap"]["links"][0].update(link_id="0"),
        "P0.TYPE_ERROR: config.ap.links[0].link_id must be an integer"),
    "beacon_protection as int": (
        lambda d: d["config"]["ap"].update(beacon_protection=1),
        "P0.TYPE_ERROR: config.ap.beacon_protection must be true or false"),
    "missing client": (
        lambda d: d["config"].pop("sta"),
        "P0.MISSING_FIELD: config.sta is required"),
    "raw hostapd option": (
        lambda d: d["config"]["ap"].update(wpa_key_mgmt="SAE"),
        "P0.UNKNOWN_FIELD: config.ap.wpa_key_mgmt is not a known field"),
    "unknown AKM": (
        lambda d: d["config"]["sta"].update(akms=["WEP"]),
        "P0.NOT_ALLOWED: config.sta.akms[0] must be one of 'SAE', 'SAE-EXT-KEY', 'OWE', "
        "'WPA-PSK' or 'WPA-PSK-SHA256'"),
    "link_id out of range": (
        lambda d: d["config"]["ap"]["links"][1].update(link_id=15),
        "P0.OUT_OF_RANGE: config.ap.links[1].link_id must be <= 14"),
    "empty AKM list": (
        lambda d: d["config"]["sta"].update(akms=[]),
        "P0.OUT_OF_RANGE: config.sta.akms needs at least 1 item(s)"),
    "repeated link IDs": (
        lambda d: d["config"]["ap"]["links"][1].update(link_id=0),
        "P0.INVALID_VALUE: config.ap: links[].link_id must not repeat values"),
    "unknown action": (
        lambda d: d["actions"].append({"action": "reboot"}),
        "P0.NOT_ALLOWED: actions[2] unknown action 'reboot'; expected one of 'associate', "
        "'scan', 'rekey_gtk_now', 'link_remove', 'disable_enable_mld', "
        "'sta_disconnect_reconnect', 'ap_disassociate', 'ap_deauthenticate', 'ml_probe_req', "
        "'bss_tm_link_removal_imminent', 'setup_link_reconfig'"),
    "action argument as string": (
        lambda d: d["actions"][1].update(link_id="1"),
        "P0.TYPE_ERROR: actions[1].link_id must be an integer"),
    "zero removal count": (
        lambda d: d["actions"][1].update(count=0),
        "P0.OUT_OF_RANGE: actions[1].count must be >= 1"),
    "action names a link that isn't configured": (
        lambda d: d["actions"][1].update(link_id=4),
        "P0.INVALID_VALUE: actions[1] (link_remove): link_id 4 is not a configured AP link [0, 1]"),
}


@pytest.mark.parametrize("label", CASES)
def test_bad_input_gives_a_readable_message(label):
    mutate, expected = CASES[label]
    assert _messages(mutate) == [expected]


def test_every_problem_is_reported():
    def mutate(d):
        d["config"]["ap"]["links"][0]["link_id"] = "0"
        d["config"]["ap"]["beacon_protection"] = 1
    assert len(_messages(mutate)) == 2


def test_rule_ids_are_documented():
    seen = set()
    for mutate, _ in CASES.values():
        data = copy.deepcopy(GOOD)
        mutate(data)
        seen |= {f.rule_id for f in parse_candidate(data)[1]}
    assert seen == set(P0_ERRORS)


def test_non_object_input():
    candidate, findings = parse_candidate(["not", "a", "candidate"])
    assert candidate is None
    assert [f.rule_id for f in findings] == ["P0.TYPE_ERROR"]

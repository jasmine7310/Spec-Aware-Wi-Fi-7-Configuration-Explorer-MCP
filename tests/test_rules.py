import copy
import csv
import os
import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from explorer.rules import RULES_FILE, RuleRegistry, load_rules

CSV_PATH = Path(__file__).resolve().parent.parent / "surface_candidates.csv"
# e.g. "src/ap/hostapd.c:477" or "tests/hwsim/test_eht.py:1392, 1400-1404"
HOSTAP_REF = re.compile(r"^([\w./-]+):(\d+(?:-\d+)?(?:, \d+(?:-\d+)?)*)$")


def _raw():
    with RULES_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _hostap_citations():
    return [(rule.id, citation.location)
            for rule in load_rules().rules
            for citation in rule.sources if citation.doc == "hostap"]


def test_registry_loads():
    registry = load_rules()
    assert registry.rules


def test_meets_checkpoint_minimum():
    # Roadmap: >=4 rules, >=2 Wi-Fi security/MLO rules, >=1 action-state rule.
    registry = load_rules()
    assert len(registry.rules) >= 4
    security = [r for r in registry.of_kind("normative") if r.id.startswith("SEC.")]
    actions = [r for r in registry.of_kind("harness", "policy") if r.id.startswith("AO.")]
    assert len(security) >= 2
    assert len(actions) >= 1


def test_applies_to_names_are_candidates():
    with CSV_PATH.open(newline="") as f:
        names = {row["name"] for row in csv.DictReader(f)}
    for rule in load_rules().rules:
        assert set(rule.applies_to) <= names, rule.id


def test_get_finds_rules_by_id():
    registry = load_rules()
    assert registry.get("SEC.MLD_COMMON_SUITES").kind == "normative"
    with pytest.raises(KeyError, match="NOPE.RULE"):
        registry.get("NOPE.RULE")


def test_action_order_rules_are_not_spec_rules():
    # action-order.md: refusing an action sequence is never a Wi-Fi spec violation,
    # even when the standard defines the state change behind it (AO.NO_LINKS_LEFT).
    for rule in load_rules().rules:
        if rule.id.startswith("AO."):
            assert rule.kind in {"harness", "policy"}, rule.id
            assert "hostap" in {c.doc for c in rule.sources}, rule.id


@pytest.mark.parametrize("rule_id,location", _hostap_citations(),
                         ids=[f"{rule_id} {location}" for rule_id, location in _hostap_citations()])
def test_hostap_locations_are_well_formed(rule_id, location):
    assert HOSTAP_REF.match(location), f"{rule_id}: {location}"


@pytest.mark.skipif(not os.environ.get("WIFI7_HOSTAP_SRC"),
                    reason="set WIFI7_HOSTAP_SRC to a hostap checkout at the pinned commit")
def test_hostap_locations_exist_in_pinned_hostap():
    root = Path(os.environ["WIFI7_HOSTAP_SRC"])
    cache = {}
    for rule_id, location in _hostap_citations():
        path, refs = HOSTAP_REF.match(location).groups()
        lines = cache.setdefault(path, (root / path).read_text(errors="replace").splitlines())
        for ref in refs.split(", "):
            first, _, last = ref.partition("-")
            first, last = int(first), int(last or first)
            assert 1 <= first <= last <= len(lines), f"{rule_id}: {location}"
            assert lines[first - 1].strip(), f"{rule_id}: {path}:{first} is a blank line"


def _invalid(mutate):
    data = copy.deepcopy(_raw())
    mutate(data)
    with pytest.raises(ValidationError) as excinfo:
        RuleRegistry.model_validate(data)
    return str(excinfo.value)


def test_rejects_repeated_rule_id():
    def mutate(data):
        data["rules"].append(copy.deepcopy(data["rules"][0]))
    assert "unique" in _invalid(mutate)


def test_rejects_unknown_source_doc():
    def mutate(data):
        data["rules"][0]["sources"][0]["doc"] = "IEEE-802.11-1999"
    assert "unknown source" in _invalid(mutate)


def _rule(data, rule_id):
    return next(rule for rule in data["rules"] if rule["id"] == rule_id)


def test_rejects_normative_rule_without_normative_source():
    # A rule backed only by WFA guidance or hostap can't call itself a spec rule.
    def mutate(data):
        rule = data["rules"][0]
        rule["sources"] = [s for s in rule["sources"] if s["doc"] in {"WFA-WPA3", "hostap"}]
    assert "no 'shall'" in _invalid(mutate)


def test_rejects_normative_rule_resting_on_a_note():
    # docs/references.md: NOTEs are informative, not rules. SEC.PMF without its
    # 802.11-2024 §11.52 "shall" has only a NOTE and WFA guidance left.
    def mutate(data):
        rule = _rule(data, "SEC.PMF")
        rule["sources"] = [s for s in rule["sources"] if s["strength"] != "shall"]
        assert {s["strength"] for s in rule["sources"]} == {"note", "guidance"}
    assert "SEC.PMF is normative but cites no 'shall'" in _invalid(mutate)


@pytest.mark.parametrize("doc,strength", [
    ("WFA-WPA3", "shall"), ("hostap", "note"), ("IEEE-802.11be-2024", "code"),
    ("IEEE-802.11be-2024", "guidance"),
])
def test_rejects_strength_that_doesnt_fit_the_source(doc, strength):
    def mutate(data):
        source = next(s for s in _rule(data, "SEC.EHT_SAE_AKM")["sources"] if s["doc"] == doc)
        source["strength"] = strength
    assert "doesn't fit source" in _invalid(mutate)


def test_rejects_wrong_version():
    def mutate(data):
        data["version"] = 2
    assert "version" in _invalid(mutate)


@pytest.mark.parametrize("mutate", [
    lambda data: data["rules"][0].update(kind="recommended"),
    lambda data: data["rules"][0].update(status="verified"),
    lambda data: data["rules"][0].update(id="sec-lowercase"),
    lambda data: data["rules"][0].update(severity="high"),
    lambda data: data["rules"][0]["examples"].update(disallowed=[]),
    lambda data: data["rules"][0].update(applies_to=[]),
    lambda data: data["rules"][0].pop("sources"),
    lambda data: data["sources"]["hostap"].update(normative="no"),
    lambda data: data["rules"][0]["sources"][0].pop("strength"),
    lambda data: data["rules"][0]["sources"][0].update(strength="must"),
], ids=["kind", "status", "id-format", "extra-field", "no-disallowed-example",
        "no-applies-to", "no-sources", "non-bool-normative", "no-strength", "bad-strength"])
def test_rejects_malformed_rule(mutate):
    _invalid(mutate)

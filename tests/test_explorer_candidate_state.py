"""The adapter test's association state and traffic expectations (docker/
test_explorer_candidate.py), imported with hostap's guest modules stubbed out."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ADAPTER_TEST = Path(__file__).resolve().parents[1] / "docker" / "test_explorer_candidate.py"


@pytest.fixture(scope="module")
def harness(monkeypatch_module):
    for name, attrs in {"test_eht": {}, "hwsim": {"HWSimRadio": object},
                        "utils": {"check_owe_capab": None, "check_sae_capab": None},
                        "wpasupplicant": {"WpaSupplicant": object}}.items():
        monkeypatch_module.setitem(sys.modules, name, types.SimpleNamespace(**attrs))
    spec = importlib.util.spec_from_file_location("explorer_candidate_under_test", ADAPTER_TEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def monkeypatch_module():
    with pytest.MonkeyPatch.context() as mp:
        yield mp


def test_the_clients_state_wins_over_the_actions(harness):
    assert harness.observed_state(True, "COMPLETED") == ("associated", True)
    assert harness.observed_state(False, "DISCONNECTED") == ("not associated", False)
    # The AP disconnected it (e.g. reason 15) and it's mid-handshake again: run 1794878187.
    label, associated = harness.observed_state(True, "4WAY_HANDSHAKE")
    assert not associated and label.startswith("not associated: wpa_state=4WAY_HANDSHAKE")
    label, associated = harness.observed_state(False, "COMPLETED")
    assert associated and label.startswith("associated, though")
    assert harness.observed_state(True, None)[1] is False


def test_traffic_expectations(harness):
    # Associated: only links still in use, expecting delivery.
    assert harness.traffic_checks(True, {0: 1, 1: 1}, set(), 0b11) == [(0, True), (1, True)]
    assert harness.traffic_checks(True, {0: 1, 1: 1}, {1}, 0b01) == [(0, True)]
    assert harness.traffic_checks(True, {0: 1, 1: 1}, set(), 0b01) == [(0, True)]
    # Not associated (after an AP-initiated disconnect too): every link, expecting none.
    assert harness.traffic_checks(False, {1: 1, 0: 1}, {1}, 0b01) == [(0, False), (1, False)]

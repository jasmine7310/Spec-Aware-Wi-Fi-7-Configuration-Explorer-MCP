"""Candidate -> hwsim test adapter (issue #79).

``build_plan(candidate)`` turns a ``model.Candidate`` into the hostapd parameters, the
wpa_supplicant connect arguments and the actions that ``docker/test_explorer_candidate.py``
runs inside the guest with hostap's own helpers. ``run_candidate()`` runs it in a fresh
UML guest and classifies the outcome with the roadmap's P3 statuses:

- ``ACCEPTED``: every action was carried out (the test passed).
- ``REJECTED``: hostapd or wpa_supplicant refused a setup step or an action; the run's
  log says which (``EXPLORER-REJECTED ...``).
- ``SETUP_FAIL``: the guest or the test didn't get as far as the candidate (no run
  folder, a missing capability, or an adapter error), so nothing is said about it.
- ``TIMEOUT``: the run took longer than the timeout.

Traffic, link and rekey results are observations in the behavior record, never a
rejection. The plan mirrors hostap's own EHT MLD tests at the pinned commit (43ee60e1):
AP parameters as ``eht_mld_ap_wpa2_params()`` builds them (tests/hwsim/test_eht.py:320-338,
``hostapd.wpa2_params()`` at hostapd.py:841-852), the client's ``connect`` arguments as in
test_eht.py:826-827 / 521-522.

Not supported yet (refused before a guest boots, see ``unsupported()``): actions other
than associate, link_remove, rekey_gtk_now, sta_disconnect_reconnect and
disable_enable_mld (issue #61 added GCMP-256 and disable_enable_mld).
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from explorer.model import PMF_TO_IEEE80211W, SAE_PWE_TO_HOSTAPD, SCHEMA_VERSION, Candidate
from explorer.runner import DEFAULT_IMAGE, DEFAULT_LOG_DIR, DEFAULT_TIMEOUT_S, run_test
from explorer.signatures import BehaviorRecord

ADAPTER_TEST = "explorer_candidate"
ADAPTER_FILE = Path(__file__).resolve().parents[2] / "docker" / "test_explorer_candidate.py"
SSID = "explorer_mld"
PASSPHRASE = "qwertyuiop"          # the passphrase hostap's SAE MLD tests use
CHANNEL_FREQ = {1: 2412, 6: 2437}  # MHz

SUPPORTED_ACTIONS = ("associate", "link_remove", "rekey_gtk_now", "sta_disconnect_reconnect",
                     "disable_enable_mld")
_SAE = {"SAE", "SAE-EXT-KEY"}
_PSK = {"WPA-PSK", "WPA-PSK-SHA256"}

P3Status = Literal["ACCEPTED", "REJECTED", "SETUP_FAIL", "TIMEOUT"]
_REJECTED = re.compile(r"EXPLORER-REJECTED (?P<reason>.+)$", re.MULTILINE)

# The adapter's settle step waits (in guest time) up to PTK interval + 5 s for one PTK
# rekey and 2 x (GTK interval + 5 s) for two GTK rekeys (docker/test_explorer_candidate.py).
# UML's time-travel mode makes guest waits faster than real time, but not free: a 300 s
# GTK interval (610 s of guest waiting) took 194 s of wall time and passed (trial run
# 1794366750, Intel Mac, 2026-11-10). Longer waits are refused until a run shows they
# fit the runner's timeout.
MAX_SETTLE_WAIT_S = 610


def settle_wait_s(candidate: Candidate) -> int:
    """Longest guest time the settle step can wait for interval-driven rekeys."""
    ap = candidate.config.ap
    wait = 0
    if ap.ptk_rekey_interval_s is not None:
        wait += ap.ptk_rekey_interval_s + 5
    if ap.gtk_rekey_interval_s is not None:
        wait += 2 * (ap.gtk_rekey_interval_s + 5)
    return wait


class UnsupportedCandidate(ValueError):
    """The adapter can't express this candidate yet; nothing was run."""


def unsupported(candidate: Candidate) -> list[str]:
    """Why the adapter can't run this candidate yet (empty if it can)."""
    reasons = []
    if (wait := settle_wait_s(candidate)) > MAX_SETTLE_WAIT_S:
        reasons.append(f"rekey intervals need up to {wait} s of waiting for rekeys; the "
                       f"longest shown to fit the run timeout is {MAX_SETTLE_WAIT_S} s "
                       "(e.g. a GTK interval of 300 s)")
    for index, step in enumerate(candidate.actions):
        if step.action not in SUPPORTED_ACTIONS:
            reasons.append(f"actions[{index}] ({step.action}): not supported by the "
                           "adapter yet")
    return reasons


def build_plan(candidate: Candidate) -> dict:
    """The JSON plan the guest-side test runs (see the module docstring)."""
    if reasons := unsupported(candidate):
        raise UnsupportedCandidate("; ".join(reasons))
    ap, sta = candidate.config.ap, candidate.config.sta

    shared = {
        # eht_mld_ap_wpa2_params() / hostapd.wpa2_params()
        "ssid": SSID,
        "wpa": "2",
        "ieee80211w": str(PMF_TO_IEEE80211W[ap.pmf]),
        "ieee80211n": "1",
        "ieee80211ax": "1",
        "ieee80211be": "1",
        "hw_mode": "g",
        "group_mgmt_cipher": "AES-128-CMAC",
        "beacon_prot": "1" if ap.beacon_protection else "0",
    }
    if ap.sae_pwe is not None:
        shared["sae_pwe"] = str(SAE_PWE_TO_HOSTAPD[ap.sae_pwe])
    if ap.ptk_rekey_interval_s is not None:
        shared["wpa_ptk_rekey"] = str(ap.ptk_rekey_interval_s)
    if ap.gtk_rekey_interval_s is not None:
        shared["wpa_group_rekey"] = str(ap.gtk_rekey_interval_s)
    if ap.bss_transition:
        shared["bss_transition"] = "1"

    links = []
    for link in ap.links:
        params = {**shared,
                  "wpa_key_mgmt": " ".join(link.akms),
                  "rsn_pairwise": link.pairwise_cipher,
                  "channel": str(link.channel)}
        if set(link.akms) & (_SAE | _PSK):
            params["wpa_passphrase"] = PASSPHRASE
        if link.indicate_disabled:
            params["mld_indicate_disabled"] = "1"
        links.append({"link_id": link.link_id, "params": params})

    connect = {
        "key_mgmt": " ".join(sta.akms),
        "ieee80211w": "2",  # the MLD tests' client always requires PMF (model docstring)
        "scan_freq": " ".join(str(CHANNEL_FREQ[c]) for c in sorted(l.channel for l in ap.links)),
    }
    if set(sta.akms) & _SAE:
        connect["sae_password"] = PASSPHRASE
    if set(sta.akms) & _PSK:
        connect["psk"] = PASSPHRASE
    if sta.beacon_protection:
        connect["beacon_prot"] = "1"
    if any(link.pairwise_cipher != "CCMP" for link in ap.links):
        # The client's cipher lists aren't modeled. wpa_supplicant's defaults don't include
        # GCMP-256 (wpa_supplicant/config_ssid.h:23-27), so when an AP link uses it the client allows both, as hostap's own MLD
        # test does (test_eht.py:2751-2752); hostapd picks GCMP-256 as the group cipher when
        # it is the only pairwise cipher (src/common/wpa_common.c:3823-3825, called from
        # src/ap/ap_config.c:1727). With CCMP only, the client stays as before.
        connect["pairwise"] = "CCMP GCMP-256"
        connect["group"] = "CCMP GCMP-256"

    return {
        "ssid": SSID,
        "ap_shared": shared,
        "ap_links": links,
        "sta": {"connect": connect,
                "sae_groups": " ".join(map(str, sta.sae_groups)) if sta.sae_groups else ""},
        "needs_sae": bool(set(sta.akms) & _SAE),
        "needs_owe": "OWE" in sta.akms,
        "actions": [step.model_dump(mode="json") for step in candidate.actions],
    }


class CandidateRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: P3Status
    reason: str | None
    """Why the run was REJECTED or a SETUP_FAIL; None when ACCEPTED."""
    run_id: str | None
    run_dir: Path | None
    record: BehaviorRecord | None
    plan: dict


def classify(test_status: str, record: BehaviorRecord | None, log_text: str) -> tuple[P3Status, str | None]:
    """Map a runner result plus the adapter's log markers onto a P3 status."""
    if test_status == "TIMEOUT":
        return "TIMEOUT", None
    if test_status != "COMPLETED" or record is None:
        return "SETUP_FAIL", "no run folder came back"
    if m := _REJECTED.search(log_text):
        return "REJECTED", m["reason"].strip()
    if record.test_result == "PASS" and "EXPLORER-DONE" in log_text:
        return "ACCEPTED", None
    if record.test_result == "SKIP":
        return "SETUP_FAIL", "the test was skipped (a capability is missing in the guest)"
    return "SETUP_FAIL", f"the adapter didn't finish (test result {record.test_result})"


def comparable_signature(record: BehaviorRecord) -> dict:
    """The record's signature without the test name, so runs of different tests (or of
    the adapter) can be compared fact by fact."""
    signature = record.signature()
    signature.pop("test")
    return signature


def compare_signatures(adapter_signature: dict, test_signature: dict) -> dict:
    """Facts that differ between an adapter run and a run of the hostap test it
    reproduces, limited to facts both observed (neither side UNKNOWN). The adapter
    observes uniformly (links, status and traffic after every action), while each
    hostap test observes what it chooses, so a fact one side didn't observe isn't a
    difference. Returns {fact: (adapter value, test value)}."""
    from explorer.signatures import UNKNOWN
    return {fact: (adapter_signature[fact], value)
            for fact, value in test_signature.items()
            if fact in adapter_signature and UNKNOWN not in (value, adapter_signature[fact])
            and adapter_signature[fact] != value}


def run_metadata(candidate: Candidate) -> dict:
    """What a run folder records about the candidate besides the plan: the candidate
    itself, the model's schema version, validate_candidate's verdict (status, rule IDs,
    P2 status) and whether running it is a negative experiment."""
    from explorer.validate import validate_candidate  # validate imports support -> scenarios
    data = candidate.model_dump(mode="json")
    result = validate_candidate(data)
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate": data,
        "validation": {"status": result.status,
                       "rule_ids": [f.rule_id for f in result.findings],
                       "p2": result.p2.status if result.p2 else None},
        "negative_experiment": result.status != "PASSES_MODELED_RULES",
    }


def run_candidate(candidate: Candidate, *,
                  log_dir: Path | str = DEFAULT_LOG_DIR,
                  image: str = DEFAULT_IMAGE,
                  timeout_s: float = DEFAULT_TIMEOUT_S) -> CandidateRun:
    """Run one candidate in a fresh guest. It runs whatever the modeled rules say (the
    MCP tool refuses rule-breaking candidates unless asked), but the run folder's
    ``explorer_plan.json`` and manifest record the verdict and label a rule-breaking run
    as a negative experiment (``run_metadata``)."""
    plan = {**build_plan(candidate), "explorer": run_metadata(candidate)}
    with tempfile.TemporaryDirectory() as tmp:
        plan_file = Path(tmp) / "explorer_plan.json"
        plan_file.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        result = run_test(ADAPTER_TEST, log_dir=log_dir, image=image, timeout_s=timeout_s,
                          plan_file=plan_file)
    log_text = ""
    if result.run_dir is not None and (result.run_dir / f"{ADAPTER_TEST}.log").exists():
        log_text = (result.run_dir / f"{ADAPTER_TEST}.log").read_text(errors="replace")
    status, reason = classify(result.status, result.record, log_text)
    return CandidateRun(status=status, reason=reason,
                        run_id=result.run_dir.name if result.run_dir else None,
                        run_dir=result.run_dir, record=result.record, plan=plan)

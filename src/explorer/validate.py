"""P1 rule checks: each enforces one rule from ``rules.yaml`` on a ``model.Config``.

A check takes an already well-formed (P0) configuration and returns the violations it
finds, each naming the rule ID so the registry can supply the rule's meaning and
sources. An empty list means only that the candidate passes the modeled rules, not
that it complies with 802.11be.

``P1_CHECKS`` maps rule IDs to their checks; ``run_p1_checks`` runs them all.
``check_action_order`` enforces the AO.* rules on a candidate's ordered actions. The
``validate_candidate`` pipeline will build on both.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from explorer.model import Candidate, Config


class Violation(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: Literal["P1"] = "P1"
    rule_id: str
    reason: str
    """What this candidate does wrong, in terms of its own fields."""


def _common_akms(config: Config) -> list[str]:
    """AKMs advertised on every AP MLD link, in the first link's order."""
    links = config.ap.links
    return [akm for akm in links[0].akms if all(akm in link.akms for link in links)]


def check_mld_common_suites(config: Config) -> list[Violation]:
    """SEC.MLD_COMMON_SUITES (802.11be §12.6.2): the AP MLD's links advertise the same
    RSNE apart from the AKM list and MFPR, and at least one common AKM.

    Of the RSNE fields, only the pairwise cipher and the AKM list are per-link in
    ``model.Config``; PMF, beacon protection and SAE PWE are shared by all links by
    construction. The AKM lists may differ, so this compares their intersection,
    never the lists themselves.
    """
    rule_id = "SEC.MLD_COMMON_SUITES"
    links = config.ap.links
    violations = []

    if len({link.pairwise_cipher for link in links}) > 1:
        per_link = ", ".join(f"link {link.link_id} {link.pairwise_cipher}" for link in links)
        violations.append(Violation(
            rule_id=rule_id,
            reason=f"AP MLD links advertise different pairwise ciphers ({per_link})"))

    if not _common_akms(config):
        per_link = ", ".join(f"link {link.link_id} {link.akms}" for link in links)
        violations.append(Violation(
            rule_id=rule_id,
            reason=f"AP MLD links advertise no common AKM ({per_link})"))

    return violations


def check_mld_client_common_akm(config: Config) -> list[Violation]:
    """SEC.MLD_CLIENT_COMMON_AKM (802.11be §12.6.3.1): for an ML association the client
    selects one AKM common to all the AP MLD's links, and declines to associate if it
    allows none of them.

    Not a fault in either configuration: a conforming client simply can't set up the
    ML association this candidate asks for. Skipped when the links share no AKM at
    all, which SEC.MLD_COMMON_SUITES already reports.
    """
    common = _common_akms(config)
    if not common or any(akm in common for akm in config.sta.akms):
        return []
    return [Violation(
        rule_id="SEC.MLD_CLIENT_COMMON_AKM",
        reason=(f"none of the client's AKMs {config.sta.akms} is offered on every AP MLD "
                f"link (common to all links: {common}); a conforming client declines "
                f"the ML association"))]


def check_eht_sae_akm(config: Config) -> list[Violation]:
    """SEC.EHT_SAE_AKM (802.11be §12.12.9): two EHT devices negotiating SAE use AKM 24 or
    25 (hostap ``SAE-EXT-KEY`` / ``FT-SAE-EXT-KEY``), never plain ``SAE`` (AKM 8).

    The client picks among the AKMs it allows that every link offers. If plain SAE is
    among them but SAE-EXT-KEY isn't, SAE can only be negotiated with AKM 8.
    """
    usable = [akm for akm in config.sta.akms if akm in _common_akms(config)]
    if "SAE" not in usable or "SAE-EXT-KEY" in usable:
        return []
    return [Violation(
        rule_id="SEC.EHT_SAE_AKM",
        reason=(f"SAE between these EHT devices could only use AKM 8 (SAE): the client "
                f"and every link share {usable} but not SAE-EXT-KEY (AKM 24)"))]


P1_CHECKS: dict[str, Callable[[Config], list[Violation]]] = {
    "SEC.MLD_COMMON_SUITES": check_mld_common_suites,
    "SEC.MLD_CLIENT_COMMON_AKM": check_mld_client_common_akm,
    "SEC.EHT_SAE_AKM": check_eht_sae_akm,
}


def run_p1_checks(config: Config) -> list[Violation]:
    """Every coded P1 check, in ``P1_CHECKS`` order."""
    return [violation for check in P1_CHECKS.values() for violation in check(config)]


# --- Action order (docs/research/action-order.md, AO.* in rules.yaml) -----------

# Actions that need an associated STA (AO.ASSOC_REQUIRED). DISCONNECT needs it too;
# RECONNECT has its own rule (AO.RECONNECT_AFTER_DISCONNECT).
_NEEDS_ASSOCIATION = {"rekey_gtk_now", "link_remove", "ap_disassociate", "ap_deauthenticate",
                      "bss_tm_link_removal_imminent", "setup_link_reconfig"}

ACTION_ORDER_RULES = ("AO.ASSOC_REQUIRED", "AO.ML_PROBE_STATE", "AO.LINK_MUST_EXIST",
                      "AO.NO_LINKS_LEFT", "AO.RECONFIG_DELETE_ACTIVE", "AO.RECONFIG_ADD_ABSENT",
                      "AO.RECONNECT_AFTER_DISCONNECT", "AO.ENABLE_AFTER_DISABLE")


@dataclass
class _State:
    """What the action sequence has done so far (action-order.md, "State model")."""

    ap_links: set[int]
    """AP MLD links that still exist."""
    disabled_links: set[int]
    """Links the AP MLD advertises as disabled; a STA doesn't use them (802.11be §35.3.7.5.2)."""
    associated: bool = False
    why_not_associated: str = "the STA hasn't associated yet"
    not_associated_rule: str = "AO.ASSOC_REQUIRED"
    """The rule to cite when an action needs an association the STA doesn't have."""
    active_links: set[int] = field(default_factory=set)
    scanned: bool = False
    ap_enabled: bool = True
    disconnected_by_command: bool = False

    def associate(self) -> None:
        self.associated = True
        self.disconnected_by_command = False
        self.active_links = self.ap_links - self.disabled_links

    def leave(self, why: str, rule: str = "AO.ASSOC_REQUIRED") -> None:
        self.associated = False
        self.why_not_associated = why
        self.not_associated_rule = rule
        self.active_links = set()


def check_action_order(candidate: Candidate) -> list[Violation]:
    """Walk the candidate's actions through the action-order state model.

    Returns the first violation (the state after a refused action is undefined, so
    later actions aren't judged), or an empty list. These are harness and policy
    rules: a violation means the sequence doesn't make sense for our experiments,
    never that it breaks the Wi-Fi specification.
    """
    links = candidate.config.ap.links
    state = _State(ap_links={link.link_id for link in links},
                   disabled_links={link.link_id for link in links if link.indicate_disabled})
    for index, step in enumerate(candidate.actions):
        problem = _apply(state, step)
        if problem is not None:
            rule_id, reason = problem
            return [Violation(rule_id=rule_id, reason=f"actions[{index}] ({_label(step)}): {reason}")]
    return []


def _label(step) -> str:
    detail = getattr(step, "command", None) or getattr(step, "operation", None)
    return f"{step.action} {detail}" if detail else step.action


def _apply(state: _State, step) -> tuple[str, str] | None:
    """Check one action against the state, then apply its effect. Returns
    (rule_id, reason) if the action isn't allowed here."""
    name = step.action
    needs_association = name in _NEEDS_ASSOCIATION or (
        name == "sta_disconnect_reconnect" and step.command == "DISCONNECT")
    if needs_association and not state.associated:
        return state.not_associated_rule, f"needs an associated STA, but {state.why_not_associated}"

    if name == "associate":
        state.associate()
    elif name == "scan":
        state.scanned = True
    elif name == "ml_probe_req":
        if not state.scanned:
            return "AO.ML_PROBE_STATE", "the AP MLD hasn't been seen in a scan yet"
        if state.associated:
            return "AO.ML_PROBE_STATE", ("probing while associated isn't admitted (no hostap "
                                         "test does it)")
    elif name == "link_remove":
        if step.link_id not in state.ap_links:
            return "AO.LINK_MUST_EXIST", f"AP link {step.link_id} was already removed"
        state.ap_links.discard(step.link_id)
        state.active_links.discard(step.link_id)
        if not state.active_links:
            # Its last usable setup link is gone: 802.11be §35.3.6.3 (and §35.3.7.5.2
            # when only disabled links remain) disassociate the non-AP MLD.
            state.leave("the last link was removed, which disassociates the STA "
                        "(802.11be §35.3.6.3)", rule="AO.NO_LINKS_LEFT")
    elif name == "setup_link_reconfig":
        if step.operation == "delete":
            if step.link_id not in state.active_links:
                return "AO.RECONFIG_DELETE_ACTIVE", f"link {step.link_id} isn't one of the STA's links"
            state.active_links.discard(step.link_id)
        else:
            if step.link_id not in state.ap_links:
                return "AO.RECONFIG_ADD_ABSENT", f"the AP MLD doesn't have link {step.link_id}"
            if step.link_id in state.active_links:
                return "AO.RECONFIG_ADD_ABSENT", f"the STA already has link {step.link_id}"
            state.active_links.add(step.link_id)
    elif name == "sta_disconnect_reconnect":
        if step.command == "DISCONNECT":
            state.leave("the STA was disconnected with DISCONNECT")
            state.disconnected_by_command = True
        else:
            if not state.disconnected_by_command:
                return ("AO.RECONNECT_AFTER_DISCONNECT",
                        "RECONNECT only has an effect after DISCONNECT")
            if not state.ap_enabled:
                return "AO.ENABLE_AFTER_DISABLE", "RECONNECT comes after ENABLE_MLD"
            state.associate()
    elif name == "disable_enable_mld":
        if step.command == "DISABLE_MLD":
            state.ap_enabled = False
        else:
            if state.ap_enabled:
                return "AO.ENABLE_AFTER_DISABLE", "ENABLE_MLD only follows DISABLE_MLD"
            if state.associated:
                return ("AO.ENABLE_AFTER_DISABLE",
                        "the STA must be disconnected with DISCONNECT before ENABLE_MLD")
            state.ap_enabled = True
    elif name in ("ap_disassociate", "ap_deauthenticate"):
        # Decided 2026-11-03: hostap's automatic reconnection isn't assumed.
        state.leave(f"the AP {'disassociated' if name == 'ap_disassociate' else 'deauthenticated'} "
                    f"the STA (continuing needs an explicit associate)")
    return None

"""P0 format errors, P1 rule checks and the action-order checker.

Every finding names its stage, its outcome and the ID it rests on:

- P0, ``MALFORMED``: the input doesn't fit ``model.Candidate``; IDs are ``P0.*``
  (``P0_ERRORS``), from ``parse_candidate`` / ``format_errors``.
- P1, ``SPEC_RULE_VIOLATION``: a rule in ``rules.yaml`` rejects the candidate.
- P1, ``SPEC_UNDETERMINED``: an open question in ``rules.yaml`` (``UND.*``) the modeled
  rules can't decide. A distinct non-approval, never treated as legal or as a violation.

``P1_CHECKS`` maps rule IDs to their configuration checks and ``run_p1_checks`` runs
them; ``find_undetermined`` asks the configuration questions; ``check_action_order``
walks a candidate's actions. ``p1_status`` sums findings up. No finding means only
that the candidate passes the modeled rules, not that it complies with 802.11be. The
``validate_candidate`` pipeline will build on these.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from explorer.model import Candidate, Config

Outcome = Literal["MALFORMED", "SPEC_RULE_VIOLATION", "SPEC_UNDETERMINED"]


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: Literal["P0", "P1"] = "P1"
    outcome: Outcome = "SPEC_RULE_VIOLATION"
    rule_id: str
    """A P0.* error, a rule ID or an UND.* question ID from rules.yaml."""
    reason: str
    """What this candidate does, in terms of its own fields."""

    def message(self) -> str:
        return f"{self.rule_id}: {self.reason}"


def p1_status(findings: list[Finding]) -> Literal[
        "SPEC_RULE_VIOLATION", "SPEC_UNDETERMINED", "PASSES_MODELED_RULES"]:
    """A violation outweighs an open question; with neither, the candidate passes the
    modeled rules (not full 802.11be compliance)."""
    outcomes = {f.outcome for f in findings}
    if "SPEC_RULE_VIOLATION" in outcomes:
        return "SPEC_RULE_VIOLATION"
    if "SPEC_UNDETERMINED" in outcomes:
        return "SPEC_UNDETERMINED"
    return "PASSES_MODELED_RULES"


# --- P0: readable format errors --------------------------------------------------

P0_ERRORS = {
    "P0.TYPE_ERROR": "a value has the wrong type (e.g. a string where an integer is needed)",
    "P0.MISSING_FIELD": "a required field is missing",
    "P0.UNKNOWN_FIELD": "a field that isn't part of the model, e.g. a raw hostapd option",
    "P0.NOT_ALLOWED": "a value outside the allowed set (e.g. an unknown AKM or action)",
    "P0.OUT_OF_RANGE": "a number or list length outside its bounds",
    "P0.INVALID_VALUE": "a value the model's own checks refuse (e.g. a repeated link ID)",
}

_TYPE_NAMES = {"int": "an integer", "bool": "true or false", "string": "a string",
               "list": "a list", "dict": "an object", "model": "an object",
               "model_attributes": "an object"}


def format_errors(exc: ValidationError) -> list[Finding]:
    """Turn a model ValidationError into P0 findings like
    'P0.TYPE_ERROR: config.ap.links[0].link_id must be an integer'."""
    return [_p0_finding(error) for error in exc.errors(include_url=False)]


def parse_candidate(data: object) -> tuple[Candidate | None, list[Finding]]:
    """Validate raw input (e.g. JSON from the agent) as a Candidate."""
    try:
        return Candidate.model_validate(data), []
    except ValidationError as exc:
        return None, format_errors(exc)


def _p0_finding(error: dict) -> Finding:
    kind, ctx = error["type"], error.get("ctx", {})
    path = _path(error["loc"])
    if kind == "missing":
        rule, text = "P0.MISSING_FIELD", "is required"
    elif kind == "union_tag_not_found":
        rule, text = "P0.MISSING_FIELD", f"needs an {ctx.get('discriminator', 'action')!s} field"
    elif kind == "extra_forbidden":
        rule, text = "P0.UNKNOWN_FIELD", "is not a known field"
    elif kind == "literal_error":
        rule, text = "P0.NOT_ALLOWED", f"must be one of {ctx['expected']}"
    elif kind == "union_tag_invalid":
        rule, text = "P0.NOT_ALLOWED", (f"unknown action {ctx['tag']!r}; expected one of "
                                        f"{ctx['expected_tags']}")
    elif kind in ("greater_than_equal", "greater_than"):
        rule, text = "P0.OUT_OF_RANGE", f"must be >= {ctx.get('ge', ctx.get('gt'))}"
    elif kind in ("less_than_equal", "less_than"):
        rule, text = "P0.OUT_OF_RANGE", f"must be <= {ctx.get('le', ctx.get('lt'))}"
    elif kind == "too_short":
        rule, text = "P0.OUT_OF_RANGE", f"needs at least {ctx['min_length']} item(s)"
    elif kind == "too_long":
        rule, text = "P0.OUT_OF_RANGE", f"allows at most {ctx['max_length']} item(s)"
    elif kind.endswith(("_type", "_parsing")):
        name = kind.rsplit("_", 1)[0]
        rule, text = "P0.TYPE_ERROR", f"must be {_TYPE_NAMES.get(name, name)}"
    else:
        # The model's own checks phrase a full sentence, so separate it from the path.
        rule, text = "P0.INVALID_VALUE", error["msg"].removeprefix("Value error, ")
        path = f"{path}:" if path else path
    return Finding(stage="P0", outcome="MALFORMED", rule_id=rule,
                   reason=f"{path} {text}" if path else text)


def _path(loc: tuple) -> str:
    """('config', 'ap', 'links', 0, 'link_id') -> 'config.ap.links[0].link_id'. The
    action tag Pydantic inserts after an action's index is dropped."""
    out = ""
    previous = None
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        elif isinstance(previous, int) and out.startswith("actions"):
            pass  # discriminator tag, e.g. actions[0].link_remove.link_id
        else:
            out += f".{part}" if out else part
        previous = part
    return out


# --- P1: configuration rules -----------------------------------------------------

_SAE_FAMILY = ("SAE", "SAE-EXT-KEY")


def _common_akms(config: Config) -> list[str]:
    """AKMs advertised on every AP MLD link, in the first link's order."""
    links = config.ap.links
    return [akm for akm in links[0].akms if all(akm in link.akms for link in links)]


def _usable_akms(config: Config) -> list[str]:
    """The client's allowed AKMs that every link offers, in the client's order."""
    common = _common_akms(config)
    return [akm for akm in config.sta.akms if akm in common]


def check_mld_common_suites(config: Config) -> list[Finding]:
    """SEC.MLD_COMMON_SUITES (802.11be §12.6.2): the AP MLD's links advertise the same
    RSNE apart from the AKM list and MFPR, and at least one common AKM.

    Of the RSNE fields, only the pairwise cipher and the AKM list are per-link in
    ``model.Config``; PMF, beacon protection and SAE PWE are shared by all links by
    construction. The AKM lists may differ, so this compares their intersection,
    never the lists themselves.
    """
    rule_id = "SEC.MLD_COMMON_SUITES"
    links = config.ap.links
    findings = []

    if len({link.pairwise_cipher for link in links}) > 1:
        per_link = ", ".join(f"link {link.link_id} {link.pairwise_cipher}" for link in links)
        findings.append(Finding(
            rule_id=rule_id,
            reason=f"AP MLD links advertise different pairwise ciphers ({per_link})"))

    if not _common_akms(config):
        per_link = ", ".join(f"link {link.link_id} {link.akms}" for link in links)
        findings.append(Finding(
            rule_id=rule_id,
            reason=f"AP MLD links advertise no common AKM ({per_link})"))

    return findings


def check_mld_client_common_akm(config: Config) -> list[Finding]:
    """SEC.MLD_CLIENT_COMMON_AKM (802.11be §12.6.3.1): for an ML association the client
    selects one AKM common to all the AP MLD's links, and declines to associate if it
    allows none of them.

    Not a fault in either configuration: a conforming client simply can't set up the
    ML association this candidate asks for. Skipped when the links share no AKM at
    all, which SEC.MLD_COMMON_SUITES already reports.
    """
    common = _common_akms(config)
    if not common or _usable_akms(config):
        return []
    return [Finding(
        rule_id="SEC.MLD_CLIENT_COMMON_AKM",
        reason=(f"none of the client's AKMs {config.sta.akms} is offered on every AP MLD "
                f"link (common to all links: {common}); a conforming client declines "
                f"the ML association"))]


def check_eht_sae_akm(config: Config) -> list[Finding]:
    """SEC.EHT_SAE_AKM (802.11be §12.12.9): two EHT devices negotiating SAE use AKM 24 or
    25 (hostap ``SAE-EXT-KEY`` / ``FT-SAE-EXT-KEY``), never plain ``SAE`` (AKM 8).

    If plain SAE is usable but SAE-EXT-KEY isn't, SAE can only be negotiated with AKM 8.
    """
    usable = _usable_akms(config)
    if "SAE" not in usable or "SAE-EXT-KEY" in usable:
        return []
    return [Finding(
        rule_id="SEC.EHT_SAE_AKM",
        reason=(f"SAE between these EHT devices could only use AKM 8 (SAE): the client "
                f"and every link share {usable} but not SAE-EXT-KEY (AKM 24)"))]


def check_eht_beacon_prot(config: Config) -> list[Finding]:
    """SEC.EHT_BEACON_PROT (802.11be §12.12.9): an EHT AP using RSN has beacon protection
    enabled. Every AKM in ``model.Akm`` is an RSN AKM."""
    if config.ap.beacon_protection:
        return []
    return [Finding(rule_id="SEC.EHT_BEACON_PROT",
                    reason="beacon protection is off on an EHT AP that uses RSN")]


def check_eht_sae_h2e(config: Config) -> list[Finding]:
    """SEC.EHT_SAE_H2E (802.11be §12.12.9): SAE between EHT devices uses hash-to-element.

    Judges the effective method, as hostap applies it at the pinned commit: with
    SAE-EXT-KEY, H2E is used even if sae_pwe is unset (src/ap/wpa_auth_ie.c:553-557,
    src/ap/ieee802_11.c:2006-2009, wpa_supplicant/sme.c:364-366); with plain SAE an
    unset sae_pwe means hunting-and-pecking only (hostapd/hostapd.conf:2292-2294) on
    the 2.4 GHz channels the model allows. A conforming client prefers SAE-EXT-KEY over
    plain SAE (§12.12.9), so plain SAE is the SAE AKM only when SAE-EXT-KEY isn't usable.
    """
    usable = _usable_akms(config)
    if "SAE" not in usable or "SAE-EXT-KEY" in usable or config.ap.sae_pwe is not None:
        return []
    return [Finding(
        rule_id="SEC.EHT_SAE_H2E",
        reason=("plain SAE with sae_pwe unset uses hunting-and-pecking, not hash-to-element; "
                "set sae_pwe to hash_to_element or both"))]


def check_sae_pwe_needs_sae(config: Config) -> list[Finding]:
    """SEC.SAE_PWE_NEEDS_SAE (setting dependency): sae_pwe only has an effect when an AP
    link offers an SAE-family AKM; otherwise the setting is meaningless."""
    if config.ap.sae_pwe is None or any(
            akm in _SAE_FAMILY for link in config.ap.links for akm in link.akms):
        return []
    return [Finding(
        rule_id="SEC.SAE_PWE_NEEDS_SAE",
        reason=(f"sae_pwe={config.ap.sae_pwe} is set but no AP link offers SAE or "
                f"SAE-EXT-KEY, so it has no effect"))]


P1_CHECKS: dict[str, Callable[[Config], list[Finding]]] = {
    "SEC.MLD_COMMON_SUITES": check_mld_common_suites,
    "SEC.MLD_CLIENT_COMMON_AKM": check_mld_client_common_akm,
    "SEC.EHT_SAE_AKM": check_eht_sae_akm,
    "SEC.EHT_BEACON_PROT": check_eht_beacon_prot,
    "SEC.EHT_SAE_H2E": check_eht_sae_h2e,
    "SEC.SAE_PWE_NEEDS_SAE": check_sae_pwe_needs_sae,
}


def run_p1_checks(config: Config) -> list[Finding]:
    """Every coded P1 rule check, in ``P1_CHECKS`` order (violations only)."""
    return [finding for check in P1_CHECKS.values() for finding in check(config)]


# --- P1: open questions (SPEC_UNDETERMINED) --------------------------------------

def _undetermined(question_id: str, reason: str) -> Finding:
    return Finding(outcome="SPEC_UNDETERMINED", rule_id=question_id, reason=reason)


def ask_akm_preference(config: Config) -> list[Finding]:
    """UND.AKM_PREFERENCE: when the client and every link share AKMs from different
    families (SAE-family vs PSK vs OWE), which one is negotiated follows the WPA3
    Specification's preference order (WFA-WPA3 Table 3), which we don't have."""
    families = {_akm_family(akm) for akm in _usable_akms(config)}
    if len(families) < 2:
        return []
    return [_undetermined(
        "UND.AKM_PREFERENCE",
        f"the client and every link share {_usable_akms(config)}; which family is "
        f"negotiated depends on the WPA3 Specification's preference order")]


def _akm_family(akm: str) -> str:
    return "SAE" if akm in _SAE_FAMILY else "PSK" if akm.startswith("WPA-PSK") else akm


CONFIG_QUESTIONS: dict[str, Callable[[Config], list[Finding]]] = {
    "UND.AKM_PREFERENCE": ask_akm_preference,
}


def find_undetermined(config: Config) -> list[Finding]:
    """Every configuration question the modeled rules can't decide."""
    return [finding for ask in CONFIG_QUESTIONS.values() for finding in ask(config)]


# --- P1: action order (docs/research/action-order.md, AO.* in rules.yaml) --------

# Actions that need an associated STA (AO.ASSOC_REQUIRED). DISCONNECT needs it too;
# RECONNECT has its own rule (AO.RECONNECT_AFTER_DISCONNECT).
_NEEDS_ASSOCIATION = {"rekey_gtk_now", "link_remove", "ap_disassociate", "ap_deauthenticate",
                      "bss_tm_link_removal_imminent", "setup_link_reconfig"}

ACTION_ORDER_RULES = ("AO.ASSOC_REQUIRED", "AO.ML_PROBE_STATE", "AO.LINK_MUST_EXIST",
                      "AO.NO_LINKS_LEFT", "AO.RECONFIG_DELETE_ACTIVE", "AO.RECONFIG_ADD_ABSENT",
                      "AO.RECONNECT_AFTER_DISCONNECT", "AO.ENABLE_AFTER_DISABLE")
ACTION_ORDER_QUESTIONS = ("UND.STA_STATE_WHILE_MLD_DISABLED", "UND.ASSOC_WITHOUT_AP_LINKS")


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


def check_action_order(candidate: Candidate) -> list[Finding]:
    """Walk the candidate's actions through the action-order state model.

    Returns the first violation or open question (the state after it is unknown, so
    later actions aren't judged), or an empty list. AO.* rules are harness and policy
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
            reason = f"actions[{index}] ({_label(step)}): {reason}"
            if rule_id.startswith("UND."):
                return [_undetermined(rule_id, reason)]
            return [Finding(rule_id=rule_id, reason=reason)]
    return []


def _label(step) -> str:
    detail = getattr(step, "command", None) or getattr(step, "operation", None)
    return f"{step.action} {detail}" if detail else step.action


def _apply(state: _State, step) -> tuple[str, str] | None:
    """Check one action against the state, then apply its effect. Returns
    (rule or question ID, reason) if the action isn't allowed or can't be judged."""
    name = step.action
    needs_association = name in _NEEDS_ASSOCIATION or (
        name == "sta_disconnect_reconnect" and step.command == "DISCONNECT")
    if needs_association and not state.associated:
        return state.not_associated_rule, f"needs an associated STA, but {state.why_not_associated}"
    if needs_association and not state.ap_enabled and not (
            name == "sta_disconnect_reconnect"):
        return ("UND.STA_STATE_WHILE_MLD_DISABLED",
                "the AP MLD is disabled and the STA wasn't disconnected, so whether it is "
                "still associated is unknown")

    if name == "associate":
        if not state.ap_links:
            return ("UND.ASSOC_WITHOUT_AP_LINKS",
                    "every AP link was removed; our sources don't say what associating "
                    "with an AP MLD that has no affiliated APs does")
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
            if not state.ap_links:
                return ("UND.ASSOC_WITHOUT_AP_LINKS",
                        "every AP link was removed; our sources don't say what reconnecting "
                        "to an AP MLD that has no affiliated APs does")
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

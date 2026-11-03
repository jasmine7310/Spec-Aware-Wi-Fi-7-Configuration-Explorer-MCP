"""P1 rule checks: each enforces one rule from ``rules.yaml`` on a ``model.Config``.

A check takes an already well-formed (P0) configuration and returns the violations it
finds, each naming the rule ID so the registry can supply the rule's meaning and
sources. An empty list means only that the candidate passes the modeled rules, not
that it complies with 802.11be.

``P1_CHECKS`` maps rule IDs to their checks; ``run_p1_checks`` runs them all. The
``validate_candidate`` pipeline will build on it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from explorer.model import Config


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

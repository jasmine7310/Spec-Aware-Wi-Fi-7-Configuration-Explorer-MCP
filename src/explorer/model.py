"""P0 data model for a candidate: its configuration (settings set before association)
and its ordered runtime actions.

Structural validation only: field types, allowed values, required fields, unique
link IDs, and action arguments that name configured links. Whether a combination
makes sense for Wi-Fi (e.g. SAE PWE only with an SAE AKM, the selected AKM offered on
every link, beacon protection needing PMF) or whether an action order is meaningful
(e.g. rekey before association) is a P1 rule and deliberately not checked here.

Fields and allowed values come from ``surface_candidates.csv`` and hostap at the pinned
commit (43ee60e1). Values are limited to those hostap's EHT/MLD tests actually use;
meanings are from ``hostapd/hostapd.conf`` and ``wpa_supplicant/wpa_supplicant.conf``.

Not fields, because the tests don't vary them as settings of their own: client PMF is
required (``ieee80211w=2``). Client beacon protection and SAE PWE aren't modeled either,
but they do differ between tests: the plain-SAE tests set ``beacon_prot=1`` and
``sae_pwe=1``, while the SAE-EXT-KEY, OWE, rekey and link removal tests leave both unset,
so that client doesn't use beacon protection (docs/plan.md, "Main blockers"). SSID and
passphrase are supplied by the harness.

Actions are the runtime operations in ``surface_candidates.csv`` (kind "action"), as
hostap's tests issue them at the pinned commit; each class names its source lines.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

# AKMs (hostapd wpa_key_mgmt / wpa_supplicant key_mgmt) used in test_eht.py.
Akm = Literal["SAE", "SAE-EXT-KEY", "OWE", "WPA-PSK", "WPA-PSK-SHA256"]

# Link IDs 0..14: MAX_NUM_MLD_LINKS is 15 (src/common/defs.h:568).
MAX_LINKS = 15

# 2.4 GHz channels the two-link tests use (link 0 on 1, link 1 on 6).
CHANNELS = {1, 6}

# hostapd ieee80211w: 0 = disabled, 1 = optional, 2 = required (hostapd.conf).
# No MLD test uses 0, so it isn't offered.
Pmf = Literal["optional", "required"]
PMF_TO_IEEE80211W = {"optional": 1, "required": 2}

# hostapd sae_pwe: 1 = hash-to-element only, 2 = both hunting-and-pecking and
# hash-to-element (hostapd.conf). 0 (hunting-and-pecking only) isn't used in the tests.
SaePwe = Literal["hash_to_element", "both"]
SAE_PWE_TO_HOSTAPD = {"hash_to_element": 1, "both": 2}

# SAE groups seen in wpas.set("sae_groups") calls in test_eht.py.
SaeGroup = Literal[19, 20, 21]

_STRICT = ConfigDict(strict=True, extra="forbid", frozen=True)


def _unique(values: list, what: str) -> list:
    if len(values) != len(set(values)):
        raise ValueError(f"{what} must not repeat values")
    return values


class ApLink(BaseModel):
    """One affiliated AP of the AP MLD (one ``eht_mld_enable_ap()`` call)."""

    model_config = _STRICT

    link_id: int = Field(ge=0, le=MAX_LINKS - 1,
                         description="AP MLD link ID (0..14).")
    # A plain int (checked below) rather than Literal[1, 6]: Literal would accept
    # True, since True == 1 in Python; strict int rejects booleans.
    channel: int = Field(
        description="2.4 GHz channel: 1 (2412 MHz) or 6 (2437 MHz), as in the two-link tests.")
    akms: list[Akm] = Field(
        min_length=1,
        description="AKMs this link advertises (hostapd wpa_key_mgmt), in order.")
    pairwise_cipher: Literal["CCMP", "GCMP-256"] = Field(
        default="CCMP", description="hostapd rsn_pairwise.")
    indicate_disabled: bool = Field(
        default=False, description="hostapd mld_indicate_disabled: advertise this link as disabled.")

    @field_validator("channel")
    @classmethod
    def _channel_allowed(cls, channel: int) -> int:
        if channel not in CHANNELS:
            raise ValueError(f"channel must be one of {sorted(CHANNELS)}")
        return channel

    @field_validator("akms")
    @classmethod
    def _akms_unique(cls, akms: list[str]) -> list[str]:
        return _unique(akms, "akms")


class ApConfig(BaseModel):
    """AP MLD configuration. Security settings shared by all links live here;
    per-link AKMs and ciphers live on each ``ApLink``."""

    model_config = _STRICT

    links: list[ApLink] = Field(min_length=1, max_length=MAX_LINKS)
    pmf: Pmf = Field(default="required",
                     description="Management frame protection (hostapd ieee80211w: optional=1, required=2).")
    beacon_protection: bool = Field(default=True, description="hostapd beacon_prot.")
    sae_pwe: SaePwe | None = Field(
        default=None,
        description="hostapd sae_pwe (hash_to_element=1, both=2); None leaves it unset.")
    ptk_rekey_interval_s: int | None = Field(
        default=None, ge=1,
        description="hostapd wpa_ptk_rekey in seconds; None = unset. Tests use 5.")
    gtk_rekey_interval_s: int | None = Field(
        default=None, ge=1,
        description="hostapd wpa_group_rekey in seconds; None = hostapd default. Tests use 5.")
    bss_transition: bool = Field(default=False, description="hostapd bss_transition.")

    @model_validator(mode="after")
    def _link_ids_unique(self) -> ApConfig:
        _unique([link.link_id for link in self.links], "links[].link_id")
        return self


class StaConfig(BaseModel):
    """Non-AP MLD (client) configuration."""

    model_config = _STRICT

    akms: list[Akm] = Field(
        min_length=1,
        description="AKMs the client allows (wpa_supplicant key_mgmt), in order.")
    sae_groups: list[SaeGroup] | None = Field(
        default=None, min_length=1,
        description="wpa_supplicant sae_groups, tried in order; None = default.")

    @field_validator("akms", "sae_groups")
    @classmethod
    def _lists_unique(cls, values: list | None, info) -> list | None:
        return values if values is None else _unique(values, info.field_name)


class Config(BaseModel):
    """A candidate's full configuration: the AP MLD and the client."""

    model_config = _STRICT

    ap: ApConfig
    sta: StaConfig


# --- Runtime actions -----------------------------------------------------------
# Lines are in tests/hwsim/test_eht.py at the pinned commit unless noted.

def _link_id():
    return Field(ge=0, le=MAX_LINKS - 1, description="AP MLD link ID (0..14).")


class Associate(BaseModel):
    """STA connects to the AP MLD on all its advertised links (wpas.connect, e.g. 714)."""

    model_config = _STRICT
    action: Literal["associate"]


class Scan(BaseModel):
    """STA scans for the AP MLD (SCAN freq=..., 387-395); needed before an ML probe."""

    model_config = _STRICT
    action: Literal["scan"]


class RekeyGtkNow(BaseModel):
    """AP sends REKEY_GTK (1406, to link 0's AP in eht_mld_link_removal)."""

    model_config = _STRICT
    action: Literal["rekey_gtk_now"]


class LinkRemove(BaseModel):
    """AP MLD removes one affiliated AP: LINK_REMOVE <count> on that link's AP
    (hostapd.py:296; test_eht.py 1400 with count 4, 1416 with count 20)."""

    model_config = _STRICT
    action: Literal["link_remove"]
    link_id: int = _link_id()
    count: int = Field(ge=1, description="Beacons until removal (LINK_REMOVE <count>). Tests use 4 and 20.")


class DisableEnableMld(BaseModel):
    """AP MLD DISABLE_MLD (728) or ENABLE_MLD (743)."""

    model_config = _STRICT
    action: Literal["disable_enable_mld"]
    command: Literal["DISABLE_MLD", "ENABLE_MLD"]


class StaDisconnectReconnect(BaseModel):
    """STA DISCONNECT (740) or RECONNECT (760)."""

    model_config = _STRICT
    action: Literal["sta_disconnect_reconnect"]
    command: Literal["DISCONNECT", "RECONNECT"]


class ApDisassociate(BaseModel):
    """AP sends DISASSOCIATE <sta addr> (2039, 2045)."""

    model_config = _STRICT
    action: Literal["ap_disassociate"]


class ApDeauthenticate(BaseModel):
    """AP sends DEAUTHENTICATE <sta addr> (2039, 2045)."""

    model_config = _STRICT
    action: Literal["ap_deauthenticate"]


class MlProbeReq(BaseModel):
    """STA sends an ML probe request (ML_PROBE_REQ, 422 / 439 / 446)."""

    model_config = _STRICT
    action: Literal["ml_probe_req"]
    link_id: int = Field(default=-1, ge=-1, le=MAX_LINKS - 1,
                         description="Requested AP link; -1 requests all links (the helper's default).")


class BssTmLinkRemovalImminent(BaseModel):
    """AP sends BSS_TM_REQ with link_removal_imminent=1 (1457-1471)."""

    model_config = _STRICT
    action: Literal["bss_tm_link_removal_imminent"]


class SetupLinkReconfig(BaseModel):
    """STA sends SETUP_LINK_RECONFIG delete=<link> (3024) or add=<link> (3044)."""

    model_config = _STRICT
    action: Literal["setup_link_reconfig"]
    operation: Literal["delete", "add"]
    link_id: int = _link_id()


Action = Annotated[
    Union[Associate, Scan, RekeyGtkNow, LinkRemove, DisableEnableMld, StaDisconnectReconnect,
          ApDisassociate, ApDeauthenticate, MlProbeReq, BssTmLinkRemovalImminent,
          SetupLinkReconfig],
    Field(discriminator="action"),
]


class Candidate(BaseModel):
    """A candidate experiment: a configuration and the ordered actions to run on it."""

    model_config = _STRICT

    config: Config
    actions: list[Action] = []

    @model_validator(mode="after")
    def _actions_name_configured_links(self) -> Candidate:
        configured = {link.link_id for link in self.config.ap.links}
        for index, step in enumerate(self.actions):
            link_id = getattr(step, "link_id", None)
            if link_id is None or link_id == -1:
                continue
            if link_id not in configured:
                raise ValueError(f"actions[{index}] ({step.action}): link_id {link_id} is not "
                                 f"a configured AP link {sorted(configured)}")
        return self

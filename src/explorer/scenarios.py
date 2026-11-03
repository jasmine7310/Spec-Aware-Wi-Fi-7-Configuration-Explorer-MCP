"""The configuration each runnable hostap test sets up, as a ``model.Config``.

Read from ``tests/hwsim/test_eht.py`` at the pinned hostap commit (43ee60e1); line
numbers are given per test. ``eht_mld_ap_wpa2_params()`` defaults to ``mfp="2"``,
``pwe=None`` (sae_pwe unset) and ``beacon_prot="1"``, and every two-link test puts
link 0 on channel 1 and link 1 on channel 6.

These let the P1 checks judge a hostap test before it runs. Runtime actions (rekey,
link removal) aren't part of ``Config`` yet.
"""

from __future__ import annotations

from explorer.model import Config


def _two_links(akms, *, link1=None, **ap):
    return {"links": [{"link_id": 0, "channel": 1, "akms": akms},
                      {"link_id": 1, "channel": 6, "akms": akms, **(link1 or {})}], **ap}


_REKEY_AKMS = ["SAE-EXT-KEY", "SAE", "WPA-PSK", "WPA-PSK-SHA256"]

TEST_CONFIGS: dict[str, Config] = {name: Config.model_validate(raw) for name, raw in {
    # run_eht_mld_sae_two_links: AP key_mgmt SAE, mfp 2, pwe 1 (692-699);
    # STA sae_pwe 1, sae_groups "20 19", key_mgmt SAE (707-714)
    "eht_mld_sae_two_links": {
        "ap": _two_links(["SAE"], sae_pwe="hash_to_element"),
        "sta": {"akms": ["SAE"], "sae_groups": [20, 19]},
    },
    # test_eht_mld_sae_ext_two_links: AP key_mgmt SAE-EXT-KEY (817-824);
    # STA key_mgmt SAE-EXT-KEY (826). The STA's sae_pwe isn't set here, unlike
    # the fixed hash-to-element STA explorer.model assumes.
    "eht_mld_sae_ext_two_links": {
        "ap": _two_links(["SAE-EXT-KEY"]),
        "sta": {"akms": ["SAE-EXT-KEY"]},
    },
    # _eht_mld_owe_two_links: AP key_mgmt OWE, mfp 2 (502); STA key_mgmt OWE (522)
    "eht_mld_owe_two_links": {
        "ap": _two_links(["OWE"]),
        "sta": {"akms": ["OWE"]},
    },
    # Same helper with second_link_disabled: mld_indicate_disabled 1 on link 1 (510)
    "eht_mld_owe_two_links_one_disabled": {
        "ap": _two_links(["OWE"], link1={"indicate_disabled": True}),
        "sta": {"akms": ["OWE"]},
    },
    # test_eht_mld_ptk_rekey: mixed AKM list, mfp 1 (917-919), wpa_ptk_rekey 5 (920);
    # STA key_mgmt SAE-EXT-KEY (928)
    "eht_mld_ptk_rekey": {
        "ap": _two_links(_REKEY_AKMS, pmf="optional", ptk_rekey_interval_s=5),
        "sta": {"akms": ["SAE-EXT-KEY"]},
    },
    # test_eht_mld_gtk_rekey: same, wpa_group_rekey 5 (958-961); STA (969)
    "eht_mld_gtk_rekey": {
        "ap": _two_links(_REKEY_AKMS, pmf="optional", gtk_rekey_interval_s=5),
        "sta": {"akms": ["SAE-EXT-KEY"]},
    },
    # test_eht_mld_link_removal: AP key_mgmt OWE, mfp 2 (1386); STA OWE (1392).
    # The LINK_REMOVE / REKEY_GTK actions aren't modeled.
    "eht_mld_link_removal": {
        "ap": _two_links(["OWE"]),
        "sta": {"akms": ["OWE"]},
    },
}.items()}

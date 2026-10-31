# Action-order rules (research)

Ordering and state prerequisites for the runtime actions in
[`surface_candidates.csv`](../../surface_candidates.csv). These are the rules the
action-order checker will encode.

**These are not IEEE 802.11 / Wi-Fi Alliance rules.** They come from hostap's test
harness and control-interface code at the pinned commit
(`43ee60e13c257d33d25bfb6892b9ee38fb6e88a4`). A violation means "this action sequence
doesn't make sense for our experiments", never "this violates the Wi-Fi specification".

Every source below is a path in the hostap tree at the pinned commit. Each rule says who
enforces it:

- **hostap code**: the control command itself fails (`FAIL`) if the rule is broken.
- **harness**: hostap accepts the command, but the test's expected observation can't
  happen, or the test only ever uses this order. We enforce it so candidates stay
  meaningful.
- **policy**: a modeling choice of ours, derived from the tests; may be revisited.

## State model

The checker tracks, through an ordered action list:

- **STA association**: `disconnected` → (`associate`) → `associated`, with the set of
  **active links** (initially every link the STA associated on).
- **AP links**: the set of AP MLD links that still exist (initially all configured links).
- **AP MLD enabled**: `true` initially; `disable_enable_mld` toggles it.
- **STA disconnected by command**: set by `DISCONNECT`, cleared by `RECONNECT`.

Action names match `surface_candidates.csv`.

## Rules

### AO.ASSOC_REQUIRED: post-association actions need an associated STA

| | |
|---|---|
| **Applies to** | `rekey_gtk_now`, `link_remove`, `ap_disassociate`, `ap_deauthenticate`, `bss_tm_link_removal_imminent`, `setup_link_reconfig`, `sta_disconnect_reconnect` (DISCONNECT) |
| **Rule** | The action is only allowed while the STA is `associated`. |
| **Predicate** | `state.associated` before the action |
| **Enforced by** | Mixed, per action (below) |
| **Allowed** | `[associate, rekey_gtk_now]` |
| **Disallowed** | `[rekey_gtk_now, associate]`; `[link_remove]` |

| Action | Who enforces it | Source |
|---|---|---|
| `bss_tm_link_removal_imminent` | **hostap code**: fails if the STA isn't known to the AP | `src/ap/ctrl_iface_ap.c:1715-1720` (`hostapd_ctrl_iface_bss_tm_req`) |
| `setup_link_reconfig` | **hostap code**: fails with "Not connected" | `wpa_supplicant/ctrl_iface.c:12803-12805` |
| `rekey_gtk_now` | **harness**: `REKEY_GTK` just schedules a rekey and succeeds with no STA (`src/ap/wpa_auth.c:7906-7914`), but the evidence (`MLO RSN: Group rekeying completed` on the STA) needs one | `tests/hwsim/test_eht.py:1392, 1406-1411` |
| `link_remove` | **harness**: `hostapd_link_remove()` only checks the AP is an AP MLD (`src/ap/hostapd.c:477`); the test removes links after `connect` and checks traffic on the remaining link | `tests/hwsim/test_eht.py:1392, 1400-1404` |
| `ap_disassociate`, `ap_deauthenticate` | **harness**: the handlers send the frame through the driver whether or not the STA is known; `if (sta)` only guards the extra cleanup (`src/ap/ctrl_iface_ap.c:688-698` deauth, `753-766` disassoc); the test waits for that STA to disconnect | `tests/hwsim/test_eht.py:2030, 2045-2048` |
| DISCONNECT | **harness**: used only after `connect` | `tests/hwsim/test_eht.py:714, 740`; `1165, 1170` |

### AO.ML_PROBE_STATE: ML probe needs a known AP and an idle or completed STA

| | |
|---|---|
| **Applies to** | `ml_probe_req` |
| **Rule** | The target AP must already be in the STA's scan results, and the STA must not be scanning or part-way through connecting. |
| **Predicate** | AP seen in a prior scan, and `state` is `disconnected` (after a scan) or `associated` |
| **Enforced by** | **hostap code** |
| **Source** | `wpa_supplicant/ctrl_iface.c:12946-12955` (`wpas_ctrl_ml_probe`: fails if the BSS isn't known, if scanning, or if `WPA_SCANNING < wpa_state < WPA_COMPLETED`) |
| **Tested order** | `tests/hwsim/test_eht.py:387-395` (scan), `422`, `439`, `446` (probes); no association in `test_eht_mld_discovery` |
| **Allowed** | `[scan, ml_probe_req]` |
| **Disallowed** | `[ml_probe_req]` with no prior scan |
| **Note** | The code also allows probing while `associated`, but no test does it. Treat `[associate, ml_probe_req]` as permitted by the code but **untested**: it needs a smoke test before it's admitted. |

### AO.LINK_MUST_EXIST: only remove links that still exist

| | |
|---|---|
| **Applies to** | `link_remove` |
| **Rule** | The AP link being removed must not have been removed already. |
| **Predicate** | `link ∈ state.ap_links`; afterwards remove it from `ap_links` and from the STA's active links |
| **Enforced by** | **harness**: `hostapd_link_remove()` doesn't check this (`src/ap/hostapd.c:475-494`) |
| **Source** | `tests/hwsim/test_eht.py:1400` (removes link 1), `1416` (then link 0) |
| **Allowed** | `[associate, link_remove(1), link_remove(0)]` |
| **Disallowed** | `[associate, link_remove(1), link_remove(1)]` |
| **Note** | `LINK_REMOVE <count>` removes the link after `count` beacons (log message at `src/ap/hostapd.c:481`); the test uses 4 and 20. The command only exists in builds with `CONFIG_TESTING_OPTIONS` (`src/ap/hostapd.c:497`). |

### AO.NO_LINKS_LEFT: removing the last link ends useful post-association actions

| | |
|---|---|
| **Applies to** | every `AO.ASSOC_REQUIRED` action after the STA has no active links |
| **Rule** | After the last active link is removed, treat the STA as not associated until it associates again. |
| **Predicate** | if `state.active_links` becomes empty, set `associated = false` |
| **Enforced by** | **policy** |
| **Source** | `tests/hwsim/test_eht.py:1416-1424`: after removing the last link the test expects traffic to fail (`traffic_test(..., success=False)`) |
| **Allowed** | `[associate, link_remove(1), link_remove(0)]` (ends there) |
| **Disallowed** | `[associate, link_remove(1), link_remove(0), rekey_gtk_now]` |
| **Note** | The test checks only that traffic fails; it doesn't check for a disconnect event. Whether the STA is formally disconnected is **undetermined** from the tests. |

### AO.RECONFIG_DELETE_ACTIVE: link reconfig can only delete a current link

| | |
|---|---|
| **Applies to** | `setup_link_reconfig delete=<link>` |
| **Rule** | The link must be one of the STA's current links. |
| **Predicate** | `link ∈ state.active_links`; afterwards remove it |
| **Enforced by** | **hostap code**: "not a valid delete link" |
| **Source** | `wpa_supplicant/ctrl_iface.c:12847-12853`; tested at `tests/hwsim/test_eht.py:3024, 3034` |
| **Allowed** | `[associate, setup_link_reconfig delete=1]` |
| **Disallowed** | `[associate, setup_link_reconfig delete=1, setup_link_reconfig delete=1]` |

### AO.RECONFIG_ADD_ABSENT: link reconfig adds only links the STA doesn't have

| | |
|---|---|
| **Applies to** | `setup_link_reconfig add=<link>` |
| **Rule** | The AP MLD must advertise the link, and the STA must not currently have it. |
| **Predicate** | `link ∈ state.ap_links` and `link ∉ state.active_links`; afterwards add it |
| **Enforced by** | First half **hostap code** ("add link info not present", `wpa_supplicant/ctrl_iface.c:12819-12830`); second half **policy**: wpa_supplicant doesn't check it |
| **Source** | `tests/hwsim/test_eht.py:3024` (delete) then `3044` (add the same link), checked by `CTRL-EVENT-LINK-STA-ADDED` at `3054` |
| **Allowed** | `[associate, setup_link_reconfig delete=1, setup_link_reconfig add=1]` |
| **Disallowed** | `[associate, setup_link_reconfig add=1]` while link 1 is still active |

### AO.RECONNECT_AFTER_DISCONNECT: RECONNECT only after DISCONNECT

| | |
|---|---|
| **Applies to** | `sta_disconnect_reconnect` (RECONNECT) |
| **Rule** | RECONNECT is only meaningful after DISCONNECT. |
| **Predicate** | `state.disconnected_by_command` before RECONNECT; afterwards `associated = true` once the reconnect completes |
| **Enforced by** | **harness**: RECONNECT replies OK but does nothing unless the STA was disconnected with DISCONNECT, so a misplaced RECONNECT silently has no effect |
| **Source** | `wpa_supplicant/ctrl_iface.c:13925-13929`; tested at `tests/hwsim/test_eht.py:740, 760`; `1170, 1181` |
| **Allowed** | `[associate, DISCONNECT, RECONNECT]` |
| **Disallowed** | `[associate, RECONNECT]` |

### AO.ENABLE_AFTER_DISABLE: ENABLE_MLD only after DISABLE_MLD

| | |
|---|---|
| **Applies to** | `disable_enable_mld` |
| **Rule** | `ENABLE_MLD` follows `DISABLE_MLD`. While the AP MLD is disabled, the STA must be disconnected with DISCONNECT before the AP is re-enabled, and reconnected with RECONNECT afterwards. |
| **Predicate** | `not state.ap_enabled` before `ENABLE_MLD` |
| **Enforced by** | **harness** |
| **Source** | `tests/hwsim/test_eht.py:728-748`; comment at `737`: mac80211 doesn't detect the AP going away, so the test forces the disconnect |
| **Allowed** | `[associate, DISABLE_MLD, DISCONNECT, ENABLE_MLD, RECONNECT]` |
| **Disallowed** | `[associate, ENABLE_MLD]`; `[associate, DISABLE_MLD, ENABLE_MLD, rekey_gtk_now]` (STA never disconnected/reconnected) |

## Config prerequisites seen alongside actions

Not ordering rules, but the checker needs them to accept an action:

| Action | Needs config | Source | Enforced by |
|---|---|---|---|
| `bss_tm_link_removal_imminent` | `ap_bss_transition=1` (and `mbo=1` in the test) | `tests/hwsim/test_eht.py:1438-1439` | Harness: set in the only test; not checked in the `BSS_TM_REQ` handler I read |
| `link_remove` | hostapd built with `CONFIG_TESTING_OPTIONS` | `src/ap/hostapd.c:497` | hostap build |

## Open questions

- **ML probe while associated** (AO.ML_PROBE_STATE): allowed by the code, never tested.
  Needs a smoke test before it's admitted.
- **Last link removed** (AO.NO_LINKS_LEFT): the tests don't say whether the STA is
  disconnected or just has no working link.
- **Disassociate / deauthenticate**: the test expects the STA to reconnect on its own
  afterwards (`tests/hwsim/test_eht.py:2050-2056`). Should the model treat
  `[ap_disassociate]` as returning to `associated` after a wait, or require an explicit
  `associate`? A choice for the action data model.

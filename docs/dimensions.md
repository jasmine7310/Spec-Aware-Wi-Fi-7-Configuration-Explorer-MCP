# Admitted dimensions

The executable dimensions of the candidate space (issue #61; roadmap Week 3 asks for ≥8
across security, key and link lifecycles). A dimension is a setting or action with **≥2
admissible values**, each of which passes the coded P1 rules and has a committed passing
run in `runs/smoke/` (listed in `surface_candidates.csv`'s `smoke_runs`). A field with one
workable value (e.g. client PMF, client `sae_pwe`) is a fixed setting, not a dimension.

"Passes modeled rules" is all a value's legality claim means here, never full 802.11be
compliance. Spec citations below are the ones already checked in `rules.yaml`; anything not
yet read in the PDF says so.

Versions for every row: hostap `43ee60e1`, wireless-next `21b4248b` (`baseline/README.md`).

## Summary

| # | Dimension | Area | Values | Smoke evidence |
|---|---|---|---|---|
| 1 | `ap_akm` | security | SAE-EXT-KEY, OWE | ✅ `1793897820`, `1793897854` |
| 2 | `sta_akm` | security | SAE-EXT-KEY, OWE | ✅ `1793897820`, `1793897854` |
| 3 | `ap_ptk_rekey_interval` | key | unset, 5 s | ✅ `1793897820`, `1793897917` |
| 4 | `ap_gtk_rekey_interval` | key | unset, 5 s | ✅ `1793897820`, `1793897930` |
| 5 | `ap_link_indicate_disabled` | link | 0, 1 | ✅ `1793897854`, `1793897892` |
| 6 | `link_remove` | link | absent, present | ✅ `1793897854`, `1793897945` |
| 7 | `ap_sae_pwe` (conditional) | security | unset, 2 (1 REJECTED, see below) | ✅ `1794384666`, `1794384680` |
| 8 | `ap_pairwise_cipher` | security | CCMP, GCMP-256 | ✅ `1794384666`, `1794384688` |
| 9 | `rekey_gtk_now` | key | absent, present | ✅ `1794384666`, `1794384695` |
| 10 | `disable_enable_mld` | link | absent, present | ✅ `1794384666`, `1794384702` |

Rows 7–10 were added for issue #61. They run through the candidate adapter
(`explorer.adapter`, issue #79), since no hostap test sets them up on the legal F02
configuration. Each candidate is F02 (`eht_mld_sae_ext_two_links_client_bp`: SAE-EXT-KEY on
both links, PMF required, beacon protection on at both ends) with one dimension changed,
and the "base" candidate is F02 itself through the adapter, so each value's run differs
from the base run in that dimension only. All six candidates pass the modeled rules
(`scripts/smoke_dimensions.py --check`). They ran on 2026-11-11 (Windows 11 + WSL2 Ubuntu +
Docker Desktop, image `sha256:e61362e4…`, one fresh guest each): five `ACCEPTED`, and
`sae_pwe_h2e` (`ap_sae_pwe=1`) `REJECTED` (`1794384673`, kept in `runs/smoke/` as a labeled
rejection, not a smoke value). So all 10 dimensions are admitted, `ap_sae_pwe` with the values
unset and 2.

Not admitted:

- `ap_mld_link_count`: P0 allows ≤2 links (`model.MAX_TESTED_LINKS`) until hostap's
  `test_eht_mld_owe_N_link` tests are run here.
- `ap_pmf`: `mfp=1` only appears with WPA3-Personal Transition Mode's mixed AKM list (rekey
  tests); as a dimension on its own it needs a decision about Transition Mode first
  (see `runs/smoke/README.md`).
- `ap_beacon_protection`, `sta_beacon_protection`: off breaks `SEC.EHT_BEACON_PROT`, so there
  is one legal value.

## Per-dimension record

Rows 1–6 are recorded in `runs/smoke/README.md` ("What each smoke-tested value rests on");
summarized here so the record is in one place.

### 1–2. `ap_akm`, `sta_akm`

- **Typed values:** `ApLink.akms`, `StaConfig.akms` = `["SAE-EXT-KEY"]` / `["OWE"]`.
- **Spec-rule status:** `SEC.EHT_SAE_AKM` (802.11be §12.12.9, shall) rules out plain SAE
  (AKM 8) between EHT devices; `SEC.MLD_COMMON_SUITES` / `SEC.MLD_CLIENT_COMMON_AKM`
  (§12.6.2, §12.6.3.1) need an AKM common to every link. Which of several usable AKMs is
  negotiated is `UND.AKM_PREFERENCE`.
- **Tested alternatives:** plain SAE runs (`1793690818`) but is a labeled negative experiment.
- **Prerequisites:** SAE / OWE capability in the guest (`check_sae_capab`, `check_owe_capab`).

### 3–4. `ap_ptk_rekey_interval`, `ap_gtk_rekey_interval`

- **Typed values:** `ApConfig.ptk_rekey_interval_s` / `gtk_rekey_interval_s` = `None` / `5`.
- **Spec-rule status:** no modeled rule; 802.11be §12.6.19 only says a new PTKSA *should*
  be set up before the old one expires (not a rule).
- **Tested alternatives:** the hostap rekey tests also change the AKM list and PMF (WFA
  Transition Mode, AP side only); see the caveat in `runs/smoke/README.md`. Through the
  adapter, intervals up to 610 s of rekey waiting are allowed (`adapter.MAX_SETTLE_WAIT_S`).
- **Observed as:** `ptk_rekeys_completed`, `gtk_rekeys_completed` (calibrated,
  `runs/calibration/`).

### 5. `ap_link_indicate_disabled`

- **Typed values:** `ApLink.indicate_disabled` = `False` / `True` (on link 1).
- **Spec-rule status:** matches 802.11be §35.3.7.5.2 for the observed behavior only;
  hostap's `mld_indicate_disabled` is static, not the TTLM procedure.
- **Observed as:** active links `0x1` with valid links `0x3`.

### 6. `link_remove`

- **Typed values/actions:** `LinkRemove(link_id, count)`, absent / present.
- **Spec-rule status:** `AO.LINK_MUST_EXIST`, `AO.NO_LINKS_LEFT` (802.11be §35.3.6.3 for
  the disassociation after the last link); `UND.ASSOC_WITHOUT_AP_LINKS` for associating
  afterwards.
- **Observed as:** `link_reconfig_valid_links` (calibrated on `1793690892`).

### 7. `ap_sae_pwe` (conditional on an SAE AKM)

- **Typed values:** `ApConfig.sae_pwe` = `None` (unset) / `"hash_to_element"` (1) /
  `"both"` (2). hostapd option `sae_pwe`, set by `eht_mld_ap_wpa2_params(pwe=)`
  (test_eht.py:320-338; values used at 334, 665, 692).
- **Condition:** only with an SAE-family AKM: `SEC.SAE_PWE_NEEDS_SAE` flags it otherwise.
  With plain SAE, unset breaks `SEC.EHT_SAE_H2E` (802.11be §12.12.9); with SAE-EXT-KEY all
  three values pass, because hostap uses hash-to-element for SAE-EXT-KEY whatever
  `sae_pwe` says (`src/ap/wpa_auth_ie.c:553-557`, `wpa_supplicant/sme.c:364-366`, cited in
  `rules.yaml`).
- **Runs:** unset (`1794384666`) and 2 (`1794384680`) have identical signatures, H2E in use
  (`sae_h2e=1`) in both. **1 is `REJECTED`** (`1794384673`): the client never associates. Not
  because H2E fails, but at BSS selection: with `sae_pwe=1` and only SAE AKMs, hostapd adds the
  "SAE H2E only" BSS membership selector to its rates (`src/ap/ieee802_11.c:165-170`), and
  wpa_supplicant, whose `sae_pwe` is unset (hunting-and-pecking), skips such a BSS for any SAE
  AKM, SAE-EXT-KEY included (`wpa_supplicant/events.c:1249-1259`, logged as "SAE H2E
  disabled" then "skip - rate sets do not match", 1651-1654). hostap's tests always set the
  client's `sae_pwe=1` when the AP uses `pwe=1` (test_eht.py:672, 707). The model's
  assumption that the client's `sae_pwe` doesn't matter with SAE-EXT-KEY (`model.py`
  docstring) holds for the handshake (`wpa_supplicant/sme.c:364-366`) but not for BSS
  selection. Admitting `ap_sae_pwe=1` needs the client's `sae_pwe` modeled (a P0 change and a
  P1 dependency rule, both to research first); until then it isn't offered as a smoke value.
  This is a configuration mismatch we can explain, not evidence that hostap doesn't support
  the value, so it isn't `UNSUPPORTED_IMPLEMENTATION`.
- **Tested alternatives:** hostap's tests use 1 with plain SAE (`eht_mld_sae_two_links`,
  negative experiment) and with SAE-EXT-KEY on one link of `eht_mld_invalid_link_akm`
  (rule-breaking); 2 with plain SAE (`eht_mld_sae_single_link`) and with
  `SAE SAE-EXT-KEY` (`eht_mld_legacy_stas`, non-MLD clients). None on a legal F02 config.
- **Prerequisites:** SAE AKM on the AP. Client `sae_pwe` stays unset (a fixed setting).
- **Observed as:** `station_status.sae_h2e` (already in the record).
- **Smoke runs:** unset `1794384666`, 2 `1794384680`; rejected 1 `1794384673`.

### 8. `ap_pairwise_cipher`

- **Typed values:** `ApLink.pairwise_cipher` = `"CCMP"` / `"GCMP-256"`, the same on every
  link. hostapd option `rsn_pairwise` (set in test_eht.py:2738-2739, 2794).
- **Spec-rule status:** `SEC.MLD_COMMON_SUITES` (802.11be §12.6.2, shall) requires the same
  pairwise cipher on every link, so a mixed value is a rule violation (hostap's
  `eht_mld_invalid_link_pairwise`). No modeled rule prefers one cipher. **Not yet checked
  in the PDFs:** what the WFA guide's Pairwise Cipher Suite rows (Table 3, Tables 5 / 8)
  say about GCMP-256 for EHT. Read them before calling GCMP-256 more than "passes modeled
  rules".
- **Adapter detail (harness):** wpa_supplicant's default ciphers are CCMP (+TKIP)
  (`wpa_supplicant/config_ssid.h:23-27`), so with GCMP-256 the client is given
  `pairwise="CCMP GCMP-256" group="CCMP GCMP-256"`, as in hostap's own MLD test
  (test_eht.py:2751-2752). With CCMP the client is unchanged. hostapd then picks GCMP-256
  as the group cipher (`src/common/wpa_common.c:3823-3825`, from `src/ap/ap_config.c:1727`);
  the group management cipher stays AES-128-CMAC as `eht_mld_ap_wpa2_params()` sets it.
- **Tested alternatives:** hostap runs GCMP-256 on all links only for non-MLD or
  single-AP EHT tests (`start_eht_sae_ap`, test_eht.py:163-172); on an AP MLD only on one
  link (mismatch test).
- **Observed as:** not in the record yet, so the two runs have identical signatures. The
  GCMP-256 run's logged station status shows `pairwise_cipher` and `group_cipher`
  `GCMP-256` (`mgmt_group_cipher` BIP); the CCMP runs show `CCMP`. Adding these fields to
  `signatures.STATUS_FIELDS` can now be calibrated on `1794384666` / `1794384688`.
- **Smoke runs:** CCMP `1794384666`, GCMP-256 `1794384688`.

### 9. `rekey_gtk_now`

- **Typed values/actions:** `RekeyGtkNow`, absent / present after `associate`. hostapd
  `REKEY_GTK` sent to the first remaining link's AP and waits for
  `MLO RSN: Group rekeying completed` (test_eht.py:1406-1411).
- **Spec-rule status:** `AO.ASSOC_REQUIRED` (harness: the rekey needs an associated STA to
  mean anything). Each affiliated AP has its own GTKSA (802.11be §35.3.5.2, §12.6.19, as
  cited in `runs/smoke/README.md`).
- **Tested alternatives:** hostap only uses it inside `eht_mld_link_removal`, between two
  link removals; here it runs on its own.
- **Observed as:** `gtk_rekeys_completed` (calibrated).
- **Smoke runs:** absent `1794384666`; present `1794384695` (1 GTK rekey, traffic on links 0
  and 1 after it).

### 10. `disable_enable_mld`

- **Typed values/actions:** `DisableEnableMld(command)`, absent / present as hostap's
  sequence `associate, DISABLE_MLD, DISCONNECT, ENABLE_MLD, RECONNECT`
  (test_eht.py:727-760).
- **Spec-rule status:** `AO.ENABLE_AFTER_DISABLE`, `AO.RECONNECT_AFTER_DISCONNECT`
  (harness). Sequencing decision: the STA is disconnected while the AP MLD is disabled,
  as hostap's test does, so `UND.STA_STATE_WHILE_MLD_DISABLED` doesn't arise. Any other
  order that leaves the STA associated across DISABLE_MLD stays `SPEC_UNDETERMINED`.
- **Adapter detail (harness):** before a RECONNECT that follows ENABLE_MLD the adapter
  sends `PMKSA_FLUSH` and `BSS_FLUSH 0`, as hostap's test does (test_eht.py:752-759,
  whose TODO says the reconnection fails without the flush). It logs
  `EXPLORER-HARNESS` when it does. No traffic test while the AP MLD is disabled.
- **Tested alternatives:** hostap's `eht_mld_sae_two_links_disable_enable` uses plain SAE,
  so it's a negative experiment; here it runs on F02.
- **Observed as:** valid/active links, station status and traffic after each step (adapter
  observations); `disconnects`.
- **Smoke runs:** absent `1794384666`; present `1794384702` (a second 4-way handshake and a
  second locally generated disconnect, reason 3; traffic on links 0 and 1 after RECONNECT;
  the log records the harness flush).

## Running the smoke candidates

```bash
.venv/bin/python scripts/smoke_dimensions.py --check   # validate only
.venv/bin/python scripts/smoke_dimensions.py           # 6 fresh guests
```

Runs land in `runs/hwsim-logs/` (trials). An `ACCEPTED` run kept as evidence goes to
`runs/smoke/`, with a line in `runs/smoke/README.md` and its `value=run_id` in the
dimension's `smoke_runs`. A `REJECTED` or `SETUP_FAIL` value isn't admitted; record why here.

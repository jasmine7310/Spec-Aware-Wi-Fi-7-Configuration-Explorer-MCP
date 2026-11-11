# Settings smoke-test runs

Real runs kept as evidence that each value of a candidate setting or action in
[`surface_candidates.csv`](../../surface_candidates.csv) actually executes at the pinned
versions (its `smoke_runs` column points here). Single runs, not reproducibility trials.

A value only counts as smoke-tested if its run's configuration also passes the coded
P1 rules (`tests/test_surface_candidates.py` checks this through
`explorer.scenarios` and `explorer.validate`). Passing them means "passes modeled
rules", not full 802.11be compliance.

All runs: 2026-11-03 (UTC), Windows 11 + WSL2 Ubuntu 24.04 + Docker Desktop (Docker
29.9.2), the `wifi7-env` image built from `docker/Dockerfile` (hostap `43ee60e1`,
wireless-next `21b4248b`), run through `explorer.runner.run_test()`. Full details are in
each `manifest.json`. All seven passed in hostap.

| Run ID | Test | P1 (coded rules) | What the behavior record shows |
|---|---|---|---|
| `1793690818` | `eht_mld_sae_two_links` | **SPEC_RULE_VIOLATION** (`SEC.EHT_SAE_AKM`) | `key_mgmt` SAE; valid/active links `0x3`; traffic on AP links 0 and 1; no PTK/GTK rekeys |
| `1793690831` | `eht_mld_sae_ext_two_links` | passes | `key_mgmt` SAE-EXT-KEY; links `0x3`; traffic on links 0 and 1; no rekeys |
| `1793690841` | `eht_mld_owe_two_links` | passes | `key_mgmt` OWE; links `0x3`; traffic on links 0 and 1 |
| `1793690854` | `eht_mld_ptk_rekey` | passes | 1 PTK rekey (`wpa_ptk_rekey=5`); traffic on links 0 and 1 after it |
| `1793690867` | `eht_mld_gtk_rekey` | passes | 2 GTK rekeys (`wpa_group_rekey=5`); traffic on links 0 and 1 after the last |
| `1793690878` | `eht_mld_owe_two_links_one_disabled` | passes | valid links `0x3`, active links `0x1` (link 1 advertised as disabled); traffic on link 0 only |
| `1793690892` | `eht_mld_link_removal` | passes | link reconfig to valid links `0x1` after link 1's removal; 3 GTK rekeys; traffic on link 0 (the test only sends there), none after the last rekey; a disconnect after the last link's removal |

Run `1793690818` (plain SAE, AKM 8, between EHT devices) breaks 802.11be-2024 §12.12.9,
which requires AKM 24 or 25. hostap runs it anyway; that is P2/P3 evidence, not P1, so
it isn't used as a smoke-tested value.

## What each smoke-tested value rests on

| Setting / action | Values and runs | What the standards say / caveat |
|---|---|---|
| `ap_akm`, `sta_akm` | SAE-EXT-KEY `1793690831`, OWE `1793690841` | Station status confirms the negotiated AKM. SAE-EXT-KEY is AKM 24, the SAE AKM §12.12.9 requires between EHT devices; OWE matches WFA Enhanced Open Only (Table 15) |
| `ap_ptk_rekey_interval` | unset `1793690831`, 5 `1793690854` | No interval rule found in 802.11be (§12.6.19 only says a new PTKSA *should* be set up before the old one expires). The rekey test also differs from the SAE-EXT-KEY test in its AP AKM list (SAE-EXT-KEY, SAE, WPA-PSK, WPA-PSK-SHA256) and PMF (`mfp=1`), which is WFA's WPA3-Personal Transition Mode for an EHT AP (Table 5: PMF Capable MAND, Required DISALLOW). The test's client doesn't fit that mode's EHT STA values: it enables only SAE-EXT-KEY where SAE (`:8`) is also MAND, and uses `ieee80211w=2` where Required is DISALLOW |
| `ap_gtk_rekey_interval` | unset `1793690831`, 5 `1793690867` | Same caveat as PTK rekey. Each affiliated AP has its own GTK and updates it per link (§35.3.5.2, §12.6.19) |
| `ap_link_indicate_disabled` | 0 `1793690841`, 1 `1793690878` | Same OWE helper; only `second_link_disabled` differs. The observation matches §35.3.7.5.2: a STA doesn't send individually addressed frames on a disabled link, and the AP on it doesn't send to the associated MLD's STAs. hostap's `mld_indicate_disabled` is a static setting, not the standard's runtime TTLM disablement procedure, so the claim is limited to that observed behavior |
| `link_remove` | absent `1793690841`, present `1793690892` | The record now shows the removal: `CTRL-EVENT-LINK-RECONFIG valid_links=0x1` after `LINK_REMOVE 4` on link 1 (calibrated on this run). After the last link is removed the STA logs a locally generated disconnect (reason 4) and rescans, before the test ends; §35.3.6.3 says a non-AP MLD whose only setup link is removed is disassociated. The log doesn't say why it disconnected. Of the 3 GTK rekeys, the first follows the test's `REKEY_GTK`; the other two occur after `LINK_REMOVE 20` on the last link, for reasons not yet explained |

## Client beacon protection on (current evidence)

Added 2026-11-05. The runs above leave the client's `beacon_prot` unset, which breaks
`SEC.EHT_BEACON_PROT` (802.11be §12.12.9), so they're kept only as records of hostap's
original tests. `surface_candidates.csv` now points at these runs of our `_client_bp` wrappers
(`docker/test_eht_client_bp.py`), which run the same hostap tests with `beacon_prot="1"` on
the MLD client.

All six: Intel Mac, macOS 15.8.1, Docker 27.4, image `sha256:d2309acc…`, hostap `43ee60e1`.
All passed. Each manifest has `repo_docker_dir_modified: true`, because the wrapper wasn't
committed yet when they ran.

| Run ID | Test | Compared with the run with the client's setting unset |
|---|---|---|
| `1793897820` | `eht_mld_sae_ext_two_links_client_bp` | Adds `bigtk_set=1` to the status; otherwise the same |
| `1793897854` | `eht_mld_owe_two_links_client_bp` | Adds `bigtk_set=1`; otherwise the same |
| `1793897892` | `eht_mld_owe_two_links_one_disabled_client_bp` | Adds `bigtk_set=1`; otherwise the same |
| `1793897917` | `eht_mld_ptk_rekey_client_bp` | Same signature (the test logs no status) |
| `1793897930` | `eht_mld_gtk_rekey_client_bp` | Same signature (the test logs no status) |
| `1793897945` | `eht_mld_link_removal_client_bp` | Adds `bigtk_set=1`; otherwise the same |

The caveats per value above still apply. WFA Table 5's EHT STA values still don't fit the
rekey tests' client, so the Transition Mode fit covers the AP only.

## New dimensions through the candidate adapter (issue #61)

Added 2026-11-11. Each run is one candidate through `explorer.adapter.run_candidate`
(`scripts/smoke_dimensions.py`): the F02 configuration (SAE-EXT-KEY on both links, PMF
required, beacon protection on at both ends) with one dimension changed. The candidate and
its `validate_candidate` verdict are in each run's `explorer_plan.json` and manifest.
Windows 11 + WSL2 Ubuntu + Docker Desktop (Docker 28.0.4), image
`sha256:e61362e4…`, hostap `43ee60e1`. `repo_docker_dir_modified` is true: the adapter
changes weren't committed yet when they ran. Details per dimension: `docs/dimensions.md`.
The `ap_sae_pwe=1` candidate from the same batch was `REJECTED`; its run is in
`runs/rejected/` (not a smoke value).

| Run ID | Candidate | P3 | What the behavior record shows (compared with the base run) |
|---|---|---|---|
| `1794384666` | base (F02 through the adapter) | ACCEPTED | `key_mgmt` SAE-EXT-KEY, `sae_h2e=1`, `bigtk_set=1`; links `0x3`; traffic on links 0 and 1 |
| `1794384680` | `ap_sae_pwe=2` | ACCEPTED | Same signature |
| `1794384688` | `ap_pairwise_cipher=GCMP-256` | ACCEPTED | Same signature; the logged station status shows pairwise and group cipher GCMP-256 (not in the record yet) |
| `1794384695` | `rekey_gtk_now` | ACCEPTED | 1 GTK rekey; traffic on links 0 and 1 after it |
| `1794384702` | `disable_enable_mld` | ACCEPTED | 2 four-way handshakes and 2 locally generated disconnects (reason 3); traffic on links 0 and 1 after RECONNECT |

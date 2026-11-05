# Security rules for Wi-Fi 7 APs and STAs (research draft)

What the IEEE standards and the Wi-Fi Alliance deployment guide say about the security
settings in [`surface_candidates.csv`](../../surface_candidates.csv), as input for the P1
rules "link security match" and "SAE PWE / beacon protection".

Each finding gives the **IEEE** clause (normative: "shall") where one was found, and the
**Wi-Fi Alliance** guidance separately; the roadmap wants IEEE clauses as the normative
source and asks us to say when a rule only comes from WFA guidance. All citations were found
in text extracted from the PDFs, so the wording, clause numbers and pages still need
checking against the documents before anything becomes a rule in `rules.yaml`.

## How to review

The team doesn't need a second teammate's review of the IEEE or WFA citations. Michelle has
checked them in the PDFs. Claude (an AI agent) checked the hostap lines at the pinned commit
on 2026-11-04, and Michelle accepted the result. Each
finding's **Status** row says what is verified and what isn't.

**AI check, 2026-11-02:** Claude (an AI agent) read the text of all three PDFs (the whole
WFA guide; the cited IEEE clauses plus the 802.11be MLO clauses on ML security, AP
removal and link disablement) and checked every IEEE and WFA citation here: section,
page, and "shall" vs NOTE vs MAND/RECOM/DISALLOW. All match, with these corrections and
additions, already applied in `rules.yaml`:

- SEC.MLD_COMMON_SUITES mixes two requirements. §12.6.2 binds the AP MLD's advertised
  RSNE; §12.6.3.1 tells the client to pick a common AKM and to decline to associate if
  none exists, which isn't a configuration fault. `rules.yaml` splits them into
  SEC.MLD_COMMON_SUITES (AP side) and SEC.MLD_CLIENT_COMMON_AKM (client side).
- SEC.SAE_PWE_NEEDS_SAE: the WFA guide does cover it. Table 3 (p. 10) says the SAE
  Hash-to-Element setting applies only if an SAE AKM is used.
- SEC.PMF: Table 5's column order is Required / Capable / Disabled. For an AP with EHT
  enabled in WPA3-Personal Transition Mode, Capable is MAND and Required DISALLOW (p. 14).
- WFA §3.1.4.1 (p. 28) restates §12.6.2 and adds that an AKM advertised on only some
  links can be used only for non-ML associations to that link's BSS.

**Human check of the WFA citations (Michelle, in the PDF, 2026-11-04):**

- Table 8 and its footnotes, SAE Hash-to-Element: match SEC.EHT_SAE_H2E.
- Table 8, AP with EHT enabled: SAE-GDH (`:24`) and SAE (`:8`) are MAND, FT-SAE-GDH and
  FT-SAE RECOM, PSK DISALLOW; PMF Required is MAND, with Capable and Disabled DISALLOW. The
  `:8` footnote says that where all APs and
  STAs are known to support EHT, `:8` can be left out, matching SEC.EHT_SAE_AKM. The same
  footnote also relaxes the cipher suites and allows H2E Only. Table 8's AP SAE
  Hash-to-Element row doesn't carry that footnote marker; its STA row does. Another footnote
  says SAE-GDH needs H2E.
- Table 4: beacon protection Enabled is MAND and Disabled DISALLOW, for an AP with EHT
  enabled and for an EHT STA. This matches SEC.EHT_BEACON_PROT.
- Table 15, AP with EHT enabled: PMF Required is MAND, with Capable and Disabled DISALLOW.
- Table 5, AP with EHT enabled: PMF Capable is MAND, with Required and Disabled DISALLOW;
  SAE-GDH (`:24`), SAE (`:8`) and PSK (`:2`) are MAND; PSK-SHA256 (`:6`) is RECOM; SAE Hash-to-Element Enabled is MAND, with H2E Only and Disabled DISALLOW. These
  rows fit the AP settings of `eht_mld_ptk_rekey` and `eht_mld_gtk_rekey` (`mfp=1`,
  `WPA-PSK`, `WPA-PSK-SHA256`, `sae_pwe` unset), so those AP settings fit Transition Mode.
- Table 5, EHT STA: SAE-GDH (`:24`) and SAE (`:8`) are MAND; PMF Required is DISALLOW; SAE
  Hash-to-Element Enabled is MAND and H2E Only DISALLOW. The client in those two tests doesn't
  fit: it enables only `SAE-EXT-KEY` and uses `ieee80211w=2`. So the Transition Mode fit
  covers the AP only. This is WFA guidance, so it isn't an IEEE violation and no P1 rule
  checks it.
- §2.1.1 and Table 3, AKM Suite and Pairwise Cipher Suite rows (STA Network Profile): match
  SEC.MLD_CLIENT_COMMON_AKM. The AKM Suite row also matches UND.AKM_PREFERENCE. The Pairwise
  Cipher Suite row says "an AP associates with an AP MLD"; from the context it means a STA.
- Table 3 note (p. 9): an AP MLD always enables PMF. This matches SEC.PMF.
- Table 3, SAE Hash-to-Element row, AP BSS Configuration and STA Network Profile columns
  (p. 10): applies only if an SAE AKM is used. This matches SEC.SAE_PWE_NEEDS_SAE.
- §3.1.4.1 NOTE: matches SEC.MLD_COMMON_SUITES (links share RSNE and RSNXE apart from the AKM
  Suite List and MFPR; AKMs on only some links are for non-ML associations to that BSS).
- §3.2: EHT or MLO associations using a password need WPA3 enabled, as `docs/references.md`
  says.

An AI check doesn't replace a person's. To check the rest (see "Reviewing research" in
[`docs/plan.md`](../plan.md)):

> Read `docs/research/security-guidance.md`. For each IEEE citation, open the clause in
> IEEE Std 802.11be-2024 or 802.11-2024 and check that (1) the text says what the finding
> claims, (2) it is normative ("shall") and not a NOTE, and (3) the clause number and page
> are right. For each Wi-Fi Alliance citation, open the table and page in the "WPA3 and Wi-Fi
> Enhanced Open Deployment and Implementation Guide" v1.1 and check the value, its MAND /
> RECOM / DISALLOW column, the device row and any footnote. For each hostap claim, open the
> cited line at commit `43ee60e13c257d33d25bfb6892b9ee38fb6e88a4`. Report any mismatch with
> the page or line you looked at.

Once checked, mark each finding **verified** with who checked it and when, and replace
"Not reviewed yet".

## Sources

Full entries, links and how to get a copy are in [`docs/references.md`](../references.md).

- **IEEE-802.11be-2024**: IEEE Std 802.11be-2024, "Amendment 2: Enhancements for Extremely
  High Throughput (EHT)" (per its page header). Normative.
- **IEEE-802.11-2024**: IEEE Std 802.11-2024, the base standard. Normative.
- **WFA-WPA3**: Wi-Fi Alliance, *WPA3™ and Wi-Fi Enhanced Open™ Deployment and
  Implementation Guide*, v1.1, February 2025 (39 pages). Guidance; its page numbers below
  are the guide's printed page numbers.
- **hostap** at the pinned commit, for what each value means in hostap's own terms.

The IEEE PDFs and the WFA guide are licensed to individual teammates: don't commit them or
paste long passages. IEEE pages are given as "PDF p. N (printed p. M)" because the printed
page number in the header is one less than the PDF page.

The guide marks each value per device type, and Wi-Fi 7 means the EHT rows:
**MAND** (mandatory), **RECOM** (recommended, not required) and **DISALLOW**
(§2.1.3, pp. 11–12). Its reference list gives 802.11be as Amendment 8, August 2024 (p. 5).

## Findings

### SEC.MLD_COMMON_SUITES: AP MLD links share one RSNE, and the client picks suites common to all of them

| | |
|---|---|
| **IEEE (AP side)** | IEEE-802.11be-2024 §12.6.2 "RSNA selection", PDF p. 411 (printed p. 410): all APs affiliated with an AP MLD **shall** advertise the same RSNE (and RSNXE, if included) except for the AKM Suite List field and the MFPR subfield, and **shall** advertise at least one common AKM suite selector. NOTE 3 in 802.11be §11.52 (PDF p. 384, printed p. 383) repeats this and points back to §12.6.2. |
| **IEEE (client side)** | §12.6.3.1 "General", PDF p. 412 (printed p. 411): for MLO, the non-AP MLD's single RSNE **shall** contain one AKM, one pairwise cipher and one group cipher suite selector that are common among those advertised by the APs affiliated with the targeted AP MLD. §12.6.3.2 (same page): the AP MLD compares MFPC / MFPR **per requested link** (Table 12-5) to decide which links it accepts. |
| **WFA** | WFA-WPA3 §2.1.1 (p. 7) says the security parameters a client selects apply to all links of the association with the AP MLD. Table 3 (pp. 8–9) says it picks an AKM and pairwise cipher enabled by all affiliated links, or doesn't associate. |
| **Strength** | IEEE "shall" (normative) |
| **Rule candidate** | Across the links of one AP MLD: identical pairwise and group cipher suites (and the rest of the RSNE except the AKM list and MFPR), and a non-empty intersection of AKM lists. The client's AKM and pairwise cipher must be in every link's list. |
| **Candidates** | `ap_akm`, `sta_akm`, `link_akm_mismatch`, `ap_pairwise_cipher` |
| **hostap evidence** | `eht_mld_invalid_link_pairwise` changes the pairwise cipher on link 0 only, and the `invalid_link_akm` / `no_common_key_mgmt` variants give links AKM lists with no common entry (`link_akm_mismatch` row of `surface_candidates.csv`). These AP configurations break §12.6.2, which fits their role as hostap's deliberate failure tests: candidate **P1 rejection examples**. |
| **Resolved question** | The earlier question (does "all affiliated links" mean all links, or only those set up?) is answered by §12.6.3.1: suites must be common among the APs affiliated with the AP MLD. hostap's associate-on-the-matching-link behavior only happens on AP MLDs that already break §12.6.2. Per-link differences are allowed only in the AKM list and MFPR, and §12.6.3.2 lets the AP MLD accept a subset of links based on MFPC / MFPR. |
| **Status** | IEEE §12.6.2, §12.6.3.1 (including that NOTE 2 is a NOTE), §12.6.3.2 and the §11.52 NOTE 3 verified by Michelle in the PDF (2026-10-31); WFA row verified by Michelle in the PDF (2026-11-04) |

### SEC.EHT_BEACON_PROT: beacon protection is mandatory for EHT with RSN

| | |
|---|---|
| **IEEE** | IEEE-802.11be-2024 §12.12.9 "Security constraints for EHT", PDF p. 446 (printed p. 445): an EHT non-AP STA and an EHT AP **shall** have `dot11BeaconProtectionEnabled` set when using RSN. §9.4.2.25 "Extended Capabilities element", Table 9-192 "Extended Capabilities field", bit 84 "Beacon Protection Enabled" (PDF p. 209, printed p. 208; table checked by Michelle in the PDF) says all APs affiliated with an AP MLD set `dot11BeaconProtectionEnabled` to the same value. The clause 4 overview of EHT features (PDF p. 67, printed p. 66) lists mandatory beacon protection support in an EHT AP. |
| **WFA** | WFA-WPA3 Table 4 (p. 12): for an AP with EHT enabled and for an EHT STA, beacon protection Enabled is MAND and Disabled is DISALLOW, in every WPA3 and Enhanced Open mode. |
| **Strength** | IEEE "shall" (normative); WFA agrees |
| **Candidates** | `ap_beacon_protection` (`1` / `0`), `sta_beacon_protection` |
| **hostap evidence** | `test_eht_mld_sae_two_links` and `test_eht_mld_sae_two_links_no_beacon_prot` run the same function and differ only in `beacon_prot` (`tests/hwsim/test_eht.py:767-773`; passed to the AP at line 694) |
| **Effect** | `ap_beacon_protection = 0` on our Wi-Fi 7 AP breaks a normative rule, so beacon protection has one admissible value: a fixed setting, not a dimension. `eht_mld_sae_two_links_no_beacon_prot` is a clean P1 rejection example (one setting changed). |
| **Status** | IEEE §12.12.9 and Table 9-192 verified by Michelle in the PDF (2026-10-31); WFA Table 4 verified by Michelle in the PDF (2026-11-04) |

### SEC.PMF: PMF must be on for EHT with RSN; the WFA "only" modes require it

| | |
|---|---|
| **IEEE** | IEEE-802.11-2024 §11.52 "Beacon protection procedures", PDF p. 2931 (printed p. 2930; sentence and page checked by Michelle in the PDF): if `dot11RSNAProtectedManagementFramesActivated` is false, `dot11BeaconProtectionEnabled` **shall** be false. Combined with SEC.EHT_BEACON_PROT, an EHT AP using RSN must have PMF activated; a NOTE in 802.11be §12.12.9 (PDF p. 446, printed p. 445) says exactly this. NOTE 1 in 802.11be §12.6.3.1 (PDF p. 412) also says MFP is mandatory for EHT STAs using RSNA, but NOTEs are informative. |
| **WFA** | WFA-WPA3 Table 8 "WPA3-Personal Only Mode" (p. 18) and Table 15 "Wi-Fi Enhanced Open Only Mode" (p. 25): PMF Required is MAND, Capable / Disabled DISALLOW. Transition mode has different values (Table 5, pp. 13–14). A note in Table 3 (p. 9) says an AP MLD always enables PMF. |
| **Strength** | IEEE: PMF activated ("capable" at least) follows from two "shall" rules. WFA: Required (`mfp=2`) in the "only" modes. |
| **Candidates** | `ap_pmf` (`2` / `1`), `sta_pmf` |
| **Effect** | `ap_pmf = 0` is out under IEEE. `1` vs `2` is a WFA mode question, not an IEEE one: `ap_pmf = 1` appears in hostap's rekey tests with a mixed SAE + PSK AKM list, which fits transition mode on the AP side; the client doesn't fit that mode's EHT STA values (Table 5). Per §12.6.2 MFPR may differ between links of one AP MLD. |
| **Status** | IEEE 802.11-2024 §11.52 sentence, and the 802.11be §12.12.9 NOTE and §12.6.3.1 NOTE 1 (both labeled NOTE), verified by Michelle in the PDFs (2026-10-31); WFA Tables 5, 8 and 15 (AP with EHT enabled) and the Table 3 note verified by Michelle in the PDF (2026-11-04) |

### SEC.EHT_SAE_AKM: SAE between EHT devices uses AKM 24 or 25

| | |
|---|---|
| **IEEE** | IEEE-802.11be-2024 §12.12.9 "Security constraints for EHT", PDF p. 446 (printed p. 445): an EHT STA **shall** use AKM suite selector `00-0F-AC:24` or `00-0F-AC:25` when negotiating SAE authentication with another EHT STA. |
| **WFA** | WFA-WPA3 Table 8 (p. 18) and footnotes (pp. 18–19): for an AP with EHT enabled in WPA3-Personal Only, SAE-GDH (`:24`) and SAE (`:8`) are both MAND, PSK DISALLOW; FT-SAE-GDH and FT-SAE RECOM; SAE (`:8`) can be left out where every device is known to support EHT. A footnote says SAE-GDH needs SAE Hash-to-Element. (The AP keeps `:8` for non-EHT clients; that doesn't conflict with the IEEE rule, which is about two EHT STAs.) |
| **Strength** | IEEE "shall" (normative) |
| **hostap mapping** | `00-0F-AC:24` is `RSN_AUTH_KEY_MGMT_SAE_EXT_KEY` and `00-0F-AC:25` is `RSN_AUTH_KEY_MGMT_FT_SAE_EXT_KEY` (`src/common/wpa_common.h:104-105`), i.e. hostap's `SAE-EXT-KEY` and `FT-SAE-EXT-KEY` |
| **Candidates** | `ap_akm` (`SAE` / `SAE-EXT-KEY` / `OWE`), `sta_akm` |
| **Effect on our baseline** | `eht_mld_sae_two_links`, our official baseline, configures both the AP (`tests/hwsim/test_eht.py:693`) and the client (`test_eht.py:715`) with `key_mgmt="SAE"`, i.e. AKM 8 between two EHT devices. If this rule is encoded, the baseline configuration is a SPEC_RULE_VIOLATION under our modeled rules, while the `sae_ext` tests comply. **Decided 2026-11-03** (`docs/plan.md`, "Baseline"): `runs/baseline/` stays the environment baseline, labeled a negative experiment, and anchor F02 (`eht_mld_sae_ext_two_links`) is the legal baseline; hostap running it is P2/P3 evidence, not P1 evidence. |
| **Status** | IEEE §12.12.9 verified by Michelle in the PDF (2026-10-31); WFA row (Table 8 AP row and footnotes) verified by Michelle in the PDF (2026-11-04) |

### SEC.EHT_SAE_H2E: SAE between EHT devices uses Hash-to-Element

| | |
|---|---|
| **IEEE** | IEEE-802.11be-2024 §12.12.9 "Security constraints for EHT", PDF p. 446 (printed p. 445): when an EHT STA performs SAE with a peer EHT STA, it **shall** set the SAE Hash-to-element field in the RSNXE and use the hash-to-element method. |
| **WFA** | WFA-WPA3 Table 8 (p. 18) and footnotes (pp. 18–19). Columns are "H2E Only", "Enabled" and "Disabled". As extracted, for an AP with EHT enabled: H2E Only is MAND in 6 GHz or sub-1 GHz, Enabled is MAND in other bands, Disabled is DISALLOW. For an EHT STA: Enabled MAND, H2E Only DISALLOW, with a footnote allowing H2E Only where all APs and STAs are known to support EHT. This table is the one most likely to be misread from the extracted text: check its columns first. |
| **Strength** | IEEE "shall" (normative); WFA adds band-dependent detail |
| **hostap mapping** | `sae_pwe`: `0` = hunting-and-pecking only, `1` = H2E only, `2` = both (`hostapd/hostapd.conf:2292-2294`); `0` is the default without a password identifier. hostap overrides an unset / `0` value in some cases: **(a)** on 6 GHz the AP switches SAE to both (`src/ap/ap_config.c:1269-1274`); **(b)** with `SAE-EXT-KEY` / `FT-SAE-EXT-KEY` the AP still advertises H2E in the RSNXE (`src/ap/wpa_auth_ie.c:553-557`, `src/ap/ieee802_11_shared.c:1130-1136`) and accepts H2E (`src/ap/ieee802_11.c:2006-2009`), and the client uses H2E and advertises it (`wpa_supplicant/sme.c:364-366`, `1278-1281`). Neither applies to plain `SAE` on 2.4 / 5 GHz. |
| **Candidates** | `ap_sae_pwe` (`1` / `2` / unset), `sta_sae_pwe` |
| **Effect** | `sae_pwe = 0` breaks the IEEE rule, and so does "unset" with plain `SAE` on 2.4 / 5 GHz, because that means hunting-and-pecking. "Unset" with `SAE-EXT-KEY` (e.g. `eht_mld_sae_ext_one_link`) still uses H2E, so it looks admissible. `1` and `2` both advertise and use H2E between EHT devices, so both look admissible under IEEE (WFA marks Enabled, i.e. `2`, as mandatory for an EHT AP outside 6 GHz and sub-1 GHz). The model should judge the effective H2E use, not the raw `sae_pwe` value. |
| **Status** | IEEE §12.12.9 verified by Michelle in the PDF (2026-10-31); WFA Tables 5 and 8 and footnotes verified by Michelle in the PDF (2026-11-04); hostap lines checked by Claude, accepted by Michelle (2026-11-04) |

### SEC.SAE_PWE_NEEDS_SAE: `sae_pwe` only means something with an SAE AKM

| | |
|---|---|
| **Kind** | **Setting dependency**, not a normative prohibition: nothing forbids setting it with another AKM, it just has no effect |
| **IEEE** | IEEE-802.11-2024 §12.4.4.2.3 "Hash-to-element generation of the password element with ECC groups", PDF p. 2967 (printed p. 2966), and the FFC counterpart §12.4.4.3.3 "Direct generation of the password element with FFC groups", starting printed p. 2969: hash-to-element is defined as one of SAE's two ways to derive the password element, under the SAE clause §12.4.4. §9.4.2.240 "RSNXE", Table 9-373 "Extended RSN Capabilities field", bit 5 "SAE Hash-to-element", PDF p. 1433 (printed p. 1432): a NOTE says the receiver ignores this field when SAE isn't negotiated (informative). |
| **WFA** | WFA-WPA3 Table 3, SAE Hash-to-Element row (p. 10): the setting applies only if an SAE AKM is used |
| **hostap evidence** | `hostapd/config_file.c:4675-4676` reads `sae_pwe` as a number with no check against the AKM, so OWE + `sae_pwe=1` is accepted. Without an SAE AKM it then has no effect: no H2E setup (`src/ap/ap_config.c:512-518`, "PT not needed" at line 517) and no H2E bit in the RSNXE (`src/ap/wpa_auth_ie.c:553`, `src/ap/ieee802_11_shared.c:1130`). hostap's tests only set `sae_pwe` with SAE-family AKMs (`ap_sae_pwe` row of `surface_candidates.csv`). |
| **Rule candidate** | `ap_sae_pwe` / `sta_sae_pwe` apply only when the AKM includes `SAE` or `SAE-EXT-KEY`. A P1 dependency rule (`docs/plan.md`: "Code rules: setting dependencies"), not a spec violation. |
| **Candidates** | `ap_sae_pwe`, `sta_sae_pwe`, `ap_akm` |
| **Effect** | A candidate like OWE + `sae_pwe=1` would run in P2/P3, because hostap ignores the setting, but varying `sae_pwe` under OWE is a meaningless difference. `sae_pwe` only counts as a dimension under an SAE-family AKM. |
| **Status** | IEEE Table 9-373 NOTE and §12.4.4.2.3 verified by Michelle in the PDF (2026-10-31), and §12.4.4.3.3 (2026-11-05); WFA Table 3 row verified by Michelle in the PDF (2026-11-04); hostap lines checked by Claude, accepted by Michelle (2026-11-04) |

## What this changes for the smoke test

If the findings above hold:

- **Beacon protection**: not a dimension (one admissible value on an EHT AP). Its `0` test
  is a clean P1 rejection example.
- **PMF**: `0` is out under IEEE; `1` vs `2` depends on the WFA security mode, so it isn't a
  free dimension either.
- **AKM**: between EHT devices, SAE means AKM 24 or 25, so plain `SAE` (`:8`) is out. The
  admissible choices are narrower than hostap's test values, and this affects our baseline
  (see SEC.EHT_SAE_AKM).
- **SAE H2E**: `1` and `2` look admissible, `0` doesn't, and "unset" depends on the AKM
  (H2E is still used with `SAE-EXT-KEY`, not with plain `SAE` on 2.4 / 5 GHz). It's only
  a dimension under an SAE-family AKM (SEC.SAE_PWE_NEEDS_SAE).
- **Link AKM / cipher match**: the main P1 rule candidate (SEC.MLD_COMMON_SUITES), with
  hostap's `invalid_link*` tests as rejection examples.

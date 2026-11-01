# Security guidance for Wi-Fi 7 APs and STAs (research draft)

What the Wi-Fi Alliance deployment guide says about the security settings in
[`surface_candidates.csv`](../../surface_candidates.csv), as input for the P1 rules
"link security match" and "SAE PWE / beacon protection".

**This is Wi-Fi Alliance guidance, not IEEE 802.11 text.** The guide says its mandatory and
disallowed values come from the WPA3 and Wi-Fi Enhanced Open specifications (p. 12), but the
roadmap wants IEEE clauses as the normative source where they exist. Each finding below
still needs (1) checking against the PDF, because the tables were read from extracted text
and columns can be misaligned, and (2) a matching IEEE 802.11be-2024 / 802.11-2024 clause
before it becomes a rule in `rules.yaml`.

## How to review

Not reviewed yet. Every finding is **unverified**. A teammate with a copy of the guide
should check each one (see "Reviewing research" in [`docs/plan.md`](../plan.md)):

> Read `docs/research/security-guidance.md`. For each finding, open the cited table and page
> in the Wi-Fi Alliance "WPA3 and Wi-Fi Enhanced Open Deployment and Implementation Guide"
> v1.1 and check that (1) the value and its MAND / RECOM / DISALLOW marking are in the
> column the finding says, (2) the device row (AP with EHT enabled, or EHT STA) is right,
> and (3) any condition or footnote is reflected. For each hostap claim, open the cited line
> at commit `43ee60e13c257d33d25bfb6892b9ee38fb6e88a4`. Report any mismatch with the page
> or line you looked at.

Once checked, mark each finding **verified** with who checked it and when, and replace
"Not reviewed yet".

## Sources

- **WFA-WPA3**: Wi-Fi Alliance, *WPA3™ and Wi-Fi Enhanced Open™ Deployment and
  Implementation Guide*, v1.1, February 2025 (39 pages). Licensed document: don't commit it.
  Page numbers below are the guide's printed page numbers.
- **hostap** at the pinned commit, for what each value means in hostap's own terms.

The guide marks each value per device type, and Wi-Fi 7 means the EHT rows:
**MAND** (mandatory), **RECOM** (recommended, not required) and **DISALLOW**
(§2.1.3, pp. 11–12). Its reference list gives 802.11be as Amendment 8, August 2024 (p. 5).

## Findings

### WFA.MLD_COMMON_SUITES: the client's AKM and ciphers must work on every AP MLD link

| | |
|---|---|
| **Source** | WFA-WPA3 §2.1.1 (p. 7); Table 3 "Security configuration parameters" (pp. 8–9) |
| **Says** | Each AP link has its own BSS configuration, but some security parameters apply at the MLD level and must be allowed on all affiliated links (§2.1.1). A client joining an AP MLD picks an AKM suite and a pairwise cipher suite that the BSSs of *all* affiliated links enable; if none exists it doesn't try to associate. The group data and group management cipher suites are handled the same way (Table 3). A note says the links don't have to operate in the same mode. |
| **Strength** | Describes required STA behavior; Table 3 isn't marked MAND / RECOM |
| **Candidates** | `ap_akm`, `sta_akm`, `link_akm_mismatch`, `ap_pairwise_cipher` |
| **hostap evidence** | `link_akm_mismatch` row of `surface_candidates.csv`: the `eht_mld_invalid_link*` tests expect association on the matching link only (`valid_links=2`) rather than no association |
| **Open question** | The guide says the client doesn't associate if no suite works on all links; hostap's tests associate on the subset of links that match. Find out how 802.11be scopes "all affiliated links" before writing the rule. |
| **Status** | Unverified |

### WFA.EHT_BEACON_PROT: beacon protection is mandatory when EHT is enabled

| | |
|---|---|
| **Source** | WFA-WPA3 Table 4 "Common security configuration for all WPA3 and Wi-Fi Enhanced Open modes" (p. 12) |
| **Says** | For an AP with EHT enabled on the BSS, and for an EHT STA, beacon protection Enabled is MAND and Disabled is DISALLOW, in every WPA3 and Enhanced Open mode. For non-EHT devices it's only RECOM. |
| **Strength** | MAND / DISALLOW |
| **Candidates** | `ap_beacon_protection` (`1` / `0`), `sta_beacon_protection` |
| **Effect** | If verified, `ap_beacon_protection = 0` on our Wi-Fi 7 AP is not an admissible choice, so beacon protection has one admissible value and is a fixed setting, not a dimension. `eht_mld_sae_two_links_no_beacon_prot` becomes a candidate P1 rejection example. |
| **Status** | Unverified |

### WFA.PMF_BY_MODE: PMF must be Required in the "only" modes

| | |
|---|---|
| **Source** | WFA-WPA3 Table 8 "WPA3-Personal Only Mode" (p. 18); Table 15 "Wi-Fi Enhanced Open Only Mode" (p. 25); Table 5 "WPA3-Personal Transition Mode" (pp. 13–14); Table 3 note (p. 9) |
| **Says** | In WPA3-Personal Only and Enhanced Open Only modes, PMF Required is MAND and Capable / Disabled are DISALLOW, for EHT and non-EHT devices. Transition mode has different PMF values (Table 5). A note in Table 3 says an AP MLD always enables PMF. |
| **Strength** | MAND / DISALLOW |
| **Candidates** | `ap_pmf` (`2` / `1`), `sta_pmf` |
| **Effect** | `ap_pmf = 1` appears in hostap's rekey tests together with a mixed SAE + PSK AKM list, which looks like transition mode. So PMF isn't a free choice: it follows from the security mode. |
| **Status** | Unverified (check the column order in Table 5) |

### WFA.EHT_PERSONAL_AKMS: a Wi-Fi 7 AP in WPA3-Personal Only enables SAE-GDH and SAE

| | |
|---|---|
| **Source** | WFA-WPA3 Table 8 (p. 18) and its footnotes (pp. 18–19) |
| **Says** | For an AP with EHT enabled: SAE-GDH (`00-0F-AC:24`) MAND, SAE (`:8`) MAND, PSK DISALLOW; FT-SAE-GDH and FT-SAE RECOM. A footnote says that where all APs and STAs are known to support EHT, SAE doesn't need to be enabled. Another footnote says SAE-GDH needs SAE Hash-to-Element support. |
| **Strength** | MAND / DISALLOW, with a footnote exception |
| **hostap mapping** | Selector `00-0F-AC:24` is `RSN_AUTH_KEY_MGMT_SAE_EXT_KEY` (`src/common/wpa_common.h:104`), i.e. hostap's `SAE-EXT-KEY` |
| **Candidates** | `ap_akm` (`SAE` / `SAE-EXT-KEY` / `OWE`), `sta_akm` |
| **Effect** | hostap's tests often configure the AP with `SAE` alone (`ap_akm` row of `surface_candidates.csv`). hostap tests aren't necessarily WFA-compliant configurations: keep "hostap runs it" (P2/P3) separate from "the guidance allows it" (P1). |
| **Status** | Unverified |

### WFA.EHT_SAE_H2E: Hash-to-Element can't be disabled on a Wi-Fi 7 AP

| | |
|---|---|
| **Source** | WFA-WPA3 Table 8 (p. 18) and footnotes (pp. 18–19) |
| **Says** | Columns are "H2E Only", "Enabled" and "Disabled". As extracted, for an AP with EHT enabled: H2E Only is MAND in 6 GHz or sub-1 GHz, Enabled is MAND in other bands, Disabled is DISALLOW. For an EHT STA: Enabled MAND, H2E Only DISALLOW, with a footnote allowing H2E Only where all APs and STAs are known to support EHT. |
| **Strength** | MAND / DISALLOW, band-dependent, with a footnote exception |
| **hostap mapping** | `sae_pwe`: `0` = hunting-and-pecking only, `1` = H2E only, `2` = both (`hostapd/hostapd.conf:2292-2294`). Reading "Enabled" as `2` and "Disabled" as `0` is our interpretation; check it. |
| **Candidates** | `ap_sae_pwe` (`1` / `2` / unset), `sta_sae_pwe` |
| **Effect** | Our tests use 2.4 GHz (channels 1 and 6), so `sae_pwe = 0` would be disallowed, while `2` (and `1` under the footnote) might be admissible. Note that hostap's default for `sae_pwe` is `0`, so "unset" may not be admissible either. |
| **Status** | Unverified. This table is the one most likely to be misread from the extracted text: check its columns first. |

## What this changes for the smoke test

If the findings above hold:

- **Beacon protection**: not a dimension (one admissible value on an EHT AP). Keep its
  `0` test as a P1 rejection example.
- **PMF**: not a free dimension; it's determined by the security mode.
- **AKM** and **SAE H2E**: still candidate dimensions, but the admissible choices are
  narrower than the values hostap's tests use.
- **Link AKM / cipher match**: the main P1 rule candidate; settle the open question in
  WFA.MLD_COMMON_SUITES against 802.11be first.

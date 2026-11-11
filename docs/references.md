# References

The documents our P1 rules (`rules.yaml`) and research files (`docs/research/`) cite. Every
rule names one of these by its **ID**, plus a clause or table, e.g.
`IEEE-802.11be-2024 §12.12.9`, and says what kind of text it cites (`strength`: a "shall",
a NOTE, other IEEE text, WFA guidance or hostap code). `rules.load_rules()` refuses a
normative rule without a "shall".

**Don't commit the PDFs.** They are licensed for personal use; link to them instead. Quote
only a short phrase where needed and paraphrase the rest.

## Standards and guidance

| ID | Document | Version | Kind | Get it |
|---|---|---|---|---|
| `IEEE-802.11be-2024` | IEEE Std 802.11be-2024, "Amendment 2: Enhancements for Extremely High Throughput (EHT)" (the Wi-Fi 7 amendment) | 2024 | **Normative** ("shall") | [IEEE standard page](https://standards.ieee.org/ieee/802.11be/7516/); free PDF through the [IEEE GET Program (802 series)](https://ieeexplore.ieee.org/browse/standards/get-program/page/series?id=93) |
| `IEEE-802.11-2024` | IEEE Std 802.11-2024, the base Wi-Fi standard (most security rules live here) | 2024 | **Normative** ("shall") | [IEEE GET Program (802 series)](https://ieeexplore.ieee.org/browse/standards/get-program/page/series?id=93) |
| `WFA-WPA3` | Wi-Fi Alliance, "WPA3™ and Wi-Fi Enhanced Open™ Deployment and Implementation Guide" | v1.1, February 2025 | **Guidance** (not normative) | [Wi-Fi Alliance download](https://www.wi-fi.org/file/wpa3-and-wi-fi-enhanced-open-deployment-and-implementation-guide-2025) (starts the PDF download directly) |

The WPA3 Specification itself (Wi-Fi Alliance) is optional and not used yet.

Normative means the IEEE text with "shall": a rule built on it is a spec rule. A rule that
only rests on `WFA-WPA3` must say it comes from Wi-Fi Alliance guidance (the WFA guide says
its mandatory / disallowed values come from the WPA3 and Wi-Fi Enhanced Open
specifications, but it is not IEEE text). NOTEs in the IEEE standards are informative, not
rules.

## Relevant sections

Found by the security research ([`docs/research/security-guidance.md`](research/security-guidance.md))
and the 2026-11-02 check of all three PDFs (the clause 35 and §12.6.19 rows come from
that check). IEEE pages are "PDF p. N (printed p. M)"; the printed page is one less.

| ID | Section | What it covers | Page |
|---|---|---|---|
| `IEEE-802.11be-2024` | §9.4.2.25, Table 9-192 (bit 84) | Beacon Protection Enabled is the same on all links of an AP MLD | PDF 209 (printed 208) |
| `IEEE-802.11be-2024` | §12.6.2 | AP MLD links advertise the same RSNE except the AKM list and MFPR; at least one common AKM | PDF 411 (printed 410) |
| `IEEE-802.11be-2024` | §12.6.3.1–12.6.3.2 | The client picks one AKM / pairwise / group cipher common to all affiliated APs; the AP MLD checks MFPC / MFPR per link | PDF 411–412 (printed 410–411) |
| `IEEE-802.11be-2024` | §12.6.19 | RSNA rekeying for MLO: the AP MLD manages the PTKSA, each affiliated AP its own GTKSA / IGTKSA / BIGTKSA; a new PTKSA *should* be set up before the old one expires | PDF 413 (printed 412) |
| `IEEE-802.11be-2024` | §12.12.9 | Security constraints for EHT: beacon protection, SAE hash-to-element, AKM 24 / 25 | PDF 446 (printed 445) |
| `IEEE-802.11be-2024` | §35.3.5.2 | ML security: one PTKSA across setup links, a GTKSA / IGTKSA / BIGTKSA per link; different links use different group keys | PDF 512 (printed 511) |
| `IEEE-802.11be-2024` | §35.3.6.3 | Removing affiliated AP(s): announcement, removal timer, and disassociation of a non-AP MLD whose only setup link is removed | PDF 515–518 (printed 514–517) |
| `IEEE-802.11be-2024` | §35.3.7.5 | Affiliated AP link disablement / enablement: no individually addressed frames on a disabled link | PDF 533–535 (printed 532–534) |
| `IEEE-802.11-2024` | §9.4.2.240, Table 9-373 (bit 5) | SAE Hash-to-element bit in the RSNXE; ignored when SAE isn't negotiated (NOTE) | PDF 1433 (printed 1432) |
| `IEEE-802.11-2024` | §11.52 | Beacon protection requires PMF | PDF 2931 (printed 2930) |
| `IEEE-802.11-2024` | §12.4.4.2.3, §12.4.4.3.3 | SAE hash-to-element derivation of the password element (ECC / FFC groups) | §12.4.4.2.3: PDF 2967 (printed 2966) |
| `WFA-WPA3` | §2.1, Table 3 | Security parameters; what applies at the AP MLD level; SAE Hash-to-Element applies only with an SAE AKM (p. 10) | pp. 7–11 |
| `WFA-WPA3` | §3.1.4.1 (NOTE), §3.2 | AP MLD links share RSNE / RSNXE except AKM list and MFPR (p. 28); EHT / MLO with a password needs WPA3 (p. 29) | pp. 28–29 |
| `WFA-WPA3` | Table 4 | Settings common to all WPA3 / Enhanced Open modes (incl. beacon protection) | pp. 12–13 |
| `WFA-WPA3` | Tables 5, 8, 15 | WPA3-Personal Transition, WPA3-Personal Only, Enhanced Open Only | pp. 13–14, 18–19, 24–25 |

## Coverage matrix

[`spec_coverage.csv`](../spec_coverage.csv) tracks which clauses of these three documents
the model covers (issue #62), one row per requirement: document, clause, PDF page, a
summary in our own words, strength (the `rules.yaml` vocabulary), status, the rule IDs
built on it, the unit tests that exercise them and committed runs that show it. Status is
`RULE` (a rule in `rules.yaml` cites it), `UND` (an open question cites it),
`OUT_OF_SCOPE` (with a one-line reason) or `TODO` (not read or not modeled yet; clause or
page `TBD` until someone finds it in the PDF). `tests/test_spec_coverage.py` checks that
every clause `rules.yaml` and the table above cite is in the matrix, and that every `RULE`
row names an existing rule. Add a row whenever a rule gains a citation.

## Implementation references (not normative)

These show what our pinned implementation does, not what the spec requires. Versions are
pinned in [`baseline/README.md`](../baseline/README.md).

| ID | What | Version |
|---|---|---|
| `hostap` | hostapd / wpa_supplicant and `tests/hwsim` | `43ee60e13c257d33d25bfb6892b9ee38fb6e88a4` |
| `wireless-next` | Linux kernel with mac80211_hwsim | `21b4248bfa0f410fa22202fc2c82f4808d672cda` |

## Getting your own copy

- **IEEE standards**: make a free IEEE account and download both PDFs through the IEEE GET
  Program link above. If your university subscribes to IEEE Xplore, signing in through
  your institution works too.
- **Wi-Fi Alliance guide**: open the Wi-Fi Alliance link above; the PDF downloads
  straight away, no account needed. Check the cover says v1.1, February 2025, so page
  numbers match: the Wi-Fi Alliance may replace the file behind the same link with a newer
  version.

Each copy is licensed to the person who downloaded it, so everyone doing rule research or
reviewing it needs their own.

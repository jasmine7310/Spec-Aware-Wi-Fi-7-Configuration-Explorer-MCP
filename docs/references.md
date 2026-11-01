# References

The documents our P1 rules (`rules.yaml`) and research files (`docs/research/`) cite. Every
rule names one of these by its **ID**, plus a clause or table, e.g.
`IEEE-802.11be-2024 §12.12.9`.

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

Found so far by the security research ([`docs/research/security-guidance.md`](research/security-guidance.md)).
IEEE pages are "PDF p. N (printed p. M)"; the printed page is one less.

| ID | Section | What it covers | Page |
|---|---|---|---|
| `IEEE-802.11be-2024` | §9.4.2.25, Table 9-192 (bit 84) | Beacon Protection Enabled is the same on all links of an AP MLD | PDF 209 (printed 208) |
| `IEEE-802.11be-2024` | §12.6.2 | AP MLD links advertise the same RSNE except the AKM list and MFPR; at least one common AKM | PDF 411 (printed 410) |
| `IEEE-802.11be-2024` | §12.6.3.1–12.6.3.2 | The client picks one AKM / pairwise / group cipher common to all affiliated APs; the AP MLD checks MFPC / MFPR per link | PDF 411–412 (printed 410–411) |
| `IEEE-802.11be-2024` | §12.12.9 | Security constraints for EHT: beacon protection, SAE hash-to-element, AKM 24 / 25 | PDF 446 (printed 445) |
| `IEEE-802.11-2024` | §11.52 | Beacon protection requires PMF | PDF 2931 (printed 2930) |
| `WFA-WPA3` | §2.1, Table 3 | Security parameters; what applies at the AP MLD level | pp. 7–11 |
| `WFA-WPA3` | Table 4 | Settings common to all WPA3 / Enhanced Open modes (incl. beacon protection) | pp. 12–13 |
| `WFA-WPA3` | Tables 5, 8, 15 | WPA3-Personal Transition, WPA3-Personal Only, Enhanced Open Only | pp. 13–14, 18–19, 24–25 |

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

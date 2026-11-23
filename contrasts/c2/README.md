# c2: a minimized `link` contrast (#106)

**Label: `MINIMIZED`.** Of the 7 inputs that differ between two clean runs, one change
moves traffic off link 1: **link 1's `indicate_disabled` false → true**. Both final sides
reproduced 3/3 in fresh guests.

- **Category: `link`**, by its target fact (`data_test_rx_ap_links`), as in
  `anchor_coverage.csv`'s `category` column (#105).
- **Minimal cause: a link setting.** It's not c1's 5 s PTK rekey: neither side rekeys the PTK.

`reduction.json` holds everything below: the contrast, the deltas, every probe (the
reduction trace) and the reproduction. It was written by `scripts/minimize_contrast.py`
(`minimize`, then `verify`) on 2026-11-23, on today's harness (`5c0fe724…`, the same as
c1's), with Docker Desktop on macOS. `tests/test_minimize.py` re-reads the committed runs
and checks they match it.

c2 is the issue's folder name. It isn't the C2 of `contrasts/README.md` (`link_remove` on
or off with a 5 s PTK rekey).

## The contrast

| | A: both links carry traffic | B: link 1 advertised disabled |
|---|---|---|
| Runs | `1794952292`, `1794952308`, `1794952325` (`contrasts/runs/`, c1's minimal side) | `1794933586`, `1794933644`, `1794933694` (`contrasts/runs/`) |
| AKM (both links, client) | SAE-EXT-KEY | OWE |
| `sae_pwe` (AP, client) | `hash_to_element`, `both` | unset |
| PTK / GTK rekey interval | unset / 5 s | unset / unset |
| Link 1 `indicate_disabled` | no | yes |
| Actions | `associate`, `link_remove` (link 1, count 4) | the same |
| `data_test_rx_ap_links` | `[0, 1]` | `[0]` |

Both sides are P2 `SUPPORTED`, ACCEPTED and on the same harness. The contrast claims 3
facts: `data_test_rx_ap_links`, `gtk_rekeys_completed` and `station_status`. The target is
B's `data_test_rx_ap_links` only:
- `gtk_rekeys_completed` follows from the GTK rekey interval, a different input.
- `station_status` repeats the negotiated AKM (a config echo; see `minimize.py`, "Choosing the target").

**What the fact measures.** `data_test_rx_ap_links` lists the AP links that received
hostap's traffic test (`DATA-TEST-RX`). The adapter tests every link the client reports
active (`active_links`, read from the client's debugfs), not the links the config enables
(`docker/test_explorer_candidate.py`, `traffic_checks`). So `[0]` means the client never
activated link 1. It doesn't mean traffic on link 1 was tried and failed.

## The reduction

7 typed deltas, each a whole change from A towards B (the actions are the same, so they
give none):

| ID | Delta |
|---|---|
| 0 | `config.ap.gtk_rekey_interval_s`: 5 → null |
| 1 | `config.ap.links[0].akms`: SAE-EXT-KEY → OWE |
| 2 | `config.ap.links[1].akms`: SAE-EXT-KEY → OWE |
| **3** | **`config.ap.links[1].indicate_disabled`: false → true** |
| 4 | `config.ap.sae_pwe`: hash_to_element → null |
| 5 | `config.sta.akms`: SAE-EXT-KEY → OWE |
| 6 | `config.sta.sae_pwe`: both → null |

**Cost.** 8 probes: 5 guest runs (runs in `probes/`), no cache hits.

| # | Picire step | Deltas applied | Status | Why / run | `data_test_rx_ap_links` |
|---|---|---|---|---|---|
| 0 | target | all (= B) | `INTERESTING` | `1795473021` | `[0]` |
| 1 | baseline | none (= A) | `NOT_INTERESTING` | `1795473037` | `[0, 1]` |
| 2 | r0 / s0 | 0–2 | `INVALID` (P1) | `SEC.MLD_CLIENT_COMMON_AKM`, `SEC.SAE_PWE_NEEDS_SAE` | not run |
| 3 | r0 / s1 | 3–6 | `INVALID` (P1) | `SEC.MLD_CLIENT_COMMON_AKM` | not run |
| 4 | r1 / s0 | 0 | `NOT_INTERESTING` | `1795473047` | `[0, 1]` |
| 5 | r1 / s1 | 1, 2 | `INVALID` (P1) | `SEC.MLD_CLIENT_COMMON_AKM`, `SEC.SAE_PWE_NEEDS_SAE` | not run |
| 6 | r1 / s2 | 3, 4 | `INTERESTING` | `1795473058` (support probe) | `[0]` |
| 7 | r2 / s0 | 3 | `INTERESTING` | `1795473068` (support probe) | `[0]` |

- **The endpoints were rechecked.** Probes 0 and 1 re-ran B and A and gave the same values as the committed runs.
- **The AKM changes never booted.** The 3 `INVALID` probes changed the AKM on the AP links but not the client, or the reverse, which the modeled rules forbid. Grouping changes that must move together (Jasmine's point on #101) would skip them.
- **No delta is there only for legality.** `needed_for_validity` is empty: the minimal set is the single delta 3.
- **Ruled out by a real run:** probe 4 dropped the GTK rekey alone and link 1 still carried traffic.
- **P2 at the time:** the minimal candidate was `UNRESOLVED`, so it ran as a support probe (every value had evidence). Its reproduction runs below now make it `SUPPORTED`.

## Reproduction: 3/3 per side

Each final side ran 3 more times in fresh guests (`force`, never a cache hit). The runs
are in `contrasts/runs/`, so they're P2 evidence and contrast sides. All six are test
`PASS` (`manifest.json`).

| Side | Runs | `data_test_rx_ap_links` | `active_links` after association | As expected |
|---|---|---|---|---|
| A as it was | `1795473107`, `1795473128`, `1795473143` | `[0, 1]` in each | `0x3` | 3/3 differ from the target |
| A with link 1 `indicate_disabled` | `1795473160`, `1795473183`, `1795473195` | `[0]` in each | `0x1` | 3/3 match the target |

**Supporting log lines** (`explorer_candidate.log`, the observation after `associate`):
- In `1795473107`:
  - `:65` `valid_links=0x3`, `:68` `active_links=0x3`;
  - `:97` `wlan7_link0: <3>DATA-TEST-RX …` and `:119` `wlan7_link1: <3>DATA-TEST-RX …`;
  - then `:133` `LINK_REMOVE 4`.
- In `1795473160`:
  - `:65` `valid_links=0x3`, `:68` `active_links=0x1`;
  - `:97` `wlan7_link0: <3>DATA-TEST-RX …` only, with no `wlan7_link1` line;
  - then `:111` `LINK_REMOVE 4`.

Both sides set up both links (`valid_links=0x3`). With link 1 advertised as disabled, only
link 0 becomes active.

The two sides are one input apart, so `contrasts.find` also lists them as a reproduced
contrast in `contrasts.json`. A's reproduction runs join A's group there (c1's minimal
side, now 6 runs).

## What this shows, and what it doesn't

- **Among these 7 inputs**, advertising link 1 as disabled (hostapd `mld_indicate_disabled=1`, `adapter.build_plan`) is the one change that keeps traffic off link 1, for this candidate (SAE-EXT-KEY, H2E, 5 s GTK rekeys, `link_remove`). It's 1-minimal: without the delta, link 1 is active and carries traffic (the baseline).
- **It's expected behavior, not a bug.** hostap's own test sets `mld_indicate_disabled` on link 1 (`tests/hwsim/test_eht.py:510`) and then requires the bitmaps `dormant_links` = 2 (link 1 dormant) and `active_links` = 1 (link 0 only), with `valid_links` = 3 (`test_eht.py:525-531`) at the pinned commit. The roadmap counts a predictable result as a behavior difference.
- **Only the first observation differs.** After `link_remove` both sides use link 0 only, so the difference is in traffic before the removal. The record keeps the union of links that received traffic, not a per-step value.
- **No claim about the standard.** `spec_coverage.csv`'s §35.3.7.5.2 row (link disablement) notes that `mld_indicate_disabled` is a static setting, not the TTLM procedure. This contrast reports what the pinned hostap and kernel do, nothing about what 802.11be requires.
- **Single-run probes.** Each probe is one run. The 3/3 reproduction of both final sides is what makes the result count.

## Reproduce

```bash
.venv/bin/python scripts/minimize_contrast.py minimize --a 1794952292 --b 1794933586 \
    --facts data_test_rx_ap_links --out contrasts/c2
.venv/bin/python scripts/minimize_contrast.py verify --out contrasts/c2
```

Rerunning `minimize` serves probes from the cache where their key matches. `verify` always
boots fresh guests.

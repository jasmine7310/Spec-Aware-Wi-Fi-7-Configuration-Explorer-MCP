# c3, first attempt: superseded (#107)

**Superseded by `../README.md`.** This reduction kept the AP MLD restart in its minimal set, and its cause ("the AP MLD restart and client reconnect") was wrong: the client reconnect alone gives the second handshake, and dropping `link_remove` is needed for the behavior, not only for support. Jasmine found it with trial runs on PR #121, and the second reduction shows it with committed runs. This folder keeps the first trace, its probe runs (`probes/`, some of which serve the second reduction's cache hits) and its 3/3 reproduction (in `contrasts/runs/`). The rest of this file is as written for the first attempt; paths like `reduction.json` and `probes/` mean this folder, and its Reproduce commands would write to `contrasts/c3`. Its `reduction.json` says so too (`superseded_by: c3`), so tools listing minimized contrasts can skip it.

---

## c3: a minimized `security` contrast (#107)

**Label: `MINIMIZED`.** Of the 9 inputs that differ between two clean runs, the 4 steps of
the `disable_enable_mld` dimension, with `link_remove` dropped, give the client a second
4-way handshake. Both final sides reproduced 3/3 in fresh guests.

- **Category: `security`**, by its target fact (`four_way_handshakes_completed`, one of
  F02's facts in `explorer.anchors.FAMILY_FACTS`), as in `anchor_coverage.csv`'s
  `category` column (#105).
- **Minimal cause: an action sequence.** The AP MLD is disabled and re-enabled, and the
  client disconnects and reconnects. It's not c1's PTK rekey (neither side sets one) or
  c2's link setting (both sides advertise link 1 as disabled).

`reduction.json` holds everything below: the contrast, the deltas, every probe (the
reduction trace) and the reproduction. It was written by `scripts/minimize_contrast.py`
(`minimize`, then `verify`) on 2026-11-23, on today's harness (`5c0fe724…`, the same as
c1's and c2's), with Docker Desktop on macOS. `tests/test_minimize.py` re-reads the
committed runs and checks they match it.

c3 is the issue's folder name. `contrasts/README.md` has no C3.

## The contrast

| | A: one association | B: AP MLD restarted, client reconnects |
|---|---|---|
| Runs | `1795473160`, `1795473183`, `1795473195` (`contrasts/runs/`, c2's minimal side) | `1795474122`, `1795474139`, `1795474153` (`contrasts/runs/`, made for this issue) |
| AKM (both links, client) | SAE-EXT-KEY | the same |
| Pairwise cipher (both links) | CCMP | GCMP-256 |
| `sae_pwe` (AP, client) | `hash_to_element`, `both` | `both`, `hash_to_element` |
| PTK / GTK rekey interval | unset / 5 s | the same |
| Link 1 `indicate_disabled` | yes | the same |
| Actions | `associate`, `link_remove` (link 1, count 4) | `associate`, `DISABLE_MLD`, `DISCONNECT`, `ENABLE_MLD`, `RECONNECT` |
| `four_way_handshakes_completed` | 1 | 2 |

B is the candidate of campaign run `1794812770` (`campaigns/seed1-fresh-2026-11-15/`), which
ran under the earlier harness. Its 3 runs here put both sides on today's harness. Both
sides are P2 `SUPPORTED` and `ACCEPTED`.

The contrast claims 5 facts: `four_way_handshakes_completed`, `disconnects`, `valid_links`,
`link_reconfig_valid_links` and `station_status`. The target is B's
`four_way_handshakes_completed` only:
- `valid_links` and `link_reconfig_valid_links` follow from `link_remove` on A's side.
- `disconnects` counts the client's own `DISCONNECT` (reason 3, local) as well as the teardown.
- `station_status` repeats the negotiated cipher, a config echo (see `minimize.py`, "Choosing the target").

**What the fact measures.** `four_way_handshakes_completed` counts hostapd's
`EAPOL-4WAY-HS-COMPLETED` events in the run's log (`signatures._FOUR_WAY`): handshakes the
AP saw complete. Neither side rekeys the PTK, so here each one belongs to an association.

## The reduction

9 typed deltas, each a whole change from A towards B. The 4 config deltas come first, then
one delta per action step only one side performs:

| ID | Delta |
|---|---|
| 0 | `config.ap.links[0].pairwise_cipher`: CCMP → GCMP-256 |
| 1 | `config.ap.links[1].pairwise_cipher`: CCMP → GCMP-256 |
| 2 | `config.ap.sae_pwe`: hash_to_element → both |
| 3 | `config.sta.sae_pwe`: both → hash_to_element |
| **4** | **drop A's `link_remove` (link 1, count 4)** |
| **5** | **add `disable_enable_mld` `DISABLE_MLD`** |
| **6** | **add `sta_disconnect_reconnect` `DISCONNECT`** |
| **7** | **add `disable_enable_mld` `ENABLE_MLD`** |
| **8** | **add `sta_disconnect_reconnect` `RECONNECT`** |

**Cost.** 18 probes:
- 7 guest runs (in `probes/`);
- 2 cache hits (the endpoints);
- 9 never booted: 7 broke an action-order rule and 2 hit a recorded implementation limit.

| # | Picire step | Deltas applied | Status | Why / run | Handshakes |
|---|---|---|---|---|---|
| 0 | target | all (= B) | `INTERESTING` | `1795474122` (cache hit) | 2 |
| 1 | baseline | none (= A) | `NOT_INTERESTING` | `1795473068` (cache hit, c2's probe 7) | 1 |
| 2 | r0 / s0 | 0–3 | `NOT_INTERESTING` | `1795474187` (support probe) | 1 |
| 3 | r0 / s1 | 4–8 | `INTERESTING` | `1795474199` (support probe) | 2 |
| 4 | r1 / s0 | 4, 5 | `NOT_INTERESTING` | `1795474213` (support probe) | 1 |
| 5 | r1 / s1 | 6–8 | `INVALID` | `AO.ENABLE_AFTER_DISABLE` | not run |
| 6 | r2 / s0 | 4 | `NOT_INTERESTING` | `1795474228` (support probe) | 1 |
| 7 | r2 / s1 | 5 | `UNSUPPORTED` | `P2.DISABLE_MLD_AFTER_LINK_REMOVE` | not run |
| 8 | r2 / s2 | 6 | `NOT_INTERESTING` | `1795474245` (support probe) | 1 |
| 9 | r2 / s3 | 7, 8 | `INVALID` | `AO.ENABLE_AFTER_DISABLE` | not run |
| 10 | r2 / c0 | 5–8 | `UNSUPPORTED` | `P2.DISABLE_MLD_AFTER_LINK_REMOVE` | not run |
| 11 | r2 / c1 | 4, 6–8 | `INVALID` | `AO.ENABLE_AFTER_DISABLE` (no `DISABLE_MLD` before it) | not run |
| 12 | r2 / c2 | 4, 5, 7, 8 | `INVALID` | `AO.ENABLE_AFTER_DISABLE` (no `DISCONNECT` before it) | not run |
| 13 | r2 / c3 | 4–6 | `NOT_INTERESTING` | `1795474260` (support probe) | 1 |
| 14 | r3 / s3 | 7 | `INVALID` | `AO.ENABLE_AFTER_DISABLE` | not run |
| 15 | r3 / s4 | 8 | `INVALID` | `AO.RECONNECT_AFTER_DISCONNECT` | not run |
| 16 | r3 / c3 | 4–6, 8 | `INVALID` | `AO.ENABLE_AFTER_DISABLE` (`RECONNECT` before `ENABLE_MLD`) | not run |
| 17 | r3 / c4 | 4–7 | `NOT_INTERESTING` | `1795474277` (support probe) | 1 |

- **The endpoints weren't re-run.** Both were cache hits on today's harness: B's first run, and c2's probe 7 (A's candidate). A cache hit isn't an independent run; the 3/3 reproduction below is.
- **The config deltas don't matter here.** Probe 2 applied all 4 (GCMP-256, swapped `sae_pwe`) and still logged 1 handshake.
- **The minimal set is 1-minimal.** Removing any one of its 5 deltas gives a probe that either ran and logged 1 handshake (`RECONNECT`, probe 17) or couldn't run (the other 4).
- **Kept for legality: deltas 5, 6, 7** (`needed_for_validity`). Without any one of them, `RECONNECT` breaks an action-order rule (probes 11, 12, 16). Their removal was never run, so the trace can't say whether they matter for the handshake.
- **Kept for support: delta 4.** Keeping A's `link_remove` makes `DISABLE_MLD` fail in hostapd, which `P2.DISABLE_MLD_AFTER_LINK_REMOVE` records with refusals `1794557044`, `1794557059`, `1794557071`, `1794557082` (probes 7, 10). This isn't a Wi-Fi rule. `needed_for_validity` lists only `INVALID` / `SPEC_UNDETERMINED` removals, so delta 4 isn't in it, but the same caveat applies.
- **Ruled out by real runs:** `DISABLE_MLD` alone (probe 4), `DISCONNECT` alone after `link_remove` (probe 8), and the AP restart plus `DISCONNECT` without `RECONNECT` (probes 13, 17). Each logged 1 handshake.
- **P2 at the time:** the minimal candidate was `UNRESOLVED` (probe 3 ran it as a support probe). Its reproduction runs below now make it `SUPPORTED`.

## Reproduction: 3/3 per side

Each final side ran 3 more times in fresh guests (`force`, never a cache hit). The runs
are in `contrasts/runs/`, so they're P2 evidence and contrast sides. All six are test
`PASS` (`manifest.json`).

| Side | Runs | `four_way_handshakes_completed` | As expected |
|---|---|---|---|
| A as it was | `1795474332`, `1795474355`, `1795474380` | 1 in each | 3/3 differ from the target |
| A with the 5 minimal deltas | `1795474393`, `1795474434`, `1795474453` | 2 in each | 3/3 match the target |

The minimal candidate is B's action sequence on A's config (CCMP, A's `sae_pwe`).

**Supporting log lines** (`explorer_candidate.log`):
- In `1795474332` (A):
  - `:93` `wlan7_link0: <3>EAPOL-4WAY-HS-COMPLETED`, the only one;
  - `:111` `LINK_REMOVE 4`, `:112` `CTRL-EVENT-LINK-RECONFIG valid_links=0x1`;
  - `:211` the teardown's `CTRL-EVENT-DISCONNECTED … reason=3 locally_generated=1`.
- In `1795474393` (minimal):
  - `:93` the first `EAPOL-4WAY-HS-COMPLETED`;
  - `:111` `DISABLE_MLD`. The client still reports `valid_links=0x3` after it (`:119`);
  - `:127`–`:128` `DISCONNECT`, then `CTRL-EVENT-DISCONNECTED … reason=3 locally_generated=1`, and `valid_links=0x0` (`:132`);
  - `:140` `ENABLE_MLD`;
  - `:172` the harness's `PMKSA_FLUSH` and `BSS_FLUSH 0`, then `:175` `RECONNECT`;
  - `:196` `CTRL-EVENT-CONNECTED` and `:230` the second `EAPOL-4WAY-HS-COMPLETED`;
  - `:318` the teardown's disconnect.

The final pair is 5 inputs apart, so it isn't in `contrasts.json`, which lists contrasts at
most 1 input apart.

## What this shows, and what it doesn't

- **Among these 9 inputs**, the restart sequence (`DISABLE_MLD`, `DISCONNECT`, `ENABLE_MLD`, `RECONNECT`), with `link_remove` dropped, is what gives the second handshake, for this candidate (SAE-EXT-KEY, CCMP, 5 s GTK rekeys, link 1 advertised as disabled). It's 1-minimal over the typed deltas.
- **Which steps cause it, and which only keep it legal, isn't fully separated.** Only removing `RECONNECT` was run, and it lost the second handshake. The client reconnecting without the AP restart (`associate`, `DISCONNECT`, `RECONNECT`) was never probed. Picire removes one delta or one subset at a time, and dropping `DISABLE_MLD` alone breaks `ENABLE_MLD`'s order rule. Grouping deltas that must move together (Jasmine's point on #101) would let the reduction try it.
- **It's expected behavior, not a bug.** hostap's own test does the same steps and then requires the client to connect again (`tests/hwsim/test_eht.py:728-761`, `test_eht_mld_sae_two_links_disable_enable` at `:775`), at the pinned commit. A new association gets a new 4-way handshake. The roadmap counts a predictable result as a behavior difference.
- **The client didn't notice the AP going down.** After `DISABLE_MLD`, the client still reported both links valid until its own `DISCONNECT`. hostap's test comment says the same (`test_eht.py:737-740`), which is why the sequence includes `DISCONNECT`. That's an observation from these logs, not a claim about the cause.
- **A harness step is involved.** Before `RECONNECT` the adapter flushes the client's PMKSA cache and BSS table, as hostap's test does (`test_eht.py:752-759`; `docker/test_explorer_candidate.py`). Without the flush, hostap's TODO says the reconnection fails. In `1795474393` the client then finds no PMKSA entry and runs SAE again (`explorer_candidate.log5:1606`, `:1646`–`:1647`, SAE confirm) before the second handshake.
- **No claim about the standard.** This reports what the pinned hostap and kernel do, nothing about what 802.11be requires.
- **Single-run probes.** Each probe is one run. The 3/3 reproduction of both final sides is what makes the result count.

## Reproduce

```bash
.venv/bin/python scripts/minimize_contrast.py minimize --a 1795473160 --b 1795474122 \
    --facts four_way_handshakes_completed --out contrasts/c3
.venv/bin/python scripts/minimize_contrast.py verify --out contrasts/c3
```

Rerunning `minimize` serves probes from the cache where their key matches. `verify` always
boots fresh guests.

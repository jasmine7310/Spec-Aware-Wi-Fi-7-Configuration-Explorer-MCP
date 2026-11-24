# c3: a minimized `security` contrast (#107)

**Label: `MINIMIZED`.** A client reconnect gives a second 4-way handshake, but only when
`link_remove` hasn't run. The 3 action deltas between the sides (drop `link_remove`, add
`DISCONNECT`, add `RECONNECT`) are all needed, and both final sides reproduced 3/3 in
fresh guests.

- **Category: `security`**, by its target fact (`four_way_handshakes_completed`, one of
  F02's facts in `explorer.anchors.FAMILY_FACTS`), as in `anchor_coverage.csv`'s
  `category` column (#105).
- **Minimal cause: an action sequence.** The client's `DISCONNECT` + `RECONNECT`, with
  `link_remove` absent. It's not c1's PTK rekey (neither side sets one) or c2's link
  setting (both sides advertise link 1 as disabled).

`reduction.json` holds everything below: the contrast, the deltas, every probe (the
reduction trace) and the reproduction. It was written by `scripts/minimize_contrast.py`
(`minimize`, then `verify`) on 2026-11-24, on today's harness (`5c0fe724…`, the same as
c1's and c2's), with Docker Desktop on macOS. `tests/test_minimize.py` re-reads the
committed runs and checks they match it.

c3 is the issue's folder name. `contrasts/README.md` has no C3.

**This is the second reduction.** The first (`first-attempt/`, kept with its trace) went from
A to a B that also restarts the AP MLD (`DISABLE_MLD` … `ENABLE_MLD`). It reduced 9 inputs
to 5 and kept the restart, because Picire removes one typed delta at a time and dropping
`DISABLE_MLD` alone breaks `ENABLE_MLD`'s order rule. So a reconnect without the restart
was never probed. Jasmine ran it as trials on PR #121 and found it gives the second
handshake. This reduction targets that smaller candidate, with committed runs.

## The contrast

| | A: one association | B: the client reconnects |
|---|---|---|
| Runs | `1795473160`, `1795473183`, `1795473195` (`contrasts/runs/`, c2's minimal side) | `1795480398`, `1795480414`, `1795480426` (`contrasts/runs/`, made for this issue) |
| Config | SAE-EXT-KEY, CCMP, `sae_pwe` `hash_to_element` / `both`, 5 s GTK rekeys, link 1 `indicate_disabled` | the same |
| Actions | `associate`, `link_remove` (link 1, count 4) | `associate`, `DISCONNECT`, `RECONNECT` |
| `four_way_handshakes_completed` | 1 | 2 |

Both sides are `ACCEPTED`, test `PASS` and on the same harness. A is P2 `SUPPORTED`. B was a
support probe (every value had a legal run), and its 3 runs now make it `SUPPORTED`.

**What the fact measures.** `four_way_handshakes_completed` counts hostapd's
`EAPOL-4WAY-HS-COMPLETED` events in the run's log (`signatures._FOUR_WAY`): handshakes the
AP saw complete. Neither side rekeys the PTK, so here each one belongs to an association.

## The reduction

3 typed deltas, one per action step only one side performs:

| ID | Delta |
|---|---|
| 0 | drop A's `link_remove` (link 1, count 4) |
| 1 | add `sta_disconnect_reconnect` `DISCONNECT` |
| 2 | add `sta_disconnect_reconnect` `RECONNECT` |

**Cost.** 8 probes:
- 1 guest run (in `probes/`);
- 5 cache hits, served by runs already committed (listed below);
- 2 never booted (`INVALID`).

| # | Picire step | Deltas applied | Actions | Status | Run | Handshakes |
|---|---|---|---|---|---|---|
| 0 | target | 0–2 (= B) | `associate`, `DISCONNECT`, `RECONNECT` | `INTERESTING` | `1795480398` (cache hit, B's run) | 2 |
| 1 | baseline | none (= A) | `associate`, `link_remove` | `NOT_INTERESTING` | `1795473068` (cache hit, `c2/probes/`) | 1 |
| 2 | r0 / s0 | 0 | `associate` | `NOT_INTERESTING` | `1795474228` (cache hit, `first-attempt/probes/`) | 1 |
| 3 | r0 / s1 | 1, 2 | `associate`, `link_remove`, `DISCONNECT`, `RECONNECT` | `NOT_INTERESTING` | `1795480438` (cache hit, `contrasts/runs/`) | 1 |
| 4 | r1 / s1 | 1 | `associate`, `link_remove`, `DISCONNECT` | `NOT_INTERESTING` | `1795474245` (cache hit, `first-attempt/probes/`) | 1 |
| 5 | r1 / s2 | 2 | `associate`, `link_remove`, `RECONNECT` | `INVALID` | `AO.RECONNECT_AFTER_DISCONNECT` | not run |
| 6 | r1 / c1 | 0, 2 | `associate`, `RECONNECT` | `INVALID` | `AO.RECONNECT_AFTER_DISCONNECT` | not run |
| 7 | r1 / c2 | 0, 1 | `associate`, `DISCONNECT` | `NOT_INTERESTING` | `1795480492` (new) | 1 |

The minimal set is all 3 deltas, and it's 1-minimal:
- **Without dropping `link_remove`** (probe 3), the reconnect logs no second handshake. This removal was run, so `link_remove`'s absence is needed for the behavior, not only for legality. See "With `link_remove`, the reconnect fails" below.
- **Without `RECONNECT`** (probe 7), there's no second association. This removal was run.
- **Without `DISCONNECT`** (probe 6), `RECONNECT` breaks `AO.RECONNECT_AFTER_DISCONNECT`, so it's `needed_for_validity`. Its removal was never run.

**Cache hits aren't independent.** Probe 3's run is one of the 3 runs of that candidate
committed for this issue (`1795480438`, `1795480449`, `1795480460`), each with 1 handshake.
The 3/3 reproduction below is what makes the result count.

## Reproduction: 3/3 per side

Each final side ran 3 more times in fresh guests (`force`, never a cache hit). The runs
are in `contrasts/runs/`, so they're P2 evidence and contrast sides. All six are test
`PASS` (`manifest.json`).

| Side | Runs | `four_way_handshakes_completed` | As expected |
|---|---|---|---|
| A as it was | `1795480526`, `1795480537`, `1795480546` | 1 in each | 3/3 differ from the target |
| A with the 3 deltas (= B) | `1795480556`, `1795480567`, `1795480580` | 2 in each | 3/3 match the target |

**Supporting log lines** (`explorer_candidate.log`):
- In `1795480526` (A):
  - `:93` `wlan7_link0: <3>EAPOL-4WAY-HS-COMPLETED`, the only one;
  - `:111` `LINK_REMOVE 4`, `:112` `CTRL-EVENT-LINK-RECONFIG valid_links=0x1`;
  - `:211` the teardown's `CTRL-EVENT-DISCONNECTED … reason=3 locally_generated=1`.
- In `1795480556` (B):
  - `:93` the first `EAPOL-4WAY-HS-COMPLETED`;
  - `:111`–`:112` `DISCONNECT`, then `CTRL-EVENT-DISCONNECTED … reason=3 locally_generated=1`, and `valid_links=0x0` (`:116`);
  - `:144` `RECONNECT`, `:157` `CTRL-EVENT-CONNECTED`, and `valid_links=0x3` again (`:161`);
  - `:183` the second `EAPOL-4WAY-HS-COMPLETED`;
  - `:271` the teardown's disconnect.
- **The reconnect reuses the first SAE's PMKSA.** In `explorer_candidate.log5`, the first association runs SAE (`:726` `SME SAE confirm`), and the reconnect finds its PMKID in the cache (`:1548`). The 4-way handshake still runs, so the count goes up.

The final pair is 3 inputs apart, so it isn't in `contrasts.json`, which lists contrasts at
most 1 input apart. B and the `link_remove` + reconnect candidate are one input apart, so
`contrasts.json` lists that pair.

## With `link_remove`, the reconnect fails

These are the 3 committed runs of probe 3's candidate (`associate`, `link_remove`,
`DISCONNECT`, `RECONNECT`): `1795480438`, `1795480449`, `1795480460` (`contrasts/runs/`,
`ACCEPTED`, test `PASS`). Each logged 1 handshake and disconnects
{(3, local), (15, from the AP) ×4}.

The following holds in each of the 3 runs, checked in `explorer_candidate.hostapd` and
`explorer_candidate.log5`:
- **hostapd receives EAPOL only before `LINK_REMOVE`.** Before it, hostapd receives 2 EAPOL frames (`NL80211_CMD_CONTROL_PORT_FRAME`), the initial handshake's 2/4 and 4/4. After it, hostapd receives none.
- **The reconnect's handshake times out.** The client associates again after `RECONNECT` (`explorer_candidate.log:186` in `1795480438`). hostapd sends message 1/4 (`PTKSTART`) 20 times after `LINK_REMOVE`, then disconnects the client with reason 15 (`wpa_sta_disconnect … (reason 15)`), 4 times in all. The client reassociates after each.
- **The client keeps replying.** It sends `EAPOL-Key 2/4` 17 times across the run.

That's the same pattern as `contrasts/README.md`'s C1 ("What the logs show"), where the PTK
rekey's handshake fails after `link_remove`. Here a reconnect's initial handshake fails the
same way. The logs don't show where the frames are lost (radio, kernel or hostapd), and no
claim is made about why.

## What this shows, and what it doesn't

- **Among these 3 inputs**, a client reconnect gives a second 4-way handshake only without `link_remove`, for this candidate (SAE-EXT-KEY, CCMP, 5 s GTK rekeys, link 1 advertised as disabled). All 3 deltas are needed, and 2 of the 3 removals were run.
- **The reconnect alone is expected behavior.** A new association gets a new 4-way handshake. hostap's `test_eht_mld_reconnect_stale_links` sends `DISCONNECT`, later `RECONNECT`, and requires the client to connect again (`tests/hwsim/test_eht.py:1170-1182`), at the pinned commit. The roadmap counts a predictable result as a behavior difference.
- **The `link_remove` side is the interesting part.** After `link_remove`, the client's EAPOL-Key frames stop reaching hostapd, for a reconnect as well as for C1's rekey. That's what the logs show; the cause isn't in them.
- **The AP MLD restart isn't needed.** The first reduction kept it only because its deltas couldn't be removed one at a time (`first-attempt/README.md`). Grouping deltas that must move together (Jasmine's point on #101) would have let Picire try the reconnect alone.
- **No claim about the standard.** This reports what the pinned hostap and kernel do, nothing about what 802.11be requires.
- **Single-run probes.** Each probe is one run. The 3/3 reproduction of both final sides, and the 3 runs of the `link_remove` + reconnect candidate, are what make the result count.

## Reproduce

```bash
.venv/bin/python scripts/minimize_contrast.py minimize --a 1795473160 --b 1795480398 \
    --facts four_way_handshakes_completed --out contrasts/c3
.venv/bin/python scripts/minimize_contrast.py verify --out contrasts/c3
```

Rerunning `minimize` serves probes from the cache where their key matches. `verify` always
boots fresh guests.

# Accepted-vs-accepted contrasts (#71)

Two legal candidates whose runs both came back `ACCEPTED` but behaved differently.
`contrasts.json` lists every contrast `explorer.contrasts.find` reports; this file writes
them up. Regenerate the JSON with `.venv/bin/python scripts/find_contrasts.py`
(`tests/test_contrasts.py` fails when it's stale).

Each contrast has a stable `id` ("x" + 10 hex digits, a hash of its two candidates and
harness, #111): it doesn't shift when contrasts are added or a side gets more repeats.
Each pair has a fixed orientation: side A is the candidate whose canonical JSON sorts
first, so the order the run folders are read in never swaps the sides or changes the ID. A
minimized contrast's ID is its folder name (`c1`). Over MCP, `list_contrasts`,
`get_contrast` and `replay_contrast` use these IDs (see "Over MCP" below).

**How a contrast is found** (`src/explorer/contrasts.py`):

- **Sides.** Committed adapter runs from `campaigns/` and `contrasts/runs/`. Each run must:
  - be `ACCEPTED`, so infrastructure failures (`SETUP_FAIL`, `TIMEOUT`) and refusals (`REJECTED`) are never sides;
  - not be a negative experiment;
  - still pass today's modeled rules;
  - have run on the pinned hostap and kernel commits;
  - have a known harness (`run_harness`): the hash of the adapter test and run script in `docker/`. It's the one recorded with the run's cache key or, for a run that didn't record one, the hash of `docker/` at the repo commit it ran from (only if `docker/` was unmodified).

  Both sides' candidates must be P2 `SUPPORTED` (`support.check_support`).
- **Repeats.** Runs of the same candidate under the same harness are repeats. Two groups are compared only if they ran under the same harness, since a harness change can change what a run logs (see "Two harnesses" below).
- **Inputs.** Each differing config value counts as one input, and so does each action step only one side performs. The JSON lists contrasts at most 1 input apart (`--max-inputs`).
- **Facts.** Facts are the behavior record's signature without the test name, plus `disconnect_reasons`: the set of (reason, locally generated). A fact is claimed only if it is:
  - measured on both sides (never `UNKNOWN`);
  - the same in every repeat of each side;
  - different between the two sides.

  Each claimed fact comes with the log lines it was read from.
- **Reproduced** means at least 3 independent runs per side, each in a fresh guest. Cache hits don't count, and none of these runs was served from the cache.

Today that's 82 accepted runs in 42 groups of repeats.

`contrasts/runs/` holds 49 runs, all `ACCEPTED`, on Docker Desktop on macOS. 16 were made
for this issue so that each side has 3:
- 9 on today's harness (2026-11-17), which are the evidence below;
- 7 on the earlier harness (2026-11-16).

The other 33 are for the minimized contrasts, on today's harness (see "Minimized contrasts"
below):
- their 3/3 reproductions: 6 each from `c1/` (#73) and `c2/` (#106), and 12 from `c3/` (#107), 6 per reduction;
- 9 runs of `c3/`'s candidates (#107): 3 of the first reduction's B side, which had only run under the earlier harness, 3 of the reconnect-only side and 3 of `link_remove` followed by a reconnect.

They're in `support.EVIDENCE_DIRS`, so they count as P2 evidence: each side's candidate is
`SUPPORTED` by exact-match committed runs.

## Shared base candidate

Both contrasts vary one input of the same base:
- **AP MLD:** OWE with CCMP on both links (link 0 on channel 1, link 1 on channel 6), with link 1 `indicate_disabled`, PMF required, beacon protection on and no GTK rekey interval.
- **Client:** OWE with beacon protection on.
- **Actions:** `associate`, optionally followed by `link_remove` (link 1, count 4).

Runs on today's harness:

| | `link_remove` | no `link_remove` |
|---|---|---|
| `ptk_rekey_interval_s` unset | `1794933586`, `1794933644`, `1794933694` | (not used) |
| `ptk_rekey_interval_s` 5 | `1794933558`, `1794933622`, `1794933677` | `1794933604`, `1794933660`, `1794933709` |

All are in `contrasts/runs/`.

_C1 and C2 below are contrasts from `contrasts.json` (`x8dc0b42566`, `x861c3cc852`), not the
minimized `c1/` and `c2/` further down, which are different pairs._

## C1: a 5 s PTK rekey after `link_remove` (reproduced, 3 vs 3; ID `x8dc0b42566`)

**Input that differs:** `config.ap.ptk_rekey_interval_s`, unset vs 5. Same actions:
`associate`, `link_remove`.

**Facts that changed**: all stable across the 3 repeats of each side.

| Fact | No PTK rekey | PTK rekey every 5 s |
|---|---|---|
| `disconnect_reasons` | {(3, local)} | {(3, local), (15, from the AP)} |
| `disconnects` | reason 3 (local, at teardown) | reason 15 from the AP three times, then reason 3 (local) |
| `station_status` (last) | `wpa_state` `COMPLETED`, `bigtk_set` 1 | `wpa_state` `4WAY_HANDSHAKE`, no `bigtk_set` |

Reason 15 is "4-way handshake timeout" (802.11 reason codes). The test result is `PASS` on
both sides. The adapter test records observations and doesn't assert them
(`src/explorer/adapter.py`), so no assertion separates the sides. The difference is in the
facts.

**Supporting log lines.** From `contrasts.json`, PTK-rekey side, `1794933558`'s
`explorer_candidate.log`:

```
:141  wlan8: <3>CTRL-EVENT-DISCONNECTED bssid=02:00:00:00:07:00 reason=15
:200  wlan8: <3>CTRL-EVENT-DISCONNECTED bssid=02:00:00:00:07:00 reason=15
:247  wlan8: <3>CTRL-EVENT-DISCONNECTED bssid=02:00:00:00:07:00 reason=15
:264  wlan8: <3>CTRL-EVENT-DISCONNECTED bssid=02:00:00:00:07:00 reason=3 locally_generated=1
```

The no-rekey side (`1794933586`) logs only the teardown line (`:138`, reason 3,
`locally_generated=1`). The adapter's own lines agree, on every PTK-rekey run and on no
run of the other side:
- `EXPLORER-NO-EVENT PTK rekey within 10.0 s`;
- `EXPLORER-OBSERVE after PTK rekey (not associated: wpa_state=4WAY_HANDSHAKE, no disconnect requested by the adapter)`.

These lines aren't record facts; they're quoted here as log evidence.

**Reproduced:** yes, 3 independent runs per side.

## C2: the same 5 s PTK rekey with and without `link_remove` (reproduced, 3 vs 3; ID `x861c3cc852`)

**Input that differs:** one action step. One side performs `link_remove` (link 1, count
4) after `associate`; the other doesn't. Same config: `ptk_rekey_interval_s` 5.

**Facts that changed**: all stable across the 3 repeats of each side.

| Fact | `link_remove` | no `link_remove` |
|---|---|---|
| `ptk_rekeys_completed` | 0 | 1 |
| `four_way_handshakes_completed` | 1 | 2 |
| `disconnect_reasons` | {(3, local), (15, from the AP)} | {(3, local)} |
| `disconnects` | 15, 15, 15, 3 | 3 |
| `station_status` (last) | `4WAY_HANDSHAKE`, no `bigtk_set` | `COMPLETED`, `bigtk_set` 1 |
| `valid_links` (last) | `0x1` | `0x3` |
| `link_reconfig_valid_links` | [`0x1`] | [] |

The last two follow directly from removing link 1. The others are the rekey: without
`link_remove` it completes 5 s after association (`WPA: Key negotiation completed` at
+5.0 s in `1794933604`), and the traffic check after it passes. One fact differs but isn't
claimed: traffic after the last rekey (`data_test_rx_after_last_rekey_ap_links`) is
`UNKNOWN` on the `link_remove` side, because no rekey ever completes there.

**Supporting log lines:** both sides' are in `contrasts.json`. The `link_remove` side's
runs are C1's PTK-rekey side.

**Reproduced:** yes, 3 vs 3.

## Minimized contrasts

The folders `c1/`, `c2/` and `c3/` are reductions by `scripts/minimize_contrast.py`, each
verified 3/3 per side. They aren't the C1 / C2 above, though `c1/` also points at the PTK rekey.
Their category is the category of their target facts, as in `anchor_coverage.csv`'s
`category` column (#105).

| Folder | Category | Target fact | Inputs → minimal | Minimal cause | Label |
|---|---|---|---|---|---|
| `c1/` (#73) | `key` | `disconnect_reasons` | 8 → 1 | `ptk_rekey_interval_s` 5 → unset (a key setting) | `MINIMIZED` |
| `c2/` (#106) | `link` | `data_test_rx_ap_links` | 7 → 1 | link 1 `indicate_disabled` false → true (a link setting) | `MINIMIZED` |
| `c3/` (#107) | `security` | `four_way_handshakes_completed` | 3 → 3 | the client's `DISCONNECT` + `RECONNECT`, with `link_remove` absent (an action sequence) | `MINIMIZED` |

- **`c1/`** minimizes a failing campaign run 8 inputs away from the clean OWE side (`1794812749` vs `1794557032` and its repeats). Both final sides reproduce 3/3: `1794952238`, `1794952257`, `1794952274` vs `1794952292`, `1794952308`, `1794952325`.
- **`c2/`** starts from `c1/`'s clean side (SAE-EXT-KEY, both links active) and targets the OWE side whose link 1 is advertised as disabled (`1794933586` and its repeats). Neither side rekeys the PTK, so its cause is a different one. Both final sides reproduce 3/3: `1795473107`, `1795473128`, `1795473143` vs `1795473160`, `1795473183`, `1795473195`. With link 1 advertised as disabled, the client sets up both links but activates only link 0, as hostap's own test expects.
- **`c3/`** starts from `c2/`'s minimal side (one association, `link_remove`) and targets the same config with a client reconnect instead (`associate`, `DISCONNECT`, `RECONNECT`; `1795480398` and its repeats). Neither side rekeys the PTK. All 3 action deltas are needed: without `RECONNECT` there's no second association, and with `link_remove` kept the reconnect's handshake times out with reason 15 (`1795480438`, `1795480449`, `1795480460`). Both final sides reproduce 3/3: `1795480526`, `1795480537`, `1795480546` (1 handshake) vs `1795480556`, `1795480567`, `1795480580` (2). A first reduction (`c3/first-attempt/`) went to a B that also restarts the AP MLD and wrongly kept the restart as part of the cause. Jasmine's trials on PR #121 showed the reconnect alone is enough.

Together they cover three categories (`key`, `link`, `security`) and three kinds of minimal
cause: a key setting, a link setting and an action sequence.

Each folder's `README.md` has the write-up and the full trace. Their reproduction runs are in
`runs/`. `c1/`'s and `c2/`'s final pairs are one input apart, so `contrasts.json` also lists
them as reproduced contrasts. `c3/`'s are 3 apart, so it doesn't; its reconnect-only side and the `link_remove` + reconnect candidate are one apart, so that pair is listed.

## Over MCP (#111)

- `list_contrasts`: every contrast in `contrasts.json` (kind `contrast`) and every
  minimized one (kind `minimized`, from `contrasts/<id>/reduction.json`), by ID.
- `get_contrast(contrast_id)`: a contrast's runs with their folders, the differing inputs
  and each claimed fact with both values and its log lines; a minimized one's target,
  deltas, minimal changes, reduction trace and both final sides' verification runs with
  their facts, folders and log lines. Nothing boots.
- `replay_contrast(contrast_id, runs=3, retries=1)`: reruns a minimized contrast's two
  final sides (A, and A with the minimal changes) `runs` times each in fresh guests, at
  most 12 guest runs, every one forced (never a cache hit), through `minimize.verify`.
  `REPRODUCED` when every run is `ACCEPTED` and as expected; `same_facts_as_committed`
  compares the facts with the committed runs. The committed label and files never change;
  replay runs are git-ignored trials in `runs/hwsim-logs/`.
- `minimize_contrast(contrast=...)` now takes a contrast ID instead of a list index.

Walk-through, 2026-11-24 (WSL2, current image, through an in-process MCP client on this
repo's server; trial runs, not committed). `list_contrasts` gave the 7 contrasts and `c1`,
`c2`, `c3` (all `MINIMIZED`). `get_contrast` gave each one's minimal change, its 8 probes
and its 6 committed verification runs with their log lines. `replay_contrast` reran each in
fresh guests: all three `REPRODUCED`, 6 guest runs each (about 40 s), 0 cache hits, the same
facts as committed:

| ID | Target | Baseline runs | Minimal runs |
|---|---|---|---|
| `c1` | `disconnect_reasons` | `1795546635`, `1795546642`, `1795546649`: {(15, from the AP)} | `1795546656`, `1795546663`, `1795546669`: {(3, local)} |
| `c2` | `data_test_rx_ap_links` | `1795546677`, `1795546683`, `1795546689`: [0, 1] | `1795546695`, `1795546702`, `1795546708`: [0] |
| `c3` | `four_way_handshakes_completed` | `1795546716`, `1795546722`, `1795546728`: 1 | `1795546735`, `1795546741`, `1795546748`: 2 |

The IDs held across the merge that brought in `c2` / `c3`: the earlier contrasts kept their
IDs although the list grew from 5 to 7 and `x829bf3a8d9`'s B side went from 3 runs to 6.

## Two harnesses

The adapter changed after the first runs (see the caveat below), so `contrasts.json` lists
each contrast twice:
- on today's harness (`current_harness: true`), with the runs above;
- on the earlier harness (`current_harness: false`), with campaign runs plus the 7 runs from 2026-11-16:
  - C1: `1794557032`, `1794878319`, `1794878408` vs `1794812777`, `1794878187`, `1794878259`;
  - C2: `1794812777`, `1794878187`, `1794878259` vs `1794878480`, `1794878597`, `1794878721`.

Both harnesses give the same claimed facts, with one difference: on the earlier harness the
`link_remove` + PTK-rekey side logs reason 15 twice, not three times (`disconnects` 15,
15, 3). `disconnect_reasons` is the same on both.

## Across every accepted run

The pattern holds beyond the two contrasts. Across all 82 accepted runs, under both
harnesses:

| `ptk_rekey_interval_s` | `link_remove` | Runs with a reason-15 disconnect from the AP |
|---|---|---|
| 5 | yes | **20 / 20** |
| 5 | no | 0 / 11 |
| unset | yes | 3 / 32 |
| unset | no | 0 / 19 |

The other campaign runs in the first row also differ in AKM, cipher, `sae_pwe` and other
actions. So the combination fails across those settings, not just in the base above.

The 3 in the third row are `c3/`'s `link_remove` + reconnect runs (`1795480438`, `1795480449`,
`1795480460`, #107): no PTK rekey, but the client reconnects after `link_remove`, and that
association's initial handshake fails with reason 15. So what fails is a 4-way handshake
after `link_remove`, whether a PTK rekey or a reconnect starts it. Every other run with
`link_remove` and no PTK rekey runs no handshake after the removal.

## What the logs show, and what they don't

All of the following holds in each of the 3 `link_remove` + PTK-rekey runs on today's
harness. It was checked in their `explorer_candidate.hostapd` and `explorer_candidate.log5`
(the client's wpa_supplicant):

- **hostapd receives EAPOL only before `LINK_REMOVE`.** Before it, hostapd receives 2 EAPOL frames (`NL80211_CMD_CONTROL_PORT_FRAME`): the initial handshake's 2/4 and 4/4. After it, hostapd receives none for the rest of the run.
- **The rekey times out.** When the rekey timer fires, hostapd sends message 1/4 five times (`PTKSTART`). It then disconnects the client with reason 15 (`wpa_sta_disconnect ... (reason 15)`).
- **The client keeps replying.** It logs `RX message 1 of 4-Way Handshake` and `Sending EAPOL-Key 2/4` for each 1/4 it receives. Across the run it sends 2/4 17 times: once in the initial handshake (received) and 16 times after the rekey starts (none received).
- **Reassociation fails the same way.** After a reason-15 disconnect, the client reassociates on link 0. That association's initial 4-way handshake fails the same way, so the run logs three reason-15 disconnects before teardown. The last `station status` is taken during one of those handshakes (`4WAY_HANDSHAKE`).
- **The control.** With no `link_remove` (C2's other side), hostapd receives 4 EAPOL frames: the 2/4 and 4/4 of both handshakes.

The runs on the earlier harness show the same pattern, ending after two reason-15
disconnects (the client sends 2/4 12 times).

`c3/`'s `link_remove` + reconnect runs show the same pattern without a rekey: hostapd
receives no EAPOL after `LINK_REMOVE`, and the reconnect's handshake times out
(`c3/README.md`, "With `link_remove`, the reconnect fails").

So after `link_remove`, the client's EAPOL-Key frames stop reaching hostapd. The logs
don't show where they're lost (radio, kernel or hostapd), and this write-up makes no claim
about the cause. Each run folder has the radio capture (`explorer_candidate.hwsim0.pcapng`)
for whoever looks further. Whether the standard requires this combination to work is also
open: no rule in `rules.yaml` covers rekeying after a link removal, and none is proposed
here.

## Caveats

- **The adapter's association label (fixed between the two harnesses).** On the earlier harness, `docker/test_explorer_candidate.py` tracked association only through its own actions.
  - So after the AP's reason-15 disconnect, those runs' logs still say `EXPLORER-OBSERVE after PTK rekey (associated)`. The traffic check that follows expected success and logged `EXPLORER-TRAFFIC-FAILED`.
  - No record fact depends on that label: the record reads events.
  - The adapter now reads the client's `wpa_state` at each observation, for both the label and the expected traffic result (`observed_state` / `traffic_checks`, tested in `tests/test_explorer_candidate_state.py`).
  - Its not-associated traffic check covers both links, so a run lasts longer. That leaves time for a third failed handshake, hence `disconnects` 15, 15, 15, 3 instead of 15, 15, 3.
  - This is why repeats and sides must share a harness: mixed as repeats, `disconnects` would be reported as unstable.
- **Final values.** The record keeps each fact's last value (`station_status`, `valid_links`), so it shows where a run ended, not every intermediate state.
- **Distance is in the modeled inputs only.** The adapter derives hostapd parameters from the candidate (`adapter.build_plan`). One input here means one modeled setting or action step.

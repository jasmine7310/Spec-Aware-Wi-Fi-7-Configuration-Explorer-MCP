# Accepted-vs-accepted contrasts (#71)

Two legal candidates whose runs both came back `ACCEPTED` but behaved differently.
`contrasts.json` lists every contrast `explorer.contrasts.find` reports; this file writes
them up. Regenerate the JSON with `.venv/bin/python scripts/find_contrasts.py`
(`tests/test_contrasts.py` fails when it's stale).

Each contrast has a stable `id` ("x" + 10 hex digits, a hash of its two candidates and
harness, #111): it doesn't shift when contrasts are added or a side gets more repeats. A
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

Today that's 49 accepted runs in 35 groups of repeats.

`contrasts/runs/` holds the 16 runs made for this issue so that each side has 3, all
`ACCEPTED`, on Docker Desktop on macOS:
- 9 on today's harness (2026-11-17), which are the evidence below;
- 7 on the earlier harness (2026-11-16).

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

## Minimized: `c1/` (#73)

`c1/` minimizes a wider contrast: a failing campaign run 8 inputs away from the clean OWE
side (`1794812749` vs `1794557032` and its repeats). The minimizer reduces the 8 inputs
to one, `ptk_rekey_interval_s` 5 → unset, and both final sides reproduce 3/3
(`1794952238`, `1794952257`, `1794952274` vs `1794952292`, `1794952308`, `1794952325`).
The write-up and the full trace are in `c1/README.md`. Those 6 runs are in `runs/`, so
`contrasts.json` also lists the pair as a reproduced contrast (ID `x829bf3a8d9`).

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
repo's server; trial runs, not committed): `list_contrasts` gave the 5 contrasts and `c1`
(`MINIMIZED`); `get_contrast("c1")` gave the minimal change `ptk_rekey_interval_s: 5 ->
null`, the 8 probes and the 6 committed verification runs with their log lines;
`replay_contrast("c1")` came back `REPRODUCED` in 42 s, 6 guest runs, 0 cache hits, the
same facts as committed: baseline `1795545830`, `1795545836`, `1795545844` (reason 15,
from the AP) and minimal `1795545850`, `1795545857`, `1795545863` (only the local reason
3). A direct call before it (`1795545767`–`1795545802`) gave the same.

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

The pattern holds beyond the two contrasts. Across all 49 accepted runs, under both
harnesses:

| `ptk_rekey_interval_s` | `link_remove` | Runs with a reason-15 disconnect from the AP |
|---|---|---|
| 5 | yes | **17 / 17** |
| 5 | no | 0 / 11 |
| unset | yes | 0 / 14 |
| unset | no | 0 / 7 |

The other campaign runs in the first row also differ in AKM, cipher, `sae_pwe` and other
actions. So the combination fails across those settings, not just in the base above.

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

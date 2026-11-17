# Accepted-vs-accepted contrasts (#71)

Two legal candidates whose runs both came back `ACCEPTED` but behaved differently.
`contrasts.json` lists every contrast `explorer.contrasts.find` reports; this file writes
them up. Regenerate the JSON with `.venv/bin/python scripts/find_contrasts.py`
(`tests/test_contrasts.py` fails when it's stale).

**How a contrast is found** (`src/explorer/contrasts.py`):

- **Sides.** Committed adapter runs from `campaigns/` and `contrasts/runs/`. Each run must:
  - be `ACCEPTED`, so infrastructure failures (`SETUP_FAIL`, `TIMEOUT`) and refusals (`REJECTED`) are never sides;
  - not be a negative experiment;
  - still pass today's modeled rules;
  - have run on the pinned hostap and kernel commits.

  Today that's 40 runs of 32 distinct candidates. Runs of the same candidate are repeats.
- **Inputs.** Each differing config value counts as one input, and so does each action step only one side performs. The JSON lists contrasts at most 1 input apart (`--max-inputs`).
- **Facts.** Facts are the behavior record's signature without the test name, plus `disconnect_reasons`: the set of (reason, locally generated). A fact is claimed only if it is:
  - measured on both sides (never `UNKNOWN`);
  - the same in every repeat of each side;
  - different between the two sides.

  Each claimed fact comes with the log lines it was read from.
- **Reproduced** means at least 3 independent runs per side, each in a fresh guest. Cache hits don't count, and none of these runs went through the cache.

`contrasts/runs/` holds the 7 runs made for this issue (2026-11-16, Docker Desktop on
macOS), so that each side has 3 runs. They're legal `ACCEPTED` adapter runs. They aren't in
`support.EVIDENCE_DIRS`, so P2 and the planner don't count them yet.

## Shared base candidate

Both contrasts vary one input of the same base:
- **AP MLD:** OWE with CCMP on both links (link 0 on channel 1, link 1 on channel 6), with link 1 `indicate_disabled`, PMF required, beacon protection on and no GTK rekey interval.
- **Client:** OWE with beacon protection on.
- **Actions:** `associate`, optionally followed by `link_remove` (link 1, count 4).

| | `link_remove` | no `link_remove` |
|---|---|---|
| `ptk_rekey_interval_s` unset | `1794557032`, `1794878319`, `1794878408` | (not used) |
| `ptk_rekey_interval_s` 5 | `1794812777`, `1794878187`, `1794878259` | `1794878480`, `1794878597`, `1794878721` |

`1794557032` is in `campaigns/seed0-2026-11-13/` and `1794812777` in
`campaigns/seed1-fresh-2026-11-15/`; the rest are in `contrasts/runs/`.

## C1: a 5 s PTK rekey after `link_remove` (reproduced, 3 vs 3)

**Inputs that differ:** `config.ap.ptk_rekey_interval_s`, unset (A) vs 5 (B). Same
actions: `associate`, `link_remove`.

**Facts that changed**: all stable across the 3 repeats of each side.

| Fact | A: no PTK rekey | B: PTK rekey every 5 s |
|---|---|---|
| `disconnect_reasons` | {(3, local)} | {(3, local), (15, from the AP)} |
| `disconnects` | reason 3 (local, at teardown) | reason 15 from the AP twice, then reason 3 (local) |
| `station_status` (last) | `wpa_state` `COMPLETED`, `bigtk_set` 1 | `wpa_state` `4WAY_HANDSHAKE`, no `bigtk_set` |

Reason 15 is "4-way handshake timeout" (802.11 reason codes). The test result is `PASS` on
both sides. The adapter test records observations and doesn't assert them
(`src/explorer/adapter.py`), so no assertion separates the sides. The difference is in the
facts.

**Supporting log lines.** From `contrasts.json`, B side, `1794812777`'s `explorer_candidate.log`:

```
:141  wlan8: <3>CTRL-EVENT-DISCONNECTED bssid=02:00:00:00:07:00 reason=15
:202  wlan8: <3>CTRL-EVENT-DISCONNECTED bssid=02:00:00:00:07:00 reason=15
:218  wlan8: <3>CTRL-EVENT-DISCONNECTED bssid=02:00:00:00:07:00 reason=3 locally_generated=1
```

The A side (`1794557032`) logs only the teardown line (`:138`, reason 3,
`locally_generated=1`). The adapter's own lines agree, on every B run and on no A run:
- `EXPLORER-NO-EVENT PTK rekey within 10.0 s`;
- `EXPLORER-TRAFFIC-FAILED link 0: dev1->dev2 unicast data delivery failed`.

These lines aren't record facts; they're quoted here as log evidence.

**Reproduced:** yes. 3 independent runs per side: two were campaign runs on different days
and seeds, and four were run for this issue.

## C2: the same 5 s PTK rekey with and without `link_remove` (reproduced, 3 vs 3)

**Inputs that differ:** one action step. A performs `link_remove` (link 1, count 4) after
`associate`; B doesn't. Same config: `ptk_rekey_interval_s` 5.

**Facts that changed**: all stable across the 3 repeats of each side.

| Fact | A: `link_remove` | B: no `link_remove` |
|---|---|---|
| `ptk_rekeys_completed` | 0 | 1 |
| `four_way_handshakes_completed` | 1 | 2 |
| `disconnect_reasons` | {(3, local), (15, from the AP)} | {(3, local)} |
| `disconnects` | 15, 15, 3 | 3 |
| `station_status` (last) | `4WAY_HANDSHAKE`, no `bigtk_set` | `COMPLETED`, `bigtk_set` 1 |
| `valid_links` (last) | `0x1` | `0x3` |
| `link_reconfig_valid_links` | [`0x1`] | [] |

The last two follow directly from removing link 1. The others are the rekey: without
`link_remove` it completes 5 s after association (`WPA: Key negotiation completed` at
+5.0 s in `1794878480`), and the traffic check after it passes. One fact differs but isn't
claimed: traffic after the last rekey (`data_test_rx_after_last_rekey_ap_links`) is
`UNKNOWN` on A, because no rekey ever completes there.

**Supporting log lines:** the B side's are in `contrasts.json`. For A, see C1's B side
(the same runs).

**Reproduced:** yes, 3 vs 3.

## Across every accepted run

The pattern holds beyond the two contrasts. Across all 40 accepted runs:

| `ptk_rekey_interval_s` | `link_remove` | Runs with a reason-15 disconnect from the AP |
|---|---|---|
| 5 | yes | **14 / 14** |
| 5 | no | 0 / 8 |
| unset | yes | 0 / 11 |
| unset | no | 0 / 7 |

The other campaign runs in the first row also differ in AKM, cipher, `sae_pwe` and other
actions. So the combination fails across those settings, not just in the base above.

## What the logs show, and what they don't

All of the following holds in each of the 3 B runs of C1, checked in their
`explorer_candidate.hostapd` and `explorer_candidate.log5` (the client's wpa_supplicant):

- Before `LINK_REMOVE`, hostapd receives 2 EAPOL frames (`NL80211_CMD_CONTROL_PORT_FRAME`), the initial handshake's 2/4 and 4/4. After `LINK_REMOVE` it receives none for the rest of the run.
- When the rekey timer fires, hostapd sends message 1/4 five times (`PTKSTART`, retry counters 1–4 and then a final try). It then disconnects the client with reason 15 (`wpa_sta_disconnect ... (reason 15)`).
- The client logs `RX message 1 of 4-Way Handshake` and `Sending EAPOL-Key 2/4` for each 1/4 it receives. Across the run it sends 2/4 12 times: once in the initial handshake (received) and 11 times after the rekey starts (none received).
- After the first reason-15 disconnect, the client reassociates on link 0. That association's initial 4-way handshake fails the same way, which explains the second reason-15 disconnect. The last `station status` is taken during that second handshake (`4WAY_HANDSHAKE`).
- With no `link_remove` (C2's B side), hostapd receives 4 EAPOL frames: the 2/4 and 4/4 of both handshakes.

So after `link_remove`, the client's EAPOL-Key frames stop reaching hostapd. The logs
don't show where they're lost (radio, kernel or hostapd), and this write-up makes no claim
about the cause. Each run folder has the radio capture (`explorer_candidate.hwsim0.pcapng`)
for whoever looks further. Whether the standard requires this combination to work is also
open: no rule in `rules.yaml` covers rekeying after a link removal, and none is proposed
here.

## Caveats

- **The adapter's association label (fixed after these runs).** When these runs were made, `docker/test_explorer_candidate.py` tracked association only through its own actions. So after the AP's reason-15 disconnect, their logs still say `EXPLORER-OBSERVE after PTK rekey (associated)`, and the traffic check that follows expected success and logged `EXPLORER-TRAFFIC-FAILED`. No record fact depends on that label: the record reads events. The adapter now reads the client's `wpa_state` at each observation, for both the label and the expected traffic result (`observed_state` / `traffic_checks`, tested in `tests/test_explorer_candidate_state.py`).
  - **Checked** in trial run `1794885303` (2026-11-16, not committed): it logs `(not associated: wpa_state=4WAY_HANDSHAKE, no disconnect requested by the adapter)` and no `EXPLORER-TRAFFIC-FAILED`.
  - **Side effect:** its not-associated traffic check covers both links, so that run lasted about 5 s longer and had one more failed handshake: `disconnects` lists reason 15 three times instead of twice. Every other fact matched `1794878187`, including `disconnect_reasons`. So runs of this candidate from before and after the fix agree on `disconnect_reasons` but not on the exact `disconnects`. Mixed as repeats, `disconnects` would be reported as unstable and claim nothing.
  - **Cache:** the change gives a new harness hash, so earlier runs are cache misses.
- **Final values.** The record keeps each fact's last value (`station_status`, `valid_links`), so it shows where a run ended, not every intermediate state.
- **Distance is in the modeled inputs only.** The adapter derives hostapd parameters from the candidate (`adapter.build_plan`). One input here means one modeled setting or action step.

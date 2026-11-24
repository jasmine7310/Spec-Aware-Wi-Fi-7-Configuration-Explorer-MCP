# c1: a minimized contrast (#73)

**Label: `MINIMIZED`.** Of the 8 inputs that differ between a failing campaign run and
a clean run, one change removes the failure: **`ptk_rekey_interval_s` 5 → unset**.
Both final sides reproduced 3/3 in fresh guests.

`reduction.json` holds everything below: the contrast, the deltas, every probe (the
reduction trace) and the reproduction. It was written by `scripts/minimize_contrast.py`
(`minimize`, then `verify`) on 2026-11-17, on today's harness, with Docker Desktop on
macOS. `tests/test_minimize.py` re-reads the committed runs and checks they match it.

c1 is the issue's folder name. It isn't the C1 of `contrasts/README.md`, though both
point at the 5 s PTK rekey.

## The contrast

| | A: the failing side | B: the clean side |
|---|---|---|
| Runs | `1794812749` (`campaigns/seed1-fresh-2026-11-15/`) | `1794557032` (`campaigns/seed0-2026-11-13/`), `1794878319`, `1794878408` (`contrasts/runs/`) |
| AKM (both links, client) | SAE-EXT-KEY | OWE |
| `sae_pwe` (AP, client) | `hash_to_element`, `both` | unset |
| PTK / GTK rekey interval | 5 s / 5 s | unset / unset |
| Link 1 `indicate_disabled` | no | yes |
| Actions | `associate`, `link_remove` (link 1, count 4) | the same |
| `disconnect_reasons` | {(15, from the AP)} | {(3, local)} |

Both sides are P2 `SUPPORTED`, and both ran under the earlier harness. The contrast
claims 8 facts; the target is B's `disconnect_reasons` only. That's a behavior fact,
stable across harnesses. `station_status` would also have forced the AKM changes, because
it repeats the negotiated AKM (see `minimize.py`, "Choosing the target").

## The reduction

8 typed deltas, each a whole change from A towards B (the actions are the same, so they
give none):

| ID | Delta |
|---|---|
| 0 | `config.ap.gtk_rekey_interval_s`: 5 → null |
| 1 | `config.ap.links[0].akms`: SAE-EXT-KEY → OWE |
| 2 | `config.ap.links[1].akms`: SAE-EXT-KEY → OWE |
| 3 | `config.ap.links[1].indicate_disabled`: false → true |
| **4** | **`config.ap.ptk_rekey_interval_s`: 5 → null** |
| 5 | `config.ap.sae_pwe`: hash_to_element → null |
| 6 | `config.sta.akms`: SAE-EXT-KEY → OWE |
| 7 | `config.sta.sae_pwe`: both → null |

**Cost.** 8 probes: 4 guest runs (runs in `probes/`), no cache hits, about 75 s.

| # | Picire step | Deltas applied | Status | Why / run | `disconnect_reasons` |
|---|---|---|---|---|---|
| 0 | target | all (= B) | `INTERESTING` | `1794952148` | {(3, local)} |
| 1 | baseline | none (= A) | `NOT_INTERESTING` | `1794952168` | {(15, from the AP)} |
| 2 | r0 / s0 | 0–3 | `INVALID` (P1) | `SEC.MLD_CLIENT_COMMON_AKM`, `SEC.SAE_PWE_NEEDS_SAE` | not run |
| 3 | r0 / s1 | 4–7 | `INVALID` (P1) | `SEC.MLD_CLIENT_COMMON_AKM` | not run |
| 4 | r1 / s0 | 0, 1 | `INVALID` (P1) | `SEC.MLD_COMMON_SUITES`, `SEC.MLD_SAME_RSNXE` | not run |
| 5 | r1 / s1 | 2, 3 | `INVALID` (P1) | `SEC.MLD_COMMON_SUITES`, `SEC.MLD_SAME_RSNXE` | not run |
| 6 | r1 / s2 | 4, 5 | `INTERESTING` | `1794952184` (support probe) | {(3, local)} |
| 7 | r2 / s0 | 4 | `INTERESTING` | `1794952199` (support probe) | {(3, local)} |

- **The endpoints were rechecked.** Probes 0 and 1 re-ran B and A on today's harness. They gave the same `disconnect_reasons` as the earlier runs.
- **Half the probes never booted.** The 4 `INVALID` probes split the AKM changes across links and the client, which the modeled rules forbid. That's Jasmine's point on #101: grouping changes that must move together would skip such probes on bigger pairs.
- **No delta is there only for legality.** `needed_for_validity` is empty: the minimal set is the single delta 4.
- **P2 at the time:** the minimal candidate was `UNRESOLVED`, so it ran as a support probe (every value had evidence). Its reproduction runs below now make it `SUPPORTED`.

## Reproduction: 3/3 per side

Each final side ran 3 more times in fresh guests (`force`, never a cache hit). The runs
are in `contrasts/runs/`, so they're P2 evidence and contrast sides.

| Side | Runs | `disconnect_reasons` | As expected |
|---|---|---|---|
| A as it was | `1794952238`, `1794952257`, `1794952274` | {(15, from the AP)} in each | 3/3 differ from the target |
| A with `ptk_rekey_interval_s` unset | `1794952292`, `1794952308`, `1794952325` | {(3, local)} in each | 3/3 match the target |

**Supporting log lines** (`explorer_candidate.log`):
- In `1794952238`: `:171`, `:231`, `:273`, `:290`, `:356`, each `CTRL-EVENT-DISCONNECTED bssid=02:00:00:00:07:00 reason=15`.
- In `1794952292`: only `:233`, `CTRL-EVENT-DISCONNECTED bssid=02:00:00:00:07:00 reason=3 locally_generated=1` (the teardown).

The two sides are one input apart, so `contrasts.find` also lists them as a reproduced
contrast in `contrasts.json`. It claims more facts there than the target: GTK rekeys,
link state, traffic after the last rekey and `station_status` differ too.

## What this shows, and what it doesn't

- **Among these 8 inputs**, the 5 s PTK rekey is the one whose removal removes the reason-15 disconnects, for this candidate (SAE-EXT-KEY, 5 s GTK rekeys, `link_remove`). It's 1-minimal: removing the one delta brings the failure back (the baseline).
- **`link_remove` wasn't tested here:** both sides perform it. `contrasts/README.md`'s C2 and its table across every accepted run (20/20; without the rekey, only `c3/`'s 3 reconnects after `link_remove` fail, #107) show the failure also needs `link_remove`.
- **The cause isn't shown.** The logs don't say why the rekey fails after `link_remove` (`contrasts/README.md`, "What the logs show"). No claim is made about that, or about what the standard requires.
- **Single-run probes.** Each probe is one run, so a noisy fact could steer a reduction. The 3/3 reproduction of both final sides is what makes the result count.

## Reproduce

```bash
.venv/bin/python scripts/minimize_contrast.py minimize --a 1794812749 --b 1794557032 \
    --facts disconnect_reasons --out contrasts/c1
.venv/bin/python scripts/minimize_contrast.py verify --out contrasts/c1
```

Rerunning `minimize` serves probes from the cache where their key matches (same
candidate, plan, commits, environment, model and harness). `verify` always boots fresh
guests.

# Checkpoint 2 demo

How to run the explorer for the Checkpoint 2 demo (end of Week 4, a 20-minute meeting). As
for Checkpoint 1 ([`demo.md`](demo.md)), the demo runs in a **Claude Code session that
talks to our MCP server**, with a terminal for the files and scripts that aren't MCP.
Every expected result below was checked against `main` at `75582b3` on 2026-11-19, in WSL
with Docker Desktop on Windows.

What it shows, against the roadmap's Week 4 goals and Checkpoint 2 list:

| Checkpoint 2 item | Step |
|---|---|
| End-to-end stage counts (P0 → P1 → P2 → P3) | 2, 3 |
| Legal feasible-pair coverage | 3 |
| Rule source and violation explanations ("why is this candidate pruned?") | 4 |
| Permitted alternatives | 5 |
| ≥2 accepted-vs-accepted contrasts with different behavior | 6 |
| Picire over typed changes, with the Wi-Fi interestingness wrapper ("minimize this accepted contrast") | 7 |
| A minimized contrast, reproduced 3/3 per side | 8 |
| Exact logs and assertions | 8, 9 |
| Updated four-anchor coverage matrix | 10 |
| Mentor feedback: spec coverage, and spec / rules / runs kept consistent | 11 |
| MCP transcript | Part 4 |

## Part 1: One-time setup

1. **Docker Desktop** running, with *Settings → Resources → WSL Integration* on for
   **Ubuntu** (Windows), or Docker Desktop on an Intel Mac.
2. **Rebuild the simulation image.** The adapter test changed in Week 4 (#99), and
   `run_candidate` and `minimize_contrast` refuse an image older than the repo's harness.
   From the repo in WSL:

   ```bash
   git checkout main && git pull && scripts/build-env.sh
   ```

   It ends with `smoke test: eht_mld_sae_two_links PASS`.
3. **Open Claude Code on the repo.** The simplest way is a terminal in WSL:

   ```bash
   cd ~/Spec-Aware-Wi-Fi-7-Configuration-Explorer-MCP && claude
   ```

   (Claude Code on the Windows side also works; it needs `WIFI7_MCP_LAUNCHER=wsl.exe`, see
   [`demo.md`](demo.md), Part 1.) Ask *"List the wifi7-explorer MCP tools"*. You should see
   12: `get_model`, `validate_candidate`, `explain_rule`, `run_hwsim_test`, `run_candidate`,
   `plan_campaign`, `run_campaign`, `list_campaigns`, `get_campaign`, `why_pruned`,
   `permitted_alternatives` and `minimize_contrast`.

## Part 2: Pre-check, just before presenting

```bash
WIFI7_DOCKER_TESTS=1 WIFI7_HOSTAP_SRC=~/hostap .venv/bin/pytest -q
```

On 2026-11-19 this gave **1106 passed** in about 4 minutes. `WIFI7_HOSTAP_SRC` points at a
hostap checkout at the pinned commit (see `CLAUDE.md`). If anything fails, fix it before
presenting. A new Claude Code session is needed after any code change: the MCP server
loads the code when the session starts.

## Part 3: The demo script

Do the MCP steps in **one** Claude Code session, so the transcript is one record. The JSON
and run IDs keep the results predictable; any wording around them is fine. Nothing before
step 7 boots a guest.

### Step 1: What the explorer covers now

*"Use get_model and summarize the stages, rules and admitted dimensions."*

Expect every stage implemented, P0 to P4 and the campaign. P4's note lists the contrasts,
`why_pruned`, `permitted_alternatives` and `minimize_contrast`, and says a 3/3-reproduced
minimized contrast is #73's. **19 rules and 3 open questions**: 7 normative, 2
dependency, 1 guidance (`SEC.MLO_PASSWORD_NEEDS_WPA3`, new in Week 4) and 9 harness
(`AO.*`). **11 admitted dimensions** (Checkpoint 1 had 6).

### Step 2: End-to-end stage counts of a real campaign

*"List the campaigns, then show the pruning funnel and the rejected cases of
seed0-2026-11-13."*

Expect three committed campaigns: `seed0-2026-11-13` (12 `ACCEPTED`, 4 `REJECTED`),
`seed0-topup-2026-11-13` (4 `ACCEPTED`) and `seed1-fresh-2026-11-15` (17 `ACCEPTED`, run
over MCP). The funnel of `seed0-2026-11-13`:

- **Enumerated and P0:** 4608 assignments, all well-formed.
- **ConfigSpace / P1:** 1152 pass the modeled rules and 3456 are rejected, each by its
  rules: `SEC.SAE_PWE_NEEDS_SAE` 2560, `SEC.MLD_CLIENT_COMMON_AKM` 2304,
  `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E` 128. These add up to more than 3456, because one
  assignment can break several rules. That's 3456 guest boots avoided.
- **P2:** 1152 executable at the time (9 `SUPPORTED`, 1143 support probes).
- **Planned and run:** 16 candidates → P3 12 `ACCEPTED`, 4 `REJECTED`, in 16 guest boots.

The rejected cases list the P1 groups by rule IDs, with counts and an example, and the 4
`REJECTED` runs with hostapd's reason (`DISABLE_MLD` after `link_remove`). Those
refusals became the P2 limit `P2.DISABLE_MLD_AFTER_LINK_REMOVE` (step 3).

### Step 3: Today's funnel and legal feasible-pair coverage

*"Plan a campaign with seed 0, without running it, and report the funnel and the pair
coverage."*

Takes about 7 s and boots nothing. Expect:

- **Funnel:** 4608 → 1152 pass P1. At P2, 42 are already run (`SUPPORTED`), 822 are
  support probes and **288 are `UNSUPPORTED_IMPLEMENTATION`** (the recorded hostapd
  limit), so 864 are executable.
- **The plan is empty (0 candidates):** every executable pair has already run.
- **Pair coverage:** 261 pairs of admitted values, 11 infeasible under the modeled rules.
  **249 / 250 legal pairs and 249 / 249 runnable pairs are covered by committed runs.**
  The one legal pair that can't run is `link_remove` with `disable_enable_mld`. No
  `SPEC_UNDETERMINED` assignments, so the review queue is empty.

### Step 4: Why is this candidate pruned? (rule source and evidence)

*"Why is this candidate pruned?"*

```json
{"config": {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE-EXT-KEY"]}, {"link_id": 1, "channel": 6, "akms": ["OWE"]}]}, "sta": {"akms": ["SAE-EXT-KEY"], "beacon_protection": true}}, "actions": [{"action": "associate"}]}
```

This is the roadmap's example: the links share no AKM (the roadmap calls it
`P1.ML_AKM_INTERSECTION`; ours is `SEC.MLD_COMMON_SUITES`). Expect role `pruned` at stage P1,
with two rules:

- **`SEC.MLD_COMMON_SUITES`**: link 0 `['SAE-EXT-KEY']` and link 1 `['OWE']` share nothing.
  802.11be-2024 §12.6.2, PDF p. 411, a "shall". Experimental validation: cited runs only.
- **`SEC.MLD_SAME_RSNXE`**: SAE-EXT-KEY sets the hash-to-element bit in link 0's RSNXE, and
  link 1 sends none. Same clause. hostapd builds each link's RSNXE on its own
  (`src/ap/wpa_auth_ie.c:549-557, 601-611`). The labeled negative experiment
  `runs/experiments/1794875139` breaks it, and hostapd **accepted** it: the pruning comes
  from the standard, not from the implementation refusing.

Optionally, follow up with *"Explain SEC.MLD_COMMON_SUITES."* It shows the full registry
entry: `normative`, `reviewed`, the §12.6.2 "shall" and the WFA guide's §3.1.4.1 note as
guidance, the exceptions and the examples.

### Step 5: Show permitted alternatives

*"Show permitted alternatives for it, with up to 3 changes."*

Expect 343 candidates considered and **2 permitted**, both minimal:

1. `ap_akm` → SAE-EXT-KEY (link 1 back to SAE-EXT-KEY): **`SUPPORTED`**, already run as
   `1793897820`, `1793897968`, `1793898029` (anchor F02's runs).
2. `ap_akm` → OWE and `sta_akm` → OWE: `UNRESOLVED`, a support probe. Every value has a
   passing run, but this combination hasn't run.

Passing the modeled rules is never full 802.11be compliance; the output says so.

### Step 6: Accepted-vs-accepted contrasts (files)

Open [`contrasts/README.md`](../contrasts/README.md), or ask *"Read contrasts/contrasts.json
and summarize the contrasts on today's harness."*

`contrasts.json` lists 5 contrasts, **3 on today's harness**, each between legal,
P2-`SUPPORTED`, `ACCEPTED` sides reproduced 3 vs 3 runs, one input apart:

- **C1:** a 5 s PTK rekey with `link_remove` (`1794933558`, `1794933622`, `1794933677`) vs
  no rekey (`1794933586`, `1794933644`, `1794933694`). Reason-15 disconnects from the AP
  vs only the client's reason 3.
- **C2:** the same rekey with vs without `link_remove` (`1794933604`, `1794933660`,
  `1794933709`). Without it, the rekey completes.
- A third, also on the PTK rekey: the pair #73 verified (step 8).

No side is a spec-forbidden candidate or an infrastructure failure: sides must pass
today's rules and be `ACCEPTED`. Each claimed fact comes with the log lines it was read
from.

### Step 7: Minimize an accepted contrast (Picire through MCP)

*"Minimize the difference between runs 1794812749 and 1794557032, targeting
disconnect_reasons."*

A seed-1 campaign run (SAE-EXT-KEY, `sae_pwe` set, 5 s PTK and GTK rekeys, `link_remove`)
vs a clean OWE run: **8 typed changes**. Expect:

- `label: PENDING_VERIFICATION` and `reduction_status: MINIMIZED`.
- **The 1-minimal change is `config.ap.ptk_rekey_interval_s: 5 -> null`**, with P2
  `SUPPORTED` and nothing needed only for validity.
- Every probe is listed with its run ID. 4 probes are `INVALID` at P1
  (`SEC.MLD_CLIENT_COMMON_AKM`, `SEC.SAE_PWE_NEEDS_SAE`, `SEC.MLD_COMMON_SUITES`,
  `SEC.MLD_SAME_RSNXE`) and never boot. That's the interestingness wrapper checking the
  rules before any guest run.

Time: on the machine that recorded `docs/agent-chain-transcript.md` every runnable probe is
a cache hit (about 4 s). Elsewhere it boots up to about 6 guests (about 1.5 minutes).
`PENDING_VERIFICATION` is right: one run per probe isn't proof. Step 8 is the proof.

### Step 8: The minimized contrast, reproduced 3/3, with exact log lines

Open [`contrasts/c1/README.md`](../contrasts/c1/README.md). It's the same pair as step 7,
reduced by `scripts/minimize_contrast.py` (#73) and then verified. **Label `MINIMIZED`**:
both final sides reproduced 3 out of 3 in fresh guests.

| Side | Runs | `disconnect_reasons` |
|---|---|---|
| A as it was (baseline) | `1794952238`, `1794952257`, `1794952274` | `[[15, false]]` in all 3: 4-way handshake timeout, from the AP |
| A without the 5 s PTK rekey (minimal) | `1794952292`, `1794952308`, `1794952325` | `[[3, true]]` in all 3: the client's own disconnect at teardown |

The exact lines, in a terminal:

```bash
grep -n -E 'CTRL-EVENT-DISCONNECTED|EXPLORER-NO-EVENT|EXPLORER-OBSERVE after (PTK|GTK)' contrasts/runs/1794952238/explorer_candidate.log contrasts/runs/1794952292/explorer_candidate.log
```

Baseline `1794952238`:
- line 171: `CTRL-EVENT-DISCONNECTED ... reason=15`;
- line 186: `EXPLORER-NO-EVENT PTK rekey within 10.0 s`;
- line 188: `EXPLORER-OBSERVE after PTK rekey (not associated: wpa_state=4WAY_HANDSHAKE, ...)`.

Minimal `1794952292`:
- lines 168 and 201: `EXPLORER-OBSERVE after GTK rekey 1 / 2 (associated)`;
- line 233: `... reason=3 locally_generated=1`.

Both runs' `manifest.json` record the adapter test as `PASS`. The adapter records what it
observed and doesn't assert it, so the facts differ, not the test result.

Why it matters: after `link_remove`, the client's replies to the rekey's message 1 don't
reach hostapd, which resends it and then disconnects the client with reason 15
([`contrasts/README.md`](../contrasts/README.md)). That's the shape 802.11-2024 §12.7.6.6
(PDF 3073) describes, and nothing we read makes the candidate illegal
(`spec_coverage.csv`, the #75 rows). Where the replies are lost isn't in the logs, so no
claim is made about the cause.

### Step 9 (optional): The minimal side, live

*"Run this candidate:"*

```json
{"config": {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE-EXT-KEY"]}, {"link_id": 1, "channel": 6, "akms": ["SAE-EXT-KEY"]}], "sae_pwe": "hash_to_element", "gtk_rekey_interval_s": 5}, "sta": {"akms": ["SAE-EXT-KEY"], "sae_pwe": "both", "beacon_protection": true}}, "actions": [{"action": "associate"}, {"action": "link_remove", "link_id": 1, "count": 4}]}
```

About 20–30 s. Expect `PASSES_MODELED_RULES`, P2 `SUPPORTED` (by c1's committed runs) and
P3 **`ACCEPTED`**: only one disconnect (reason 3, local), 2 GTK rekeys, valid links `0x1`
after the removal, test `PASS`. (Run `1795128843` on 2026-11-19.) The run is a trial in
`runs/hwsim-logs/`, not committed evidence.

### Step 10: The updated four-anchor coverage matrix

In a terminal:

```bash
.venv/bin/python scripts/update_anchor_coverage.py
```

It rewrites [`anchor_coverage.csv`](../anchor_coverage.csv) unchanged and prints each
family. Each family keeps its 3 runs of its own hostap test (all `PASS` with identical
signatures). Since #77 each also lists the campaign and contrast runs with its own values,
and what they showed:

| Family | Campaign runs | Observed |
|---|---|---|
| F02 SAE-EXT-KEY association | 26 | all associated |
| F08 PTK rekey (5 s) | 31 | with `link_remove`, 0 of 20 completed a PTK rekey and 20 of 20 got reason 15; without it, 11 of 11 rekeyed |
| F09 GTK rekey (5 s) | 23 | every run had at least one GTK rekey |
| F06 link removal | 3 | all also had the 5 s PTK rekey, hence reason 15 |

### Step 11: Spec coverage and consistency (mentor feedback)

In a terminal:

```bash
.venv/bin/python scripts/check_consistency.py
```

No violation lines. Then it writes `rules/validation.json` and prints `{'broken_in_a_run': 4,
'cited_runs_only': 6, 'none': 12}`, followed by the 12 rules and open questions with no
experimental validation yet (mostly the `AO.*` harness rules). Every passing evidence run
passes today's rules or is a labeled negative experiment, and every cited run passes them.

Then show [`spec_coverage.csv`](../spec_coverage.csv): **44 rows: 23 RULE, 1 UND, 6
NO_RULE, 10 OUT_OF_SCOPE, 4 TODO**. Week 4 read the rekeying and link-reconfiguration
clauses (`NO_RULE`: read, but nothing a candidate can break) and added
`SEC.MLO_PASSWORD_NEEDS_WPA3` from the WFA guide's §3.2.

## Part 4: Save the transcript

After the session, type `/export` in Claude Code. Then save the transcript as
`docs/checkpoint2-transcript.md`, as `docs/agent-chain-transcript.md` was made: verbatim
prompts, replies and every `wifi7-explorer` call and result from the session log. Claude
Code can do the conversion: point it at the session.

## Troubleshooting

| Problem | Fix |
|---|---|
| The `wifi7-explorer` server failed to connect | Start Claude Code in WSL on the repo (Part 1, step 3). On Windows-side Claude Code, check `WIFI7_MCP_LAUNCHER` is `wsl.exe` and the app was restarted after `setx`. |
| `minimize_contrast` / `run_candidate`: "Docker isn't running" | Start Docker Desktop and wait until it's running. `minimize_contrast` checks the image even when every probe would come from the cache. |
| "the wifi7-env image is older than docker/..." | Run `scripts/build-env.sh`, then retry. |
| A tool's output doesn't match this page after pulling | Quit Claude Code and start a new session: the server loads the code at session start. |
| Step 7 takes minutes | The probes aren't in your cache yet; each new one boots a guest (about 30 s). Step 8 is the committed record either way. |
| "not a committed ACCEPTED, rule-passing run" | Check the run IDs; they must be in `campaigns/` or `contrasts/runs/`. |
| A result differs from this page | `git pull`, rerun Part 2, and update this page if the code changed on purpose. |

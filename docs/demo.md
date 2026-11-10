# Checkpoint 1 demo

How to run the explorer for the Checkpoint 1 demo. The demo runs in a **Claude Code
session that talks to our MCP server** (the checkpoint wants an MCP transcript); a
terminal covers what isn't MCP (tests, rebuild). Every expected result below was
checked against `week2-jas` on 2026-11-05.

What it shows, against `docs/plan.md`'s Checkpoint 1 list:

| Checkpoint item | Step |
|---|---|
| Rule registry with sourced rules | 1, 3 |
| P0 rejection | 2 |
| P1 rejection with a cited rule (link-AKM intersection) | 3 |
| Action-order rejection | 4 |
| `SPEC_UNDETERMINED` case | 5 |
| Real accepted run triggered through MCP; basic P2 check | 6 |
| Unit tests | Part 2 |
| Smoke-tested settings, rebuild script, baseline evidence | 8, Part 1 |
| MCP transcript | Part 4 |

## Part 1: One-time setup

1. **Docker Desktop** running, with *Settings → Resources → WSL Integration* on for
   **Ubuntu** (Windows), or Docker Desktop on an Intel Mac.
2. **Simulation image**, from the repo in WSL (seconds if it's cached):

   ```bash
   git pull && scripts/build-env.sh
   ```

   It ends with `smoke test: eht_mld_sae_two_links PASS`.
3. **Windows only: let Claude Code on Windows start the server through WSL.** Once, in
   Windows PowerShell, then fully quit and reopen the Claude desktop app:

   ```powershell
   setx WIFI7_MCP_LAUNCHER wsl.exe
   ```

   Leave it unset on Mac/Linux and when Claude Code itself runs inside WSL.
4. **Open a Claude Code session on the repo**. On Windows that's the WSL folder,
   `\\wsl.localhost\Ubuntu\home\<you>\Spec-Aware-Wi-Fi-7-Configuration-Explorer-MCP`, not a
   copy on the Windows drive (it has no Linux `.venv`, so the server can't start). Ask
   *"List the wifi7-explorer MCP tools"*: you should see `get_model`,
   `validate_candidate`, `explain_rule` and `run_hwsim_test`.

## Part 2: Pre-check, just before presenting

```bash
WIFI7_DOCKER_TESTS=1 WIFI7_HOSTAP_SRC=~/hostap .venv/bin/pytest -q
```

Everything should pass with nothing skipped (a few minutes: the unit tests take about
90 s on an Intel Mac, plus two real simulation runs). `WIFI7_HOSTAP_SRC` points at a hostap checkout at the pinned commit
(see `CLAUDE.md`). If anything fails, fix it before presenting.

## Part 3: The demo script

Do the whole demo in **one** Claude Code session, so the transcript is one record. The
JSON keeps the results predictable; any wording around it is fine as long as the
candidate is the same.

### Step 1: What the explorer covers

*"Use get_model and summarize the stages, rules and runnable tests."*

Expect P0, P1, P2 (basic) and P3 implemented and P4 not yet; 16 rules (one,
`AO.BSS_TM_NEEDS_BSS_TRANSITION`, still a draft) and 3 open questions; the six `_client_bp` tests as `PASSES_MODELED_RULES` and hostap's originals as
`SPEC_RULE_VIOLATION` (they leave the client's beacon protection off, 802.11be §12.12.9).

### Step 2: P0 malformed rejection

*"Validate this candidate:"*

```json
{"config": {"ap": {"links": [{"link_id": "0", "channel": 1, "akms": ["SAE-EXT-KEY"]}, {"link_id": 1, "channel": 6, "akms": ["SAE-EXT-KEY"]}]}, "sta": {"akms": ["SAE-EXT-KEY"]}}, "actions": [{"action": "associate"}]}
```

Expect `MALFORMED`: `P0.TYPE_ERROR: config.ap.links[0].link_id must be an integer`.

### Step 3: P1 rejection with a cited rule (link-AKM intersection)

*"Validate this candidate, then explain the rule it breaks:"*

```json
{"config": {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE"]}, {"link_id": 1, "channel": 6, "akms": ["SAE-EXT-KEY"]}]}, "sta": {"akms": ["SAE", "SAE-EXT-KEY"]}}, "actions": [{"action": "associate"}]}
```

Expect `SPEC_RULE_VIOLATION`, `SEC.MLD_COMMON_SUITES` ("AP MLD links advertise no common
AKM"), citing IEEE 802.11be-2024 §12.6.2 (PDF 411, a "shall"). `explain_rule` shows the
full entry, including the exception that the links' AKM lists may differ as long as they
share one.

### Step 4: Action-order rejection

*"Validate this candidate:"*

```json
{"config": {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE-EXT-KEY"]}, {"link_id": 1, "channel": 6, "akms": ["SAE-EXT-KEY"]}]}, "sta": {"akms": ["SAE-EXT-KEY"]}}, "actions": [{"action": "rekey_gtk_now"}, {"action": "associate"}]}
```

Expect `AO.ASSOC_REQUIRED` on `actions[0]`, with the note that an `AO.*` rule means the
sequence doesn't make sense for our experiments, not that it breaks the Wi-Fi spec.

### Step 5: An undetermined case

*"Validate this candidate:"*

```json
{"config": {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE-EXT-KEY", "WPA-PSK"]}, {"link_id": 1, "channel": 6, "akms": ["SAE-EXT-KEY", "WPA-PSK"]}]}, "sta": {"akms": ["WPA-PSK", "SAE-EXT-KEY"]}}, "actions": [{"action": "associate"}]}
```

Expect `SPEC_UNDETERMINED`, `UND.AKM_PREFERENCE`: which AKM the client picks follows the
WPA3 Specification, which we don't have (WFA guide Table 3). Neither approved nor a
violation.

### Step 6: Legal candidate, P2, and a real run through MCP

*"Validate this candidate. If P2 says it's supported, run that test."*

```json
{"config": {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE-EXT-KEY"]}, {"link_id": 1, "channel": 6, "akms": ["SAE-EXT-KEY"]}]}, "sta": {"akms": ["SAE-EXT-KEY"]}}, "actions": [{"action": "associate"}]}
```

Expect `PASSES_MODELED_RULES` (the note says it isn't full 802.11be compliance) and P2
`SUPPORTED` by `eht_mld_sae_ext_two_links_client_bp` with its committed run IDs. Claude then
calls `run_hwsim_test`, which boots a fresh simulated network (about 20–30 s): the test
passes, and the behavior record shows `key_mgmt` SAE-EXT-KEY, valid/active links `0x3`,
`bigtk_set` 1 and traffic on links 0 and 1.

### Step 7 (optional): The standards in action

*"Run eht_mld_sae_two_links."*

Refused: plain SAE (AKM 8) between Wi-Fi 7 devices breaks 802.11be §12.12.9, which requires
AKM 24 or 25. It only runs with `negative_experiment=true`, labeled as such.

### Step 8: Should-show items (files and terminal)

- **Smoke-tested settings:** `surface_candidates.csv` (`smoke_runs` column) and
  `anchor_coverage.csv` (four anchor families, each `PASS` with 3 identical-signature runs).
- **Rebuild script:** the `scripts/build-env.sh` output from Part 1.
- **Baseline evidence:** `baseline/README.md` and `runs/baseline/`. It's the *environment*
  baseline; its plain-SAE configuration is a negative experiment under §12.12.9.

## Part 4: Save the transcript

After the demo session, export its transcript (from Claude Code, or ask a Claude Code
session to export it) and save it as `docs/demo-transcript.md`, next to the report.

## Troubleshooting

| Problem | Fix |
|---|---|
| The `wifi7-explorer` server failed to connect | Open the session on the WSL repo folder, not a Windows-drive copy. On Windows, check `WIFI7_MCP_LAUNCHER` is `wsl.exe` (`echo $env:WIFI7_MCP_LAUNCHER` in PowerShell) and that the app was restarted after `setx`. |
| `run_hwsim_test`: "Docker isn't running" | Start Docker Desktop, wait until it's running, retry. |
| "image 'wifi7-env' not found" | Run `scripts/build-env.sh`. (Before the fix for #81, this also appeared falsely when Docker Desktop's Resource Saver had stopped its VM after 5 idle minutes; the check now wakes the VM first.) |
| The first `run_hwsim_test` after a break takes ~30 s longer | Docker Desktop's Resource Saver is waking its VM; expected. |
| "is not a runnable test" | Use a `_client_bp` name from `get_model`'s `runnable_tests`. |
| A result differs from this page | `git pull`, rerun Part 2, and update this page if the code has changed on purpose. |

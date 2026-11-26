# Spec-Aware Wi-Fi 7 Configuration Explorer (MCP)

CS 211 Fall 2026, Project F. An MCP server that lets an agent explore Wi-Fi 7 multi-link
(MLO) configurations of hostapd and wpa_supplicant. A candidate is checked against a typed
model (P0), against rules cited from IEEE 802.11be-2024 / 802.11-2024 and the WFA WPA3
guide (P1), and against what the implementation is known to support (P2). Only then does
it run in a fresh simulated network (P3: hostap's hwsim tests in a User-Mode Linux guest,
inside Docker). Bounded pairwise campaigns, accepted-vs-accepted contrasts and their
minimization (P4) build on top.

This page covers building it from a fresh clone and connecting an agent to it. For the
design, decisions and status see [`docs/plan.md`](docs/plan.md); for every command and
module, [`CLAUDE.md`](CLAUDE.md).

## What you need

| | macOS | Windows |
|---|---|---|
| Machine | **Intel** Mac. Apple Silicon can't run UML (x86-64 only). | x86-64 PC with WSL2 + Ubuntu |
| Docker | Docker Desktop | Docker Desktop, WSL2 backend, with *Settings → Resources → WSL Integration* on for **Ubuntu** |
| Python | 3.11 or newer | 3.11 or newer **inside Ubuntu**. On Ubuntu 22.04 `python3` is 3.10: `sudo apt install python3.11 python3.11-venv` |
| Agent | [Claude Code](https://docs.claude.com/en/docs/claude-code) (or another MCP client) | Claude Code in WSL, or the Claude desktop app (see [step 5](#5-connect-claude-code-to-the-mcp-server)) |
| Disk / memory | ~1.4 GB for the image; 3 GB+ memory for Docker | the same; see [`docker/README.md`](docker/README.md#windows-wsl2) for `.wslconfig` |

On Windows, run every command below **inside WSL Ubuntu**, not PowerShell or Git Bash.

## Setup

### 1. Clone

```bash
git clone https://github.com/jasmine7310/Spec-Aware-Wi-Fi-7-Configuration-Explorer-MCP.git
cd Spec-Aware-Wi-Fi-7-Configuration-Explorer-MCP
```

On Windows, clone into your Linux home folder (`~/`), **not** under `/mnt/c/...`: builds
are much slower across that boundary, and the MCP server needs the Linux `.venv`.

### 2. Python environment

```bash
python3 -m venv .venv            # python3.11 -m venv .venv on Ubuntu 22.04
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q              # unit tests, a few minutes; nothing boots
```

Every dependency is pinned in [`pyproject.toml`](pyproject.toml). Tests that need Docker or
a hostap checkout are skipped unless you opt in (see [Tests](#tests)).

### 3. Build the simulation image

```bash
scripts/build-env.sh
```

It checks Docker (running, x86-64, enough memory), builds the `wifi7-env` image from
hostap and a UML kernel at the commits pinned in
[`baseline/README.md`](baseline/README.md), then runs one hostap test
(`eht_mld_sae_two_links`) in a fresh guest. It should end with
`smoke test: eht_mld_sae_two_links PASS`. The first build takes about 10 min on Windows/WSL2
and up to ~45 min on an Intel Mac; later builds reuse Docker's cache.
[`docker/README.md`](docker/README.md) has the details, the `docker run` settings UML
needs and Windows troubleshooting.

### 4. Rebuild after pulling `docker/` changes

The image contains our harness files from `docker/`. After a `git pull` that changes
anything there, run `scripts/build-env.sh` again. Until you do, `run_candidate`,
`run_campaign` and `replay_contrast` refuse to run and tell you the image is stale.

### 5. Connect Claude Code to the MCP server

[`.mcp.json`](.mcp.json) declares the server `wifi7-explorer`, started over stdio as
`.venv/bin/python -m explorer.mcp_server` from the repo root. Claude Code reads it when a
session opens in this folder; approve the `wifi7-explorer` server when it asks.

- **macOS, or Claude Code running inside WSL:** open the session in the repo folder
  (`cd` into it and run `claude`). Nothing else to set.
- **Windows, Claude Code on the Windows side** (e.g. the Claude desktop app): it can't run
  the Linux `.venv/bin/python` itself. Once, in Windows PowerShell:

  ```powershell
  setx WIFI7_MCP_LAUNCHER wsl.exe
  ```

  Then fully quit and reopen the app, and open the session on the WSL folder,
  `\\wsl.localhost\Ubuntu\home\<you>\Spec-Aware-Wi-Fi-7-Configuration-Explorer-MCP`, not a
  copy on the Windows drive. `.mcp.json` then launches the server through `wsl.exe`.
  Leave `WIFI7_MCP_LAUNCHER` unset on macOS and when Claude Code runs inside WSL.

Check it: ask *"List the wifi7-explorer MCP tools."* You should see 15 tools:
`get_model`, `validate_candidate`, `explain_rule`, `why_pruned`, `permitted_alternatives`,
`run_hwsim_test`, `run_candidate`, `plan_campaign`, `run_campaign`, `list_campaigns`,
`get_campaign`, `minimize_contrast`, `list_contrasts`, `get_contrast` and
`replay_contrast`. A server started before a `git pull` doesn't show new tools: restart
Claude Code.

Other MCP clients: run `.venv/bin/python -m explorer.mcp_server` from the repo root as a
stdio server.

## Try it

Three prompts that exercise the whole pipeline. Each one boots at most a few guests.

**1. Why is a candidate rejected?** Nothing boots.

> Why is this candidate pruned? {"config": {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE-EXT-KEY"]}, {"link_id": 1, "channel": 6, "akms": ["OWE"]}]}, "sta": {"akms": ["SAE-EXT-KEY"], "beacon_protection": true}}, "actions": [{"action": "associate"}]}

Expected: `why_pruned` says `pruned` at P1 by two rules from 802.11be §12.6.2:
`SEC.MLD_COMMON_SUITES` (link 1 offers only OWE, which the client's SAE-EXT-KEY doesn't
share) and `SEC.MLD_SAME_RSNXE` (the two links' AKMs give different RSNXEs), each with its
cited clause, PDF page and strength. Asking *"show permitted alternatives"* next calls `permitted_alternatives`.
[`docs/agent-chain-transcript.md`](docs/agent-chain-transcript.md) is a recorded session of
this chain.

**2. A small campaign** (3 candidates, a minute or two).

> Plan a campaign with seed 7, budget 3 and build_on_runs false, then run it with campaign_id readme-trial.

`plan_campaign` shows the funnel (how many assignments P0, P1 and P2 pruned) and the 3
planned candidates; `run_campaign` runs them. Candidates that already ran under the same
versions come back from the experiment cache without booting. With `build_on_runs` left at
its default the plan may be empty, since the committed campaigns already cover almost every
pair.

`run_campaign` writes `campaigns/readme-trial/` and updates the repo-root
`pruning_counts.json`. A campaign is evidence only once someone reviews and commits it, and
tests that read the committed runs fail while a trial folder is there. So after a trial,
remove it:

```bash
rm -rf campaigns/readme-trial && git checkout -- pruning_counts.json
```

**3. Replay a minimized contrast** (6 guests, about a minute).

> List the contrasts, show me c1, then replay it.

`list_contrasts` → `get_contrast("c1")` → `replay_contrast("c1")`. c1 is a 5 s PTK rekey
after `link_remove` that ends in a 4-way handshake timeout (reason 15); without the rekey
the client only disconnects locally at teardown (reason 3). The replay reruns both sides 3
times in fresh guests and should come back `REPRODUCED` with `same_facts_as_committed`.
Replay runs are git-ignored trials in `runs/hwsim-logs/` and change nothing committed.
[`contrasts/README.md`](contrasts/README.md) explains c1–c3.

## Tests

```bash
.venv/bin/pytest -q                                   # unit tests; nothing boots
WIFI7_DOCKER_TESTS=1 .venv/bin/pytest -q              # also real simulation runs (Docker)
WIFI7_HOSTAP_SRC=~/hostap .venv/bin/pytest -q         # also checks against hostap's source
```

`WIFI7_HOSTAP_SRC` points at a hostap checkout at the pinned commit; [`CLAUDE.md`](CLAUDE.md#hostap-source)
shows how to clone it.

## Windows notes

- If you drive WSL from Windows PowerShell 5.1, put the commands in a script and run
  `wsl -d Ubuntu -- bash <script>`. PowerShell strips embedded double quotes from inline
  `wsl -- bash -lc '…'` commands.
- WSL2 takes its CPU and memory limits from `C:\Users\<you>\.wslconfig`, not from Docker
  Desktop's settings. [`docker/README.md`](docker/README.md#windows-wsl2) has the settings
  that worked and what to do when Docker's WSL integration gets stuck.

## Troubleshooting

| Problem | Fix |
|---|---|
| The `wifi7-explorer` server failed to connect | Check `.venv` exists in the repo (step 2). On Windows with the desktop app: open the WSL folder, not a Windows-drive copy, and check `echo $env:WIFI7_MCP_LAUNCHER` in PowerShell prints `wsl.exe` (restart the app after `setx`). |
| A tool says Docker isn't running | Start Docker Desktop, wait until it's running, retry. The first run after a break can take ~30 s longer while Docker's VM wakes. |
| "image 'wifi7-env' not found", or the image is stale | `scripts/build-env.sh` (step 3). |
| `build-env.sh`: "UML needs x86-64" | Apple Silicon can't run the simulation; use an Intel Mac or Windows + WSL2. |
| The build runs out of memory | Give Docker / WSL2 more memory or swap ([`docker/README.md`](docker/README.md#windows-wsl2)). |
| Tests fail after a trial campaign | Remove the uncommitted `campaigns/<id>/` folder and restore `pruning_counts.json` ([Try it](#try-it), step 2). |
| New MCP tools are missing | Restart Claude Code so it starts the server again. |

[`docs/demo.md`](docs/demo.md) has more troubleshooting from the Checkpoint 1 demo.

## Where things are

| Path | What |
|---|---|
| [`docs/plan.md`](docs/plan.md) | Stages P0–P4, decisions, weekly status |
| [`CLAUDE.md`](CLAUDE.md) | Every command and module; rules for coding agents |
| [`baseline/README.md`](baseline/README.md) | Pinned hostap, kernel and base-image versions |
| [`docker/`](docker/README.md) | The simulation image and `run-test.sh` |
| `src/explorer/` | The explorer; `mcp_server.py` is the MCP server |
| `rules.yaml`, `rules/fixtures/` | P1 rules and open questions (`UND.*`) with their sources and test cases |
| `model.json` | The candidate space: dimensions, values, constraints, actions |
| `spec_coverage.csv` | Every clause read and what became of it ([`docs/references.md`](docs/references.md) lists the standards) |
| [`docs/rule-audit.md`](docs/rule-audit.md), [`docs/counterexamples.md`](docs/counterexamples.md) | False-pruning / false-admission audit; counterexample suite |
| `campaigns/` | Committed campaigns (runs, plan, results, pruning funnel) |
| [`contrasts/`](contrasts/README.md) | Accepted-vs-accepted contrasts and the minimized ones (c1–c3) |
| `runs/` | Committed evidence runs by kind ([`CLAUDE.md`](CLAUDE.md) lists the folders); `runs/hwsim-logs/` holds git-ignored trials |

The standards themselves are licensed and not in the repo.

# Project plan: Weeks 1–2 (Checkpoint 1)

Shared context for the team and for coding agents. The GitHub issue board tracks
individual tasks and their status; this file holds the big picture and the decisions
behind it. Issues are referred to by name, not number.

## What we're building

An MCP server that a coding agent (Claude Code / Codex) can call to explore Wi-Fi 7
multi-link (MLO) settings. Each candidate configuration passes through filters, and
every rejection says which stage and which sourced rule rejected it:

| Stage | Component | Question it answers |
|---|---|---|
| P0 | Format checker | Is the request well formed? (types, allowed values, action syntax) |
| P1 | Rule checker | Does it break one of our audited Wi-Fi rules? (≥4 rules, each with a cited source) |
| P2 | Support checker | Does our pinned hostap/kernel version actually support it? |
| P3 | Test runner | What happens when we run it in a fresh simulated network? |
| P4 | Difference finder | Which minimal change explains a behavior difference between two accepted runs? (Weeks 3–5) |
| – | MCP server | Lets the agent use all of the above in plain English |

Weeks 1–2 cover P0, P1, basic P2/P3 and MCP. P4 and the large campaign come later.

## Repo layout

| Path | What it is |
|---|---|
| `src/explorer/` | The tool: one module per component (`model.py`, `rules.py`, `validate.py`, `runner.py`, `signatures.py`, `mcp_server.py`, …) |
| `tests/` | pytest tests for `src/` |
| `docker/` | Simulation environment: `Dockerfile`, `run-test.sh`, `README.md` |
| `baseline/README.md` | Pinned versions and the record that the environment is reproducible |
| `runs/` | Raw run evidence (logs, pcapng, manifests). Trial runs are not committed |
| `docs/` | This plan and other notes |

Data files (`rules.yaml`, `model.json`, `anchor_coverage.csv`, `surface_candidates.csv`,
`pruning_counts.json`) currently sit in `src/` as placeholders and should move to the repo
root (as in the spec's layout) when they are first filled in.

## Decisions

- **Simulation environment:** Docker + UML (User-Mode Linux) with mac80211_hwsim, running
  hostap's own `tests/hwsim` tests (`test_eht.py`, `run-tests.py`, `hostapd.py`,
  `wpasupplicant.py`, `hwsim_utils.py`). Required by the spec.
- **Versions** (in `baseline/README.md`): the spec's reference pair, hostap
  `43ee60e13c257d33d25bfb6892b9ee38fb6e88a4` and wireless-next
  `21b4248bfa0f410fa22202fc2c82f4808d672cda`, on `ubuntu:24.04`.
- **Platforms:** Intel Mac uses Docker Desktop. Windows uses WSL2 Ubuntu + Docker Desktop
  (WSL2 backend), with the repo cloned inside Ubuntu, not under `C:\`. Apple Silicon
  can't run UML natively.
- **Two layers:** everyday Python development (model, rules, MCP) runs directly on laptops
  (inside WSL on Windows). The Docker/UML environment is only where experiments execute;
  `runner.py` will launch it.
- **Required `docker run` settings** (all built into `docker/run-test.sh`, details in
  `docker/README.md`): an exec-enabled tmpfs for UML's memory, pinning to one CPU
  (`--cpuset-cpus=0`) so UML's time-travel mode doesn't hang or panic, and keeping logs
  inside the container until the run ends (SQLite hangs on a host bind mount).
- **Dependencies:** pinned exactly in `pyproject.toml`. `setuptools==80.9.0` is pinned
  because picire 21.8 imports `pkg_resources`, which newer setuptools removed.

## Week 1 status

| Issue | Status |
|---|---|
| Repo skeleton | ✅ Done, merged |
| Pick software versions + platform plan | ✅ Done, merged |
| Dev setup guide | 🟡 Everyone has the skeleton running; confirm `docker run --rm hello-world` for all |
| Build simulation environment | ✅ Done, merged. `eht_mld_sae_two_links` passes on Intel Mac (4/4) and Windows 11 + WSL2 (1/1) |
| Run one existing Wi-Fi 7 test | ✅ Done on Mac and Windows (trial runs, not committed) |
| Rebuild script | 🟡 `docker/run-test.sh` runs tests; still needs one-command build + test, run by a teammate on the other platform |
| Three clean baseline runs | ⬜ Official runs with logs, pcap and a version manifest in `runs/` (earlier runs were trials) |
| Extract a behavior record | ⬜ Needs the baseline runs |
| List candidate settings from test code | ⬜ `surface_candidates.csv`, ≥12 rows with source file and line |
| Get the standards documents | ⬜ IEEE 802.11be-2024, IEEE 802.11-2024, WFA WPA3 guidance |
| Rule research (link security match; SAE PWE / beacon protection; action order) | ⬜ |
| Pick the 4 scenario families | ⬜ Suggested: F01 SAE association, F05 beacon protection, F09 GTK (or F08 PTK) rekey, F06 link removal |
| Data model for settings / actions | ⬜ Pydantic, strict, `extra="forbid"` |
| Readable format errors, rules file + loader | ⬜ Can slide to Week 2 |

## Week 2

Code the ≥4 rules with passing/failing fixtures and unit tests; action-order checker;
`SPEC_UNDETERMINED` for unmodeled cases; runner adapter (Python starts a hostap test in a
fresh guest via `docker/run-test.sh`); smoke-test ≥4 settings with ≥2 values each; P2
support check; `validate_candidate` pipeline; MCP server with `get_model`,
`validate_candidate`, `explain_rule` and one real run; record the demo; 1-page report.

## Checkpoint 1

**Must show:** real baseline run with logs and versions; rule registry with ≥4 sourced rules
and unit tests; a P0 rejection, a P1 rejection with cited rule, an action-order rejection
and a `SPEC_UNDETERMINED` case; one real accepted run triggered through MCP; the MCP
transcript; a 1-page report.

**Should show:** 4 smoke-tested settings; a basic P2 support check; a rebuild script
working on both platforms.

**Only if genuinely encountered:** a valid-but-unsupported (P2) case. Don't invent one.

## Ground rules from the spec

- Never invent results, run IDs, hostap options or citations. Every claim needs real evidence.
- Passing our rules is **not** full 802.11be compliance; say "passes modeled rules".
- Keep spec rules (normative) separate from harness requirements and from mere recommendations.
- Read the actual hostap source at the pinned commit before writing code against it.
- Reuse existing tools (Pydantic, ConfigSpace, allpairspy, Picire, hostap tests); don't
  build a new simulator, solver or packet parser.

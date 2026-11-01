# Project plan: Weeks 1–2 (Checkpoint 1)

Shared context for the team and for coding agents. The GitHub issue board tracks
individual tasks and their status; this file holds the big picture and the decisions
behind it. Issues are referred to by name, not number.

_Status last updated 2026-10-30 from what is merged on `main`. Work that exists only on
someone's laptop or on the board isn't reflected here._

## What we're building

An MCP server that a coding agent (Claude Code / Codex) can call to explore Wi-Fi 7
multi-link (MLO) settings. Each candidate configuration passes through filters, and
every rejection says which stage and which sourced rule rejected it:

| Stage | Component | Question it answers | Status |
|---|---|---|---|
| P0 | Format checker | Is the request well formed? (types, allowed values, action syntax) | 🟡 Settings model (`model.Config`); actions model not yet |
| P1 | Rule checker | Does it break one of our audited Wi-Fi rules? (≥4 rules, each with a cited source) | ⬜ |
| P2 | Support checker | Does our pinned hostap/kernel version actually support it? | ⬜ |
| P3 | Test runner | What happens when we run it in a fresh simulated network? | ✅ `runner.run_test()` + `signatures.extract_record()` |
| P4 | Difference finder | Which minimal change explains a behavior difference between two accepted runs? (Weeks 3–5) | ⬜ |
| – | MCP server | Lets the agent use all of the above in plain English | 🟡 Skeleton with `get_model` |

Weeks 1–2 cover P0, P1, basic P2/P3 and MCP. P4 and the large campaign come later.

## Repo layout

| Path | What it is |
|---|---|
| `src/explorer/` | The tool: one module per component. Implemented so far: `model.py` (P0 settings model), `runner.py` (P3), `signatures.py` (behavior records), `mcp_server.py` (MCP skeleton). The rest are placeholders |
| `tests/` | pytest tests for `src/` (`WIFI7_DOCKER_TESTS=1` also runs a real simulation test) |
| `docker/` | Simulation environment: `Dockerfile`, `run-test.sh`, `README.md` |
| `scripts/build-env.sh` | One command: build the simulation image + smoke test (`--fresh` ignores the cache) |
| `.mcp.json` | Registers the MCP server (`wifi7-explorer`) for Claude Code |
| `baseline/README.md` | Pinned versions and the baseline runs that show the environment is reproducible |
| `runs/baseline/` | The three official baseline runs (committed evidence) |
| `runs/calibration/` | Runs used to calibrate how `signatures.py` detects a behavior (committed evidence, not baseline) |
| `runs/hwsim-logs/` | Trial runs (git-ignored; the default for `run-test.sh` and `run_test()`) |
| `docs/` | This plan and other notes |
| `surface_candidates.csv` | Candidate settings, actions and observations found in hostap's tests, each with source lines (`tests/test_surface_candidates.py` checks it; set `WIFI7_HOSTAP_SRC` to also check the lines exist) |

The other data files (`rules.yaml`, `model.json`, `anchor_coverage.csv`,
`pruning_counts.json`) still sit in `src/` as placeholders and should move to the repo
root (as in the spec's layout) when they are first filled in.

## Decisions

- **Simulation environment:** Docker + UML (User-Mode Linux) with mac80211_hwsim, running
  hostap's own `tests/hwsim` tests (`test_eht.py`, `run-tests.py`, `hostapd.py`,
  `wpasupplicant.py`, `hwsim_utils.py`). Required by the spec.
- **Versions** (in `baseline/README.md`, read by `get_model` from `docker/Dockerfile`): the
  spec's reference pair, hostap `43ee60e13c257d33d25bfb6892b9ee38fb6e88a4` and
  wireless-next `21b4248bfa0f410fa22202fc2c82f4808d672cda`, on
  `ubuntu:24.04@sha256:24737cef…` (pinned by digest because the tag moves).
- **Platforms:** Intel Mac uses Docker Desktop. Windows uses WSL2 Ubuntu + Docker Desktop
  (WSL2 backend), with the repo cloned inside Ubuntu, not under `C:\`. Apple Silicon
  can't run UML natively.
- **Two layers:** everyday Python development (model, rules, MCP) runs directly on laptops
  (inside WSL on Windows). The Docker/UML environment is only where experiments execute;
  `runner.run_test()` launches it through `docker/run-test.sh`.
- **Required `docker run` settings** (all built into `docker/run-test.sh`, details in
  `docker/README.md`): an exec-enabled tmpfs for UML's memory, pinning to one CPU
  (`--cpuset-cpus=0`) so UML's time-travel mode doesn't hang or panic, and keeping logs
  inside the container until the run ends (SQLite hangs on a host bind mount).
- **Run outcomes:** `run_test()` returns `COMPLETED` (hostap's PASS/FAIL is in the
  record), `SETUP_FAIL` or `TIMEOUT`; environment problems raise `RunnerError`. Mapping
  these onto the spec's ACCEPTED/REJECTED is left to the candidate-to-test layer.
- **Behavior facts:** every fact comes from a specific log line or file; missing evidence
  is `UNKNOWN`, never guessed. A fact is only detected after it has been calibrated
  against real runs (kept in `runs/calibration/`). ML probe and BTM are not calibrated yet.
- **MCP SDK:** `mcp==2.3.0`. `FastMCP` was removed in v2; use
  `from mcp.server.mcpserver import MCPServer`. Most online examples are v1 and won't import.
- **Dependencies:** pinned exactly in `pyproject.toml`. `setuptools==80.9.0` is pinned
  because picire 21.8 imports `pkg_resources`, which newer setuptools removed.

## Week 1 status

| Issue | Status |
|---|---|
| Repo skeleton | ✅ Done |
| Pick software versions + platform plan | ✅ Done |
| Dev setup guide | ✅ Done. Setup works for all three teammates |
| Build simulation environment | ✅ Done. `eht_mld_sae_two_links` passes on Intel Mac and Windows 11 + WSL2 |
| Run one existing Wi-Fi 7 test | ✅ Done on Mac and Windows |
| Rebuild script | ✅ Done. `scripts/build-env.sh` passes on Intel Mac and, with `--fresh` from a clean clone, on Windows 11 + WSL2 |
| Three clean baseline runs | ✅ Done. 3/3 PASS in `runs/baseline/`, with manifests |
| Extract a behavior record | ✅ Done. `signatures.py`; the three baseline signatures are identical |
| List candidate settings from test code | ✅ `surface_candidates.csv`: 34 candidates (17 settings, 10 actions, 7 observations) from `test_eht.py` / `hostapd.py` at the pinned commit. Candidates only; admitting a dimension needs the settings smoke test |
| Get the standards documents | 🟡 Michelle has IEEE Std 802.11be-2024, IEEE Std 802.11-2024 (IEEE Xplore) and the WFA "WPA3 and Wi-Fi Enhanced Open Deployment and Implementation Guide" v1.1 (Feb 2025). Still to do: `docs/references.md`, and copies for the teammates who review research. Don't commit the PDFs |
| Rule research: action order | ✅ `docs/research/action-order.md`: 8 rules (harness/code prerequisites, not spec rules), each with sources, who enforces it, and allowed/disallowed examples |
| Rule research: link security match; SAE PWE / beacon protection | 🟡 Draft in `docs/research/security-guidance.md`: 5 findings (link suites, beacon protection, PMF, SAE AKM, SAE H2E), each citing 802.11be-2024 / 802.11-2024 and the WFA guide. IEEE citations checked against the PDFs; **the WFA rows (and a few hostap lines) still need a teammate's review** before merging. **Team decision needed:** 802.11be §12.12.9 requires AKM 24/25 for SAE between EHT devices, so the plain-SAE baseline test (`eht_mld_sae_two_links`) wouldn't pass the modeled rules |
| Pick the 4 scenario families | ⬜ Nothing on `main` yet. Suggested: F01 SAE association, F05 beacon protection, F09 GTK (or F08 PTK) rekey, F06 link removal |
| Data model for settings | ✅ `model.Config` (AP MLD with per-link AKMs + client), strict, `extra="forbid"`; values limited to those hostap's tests use. Wi-Fi rules are left to P1 |
| Data model for actions | ⬜ Needs the settings model and a decision on the open questions in `docs/research/action-order.md` |
| Readable format errors, rules file + loader | ⬜ Can slide to Week 2 |

## Week 2 status

| Issue | Area | Status |
|---|---|---|
| Runner adapter | Simulation | ✅ Done. `runner.run_test()` |
| Calibrate rekey facts | Simulation | ✅ Done. PTK/GTK rekey counts + traffic after the last rekey, from runs in `runs/calibration/` |
| MCP server skeleton | MCP | ✅ Done. `get_model`, `.mcp.json`; verified in a Claude Code session |
| Smoke-test 4 settings | Simulation | ⬜ Unblocked (candidate list done). Per the roadmap: ≥4 executable config/action dimensions, each with ≥2 verified choices. The security research narrows the choices: beacon protection and PMF look like fixed settings, not dimensions |
| Support check (P2) | Simulation | ⬜ Waits on the settings smoke test |
| Code rule: security type matches on every link | Research | ⬜ Waits on its rule research, data model, rules file + loader |
| Code rules: setting dependencies | Research | ⬜ Waits on their rule research, data model, rules file + loader |
| Action-order checker | Research | ⬜ Waits on the action data model (research done: `docs/research/action-order.md`) |
| Undetermined result (`SPEC_UNDETERMINED`) | Research | ⬜ Waits on rules file + loader |
| `validate_candidate` pipeline | Data models | ⬜ Waits on all checks above |
| Expose checks and runs over MCP | MCP | ⬜ Waits on the pipeline (runner and MCP skeleton are ready) |
| Record the demo | MCP | ⬜ Last |
| Write the 1-page report | MCP | ⬜ Last |

**Main blockers:** the rules file + loader (the coded rules and `SPEC_UNDETERMINED` wait on
it) and a teammate review of `docs/research/security-guidance.md`. The candidate settings
list is done, so the settings smoke test can start.

## Checkpoint 1

**Must show:** real baseline run with logs and versions (✅); rule registry with ≥4 sourced
rules and unit tests; a P0 rejection, a P1 rejection with cited rule, an action-order
rejection and a `SPEC_UNDETERMINED` case; one real accepted run triggered through MCP; the
MCP transcript; a 1-page report.

**Should show:** 4 smoke-tested settings; a basic P2 support check; a rebuild script
working on both platforms.

**Only if genuinely encountered:** a valid-but-unsupported (P2) case. Don't invent one.

## Reviewing research

Research files (`surface_candidates.csv`, `docs/research/*.md`) should be checked by a
second teammate before their pull request is merged, ideally with their own coding agent
reading the source fresh rather than re-reading the doc. Paste this into Claude Code (or
Codex) in the repo, filling in the file:

> Review `<research file>` against its sources. If you don't have hostap at the pinned
> commit, clone it per `CLAUDE.md`. For every claim that cites a hostap line, open that
> line and check (1) it says what the file claims, (2) any "enforced by" / "who enforces
> it" label is right, and (3) any allowed/disallowed examples actually follow from the
> rule. For standards citations, check the document, version and section. Report each
> claim whose evidence doesn't match, with the line you looked at; don't fix anything yet.

Leave the result as a comment on the pull request, then fix any mismatches before merging.

## Ground rules from the spec

- Never invent results, run IDs, hostap options or citations. Every claim needs real evidence.
- Passing our rules is **not** full 802.11be compliance; say "passes modeled rules".
- Keep spec rules (normative) separate from harness requirements and from mere recommendations.
- Read the actual hostap source at the pinned commit before writing code against it.
- Reuse existing tools (Pydantic, ConfigSpace, allpairspy, Picire, hostap tests); don't
  build a new simulator, solver or packet parser.

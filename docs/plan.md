# Project plan: Weeks 1–2 (Checkpoint 1)

Shared context for the team and for coding agents. The GitHub issue board tracks
individual tasks; this file holds the big picture and the decisions behind it.

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
| — | MCP server | Lets the agent use all of the above in plain English |

Weeks 1–2 cover P0, P1, basic P2/P3 and MCP. P4 and the large campaign come later.

## Decisions

- **Simulation environment:** Docker + UML (User-Mode Linux) with mac80211_hwsim, running
  hostap's own `tests/hwsim` tests (`test_eht.py`, `run-tests.py`, `hostapd.py`,
  `wpasupplicant.py`, `hwsim_utils.py`). Required by the spec.
- **Platforms:** Windows uses WSL2 Ubuntu + Docker Desktop (WSL2 backend), with the repo
  cloned inside Ubuntu, not under `C:\`. Intel Macs use Docker Desktop. Apple Silicon
  can't run UML natively.
- **Two layers:** everyday Python development (model, rules, MCP) runs directly on laptops
  (inside WSL on Windows). The Docker/UML environment is only where experiments execute;
  `runner.py` launches it.
- **Container flags to try first:** `--privileged --shm-size=2g` (untested; record what works).
- **Versions:** pin hostap and kernel commits in `baseline/README.md`. The spec's reference
  pair (hostap `43ee60e13c257d33d25bfb6892b9ee38fb6e88a4`, wireless-next
  `21b4248bfa0f410fa22202fc2c82f4808d672cda`) is an acceptable default.
- **Day-3 fallback:** if UML + hwsim isn't booting by day 3, switch the same day to
  (a) UML directly in WSL2 without Docker, or (b) one shared x86-64 Linux machine
  (lab server or cloud VM). Also ask the mentor whether "Docker/UML" means both or either.

## Week 1 issues

| # | Issue | Done when | Needs | Day |
|---|---|---|---|---|
| 1 | Repo skeleton | A teammate clones, installs and runs `pytest` successfully | – | 1 |
| 2 | Pick software versions + platform plan | `baseline/README.md` has versions and the plan | – | 1 |
| 3 | Dev setup guide | Every teammate has Docker working and `pytest` passing | – | 1 |
| 4 | Build simulation environment (2-day trial) | UML + hwsim boots and the test runner starts on one Windows machine and one Mac | 2, 3 | 3 |
| 5 | Run one existing Wi-Fi 7 test | A multi-link association test from `test_eht.py` passes, output saved | 4 | 4 |
| 6 | Rebuild script | A teammate on the other platform rebuilds and runs it with one command | 4 | 5 |
| 7 | Three clean baseline runs | 3 folders in `runs/` with logs, pcap and a version manifest | 5 | 4–5 |
| 8 | Extract a behavior record | Connected / active links / rekey facts parsed from baseline runs; UNKNOWN when missing | 7 | 5–6 |
| 9 | List candidate settings from test code | `surface_candidates.csv` has ≥12 rows with source file and line | – | 2 |
| 10 | Get the standard + guidance documents | IEEE 802.11be-2024 and WFA WPA3 guide linked with versions | – | 1 |
| 11 | Research rule: security type must match on every link | Source section, summary and exceptions written up | 10 | 3 |
| 12 | Research rules: SAE PWE only for SAE; beacon protection needs PMF | Each labeled confirmed / unclear / not a rule, with source | 10 | 3 |
| 13 | Research rule: action order (no rekey/remove before connecting) | Written up as harness requirements with test-code references | 9 | 3 |
| 14 | Pick the 4 scenario families | `anchor_coverage.csv` has 4 rows (e.g. F01, F04, F09, F06) | 9 | 3 |
| 15 | Data model for settings | Valid example loads; wrong type errors (Pydantic strict mode) | 1, 9 | 3–4 |
| 16 | Data model for actions | Valid action list loads; bad link ID rejected | 15 | 4 |
| 17 | Readable format errors *(can slide)* | ≥3 bad inputs give messages like `P0.TYPE_ERROR: …` | 16 | 5 |
| 18 | Rules file and loader *(can slide)* | `rules.yaml` loads and its tests pass | 1 | 5 |

Critical path: 3 → 4 → 5 → 7 → 8.

## Week 2 (to be numbered from #19)

Code the ≥4 rules with passing/failing fixtures and unit tests; action-order checker;
`SPEC_UNDETERMINED` for unmodeled cases; runner adapter (Python starts a hostap test in a
fresh guest); smoke-test ≥4 settings with ≥2 values each; P2 support check;
`validate_candidate` pipeline; MCP server with `get_model`, `validate_candidate`,
`explain_rule` and one real run; record the demo; 1-page report.

## Checkpoint 1 (end of day 9)

**Must show:** real baseline run with logs and versions; rule registry with ≥4 sourced rules
and unit tests; a P0 rejection, a P1 rejection with cited rule, an action-order rejection
and a `SPEC_UNDETERMINED` case; one real accepted run triggered through MCP; the MCP
transcript; a 1-page report.

**Should show:** 4 smoke-tested settings; a basic P2 support check; a rebuild script
working on both platforms.

**Only if genuinely encountered:** a valid-but-unsupported (P2) case. Don't invent one.

## Ground rules from the spec

- Never invent results, run IDs or citations. Every claim needs real evidence.
- Passing our rules is **not** full 802.11be compliance; say "passes modeled rules".
- Keep spec rules (normative) separate from harness requirements and from mere recommendations.
- Show coding agents the actual hostap checkout before they write code against it.
- Reuse existing tools (Pydantic, ConfigSpace, allpairspy, Picire, hostap tests); don't
  build a new simulator, solver or packet parser.

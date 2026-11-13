# CS 211 Project F: Spec-Aware Wi-Fi 7 Configuration Explorer (MCP)

**Read [`docs/plan.md`](docs/plan.md) first.** It has what we're building (P0–P4 stages),
the decisions made so far, current status and the spec's ground rules.

## Sources of truth

- **Project spec:** the CS 211 Fall 2026 Project F roadmap on Notion:
  https://app.notion.com/p/CS-211-Fall-2026-Project-F-Roadmap-Spec-Aware-Wi-Fi-7-Configuration-Explorer-MCP-40003bb3e77681a0a338c5208f14bf51
  If you can't open it, ask the user to paste the relevant section. Don't guess requirements.
- **Pinned versions:** [`baseline/README.md`](baseline/README.md).
- **Task details:** the GitHub issue the user is working on.

## hostap source

Code that touches hostap (settings, actions, test names, helper functions) must match
the **pinned commit**, not memory of upstream hostap. Read the real source before writing
against it. If there is no local copy yet, clone it next to this repo:

```bash
git clone https://w1.fi/hostap.git ../hostap
git -C ../hostap checkout 43ee60e13c257d33d25bfb6892b9ee38fb6e88a4
```

The tests live in `../hostap/tests/hwsim/` (`test_eht.py`, `hostapd.py`,
`wpasupplicant.py`, `hwsim_utils.py`).

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup
.venv/bin/pytest                                             # unit tests
WIFI7_DOCKER_TESTS=1 .venv/bin/pytest                        # also run a real simulation test
scripts/build-env.sh                                         # build simulation image + smoke test
docker build --progress=plain -t wifi7-env docker/           # simulation image only (slow first time)
docker/run-test.sh eht_mld_sae_two_links                     # one hwsim test in a fresh UML guest
docker/run-test.sh eht_mld_sae_ext_two_links_client_bp       # our wrapper: client beacon protection on
.venv/bin/python -m explorer.mcp_server                      # MCP server over stdio
```

Claude Code starts the MCP server itself from `.mcp.json` (server name `wifi7-explorer`)
when a session opens in this repo; it needs the `.venv` above to exist. On Windows, if
Claude Code runs on the Windows side (e.g. the desktop app opening the repo's
`\\wsl.localhost\...` folder), it can't run the Linux `.venv/bin/python` directly: run
`setx WIFI7_MCP_LAUNCHER wsl.exe` once in PowerShell and restart Claude Code, so
`.mcp.json` launches the server through WSL. Leave it unset on Mac/Linux and when Claude
Code itself runs inside WSL.

The project needs Python 3.11+. On Ubuntu 22.04 `python3` is 3.10, so create the venv
with `python3.11` instead (`sudo apt install python3.11 python3.11-venv`).

On Windows, run everything inside WSL Ubuntu. See `docker/README.md` for the simulation
environment, the `docker run` settings it needs and Windows troubleshooting. If you drive
WSL from Windows PowerShell 5.1, put the commands in a script and run
`wsl -d Ubuntu -- bash <script>`: PowerShell strips embedded double quotes from inline
`wsl -- bash -lc '…'` commands.

## What already exists (build on it, don't re-create it)

- `explorer.runner.run_test(test)`: runs one hostap hwsim test in a fresh UML guest and
  returns a `RunResult` (`COMPLETED` / `SETUP_FAIL` / `TIMEOUT`) with its behavior record.
- `explorer.signatures.extract_record(run_dir)`: turns a run folder into a `BehaviorRecord`;
  `.signature()` gives the comparable facts.
- `explorer.mcp_server`: `MCPServer` with `get_model`, `validate_candidate`, `explain_rule`,
  `run_hwsim_test` and `run_candidate`. Add new tools
  here with `@server.tool()`; raise `ToolError` for expected failures (any other exception
  reaches the agent only as "Error executing tool").
- `explorer.model.Config`: P0 settings model; `explorer.model.Candidate`: a `Config` plus
  ordered typed actions; `model.SCHEMA_VERSION` goes up when the P0 schema changes.
  `explorer.rules.load_rules()`: the P1 rule registry from
  `rules.yaml` (rules plus `UND.*` open questions). `explorer.validate`: `parse_candidate`
  (readable `P0.*` errors), `P1_CHECKS` / `run_p1_checks(config)` (coded rule checks by
  rule ID), `find_undetermined(config)`, `check_action_order(candidate)` (AO.* rules), all
  returning `Finding`s with an outcome; `p1_status` sums them up; `validate_candidate(data)`
  chains P0, P1 and P2 for raw input and explains each finding from `rules.yaml`.
- `explorer.scenarios`: `TEST_CONFIGS` (the `Config` each runnable hostap test sets up) and
  `TEST_CANDIDATES` (config plus its actions), read from the tests' source lines.
- `explorer.adapter`: `build_plan(candidate)` (hostapd parameters, client connect arguments
  and actions for `docker/test_explorer_candidate.py`), `run_candidate(candidate)` (fresh
  guest, P3 status `ACCEPTED` / `REJECTED` / `SETUP_FAIL` / `TIMEOUT`), `unsupported()`,
  `compare_signatures()`. MCP tool `run_candidate` validates first. Changing the adapter
  test means rebuilding the image.
- `model.json` (repo root): the machine-readable candidate space (P0 schema, admitted
  dimensions with typed values and smoke runs, constraints by rule ID, actions, pinned
  versions, `model_digest`), built by `explorer.model_json.build()`. Regenerate it with
  `.venv/bin/python scripts/build_model_json.py` after changing the model, `rules.yaml`,
  `surface_candidates.csv`'s `smoke_runs` or the adapter's actions; a test fails until you
  do. `model_json.apply({dimension: label})` turns choices into a candidate.
- `explorer.planner`: the pairwise campaign planner (#66). `Space()` enumerates the candidate
  space from `model.json` and assesses each assignment with P0, P1 and P2; `plan(seed,
  budget)` builds the allpairspy design (exact legal-completion filter, then a coverage
  top-up) over executable candidates; `coverage(space, plan_rows, ran_rows)` counts pairs
  with both denominators, covered only by real runs. `scripts/plan_campaign.py --seed N`
  writes `campaign_plan.json` and `pairwise_coverage.json`; a test fails if the committed
  plan no longer matches its seed and the current model.
- `explorer.support.check_support(candidate)`: the P2 check (rules decided in #80).
  `SUPPORTED` for an exact match to a tested scenario, or to a committed legal adapter run
  on the pinned commits; otherwise `UNRESOLVED` with the evidence per value (smoke runs per
  admitted dimension, legal runs per fixed setting and per action) and
  `all_values_evidenced` (a support probe). `recorded_refusals` cites `runs/rejected/`. Never infer `UNSUPPORTED_IMPLEMENTATION` from missing evidence.

## Rules for agents

- Never invent results, run IDs, hostap options, rule citations or spec section numbers.
  If something is unverified, say so.
- Spec-rule research needs the user to check the source; draft, don't declare.
- The standards in `docs/references.md` are the authority for what is legal: IEEE Std
  802.11be-2024 and 802.11-2024 ("shall", normative) and the WFA WPA3 / Enhanced Open
  Deployment Guide v1.1 (guidance). Before writing or changing a rule, an admissible value
  or a claim about Wi-Fi behavior, read the clause in the PDF (ask the user for their copy's
  path; they're licensed, so never commit them or their extracted text) and cite it with
  section, PDF page and strength. A NOTE is never a rule. Experiments that break a modeled
  rule run only as labeled negative experiments, never as legal candidates or smoke values.
- P0 models are strict (`strict=True`, `extra="forbid"`); cross-field Wi-Fi rules belong in P1.
- The MCP SDK is v2 (`mcp==2.3.0`): `FastMCP` no longer exists, use
  `from mcp.server.mcpserver import MCPServer`. v1 examples from the web won't import.
- Behavior facts come from real log lines. Before detecting a new behavior (e.g. ML probe,
  BTM), run the matching test and calibrate against its real logs; until then it stays `UNKNOWN`.
- Run evidence: `runs/baseline/` (official baseline), `runs/calibration/` (runs a detector
  was calibrated on), `runs/smoke/` (runs showing a setting value executes),
  `runs/anchors/` (extra runs so each anchor family has 3), `runs/rejected/` (runs of
  rule-passing candidates the implementation refused, kept as labeled refusals, never as
  smoke values), `campaigns/` (committed campaign runs, #68), `runs/hwsim-logs/`
  (git-ignored trials). Never commit trials as evidence.
- Keep `docs/plan.md`'s status tables current when an issue is finished.

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
.venv/bin/python scripts/build_model_json.py                 # regenerate model.json
.venv/bin/python scripts/plan_campaign.py --seed 0           # campaign_plan.json + pairwise_coverage.json
.venv/bin/python scripts/smoke_dimensions.py --check         # validate the dimension smoke candidates
.venv/bin/python scripts/run_campaign.py                     # run campaign_plan.json (Docker; slow)
.venv/bin/python scripts/find_contrasts.py                   # regenerate contrasts/contrasts.json
.venv/bin/python scripts/minimize_contrast.py minimize --a RUN --b RUN --facts F --out contrasts/cN  # Docker
.venv/bin/python scripts/minimize_contrast.py verify --out contrasts/cN   # 3/3 per final side (Docker)
.venv/bin/python scripts/check_consistency.py                # spec/rules/runs checks + rules/validation.json
.venv/bin/python scripts/update_anchor_coverage.py           # anchor_coverage.csv's campaign columns
.venv/bin/python scripts/update_dimension_coverage.py        # dimension_coverage.csv
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
  `run_hwsim_test`, `run_candidate`, the campaign tools `plan_campaign`, `run_campaign`,
  `list_campaigns`, `get_campaign`, and the agent chain `why_pruned` /
  `permitted_alternatives` (#74, over `explorer.pruning`) and `minimize_contrast` (#74, over
  `explorer.minimize`; a contrast index or two run IDs, `facts`, `max_guest_runs` ≤ 40;
  `MINIMIZE_RUNNER` is swapped in tests). Add new tools
  here with `@server.tool()`; raise `ToolError` for expected failures (any other exception
  reaches the agent only as "Error executing tool").
- `explorer.model.Config`: P0 settings model; `explorer.model.Candidate`: a `Config` plus
  ordered typed actions; `model.SCHEMA_VERSION` goes up when the P0 schema changes.
  `explorer.rules.load_rules()`: the P1 rule registry from
  `rules.yaml` (rules plus `UND.*` open questions); `rules/fixtures/<ID>.json` holds each
  entry's executable positive / negative / exception cases (`explorer.fixtures`, run by
  `tests/test_rule_fixtures.py`): add one with every new rule. `explorer.validate`: `parse_candidate`
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
  test means rebuilding the image; so does pulling anyone's change to `docker/`. `run_candidate` and
  `run_campaign` refuse a stale image (`runner.stale_harness`) until `scripts/build-env.sh` reruns.
- `model.json` (repo root): the machine-readable candidate space (P0 schema, admitted
  dimensions with typed values and smoke runs, constraints by rule ID, actions, pinned
  versions, `model_digest`), built by `explorer.model_json.build()`. Regenerate it with
  `.venv/bin/python scripts/build_model_json.py` after changing the model, `rules.yaml`,
  `surface_candidates.csv`'s `smoke_runs` or the adapter's actions; a test fails until you
  do. `model_json.apply({dimension: label})` turns choices into a candidate.
- `explorer.config_space`: the static settings as a ConfigSpace space (#63), each condition
  and forbidden clause tagged with its rule ID (`constraints()`); `PREDICATE_ONLY` lists the
  coded setting rules left to P1, with the reason. `is_valid(values)` / `violations(values)`
  judge hyperparameter values; `tests/test_config_space.py` keeps it in agreement with P1, so
  a new setting rule needs a constraint or a `PREDICATE_ONLY` entry.
- `explorer.cache`: the experiment cache (#67). `run_cached(candidate, Cache())` runs a
  candidate unless an `ACCEPTED` / `REJECTED` outcome is stored for its key (candidate +
  plan, pinned commits, environment digest, model version, harness hash); a hit has
  `independent=False`, so never count it as a repeat. `runs/cache.sqlite` is git-ignored;
  `Cache().rebuild()` re-indexes committed runs from the key each run records.
- `explorer.planner`: the pairwise campaign planner (#66). `Space()` enumerates the candidate
  space from `model.json` and assesses each assignment with P0, P1 and P2; `plan(seed,
  budget)` builds the allpairspy design (exact legal-completion filter, then a coverage
  top-up) over executable candidates; `coverage(space, plan_rows, ran_rows)` counts pairs
  with both denominators, covered only by real runs. `scripts/plan_campaign.py --seed N`
  writes `campaign_plan.json` and `pairwise_coverage.json`; a test fails if the committed
  plan no longer matches its seed and the current model.
- `explorer.campaign`: runs a plan (#68). `run(plan, id, cache=Cache())` re-checks each
  candidate, runs it through the cache (reruns once on `SETUP_FAIL` / `TIMEOUT`, never on
  `REJECTED`); `pruning_counts` / `rejected_cases` build the funnel and table.
  `scripts/run_campaign.py --id <id>` writes `campaigns/<id>/` (with the plan it ran) and
  `pruning_counts.json`; then regenerate the plan files: plans build on committed runs,
  so the next plan covers only what's left.
- `explorer.contrasts`: accepted-vs-accepted contrasts (#71). `find(group(accepted_runs()))`
  pairs candidates at most `max_inputs` inputs apart (`input_diff` / `distance`) whose runs
  are `ACCEPTED`, not negative experiments, pass today's rules and ran on the pinned
  commits. Both sides must be P2 `SUPPORTED` and ran under the same harness (`run_harness`:
  recorded with the cache key, or from the run's repo commit); repeats share a harness too,
  and a contrast on an older harness is marked `current_harness: false`. It claims a fact only when it's measured on both sides (never `UNKNOWN`) and the
  same in every repeat of each side, with the log lines it was read from (`evidence`).
  `reproduced` needs 3 runs per side. `scripts/find_contrasts.py` writes
  `contrasts/contrasts.json` (a test fails when it's stale); write-ups go in
  `contrasts/README.md`.
- `explorer.minimize`: the Picire interestingness wrapper (#72). `DeltaSet(a, b)` gives whole typed
  deltas (per config value per link, a one-sided link, a one-sided action step, a reordering) and
  `apply(subset)`; `minimize(a, b, target)` / `from_contrast(contrast)` run Picire's `DD`. Each probe
  passes P0, P1, action order, P2 and the adapter before `cache.run_cached`; `INVALID`,
  `SPEC_UNDETERMINED`, `UNSUPPORTED`, `UNRESOLVED`, `UNKNOWN`, `REJECTED`, `SETUP_FAIL`, `TIMEOUT` and
  `NOT_INTERESTING` stay separate in `Reduction.trace`; only `INTERESTING` (every target fact measured
  and equal to B's) counts. `from_contrast(facts=[...])` targets behavior facts, not config echoes such
  as `station_status`; the result has `needed_for_validity` and `minimal_p2`. Pass `runner=` /
  `support=` fakes in tests; a cache hit isn't independent. `max_guest_runs` stops a reduction
  with `BUDGET_EXHAUSTED` before the run that would exceed it. `verify(reduction)` (#73) runs both
  final sides (A, and A with the minimal deltas) 3 times each in fresh guests: `MINIMIZED` only when
  every run reproduces its side, else `PENDING_VERIFICATION`. `scripts/minimize_contrast.py` runs both
  steps and writes `contrasts/<id>/reduction.json`; `contrasts/c1/` (key), `contrasts/c2/` (link)
  and `contrasts/c3/` (security) are the first three. A `reduction.json` in a nested folder
  (`contrasts/c3/first-attempt/`) is a superseded attempt with `superseded_by`; don't count it.
- `explorer.pruning`: the agent chain's first two steps (#74). `why_pruned(data)` gives the
  planner's role for a candidate (`malformed` / `pruned` / `undetermined` / `unsupported` /
  `not_run` are pruned; `probe` / `supported` are executable), the stage, and per finding
  the rule's sources, ConfigSpace encoding and experimental validation (#76).
  `permitted_alternatives(data, max_changes, limit)` changes up to 3 admitted dimensions on
  the candidate itself and returns the minimal rule-passing results, `SUPPORTED` first.
  `current_label` / `set_label` read and set a dimension by its model.json label.
- `explorer.anchors`: campaign evidence for the anchor families (#77). `anchor_coverage.csv`'s
  `campaign_runs` (committed accepted campaign and contrast runs with the family's own value
  for every modeled dimension) and `campaign_observed` (value counts of `FAMILY_FACTS` over
  them) are generated by `scripts/update_anchor_coverage.py`; rerun it after committing runs,
  or `tests/test_anchor_coverage.py` fails. `run_ids` stay the family's own hostap test runs.
- `explorer.dimension_coverage`: committed evidence for every admitted dimension value (#110).
  `dimension_coverage.csv` (all generated by `scripts/update_dimension_coverage.py`): per
  `model.json` value, its smoke run and result, the accepted campaign and contrast runs with
  that value, how many ran on today's harness, and `status` (`COVERED` / `SMOKE_ONLY` /
  `RUNS_ONLY` / `GAP`). Rerun it after committing runs or changing `model.json`, or
  `tests/test_dimension_coverage.py` fails; it also fails if a value isn't `COVERED`.
- `explorer.consistency`: spec / rules / runs consistency (#76), run by
  `tests/test_consistency.py`. Passing runs in the evidence folders must pass today's
  rules unless labeled negative: `negative_experiment: true`, or one of hostap's own tests
  breaking only a rule in `NEGATIVE_BY_DESIGN`. Runs cited as evidence (smoke runs, anchor
  runs, contrast sides) get no exemption. Labeled negatives stay out of the evidence
  folders. A new rule that turns a committed run into a violation fails these tests: move
  the run to `runs/experiments/` as a labeled negative, or revisit the rule.
  `scripts/check_consistency.py` writes `rules/validation.json` (each rule's experimental
  validation; rules with none are flagged), and a test fails when it's stale.
- `explorer.support.check_support(candidate)`: the P2 check (rules decided in #80).
  `SUPPORTED` for an exact match to a tested scenario, or to a committed legal adapter run
  on the pinned commits; otherwise `UNRESOLVED` with the evidence per value (smoke runs per
  admitted dimension, legal runs per fixed setting and per action) and
  `all_values_evidenced` (a support probe). `recorded_refusals` cites `runs/rejected/` and
  campaigns' `REJECTED` runs. `UNSUPPORTED_IMPLEMENTATION` only for an entry of
  `IMPLEMENTATION_LIMITS` with recorded refusals; never infer it from missing evidence.

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
  smoke values), `runs/experiments/` (labeled experiment runs that answer a spec or
  implementation question, e.g. #95's RSNXE run; never P2 evidence), `campaigns/`
  (committed campaign runs, #68), `contrasts/runs/` (extra legal runs so each contrast
  side has 3, #71, and minimized contrasts' 3/3 reproductions, #73; P2 evidence),
  `contrasts/<id>/probes/` (a minimization's probe runs, the trace's evidence; not P2 evidence),
  `runs/hwsim-logs/`
  (git-ignored trials), `runs/cache.sqlite` (the cache's git-ignored
  index). Never commit trials as evidence.
- Keep `docs/plan.md`'s status tables current when an issue is finished.

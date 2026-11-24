# Project plan: Weeks 1–4

Shared context for the team and for coding agents. The GitHub issue board tracks
individual tasks and their status; this file holds the big picture and the decisions
behind it. Issues are referred to by name, not number.

_Status last updated 2026-11-16 from what is committed on `main`. Work that exists only on
someone's laptop or on the board isn't reflected here._

## What we're building

An MCP server that a coding agent (Claude Code / Codex) can call to explore Wi-Fi 7
multi-link (MLO) settings. Each candidate configuration passes through filters, and
every rejection says which stage and which sourced rule rejected it:

| Stage | Component | Question it answers | Status |
|---|---|---|---|
| P0 | Format checker | Is the request well formed? (types, allowed values, action syntax) | ✅ Settings model (`model.Config`), action model (`model.Candidate`: config + ordered actions) and readable `P0.*` errors (`validate.parse_candidate`) |
| P1 | Rule checker | Does it break one of our audited Wi-Fi rules? (≥4 rules, each with a cited source) | ✅ Rule registry (`rules.yaml` + `rules.load_rules()`); 8 security/setting rules coded (`validate.run_p1_checks`, applied to hostap tests by `run_hwsim_test`; all reviewed: since the #64 audit, and `SEC.MLD_SAME_RSNXE` since #95), all 9 action-order rules (`validate.check_action_order`) and 3 open questions that give `SPEC_UNDETERMINED`, chained by `validate.validate_candidate` |
| P2 | Support checker | Does our pinned hostap/kernel version actually support it? | 🟡 `support.check_support`: `SUPPORTED` for an exact match to a tested scenario or to a committed legal adapter run on the pinned commits; otherwise `UNRESOLVED` with per-value run evidence and `all_values_evidenced` (a support probe), plus recorded refusals (#80) |
| – | Campaign planner and runner | Which legal, runnable candidates cover every pair of admitted values, and what happens when they run? | ✅ `planner.plan` (`campaign_plan.json`, `pairwise_coverage.json`), `cache.run_cached`, `campaign.run` (`campaigns/`, `pruning_counts.json`). Over MCP: `plan_campaign`, `run_campaign`, `list_campaigns`, `get_campaign` |
| P3 | Test runner | What happens when we run it in a fresh simulated network? | ✅ `runner.run_test()` + `signatures.extract_record()`; any candidate the adapter supports runs through `adapter.run_candidate()` (ACCEPTED / REJECTED / SETUP_FAIL / TIMEOUT) |
| P4 | Difference finder | Which minimal change explains a behavior difference between two accepted runs? (Weeks 3–5) | 🟡 Contrasts: `contrasts.find` pairs accepted, rule-passing runs a few inputs apart and keeps only fact differences measured on both sides and stable across repeats, each with its log lines (`contrasts/contrasts.json`, `contrasts/README.md`). Minimization: `minimize.minimize` / `from_contrast` reduce a contrast's typed deltas with Picire, every probe checked by P0, P1 and P2 before a cached run (#72). Minimized so far, each with both final sides reproduced 3/3: `contrasts/c1/` (#73, `key`: 8 inputs reduced to the 5 s PTK rekey) `contrasts/c2/` (#106, `link`: 7 inputs reduced to link 1's `indicate_disabled`) and `contrasts/c3/` (#107, `security`: a client reconnect gives a second 4-way handshake only without `link_remove`) |
| – | MCP server | Lets the agent use all of the above in plain English | 🟡 `get_model`, `validate_candidate` (P0 + P1 + basic P2, no guest), `explain_rule` (full registry entry behind any finding) `run_hwsim_test` (runs an approved hostap test; one that breaks a modeled rule only as a labeled negative experiment) and `run_candidate` (runs any candidate the adapter supports, after validating it, with the same negative-experiment rule). `get_model` also reports `model.json`'s versions, admitted dimensions and the dependencies between them. Campaign tools: `plan_campaign`, `run_campaign`, `list_campaigns`, `get_campaign` ("Expose campaign over MCP"); contrast tools come with P4 |

Weeks 1–2 covered P0, P1, basic P2/P3 and MCP (Checkpoint 1). Week 3 adds the admitted
dimensions, `model.json`, P2 support probes, the candidate adapter and the campaign plan;
the ConfigSpace encoding, the experiment cache and the campaign (20 runs: 16 `ACCEPTED`,
4 `REJECTED`; every runnable value pair covered by a real run) are done.
P4 (contrasts and minimization) is Weeks 4–5.

## Repo layout

| Path | What it is |
|---|---|
| `src/explorer/` | The tool: one module per component. Implemented so far: `model.py` (P0 settings model), `rules.py` (P1 rule registry loader), `validate.py` (P0 errors, P1 rule checks, the pipeline), `scenarios.py` (what each runnable hostap test sets up and does), `support.py` (P2), `runner.py` (P3), `adapter.py` (runs any candidate: candidate → hwsim test plan, P3 status), `signatures.py` (behavior records), `model_json.py` (builds `model.json`; `apply()` turns dimension choices into a candidate), `planner.py` (the pairwise campaign plan and coverage), `config_space.py` (the static settings as a ConfigSpace space, each constraint tagged with its rule), `cache.py` (experiment cache: key, SQLite store, `run_cached`), `campaign.py` (runs a plan, the pruning funnel and rejected-cases table), `contrasts.py` (accepted-vs-accepted contrasts), `minimize.py` (Picire interestingness wrapper: typed deltas between two candidates, reduction trace), `mcp_server.py` (MCP tools) |
| `tests/` | pytest tests for `src/` (`WIFI7_DOCKER_TESTS=1` also runs a real simulation test) |
| `docker/` | Simulation environment: `Dockerfile`, `run-test.sh`, `README.md` |
| `scripts/build-env.sh` | One command: build the simulation image + smoke test (`--fresh` ignores the cache). Rerun it whenever `docker/` changes, including after pulling: `run_candidate` and `run_campaign` refuse an image whose harness files differ from the repo's (`runner.stale_harness`) |
| `.mcp.json` | Registers the MCP server (`wifi7-explorer`) for Claude Code |
| `baseline/README.md` | Pinned versions and the baseline runs that show the environment is reproducible |
| `runs/baseline/` | The three official baseline runs (committed evidence) |
| `runs/calibration/` | Runs used to calibrate how `signatures.py` detects a behavior (committed evidence, not baseline) |
| `docker/test_eht_client_bp.py` | Our `_client_bp` wrappers: hostap's tests with client beacon protection on |
| `docker/test_explorer_candidate.py` | Our adapter test: runs one candidate's plan (from `adapter.build_plan`) with hostap's own helpers |
| `scripts/build_model_json.py`, `scripts/plan_campaign.py` | Regenerate `model.json`, and `campaign_plan.json` + `pairwise_coverage.json` (`--seed N`, `--budget N`) |
| `scripts/run_campaign.py` | Runs `campaign_plan.json` (each candidate in a fresh guest through the cache; `--id`, `--retries`) and writes `campaigns/<id>/` and `pruning_counts.json`; the MCP tool `run_campaign` does the same for a plan from `plan_campaign` |
| `scripts/minimize_contrast.py` | Minimizes one contrast with real probes (`minimize`) and reproduces its final sides 3/3 (`verify`), writing `contrasts/<id>/reduction.json` (#73; Docker) |
| `scripts/find_contrasts.py` | Regenerates `contrasts/contrasts.json` from the committed runs (`--max-inputs N`); `tests/test_contrasts.py` fails when it's out of date |
| `scripts/check_consistency.py` | Runs the spec / rules / runs consistency checks (#76) and regenerates `rules/validation.json`; `tests/test_consistency.py` runs the same checks and fails when the report is out of date |
| `scripts/smoke_dimensions.py` | Runs the smoke candidates for the dimensions admitted through the adapter (`--check` validates only) |
| `scripts/reproduce-scenarios.py` | Runs each rule-passing hostap scenario through the adapter and lists the facts that differ from its committed runs |
| `runs/smoke/` | Runs showing each smoke-tested setting value executes (committed evidence; `surface_candidates.csv`'s `smoke_runs` column points here) |
| `runs/anchors/` | Extra runs so each anchor family in `anchor_coverage.csv` has 3 independent passing runs (committed evidence) |
| `runs/rejected/` | Runs of rule-passing candidates that hostapd / wpa_supplicant refused (P3 `REJECTED`), kept as labeled evidence of the refusal, never as smoke values (`runs/rejected/README.md`) |
| `runs/experiments/` | Labeled experiment runs that answer a question about the spec or the implementation (`runs/experiments/README.md`; #95's RSNXE run). Not P2 evidence: not in `support.EVIDENCE_DIRS` |
| `campaigns/` | Committed campaign runs, one folder per campaign (`seed0-2026-11-13/`, `seed0-topup-2026-11-13/`, `seed1-fresh-2026-11-15/` (run over MCP): run folders, `campaign_plan.json`, `pruning_counts.json`, `results.json`, `rejected_cases.csv`, `README.md`). `ACCEPTED` runs count as P2 evidence; `REJECTED` ones as recorded refusals |
| `contrasts/` | Accepted-vs-accepted contrasts (#71): `contrasts.json` (every contrast `contrasts.find` reports, with run IDs, the inputs that differ, the claimable facts and their log lines), `README.md` (each contrast's write-up) and `runs/` (the extra runs that give each side 3 independent runs; legal `ACCEPTED` adapter runs, in `support.EVIDENCE_DIRS` so a contrast's sides are P2 `SUPPORTED`), and `c1/`, `c2/`, `c3/` (#73, #106, #107: each minimized contrast's `reduction.json`, its write-up and its probe runs in `probes/`) |
| `pruning_counts.json` | The latest campaign's funnel (each campaign folder keeps its own copy, with the plan it ran): enumerated → P0 → ConfigSpace / P1 → P2 → planned → P3 statuses, guest boots, cache hits, retries. Written by `scripts/run_campaign.py` or the MCP tool `run_campaign` |
| `runs/cache.sqlite` | The experiment cache's index (git-ignored): run outcomes by cache key. The run folders are the evidence; `explorer.cache.Cache().rebuild()` re-indexes the committed ones |
| `runs/hwsim-logs/` | Trial runs (git-ignored; the default for `run-test.sh` and `run_test()`) |
| `docs/` | This plan; `references.md` (the standards, and the coverage matrix's legend); `research/` (the rule research `rules.yaml` is transcribed from); `dimensions.md` (below); Checkpoint 1's `demo.md` (script), `demo-transcript.md` and `demo-transcript-terminal.txt` (transcripts) and `checkpoint1-report.md`; `agent-chain-transcript.md` (#74: why pruned → permitted alternatives → minimize, over MCP from Claude Code) |
| `surface_candidates.csv` | Candidate settings, actions and observations found in hostap's tests, each with source lines (`tests/test_surface_candidates.py` checks it; set `WIFI7_HOSTAP_SRC` to also check the lines exist) |
| `rules.yaml` | P1 rule registry: each rule's ID, kind (normative / guidance / dependency / harness / policy), meaning, predicate, exceptions, sources (each tagged shall / note / unclassified / guidance / code; a normative rule needs a "shall") and examples, transcribed from `docs/research/`. `tests/test_rules.py` checks it; set `WIFI7_HOSTAP_SRC` to also check the hostap lines exist |
| `rules/fixtures/` | Executable rule fixtures (#64): one JSON file per rule or open question, with positive, negative and exception candidates and the exact expected `validate_candidate` outcome. `explorer.fixtures.evaluate()` reports their accuracy; `tests/test_rule_fixtures.py` runs them |
| `rules/validation.json` | Each rule's and open question's experimental validation (#76): the committed runs that break it today, the runs its matrix rows cite, its matrix rows and fixture counts; `unvalidated` lists those with no run at all. Written by `scripts/check_consistency.py` |
| `spec_coverage.csv` | Spec coverage matrix: each clause of the standards with its strength, status (`RULE` / `UND` / `OUT_OF_SCOPE` / `TODO`), rule IDs, tests and run evidence (`docs/references.md`, "Coverage matrix"). `tests/test_spec_coverage.py` checks it |
| `docs/dimensions.md` | The admitted dimensions and the per-dimension record (values, rule status, tested alternatives, prerequisites, versions); `scripts/smoke_dimensions.py` runs the smoke candidates for the new ones |
| `campaign_plan.json` | The pairwise campaign plan (issue #66): seed, budget, model version, the funnel (enumerated → P0 → P1 → P2 executable → planned), the planned candidates (each with its choices, the candidate, P1/P2 verdict and role: supported or support probe), what the budget cut, and the `SPEC_UNDETERMINED` review queue. Generated by `scripts/plan_campaign.py --seed N`; nothing in it has run |
| `pairwise_coverage.json` | Pairwise coverage with both denominators: feasible pairs after P0/P1 (modeled-admissible) and after P2 (executable), covered pairs (only candidates with a committed legal ACCEPTED run), planned pairs, and each infeasible pair with the rules that rule it out. Written with `campaign_plan.json` |
| `model.json` | The machine-readable candidate space: P0 schema, admitted dimensions (typed values, smoke runs, rule IDs), constraints by rule ID, action catalog, pinned versions, `schema_version` / `rules_version` / `model_digest`. Generated by `scripts/build_model_json.py` from `explorer.model_json`; `tests/test_model_json.py` fails when it's out of date |
| `anchor_coverage.csv` | The 4 scenario families (anchors): source test and helpers, modeled dimensions, real run IDs, observed signature and status (`IN_PROGRESS` until 3 passing runs with identical behavior signatures, then `PASS`). `tests/test_anchor_coverage.py` checks it |

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
  record), `SETUP_FAIL` or `TIMEOUT`; environment problems raise `RunnerError`. The candidate
  adapter maps them onto the spec's P3 statuses (see "Candidate adapter").
- **Behavior facts:** every fact comes from a specific log line or file; missing evidence
  is `UNKNOWN`, never guessed. A fact is only detected after it has been calibrated
  against real runs (kept in `runs/calibration/`). ML probe and BTM are not calibrated yet.
- **Baseline** (decided 2026-11-03): `runs/baseline/` (plain SAE, `eht_mld_sae_two_links`)
  is the *environment* baseline: it shows the Docker/UML setup reproduces a two-link MLO
  association. Its configuration breaks 802.11be §12.12.9 (AKM 8 between EHT devices), so
  it's a negative experiment, never a legal candidate or a side of a contrast. The *legal*
  baseline for experiments and contrasts is anchor family F02,
  `eht_mld_sae_ext_two_links_client_bp` (AKM 24, client beacon protection on), whose three
  runs with identical signatures are listed in `anchor_coverage.csv`.
- **Action model** (decided 2026-11-03, answers the open questions in
  `docs/research/action-order.md`):
  - *ML probe:* only `[scan, ml_probe_req]` is admitted. Probing while associated is
    allowed by hostap's code but no hostap test does it, so it stays not admitted.
  - *Last link removed:* the STA is disassociated (802.11be §35.3.6.3); post-association
    actions need a new `associate`.
  - *Disassociate / deauthenticate:* the STA is disconnected afterwards and continuing
    needs an explicit `associate`. hostap's automatic reconnection is recorded as observed
    behavior, not assumed by the action model.
  - *Added 2026-11-04 from code review (policy, for the team to check):* `associate` is
    refused while already associated or while the AP MLD or every remaining link is disabled;
    deleting the STA's last link with link reconfiguration leaves it unassociated; a disabled
    link can't be added; an ML probe needs the scanned AP MLD and requested link to still
    exist; `DISABLE_MLD` is refused if already disabled.
- **Anchor families** (approved by the team 2026-11-03): F02 SAE-EXT-KEY association, F08
  PTK rekey, F09 GTK rekey, F06 link removal (`anchor_coverage.csv`). F01 (plain SAE) and
  F05 (beacon protection off) are out because both break 802.11be §12.12.9.
- **Client beacon protection** (2026-11-05, Michelle's call; **the team should confirm**):
  §12.12.9 also covers the client, but hostap's tests for these families leave it off. The
  families now run through `_client_bp` wrappers (`docker/test_eht_client_bp.py`), which run
  hostap's own test with `beacon_prot="1"` on the MLD client. The originals are violations
  of `SEC.EHT_BEACON_PROT`, so they only run as negative experiments. After pulling, rebuild
  the image (`scripts/build-env.sh`).
- **P2 for untested combinations** (#80, 2026-11-13; proposed by Michelle, agreed by
  Jasmine on the issue):
  - P2 keeps the roadmap's statuses. An `UNRESOLVED` candidate whose every value has a
    passing, committed, rule-passing run (no trials, no negative experiments) gets
    `all_values_evidenced: true`; that covers the admitted dimensions, the fixed settings
    (a legal run with the same value) and each action. Only those run in the campaign, as
    labeled **support probes**; `pruning_counts.json` splits P2 into supported / probe /
    not run (#66).
  - An exact match (config and ordered actions) with a committed adapter run that passed
    the modeled rules, on the pinned hostap and kernel commits and a compatible schema
    version (`model.COMPATIBLE_SCHEMA_VERSIONS`: versions whose recorded candidates still
    mean the same, e.g. schema 1 runs under schema 2), is `SUPPORTED`. The image ID isn't
    compared (it changes on every rebuild). One ACCEPTED run is enough for P2; anchors and
    contrasts need 3/3. A cache hit isn't a new run. `campaigns/` and `contrasts/runs/`
    count as committed evidence. A recorded verdict is re-checked against today's rules: a run whose candidate
    a later rule rejects isn't evidence.
  - A refusal caused by our model isn't `UNSUPPORTED_IMPLEMENTATION`: the gap gets modeled.
    `ap_sae_pwe=1` with the client's `sae_pwe` unset was one; since #88 the client's
    `sae_pwe` is a dimension and `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E` rejects that pairing at
    P1, so P2 no longer cites that run. `recorded_refusals` cites only rejected runs whose
    candidate still passes the modeled rules. `UNSUPPORTED_IMPLEMENTATION` needs a REJECTED
    run showing the pinned versions really can't do something.
  - **Implementation limits** (PR #92, 2026-11-13, agreed with Michelle): P2 answers
    `UNSUPPORTED_IMPLEMENTATION` only from recorded refusals. `support.IMPLEMENTATION_LIMITS`
    names each sequence the pinned versions refuse, with the source lines and the log marker;
    a candidate matching one is unsupported when a committed `REJECTED` run of a rule-passing
    candidate matches it too (`runs/rejected/` and campaigns' `REJECTED` runs). Today:
    `P2.DISABLE_MLD_AFTER_LINK_REMOVE`, hostapd's `DISABLE_MLD` failing on a link
    `LINK_REMOVE` already disabled (4 campaign runs). Not a P1 rule: it isn't Wi-Fi behavior.
  - A probe that comes back REJECTED, SETUP_FAIL or TIMEOUT is counted at P3, never
    dropped. SETUP_FAIL / TIMEOUT say nothing about the candidate: rerun once, never file
    under `runs/rejected/` or use as evidence (#68). Probe pairs count as executed
    coverage only after an ACCEPTED run.
- **Candidate adapter** (#79, 2026-11-10; merged in PR #86 and built on since by "Admit ≥8
  executable dimensions", "Model the client's `sae_pwe`" and the campaigns, so it stands):
  any candidate runs
  through one hwsim test (`docker/test_explorer_candidate.py`) that uses hostap's own
  helpers. It observes the same way after every action (links, station status, traffic on
  each active link; after a disconnect or the last link's removal, that traffic fails) and
  after interval rekeys (one PTK rekey, two GTK rekeys, as hostap's rekey tests wait for).
  Rekey intervals whose waits exceed 610 s of guest time are refused (a 300 s GTK interval
  took 194 s of wall time). Each run folder's `explorer_plan.json` and manifest record the
  candidate, its validation (status, rule IDs, P2) and `negative_experiment`, and the model's
  schema version. A setup step or action that hostapd/wpa_supplicant refuses is P3
  `REJECTED`; traffic, link and rekey results are observations, never a rejection. Because
  each hostap test chooses what to observe, an adapter run is compared with that test's
  runs only on facts both observed (`adapter.compare_signatures`). It runs GCMP-256 and
  `disable_enable_mld` since the dimensions work (Week 3), and sets the client's `sae_pwe`
  with `wpas.set` before connecting, resetting it afterwards ("Model the client's
  `sae_pwe`"). Refused before a guest boots: `scan`, `ml_probe_req`, `ap_disassociate`,
  `ap_deauthenticate`, `bss_tm_link_removal_imminent` and `setup_link_reconfig`. After
  pulling, rebuild the image.
- **Admitted dimensions** (Week 3, "Admit ≥8 executable dimensions" and "Model the client's
  `sae_pwe`"): a dimension is a setting or action with at least two values that each pass
  the coded P1 rules and have a committed passing run (`surface_candidates.csv`'s
  `smoke_runs`; per-dimension record in `docs/dimensions.md`). Eleven are admitted:
  `ap_akm`, `sta_akm`, `ap_sae_pwe`, `sta_sae_pwe`, `ap_pairwise_cipher`,
  `ap_link_indicate_disabled`, `ap_ptk_rekey_interval`, `ap_gtk_rekey_interval`,
  `rekey_gtk_now`, `link_remove` and `disable_enable_mld`. The two `sae_pwe` settings only
  mean something with an SAE AKM, and the AP's 1 needs the client's set. Not admitted: the
  link count (P0 allows ≤2 links, the layouts we've run), AP PMF (`optional` only fits WFA
  Transition Mode), and beacon protection and client PMF (one legal value each). Campaign
  candidates are the legal F02 configuration with these dimensions varied
  (`model_json.apply`).
- **How dependencies are represented** (Week 3): every dependency and forbidden combination
  is a rule in `rules.yaml` (kind `dependency`, `normative` or `guidance`, with its
  citations) coded in `validate.P1_CHECKS`; action order is the `AO.*` rules in
  `validate.check_action_order`. `model.json` lists them as constraints by rule ID with their
  role (forbidden / dependency / action order). The static settings are also a ConfigSpace
  space (`explorer.config_space`, "Model parameter dependencies in ConfigSpace"): one
  categorical hyperparameter per setting dimension plus the two beacon-protection settings,
  `SEC.SAE_PWE_NEEDS_SAE` as conditions (the `sae_pwe` settings are active only with an SAE
  AKM), and `SEC.MLD_CLIENT_COMMON_AKM`, `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E` and
  `SEC.EHT_BEACON_PROT` as forbidden clauses, each tagged with its rule ID. What ConfigSpace
  can't express or can't reach here stays a P1 predicate, with the reason recorded
  (`config_space.PREDICATE_ONLY`): per-link AKM lists (`SEC.MLD_COMMON_SUITES`), plain SAE
  (`SEC.EHT_SAE_AKM`, `SEC.EHT_SAE_H2E`), PMF off (P0), the link layout (P0), action order
  and the open questions. An exhaustive test checks that ConfigSpace and P1 agree on every
  combination of the hyperparameters (verdict and rule IDs). Actions stay out of ConfigSpace,
  as the roadmap suggests. The planner still enumerates the space (actions are part of each
  assignment, and enumeration is exact at 4608), and reports ConfigSpace's pruning in its
  funnel.
- **Campaign strategy** ("Campaign planner", 2026-11-13): pairwise (strength 2) over the
  admitted dimensions on the F02 base. P0, P1 and P2 run on every assignment before any guest
  launches; only P2-supported candidates and support probes are planned, and
  `SPEC_UNDETERMINED` ones go to a review queue. allpairspy builds the design with an exact
  legal-completion filter; because it stops early under constraints, the planner checks the
  coverage itself and tops it up greedily. The seed fixes the value order, so a seed gives the
  same plan for the same evidence. Plans build on what has run: assignments with a
  committed legal `ACCEPTED` run count as covered, so each campaign covers what the earlier
  ones left. Budget 20. Coverage has two denominators (after P0/P1 and
  after P2), and a pair counts as covered only after a candidate with it runs `ACCEPTED`;
  planned pairs are reported apart. Running it ("Run ~20-candidate campaign"): each
  candidate in a fresh guest through the adapter and the experiment cache, `SETUP_FAIL` /
  `TIMEOUT` rerun once, runs committed under `campaigns/`.
- **Experiment cache** ("Experiment cache", 2026-11-13): the key is a SHA-256 over the
  normalized candidate and the exact plan the guest runs, the pinned hostap and kernel
  commits, an environment digest (the pinned base-image digest plus a hash of
  `docker/Dockerfile`, never the local image ID, which changes on cache-only rebuilds), the
  schema version and `model_digest`, and a harness hash (`docker/test_eht_client_bp.py`,
  `docker/test_explorer_candidate.py`, `docker/run-test.sh`). Only `ACCEPTED` and `REJECTED`
  outcomes are reused; `SETUP_FAIL` / `TIMEOUT` are recorded and rerun. A hit is not a new
  independent run (`independent: false`): repeat counts use run IDs, and an independent
  repeat runs with `force=True`. Each run records its key, context (campaign, seed) and
  timeout in its manifest, so the SQLite index (`runs/cache.sqlite`, git-ignored) can be
  rebuilt from committed runs on any machine.
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
| Get the standards documents | ✅ `docs/references.md` lists IEEE Std 802.11be-2024, IEEE Std 802.11-2024 and the WFA "WPA3 and Wi-Fi Enhanced Open Deployment and Implementation Guide" v1.1 (Feb 2025), with versions, links, normative vs guidance, relevant sections and how to get a copy. Every teammate doing rule research can open all three (confirmed 2026-11-16). Don't commit the PDFs |
| Rule research: action order | ✅ `docs/research/action-order.md`: 8 rules (harness/code prerequisites, not spec rules), plus the BSS TM config prerequisite coded as a ninth (`AO.BSS_TM_NEEDS_BSS_TRANSITION`, `draft` until 2026-11-13, now `reviewed`), each with sources, who enforces it, and allowed/disallowed examples |
| Rule research: link security match; SAE PWE / beacon protection | ✅ `docs/research/security-guidance.md`: 6 findings (link suites, beacon protection, PMF, SAE AKM, SAE H2E, and the setting dependency "`sae_pwe` only with SAE"; the link suites finding became two rules), citing 802.11be-2024 / 802.11-2024 and, where it applies, the WFA guide. IEEE citations checked against the PDFs; WFA citations checked by Michelle in the PDF (2026-11-04), who found that the PTK / GTK rekey tests fit Transition Mode on the AP side only. The team doesn't need a second teammate's review of the IEEE or WFA citations. Claude checked the hostap lines at the pinned commit and Michelle accepted the result (2026-11-04). The plain-SAE baseline question (802.11be §12.12.9 requires AKM 24/25 between EHT devices) is decided: see "Baseline" under Decisions |
| Pick the 4 scenario families | ✅ Done, approved by the team 2026-11-03. `anchor_coverage.csv` (moved to the repo root) lists F02 SAE-EXT-KEY association, F08 PTK rekey, F09 GTK rekey and F06 link removal, with helpers checked against the pinned tests. All four are `PASS`: 3 independent passing runs each with identical behavior signatures (`_client_bp` runs in `runs/smoke/` and `runs/anchors/`, all on one Intel Mac). F01 (plain SAE) and F05 (beacon protection off) were dropped: both break 802.11be §12.12.9. `tests/test_anchor_coverage.py` checks the file |
| Data model for settings | ✅ `model.Config` (AP MLD with per-link AKMs + client), strict, `extra="forbid"`; values limited to those hostap's tests use. Wi-Fi rules are left to P1 |
| Data model for actions | ✅ Done. `model.Candidate` = `Config` + an ordered list of typed actions (a discriminated union on `action`, strict, `extra="forbid"`), one class per action in `surface_candidates.csv` with its hostap source lines; arguments (link ID, removal count, DISABLE/ENABLE_MLD, DISCONNECT/RECONNECT, reconfig delete/add) are typed, and a link an action names must be a configured AP link. Added the `scan` action to `surface_candidates.csv` (the ML probe needs it). Action order is left to P1 |
| Decide baseline and action model | ✅ Done 2026-11-03. Recorded under Decisions ("Baseline", "Action model") and in `docs/research/action-order.md` |
| Readable format errors, rules file + loader | ✅ Rules file + loader done: `rules.yaml` holds 16 rules (7 `SEC.*` from the security research, 9 `AO.*` from the action-order research), loaded and checked by `rules.load_rules()`; hostap citations checked to exist at the pinned commit. All are `reviewed`; `AO.BSS_TM_NEEDS_BSS_TRANSITION` (new) was `draft` until Michelle accepted its hostap citations on 2026-11-13. Hostap citations were compared with the code by Claude and accepted by Michelle, apart from 4 she checked herself. Readable format errors done too: `validate.parse_candidate` turns bad input into `P0.*` findings (`P0.TYPE_ERROR`, `MISSING_FIELD`, `UNKNOWN_FIELD`, `NOT_ALLOWED`, `OUT_OF_RANGE`, `INVALID_VALUE`) with a path, e.g. `P0.TYPE_ERROR: config.ap.links[0].link_id must be an integer`; 14 bad inputs tested. Since 2026-11-05, P0 also limits the AP MLD to the layouts hostap's tests use (one link, or two on different channels): a limit to what's tested, not a Wi-Fi rule |

## Week 2 status

| Issue | Area | Status |
|---|---|---|
| Runner adapter | Simulation | ✅ Done. `runner.run_test()` |
| Calibrate rekey facts | Simulation | ✅ Done. PTK/GTK rekey counts + traffic after the last rekey, from runs in `runs/calibration/` |
| MCP server skeleton | MCP | ✅ Done. `get_model`, `.mcp.json`; verified in a Claude Code session |
| Smoke-test 4 settings | Simulation | ✅ Done. 6 candidates have ≥2 values that both run and pass the coded P1 rules (AKM SAE-EXT-KEY / OWE on AP and STA, PTK rekey unset / 5, GTK rekey unset / 5, link advertised disabled 0 / 1, link removal absent / present): passing runs in `runs/smoke/` (Intel Mac, with client beacon protection on), recorded in `surface_candidates.csv`'s `smoke_runs`; a test checks every listed run is legal under the coded rules. Plain SAE also runs but breaks 802.11be §12.12.9, so it doesn't count. Link removal is now in the behavior record (`link_reconfig_valid_links`). Caveats per value, with what the standards say, are in `runs/smoke/README.md` |
| Support check (P2) | Simulation | ✅ Basic version done. `support.check_support(candidate)` answers `SUPPORTED` only when a tested hostap scenario (`scenarios.TEST_CANDIDATES`: each runnable test's config and actions, from its source lines) executes the candidate exactly and that test has passing committed runs, naming the test and run IDs. Anything else is `UNRESOLVED`, listing the committed runs behind each value (smoke runs for the smoke-tested settings, runs of tests that perform each action and pass the modeled rules; runs of rule-breaking tests such as the plain-SAE baseline never count) and the closest tests. `UNSUPPORTED_IMPLEMENTATION` needs a recorded failure; there is none, so it never fires (the roadmap says not to invent one). `validate_candidate` runs it only for candidates that pass the modeled rules. No new simulation runs |
| Code rule: security type matches on every link | Research | ✅ Done, rechecked against the PDFs. Split by what the standard binds: `SEC.MLD_COMMON_SUITES` (802.11be §12.6.2, the AP MLD's own RSNE: same pairwise cipher, a common AKM) rejects hostap's `invalid_link`, `invalid_link_akm`, `invalid_link_pairwise` and `no_common_key_mgmt` configurations and allows different AKM lists that share an AKM; `SEC.MLD_CLIENT_COMMON_AKM` (§12.6.3.1) flags a client that allows none of the common AKMs, which a conforming client answers by declining. `SEC.EHT_SAE_AKM` (§12.12.9) is coded too. Rules are `reviewed` |
| Code rules: setting dependencies | Research | ✅ Done. `SEC.EHT_BEACON_PROT` (beacon protection on), `SEC.EHT_SAE_H2E` (plain SAE with `sae_pwe` unset uses hunting-and-pecking; judged by hostap's effective behavior, lines checked at the pinned commit) and `SEC.SAE_PWE_NEEDS_SAE` (`sae_pwe` without an SAE AKM has no effect) are in `validate.P1_CHECKS`, with allowed/disallowed tests. `SEC.PMF` isn't coded: the model can't express PMF disabled, so P0 rejects it. Research still needs a teammate's review |
| Action-order checker | Research | ✅ Done. `validate.check_action_order(candidate)` walks the actions through the state model in `action-order.md` and returns the first violation with its AO rule ID and the failing action's index. Enforces all 9 `AO.*` rules plus the 2026-11-03 decisions (no ML probe while associated; disconnected after disassociate/deauthenticate; disassociated when the last usable link is removed, 802.11be §35.3.6.3; links advertised disabled aren't the STA's links, §35.3.7.5.2). Tested with every rule's allowed and disallowed examples and hostap's own sequences |
| Undetermined result (`SPEC_UNDETERMINED`) | Research | ✅ Done. Findings carry an outcome (`MALFORMED`, `SPEC_RULE_VIOLATION`, `SPEC_UNDETERMINED`) and `validate.p1_status` sums them up. `rules.yaml` gains an `undetermined:` section of open questions with sources: `UND.AKM_PREFERENCE` (several AKM families usable; the choice follows the WPA3 Specification, which we don't have; WFA guide Table 3), `UND.STA_STATE_WHILE_MLD_DISABLED` (actions while the AP MLD is disabled and the STA wasn't disconnected; hostap's test says mac80211 may not notice) and `UND.ASSOC_WITHOUT_AP_LINKS` (associating after every AP link was removed). No runnable hostap test hits one |
| `validate_candidate` pipeline | Data models | ✅ Done. `validate.validate_candidate(data)` takes raw input, stops at P0 if it's malformed, otherwise runs every coded setting rule, open question and the action-order check, and returns the status (`MALFORMED` / `SPEC_RULE_VIOLATION` / `SPEC_UNDETERMINED` / `PASSES_MODELED_RULES`) with each finding explained from `rules.yaml` (title, kind, cited sources). Never boots a guest. Candidates that pass the modeled rules go on to the P2 support check. Tested with the Checkpoint 1 cases: P0 malformed, link-AKM rejection (§12.6.2), action-order rejection, an undetermined case and a legal candidate |
| Expose a real run over MCP | MCP | ✅ Done. `run_hwsim_test` runs one hostap test that has a passing committed run and a known configuration (`explorer.scenarios`) and returns its behavior record. It applies the coded P1 rules first: `get_model` lists each runnable test's `p1_status`, and a test that breaks a rule (the plain-SAE baseline, §12.12.9) is refused unless called with `negative_experiment=true`, which labels the result. Verified with a real run of `eht_mld_sae_ext_two_links_client_bp` through an in-process MCP client (`WIFI7_DOCKER_TESTS=1`). Still to record: a transcript from a Claude Code session |
| Expose validation and rules over MCP | MCP | ✅ Done. MCP tools `validate_candidate` (takes the candidate as a plain JSON object, so malformed input comes back as readable `P0.*` findings, not a tool error) and `explain_rule` (any `SEC.*` / `AO.*` / `UND.*` / `P0.*` ID: kind, review status, meaning, predicate, exceptions, every citation with page, strength and who checked it, examples). `get_model` now lists every rule and open question and reports P0 and P1 as implemented. Tested in process and over stdio as `.mcp.json` launches it. Still to record: a transcript from a Claude Code session (demo issue) |
| Record the demo | MCP | ✅ Done. Script `docs/demo.md`; transcripts `docs/demo-transcript.md` (Claude Code desktop session, 2026-11-06, `main` at `85ad39c`, Intel Mac) and `docs/demo-transcript-terminal.txt` (terminal session) |
| Write the 1-page report | MCP | ✅ Done. `docs/checkpoint1-report.md` (2026-11-06, `main` at `85ad39c`) |

**Main blockers:** none in the rule research. The team doesn't need a second teammate's
review of the citations, and should confirm the client beacon protection decision and the
action-model additions under Decisions.
The baseline and action-model decisions are made, the anchor families approved, and the
action model, action-order checker, P0 errors, setting rules, `SPEC_UNDETERMINED`, the
`validate_candidate` pipeline, its MCP tools and a basic P2 support check are done, and
Checkpoint 1's demo transcripts and report are on `main`. `run_hwsim_test` treats the plain-SAE baseline as a negative experiment,
as decided.

## Week 3 status

Parent issue "Week 3: Admit ≥8 dimensions and run staged constrained search"; sub-issues
on the board. Early Week 3 work went through the `week3-4` branch (merged in PR #92); later
issues each merged to `main` through their own PR. Every Week 3 issue below is done. The
only Week 3 follow-up still open is "Check whether per-link AKM lists give different
RSNXEs" (from the rule audit), an experiment rather than a deliverable.

| Issue | Area | Status |
|---|---|---|
| Fix the false "image not found" | Simulation | ✅ Done (PR #85). Docker Desktop's Resource Saver answers `docker image inspect` from a cache while its VM sleeps; `check_environment` re-checks with a filtered `docker image ls`, which wakes the VM |
| Run any candidate in a fresh guest (adapter) | Simulation | ✅ Done. `adapter.build_plan` / `run_candidate`, `docker/test_explorer_candidate.py`, MCP `run_candidate`. All 6 rule-passing scenarios run `ACCEPTED` through it (`scripts/reproduce-scenarios.py`, trial runs 1794367274–1794367744). Three match their committed runs on every fact both observed. The other three differ because hostap's legacy client `dev[0]` isn't modeled (OWE: an extra handshake and disconnect) and because the record keeps each fact's last value: the adapter's last look is after the final DISCONNECT or link removal (links `0x0`, not associated), hostap's tests last look while associated. Reviewed and tested on Windows/WSL by a teammate. Follow-up: the record can't show per-step state (e.g. traffic lost after an action); needs a signature issue before Week 4 contrasts. A candidate no hostap test covers (associate, then a GTK rekey on its own) runs `ACCEPTED` over MCP |
| Admit ≥8 executable dimensions | Model | ✅ 10 dimensions admitted (11 since "Model the client's `sae_pwe`"; `docs/dimensions.md`): the 6 from Week 2 plus `ap_sae_pwe` (conditional on SAE; unset / 2), `ap_pairwise_cipher` (CCMP / GCMP-256 on every link), `rekey_gtk_now` and `disable_enable_mld` (hostap's order: the STA is disconnected while the AP MLD is disabled). The adapter now runs GCMP-256 and DISABLE/ENABLE_MLD; the runs went through it on 2026-11-11 (WSL2) and are in `runs/smoke/`; `tests/test_surface_candidates.py` requires ≥8. Finding: `ap_sae_pwe=1` is **REJECTED** (`1794384673`): the AP then advertises the SAE H2E-only selector and a client with `sae_pwe` unset skips it, even with SAE-EXT-KEY (hostap lines checked), so admitting 1 needed the client's `sae_pwe` modeled (done: see "Model the client's `sae_pwe`"). Still open: the WFA cipher rows for GCMP-256 (PDF), and adding the cipher to the behavior record. `ap_mld_link_count` stays out (P0 ≤2 links) |
| Spec coverage matrix | Rules | ✅ `spec_coverage.csv`, 38 rows checked by `tests/test_spec_coverage.py`. Coverage: **22 RULE, 1 UND, 6 OUT_OF_SCOPE, 9 TODO** (802.11be: 9 / 0 / 4 / 4; 802.11-2024: 5 / 0 / 0 / 3; WFA: 8 / 1 / 2 / 2). Rows reuse the citations already checked in the PDFs; the two 802.11-2024 rows added for the client's `sae_pwe` (Table 9-131, §11.1.4.6) were checked by Michelle on PR #92; the 9 TODO rows (802.11-2024 rekey / PMF clauses, the rest of 802.11be §12.6, §35.3.6, §35.3.7, §35.3.5.2, WFA §3.2 and Table 4) need someone with the PDFs to find the clause and page |
| Model the client's `sae_pwe` | Model, Rules | ✅ Done 2026-11-12; rule reviewed 2026-11-13 (Michelle checked the PDF citations on PR #92). `StaConfig.sae_pwe` (unset / `hash_to_element` / `both`, P0 schema version 2), passed to the guest with `wpas.set("sae_pwe")` and reset afterwards. New P1 dependency rule `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E` (reviewed): an AP with `sae_pwe=1` and only SAE AKMs advertises the SAE H2E-only BSS membership selector (802.11-2024 Table 9-131, value 123), so the client needs `sae_pwe` 1 or 2; drafted from the PDF text (802.11-2024 Table 9-131 and §11.1.4.6, WFA Table 3) and the hostap lines, research in `docs/research/security-guidance.md`. `SEC.EHT_SAE_H2E` and `SEC.SAE_PWE_NEEDS_SAE` now also check the client's side. Smoke runs (all `ACCEPTED`, same signature as the base): `ap_sae_pwe=1` with the client's 1 (`1794548583`) or 2 (`1794548598`), and the client's 1 (`1794548609`) and 2 (`1794548623`) alone. So `ap_sae_pwe` gains the value 1 and `sta_sae_pwe` is an 11th dimension; the rejected run `1794384673` is now a P1 rejection. WFA guidance (not coded): for an EHT STA, Table 8 marks H2E Enabled (2) MAND and H2E Only (1) DISALLOW except in all-EHT networks |
| Build `model.json` | Model | ✅ Done 2026-11-12. `model.json` at the repo root (placeholder `src/model.json` removed), built by `explorer.model_json` and written by `scripts/build_model_json.py`: P0 schema, the 11 admitted dimensions with typed values, smoke runs and rule IDs, the other rows as not admitted, every rule as a constraint (forbidden / dependency / action_order, coded or not), open questions, the action catalog (adapter support), pinned versions, `schema_version`, `rules_version` and `model_digest` (ignores smoke run IDs, so new evidence doesn't change it). `get_model` reports its versions and dimensions; adapter runs record `model_digest`; `tests/test_model_json.py` fails when the file is stale and applies every value to F02. `model_json.apply()` turns dimension choices into a candidate, for the planner. The ConfigSpace encoding is still to come ("Model parameter dependencies in ConfigSpace"); until then model.json lists the dependencies and forbidden combinations as the coded P1 rules |
| P2 sees the new dimensions | Simulation | ✅ Done. `support.setting_values` now covers `ap_sae_pwe` and `ap_pairwise_cipher`, and `rekey_gtk_now` / `disable_enable_mld` as absent / present like `link_remove`, so their smoke runs are cited. Committed adapter runs count as action evidence (`support.adapter_runs`: passing runs whose recorded validation is `PASSES_MODELED_RULES`), listed before hostap-test runs. A GCMP-256 candidate cites `1794384688`, DISABLE/ENABLE_MLD `1794384702`, `rekey_gtk_now` `1794384695`. Merged into `week3-4` with #88: `sta_sae_pwe` added too, `ap_sae_pwe=1` cites `1794548583`, and a test makes every model field reach P2 (an admitted dimension or a fixed setting), so a new field can't slip past it. The rejected run in `runs/rejected/` is never cited as evidence |
| P2 for untested combinations | Simulation | ✅ Decided and built (Decisions). `all_values_evidenced` marks support probes, now also requiring a legal run for each fixed setting (e.g. `bss_transition` on has none); an exact match with a committed legal adapter run on the pinned commits and a compatible schema version is `SUPPORTED` (the #61 smoke candidates now are, e.g. F02 + GCMP-256 by `1794384688`, recorded under schema 1); recorded verdicts are re-checked against today's rules; `recorded_refusals` cites `runs/rejected/` runs no rule explains; `campaigns/` is in `EVIDENCE_DIRS`. Merged into `week3-4` after review (2026-11-13), with those fixes for #88 |
| Campaign planner (allpairspy) | Search | ✅ Done 2026-11-13. `explorer.planner` enumerates the candidate space (F02 with each of `model.json`'s 11 dimensions set: 4608 assignments) and checks every one with P0, P1 and P2 before any guest launches: 1152 pass the modeled rules (3456 pruned: assignments rejected by `SEC.SAE_PWE_NEEDS_SAE` 2560, `SEC.MLD_CLIENT_COMMON_AKM` 2304, `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E` 128; an assignment can break several), none is `SPEC_UNDETERMINED` (the review queue is empty), and all 1152 are executable (9 `SUPPORTED`, 1143 support probes). allpairspy builds the design with an exact filter (a partial row is rejected only when no executable completion exists); it stops after 8 rows covering 209 of the 250 feasible pairs, so the planner checks coverage itself and tops it up greedily: seed 0 plans 16 candidates (8 + 8, all new probes) covering all 250, within the budget of 20 (the roadmap's ~20: the admitted model needs fewer). `pairwise_coverage.json`: 261 pairs, 11 infeasible (each with its rules), 250 feasible after P1 and after P2, 126 already covered by committed runs (0.504), 250 planned. `scripts/plan_campaign.py` writes both files; `tests/test_planner.py` (19 tests) covers the filter, reproducibility, P2 filtering, the review queue and coverage counting. ConfigSpace ("Model parameter dependencies in ConfigSpace") isn't used yet: the legal domain is the coded P1 rules over the enumerated space, exact at this size |
| Model parameter dependencies in ConfigSpace | Model | ✅ Done 2026-11-13. `explorer.config_space`: a ConfigSpace space over the 8 setting dimensions plus AP/client beacon protection; `SEC.SAE_PWE_NEEDS_SAE` as conditions, `SEC.MLD_CLIENT_COMMON_AKM` / `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E` / `SEC.EHT_BEACON_PROT` as forbidden clauses, each tagged with its rule ID; the other coded setting rules documented as predicate-only, with the reason (Decisions, "How dependencies are represented"). `tests/test_config_space.py` checks all 2304 combinations: ConfigSpace and P1 agree on the verdict (144 legal) and on the rule IDs, and samples from ConfigSpace pass P1; #76 reuses it. `model.json`'s `configspace` section records the encoding, and the planner's funnel shows ConfigSpace pruning the same 3456 assignments as P1 |
| Audit rules against clause text | Rules | ✅ Done 2026-11-13. Audit (Michelle, PDFs; Claude, hostap lines at the pinned commit): all 17 rules and 3 open questions match their cited clauses. Changes in `rules.yaml`: `SEC.MLD_COMMON_SUITES` notes that §12.6.2's same-RSNXE requirement isn't checked (follow-up experiment: "Check whether per-link AKM lists give different RSNXEs"); `SEC.MLD_CLIENT_COMMON_AKM` notes how the common ciphers are covered; `SEC.EHT_SAE_H2E` notes that its predicate covers both sides (the predicate text stays, since it feeds `model_digest`); `AO.NO_LINKS_LEFT`'s §35.3.7.5.2 source now describes hostapd's disabled-link TTLM, with hostap sources; `AO.BSS_TM_NEEDS_BSS_TRANSITION`'s citations widened, then accepted by Michelle, so it's `reviewed` (every rule and open question now is); re-read citations dated. Fixtures: `rules/fixtures/` has 57 executable cases for all 20 entries (22 positive, 29 negative, 6 exception), each with the exact expected outcome; `explorer.fixtures.evaluate()` reports 100% accuracy and every negative caught. `rules.yaml`'s examples stay as the plain-language description |
| Experiment cache | Search | ✅ Done 2026-11-13. `explorer.cache`: `key_parts` / `cache_key` (candidate and plan, pinned commits, environment digest, schema version and `model_digest`, harness hash; Decisions, "Experiment cache"), a SQLite store (`runs/cache.sqlite`, git-ignored) and `run_cached`, which reuses only `ACCEPTED` / `REJECTED` outcomes and marks hits not independent. `adapter.run_candidate` records the key, context and timeout in each run's manifest, and `Cache.rebuild()` re-indexes committed runs. `tests/test_cache.py` (16 tests): the key changes with the candidate, environment, harness and model; hit and miss; failures rerun; forced repeats; rebuild |
| Run ~20-candidate campaign | Search | ✅ Done 2026-11-13, two campaigns, **20 runs: 16 `ACCEPTED`, 4 `REJECTED`**, 0 `SETUP_FAIL` / `TIMEOUT`, no retries (WSL2). `explorer.campaign` + `scripts/run_campaign.py` re-check each candidate at launch and run it once in a fresh guest through the cache. `campaigns/seed0-2026-11-13/` ran the 16-candidate plan: 12 `ACCEPTED`, 4 `REJECTED`. All 4 combine `link_remove` with `DISABLE_MLD`: the pinned hostapd fails `DISABLE_MLD` because the removed link's interface is already disabled (`hostapd/ctrl_iface.c:3670-3708`, `src/ap/hostapd.c:3744-3757`). After review (PR #92), P2 reads campaign refusals and answers `UNSUPPORTED_IMPLEMENTATION` for `DISABLE_MLD` after a `link_remove` (288 assignments), and plans build on earlier runs: `campaigns/seed0-topup-2026-11-13/` ran the 4 candidates left, all `ACCEPTED`. Coverage by real runs: **249 / 249 runnable pairs, 249 / 250 allowed by the modeled rules**; the one left is the unsupported pair. `tests/test_campaign.py` |
| Expose campaign over MCP | MCP | ✅ Done 2026-11-16. Tools: `plan_campaign` (a bounded pairwise plan, budget 1–40, no boot; a brief summary with a `plan_id`, the funnel, pair coverage and each candidate's ID and choices; the plan stays in the server and is remade from its ID after a restart, refused if the evidence or model changed), `run_campaign` (re-checks each candidate at launch, runs it through the cache, retries `SETUP_FAIL` / `TIMEOUT` up to 2 times, writes `campaigns/<id>/` like `scripts/run_campaign.py`, returns each candidate's status and run ID), `list_campaigns` and `get_campaign` (funnel, rejected cases, one candidate's full entry on request). `get_model` lists the dependencies (`model.json` constraints). `tests/test_mcp_campaign.py` covers them in process with a fake runner and over stdio. `run_campaign` and `run_candidate` now refuse to run on an image older than the repo's harness files (`runner.stale_harness`): the cache keys runs by the repo's copies, and on 2026-11-16 an image built before #88 ignored the client's `sae_pwe` and turned a legal candidate into a false `REJECTED`. Checked for real 2026-11-16 (WSL2) through an in-process MCP client: `plan_campaign` (seed 5, budget 3, fresh) then `run_campaign`: 3 guests, 3 `ACCEPTED`, output in a scratch folder, not committed. Then from a Claude Code session (Nancy, 2026-11-16): `campaigns/seed1-fresh-2026-11-15/`, a fresh seed-1 design, **17 `ACCEPTED`** of 17, 17 guest boots, no retries |
| Add the cipher to the behavior record | Simulation | ✅ Done 2026-11-13. `signatures.STATUS_FIELDS` adds `pairwise_cipher`, `group_cipher` and `mgmt_group_cipher` (wpa_supplicant's STATUS lines, `src/rsn_supp/wpa.c:5342-5343, 5368`), calibrated on `1794384666` (CCMP) and `1794384688` (GCMP-256), whose signatures now differ only in those fields. The four anchor families still have identical signatures per family (F02 and F06 show CCMP / CCMP / BIP; F08 and F09 log no status) |
| Update plan.md for Week 3 | Docs | ✅ Done 2026-11-16 (Michelle, with Jasmine's go-ahead): reflects `main` at the end of Week 3. The Week 3 decisions (dimensions, dependency representation, campaign strategy, P2 for untested combinations, implementation limits, experiment cache), a row per Week 3 issue, the deliverables and the coverage summary below, and CLAUDE.md |

### Week 3 deliverables (the roadmap's list)

| Artifact | Status |
|---|---|
| ≥8 executable dimensions | ✅ 11 (`docs/dimensions.md`, `model.json`) |
| `rules.yaml` + tests | ✅ 17 rules and 3 open questions, all `reviewed`; 57 executable fixtures in `rules/fixtures/`; `tests/test_rules.py`, `test_validate.py`, `test_action_order.py`, `test_rule_fixtures.py` |
| `model.json` | ✅ `scripts/build_model_json.py` |
| `campaign_plan.json` | ✅ Seed 0; the plans each campaign ran are in its folder (16, then 4); the repo root's is the next one, empty: nothing runnable is left uncovered |
| `pairwise_coverage.json` | ✅ 250 feasible pairs after P1, 249 after P2; 249 covered by committed runs (1.0 of runnable, 0.996 of allowed) |
| `pruning_counts.json` (P0 → P1 → P2 → P3) | ✅ Latest (`seed1-fresh-2026-11-15`, a fresh seed-1 design over MCP): 4608 → 1152 pass P1 → 864 runnable (288 `UNSUPPORTED_IMPLEMENTATION`; 25 `SUPPORTED`, 839 probes) → 17 planned → 17 `ACCEPTED`; the earlier campaigns' (16 → 12 / 4, then the 4-candidate top-up → 4 / 0) are in their folders |
| Table of rejected cases with rule IDs | ✅ Each campaign's `rejected_cases.csv`: P1 rejections grouped by rule IDs (count and an example) and its `REJECTED` runs with their reason (the 4 in `seed0-2026-11-13`) |
| ~20 distinct legal uncached runs | ✅ 20 (16 + a 4-candidate top-up), out of 864 runnable candidates; `seed1-fresh-2026-11-15` (#69) then ran 17 more over a fresh seed-1 design, all `ACCEPTED`. We stopped at 20 because they cover every runnable value pair (pairwise strength 2), not because fewer candidates were legal |

### Coverage summary

- **Spec coverage** ([`spec_coverage.csv`](../spec_coverage.csv), legend in
  [`docs/references.md`, "Coverage matrix"](references.md#coverage-matrix)): 57 rows,
  **23 RULE, 1 UND, 17 NO_RULE, 16 OUT_OF_SCOPE, 0 TODO** (2026-11-24, after #112). Every
  RULE row's citation has been checked in the PDF by a person (the last, WFA §3.2 for
  `SEC.MLO_PASSWORD_NEEDS_WPA3`, by Michelle on 2026-11-17). #112's 17 new rows (no new
  rule) still need a person's check.
- **Anchor families** ([`anchor_coverage.csv`](../anchor_coverage.csv)): F02, F08, F09 and
  F06 all `PASS` (3 independent runs each of their own hostap test, identical signatures).
  Since #77, each row also lists the committed accepted campaign and contrast runs that
  have the family's own values (`campaign_runs`), and what they showed (`campaign_observed`).
  These are generated by `scripts/update_anchor_coverage.py`, and a test fails when stale.
  The counts as of 2026-11-18:
  - F02 (SAE-EXT-KEY at both ends): 26 runs, all associated.
  - F08 (5 s PTK rekey): 31 runs. The 11 without `link_remove` all completed a PTK rekey
    and ended with only reason 3 (local). The 20 with `link_remove` never did, and all got
    reason 15 from the AP: the C1 contrast, across the campaigns.
  - F09 (5 s GTK rekey): 23 runs, each with at least one GTK rekey.
  - F06 (`link_remove` and `rekey_gtk_now`): 3 runs. All three also had the 5 s PTK rekey,
    hence their reason 15.
- **Pairwise** ([`pairwise_coverage.json`](../pairwise_coverage.json), checked current
  2026-11-18): 261 pairs of admitted values, 11 infeasible under the modeled rules; 250
  feasible after P1, 249 after P2 (`link_remove` with `DISABLE_MLD` is
  `UNSUPPORTED_IMPLEMENTATION`). Covered by committed `ACCEPTED` runs: **249 / 250 legal
  (99.6%), 249 / 249 runnable (100%)**; 126 were covered before the campaigns.

## Week 4 status

Parent issue "Week 4: Find contrasts and minimize them (Checkpoint 2)"; sub-issues on the
board. Each issue merges to `main` through its own PR.

| Issue | Area | Status |
|---|---|---|
| Find ≥2 accepted-vs-accepted contrasts | Search | ✅ Done 2026-11-17. `explorer.contrasts` + `scripts/find_contrasts.py` (`contrasts/contrasts.json`, write-up in `contrasts/README.md`). It pairs accepted, rule-passing, non-negative runs on the pinned commits that are a few inputs apart, both P2 `SUPPORTED` and under the same harness (repeats too), and claims only facts measured on both sides and stable across each side's repeats, each with its log lines. **2 reproduced contrasts, 3 vs 3 runs, one input apart**, on today's harness (9 runs in `contrasts/runs/`, all `ACCEPTED`). C1: a 5 s PTK rekey after `link_remove` (`1794933558`, `1794933622`, `1794933677` vs `1794933586`, `1794933644`, `1794933694`) adds AP-initiated reason-15 disconnects (15, 15, 15, 3) and ends in `4WAY_HANDSHAKE`. C2: the same rekey without `link_remove` (`1794933604`, `1794933660`, `1794933709`) completes (`ptk_rekeys_completed` 1 vs 0). Across all 49 accepted runs, reason 15 comes in 17/17 with ptk 5 + `link_remove` and 0/32 otherwise. hostapd receives no EAPOL frame after `LINK_REMOVE`, though the client sends 2/4; the cause isn't in the logs and no claim is made. The adapter now reads the client's `wpa_state` at each observation for its label and the expected traffic result: it logged "(associated)" after the AP's disconnect (`tests/test_explorer_candidate_state.py`). Runs on the earlier harness give the same contrasts (`current_harness: false`), with reason 15 twice instead of three times. Review follow-ups: `contrasts/runs/` is in `support.EVIDENCE_DIRS`, and `run_harness` takes a run's harness from its cache key or its repo commit. New harness hash: rebuild the image, and earlier runs are cache misses |
| Picire interestingness wrapper | Search | ✅ Done 2026-11-17 (unit tests only; no real probes yet, that's #73). `explorer.minimize`: `DeltaSet` turns two candidates into whole typed deltas from `contrasts.input_diff` (one per differing config value per AP link, a link only one side has as one delta, one per action step only one side performs placed among the common steps, or one reordering); no deltas give A, all give B. `minimize(a, b, target)` (or `from_contrast`) runs Picire's `DD` over them. Each probe is checked by P0, P1 settings, open questions, action order, P2 (`SUPPORTED`, or an `UNRESOLVED` support probe with every value evidenced, as the planner does) and the adapter before `cache.run_cached`, rerunning once on `SETUP_FAIL` / `TIMEOUT`. Statuses kept apart in the trace: `INVALID` (stage P0 / P1 / action_order), `SPEC_UNDETERMINED`, `UNSUPPORTED` (P2 limit or adapter), `UNRESOLVED`, `UNKNOWN` (a target fact not measured, none measured differs), `REJECTED`, `SETUP_FAIL`, `TIMEOUT`, `NOT_INTERESTING` (a measured target fact differs); only `INTERESTING` (every target fact measured and equal to B's) counts. `from_contrast(facts=...)` picks a subset of the claimed facts: a fact echoing the config (`station_status`'s `key_mgmt` / ciphers) makes it keep AKM / cipher deltas, so #73 should target behavior facts such as `disconnect_reasons`. The result lists `needed_for_validity` (minimal deltas whose single removal gave an `INVALID` / `SPEC_UNDETERMINED` probe) and `minimal_p2` (`UNRESOLVED` for a support probe until #73's committed runs). Cache hits are marked `independent: false` and `guest_runs` counts only real runs. A and B are probed first (`TARGET_NOT_INTERESTING` / `BASELINE_INTERESTING` stop it). `picire==21.8` was already pinned. `tests/test_minimize.py` (fake runner) covers each status and small reductions |
| Minimize one contrast end to end | Search | ✅ Done 2026-11-17. `contrasts/c1/` (`reduction.json`, `README.md`, probe runs in `probes/`), made by `scripts/minimize_contrast.py`. A: campaign run `1794812749` (SAE-EXT-KEY, `sae_pwe` set, 5 s PTK and GTK rekeys, `link_remove`; reason-15 disconnects); B: the clean OWE group (`1794557032`, `1794878319`, `1794878408`); target `disconnect_reasons`. 8 deltas reduced to one, **`ptk_rekey_interval_s` 5 → unset**, in 8 probes (4 guest runs, 4 `INVALID` at P1 that never booted, no cache hits). `minimize.verify` reran both final sides in fresh guests: A `1794952238`, `1794952257`, `1794952274` (reason 15 in each) and A without the rekey `1794952292`, `1794952308`, `1794952325` (only the local teardown in each), so it is labeled `MINIMIZED`. Those runs are in `contrasts/runs/`, and `contrasts.json` lists the pair as a reproduced contrast. `tests/test_minimize.py` re-reads the committed runs against `reduction.json`. The cause of the failure isn't in the logs and no claim is made |
| Check whether per-link AKM lists give different RSNXEs | Rules | ✅ Done 2026-11-16. They do: run `1794875139` (`runs/experiments/`; link 0 `[SAE-EXT-KEY, OWE]`, link 1 `[OWE]`, client `OWE`, `ACCEPTED`) shows RSNXE `0x20` (SAE hash-to-element) in link 0's Beacons and responses and no RSNXE on link 1, whose per-STA profile marks element 244 as not inherited. Michelle re-read 802.11be §12.6.2 (PDF p. 411, shall) and chose the strict reading of "RSNXE if included": once one link includes it, every link advertises the same one. New rule `SEC.MLD_SAME_RSNXE` (`validate.check_mld_same_rsnxe`, computing each link's bit as hostapd does, `src/ap/wpa_auth_ie.c:549-557, 601-611`), with fixtures, a `config_space.PREDICATE_ONLY` entry (every link gets the same AKM in the campaign space, so it can't fire there) and the §12.6.2 matrix row. It also fires on hostap's `eht_mld_no_common_key_mgmt` (plain SAE without `sae_pwe` on link 0). Reviewed: Michelle accepted the hostap lines, which the run bears out |
| MCP tool chain for contrasts (#74) | Agent | ✅ Done 2026-11-18. All three steps recorded from Claude Code in `docs/agent-chain-transcript.md` (WSL, 2026-11-18, at `e3b3118`). Step 3 minimized #73's pair `1794812749` → `1794557032` to the same `ptk_rekey_interval_s` 5 → unset, labeled `PENDING_VERIFICATION`; `contrasts/c1/` holds that pair's 3/3 verification. Its probes were served from the cache. A first recording (at `8d5dcec`) had caught the tool reporting `MINIMIZED` for a one-run-per-probe reduction, so it was fixed (`e3b3118`) and the chain recorded again. The tool now returns #73's `label: PENDING_VERIFICATION` (`MINIMIZED` needs `scripts/minimize_contrast.py verify`, 3/3 per side), with the reduction's outcome as `reduction_status`. Step 3: MCP tool `minimize_contrast` over #72's `explorer.minimize` (`tests/test_mcp_minimize.py`, fake guest). It takes a contrast from `contrasts.json` by index, or any two committed `ACCEPTED` runs, plus the target `facts` and a guest-run budget (`max_guest_runs`, 1-40). `minimize` gained that budget: it stops with `BUDGET_EXHAUSTED` before the run that would exceed it. The report lists every change, the 1-minimal ones, the minimal candidate and its P2 status, and every probe with its status, stage, rule IDs and exact run IDs. Real call over MCP, 2026-11-17 (trial runs, not committed): `1794812824` → `1794933586` (6 changes), target `disconnect_reasons`, gave `MINIMIZED` to `ptk_rekey_interval_s: 5 -> null`. It took 15 probes (9 stopped at P1 without booting), 6 guest runs and 70 s. Picire logs to stderr, so the stdio transport stays clean. Steps 1–2: `explorer.pruning` + MCP tools `why_pruned` and `permitted_alternatives` (`tests/test_pruning.py`). `why_pruned` runs the planner's stages and answers in its roles: `malformed` (P0); `pruned` or `undetermined` (P1); `unsupported` or `not_run` (P2); executable `probe` or `supported`. Per finding it gives the reason, the predicate, every cited source with page and strength, how ConfigSpace encodes the rule and its experimental validation from #76. A test checks it agrees with `planner.Space` on a spread of assignments. `permitted_alternatives` changes up to 3 admitted dimensions on the candidate itself and lists the minimal rule-passing results, `SUPPORTED` first, then support probes. The roadmap's example ("`P1.ML_AKM_INTERSECTION`"; ours is `SEC.MLD_COMMON_SUITES`: link 1 offering only OWE) gets one alternative, `ap_akm` back to SAE-EXT-KEY, `SUPPORTED` by committed runs |
| Extend spec coverage: next clause batch (#75) | Rules | ✅ Done 2026-11-18. Batch read 2026-11-17 (Claude, PDF text); the new rule reviewed 2026-11-17 (Michelle checked WFA §3.2 and Tables 5 and 8 in the PDF). The clauses behind the key and link dimensions and contrast C1 left `TODO`. **New rule** `SEC.MLO_PASSWORD_NEEDS_WPA3` (guidance, reviewed, WFA §3.2 p. 29: an ML association that can use WPA-PSK / WPA-PSK-SHA256 needs an SAE-family AKM on every link), coded in `validate.check_mlo_password_needs_wpa3` with 7 fixtures, a `config_space.PREDICATE_ONLY` entry (no admitted value reaches it) and research in `docs/research/security-guidance.md`. **New matrix status `NO_RULE`**: read, but nothing a candidate can break. 802.11-2024 §12.6.19 (PDF 3035-3036: rekeying is allowed, "may"), §12.7.6.6 (PDF 3073: retransmit message 1, then "should" deauthenticate; C1's reason-15 disconnects have this shape) and §12.7.7.4 (PDF 3079); 802.11be §35.3.5.2 (PDF 512: one PTKSA across setup links, descriptive) and §35.3.6.3's non-AP MLD side (PDF 518: the removed link is nonexistent, the other setup link stays). So nothing read makes C1's ptk 5 + `link_remove` illegal. §35.3.6.1/.2/.4/.5/.6 are `OUT_OF_SCOPE` (capability bits, adding APs, `setup_link_reconfig` not admitted). Still `TODO`, for the next batch (not part of #75): 802.11be §12.6 (other) and §35.3.7 (other), 802.11-2024 PMF (MFPC/MFPR), WFA Table 4 |
| Consistency checks: spec ↔ rules ↔ runs (#76) | Rules | ✅ Done 2026-11-17. `explorer.consistency`, `tests/test_consistency.py`, `scripts/check_consistency.py`. Every passing run in the evidence folders passes today's rules (P1, open questions, action order) or is a labeled negative: `negative_experiment: true`, or one of hostap's own tests breaking only `SEC.EHT_SAE_AKM` (the baseline) or `SEC.EHT_BEACON_PROT` (client beacon protection off). Runs cited as evidence (smoke, anchors, contrast sides) get no exemption, and labeled negatives stay out of the evidence folders. Every value `model_json.DIMENSIONS` offers has a smoke run. Already covered, so not repeated: fixtures per rule (`test_rule_fixtures.py`), a matrix row per standards citation (`test_spec_coverage.py`), smoke runs that show their value (`test_surface_candidates.py`, `test_model_json.py`) and #63's ConfigSpace ↔ P1 agreement (`test_config_space.py`). Nothing on `main` failed the checks. `rules/validation.json` flags rules with no experimental validation: 4 of 21 are broken in a committed run (`SEC.EHT_SAE_AKM`, `SEC.EHT_BEACON_PROT`, `SEC.MLD_SAME_RSNXE`, `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E`), 6 have only cited legal runs, and 11 have none (`SEC.SAE_PWE_NEEDS_SAE`, 8 of the 9 `AO.*` rules, `UND.AKM_PREFERENCE`, `UND.STA_STATE_WHILE_MLD_DISABLED`) |
| Update anchor & pairwise coverage (#77) | Coverage | ✅ Done 2026-11-18. No campaign run re-ran a family's exact candidate (the campaigns vary the dimensions around the F02 base). So `anchor_coverage.csv` gained two generated columns per family instead: `campaign_runs`, the committed accepted campaign and contrast runs with the family's own value for every modeled dimension, and `campaign_observed`, value counts of the family's behavior facts over them (`explorer.anchors`, `scripts/update_anchor_coverage.py`, `tests/test_anchor_coverage.py` fails when stale). F02 26 runs, F08 31, F09 23, F06 3. F08's split is the C1 finding across the campaigns: with `link_remove`, 0 / 20 completed a PTK rekey and 20 / 20 got reason 15; without it, 11 / 11 rekeyed. `pairwise_coverage.json` regenerates unchanged: 249 / 250 legal pairs (99.6%) and 249 / 249 runnable pairs covered by committed runs. Numbers in "Coverage summary" above |

## Week 5 status

Parent issue "Week 5: Extend executable surface and reproduce three contrasts"; sub-issues
on the board. Each issue merges to `main` through its own PR.

| Issue | Area | Status |
|---|---|---|
| Minimize a second contrast (#106) | Search | ✅ Done 2026-11-23. `contrasts/c2/` (`reduction.json`, `README.md`, probe runs in `probes/`), category `link` by its target fact. A: `c1/`'s clean side (`1794952292`, `1794952308`, `1794952325`; SAE-EXT-KEY, `sae_pwe` set, 5 s GTK rekeys, `link_remove`, both links active); B: OWE with link 1 `indicate_disabled` (`1794933586`, `1794933644`, `1794933694`); target `data_test_rx_ap_links` (`[0, 1]` vs `[0]`). Both on today's harness, no PTK rekey on either side. 7 deltas reduced to one, **link 1 `indicate_disabled` false → true**, in 8 probes (5 guest runs, 3 `INVALID` at P1 that never booted, no cache hits). Verified 3/3 per side in fresh guests: A `1795473107`, `1795473128`, `1795473143` (`active_links=0x3`, traffic on both links) and A with link 1 disabled `1795473160`, `1795473183`, `1795473195` (`valid_links=0x3`, `active_links=0x1`, traffic on link 0 only), so `MINIMIZED`. This is what hostap's own test expects (`test_eht.py:510`, 525-531): expected behavior, not a bug. `scripts/minimize_contrast.py` now labels runs and the JSON by the output folder; `tests/test_minimize.py` re-reads both `c1/` and `c2/` |
| Minimize a third contrast (#107) | Search | ✅ Done 2026-11-24. `contrasts/c3/` (`reduction.json`, `README.md`, probe runs in `probes/`), category `security` by its target fact (`four_way_handshakes_completed`, an F02 fact). A: `c2/`'s minimal side (`1795473160`, `1795473183`, `1795473195`; SAE-EXT-KEY, CCMP, 5 s GTK rekeys, link 1 `indicate_disabled`, `associate` + `link_remove`; 1 handshake). B: the same config with `associate`, `DISCONNECT`, `RECONNECT` (`1795480398`, `1795480414`, `1795480426`; 2 handshakes). No PTK rekey on either side. 3 action deltas, all needed: 8 probes (1 guest run, 5 cache hits on committed runs, 2 `INVALID` by `AO.RECONNECT_AFTER_DISCONNECT`). Without `RECONNECT` there's no second association; with `link_remove` kept, the reconnect's handshake times out with reason 15 (`1795480438`, `1795480449`, `1795480460`: hostapd receives no EAPOL after `LINK_REMOVE`, C1's pattern without a rekey). Verified 3/3 per side: `1795480526`, `1795480537`, `1795480546` (1 handshake) and `1795480556`, `1795480567`, `1795480580` (2), so `MINIMIZED`. A first reduction (`c3/first-attempt/`, 9 → 5 against a B that also restarts the AP MLD) kept the restart in its cause because Picire removes one typed delta at a time. Jasmine's trials on PR #121 showed the reconnect alone is enough, and this reduction shows it with committed runs. `contrasts/README.md`'s table across every accepted run now shows the failure is a 4-way handshake after `link_remove`, from a rekey or a reconnect. c1–c3 cover `key`, `link` and `security` with three different minimal causes. `tests/test_minimize.py` re-reads `c3/` too and accepts a cache-hit probe's run committed elsewhere under `contrasts/`; `tests/test_mcp_minimize.py` finds C1 by its runs, since its index in `contrasts.json` moved |
| Close the remaining spec-coverage TODOs (#112) | Rules | 🟡 Read 2026-11-24 (Claude, PDF text); a person's check of the 17 new rows is still to come. The 4 `TODO` rows became 17 rows: **no new rule**, since nothing in them can be broken by a candidate. 802.11be §12.6: §12.6.1.1.2, §12.6.1.1.6 (one PTKSA per MLD setup, "shall", on the implementation) and §12.6.12 are `NO_RULE`; §12.6.8.2 (preauthentication) is `OUT_OF_SCOPE`. 802.11be §35.3.7: TTLM (§35.3.7.2; every candidate is in the default mapping mode), §35.3.7.1, .3, .4 and .5.3 are `OUT_OF_SCOPE`; §35.3.7.5.1 (link disablement uses advertised TTLM) is `NO_RULE`, since `indicate_disabled` is hostapd's static option. 802.11-2024 PMF: §12.6.3's Table 12-5 (MFPC/MFPR) is `NO_RULE` because every modeled pair is in its "may associate, PMF negotiated" row (AP `ieee80211w` 1 / 2, client fixed at 2); it would need a rule only if client PMF became a setting. §12.6.17 is `NO_RULE`. WFA Table 4's other rows (legacy security, Privacy, OCV, Transition Disable, SAE groups) are `NO_RULE`: P0 can't express the disallowed values, or the modeled AP keeps hostapd's defaults, which match. `spec_coverage.csv` now has 57 rows and no `TODO` |

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
person against their sources before their pull request is merged, ideally with a coding
agent reading the source fresh rather than re-reading the doc. A second teammate isn't needed. Paste this into Claude Code (or
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

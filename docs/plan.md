# Project plan: Weeks 1–2 (Checkpoint 1)

Shared context for the team and for coding agents. The GitHub issue board tracks
individual tasks and their status; this file holds the big picture and the decisions
behind it. Issues are referred to by name, not number.

_Status last updated 2026-11-03 from what is committed on `main` and the `week2-jas`
branch (Week 2 work lands on `week2-jas` first). Work that exists only on someone's
laptop or on the board isn't reflected here._

## What we're building

An MCP server that a coding agent (Claude Code / Codex) can call to explore Wi-Fi 7
multi-link (MLO) settings. Each candidate configuration passes through filters, and
every rejection says which stage and which sourced rule rejected it:

| Stage | Component | Question it answers | Status |
|---|---|---|---|
| P0 | Format checker | Is the request well formed? (types, allowed values, action syntax) | ✅ Settings model (`model.Config`), action model (`model.Candidate`: config + ordered actions) and readable `P0.*` errors (`validate.parse_candidate`) |
| P1 | Rule checker | Does it break one of our audited Wi-Fi rules? (≥4 rules, each with a cited source) | 🟡 Rule registry (`rules.yaml` + `rules.load_rules()`); 6 security/setting rules coded (`validate.run_p1_checks`, applied to hostap tests by `run_hwsim_test`), all 8 action-order rules (`validate.check_action_order`) and 3 open questions that give `SPEC_UNDETERMINED`, chained by `validate.validate_candidate` |
| P2 | Support checker | Does our pinned hostap/kernel version actually support it? | ⬜ |
| P3 | Test runner | What happens when we run it in a fresh simulated network? | ✅ `runner.run_test()` + `signatures.extract_record()` |
| P4 | Difference finder | Which minimal change explains a behavior difference between two accepted runs? (Weeks 3–5) | ⬜ |
| – | MCP server | Lets the agent use all of the above in plain English | 🟡 `get_model`, `validate_candidate` (P0 + P1, no guest), `explain_rule` (full registry entry behind any finding) and `run_hwsim_test` (runs an approved hostap test; one that breaks a modeled rule only as a labeled negative experiment). Campaign and contrast tools come with P4 |

Weeks 1–2 cover P0, P1, basic P2/P3 and MCP. P4 and the large campaign come later.

## Repo layout

| Path | What it is |
|---|---|
| `src/explorer/` | The tool: one module per component. Implemented so far: `model.py` (P0 settings model), `rules.py` (P1 rule registry loader), `validate.py` (P1 rule checks), `runner.py` (P3), `signatures.py` (behavior records), `mcp_server.py` (MCP tools). The rest are placeholders |
| `tests/` | pytest tests for `src/` (`WIFI7_DOCKER_TESTS=1` also runs a real simulation test) |
| `docker/` | Simulation environment: `Dockerfile`, `run-test.sh`, `README.md` |
| `scripts/build-env.sh` | One command: build the simulation image + smoke test (`--fresh` ignores the cache) |
| `.mcp.json` | Registers the MCP server (`wifi7-explorer`) for Claude Code |
| `baseline/README.md` | Pinned versions and the baseline runs that show the environment is reproducible |
| `runs/baseline/` | The three official baseline runs (committed evidence) |
| `runs/calibration/` | Runs used to calibrate how `signatures.py` detects a behavior (committed evidence, not baseline) |
| `runs/smoke/` | Runs showing each smoke-tested setting value executes (committed evidence; `surface_candidates.csv`'s `smoke_runs` column points here) |
| `runs/anchors/` | Extra runs so each anchor family in `anchor_coverage.csv` has 3 independent passing runs (committed evidence) |
| `runs/hwsim-logs/` | Trial runs (git-ignored; the default for `run-test.sh` and `run_test()`) |
| `docs/` | This plan and other notes |
| `surface_candidates.csv` | Candidate settings, actions and observations found in hostap's tests, each with source lines (`tests/test_surface_candidates.py` checks it; set `WIFI7_HOSTAP_SRC` to also check the lines exist) |
| `rules.yaml` | P1 rule registry: each rule's ID, kind (normative / guidance / dependency / harness / policy), meaning, predicate, exceptions, sources (each tagged shall / note / unclassified / guidance / code; a normative rule needs a "shall") and examples, transcribed from `docs/research/`. `tests/test_rules.py` checks it; set `WIFI7_HOSTAP_SRC` to also check the hostap lines exist |
| `anchor_coverage.csv` | The 4 scenario families (anchors): source test and helpers, modeled dimensions, real run IDs, observed signature and status (`IN_PROGRESS` until 3 passing runs with identical behavior signatures, then `PASS`). `tests/test_anchor_coverage.py` checks it |

The other data files (`model.json`, `pruning_counts.json`) still sit in `src/` as
placeholders and should move to the repo root (as in the spec's layout) when they are
first filled in.

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
- **Baseline** (decided 2026-11-03): `runs/baseline/` (plain SAE, `eht_mld_sae_two_links`)
  is the *environment* baseline: it shows the Docker/UML setup reproduces a two-link MLO
  association. Its configuration breaks 802.11be §12.12.9 (AKM 8 between EHT devices), so
  it's a negative experiment, never a legal candidate or a side of a contrast. The *legal*
  baseline for experiments and contrasts is anchor family F02, `eht_mld_sae_ext_two_links`
  (AKM 24), whose three runs with identical signatures are listed in
  `anchor_coverage.csv`.
- **Action model** (decided 2026-11-03, answers the open questions in
  `docs/research/action-order.md`):
  - *ML probe:* only `[scan, ml_probe_req]` is admitted. Probing while associated is
    allowed by hostap's code but no hostap test does it, so it stays not admitted.
  - *Last link removed:* the STA is disassociated (802.11be §35.3.6.3); post-association
    actions need a new `associate`.
  - *Disassociate / deauthenticate:* the STA is disconnected afterwards and continuing
    needs an explicit `associate`. hostap's automatic reconnection is recorded as observed
    behavior, not assumed by the action model.
- **Anchor families** (approved by the team 2026-11-03): F02 SAE-EXT-KEY association, F08
  PTK rekey, F09 GTK rekey, F06 link removal (`anchor_coverage.csv`). F01 (plain SAE) and
  F05 (beacon protection off) are out because both break 802.11be §12.12.9.
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
| Get the standards documents | 🟡 `docs/references.md` lists IEEE Std 802.11be-2024, IEEE Std 802.11-2024 and the WFA "WPA3 and Wi-Fi Enhanced Open Deployment and Implementation Guide" v1.1 (Feb 2025), with versions, links, normative vs guidance, relevant sections and how to get a copy. Still to do: every teammate doing rule research confirming they can open all three. Don't commit the PDFs |
| Rule research: action order | ✅ `docs/research/action-order.md`: 8 rules (harness/code prerequisites, not spec rules), each with sources, who enforces it, and allowed/disallowed examples |
| Rule research: link security match; SAE PWE / beacon protection | 🟡 Draft in `docs/research/security-guidance.md`: 6 findings (link suites, beacon protection, PMF, SAE AKM, SAE H2E, and the setting dependency "`sae_pwe` only with SAE"), citing 802.11be-2024 / 802.11-2024 and, where it applies, the WFA guide. IEEE citations checked against the PDFs; **the WFA rows (and a few hostap lines) still need a teammate's review** before merging. The plain-SAE baseline question (802.11be §12.12.9 requires AKM 24/25 between EHT devices) is decided: see "Baseline" under Decisions |
| Pick the 4 scenario families | ✅ Done, approved by the team 2026-11-03. `anchor_coverage.csv` (moved to the repo root) lists F02 SAE-EXT-KEY association, F08 PTK rekey, F09 GTK rekey and F06 link removal, with helpers checked against the pinned tests. All four are `PASS`: 3 independent passing runs each with identical behavior signatures (new runs in `runs/anchors/`; F08 and F09 span an Intel Mac and Windows + WSL2). F01 (plain SAE) and F05 (beacon protection off) were dropped: both break 802.11be §12.12.9. `tests/test_anchor_coverage.py` checks the file |
| Data model for settings | ✅ `model.Config` (AP MLD with per-link AKMs + client), strict, `extra="forbid"`; values limited to those hostap's tests use. Wi-Fi rules are left to P1 |
| Data model for actions | ✅ Done. `model.Candidate` = `Config` + an ordered list of typed actions (a discriminated union on `action`, strict, `extra="forbid"`), one class per action in `surface_candidates.csv` with its hostap source lines; arguments (link ID, removal count, DISABLE/ENABLE_MLD, DISCONNECT/RECONNECT, reconfig delete/add) are typed, and a link an action names must be a configured AP link. Added the `scan` action to `surface_candidates.csv` (the ML probe needs it). Action order is left to P1 |
| Decide baseline and action model | ✅ Done 2026-11-03. Recorded under Decisions ("Baseline", "Action model") and in `docs/research/action-order.md` |
| Readable format errors, rules file + loader | 🟡 Rules file + loader done: `rules.yaml` holds 14 draft rules (6 `SEC.*` from the security research, 8 `AO.*` from the action-order research), loaded and checked by `rules.load_rules()`; hostap citations checked to exist at the pinned commit. Every rule stays `draft` until its research is reviewed. Readable format errors done too: `validate.parse_candidate` turns bad input into `P0.*` findings (`P0.TYPE_ERROR`, `MISSING_FIELD`, `UNKNOWN_FIELD`, `NOT_ALLOWED`, `OUT_OF_RANGE`, `INVALID_VALUE`) with a path, e.g. `P0.TYPE_ERROR: config.ap.links[0].link_id must be an integer`; 12 bad inputs tested |

## Week 2 status

| Issue | Area | Status |
|---|---|---|
| Runner adapter | Simulation | ✅ Done. `runner.run_test()` |
| Calibrate rekey facts | Simulation | ✅ Done. PTK/GTK rekey counts + traffic after the last rekey, from runs in `runs/calibration/` |
| MCP server skeleton | MCP | ✅ Done. `get_model`, `.mcp.json`; verified in a Claude Code session |
| Smoke-test 4 settings | Simulation | ✅ Done. 6 candidates have ≥2 values that both run and pass the coded P1 rules (AKM SAE-EXT-KEY / OWE on AP and STA, PTK rekey unset / 5, GTK rekey unset / 5, link advertised disabled 0 / 1, link removal absent / present): passing runs in `runs/smoke/` (Windows + WSL2), recorded in `surface_candidates.csv`'s `smoke_runs`; a test checks every listed run is legal under the coded rules. Plain SAE also runs but breaks 802.11be §12.12.9, so it doesn't count. Link removal is now in the behavior record (`link_reconfig_valid_links`). Caveats per value, with what the standards say, are in `runs/smoke/README.md` |
| Support check (P2) | Simulation | ⬜ Unblocked (smoke runs recorded) |
| Code rule: security type matches on every link | Research | ✅ Done, rechecked against the PDFs. Split by what the standard binds: `SEC.MLD_COMMON_SUITES` (802.11be §12.6.2, the AP MLD's own RSNE: same pairwise cipher, a common AKM) rejects hostap's `invalid_link`, `invalid_link_akm`, `invalid_link_pairwise` and `no_common_key_mgmt` configurations and allows different AKM lists that share an AKM; `SEC.MLD_CLIENT_COMMON_AKM` (§12.6.3.1) flags a client that allows none of the common AKMs, which a conforming client answers by declining. `SEC.EHT_SAE_AKM` (§12.12.9) is coded too. Rules stay `draft` until a teammate reviews the research |
| Code rules: setting dependencies | Research | ✅ Done. `SEC.EHT_BEACON_PROT` (beacon protection on), `SEC.EHT_SAE_H2E` (plain SAE with `sae_pwe` unset uses hunting-and-pecking; judged by hostap's effective behavior, lines checked at the pinned commit) and `SEC.SAE_PWE_NEEDS_SAE` (`sae_pwe` without an SAE AKM has no effect) are in `validate.P1_CHECKS`, with allowed/disallowed tests. `SEC.PMF` isn't coded: the model can't express PMF disabled, so P0 rejects it. Research still needs a teammate's review |
| Action-order checker | Research | ✅ Done. `validate.check_action_order(candidate)` walks the actions through the state model in `action-order.md` and returns the first violation with its AO rule ID and the failing action's index. Enforces all 8 `AO.*` rules plus the 2026-11-03 decisions (no ML probe while associated; disconnected after disassociate/deauthenticate; disassociated when the last usable link is removed, 802.11be §35.3.6.3; links advertised disabled aren't the STA's links, §35.3.7.5.2). Tested with every rule's allowed and disallowed examples and hostap's own sequences |
| Undetermined result (`SPEC_UNDETERMINED`) | Research | ✅ Done. Findings carry an outcome (`MALFORMED`, `SPEC_RULE_VIOLATION`, `SPEC_UNDETERMINED`) and `validate.p1_status` sums them up. `rules.yaml` gains an `undetermined:` section of open questions with sources: `UND.AKM_PREFERENCE` (several AKM families usable; the choice follows the WPA3 Specification, which we don't have; WFA guide Table 3), `UND.STA_STATE_WHILE_MLD_DISABLED` (actions while the AP MLD is disabled and the STA wasn't disconnected; hostap's test says mac80211 may not notice) and `UND.ASSOC_WITHOUT_AP_LINKS` (associating after every AP link was removed). No runnable hostap test hits one |
| `validate_candidate` pipeline | Data models | ✅ Done. `validate.validate_candidate(data)` takes raw input, stops at P0 if it's malformed, otherwise runs every coded setting rule, open question and the action-order check, and returns the status (`MALFORMED` / `SPEC_RULE_VIOLATION` / `SPEC_UNDETERMINED` / `PASSES_MODELED_RULES`) with each finding explained from `rules.yaml` (title, kind, cited sources). Never boots a guest. P2 is reported as `NOT_CHECKED` until the support check exists. Tested with the Checkpoint 1 cases: P0 malformed, link-AKM rejection (§12.6.2), action-order rejection, an undetermined case and a legal candidate |
| Expose a real run over MCP | MCP | ✅ Done. `run_hwsim_test` runs one hostap test that has a passing committed run and a known configuration (`explorer.scenarios`) and returns its behavior record. It applies the coded P1 rules first: `get_model` lists each runnable test's `p1_status`, and a test that breaks a rule (the plain-SAE baseline, §12.12.9) is refused unless called with `negative_experiment=true`, which labels the result. Verified with a real run of `eht_mld_sae_ext_two_links` through an in-process MCP client (`WIFI7_DOCKER_TESTS=1`). Still to record: a transcript from a Claude Code session |
| Expose validation and rules over MCP | MCP | ✅ Done. MCP tools `validate_candidate` (takes the candidate as a plain JSON object, so malformed input comes back as readable `P0.*` findings, not a tool error) and `explain_rule` (any `SEC.*` / `AO.*` / `UND.*` / `P0.*` ID: kind, review status, meaning, predicate, exceptions, every citation with page, strength and who checked it, examples). `get_model` now lists every rule and open question and reports P0 and P1 as implemented. Tested in process and over stdio as `.mcp.json` launches it. Still to record: a transcript from a Claude Code session (demo issue) |
| Record the demo | MCP | ⬜ Last |
| Write the 1-page report | MCP | ⬜ Last |

**Main blockers:** a teammate review of `docs/research/security-guidance.md` (an AI agent
has checked every IEEE and WFA citation against the PDF text, which doesn't replace it).
The baseline and action-model decisions are made, the anchor families approved, and the
action model, action-order checker, P0 errors, setting rules, `SPEC_UNDETERMINED`, the
`validate_candidate` pipeline and its MCP tools are done, so the P2 support check, the
demo (with a Claude Code transcript) and the 1-page report are next. `run_hwsim_test` treats the plain-SAE baseline as a negative experiment,
as decided.

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

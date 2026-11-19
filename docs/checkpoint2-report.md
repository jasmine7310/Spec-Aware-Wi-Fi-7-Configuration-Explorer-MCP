# Checkpoint 2 report: Spec-Aware Wi-Fi 7 Configuration Explorer (MCP)

CS 211 Fall 2026, Project F · Week 4 · repo `main` at `75582b3` · demo:
[`checkpoint2-demo.md`](checkpoint2-demo.md)

**Since Checkpoint 1.**
- **Space and search:** 11 admitted dimensions (6 before). Rules are also a ConfigSpace
  space, and a pairwise planner (allpairspy) runs campaigns through an experiment cache.
- **P2:** decides support from committed runs only.
- **New in Week 4:** accepted-vs-accepted contrasts, a Picire minimizer with a Wi-Fi
  interestingness wrapper, and the MCP chain `why_pruned` → `permitted_alternatives` →
  `minimize_contrast` (12 tools in all).
- **Evidence:** 106 committed runs; 1106 tests pass with Docker.

Passing still means **"passes modeled rules"**, not 802.11be compliance.

| Checkpoint 2 item | Evidence |
|---|---|
| End-to-end stage counts | Campaign `seed0-2026-11-13`: 4608 enumerated → 4608 P0 → 1152 pass ConfigSpace/P1 (3456 rejected, by rule ID) → 1152 P2-executable → 16 planned → P3 12 `ACCEPTED`, 4 `REJECTED`, 16 guest boots. Three campaigns: 37 runs (33 `ACCEPTED`, 4 `REJECTED`, no setup failures or timeouts). Today's P2 marks 288 candidates `UNSUPPORTED_IMPLEMENTATION` from those 4 refusals (demo 2–3). |
| Rule sources and violations | 19 rules (7 normative, 2 dependency, 1 guidance, 9 harness) + 3 open questions, all `reviewed`; each citation has its section, PDF page, strength and checker. 70 executable fixtures: all pass, every negative caught. `why_pruned` on "links share no AKM" names `SEC.MLD_COMMON_SUITES` (802.11be §12.6.2, PDF 411, "shall") with its evidence (demo 4). |
| ≥2 accepted-vs-accepted contrasts | `contrasts/contrasts.json`: 5, 3 on today's harness, each 3 vs 3 runs. Sides must be legal, P2-`SUPPORTED`, `ACCEPTED`; only facts stable across repeats are claimed, with their log lines. C1: a 5 s PTK rekey with `link_remove` adds AP reason-15 disconnects (demo 6). |
| Minimized contrast | `contrasts/c1/`: Picire DD over 8 typed changes → 1, `ptk_rekey_interval_s` 5 → unset. 8 probes, 4 `INVALID` at P1 and never booted. **`MINIMIZED`**: both final sides reproduced 3/3. Over MCP, `minimize_contrast` says `PENDING_VERIFICATION` until that check (demo 7–8). |
| Legal feasible-pair coverage | 261 pairs, 11 infeasible (with their rule IDs). **249 / 250 legal and 249 / 249 runnable pairs covered** by committed `ACCEPTED` runs. The one legal pair that can't run: `link_remove` + `DISABLE_MLD`. |
| Exact logs and assertions | c1 baseline `1794952238`: line 171 `reason=15`, line 186 `EXPLORER-NO-EVENT PTK rekey within 10.0 s`. Minimal `1794952292`: GTK rekeys at lines 168 and 201, line 233 `reason=3 locally_generated=1`. The adapter test is `PASS` on both: it observes and doesn't assert, so the facts differ (demo 8). |
| Four-anchor coverage matrix | F02, F08, F09, F06 each `PASS` (3 identical-signature runs of its own test). New campaign columns: 26 / 31 / 23 / 3 runs. F08: with `link_remove`, 0 / 20 rekeyed and 20 / 20 got reason 15; without it, 11 / 11 rekeyed (demo 10). |
| MCP chain | `docs/agent-chain-transcript.md`: the three steps run from Claude Code. |
| Mentor feedback | `spec_coverage.csv`: 44 rows: 23 RULE, 1 UND, 6 NO_RULE, 10 OUT_OF_SCOPE, 4 TODO. `scripts/check_consistency.py`: every evidence run passes today's rules or is a labeled negative experiment. `rules/validation.json`: 4 rules broken in a run, 6 with cited runs, 12 with none (demo 11). |

**Findings.**
- **PTK rekey after link removal fails.** After `LINK_REMOVE`, the client's EAPOL-Key replies
  stop reaching hostapd, which resends message 1 and disconnects it with reason 15. That's
  the shape of 802.11-2024 §12.7.6.6. The logs don't show where the replies are lost, so we
  claim no cause. Nothing we read makes the candidate illegal:
  - 802.11-2024 §12.6.19 allows rekeying ("may");
  - 802.11be §35.3.5.2: one PTKSA spans the setup links;
  - 802.11be §35.3.6.3: the other setup link stays.
- **The pinned hostapd doesn't enforce every rule.** It accepted per-link RSNXEs that
  differ (`SEC.MLD_SAME_RSNXE`), as the labeled experiment `runs/experiments/1794875139`
  shows. The pruning comes from the standard.
- **Behavior targets, not config echoes.** A target fact that repeats the config
  (`station_status`'s AKM) makes the minimizer keep config changes, so targets are behavior
  facts such as `disconnect_reasons`.

**To discuss with the mentor.**
1. **C1:** report it to hostap as a likely bug, or treat it as expected? Should a run that
   loses its rekey stay P3 `ACCEPTED`?
2. **Two readings to confirm:**
   - §12.6.2's "RSNXE if included", which we read strictly;
   - the WFA guide's §3.2 "network", which we read per link (each link is its own BSS).
3. **Client beacon protection:** keeping it on through the `_client_bp` wrappers, with
   hostap's originals only as negative experiments.
4. **12 rules with no experimental validation**, mostly `AO.*` harness rules: run labeled
   negative experiments for them, or accept their hostap code citations?
5. **API:**
   - `minimize_contrast` now returns `label` and `reduction_status`;
   - contrasts are files only: should they get an MCP tool?
   - the new matrix status `NO_RULE`.

**Limits.**
- Each minimization probe is one run; only the final sides are reproduced 3/3.
- The 106 committed runs come from two kinds of host: 60 from Windows/WSL2 and 46 from an
  Intel Mac.
- 4 spec clauses are still TODO: 802.11be §12.6 (other subclauses) and §35.3.7, 802.11-2024
  PMF, WFA Table 4.
- The ML probe and BTM detectors aren't calibrated (`UNKNOWN`).

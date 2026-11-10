# Checkpoint 1 report: Spec-Aware Wi-Fi 7 Configuration Explorer (MCP)

CS 211 Fall 2026, Project F · Week 2 · repo `main` at `85ad39c`

**What we built.** An MCP server (`wifi7-explorer`) that takes a Wi-Fi 7 MLO candidate
(AP MLD links, client settings, ordered actions) and checks it in stages without booting
a guest: **P0** format (strict Pydantic models), **P1** sourced rules from `rules.yaml`,
**P2** a basic support check against committed runs. Only then does **P3** run an approved
hostap hwsim test in a fresh Docker + UML + mac80211_hwsim guest and return a behavior
record. Tools: `get_model`, `validate_candidate`, `explain_rule`, `run_hwsim_test`.
Passing means **"passes modeled rules"**, not full 802.11be compliance.

**Demo reference:** Jasmine's Claude Code session of 2026-11-06,
`docs/demo-transcript-terminal.txt` (steps 2–6, then step 1, `get_model`). A second
session on an Intel Mac is in `docs/demo-transcript.md`.

| Checkpoint 1 item | Evidence |
|---|---|
| Real baseline | hostap `43ee60e1` + wireless-next `21b4248b`, image built by `scripts/build-env.sh`. Three passing runs of `eht_mld_sae_two_links` (`runs/baseline/`, 2026-10-29). Plain SAE breaks §12.12.9, so it's the *environment* baseline only; the legal baseline is anchor F02 (below). |
| Rule registry with citations and exceptions | `rules.yaml`: 16 rules + 3 open questions. 6 normative (802.11be "shall" clauses, WFA guide as guidance), 1 dependency, 9 harness (action order). Each lists section, PDF page, strength and who checked it, plus exceptions and allowed/disallowed examples. 15 `reviewed`, 1 `draft`. Shown by `explain_rule` in the demo. |
| ≥4 checked rules with unit tests | 6 coded setting rules, incl. security/MLO rules `SEC.MLD_COMMON_SUITES` (§12.6.2), `SEC.MLD_CLIENT_COMMON_AKM` (§12.6.3.1), `SEC.EHT_SAE_AKM`, `SEC.EHT_SAE_H2E`, `SEC.EHT_BEACON_PROT` (§12.12.9). 9 action-state rules (`AO.*`), e.g. `AO.NO_LINKS_LEFT` (§35.3.6.3, §35.3.7.5.2). Each coded rule has passing and failing fixtures (for `AO.*`, the registry's own allowed/disallowed examples); 439 tests pass (2026-11-06, with Docker and hostap source checks). |
| P0 malformed rejection | `link_id: "0"` → `MALFORMED`, `P0.TYPE_ERROR` (demo step 2). |
| P1 spec rejection (link-AKM intersection) | Links offering only SAE / only SAE-EXT-KEY → `SEC.MLD_COMMON_SUITES`, 802.11be §12.6.2, PDF p. 411, "shall" (step 3). |
| Action-ordering example | `rekey_gtk_now` before `associate` → `AO.ASSOC_REQUIRED`, labeled a harness rule, not a spec rule (step 4). |
| Unknown / unmodeled case | WPA-PSK + SAE-EXT-KEY on every link and client → `SPEC_UNDETERMINED`, `UND.AKM_PREFERENCE` (the order is in the WPA3 Specification, which we don't have) (step 5). |
| Basic P2 | The legal candidate is `SUPPORTED` by `eht_mld_sae_ext_two_links_client_bp`, with 3 committed runs (step 6). No valid-but-unsupported case came up, so none is claimed. |
| Real accepted run through MCP | `run_hwsim_test` → run `1793990016`, PASS: SAE-EXT-KEY, links `0x3`, data on both links, BIGTK set (step 6). The Mac session's run `1793989115` passed too. |
| ≥4 smoke-tested dimensions | 6, each with ≥2 values that run and pass the rules (`surface_candidates.csv`, `runs/smoke/`): AP AKM, client AKM (SAE-EXT-KEY / OWE), PTK rekey and GTK rekey (unset / 5 s), link advertised disabled (0 / 1), link removal (absent / present). |
| Anchor families | F02 SAE-EXT-KEY two-link, F08 PTK rekey, F09 GTK rekey, F06 link removal: each `PASS` with 3 runs of identical behavior signature (`anchor_coverage.csv`). 32 committed runs in all. |

**Findings and decisions.**
- **Client beacon protection.** hostap's MLD tests leave the client's `beacon_prot` off, which
  802.11be §12.12.9 requires on EHT STAs. We added `_client_bp` wrappers that run hostap's
  own tests with it on; the originals run only as labeled negative experiments.
- **Normative vs. harness.** `AO.*` rules say a sequence makes no sense for our harness, not
  that it breaks 802.11be; outputs label each rule's kind.
- **Conservative P2.** P2 cites only runs of tests that pass the modeled rules and never infers
  `UNSUPPORTED_IMPLEMENTATION` from missing evidence. P0 allows only the link layouts we've
  run (one link, or two on different channels); that's a testing limit, not a Wi-Fi rule.

**Limits and next steps.** `AO.BSS_TM_NEEDS_BSS_TRANSITION` is still a draft. The ML probe and
BTM detectors aren't calibrated yet (`UNKNOWN`). All committed evidence comes from one Intel
Mac; Windows/WSL has passed trial runs (`docker/README.md`) but has no committed runs. `run_hwsim_test` has
twice reported the image missing when it existed; a retry works, and the cause is open.
Rules are Python predicates, not ConfigSpace yet. Week 3: ≥8 dimensions, pairwise search,
and a ~20-candidate campaign with stage counts.

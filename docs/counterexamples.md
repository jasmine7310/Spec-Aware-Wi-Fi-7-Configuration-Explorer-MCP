# Counterexample suite for the formalization (#108)

The roadmap (Week 5) asks to "test the formalization against counterexamples so rules
don't eliminate semantically permitted cases". This page lists the roadmap's five cases,
the outcome each must get, and an MCP walk-through of them.

- The cases and their expected outcomes are in `src/explorer/counterexamples.py`
  (`CASES`). Each one points at the fixture (`rules/fixtures/<ID>.json`) or the committed
  run it comes from, so the suite and the rule fixtures can't drift apart.
- `tests/test_counterexamples.py` checks every case directly and over MCP
  (`validate_candidate`, `why_pruned`, `explain_rule`): status, the stage it reaches, every
  finding's rule ID and, where it matters, P2's status, limit and recorded refusals.
- `counterexamples.evaluate()` gives the same results as data (for the Week 6 metrics).

## The cases

| Roadmap case | Case | Source | Expected | why_pruned role |
|---|---|---|---|---|
| Different AP-link AKM lists, shared selected AKM: **must pass P1** | `akm_lists_differ_same_rsnxe`: link 0 `[SAE-EXT-KEY, SAE]`, link 1 `[SAE-EXT-KEY]`, client SAE-EXT-KEY | fixture `SEC.MLD_SAME_RSNXE` "different AKM lists, same bit" (= `SEC.MLD_COMMON_SUITES` "different AKM lists sharing an AKM") | `PASSES_MODELED_RULES`, no findings | not pinned (P2: depends on committed runs) |
| … the other direction | `akm_lists_differ_rsnxe_differs`: link 0 `[SAE-EXT-KEY, OWE]`, link 1 `[OWE]`, client OWE | fixture `SEC.MLD_SAME_RSNXE` "SAE-EXT-KEY on one link only" | `SPEC_RULE_VIOLATION` at P1: `SEC.MLD_SAME_RSNXE` only (not `SEC.MLD_COMMON_SUITES`) | `pruned` / P1 |
| A malformed link ID | `link_id_repeated`: both links ID 0 | `SEC.MLD_SAME_RSNXE` positive fixture, changed | `MALFORMED` at P0: `P0.INVALID_VALUE` | `malformed` / P0 |
| | `link_id_out_of_range`: link ID 15 | same | `P0.OUT_OF_RANGE` | `malformed` / P0 |
| | `link_id_negative`: link ID -1 | same | `P0.OUT_OF_RANGE` | `malformed` / P0 |
| | `link_id_wrong_type`: link ID `"0"` | same | `P0.TYPE_ERROR` | `malformed` / P0 |
| | `link_id_not_configured`: `link_remove` on link 5 | same | `P0.INVALID_VALUE` | `malformed` / P0 |
| A legal-but-unsupported helper | `disable_mld_after_link_remove`: `link_remove`, then `DISABLE_MLD` | campaign run `campaigns/seed0-2026-11-13/1794557044` | `PASSES_MODELED_RULES`; P2 `UNSUPPORTED_IMPLEMENTATION`, limit `P2.DISABLE_MLD_AFTER_LINK_REMOVE`, citing refusal 1794557044 | `unsupported` / P2 |
| A missing / ambiguous requirement | `und_assoc_without_ap_links` | fixture `UND.ASSOC_WITHOUT_AP_LINKS` "associate again after every link is removed" | `SPEC_UNDETERMINED` at P1: `UND.ASSOC_WITHOUT_AP_LINKS` | `undetermined` / P1 |
| | `und_sta_state_while_mld_disabled` | fixture "rekey while the AP MLD is disabled, no disconnect" | `UND.STA_STATE_WHILE_MLD_DISABLED` | `undetermined` / P1 |
| | `und_akm_preference` | fixture "SAE-EXT-KEY and WPA-PSK both usable" | `UND.AKM_PREFERENCE` | `undetermined` / P1 |
| A rekey action before association | `rekey_before_association`: `rekey_gtk_now`, then `associate` | fixture `AO.ASSOC_REQUIRED` "rekey before associating" | `SPEC_RULE_VIOLATION` at P1: `AO.ASSOC_REQUIRED` (a harness rule) | `pruned` / P1 |

Notes on the cases:

- **The AKM case has two directions since #95.** 802.11be §12.6.2 lets the links' AKM lists
  differ as long as they share one (`SEC.MLD_COMMON_SUITES`'s exception). The same
  sentence requires the same RSNXE on every link, with no per-link exception
  (`SEC.MLD_SAME_RSNXE`). So a shared AKM passes only when the lists also give the same
  RSNXE. The test checks both pairs of lists really differ and share an AKM.
- **The permitted AKM case isn't executable yet.** It passes P1, but no committed run used
  `SAE` in an AP link's list, so P2 is `UNRESOLVED` and the planner's role is `not_run`
  (pruned for lack of evidence, not by a rule). The test only requires that no rule prunes
  it; its role would change once such a run is committed.
- **Unsupported isn't inferred.** `UNSUPPORTED_IMPLEMENTATION` comes only from an entry of
  `support.IMPLEMENTATION_LIMITS` with recorded refusals (here 4 campaign runs that came
  back `REJECTED` with "DISABLE_MLD failed"), never from missing evidence.
- **Every `UND.*` entry has a case** (a test checks this), so a new open question needs one.
- **Removing a link twice** is a different case from a link ID that was never configured:
  that's `AO.LINK_MUST_EXIST`, a P1 harness rule, not P0.

## MCP walk-through

Run on 2026-11-24 by Claude (AI agent) in Claude Code, through the `wifi7-explorer` MCP
server of this repo. Outputs are cut to the fields that matter; nothing booted.

**1. Different AKM lists, shared AKM, same RSNXE.** `validate_candidate` with link 0
`["SAE-EXT-KEY", "SAE"]`, link 1 `["SAE-EXT-KEY"]`, client `["SAE-EXT-KEY"]`:

```json
{"status": "PASSES_MODELED_RULES", "stage_reached": "P2", "findings": [],
 "p2": {"status": "UNRESOLVED", "all_values_evidenced": false,
        "note": "... No passing run under the modeled rules for: ap_akm=SAE."}}
```

No rule prunes it. P2 says no committed run has shown `SAE` in an AP link's list yet.

**2. Different AKM lists, shared AKM, different RSNXE.** Link 0 `["SAE-EXT-KEY", "OWE"]`,
link 1 `["OWE"]`, client `["OWE"]`:

```json
{"status": "SPEC_RULE_VIOLATION", "stage_reached": "P1",
 "findings": [{"rule_id": "SEC.MLD_SAME_RSNXE", "kind": "normative",
   "reason": "AP MLD links advertise different RSNXEs: the SAE hash-to-element bit is set on link 0 ['SAE-EXT-KEY', 'OWE'] but not on link 1 ['OWE'], which advertise no RSNXE",
   "sources": ["IEEE-802.11be-2024 §12.6.2 RSNA selection, PDF 411 (printed 410) (shall)",
               "hostap src/ap/wpa_auth_ie.c:549-557 (code)",
               "hostap src/ap/wpa_auth_ie.c:601-611 (code)"]}]}
```

Only `SEC.MLD_SAME_RSNXE`: the shared OWE satisfies `SEC.MLD_COMMON_SUITES`.

**3. Malformed link ID.** Both links with `link_id` 0:

```json
{"status": "MALFORMED", "stage_reached": "P0",
 "findings": [{"rule_id": "P0.INVALID_VALUE",
               "reason": "config.ap: links[].link_id must not repeat values"}],
 "note": "Rejected at P0: the input doesn't fit the model, so the rules weren't checked."}
```

**4. Legal but unsupported.** `why_pruned` on run 1794557044's candidate (`associate`,
`rekey_gtk_now`, `link_remove` link 1, `DISABLE_MLD`, `DISCONNECT`, `ENABLE_MLD`,
`RECONNECT`):

```json
{"role": "unsupported", "pruned": true, "stage": "P2", "status": "PASSES_MODELED_RULES",
 "findings": [],
 "p2": {"status": "UNSUPPORTED_IMPLEMENTATION", "limit": "P2.DISABLE_MLD_AFTER_LINK_REMOVE",
        "run_ids": ["1794557044", "1794557059", "1794557071", "1794557082"],
        "note": "... hostapd behavior at the pinned commit, not a Wi-Fi rule. ... (sources: hostapd/ctrl_iface.c:3670-3708, src/ap/hostapd.c:3744-3757)."},
 "note": "Pruned at P2: it matches an implementation limit with recorded refusals (p2.limit). Not a Wi-Fi rule."}
```

**5. Missing requirement.** `why_pruned` on `associate`, `link_remove` link 1,
`link_remove` link 0, `associate`:

```json
{"role": "undetermined", "pruned": true, "stage": "P1", "status": "SPEC_UNDETERMINED",
 "findings": [{"rule_id": "UND.ASSOC_WITHOUT_AP_LINKS", "kind": "open_question",
   "reason": "actions[3] (associate): every AP link was removed; our sources don't say what associating with an AP MLD that has no affiliated APs does",
   "sources": [{"doc": "IEEE-802.11be-2024", "location": "§35.3.6.3 Removing affiliated AP(s)",
                "page": "PDF 515-518 (printed 514-517)", "strength": "shall"}, "..."]}],
 "note": "Held at P1: an open question (UND.*) applies, so it goes to the review queue, never the default campaign. Neither approved nor a violation."}
```

**6. Rekey before association.** `why_pruned` on `rekey_gtk_now`, then `associate`:

```json
{"role": "pruned", "stage": "P1", "status": "SPEC_RULE_VIOLATION",
 "findings": [{"rule_id": "AO.ASSOC_REQUIRED", "kind": "harness",
   "reason": "actions[0] (rekey_gtk_now): needs an associated STA, but the STA hasn't associated yet",
   "sources": [{"doc": "hostap", "location": "src/ap/wpa_auth.c:7906-7914", "strength": "code",
                "says": "REKEY_GTK schedules a rekey and succeeds with no STA; its evidence needs one (harness)."}, "..."],
   "validation": "none"}],
 "note": "Pruned at P1: ... AO.* and other harness/policy rules keep candidates meaningful for our experiments; they aren't Wi-Fi specification rules."}
```

`validation: "none"`: `AO.ASSOC_REQUIRED` is one of the rules without experimental
validation (`rules/validation.json`; see the audit, #109).

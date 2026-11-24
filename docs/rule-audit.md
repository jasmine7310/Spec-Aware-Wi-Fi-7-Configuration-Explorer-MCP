# Rule audit: false pruning and false admission (#109)

Where could a modeled rule prune a candidate the standard permits, or admit one it forbids?
This audits every entry of `rules.yaml` (10 `SEC.*` rules, 9 `AO.*` rules, 3 `UND.*` open
questions) and the one implementation limit P2 applies, against:
- each rule's predicate and exceptions (`rules.yaml`) and code (`explorer.validate`);
- its fixtures (`rules/fixtures/<ID>.json`, run by `tests/test_rule_fixtures.py`);
- `spec_coverage.csv` (which clauses have a rule, which don't, and why);
- `rules/validation.json` (each rule's experimental validation, `scripts/check_consistency.py`);
- the labeled negative experiments (`runs/experiments/`, `runs/rejected/`, `consistency.NEGATIVE_BY_DESIGN`);
- the planner funnel in `campaign_plan.json`.

**No new reading of the standards is made here**, except the WFA cipher rows behind F13,
which Michelle read for this audit on 2026-11-24. Every other clause citation below is one
`rules.yaml` or `spec_coverage.csv` already records with a person's check; for the rekeying
clauses (802.11-2024 §12.6.19, §12.7.6.6, §12.7.7.4 and 802.11be §12.6.19) Michelle added
that check for this audit on 2026-11-24. Where a finding
would need a clause read in the PDF, it says so and stops there (marked *needs a person's
check*). Nothing in this file changes a rule.

`tests/test_rule_audit.py` checks that every rule and open question in `rules.yaml` has a
row in the summary table below, so a new rule can't skip the audit.

## Where pruning actually happens

The planner enumerates 4608 assignments of the 11 admitted dimensions (`campaign_plan.json`,
`funnel`). Only three rules ever reject one; the rest can't fire in this space:

| Rule | Assignments rejected | Kind | Experimental validation |
|---|---|---|---|
| `SEC.SAE_PWE_NEEDS_SAE` | 2560 | dependency | **none** |
| `SEC.MLD_CLIENT_COMMON_AKM` | 2304 | normative | cited runs only (the legal side) |
| `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E` | 128 | dependency | a committed refusal (`runs/rejected/1794384673`) |

An assignment can break several, so the three add up to more than the 3456 rejected; 1152
pass. Then P2 marks 288 of those `UNSUPPORTED_IMPLEMENTATION` (`DISABLE_MLD` after
`link_remove`, below), leaving 864 executable.

So for the campaigns, false pruning can only come from these three rules and the P2 limit.
**The rule that prunes the most has no experimental validation** (finding F1).

The other rules guard candidates outside the admitted values: hostap's own tests, the
agent's free-form candidates (MCP `validate_candidate`, `run_candidate`), and the
minimizer's probes, which apply deltas one at a time and can produce any combination.

## Summary

Validation is `rules/validation.json`'s: **broken** (a committed run breaks the rule and
shows what the implementation does), **cited** (only runs of the legal side) or **none**.
"Prune risk" and "admit risk" are this audit's reading of the predicate against the
sources it cites.

| ID | Kind | Prunes in campaigns | Validation | Prune risk | Admit risk | Findings |
|---|---|---|---|---|---|---|
| `SEC.MLD_COMMON_SUITES` | normative | no | cited | low (exception fixture) | low (model-level) | F8 |
| `SEC.MLD_SAME_RSNXE` | normative | no | broken | reading-dependent | low | F5 |
| `SEC.MLD_CLIENT_COMMON_AKM` | normative | 2304 | cited | low (new exception fixture) | low | F2, F11 |
| `SEC.EHT_BEACON_PROT` | normative | no (fixed) | broken | none | none | — |
| `SEC.PMF` | normative | no (P0) | cited | none | WFA mode tables | F9 |
| `SEC.EHT_SAE_AKM` | normative | no | broken | low | low | — |
| `SEC.EHT_SAE_H2E` | normative | no | cited | low | 6 GHz unmodeled | F10 |
| `SEC.SAE_PWE_NEEDS_SAE` | dependency | 2560 | **none** | by design | none | F1, F11 |
| `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E` | dependency | 128 | broken | low (new exception fixture) | unmodeled triggers | F11 |
| `SEC.MLO_PASSWORD_NEEDS_WPA3` | guidance | no | **none** | reading-dependent | WFA mode tables | F3, F9 |
| `AO.ASSOC_REQUIRED` | harness | no | **none** | by design (policy) | none | F4, F6 |
| `AO.ML_PROBE_STATE` | harness | no | **none** | by design (policy) | none | F6 |
| `AO.LINK_MUST_EXIST` | harness | no | **none** | by design (policy) | none | F6 |
| `AO.NO_LINKS_LEFT` | harness | no | cited | low | none | — |
| `AO.RECONFIG_DELETE_ACTIVE` | harness | no | **none** | low | none | F6 |
| `AO.RECONFIG_ADD_ABSENT` | harness | no | **none** | by design (policy) | none | F6 |
| `AO.RECONNECT_AFTER_DISCONNECT` | harness | no | **none** | none (a no-op) | none | F6, F7 |
| `AO.ENABLE_AFTER_DISABLE` | harness | no | **none** | by design (harness) | none | F6, F7 |
| `AO.BSS_TM_NEEDS_BSS_TRANSITION` | harness | no | **none** | by design (policy) | none | F6 |
| `UND.AKM_PREFERENCE` | open question | no | none | n/a | n/a | F12 |
| `UND.STA_STATE_WHILE_MLD_DISABLED` | open question | no | none | n/a | n/a | F12 |
| `UND.ASSOC_WITHOUT_AP_LINKS` | open question | no | cited | n/a | n/a | F12 |

"By design" means the rule knowingly prunes candidates the implementation would run, because
they're meaningless or untested for our experiments. That's a stated limit, not a bug: the
rule's `kind` (dependency, harness) already says it isn't a Wi-Fi requirement.

## Security rules

### SEC.MLD_COMMON_SUITES (normative, §12.6.2)
- **Assumes** the AP MLD's RSNE fields other than the AKM list and pairwise cipher (group cipher, group management cipher, RSN capabilities) can't differ per link. True by construction: P0 has one setting for each per AP MLD, so this half of §12.6.2 holds without a check.
- **Could wrongly prune:** different AKM lists that share an AKM. It doesn't: the predicate needs only a non-empty intersection, and the exception fixture "different AKM lists sharing an AKM" passes.
- **Doesn't catch:** per-link MFPR differences, which §12.6.2 allows. Not catchable either way: P0 has one PMF setting (`spec_coverage.csv`, §12.6.3.2, `OUT_OF_SCOPE`). Stated limit (F8).

### SEC.MLD_SAME_RSNXE (normative, §12.6.2)
- **Assumes** the strict reading of "RSNXE if included" (Michelle, #95): once any link includes an RSNXE, every link advertises the same one. Jasmine's per-link reading on #98 is recorded in the rule's notes.
- **Could wrongly prune:** under the per-link reading, link 0 [SAE-EXT-KEY, OWE] with link 1 [OWE] is legal. The rule rejects it, and `runs/experiments/1794875139` shows hostapd accepts it and the client associates. A reading choice, recorded with both readings and the run (F5). It can't prune in the campaigns, where every link gets the same AKM.
- **Doesn't catch:** RSNXE bits other than SAE hash-to-element. Every other bit comes from settings left unset on every link (rule notes), so none can differ today.

### SEC.MLD_CLIENT_COMMON_AKM (normative, §12.6.3.1)
- **Assumes** a client with no common AKM declines to associate at all, not on fewer links (rule notes, #64 audit).
- **Could wrongly prune:** a client allowing several AKMs, one of them common. It doesn't: new exception fixture "client allows several AKMs, one of them common" passes (F11).
- **Doesn't catch:** the client's pairwise and group cipher being common. Holds by construction: `SEC.MLD_COMMON_SUITES` forces one pairwise cipher, hostapd derives the group cipher, and the adapter lets the client allow both CCMP and GCMP-256 (rule notes).
- **Validation:** cited runs only, so no committed run shows a client declining (F2). It's the second-largest pruner.

### SEC.EHT_BEACON_PROT (normative, §12.12.9)
- A fixed setting: beacon protection has one admissible value, so it can't wrongly prune a campaign candidate. hostap's tests without client beacon protection break it (`NEGATIVE_BY_DESIGN`), which is its validation. No finding.

### SEC.PMF (normative, 802.11-2024 §11.52)
- P0 has no "PMF disabled" value, so the rule never runs as a check (its negative fixture expects `MALFORMED`).
- **Doesn't catch:** the WFA mode tables' Required-vs-Capable choice (Tables 5, 8, 15). Guidance by mode, deliberately not coded (rule exceptions). Stated limit (F9).

### SEC.EHT_SAE_AKM and SEC.EHT_SAE_H2E (normative, §12.12.9)
- Fire only when plain SAE is the one usable AKM; with another family usable too, the candidate is `UND.AKM_PREFERENCE` (exception fixtures). So they can't prune a candidate whose negotiated AKM is unknown.
- Plain SAE isn't an admitted value, so neither prunes in the campaigns. The official baseline breaks `SEC.EHT_SAE_AKM` and is labeled negative (`NEGATIVE_BY_DESIGN`).
- **`SEC.EHT_SAE_H2E` doesn't catch:** 6 GHz, where hostapd switches an unset `sae_pwe` to both methods (rule exceptions). Out of scope: the project excludes 6 GHz and our links are on 2.4 GHz (`spec_coverage.csv`, Table 8 6 GHz row). Stated limit (F10).

### SEC.SAE_PWE_NEEDS_SAE (dependency)
- **Prunes by design:** `sae_pwe` set with no SAE-family AKM. hostapd accepts that and the setting does nothing (rule sources). It's not a spec violation; the rule removes combinations that duplicate the same behavior. That's why it prunes 2560 assignments: every OWE assignment with a `sae_pwe` value set.
- **Could wrongly prune:** `sae_pwe` set where a link also offers SAE-EXT-KEY next to OWE. It doesn't: the predicate needs an SAE-family AKM in the list, not only SAE-family AKMs. New exception fixture "AP and client sae_pwe with SAE-EXT-KEY next to OWE" passes (F11).
- **Validation: none.** "The setting has no effect" is read from code, never run (F1).

### SEC.SAE_H2E_ONLY_NEEDS_STA_H2E (dependency)
- Validated by a refusal: `runs/rejected/1794384673` (AP `sae_pwe`=1, client unset) never associated.
- **Could wrongly prune:** an H2E-only AP whose links also offer OWE, where hostapd advertises no H2E-only selector (`src/ap/ieee802_11.c:166-170`, cited by the rule). It doesn't: the predicate needs a link with only SAE-family AKMs. New exception fixture "H2E-only AP whose links also offer OWE, unset client" passes (F11). That fixture shows the rule's reading; no run has tried it.
- **Doesn't catch:** the other triggers it lists as unmodeled (a password identifier, 6 GHz). Stated in the rule's exceptions.

### SEC.MLO_PASSWORD_NEEDS_WPA3 (guidance, WFA §3.2)
- **Assumes** "the network" means each link (each link is a BSS in Tables 5 and 8; rule notes). A reading of guidance, checked by Michelle (F3).
- No admitted value reaches it (`ap_akm`, `sta_akm` are SAE-EXT-KEY or OWE), so it can't prune in the campaigns.
- **Validation: none** (F3). The adapter can run WPA-PSK (`adapter._PSK`), so a labeled negative run is feasible.

## Action-order rules: what would validate each

Every `AO.*` rule is `kind: harness`: it encodes what hostap's code needs or what our
experiments assume, not a Wi-Fi requirement. Several prune sequences hostap would execute
(F4, F6). That's intended: the rules keep candidates to sequences hostap's tests perform.

8 of the 12 rules and questions with no validation are `AO.*`. `AO.NO_LINKS_LEFT` has cited
runs. For each, here is what would count as validation. Following `scripts/check_consistency.py`,
a committed run that breaks the rule counts. It would be a labeled negative experiment in
`runs/experiments/` (or `runs/rejected/` if refused), with the log line showing the
implementation's response.

| Rule | A breaking candidate | Expected response, per the rule's sources | Adapter can run it? | Feasible |
|---|---|---|---|---|
| `AO.ASSOC_REQUIRED` | `[rekey_gtk_now]` or `[link_remove]` before `associate` | hostapd accepts: `REKEY_GTK` succeeds with no STA (`src/ap/wpa_auth.c:7906-7914`); `hostapd_link_remove()` checks only that it's an AP MLD (`src/ap/hostapd.c:477`) | yes | **yes**: it would show the rule is our policy for these actions |
| `AO.ML_PROBE_STATE` | `[ml_probe_req]` with no scan | wpa_supplicant fails (`wpa_supplicant/ctrl_iface.c:12946-12955`) | no: `ml_probe_req` and `scan` aren't adapter actions | no, until the adapter supports them |
| `AO.LINK_MUST_EXIST` | `[associate, link_remove(1), link_remove(1)]` | hostapd doesn't check (`src/ap/hostapd.c:475-494`) | partly: the adapter refuses it first ("link already removed"), so a run shows the adapter, not hostapd | only after the adapter check is lifted for a labeled experiment |
| `AO.RECONFIG_DELETE_ACTIVE` | delete the same link twice | wpa_supplicant fails, "not a valid delete link" (`ctrl_iface.c:12847-12853`) | no: `setup_link_reconfig` isn't an adapter action | no |
| `AO.RECONFIG_ADD_ABSENT` | add a link the STA has | wpa_supplicant doesn't check (rule exceptions) | no | no |
| `AO.RECONNECT_AFTER_DISCONNECT` | `[associate, RECONNECT]` | replies OK and does nothing (`wpa_supplicant/ctrl_iface.c:13925-13929`) | yes: the adapter waits for `CTRL-EVENT-CONNECTED` and logs `EXPLORER-NO-EVENT` | **yes** |
| `AO.ENABLE_AFTER_DISABLE` | `[associate, ENABLE_MLD]` | hostapd fails, "already enabled" (`src/ap/hostapd.c:3671-3675`) | yes: the adapter logs `EXPLORER-REJECTED … ENABLE_MLD failed` | **yes**: a refusal, so `runs/rejected/` |
| `AO.BSS_TM_NEEDS_BSS_TRANSITION` | BSS TM request with `bss_transition` off | hostapd sends it anyway (`src/ap/wnm_ap.c:959-1063`) | no: not an adapter action | no |

So 3 are feasible now (`AO.ASSOC_REQUIRED`, `AO.RECONNECT_AFTER_DISCONNECT`,
`AO.ENABLE_AFTER_DISABLE`). One more needs a change to the adapter (`AO.LINK_MUST_EXIST`), and 4
need actions the adapter doesn't support (F6). Of the non-`AO` unvalidated rules,
`SEC.SAE_PWE_NEEDS_SAE` and `SEC.MLO_PASSWORD_NEEDS_WPA3` are feasible too (F1, F3).

**What the minimizer showed (#107).** `AO.ENABLE_AFTER_DISABLE` and
`AO.RECONNECT_AFTER_DISCONNECT` tie four action steps together: `ENABLE_MLD` needs a
`DISABLE_MLD` and a `DISCONNECT` before it, and `RECONNECT` needs a `DISCONNECT`. A
reduction that removes one delta at a time can't drop the AP restart while keeping the
reconnect, because every intermediate step breaks one of the rules. `contrasts/c3/first-attempt/`
kept the restart in its minimal cause for that reason, and the reconnect alone turned out to
be enough. That's not a false prune: each blocked sequence really is outside the rules. It
is a limit of minimizing over single deltas (F7).

## Open questions

The `UND.*` entries make a candidate `SPEC_UNDETERMINED`, neither approved nor a violation.
They prune nothing on their own: the planner sends such candidates to its review queue, which
is empty for the admitted space (`campaign_plan.json`, `review_queue`).
- `UND.AKM_PREFERENCE`: needs the WPA3 Specification, which isn't one of our sources (`spec_coverage.csv`, Table 3 AKM row).
- `UND.STA_STATE_WHILE_MLD_DISABLED`: a run could observe it. #107's runs show the client still reports both links valid after `DISABLE_MLD` until its own `DISCONNECT` (`contrasts/c3/first-attempt/README.md`). That's one observation, not an answer: the open question asks about post-association actions while disabled.
- `UND.ASSOC_WITHOUT_AP_LINKS`: no source says what associating after every link is removed does.

Validating an open question means answering it, so none is "unvalidated" in the same sense
as a rule (F12).

## The implementation limit (P2)

`support.IMPLEMENTATION_LIMITS` has one entry: `DISABLE_MLD` after `link_remove` fails in
hostapd (`P2.DISABLE_MLD_AFTER_LINK_REMOVE`, recorded refusals `1794557044`, `1794557059`,
`1794557071`, `1794557082`). It marks 288 rule-passing assignments `UNSUPPORTED_IMPLEMENTATION`.
- It isn't a Wi-Fi rule, and its status says so; a candidate it blocks is still legal.
- It rests on four committed refusals, never on missing evidence, so it can't prune a sequence hostapd hasn't refused.

## Admission gaps outside the rules

Requirements no rule models, so a candidate that breaks them would pass P1:
- **Unread clauses.** `spec_coverage.csv` still has 4 `TODO` rows: 802.11be §12.6 (other subclauses) and §35.3.7 (other subclauses), the 802.11-2024 clause on protecting robust management frames, and WFA Table 4's other rows. Until they're read, a requirement there may be missing. Tracked by #112.
- **The pairwise cipher.** `ap_pairwise_cipher` admits CCMP (the default) or GCMP-256, one cipher on every link. Michelle read the cipher rows on 2026-11-24 (`spec_coverage.csv`): WFA Table 3's Pairwise Cipher Suite row (pp. 8-9) names no suite, and for an AP with EHT, Tables 5 (Transition Mode), 8 (WPA3-Personal Only) and 15 (Enhanced Open Only) all give both GCMP-256 and CCMP-128 MAND. So neither admitted value matches the tables on its own: CCMP-only leaves out GCMP-256 and GCMP-256-only leaves out CCMP-128. Only an AP offering both (`rsn_pairwise=CCMP GCMP-256`) does, and `ap_pairwise_cipher` takes one value, so it can't express that. This is WFA guidance, not an IEEE "shall", and the mode tables aren't coded (F9). It isn't a false admission of one value over the other: every admitted candidate is a single-cipher AP. hostap's tests are single-cipher too, apart from transition mode: the MLD tests built on `eht_mld_ap_wpa2_params` use CCMP (`hostapd.wpa2_params` sets it, `tests/hwsim/hostapd.py:834`), and `start_eht_sae_ap` uses `CCMP GCMP-256` in transition mode and `GCMP-256` otherwise (`tests/hwsim/test_eht.py:170`) (F13).
- **WFA mode tables.** Which AKM, PMF and H2E values each WPA3 mode allows for EHT (Tables 5, 8, 15) aren't coded. For example, Table 8 disallows an EHT STA with H2E Only (`sta_sae_pwe`=1) except where every device supports EHT; our testbed has only EHT devices (`SEC.SAE_H2E_ONLY_NEEDS_STA_H2E` notes). Guidance by mode, stated as not coded (F9).
- **Static link disablement.** `indicate_disabled` uses hostapd's `mld_indicate_disabled`, a static testing option, not the TTLM procedure (§35.3.7.5.2 row). Only observed behavior is claimed for it.
- **Behavior after `link_remove`.** A PTK rekey (C1) or a reconnect (`contrasts/c3/`) after `link_remove` fails with reason 15 in every committed run. No rule forbids either: §12.6.19 permits rekeying, and §12.7.6.6 is a requirement on the Authenticator's behavior, not on a candidate (`spec_coverage.csv`, `NO_RULE`). These are behavior findings, not false admissions.

## Findings

Each finding has a fixture, an issue or a stated limit, as #109 asks.

| # | Finding | Disposition |
|---|---|---|
| F1 | `SEC.SAE_PWE_NEEDS_SAE`, the largest pruner (2560), has no experimental validation; "no effect" is read from code | **Issue (proposed):** a labeled run of OWE with `sae_pwe` set, compared with the same candidate without it |
| F2 | `SEC.MLD_CLIENT_COMMON_AKM` (2304 pruned) has only legal-side runs; none shows a client declining | **Issue (proposed):** a labeled run of AP SAE-EXT-KEY with a client allowing only OWE |
| F3 | `SEC.MLO_PASSWORD_NEEDS_WPA3` has no validation and rests on a per-link reading of "the network" | **Stated limit** (reading checked by Michelle, rule notes); **issue (proposed):** a labeled WPA-PSK-only run |
| F4 | `AO.ASSOC_REQUIRED` prunes sequences hostapd accepts (`REKEY_GTK` or `LINK_REMOVE` before association, associating twice) | **Stated limit:** a harness / policy rule (`kind: harness`, rule notes); validation run in F6 |
| F5 | `SEC.MLD_SAME_RSNXE` rejects a candidate that's legal under the per-link reading of §12.6.2 (run `1794875139`) | **Stated limit:** both readings recorded in the rule's notes, strict reading chosen on #95 |
| F6 | 8 `AO.*` rules have no validation; 3 are feasible now, 1 needs an adapter change, 4 need new adapter actions | **Issue (proposed):** labeled runs for `AO.ASSOC_REQUIRED`, `AO.RECONNECT_AFTER_DISCONNECT`, `AO.ENABLE_AFTER_DISABLE`; **stated limit** for the other 5 (table above) |
| F7 | The action-order rules tie the restart steps together, so single-delta minimization can't separate them (#107's first attempt) | **Stated limit** here and in `contrasts/c3/README.md`; grouping deltas that move together is the fix (Jasmine's point on #101) |
| F8 | Per-link MFPC / MFPR differences can't be expressed (one PMF setting) | **Stated limit:** `spec_coverage.csv`, §12.6.3.2 `OUT_OF_SCOPE` |
| F9 | WFA mode tables (PMF Required vs Capable, H2E Only for EHT STAs, PSK per mode) aren't coded | **Stated limit:** guidance by mode, in `SEC.PMF`'s exceptions and `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E`'s notes |
| F10 | 6 GHz behavior (unset `sae_pwe` becomes both methods) isn't modeled | **Stated limit:** the project excludes 6 GHz (`spec_coverage.csv`, Table 8 6 GHz row) |
| F11 | Three rules had no fixture for the permitted case they could wrongly prune | **Fixtures added:** `SEC.SAE_PWE_NEEDS_SAE`, `SEC.SAE_H2E_ONLY_NEEDS_STA_H2E`, `SEC.MLD_CLIENT_COMMON_AKM` (one exception fixture each) |
| F12 | The open questions have no validation, since validating one means answering it | **Stated limit:** listed above with what's known |
| F13 | WFA Tables 5, 8 and 15 give both GCMP-256 and CCMP-128 MAND for an AP with EHT (read 2026-11-24), but `ap_pairwise_cipher` admits one cipher per AP, so no admitted candidate enables both | **Stated limit:** mode-table guidance isn't coded (F9). **Issue (proposed):** add a `CCMP GCMP-256` value to `ap_pairwise_cipher` (needs a smoke run, a model.json regeneration and the adapter's client cipher list checked); coding the tables as a guidance rule would prune every admitted candidate, so that waits for the new value |

### Proposed follow-up issue

F1, F2, F3 and F6 share one follow-up: run the feasible breaking candidates as labeled negative
experiments, so `rules/validation.json` can count them. Each is a single candidate through
the adapter, committed in `runs/experiments/` or `runs/rejected/` with
`negative_experiment: true`, and a line in `runs/experiments/README.md`:
1. OWE on both links with `sae_pwe` set (`SEC.SAE_PWE_NEEDS_SAE`), next to the same candidate without it;
2. AP SAE-EXT-KEY, client OWE only (`SEC.MLD_CLIENT_COMMON_AKM`);
3. WPA-PSK only on both links and the client (`SEC.MLO_PASSWORD_NEEDS_WPA3`);
4. `[rekey_gtk_now, associate]` (`AO.ASSOC_REQUIRED`);
5. `[associate, RECONNECT]` (`AO.RECONNECT_AFTER_DISCONNECT`);
6. `[associate, ENABLE_MLD]` (`AO.ENABLE_AFTER_DISABLE`).

Runs 1 and 3–6 would take the unvalidated count from 12 to 7. Run 2 would move
`SEC.MLD_CLIENT_COMMON_AKM` from cited to broken. Together they'd give the two largest
pruners a run that breaks them.

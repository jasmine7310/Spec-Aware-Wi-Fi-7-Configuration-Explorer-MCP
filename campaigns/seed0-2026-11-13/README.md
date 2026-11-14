# Campaign `seed0-2026-11-13`

The first bounded pairwise campaign (issue #68): the 16 candidates of `campaign_plan.json`
(seed 0, issue #66), each run once in a fresh UML guest through the candidate adapter and
the experiment cache (`scripts/run_campaign.py`). Every candidate is the legal F02
configuration with `model.json`'s dimensions varied, passed the modeled rules when it was
launched (re-checked then, not only at planning) and was a P2 support probe (no committed
run of it existed). "Passes modeled rules" is all the legality claim means, never full
802.11be compliance.

Windows 11 + WSL2 Ubuntu 24.04 + Docker Desktop (Docker 29.9.2), image built from
`docker/Dockerfile` at repo commit `7609144` (`repo_docker_dir_modified: false` in every
manifest), hostap `43ee60e1`, wireless-next `21b4248b`, 2026-11-13. Each run folder's
manifest records the candidate, its validation, the cache key and its parts, the context
(campaign, seed, candidate ID, attempt) and the timeout (600 s). Single runs: P2 evidence,
not reproducibility trials. Files here: `campaign_plan.json` (the plan it ran), `results.json` (each candidate's
attempts), `rejected_cases.csv` (every case that didn't run or didn't come back
`ACCEPTED`) and `pruning_counts.json` (the funnel).

## Results

**12 `ACCEPTED`, 4 `REJECTED`, 0 `SETUP_FAIL`, 0 `TIMEOUT`**; 16 guest boots, no cache
hits, no retries, about 100 s in all. P0/P1 pruned 3456 of the 4608 enumerated
assignments before any guest launched (ConfigSpace and P1 agree on all of them).

| ID | Run | P3 | Candidate (F02 plus) | Reason |
|---|---|---|---|---|
| c01 | `1794557032` | ACCEPTED | OWE; CCMP; link 1 advertised disabled; actions: associate, LINK_REMOVE link 1 | |
| c02 | `1794557038` | ACCEPTED | SAE-EXT-KEY; AP pwe 2, STA pwe 1; GCMP-256; PTK 5 s; GTK 5 s; actions: associate, REKEY_GTK | |
| c03 | `1794557044` | REJECTED | SAE-EXT-KEY; AP pwe 1, STA pwe 2; CCMP; link 1 advertised disabled; PTK 5 s; actions: associate, REKEY_GTK, LINK_REMOVE link 1, DISABLE/ENABLE_MLD | actions[3] DISABLE_MLD: DISABLE_MLD failed |
| c04 | `1794557050` | ACCEPTED | OWE; GCMP-256; PTK 5 s; GTK 5 s; actions: associate, DISABLE/ENABLE_MLD | |
| c05 | `1794557059` | REJECTED | OWE; GCMP-256; link 1 advertised disabled; GTK 5 s; actions: associate, REKEY_GTK, LINK_REMOVE link 1, DISABLE/ENABLE_MLD | actions[3] DISABLE_MLD: DISABLE_MLD failed |
| c06 | `1794557065` | ACCEPTED | OWE; CCMP; actions: associate, REKEY_GTK, DISABLE/ENABLE_MLD | |
| c07 | `1794557071` | REJECTED | OWE; CCMP; PTK 5 s; GTK 5 s; actions: associate, REKEY_GTK, LINK_REMOVE link 1, DISABLE/ENABLE_MLD | actions[3] DISABLE_MLD: DISABLE_MLD failed |
| c08 | `1794557076` | ACCEPTED | OWE; GCMP-256; link 1 advertised disabled; PTK 5 s; actions: associate, REKEY_GTK, DISABLE/ENABLE_MLD | |
| c09 | `1794557082` | REJECTED | SAE-EXT-KEY; AP pwe 2, STA pwe 1; CCMP; link 1 advertised disabled; actions: associate, LINK_REMOVE link 1, DISABLE/ENABLE_MLD | actions[2] DISABLE_MLD: DISABLE_MLD failed |
| c10 | `1794557090` | ACCEPTED | SAE-EXT-KEY; AP pwe 1, STA pwe 2; GCMP-256; GTK 5 s; actions: associate | |
| c11 | `1794557096` | ACCEPTED | SAE-EXT-KEY; AP pwe unset, STA pwe unset; CCMP; link 1 advertised disabled; actions: associate, LINK_REMOVE link 1 | |
| c12 | `1794557101` | ACCEPTED | SAE-EXT-KEY; AP pwe 2, STA pwe 2; CCMP; link 1 advertised disabled; actions: associate, LINK_REMOVE link 1 | |
| c13 | `1794557107` | ACCEPTED | SAE-EXT-KEY; AP pwe 2, STA pwe unset; CCMP; link 1 advertised disabled; actions: associate, LINK_REMOVE link 1 | |
| c14 | `1794557112` | ACCEPTED | SAE-EXT-KEY; AP pwe 1, STA pwe 1; CCMP; link 1 advertised disabled; actions: associate, LINK_REMOVE link 1 | |
| c15 | `1794557120` | ACCEPTED | SAE-EXT-KEY; AP pwe unset, STA pwe 1; CCMP; link 1 advertised disabled; actions: associate, LINK_REMOVE link 1 | |
| c16 | `1794557126` | ACCEPTED | SAE-EXT-KEY; AP pwe unset, STA pwe 2; CCMP; link 1 advertised disabled; actions: associate, LINK_REMOVE link 1 | |

## Finding: `DISABLE_MLD` is refused after a link removal

All four `REJECTED` candidates remove link 1 (`LINK_REMOVE 4`) and later send
`DISABLE_MLD`; every candidate with only one of the two actions came back `ACCEPTED`
(c04, c06 and c08 do DISABLE/ENABLE_MLD without a link removal; c01 and c11-c16 remove the
link without DISABLE/ENABLE_MLD). From the
logs of `1794557082` (c09) and hostap at the pinned commit:

- after `LINK_REMOVE`, hostapd logs `Interface wlan7 disabled` for the removed link;
- `DISABLE_MLD` (sent to link 0's AP, as hostap's own test does) disables link 0, then tries
  every partner link of the AP MLD (`hostapd/ctrl_iface.c:3670-3708`); for the removed link,
  `hostapd_disable_iface()` returns -1 because the interface is already disabled
  (`src/ap/hostapd.c:3744-3757`, logged `Interface wlan7 already disabled`), so the command
  logs `Disabling AP MLD failed` (`hostapd/ctrl_iface.c:3701-3703`) and answers `FAIL`;
- the adapter then logs `EXPLORER-REJECTED actions[n] DISABLE_MLD: DISABLE_MLD failed`.

So the pinned hostapd refuses `DISABLE_MLD` on an AP MLD one of whose links was removed
(while having disabled the remaining link). This is hostapd control-interface behavior,
not a Wi-Fi rule: no modeled rule forbids the sequence, and hostap's tests never combine
the two actions. It is a recorded refusal by the implementation, the kind of evidence
`UNSUPPORTED_IMPLEMENTATION` needs; whether P2 should now answer that for candidates with
both actions is for the team to decide (#80's rule: only from a recorded refusal).

## Coverage

Pairs covered by committed `ACCEPTED` legal runs went from 126 to 233 of 250 feasible pairs
(0.932) with this campaign. The other 17 appeared only in the four `REJECTED` candidates.

## What changed after review (PR #92)

- P2 now reads these `REJECTED` runs as recorded refusals (`support.rejected_runs`), and
  answers `UNSUPPORTED_IMPLEMENTATION` for any candidate with `DISABLE_MLD` after a
  `link_remove` (`support.IMPLEMENTATION_LIMITS`, `P2.DISABLE_MLD_AFTER_LINK_REMOVE`), citing
  the four runs and the hostapd lines above. Michelle and the team agreed on the scope.
- The top-up campaign [`seed0-topup-2026-11-13`](../seed0-topup-2026-11-13/README.md) covered
  the 16 runnable pairs left (4 runs, all `ACCEPTED`); the remaining pair is the unsupported
  one.
- `campaign_plan.json` and `pruning_counts.json` here are this campaign's own copies (from
  commit `0c76e0a`); the repo root's files describe the latest campaign.

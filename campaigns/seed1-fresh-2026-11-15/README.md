# Campaign `seed1-fresh-2026-11-15`

A fresh pairwise campaign (seed 1, budget 20, `build_on_runs: false`), run by Nancy
(NancyLan0712) with the campaign MCP tools of issue #69 (`plan_campaign`, `run_campaign`). The
plan isn't the repo-root `campaign_plan.json`, which the CLI scripts write and read and which
this campaign left unchanged; the plan it ran is `campaign_plan.json` in this folder. Every
candidate is the legal F02 configuration with `model.json`'s dimensions varied, and was
re-checked at launch (P0/P1 and the adapter) before it booted. "Passes modeled rules" is all
the legality claim means, never full 802.11be compliance.

Windows 11 + WSL2 (Ubuntu 26.04.1), Docker Desktop (Docker 28.0.4), image
`sha256:e613517b…` rebuilt the same evening, after the stale-image problem found in #69
(its harness matches the repo: `repo_docker_dir_modified: false`), repo commit `6d29119`,
hostap `43ee60e1`, wireless-next `21b4248b`. 2026-11-16 07:05–07:07 UTC. Each run folder's
manifest records the candidate, its validation, the cache key and the context (campaign,
seed, candidate ID, attempt). Single runs: P2 evidence, not reproducibility trials.

## Results

**17 `ACCEPTED`, 0 `REJECTED`, 0 `SETUP_FAIL`, 0 `TIMEOUT`**; 17 guest boots, no cache hits,
no retries, no candidate refused at launch, about 2 minutes.

The plan has 9 allpairspy rows and 8 top-up rows. 15 candidates were support probes (P2
`UNRESOLVED`, every value with a passing legal run). c03 and c06 already had a committed run of
the same candidate (P2 `SUPPORTED`), but the cache had no entry under today's key, so they ran
again.

Coverage is unchanged: the earlier campaigns already covered every runnable pair (249 / 249).
This campaign adds a second, independent set of runs over a different design. Among them, 8
candidates combine SAE-EXT-KEY with a client `sae_pwe` (#88; c01, c04, c10, c11, c13, c14,
c16, c17), and 3 set the AP's `sae_pwe=1` with a client `sae_pwe` of 2 (c01, c10) or 1 (c13).
That AP value was REJECTED when the client's `sae_pwe` was unset (`runs/smoke/1794384673`).

| ID | Run | Source | Role |
|---|---|---|---|
| c01 | `1794812749` | allpairspy | probe |
| c02 | `1794812757` | allpairspy | probe |
| c03 | `1794812763` | allpairspy | supported |
| c04 | `1794812770` | allpairspy | probe |
| c05 | `1794812777` | allpairspy | probe |
| c06 | `1794812783` | allpairspy | supported |
| c07 | `1794812790` | allpairspy | probe |
| c08 | `1794812797` | allpairspy | probe |
| c09 | `1794812804` | allpairspy | probe |
| c10 | `1794812810` | top_up | probe |
| c11 | `1794812817` | top_up | probe |
| c12 | `1794812824` | top_up | probe |
| c13 | `1794812831` | top_up | probe |
| c14 | `1794812838` | top_up | probe |
| c15 | `1794812845` | top_up | probe |
| c16 | `1794812851` | top_up | probe |
| c17 | `1794812858` | top_up | probe |

Each candidate's choices are in `campaign_plan.json` and `results.json`; `get_campaign` over
MCP gives one in full.

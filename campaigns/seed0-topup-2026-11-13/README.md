# Campaign `seed0-topup-2026-11-13`

The top-up after [`seed0-2026-11-13`](../seed0-2026-11-13/README.md) (issue #68, after the
review on PR #92). Its plan builds on the runs already committed: the 21 assignments with a
committed legal `ACCEPTED` run count as covered, and the 288 assignments with a link removal
before `DISABLE_MLD` are `UNSUPPORTED_IMPLEMENTATION` at P2 (`P2.DISABLE_MLD_AFTER_LINK_REMOVE`,
from the first campaign's four refusals), so they aren't planned. The plan (`campaign_plan.json`
here, seed 0) is the 4 candidates that cover the 16 runnable pairs still uncovered.

Same environment as the first campaign: Windows 11 + WSL2 Ubuntu 24.04 + Docker Desktop
(Docker 29.9.2), the same image (`docker/` unchanged since `1c47f5b`;
`repo_docker_dir_modified: false`), hostap `43ee60e1`, wireless-next `21b4248b`, 2026-11-13.
The manifests record repo `0c76e0a`; the P2 and planner changes that chose these candidates
were not committed yet when they ran, and don't touch what the guest runs. Each manifest
records the candidate, its validation, the cache key and the context.

## Results

**4 `ACCEPTED`**, no `REJECTED`, `SETUP_FAIL` or `TIMEOUT`; 4 guest boots, no cache hits or
retries, about 34 s.

| ID | Run | P3 | Candidate (F02 plus) |
|---|---|---|---|
| c01 | `1794611970` | ACCEPTED | OWE; CCMP; PTK 5 s; GTK 5 s; actions: associate, REKEY_GTK, LINK_REMOVE link 1 |
| c02 | `1794611979` | ACCEPTED | OWE; GCMP-256; link 1 advertised disabled; GTK 5 s; actions: associate, LINK_REMOVE link 1 |
| c03 | `1794611986` | ACCEPTED | SAE-EXT-KEY; AP pwe 1, STA pwe 2; CCMP; link 1 advertised disabled; PTK 5 s; actions: associate, REKEY_GTK, DISABLE/ENABLE_MLD |
| c04 | `1794611993` | ACCEPTED | SAE-EXT-KEY; AP pwe 2, STA pwe 1; CCMP; link 1 advertised disabled; actions: associate, DISABLE/ENABLE_MLD |

## Coverage after both campaigns

20 campaign runs (16 + 4): 16 `ACCEPTED`, 4 `REJECTED`. Pairs covered by committed legal
`ACCEPTED` runs: **249 of 249 runnable (after P2) and 249 of 250 allowed by the modeled rules
(after P1)**. The one left, `link_remove=present` with `disable_enable_mld=present`, is
runnable by no assignment: every one of them is `UNSUPPORTED_IMPLEMENTATION`
(`pairwise_coverage.json`, `admissible_but_not_executable_pairs`). The next plan for seed 0 is
empty.

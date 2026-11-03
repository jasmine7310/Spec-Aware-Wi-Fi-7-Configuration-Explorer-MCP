# Anchor family runs

Real runs kept as evidence that each scenario family in
[`anchor_coverage.csv`](../../anchor_coverage.csv) reproduces: the roadmap asks for at
least three independent clean runs per family. Each family's other runs are in
`runs/smoke/` and `runs/calibration/`; `anchor_coverage.csv` lists all three.

All runs: 2026-11-03 (UTC), Windows 11 + WSL2 Ubuntu 24.04 + Docker Desktop (Docker
29.9.2), the `wifi7-env` image built from `docker/Dockerfile` (hostap `43ee60e1`,
wireless-next `21b4248b`), run through `explorer.runner.run_test()`, one fresh UML guest
per run. Full details are in each `manifest.json`. All six passed in hostap.

| Run ID | Family | Test |
|---|---|---|
| `1793694450` | F02 | `eht_mld_sae_ext_two_links` |
| `1793694455` | F02 | `eht_mld_sae_ext_two_links` |
| `1793694461` | F08 | `eht_mld_ptk_rekey` |
| `1793694467` | F09 | `eht_mld_gtk_rekey` |
| `1793694474` | F06 | `eht_mld_link_removal` |
| `1793694480` | F06 | `eht_mld_link_removal` |

For every family, the behavior signatures (`BehaviorRecord.signature()`) of its three
runs are identical; `tests/test_anchor_coverage.py` checks this. For F08 and F09 that
includes a run on an Intel Mac (`runs/calibration/`) and two on Windows + WSL2. In F06,
the three GTK rekeys and the disconnect after the last link's removal (see
`runs/smoke/README.md`) reproduced in all three runs.

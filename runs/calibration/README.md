# Calibration runs

Real runs kept as evidence for **how `src/explorer/signatures.py` recognizes a
behavior** in the logs. They are not baseline runs (see `baseline/README.md`) and are
single runs, not reproducibility trials.

| Run ID | Test | Result | Used to calibrate |
|---|---|---|---|
| `1793402046` | `eht_mld_ptk_rekey` | PASS | PTK rekey: `WPA: Key negotiation completed` while already associated (the first one, just before `CTRL-EVENT-CONNECTED`, is the initial handshake) |
| `1793402120` | `eht_mld_gtk_rekey` | PASS | GTK rekey: `MLO RSN: Group rekeying completed` (twice, as the test expects) |

Both: 2026-10-30, Intel Mac + Docker Desktop, the `wifi7-env` image built from
`docker/Dockerfile` on `main` (hostap `43ee60e1`, wireless-next `21b4248b`), run through
`explorer.runner.run_test()`. Full details are in each `manifest.json`.

In both runs, hostap's traffic test reached AP links 0 and 1 after the last rekey; at
the pinned hostap commit, `test_eht_mld_gtk_rekey` does check traffic after each group
rekey.

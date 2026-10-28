# Simulation environment (Docker + UML)

Builds hostap and a UML kernel with mac80211_hwsim at the commits pinned in
[`baseline/README.md`](../baseline/README.md), then runs hostap's hwsim tests in a
fresh UML guest per run.

```bash
docker build --progress=plain -t wifi7-env docker/
docker/run-test.sh eht_mld_sae_two_links
```

`run-test.sh` exits 0 only if every requested test passed. Logs (per-test logs,
`results.db`, pcapng captures, UML console) are copied to `runs/hwsim-logs/<timestamp>/`.

## Status (issue #4)

| Platform | Build | `eht_mld_sae_two_links` |
|---|---|---|
| Intel Mac, macOS 15.8, Docker Desktop 27.4 (6 CPUs, ~5 GB) | ✅ ~44 min first time (kernel compile ~33 min) | ✅ 4/4 consecutive passes, ~40 s per run |
| Windows + WSL2 | not tried yet | – |

## Windows (WSL2)

Do everything **inside WSL Ubuntu**, not PowerShell or Git Bash.

1. Complete the dev setup from issue #3: WSL2 + Ubuntu, Docker Desktop with
   *Settings → Resources → WSL Integration* enabled for **Ubuntu**.
2. Clone the repo in your Linux home folder (`~/`), **not** under `/mnt/c/...`:
   builds are much slower across that boundary.
3. Check Docker works from Ubuntu: `docker run --rm hello-world`.
4. Build and test with the same two commands as above.

Notes:
- With the WSL2 backend, CPU and memory limits come from `C:\Users\<you>\.wslconfig`,
  not Docker Desktop's settings. The defaults are usually enough; if the build runs out
  of memory, set e.g. `[wsl2]` / `memory=6GB` / `processors=6`, then run `wsl --shutdown`.
- Expect a 45–60 min first build and ~1.4 GB of disk for the image.
- Record your result in the status table: Windows version, pass/fail, and any errors.

## Required `docker run` settings (and why)

All three are built into `run-test.sh`. Found on Intel Mac + Docker Desktop, 2026-10-27/28.

1. **Exec-enabled tmpfs for UML's memory:** `--tmpfs /umltmp:rw,exec,size=1g -e TMPDIR=/umltmp`.
   Docker mounts `/dev/shm` noexec, and UML refuses to start
   (`/dev/shm must be not mounted noexec`). `--shm-size` alone doesn't help;
   `--privileged` is not needed.
2. **Pin to one CPU:** `--cpuset-cpus=0`. Docker Desktop's VM uses the `tsc` clock across
   6 vCPUs, and the per-CPU clocks can disagree. Without pinning, hostap's default
   `time-travel=inf-cpu` hung (UML at ~90% CPU, no progress) and plain `time-travel`
   panicked with `time-travel: time goes backwards`.
3. **Keep logs inside the container, copy them out afterwards.** Writing the logs folder
   to a host bind mount made the runner hang right after `TEST-STOP`, when it writes
   the result to `results.db` (SQLite over Docker Desktop file sharing).

Running without time-travel at all (real time) is not an option on this Mac: boot took
~4 min and the SAE connection timed out.

## Next steps

- Try the same image and script on **Windows + WSL2** to finish #4.
- Turn the build + test into a one-command rebuild script (#6).

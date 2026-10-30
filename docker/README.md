# Simulation environment (Docker + UML)

Builds hostap and a UML kernel with mac80211_hwsim at the commits pinned in
[`baseline/README.md`](../baseline/README.md), then runs hostap's hwsim tests in a
fresh UML guest per run.

**One command** (build + smoke test, from anywhere in the repo):

```bash
scripts/build-env.sh            # reuses Docker's cache
scripts/build-env.sh --fresh    # rebuilds every step from scratch
```

It checks that Docker is running on x86-64 with enough memory, builds the image, runs
`eht_mld_sae_two_links` and prints the image ID, pinned commits and the test result.
Exits 0 only if the smoke test passed.

Or step by step:

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
| Windows 11 Home 10.0.26200, WSL 3.0.3 + Ubuntu 22.04, Docker Desktop 4.51.0 (12 CPUs, ~3.5 GB for WSL) | ✅ ~10 min first time | ✅ 1/1 pass, 22 s per run (2026-10-28) |

## Windows (WSL2)

Do everything **inside WSL Ubuntu**, not PowerShell or Git Bash. (Windows PowerShell 5.1
also strips embedded double quotes from commands passed through `wsl -- bash -lc '…'`.)

1. Complete the dev setup from issue #3: WSL2 + Ubuntu, Docker Desktop with
   *Settings → Resources → WSL Integration* enabled for **Ubuntu**.
2. Clone the repo in your Linux home folder (`~/`), **not** under `/mnt/c/...`:
   builds are much slower across that boundary.
3. Check Docker works from Ubuntu: `docker run --rm hello-world`.
4. Build and test with `scripts/build-env.sh` (or the two commands above).

Notes:
- With the WSL2 backend, CPU and memory limits come from `C:\Users\<you>\.wslconfig`,
  not Docker Desktop's settings. The defaults are usually enough; if the build runs out
  of memory, set e.g. `[wsl2]` / `memory=6GB` / `processors=6`, then run `wsl --shutdown`.
  On a laptop with little RAM (7 GB here), don't give WSL most of it: the build left
  Windows with ~0.3 GB free, Ubuntu stopped responding and Docker's WSL integration
  crashed. Adding swap (e.g. `swap=8GB`) is safer than raising `memory`.
- If `docker` in Ubuntu says it can't connect to the daemon after such a hiccup, turn
  Ubuntu off and on again under *Settings → Resources → WSL Integration*.
- Don't run `wsl --shutdown` while Docker Desktop is starting: it got stuck waiting on its
  VM ("still waiting for init control API") until it was fully quit and restarted.
- Expect a 10–60 min first build depending on CPU count, and ~1.4 GB of disk for the image.
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

- ~~Try the same image and script on **Windows + WSL2** to finish #4.~~ Done 2026-10-28
  (see the status table).
- ~~Turn the build + test into a one-command rebuild script.~~ Added `scripts/build-env.sh`
  (2026-10-29); passes on Intel Mac with the cache. Still needs a teammate on Windows to
  run `scripts/build-env.sh --fresh` from a clean clone.

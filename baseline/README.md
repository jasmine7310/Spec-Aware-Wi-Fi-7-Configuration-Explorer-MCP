# Baseline environment

Record of the exact environment used for every experiment. Anyone rebuilding the
project (teammates or graders) should get the same versions listed here.

## Pinned versions

| Component | Repository | Commit | Commit date |
|---|---|---|---|
| hostap (hostapd, wpa_supplicant, `tests/hwsim`) | `git://w1.fi/hostap.git` | [`43ee60e13c257d33d25bfb6892b9ee38fb6e88a4`](https://w1.fi/cgit/hostap/commit/?id=43ee60e13c257d33d25bfb6892b9ee38fb6e88a4) | 2026-09-29 |
| Linux kernel (wireless-next, built as UML with mac80211_hwsim) | `https://git.kernel.org/pub/scm/linux/kernel/git/wireless/wireless-next.git` | [`21b4248bfa0f410fa22202fc2c82f4808d672cda`](https://git.kernel.org/pub/scm/linux/kernel/git/wireless/wireless-next.git/commit/?id=21b4248bfa0f410fa22202fc2c82f4808d672cda) | 2026-09-28 |
| Docker base image | Docker Hub | `ubuntu:24.04`; the baseline image's layers were built from `sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c` (2026-10-27) | – |

The `ubuntu:24.04` tag moves: on 2026-10-29 it resolved to
`sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852`, though the
rebuild reused every cached layer. A clean build on another machine may get a newer base,
so the Dockerfile should pin `ubuntu:24.04@sha256:…` (to do with the rebuild script).

**Why these versions:** they are the reference feasibility pair named in the CS 211
Project F spec, which reports them as a working combination for Wi-Fi 7 MLO tests.
Both commits were confirmed to exist upstream on 2026-10-27.

## Platform plan

- Experiments run in **Docker + UML (User-Mode Linux)** with **mac80211_hwsim**, using
  hostap's own `tests/hwsim` test suite.
- **Windows:** WSL2 Ubuntu + Docker Desktop (WSL2 backend), repo cloned inside Ubuntu.
- **Intel Mac:** Docker Desktop. Apple Silicon Macs can't run UML natively.
- **Fallback** if UML in Docker isn't working by day 3: run UML directly in WSL2 without
  Docker, or use one shared x86-64 Linux machine.

## Build steps

See [`docker/README.md`](../docker/README.md) for the full instructions, platform notes
and the `docker run` settings UML needs. In short:

```bash
docker build --progress=plain -t wifi7-env docker/
LOG_DIR=runs/baseline docker/run-test.sh eht_mld_sae_two_links
```

A one-command rebuild script is still to come (rebuild script issue).

## Baseline runs

Three independent runs of hostap's `eht_mld_sae_two_links` (two-link SAE MLO
association), each in a fresh container and UML guest, on 2026-10-29.

| Run ID | Result | Started (UTC) | Wall time | Evidence |
|---|---|---|---|---|
| [`1793298094`](../runs/baseline/1793298094/) | PASS | 2026-10-29 18:21:34 | 25 s | `manifest.json`, `results.db`, `eht_mld_sae_two_links.log`, `console`, capture `.hwsim0.pcapng` 32,144 bytes (decrypted `.hwsim0.dec.pcapng` 58,624) |
| [`1793298125`](../runs/baseline/1793298125/) | PASS | 2026-10-29 18:22:04 | 19 s | same files; capture 32,144 bytes (decrypted 58,624) |
| [`1793298146`](../runs/baseline/1793298146/) | PASS | 2026-10-29 18:22:26 | 18 s | same files; capture 32,916 bytes (decrypted 59,952) |

The PASS in each `manifest.json` matches the result hostap's own runner wrote to that
run's `results.db`.

**Environment for all three:** Intel Mac, macOS 15.8.1; Docker Desktop 27.4.0
(LinuxKit 6.10.14, 6 CPUs, ~5 GB); image `wifi7-env`
`sha256:1970c8cf6af5…` built from this repo's `docker/Dockerfile`; hostap `43ee60e1`;
wireless-next `21b4248b`. Full details are in each run's `manifest.json`.

**Notes:**
- The test duration recorded by hostap (~0.19 s) is guest time under UML's
  `time-travel=inf-cpu` mode, not wall-clock time.
- The manifests show `repo_docker_dir_modified: true` because the run script's manifest
  step was added in the same change that recorded these runs; the image itself was built
  from the Dockerfile as committed on `main`.
- The same test also passed on Windows 11 + WSL2 (see `docker/README.md`), but those were
  trial runs and are not part of this baseline.

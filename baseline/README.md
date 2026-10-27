# Baseline environment

Record of the exact environment used for every experiment. Anyone rebuilding the
project (teammates or graders) should get the same versions listed here.

## Pinned versions

| Component | Repository | Commit | Commit date |
|---|---|---|---|
| hostap (hostapd, wpa_supplicant, `tests/hwsim`) | `git://w1.fi/hostap.git` | [`43ee60e13c257d33d25bfb6892b9ee38fb6e88a4`](https://w1.fi/cgit/hostap/commit/?id=43ee60e13c257d33d25bfb6892b9ee38fb6e88a4) | 2026-09-29 |
| Linux kernel (wireless-next, built as UML with mac80211_hwsim) | `https://git.kernel.org/pub/scm/linux/kernel/git/wireless/wireless-next.git` | [`21b4248bfa0f410fa22202fc2c82f4808d672cda`](https://git.kernel.org/pub/scm/linux/kernel/git/wireless/wireless-next.git/commit/?id=21b4248bfa0f410fa22202fc2c82f4808d672cda) | 2026-09-28 |
| Docker base image | Docker Hub | `ubuntu:24.04` (pin by digest once #4 works) | – |

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

_To be filled in by #4 (build the environment) and #6 (rebuild script)._

## Baseline runs

_To be filled in by #7: run IDs, logs, pcaps and version manifests for three clean
two-link MLO association runs._

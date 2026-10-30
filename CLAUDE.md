# CS 211 Project F: Spec-Aware Wi-Fi 7 Configuration Explorer (MCP)

**Read [`docs/plan.md`](docs/plan.md) first.** It has what we're building (P0–P4 stages),
the decisions made so far, current status and the spec's ground rules.

## Sources of truth

- **Project spec:** the CS 211 Fall 2026 Project F roadmap on Notion:
  https://app.notion.com/p/CS-211-Fall-2026-Project-F-Roadmap-Spec-Aware-Wi-Fi-7-Configuration-Explorer-MCP-40003bb3e77681a0a338c5208f14bf51
  If you can't open it, ask the user to paste the relevant section. Don't guess requirements.
- **Pinned versions:** [`baseline/README.md`](baseline/README.md).
- **Task details:** the GitHub issue the user is working on.

## hostap source

Code that touches hostap (settings, actions, test names, helper functions) must match
the **pinned commit**, not memory of upstream hostap. Read the real source before writing
against it. If there is no local copy yet, clone it next to this repo:

```bash
git clone https://w1.fi/hostap.git ../hostap
git -C ../hostap checkout 43ee60e13c257d33d25bfb6892b9ee38fb6e88a4
```

The tests live in `../hostap/tests/hwsim/` (`test_eht.py`, `hostapd.py`,
`wpasupplicant.py`, `hwsim_utils.py`).

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup
.venv/bin/pytest                                             # unit tests
scripts/build-env.sh                                         # build simulation image + smoke test
docker build --progress=plain -t wifi7-env docker/           # simulation image only (slow first time)
docker/run-test.sh eht_mld_sae_two_links                     # one hwsim test in a fresh UML guest
```

The project needs Python 3.11+. On Ubuntu 22.04 `python3` is 3.10, so create the venv
with `python3.11` instead (`sudo apt install python3.11 python3.11-venv`).

On Windows, run everything inside WSL Ubuntu. See `docker/README.md` for the simulation
environment, the `docker run` settings it needs and Windows troubleshooting. If you drive
WSL from Windows PowerShell 5.1, put the commands in a script and run
`wsl -d Ubuntu -- bash <script>`: PowerShell strips embedded double quotes from inline
`wsl -- bash -lc '…'` commands.

## Rules for agents

- Never invent results, run IDs, hostap options, rule citations or spec section numbers.
  If something is unverified, say so.
- Spec-rule research needs the user to check the source; draft, don't declare.
- P0 models are strict (`strict=True`, `extra="forbid"`); cross-field Wi-Fi rules belong in P1.
- Don't commit trial runs from `runs/` as baseline evidence.

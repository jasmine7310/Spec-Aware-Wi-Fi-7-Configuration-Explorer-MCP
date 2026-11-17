# Experiment runs

Real runs kept because they answer a question about the spec or the implementation, as
labeled experiments. They are **not** P2 evidence: this folder isn't in
`explorer.support.EVIDENCE_DIRS`, so no support check or experiment-cache rebuild reads
it. `spec_coverage.csv` may cite them as run evidence. Single runs, not reproducibility
trials.

| Run ID | Question | Candidate | P3 | Today's P1 |
|---|---|---|---|---|
| `1794875139` | Do per-link AKM lists give different RSNXEs? ("Check whether per-link AKM lists give different RSNXEs", #95) | F02 with link 0 `[SAE-EXT-KEY, OWE]`, link 1 `[OWE]`, client `OWE` | `ACCEPTED` | **SPEC_RULE_VIOLATION** (`SEC.MLD_SAME_RSNXE`): a labeled negative experiment |

## `1794875139`: per-link RSNXEs (#95)

Run 2026-11-17 00:25 UTC (the evening of 2026-11-16 in US time) by Michelle with Claude,
through `explorer.adapter.run_candidate()`, on an Intel Mac (macOS 15.8.1, Docker Desktop
27.4.0), the `wifi7-env` image built from `docker/Dockerfile` at repo commit `149f78e`
(harness matches the repo: `repo_docker_dir_modified: false`), hostap `43ee60e1`,
wireless-next `21b4248b`.

It ran before `SEC.MLD_SAME_RSNXE` existed, so its manifest records
`PASSES_MODELED_RULES` (P2 `UNRESOLVED`) and `negative_experiment: false`. The rule it
led to now rejects the candidate; the run stays as the labeled negative experiment behind
that rule and never counts as a legal run.

**Behavior record:** associated, valid / active links `0x3`, traffic on AP links 0 and 1,
`key_mgmt` OWE, CCMP / CCMP / BIP, PMF 2, BIGTK set. hostapd accepts the configuration
and the client associates normally.

**What the capture shows** (`explorer_candidate.hwsim0.pcapng`, read with the image's
`tshark` 4.2.2):

| | Link 0, channel 1, BSSID `02:00:00:ea:20:21` (`SAE-EXT-KEY OWE`) | Link 1, channel 6, BSSID `02:00:00:56:da:c8` (`OWE`) |
|---|---|---|
| Beacons | RSNXE (element 244) `0x20`: the SAE hash-to-element bit | no RSNXE |
| Probe Response (frame 4) | RSNXE `0x20` | – |
| Association Response (frame 17) | RSNXE `0x20` | its per-STA profile in the Multi-Link element carries a Non-Inheritance element listing element 244, i.e. link 1 has no RSNXE |

So the AP MLD advertises an RSNXE on one link and none on the other. 802.11be-2024
§12.6.2 (PDF p. 411, shall) requires the same RSNE, and RSNXE if included, on every link
apart from the RSNE's AKM list and MFPR. Read strictly (Michelle, 2026-11-16), this
breaks it. hostapd sets each link's bit from that link's own AKMs
(`src/ap/wpa_auth_ie.c:549-557`) and writes no RSNXE when no bit is set (`:601-611`).

To read it again:

```bash
docker run --rm -v "$PWD/runs/experiments/1794875139":/cap:ro --entrypoint tshark wifi7-env \
  -r /cap/explorer_candidate.hwsim0.pcapng -Y "wlan.tag.number == 244" \
  -T fields -e frame.number -e wlan.fc.type_subtype -e wlan.sa -e wlan.rsnx
```

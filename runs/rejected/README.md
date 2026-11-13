# Rejected runs

Committed runs of candidates that passed the modeled rules when they ran but that the
pinned implementation refused (P3 `REJECTED`): hostapd or wpa_supplicant didn't carry out a setup
step or action. They're kept as recorded evidence of that refusal, never as smoke values
or as one side of a behavior contrast. `explorer.support` doesn't read this folder yet; a
recorded refusal like these is what a future `UNSUPPORTED_IMPLEMENTATION` answer would
have to cite.

| Run ID | Candidate | Why it was rejected |
|---|---|---|
| `1794384673` | F02 (SAE-EXT-KEY on both links, client beacon protection on) with `ap_sae_pwe=1` (`scripts/smoke_dimensions.py`, `sae_pwe_h2e`; issue #61) | The client never associates. With `sae_pwe=1` and only SAE AKMs, hostapd advertises the SAE H2E-only selector (`src/ap/ieee802_11.c:166-170`), and wpa_supplicant skips that BSS when the client's own `sae_pwe` is unset, even with SAE-EXT-KEY (`wpa_supplicant/events.c:1250-1259`). The client's `sae_pwe` wasn't modeled then. Since issue #88 it is, and P1 rejects this candidate (`SEC.SAE_H2E_ONLY_NEEDS_STA_H2E`): the run is the refusal that rule predicts, and the same AP setting runs with the client's `sae_pwe` set (`runs/smoke/1794548583`). Windows 11 + WSL2, 2026-11-11 |

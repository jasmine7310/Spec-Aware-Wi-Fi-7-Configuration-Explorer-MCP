#!/usr/bin/env bash
# Build the simulation environment and prove it works, in one command.
#
#   scripts/build-env.sh            # build (reusing Docker's cache) + smoke test
#   scripts/build-env.sh --fresh    # rebuild every step from scratch, ignoring the cache
#
# Run from anywhere inside the repo. On Windows, run it inside WSL Ubuntu.
# The first build takes ~10 min (Windows/WSL2) to ~45 min (Intel Mac).
set -euo pipefail

IMAGE="${IMAGE:-wifi7-env}"
SMOKE_TEST="${SMOKE_TEST:-eht_mld_sae_two_links}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

build_args=()
case "${1:-}" in
    "") ;;
    --fresh) build_args+=(--no-cache --pull) ;;
    *) echo "usage: $0 [--fresh]" >&2; exit 2 ;;
esac

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- Checks -----------------------------------------------------------------
command -v docker >/dev/null || fail "docker not found. Install Docker Desktop (see issue: Dev setup guide)."
docker info >/dev/null 2>&1 || fail "Docker isn't running. Start Docker Desktop and try again."

arch=$(docker info -f '{{.Architecture}}')
case "$arch" in
    x86_64|amd64) ;;
    *) fail "Docker runs on $arch; UML needs x86-64 (Apple Silicon Macs can't run it natively)." ;;
esac

mem=$(docker info -f '{{.MemTotal}}')
if [ "$mem" -lt 3000000000 ]; then
    echo "WARNING: Docker has $((mem / 1000000)) MB of memory; the kernel build may run out (3 GB+ recommended)." >&2
fi

# --- Build ------------------------------------------------------------------
echo "==> Building $IMAGE (${build_args[*]:-using cache})"
start=$(date +%s)
docker build --progress=plain ${build_args[@]+"${build_args[@]}"} -t "$IMAGE" "$REPO_ROOT/docker"
build_seconds=$(( $(date +%s) - start ))

# --- Smoke test -------------------------------------------------------------
echo "==> Smoke test: $SMOKE_TEST"
if IMAGE="$IMAGE" "$REPO_ROOT/docker/run-test.sh" "$SMOKE_TEST"; then
    result=PASS
else
    result=FAIL
fi

# --- Summary ----------------------------------------------------------------
labels=$(docker image inspect -f '{{index .Config.Labels "hostap.commit"}} {{index .Config.Labels "kernel.commit"}}' "$IMAGE")
echo
echo "==> Summary"
echo "  image:        $IMAGE $(docker image inspect -f '{{.Id}}' "$IMAGE")"
echo "  hostap:       ${labels%% *}"
echo "  kernel:       ${labels##* }"
echo "  build time:   ${build_seconds}s"
echo "  smoke test:   $SMOKE_TEST $result"

[ "$result" = PASS ]

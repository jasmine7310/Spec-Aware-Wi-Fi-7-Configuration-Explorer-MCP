#!/usr/bin/env bash
# Run one or more hostap hwsim tests in a fresh UML guest inside the container.
#
#   docker/run-test.sh eht_mld_sae_two_links
#
# Logs are copied to $LOG_DIR (default: runs/hwsim-logs/ in the repo), one
# timestamped folder per run. Exits nonzero if any test did not pass.
set -euo pipefail

IMAGE="${IMAGE:-wifi7-env}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$REPO_ROOT/runs/hwsim-logs}"
GUEST_LOGS=/tmp/hwsim-test-logs

if [ "$#" -eq 0 ]; then
    echo "usage: $0 <hwsim test name> [more test names...]" >&2
    exit 2
fi

mkdir -p "$LOG_DIR"

# UML keeps its guest RAM in a temp file it must be able to execute from. Docker
# mounts /dev/shm noexec, so give UML its own exec-enabled tmpfs (larger than
# MEMORY in vm-config) and point TMPDIR at it.
#
# Pin to one CPU: in Docker Desktop's VM the per-CPU clocks can disagree, and
# UML's time-travel mode hangs or panics ("time goes backwards") when it
# migrates between CPUs.
#
# Logs stay inside the container during the run and are copied out afterwards:
# the tests' SQLite results database hangs when written to a host bind mount.
container=$(docker create \
    --cpuset-cpus=0 \
    --tmpfs /umltmp:rw,exec,size=1g \
    -e TMPDIR=/umltmp \
    -e HWSIM_TEST_LOG_DIR="$GUEST_LOGS" \
    "$IMAGE" "$@")
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT

# The UML console uses CRLF line endings; strip the CRs so the checks below match.
output=$(docker start -a "$container" 2>&1 | tr -d '\r' | tee /dev/stderr)

run_id=$(printf '%s\n' "$output" | sed -n "s|^Logfiles are at $GUEST_LOGS/\([^ ]*\) .*|\1|p")
if [ -n "$run_id" ]; then
    docker cp "$container:$GUEST_LOGS/$run_id" "$LOG_DIR/$run_id" >/dev/null
    echo "Logs copied to $LOG_DIR/$run_id"
fi

printf '%s\n' "$output" | grep -q '^ALL-PASSED$'

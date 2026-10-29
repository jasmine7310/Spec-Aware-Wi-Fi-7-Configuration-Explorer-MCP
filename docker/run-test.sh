#!/usr/bin/env bash
# Run one or more hostap hwsim tests in a fresh UML guest inside the container.
#
#   docker/run-test.sh eht_mld_sae_two_links
#   LOG_DIR=runs/baseline docker/run-test.sh eht_mld_sae_two_links   # official run
#
# Logs are copied to $LOG_DIR (default: runs/hwsim-logs/ in the repo, which is
# git-ignored for trial runs), one timestamped folder per run, together with a
# manifest.json recording results, versions and environment. Exits nonzero if
# any test did not pass.
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

started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
start_s=$(date +%s)
# The UML console uses CRLF line endings; strip the CRs so the checks below match.
output=$(docker start -a "$container" 2>&1 | tr -d '\r' | tee /dev/stderr)
finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
wall_seconds=$(( $(date +%s) - start_s ))

if printf '%s\n' "$output" | grep -q '^ALL-PASSED$'; then
    overall=PASS
else
    overall=FAIL
fi

run_id=$(printf '%s\n' "$output" | sed -n "s|^Logfiles are at $GUEST_LOGS/\([^ ]*\) .*|\1|p")
if [ -n "$run_id" ]; then
    run_dir="$LOG_DIR/$run_id"
    docker cp "$container:$GUEST_LOGS/$run_id" "$run_dir" >/dev/null

    if [ "$(uname -s)" = Darwin ]; then
        host_os="macOS $(sw_vers -productVersion)"
    else
        host_os="$(. /etc/os-release && echo "$PRETTY_NAME")"
        grep -qi microsoft /proc/version 2>/dev/null && host_os="$host_os (WSL2)"
    fi

    RUN_ID="$run_id" RUN_DIR="$run_dir" OVERALL="$overall" TESTS="$*" OUTPUT="$output" \
    STARTED_AT="$started_at" FINISHED_AT="$finished_at" WALL_SECONDS="$wall_seconds" \
    HOST_OS="$host_os" HOST_KERNEL="$(uname -srm)" \
    IMAGE_NAME="$IMAGE" \
    IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$IMAGE")" \
    IMAGE_LABELS="$(docker image inspect -f '{{json .Config.Labels}}' "$IMAGE")" \
    DOCKER_INFO="$(docker info -f '{{json .}}')" \
    REPO_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)" \
    REPO_DIRTY="$(git -C "$REPO_ROOT" status --porcelain -- docker 2>/dev/null | grep -q . && echo true || echo false)" \
    python3 - <<'PY'
import json, os, re, pathlib

env = os.environ
labels = json.loads(env["IMAGE_LABELS"] or "{}")
info = json.loads(env["DOCKER_INFO"])
results = [
    {"test": m.group(2), "result": m.group(1), "duration_s": float(m.group(3))}
    for m in re.finditer(r"^(PASS|FAIL|SKIP) (\S+) ([0-9.]+) ", env["OUTPUT"], re.M)
]
run_dir = pathlib.Path(env["RUN_DIR"])
manifest = {
    "run_id": env["RUN_ID"],
    "tests_requested": env["TESTS"].split(),
    "overall": env["OVERALL"],
    "results": results,
    "started_at": env["STARTED_AT"],
    "finished_at": env["FINISHED_AT"],
    "wall_seconds": int(env["WALL_SECONDS"]),
    "versions": {
        "hostap_commit": labels.get("hostap.commit"),
        "kernel_commit": labels.get("kernel.commit"),
        "image": env["IMAGE_NAME"],
        "image_id": env["IMAGE_ID"],
        "repo_commit": env["REPO_COMMIT"],
        "repo_docker_dir_modified": env["REPO_DIRTY"] == "true",
    },
    "environment": {
        "host_os": env["HOST_OS"],
        "host_kernel": env["HOST_KERNEL"],
        "docker_server_version": info.get("ServerVersion"),
        "docker_vm_os": info.get("OperatingSystem"),
        "docker_vm_kernel": info.get("KernelVersion"),
        "docker_vm_cpus": info.get("NCPU"),
        "docker_vm_memory_bytes": info.get("MemTotal"),
    },
    "docker_run_settings": [
        "--cpuset-cpus=0",
        "--tmpfs /umltmp:rw,exec,size=1g",
        "-e TMPDIR=/umltmp",
        "-e HWSIM_TEST_LOG_DIR=/tmp/hwsim-test-logs",
    ],
    "packet_captures": [
        {"file": p.name, "bytes": p.stat().st_size}
        for p in sorted(run_dir.glob("*.pcapng"))
    ],
}
(run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY
    echo "Logs and manifest.json copied to $run_dir"
fi

[ "$overall" = PASS ]

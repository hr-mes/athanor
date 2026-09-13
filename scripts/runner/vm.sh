#!/usr/bin/env bash
# One job of the self-hosted runner (scripts/runner/README.md). Asks GitHub for a
# just-in-time runner configuration, boots the base image with snapshot=on (no write
# reaches it) and a scratch disk recreated empty, passes the configuration to the guest
# as a systemd credential through fw_cfg, and waits for the guest to power off after its
# job; athanor-runner.service then starts the next one. Runs as the dynamic user of the
# service: STATE_DIRECTORY holds golden.qcow2 and the disks, the GitHub token is the
# service credential github-token and never appears on a command line.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
source "$HERE/runner.env"
die() { echo "error: $*" >&2; exit 1; }

STATE=${STATE_DIRECTORY:?run by athanor-runner.service}
RUNTIME=${RUNTIME_DIRECTORY:?run by athanor-runner.service}
LOGS=${LOGS_DIRECTORY:?run by athanor-runner.service}
TOKEN=${CREDENTIALS_DIRECTORY:?run by athanor-runner.service}/github-token
[[ -f $STATE/golden.qcow2 ]] || die "$STATE/golden.qcow2 missing: run build-image.sh and install.sh"
umask 077

github() { # github METHOD PATH [JSON]: the response body goes to $RUNTIME/response, the HTTP status to stdout
  curl -sS -o "$RUNTIME/response" -w '%{http_code}' -X "$1" -H @- \
    -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' \
    ${3:+--data "$3"} "https://api.github.com/$2" <<< "Authorization: Bearer $(< "$TOKEN")"
}

name=athanor-vm-$(date -u +%Y%m%d%H%M%S)
body=$(jq -cn --arg name "$name" --arg labels "$RUNNER_LABELS" \
  '{name: $name, runner_group_id: 1, labels: ($labels | split(",")), work_folder: "/var/lib/runner/work"}')
status=$(github POST "repos/$REPOSITORY/actions/runners/generate-jitconfig" "$body")
[[ $status == 201 ]] || die "generate-jitconfig: HTTP $status: $(< "$RUNTIME/response")"
id=$(jq -r .runner.id "$RUNTIME/response")
jq -r .encoded_jit_config "$RUNTIME/response" > "$RUNTIME/jitconfig"
rm "$RUNTIME/response"

cleanup() {
  rm -f "$RUNTIME/jitconfig"
  # A just-in-time runner deregisters after its job; one whose guest stopped before
  # taking a job stays registered and is removed here.
  local status
  status=$(github GET "repos/$REPOSITORY/actions/runners/$id")
  case $status in
    200) status=$(github DELETE "repos/$REPOSITORY/actions/runners/$id")
         [[ $status == 204 ]] || echo "warning: runner $name ($id) not removed: HTTP $status" >&2 ;;
    404) ;;
    *) echo "warning: runner $name ($id) not checked: HTTP $status" >&2 ;;
  esac
  rm -f "$RUNTIME/response"
}
trap cleanup EXIT
trap 'exit 143' TERM

[[ -f $STATE/cache.raw ]] || truncate -s "$CACHE_DISK_SIZE" "$STATE/cache.raw"
rm -f "$STATE/scratch.raw"
truncate -s "$SCRATCH_DISK_SIZE" "$STATE/scratch.raw"

echo "runner $name ($id): booting, serial console in $LOGS/console.log"
qemu-system-x86_64 \
  -machine q35,accel=kvm -cpu host -smp "$VM_CPUS" -m "$VM_MEMORY" \
  -nodefaults -display none -no-reboot -serial "file:$LOGS/console.log" \
  -device virtio-rng-pci \
  -drive "if=none,id=system,format=qcow2,snapshot=on,file=$STATE/golden.qcow2" \
  -device virtio-blk-pci,drive=system,bootindex=0 \
  -drive "if=none,id=cache,format=raw,discard=unmap,file=$STATE/cache.raw" \
  -device virtio-blk-pci,drive=cache,serial=runner-cache \
  -drive "if=none,id=scratch,format=raw,discard=unmap,file=$STATE/scratch.raw" \
  -device virtio-blk-pci,drive=scratch,serial=runner-scratch \
  -netdev passt,id=net0 -device virtio-net-pci,netdev=net0 \
  -fw_cfg "name=opt/io.systemd.credentials/jitconfig,file=$RUNTIME/jitconfig"
echo "runner $name ($id): guest powered off"

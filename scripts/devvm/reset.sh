#!/usr/bin/env bash
# reset.sh: discards everything done in the VM since create.sh by recreating dev.qcow2,
# and its UEFI variables, empty on top of base.qcow2.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
source "$HERE/devvm.env"

need_qemu_img
[[ -f $STATE/base.qcow2 ]] || die "$STATE/base.qcow2 missing: run create.sh"
! systemctl --user -q is-active "$UNIT" || die "the VM is running: stop it first (ssh.sh sudo poweroff)"
qemu-img create -q -f qcow2 -F qcow2 -b "$STATE/base.qcow2" "$STATE/dev.qcow2"
install -m 0644 "$STATE/base-vars.fd" "$STATE/dev-vars.fd"
# The guest's SSH host keys are generated on its first boot, which happens in the overlay.
rm -f "$STATE/known_hosts"
echo "reset: $STATE/dev.qcow2"

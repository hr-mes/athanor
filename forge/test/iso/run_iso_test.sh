#!/usr/bin/env bash
# run_iso_test.sh ISO OUTPUT_DIR: installs the published Athanor ISO in a VM without a
# person at the keyboard, restarts into what was installed, and reports whether the
# greeter came up.
#
# The ISO is used exactly as published. The shipped installer is attended by design, so
# it stops and asks; the answers a person would give are supplied instead on a second
# disk carrying forge/test/iso/collaudo.ks, selected with inst.ks= on the kernel command
# line. Nothing inside the ISO is rewritten, which is the point: the artifact under test
# is the artifact that ships.
#
# Two phases in one QEMU life. The installer writes the disk and restarts; the firmware
# then finds the installed system because the ISO ejects itself and the disk is first in
# the boot order. Both phases talk on the same serial console, and the markers this
# script waits for are written by the kickstarts: "Install finished" by the builder's own
# and "Athanor kickstart finished" by ours.
#
# Everything the run learns goes to OUTPUT_DIR: the console log, the screenshots, and
# greeter.txt with the verdict. The screenshots are there to be looked at by a person,
# not only asserted on.
set -euo pipefail

[[ $# -eq 2 ]] || { echo "usage: run_iso_test.sh ISO OUTPUT_DIR" >&2; exit 2; }
iso=$1 output=$2
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

[[ -f $iso ]] || { echo "ISO not found: $iso" >&2; exit 2; }
[[ -f "${here}/collaudo.ks" ]] || { echo "collaudo.ks missing next to this script" >&2; exit 2; }

# Space for the installed system plus room for btrfs to breathe. The image is ~6 GiB.
DISK_GIB=${DISK_GIB:-30}
# Wall clock for the whole run. With KVM the install is minutes; without it, hours.
TIMEOUT=${TIMEOUT:-5400}
# How long to keep watching after the installed system starts, before giving up on the
# greeter. Long enough for a first boot that has to relabel and start every service.
GREETER_WAIT=${GREETER_WAIT:-900}

mkdir -p "$output"
disk="${output}/disk.raw"
ksimg="${output}/kickstart.img"
vars="${output}/OVMF_VARS.fd"

# UEFI, because that is how the ISO is meant to be booted. Distributions disagree on both
# the directory and the file name: Debian and Ubuntu ship OVMF_CODE_4M.fd under
# /usr/share/OVMF, Fedora ships OVMF_CODE.fd under /usr/share/edk2/ovmf. Both spellings
# are tried rather than one being assumed, and the 4M pair is preferred because it is what
# a current Ubuntu runner actually has. The plain names come second so a Fedora host, or
# an older Ubuntu, still works.
ovmf_code=''
ovmf_vars=''
for dir in /usr/share/OVMF /usr/share/edk2/ovmf /usr/share/ovmf; do
    for suffix in _4M ''; do
        candidate_code="${dir}/OVMF_CODE${suffix}.fd"
        candidate_vars="${dir}/OVMF_VARS${suffix}.fd"
        if [[ -f $candidate_code && -f $candidate_vars ]]; then
            ovmf_code=$candidate_code
            ovmf_vars=$candidate_vars
            break 2
        fi
    done
done
[[ -n $ovmf_code ]] || {
    echo "OVMF firmware not found; looked for OVMF_CODE[_4M].fd in:" >&2
    echo "  /usr/share/OVMF /usr/share/edk2/ovmf /usr/share/ovmf" >&2
    exit 2
}
echo "=== firmware: ${ovmf_code}"
# The firmware writes to its variable store, so it cannot be the read-only system copy.
cp "$ovmf_vars" "$vars"

qemu-img create -f raw "$disk" "${DISK_GIB}G" > /dev/null

# The kickstart travels on its own small filesystem, found by label. A label rather than a
# device name because the installer sees the disks in whatever order the firmware hands
# them over, and a name that depends on that order is a test that fails for the wrong
# reason.
truncate -s 8M "$ksimg"
mkfs.ext4 -q -L ATHANORKS "$ksimg"
mkdir -p "${output}/ksmnt"
if command -v guestmount > /dev/null; then
    guestmount -a "$ksimg" -m /dev/sda --rw "${output}/ksmnt"
    cp "${here}/collaudo.ks" "${output}/ksmnt/collaudo.ks"
    guestunmount "${output}/ksmnt"
else
    # debugfs writes into an unmounted ext4 without root and without a loop device, which
    # is what a hosted runner gives us.
    debugfs -w -R "write ${here}/collaudo.ks collaudo.ks" "$ksimg" > /dev/null 2>&1
fi
rmdir "${output}/ksmnt"

accel=tcg
[[ -w /dev/kvm ]] && accel=kvm
echo "=== acceleration: ${accel}, disk ${DISK_GIB} GiB, timeout ${TIMEOUT}s"

serial="${output}/serial.sock"
monitor="${output}/monitor.sock"
rm -f "$serial" "$monitor"

# The console watcher reports the markers and tells this script when each phase is done.
python3 "${here}/console.py" "$serial" "${output}/serial.log" "${output}/phases.txt" &
console_pid=$!

# Screenshots on a timer: the installer and the greeter are graphical and say nothing on
# the serial line, so this is the only record of what they actually drew.
(
    for _ in $(seq 120); do [[ -S $monitor ]] && break; sleep 1; done
    i=0
    while [[ -S $monitor ]]; do
        sleep "${SHOT_EVERY:-120}"
        i=$((i + 1))
        printf -v name '%s/screen-%03d.ppm' "$output" "$i"
        python3 "${here}/monitor.py" "$monitor" "screendump ${name}" > /dev/null 2>&1 || break
    done
) &
shots_pid=$!

# The disk boots before the CD. On the first pass it is empty and therefore unbootable, so
# the firmware falls through to the ISO and the install happens; afterwards the disk holds
# a system and wins, which is how the machine reaches its own first boot inside the same
# QEMU life. With the CD first the guest reinstalls forever, which is what it did: the
# kickstart's `reboot --eject` does not persuade the firmware to skip a CD that is still
# attached and still first in the boot order.
set +e
timeout "$TIMEOUT" qemu-system-x86_64 \
    -machine q35 -accel "$accel" -cpu max -smp "${VCPUS:-4}" -m "${MEMORY_MIB:-6144}" \
    -drive "if=pflash,format=raw,readonly=on,file=${ovmf_code}" \
    -drive "if=pflash,format=raw,file=${vars}" \
    -device virtio-blk-pci,drive=hd,bootindex=0 \
    -drive "file=${disk},if=none,id=hd,format=raw" \
    -drive "file=${ksimg},if=virtio,format=raw" \
    -drive "file=${iso},if=none,id=cd,media=cdrom,readonly=on" \
    -device virtio-scsi-pci -device scsi-cd,drive=cd,bootindex=1 \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
    -display none -serial "unix:${serial},server,nowait" \
    -monitor "unix:${monitor},server,nowait"
qemu_status=$?
set -e

kill "$shots_pid" "$console_pid" 2> /dev/null || true
wait "$console_pid" 2> /dev/null || true

python3 "${here}/verdict.py" "$output" "$GREETER_WAIT" "$qemu_status"

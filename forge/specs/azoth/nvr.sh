#!/usr/bin/env bash
# The NVR of the Athanor kernel derived from the pins: the same one rpmbuild produces
# with `%buildid .azoth` (build.sh) and that publish uses as the tag of the OCI images.
# Usage: nvr.sh [pins.env]
set -euo pipefail
# shellcheck source=pins.env
source "${1:-$(dirname "${BASH_SOURCE[0]}")/pins.env}"
# A dotted numeric kernel version, a literal "-", and an alnum-dotted release naming a
# Fedora dist tag (fcNN) somewhere in it -- e.g. 100.fc43, 100.fc43.1, or a pre-release
# release like 0.rc4.20250226git.42.fc43. Kept metacharacter-free: FEDORA_KERNEL_NVR ends
# up unquoted in other commands (build.sh's KOJI URL and FEDORA_KEY path,
# system/kernel-artifacts.sh's attested_nvr), so a value outside this shape is rejected
# before it can inject anything there, whether it comes from pins.env or a cosign-verified
# attestation -- both go through this same check because both call this same script.
[[ $FEDORA_KERNEL_NVR =~ ^[0-9]+(\.[0-9]+)+-[0-9A-Za-z]+(\.[0-9A-Za-z]+)*\.fc[0-9]+[0-9A-Za-z.]*$ ]] \
  || { echo "nvr.sh: FEDORA_KERNEL_NVR '$FEDORA_KERNEL_NVR' does not look like one" >&2; exit 1; }
rel=${FEDORA_KERNEL_NVR#*-}
echo "${FEDORA_KERNEL_NVR%%-*}-${rel%%.*}.azoth.${rel#*.}"

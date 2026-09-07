#!/usr/bin/env bash
# sbom_rootfs.sh IMAGE SBOM.spdx.json: SPDX SBOM of a local container image, taken from
# its root filesystem. syft's image source keeps one file tree per layer and, on the
# system image (about 120 layers and 270k files), needs more memory than a hosted
# runner has; the image is mounted instead and scanned as a directory. The binary
# catalogers are left out: on an RPM system they only duplicate the RPM database.
# With rootless podman the mount only exists inside podman's user namespace, so the
# script re-executes itself under podman unshare.
set -euo pipefail
[[ $# -eq 2 ]] || { echo "usage: sbom_rootfs.sh IMAGE SBOM.spdx.json" >&2; exit 2; }
image=$1 sbom=$2
command -v syft >/dev/null || { echo "syft is not in PATH" >&2; exit 2; }
if [[ $(id -u) -ne 0 ]]; then
  exec podman unshare "$0" "$@"
fi
rootfs=$(podman image mount "$image")
trap 'podman image unmount "$image" >/dev/null' EXIT
syft scan "dir:${rootfs}" \
  --source-name "${image%:*}" --source-version "${image##*:}" \
  --select-catalogers "-binary-classifier-cataloger,-elf-binary-package-cataloger" \
  -o "spdx-json=${sbom}"

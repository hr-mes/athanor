#!/usr/bin/env bash
# build_iso.sh IMAGE OUTPUT_DIR: installer ISO of a bootc image, built with
# bootc-image-builder.
#
# Not the osbuild/bootc-image-builder-action: the builder looks for the installer
# package list as <ID>-<VERSION_ID>.yaml, where ID comes from the os-release of the
# image being installed, and its search paths are compiled in. Athanor declares
# ID=athanor, which matches none of the definitions shipped inside the builder, so ours
# has to be mounted over that directory, and the action passes no volumes of its own.
#
# The builder reads the image from the root container storage and does not pull it, so
# this script does. The build configuration has no option of its own: the builder reads
# whatever is mounted at /config.toml. Its output belongs to root, hence the --chown.
set -euo pipefail

[[ $# -eq 2 ]] || { echo "usage: build_iso.sh IMAGE OUTPUT_DIR" >&2; exit 2; }
image=$1 output=$2
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
builder=${BIB_IMAGE:-quay.io/centos-bootc/bootc-image-builder:latest}
config="${repo}/system/disk_config/iso.toml"
defs="${repo}/system/disk_config/defs"

[[ -f $config ]] || { echo "ISO configuration missing: $config" >&2; exit 2; }
[[ -d $defs ]] || { echo "distro definitions missing: $defs" >&2; exit 2; }

mkdir -p "$output"

# The builder needs the root container storage. Already root (a container): run
# directly. Otherwise sudo, which must be there.
sudo() {
  if [[ $(id -u) -eq 0 ]]; then
    "$@"
  elif command -v sudo > /dev/null; then
    command sudo "$@"
  else
    echo "build_iso.sh must run as root or with sudo available" >&2
    return 1
  fi
}

sudo podman pull "$builder"
sudo podman pull "$image"

# --rootfs: the builder formats the installed root with ext4, xfs or btrfs and knows no
# other type, so btrfs stands in for the bcachefs root the design targets.
sudo podman run --rm --privileged --security-opt label=type:unconfined_t \
  -v /var/lib/containers/storage:/var/lib/containers/storage \
  -v "${config}:/config.toml:ro" \
  -v "${defs}:/usr/share/bootc-image-builder/defs:ro" \
  -v "${output}:/output" \
  "$builder" build \
    --type anaconda-iso \
    --rootfs btrfs \
    --use-librepo=True \
    --chown "$(id -u):$(id -g)" \
    --output /output \
    "$image"

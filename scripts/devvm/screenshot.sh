#!/usr/bin/env bash
# screenshot.sh [DEST]: saves a PNG of the guest's current session to DEST (default
# ./screenshot.png). QEMU's own `screendump` monitor command does not work with
# virtio-vga-gl (`Error: no surface`), so this runs grim -- already in the image --
# inside the guest, as the logged-in session user against its own compositor socket, and
# streams the PNG back over SSH rather than writing it to a guest path first.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
source "$HERE/devvm.env"

dest=${1:-screenshot.png}
# shellcheck disable=SC2016 # $(id -u) is expanded by the guest's shell, not this one
guest_ssh 'XDG_RUNTIME_DIR=/run/user/$(id -u) WAYLAND_DISPLAY=wayland-1 grim -' > "$dest"
echo "saved: $dest"

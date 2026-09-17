#!/usr/bin/env bash
# nested.sh CMD [ARGS...]: tier A. Runs cosmic-comp as a window of the current Wayland
# session and CMD inside it. cosmic-comp picks its nested (winit) backend by itself when
# WAYLAND_DISPLAY is set, opens a socket of its own and hands CMD that WAYLAND_DISPLAY
# (and an Xwayland DISPLAY). Close the window to end it.
set -euo pipefail

[[ $# -ge 1 ]] || { echo "usage: nested.sh CMD [ARGS...]" >&2; exit 2; }
[[ -n ${WAYLAND_DISPLAY:-} ]] || { echo "error: no WAYLAND_DISPLAY: run it from a Wayland session" >&2; exit 1; }
exec cosmic-comp "$@"

#!/usr/bin/env bash
# rig.sh - the one entry point of the shell test rig. Workflows call this and nothing
# else, so every gate runs the same way on a laptop and on the hosted runner.
#
#   rig.sh build-image      build the rig and build stages locally
#   rig.sh publish-image    push the rig stage and print its digest (needs a registry login)
#   rig.sh probe-sandbox    prove that bubblewrap, and with it glycin, works in the rig
#   rig.sh css-parse        GTK parse gate over the generated stylesheets
set -euo pipefail

root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
rig=$root/forge/test/shell
out=${ATHANOR_RIG_OUT:-$root/.scratch/shell-rig}
registry=${ATHANOR_REGISTRY:-ghcr.io/hr-mes}
local_image=localhost/athanor-shell-rig

# The image: an explicit one, else the published one pinned by digest, else the local build.
rig_image() {
    if [ -n "${ATHANOR_RIG_IMAGE:-}" ]; then
        echo "$ATHANOR_RIG_IMAGE"
    elif [ -s "$rig/rig-image.digest" ]; then
        echo "$registry/athanor-shell-rig@$(cat "$rig/rig-image.digest")"
    else
        echo "$local_image:rig"
    fi
}

# label=disable: under SELinux's container_t bubblewrap cannot mount devpts, glycin's
# loaders die, and GTK draws every SVG icon blank without reporting anything.
in_rig() { # in_rig <image> <command...>
    local image=$1
    shift
    mkdir -p "$out"
    podman run --rm --memory 6g --security-opt label=disable \
        -v "$root:/repo:ro" -v "$out:/out" "$image" "$@"
}

case "${1:-}" in
build-image)
    podman build --target rig -t "$local_image:rig" -f "$rig/Containerfile" "$rig"
    podman build --target build -t "$local_image:build" -f "$rig/Containerfile" "$rig"
    ;;
publish-image)
    podman build --target rig -t "$local_image:rig" -f "$rig/Containerfile" "$rig"
    podman push --digestfile "$out/rig-image.digest" "$local_image:rig" "docker://$registry/athanor-shell-rig:latest"
    echo "published $registry/athanor-shell-rig@$(cat "$out/rig-image.digest")"
    echo "commit that digest as forge/test/shell/rig-image.digest together with the goldens it changes"
    ;;
probe-sandbox)
    in_rig "$(rig_image)" bwrap --unshare-all --ro-bind /usr /usr --symlink usr/lib64 /lib64 --dev /dev /usr/bin/true
    echo "bubblewrap works inside the rig: glycin can decode icons"
    ;;
css-parse)
    in_rig "$(rig_image)" bash -c 'python3 /repo/forge/test/shell/css_parse_gate.py --self-test /repo/system/athanor-style/calmo/generated/css/*.css'
    ;;
*)
    sed -n '2,9p' "${BASH_SOURCE[0]}" >&2
    exit 2
    ;;
esac

#!/usr/bin/env bash
# ssh.sh [CMD...]: a shell in the running VM, or CMD run in it.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
source "$HERE/devvm.env"

guest_ssh "$@"

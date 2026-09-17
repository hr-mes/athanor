#!/usr/bin/env bash
# deploy.sh [--restart-session] [--restart-unit UNIT]... SRC:DEST...
# Copies build outputs into the running VM: each local file SRC is installed at the
# absolute guest path DEST, keeping its permission bits, then the session or the named
# system units are restarted.
#
# /usr is read-only on Athanor. The first deploy of a boot makes it writable with
# `bootc usr-overlay`, which puts a transient overlay on it: everything deployed under /usr
# VANISHES AT THE NEXT GUEST REBOOT, and the guest returns to the installed image. Paths
# under /etc and /var are ordinary persistent files and stay until reset.sh.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
source "$HERE/devvm.env"

usage() { echo "usage: deploy.sh [--restart-session] [--restart-unit UNIT]... SRC:DEST..." >&2; exit 2; }

restart=()
files=()
while (($#)); do
  case $1 in
    --restart-session) restart+=(greetd.service) ;;
    --restart-unit) [[ $# -ge 2 ]] || usage; restart+=("$2"); shift ;;
    -*) usage ;;
    *:/*) files+=("$1") ;;
    *) usage ;;
  esac
  shift
done
((${#files[@]})) || usage
for pair in "${files[@]}"; do
  [[ -f ${pair%%:*} ]] || die "not a file: ${pair%%:*}"
done

# shellcheck disable=SC2016 # expanded by the guest's shell
guest_ssh '[ "$(findmnt -no FSTYPE /usr)" = overlay ] || sudo bootc usr-overlay'
for pair in "${files[@]}"; do
  src=${pair%%:*} dest=${pair#*:}
  mode=$(stat -c %a "$src")
  guest_ssh sudo install -D -m "$mode" /dev/stdin "$(printf %q "$dest")" < "$src"
  echo "deployed $src -> $dest"
done
if ((${#restart[@]})); then
  guest_ssh sudo systemctl restart "${restart[@]}"
  echo "restarted ${restart[*]}"
fi

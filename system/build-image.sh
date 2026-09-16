#!/usr/bin/env bash
# Builds one Athanor system image (docs/architecture/doc_system_image.md, S2, S8) from
# system/Containerfile, in CI and locally.
# Usage: build-image.sh --gpu none|nvidia|nvidia-legacy --registry REG --tag TAG [--tag TAG]... [--push]
# SECUREBOOT_SIGNING_KEY in the environment signs the UKI (release); without it the UKI is
# unsigned (pull-request check, local rehearsal).
set -euo pipefail

usage() { echo "usage: ${0##*/} --gpu none|nvidia|nvidia-legacy --registry REG --tag TAG [--tag TAG]... [--push]" >&2; exit 2; }
GPU='' REGISTRY='' PUSH=false TAGS=()
while [[ $# -gt 0 ]]; do
  case $1 in
    --gpu) GPU=${2:?}; shift 2 ;;
    --registry) REGISTRY=${2:?}; shift 2 ;;
    --tag) TAGS+=("${2:?}"); shift 2 ;;
    --push) PUSH=true; shift ;;
    *) usage ;;
  esac
done
case $GPU in
  none) NAME=athanor-system ;;
  nvidia) NAME=athanor-system-nvidia ;;
  nvidia-legacy) NAME=athanor-system-nvidia-legacy ;;
  *) usage ;;
esac
[[ -n $REGISTRY && ${#TAGS[@]} -gt 0 ]] || usage

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
args=(--layers --format docker --build-arg "AZOTH_NVR=$(bash "$ROOT/forge/specs/azoth/nvr.sh")" --build-arg "GPU=$GPU")
if [[ -n ${SECUREBOOT_SIGNING_KEY:-} ]]; then
  # The Secure Boot key and its certificate reach assemble_uki.sh as build secrets: never a layer.
  args+=(--secret "id=uki_key,env=SECUREBOOT_SIGNING_KEY" --secret "id=uki_cert,src=$ROOT/forge/specs/azoth/keys/secureboot/athanor-secureboot.pem")
fi
for tag in "${TAGS[@]}"; do args+=(-t "$REGISTRY/$NAME:$tag"); done
# docker format: the OCI format has no SHELL instruction and podman would drop the
# bash -o pipefail the Containerfile sets for every RUN.
podman build "${args[@]}" -f "$ROOT/system/Containerfile" "$ROOT"
if [[ $PUSH == true ]]; then
  for tag in "${TAGS[@]}"; do bash "$ROOT/forge/scripts/retry.sh" podman push "$REGISTRY/$NAME:$tag"; done
fi
echo "image: $REGISTRY/$NAME:${TAGS[0]}"

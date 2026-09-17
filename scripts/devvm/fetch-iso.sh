#!/usr/bin/env bash
# fetch-iso.sh [TAG]: downloads the published installer ISO into the state directory and
# prints its path. The ISO ships as the single file of a scratch OCI image, so the image
# is copied to an OCI layout with skopeo (anonymous, no container storage) and its one
# layer unpacked. A tag already fetched is not downloaded again.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
source "$HERE/devvm.env"

tag=${1:-$ISO_TAG}
if [[ $tag == newest ]]; then
  # The tags are the ids of the runs that built each ISO, so the highest is the newest.
  tag=$(skopeo list-tags "docker://$ISO_IMAGE" | jq -r '[.Tags[] | select(test("^[0-9]+$")) | tonumber] | max // empty')
  [[ -n $tag ]] || die "no published $ISO_IMAGE tag"
fi

iso=$STATE/iso/athanor-$tag.iso
if [[ ! -f $iso ]]; then
  oci=$STATE/iso/oci-$tag
  rm -rf "$oci"
  mkdir -p "$oci"
  echo "fetching $ISO_IMAGE:$tag" >&2
  skopeo copy "docker://$ISO_IMAGE:$tag" "oci:$oci:$tag" >&2
  layers=$(jq -r '.manifests[0].digest' "$oci/index.json" | sed 's|^sha256:|blobs/sha256/|')
  layers=$(jq -r '.layers[].digest' "$oci/$layers" | sed 's|^sha256:|blobs/sha256/|')
  mkdir "$oci/rootfs"
  for layer in $layers; do
    tar -xf "$oci/$layer" -C "$oci/rootfs"
    rm "$oci/$layer"
  done
  found=$(find "$oci/rootfs" -name '*.iso' -type f -print -quit)
  [[ -n $found ]] || die "$ISO_IMAGE:$tag contains no .iso"
  mv "$found" "$iso"
  rm -rf "$oci"
fi
echo "$iso"

#!/usr/bin/env bash
# The package names an image loses and gains against another (doc_system_image.md, section 4):
# the review of a base change. Usage: package-delta.sh OLD_IMAGE NEW_IMAGE
set -euo pipefail
OLD=${1:?usage: package-delta.sh OLD_IMAGE NEW_IMAGE}
NEW=${2:?usage: package-delta.sh OLD_IMAGE NEW_IMAGE}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
names() { podman run --rm --network none --entrypoint /usr/bin/rpm "$1" -qa --qf '%{NAME}\n' | sort -u; }
names "$OLD" > "$work/old.names"
names "$NEW" > "$work/new.names"
lost=$(comm -23 "$work/old.names" "$work/new.names")
gained=$(comm -13 "$work/old.names" "$work/new.names")
echo "### Package delta: \`$OLD\` → \`$NEW\`"
echo
count() { awk 'NF' <<< "$1" | wc -l; }
echo "Lost ($(count "$lost")):"
# shellcheck disable=SC2016 # the backticks are a literal Markdown fence, not expansion
[[ -z $lost ]] || printf '```\n%s\n```\n' "$lost"
echo "Gained ($(count "$gained")):"
# shellcheck disable=SC2016 # the backticks are a literal Markdown fence, not expansion
[[ -z $gained ]] || printf '```\n%s\n```\n' "$gained"

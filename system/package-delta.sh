#!/usr/bin/env bash
# The package names an image loses and gains against another (doc_system_image.md, section 4):
# the review of a base change. Usage: package-delta.sh OLD_IMAGE NEW_IMAGE
set -euo pipefail
OLD=${1:?usage: package-delta.sh OLD_IMAGE NEW_IMAGE}
NEW=${2:?usage: package-delta.sh OLD_IMAGE NEW_IMAGE}
names() { podman run --rm --network none --entrypoint /usr/bin/rpm "$1" -qa --qf '%{NAME}\n' | sort -u; }
names "$OLD" > old.names
names "$NEW" > new.names
lost=$(comm -23 old.names new.names)
gained=$(comm -13 old.names new.names)
echo "### Package delta: \`$OLD\` → \`$NEW\`"
echo
count() { awk 'NF' <<< "$1" | wc -l; }
echo "Lost ($(count "$lost")):"
[[ -z $lost ]] || printf '```\n%s\n```\n' "$lost"
echo "Gained ($(count "$gained")):"
[[ -z $gained ]] || printf '```\n%s\n```\n' "$gained"
rm -f old.names new.names

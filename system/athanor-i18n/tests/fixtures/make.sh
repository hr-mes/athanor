#!/usr/bin/env bash
# make.sh - rebuilds the fixtures from their .po sources with the real msgfmt.
# The .mo files are committed: the tests must not need gettext installed.
set -euo pipefail
here=$(dirname "${BASH_SOURCE[0]}")
msgfmt --endianness=little -o "$here/it.mo" "$here/it.po"
msgfmt --endianness=big -o "$here/it-big-endian.mo" "$here/it.po"
msgfmt --endianness=little -o "$here/ar.mo" "$here/ar.po"
# msgfmt converts to UTF-8 unless told not to; this fixture must stay Latin-1.
msgfmt --no-convert --endianness=little -o "$here/latin1.mo" "$here/latin1.po"

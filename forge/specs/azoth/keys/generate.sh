#!/usr/bin/env bash
# Generates one of the project signing keys (docs/architecture/doc_kernel_build.md,
# section 6) from its OpenSSL profile in profiles/. The private key goes to KEY-DIR, which
# must lie outside the repository; the public certificate goes to keys/<profile>/ in PEM,
# and in DER as well for secureboot, the form mokutil --import takes. Prints what to
# record: the SHA-256 fingerprint and the subject key identifier, the id the kernel logs
# a compiled-in certificate with.
#
# Usage: generate.sh secureboot|modules --key-dir DIR
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
die() { echo "error: $*" >&2; exit 1; }

PROFILE=${1:-}
[[ $# -gt 0 ]] && shift
KEY_DIR=''
while [[ $# -gt 0 ]]; do
  case $1 in
    --key-dir) KEY_DIR=$2; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ ($PROFILE == secureboot || $PROFILE == modules) && $KEY_DIR ]] \
  || { echo "usage: generate.sh secureboot|modules --key-dir DIR" >&2; exit 2; }

REPO=$(git -C "$HERE" rev-parse --show-toplevel)
KEY_DIR=$(realpath -m "$KEY_DIR")
[[ $KEY_DIR/ != "$REPO"/* ]] || die "--key-dir must lie outside the repository: $KEY_DIR"
(umask 077 && mkdir -p "$KEY_DIR")

KEY=$KEY_DIR/athanor-$PROFILE.key
CERT=$HERE/$PROFILE/athanor-$PROFILE.pem
[[ ! -e $KEY ]] || die "$KEY exists: a key is never overwritten"
[[ ! -e $CERT ]] || die "${CERT#"$REPO"/} exists: retire the previous certificate first"
mkdir -p "$HERE/$PROFILE"

umask 077
openssl req -new -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
  -config "$HERE/profiles/$PROFILE.cnf" -keyout "$KEY" -out "$CERT"
chmod 644 "$CERT"
if [[ $PROFILE == secureboot ]]; then
  openssl x509 -in "$CERT" -outform DER -out "${CERT%.pem}.der"
  chmod 644 "${CERT%.pem}.der"
fi

echo "private key: $KEY"
echo "certificate: ${CERT#"$REPO"/}"
openssl x509 -in "$CERT" -noout -subject -enddate -fingerprint -sha256 \
  -ext basicConstraints,keyUsage,extendedKeyUsage,subjectKeyIdentifier

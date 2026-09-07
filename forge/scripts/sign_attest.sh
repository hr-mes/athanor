#!/usr/bin/env bash
# Keyless signature and SPDX attestation of an OCI image with cosign, with bounded
# retries. Every attempt is a round trip to Fulcio, Rekor and the timestamp authority:
# public services whose transient failures (a dropped TCP read, as in runs 34033820792
# selinux and openssl-native) must not fail a build that is otherwise complete. The
# retry policy lives in retry.sh. A 502 from Rekor is usually not transient: it refuses
# bodies over about 20 MB, which is why sbom_rootfs.sh keeps the SBOM small.
# cosign must be on PATH (the DAG jobs run this under `nix shell nixpkgs#cosign -c`),
# and the registry login is the caller's business.
#
# Usage: sign_attest.sh IMAGE SBOM.spdx.json
set -euo pipefail

[[ $# -eq 2 ]] || { echo "usage: sign_attest.sh IMAGE SBOM.spdx.json" >&2; exit 2; }
image=$1 sbom=$2
[[ -s $sbom ]] || { echo "SBOM missing or empty: $sbom" >&2; exit 2; }

retry="$(dirname "${BASH_SOURCE[0]}")/retry.sh"

bash "$retry" cosign sign --yes "$image"
bash "$retry" cosign attest --yes --type spdxjson --predicate "$sbom" "$image"

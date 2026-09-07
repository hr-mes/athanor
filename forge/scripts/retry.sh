#!/usr/bin/env bash
# Run a command until it succeeds, for operations whose failures are transient by
# nature: a registry push that the server aborts with a stalled chunked upload (run
# 34051055291, builder push, HTTP 400 after 16 minutes), a network read that drops, a
# public service restarting under a signature. The delay doubles from 15 s, so the
# default five attempts span about four minutes, long enough to outlast a restart; a
# command that fails them all is a real error and the caller sees its exit status.
#
# Retries are for failures that pass. The Rekor 502 of runs 34123978083 and
# 34131187743 was not one of them: the service was refusing an oversized body, and no
# number of attempts could have helped (see sbom_rootfs.sh). Read the error first.
#
# Usage: [RETRY_ATTEMPTS=n] retry.sh COMMAND [ARG...]
set -euo pipefail

[[ $# -ge 1 ]] || { echo "usage: retry.sh COMMAND [ARG...]" >&2; exit 2; }

attempts=${RETRY_ATTEMPTS:-5}
[[ $attempts =~ ^[1-9][0-9]*$ ]] || { echo "retry.sh: RETRY_ATTEMPTS must be a positive integer, got '${attempts}'" >&2; exit 2; }

attempt=1
delay=15
until "$@"; do
  status=$?
  if [[ $attempt -ge $attempts ]]; then
    echo "retry.sh: '$1' failed ${attempt} times, giving up (exit ${status})" >&2
    exit "$status"
  fi
  echo "retry.sh: '$1' failed (exit ${status}), attempt ${attempt} of ${attempts}: retrying in ${delay} s" >&2
  sleep "$delay"
  attempt=$((attempt + 1))
  delay=$((delay * 2))
done

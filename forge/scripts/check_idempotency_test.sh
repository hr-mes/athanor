#!/bin/bash
# Checks that the registry probe in check_idempotency.sh tells its three answers apart,
# against images that really are and really are not in the registry.
#
# Run it from anywhere with skopeo available:
#   bash forge/scripts/check_idempotency_test.sh
#
# The case that matters is the first one. The probe used to pass --creds whenever a token
# was set, and a token the registry rejects makes skopeo fail with 403 even on an image
# anyone can read anonymously. That failure was read as "image absent", so every package
# rebuilt on every run: 47 nodes and 4.6 hours of runner time for a push that touched none
# of them. Anonymous first, credentials only as a fallback, and a registry that does not
# answer at all is an error rather than a silent rebuild.
set -u
h_present=c99e47feefeebd9cad8b8c7cb237230477811b2aa659be4b61a9d565ee3c00a1
h_absent=0000000000000000000000000000000000000000000000000000000000000000

probe() { # probe TAG TOKEN
  local url="docker://ghcr.io/hr-mes/athanor-forge-mold:$1" token=$2
  local status="" err rc
  for attempt in anonymous authenticated; do
    local args=("--no-tags")
    if [[ $attempt == authenticated ]]; then
      [[ -n $token ]] || continue
      args+=("--creds" "hr-mes:${token}")
    fi
    err=$(skopeo inspect "${args[@]}" "$url" 2>&1 >/dev/null); rc=$?
    if [[ $rc -eq 0 ]]; then status=found; break; fi
    if grep -qi 'manifest unknown\|name unknown\|not found' <<< "$err"; then status=absent; break; fi
    status=error
  done
  echo "$status"
}

fail=0
check() { # check LABEL EXPECTED ACTUAL
  if [[ "$2" == "$3" ]]; then echo "  ok  $1 -> $3"; else echo "  FAIL $1: expected $2, got $3"; fail=1; fi
}

# The exact CI failure: a real image, a token the registry rejects.
check "present image + rejected token" found "$(probe "$h_present" not-a-real-token)"
# No token at all, the way a local run works.
check "present image, no token"        found "$(probe "$h_present" "")"
# A tag that genuinely does not exist must read as absent, not as an error.
check "missing image"                  absent "$(probe "$h_absent" "")"
check "missing image + rejected token" absent "$(probe "$h_absent" not-a-real-token)"

exit $fail

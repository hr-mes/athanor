#!/usr/bin/env bash
# The kernel and NVIDIA module artifacts of the current pins, verified in the registry and
# identified by digest (docs/architecture/doc_build_ordering.md, O2-O5, O7). Every workflow of
# the build ordering runs this script and reads its file; none repeats its decisions.
#
#   resolve [--expect-kernel-digest D]  write kernel-artifacts.env: state=ready, modules-missing
#                                       or kernel-missing, then the verified digests. Exit 0 for
#                                       the three states; 1 on a registry, Rekor, network or data
#                                       error, or when azoth:<nvr> is not D (republished since)
#   require-ready                       resolve, then exit 1 unless state=ready
#   get KEY                             print the value of KEY; exit 1 when the file lacks it
#   has KEY                             exit 0 when KEY has a non-empty value
#   digest REF                          the digest of REF, empty when the tag does not exist
#   signed REF kernel|modules           signed or unsigned, by the workflow that publishes it
#   predicates REF modules              the custom predicates of REF, one JSON per line, or
#                                       unverified
#   probe digest|signed|predicates ...  one attempt of the three above (they retry it)
#
# The file is $KERNEL_ARTIFACTS_DIR/kernel-artifacts.env (default: kernel-artifacts/ at the
# repository root). KERNEL_REGISTRY is the registry and owner (default ghcr.io/ followed by
# GITHUB_REPOSITORY_OWNER, else hr-mes); GITHUB_SERVER_URL and GITHUB_REPOSITORY name the
# workflows whose signatures are trusted. Needs skopeo, cosign and jq.
set -euo pipefail
shopt -s inherit_errexit

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SELF=$HERE/$(basename "${BASH_SOURCE[0]}")
ROOT=$(dirname "$HERE")
DIR=${KERNEL_ARTIFACTS_DIR:-$ROOT/kernel-artifacts}
FILE=$DIR/kernel-artifacts.env
PINS=$ROOT/forge/specs/azoth/pins.env
owner=${GITHUB_REPOSITORY_OWNER:-hr-mes}
REGISTRY=${KERNEL_REGISTRY:-ghcr.io/${owner,,}}
ISSUER=https://token.actions.githubusercontent.com
workflows="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-hr-mes/athanor}/.github/workflows"
# Owner, repository and host names hold no regex metacharacter other than the dot.
workflows=${workflows//./\\.}
declare -A IDENTITY=(
  [kernel]="^${workflows}/kernel-build\.yml@refs/heads/"
  [modules]="^${workflows}/nvidia-kmod\.yml@refs/heads/"
)
# cosign v3 reports a missing or foreign signature or attestation with these messages. Any
# other failure (registry, Rekor, TUF, network) is an error, never a missing artifact.
# "no matching signatures" and "no matching attestations" are anchored to the end of the
# line: cosign appends the last per-signature error to that same prefix when the real cause
# is transient (a Rekor or cert-chain fetch failure), and an unanchored match would swallow
# that outage as a plain "unsigned" verdict instead of failing (O3).
UNVERIFIED='no signatures found|no matching signatures: *$|no matching attestations: *$|no matching CertificateIdentity'

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

usage() { sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "$SELF" >&2; exit 2; }
die() { echo "kernel-artifacts: $*" >&2; exit 1; }
retry() { bash "$ROOT/forge/scripts/retry.sh" "$@"; }
ask() { retry bash "$SELF" probe "$@"; }
identity() { [[ -n ${IDENTITY[${1:-}]:-} ]] || usage; echo "${IDENTITY[$1]}"; }

probe_digest() {
  local out status=0
  out=$(skopeo inspect --format '{{.Digest}}' "docker://$1" 2> "$TMP/err") || status=$?
  if [[ $status -ne 0 ]]; then
    grep -q 'manifest unknown' "$TMP/err" && return 0
    cat "$TMP/err" >&2
    return 1
  fi
  [[ $out =~ ^sha256:[0-9a-f]{64}$ ]] || die "$1: malformed digest '$out'"
  echo "$out"
}

probe_signed() {
  local status=0
  cosign verify --certificate-identity-regexp "$(identity "$2")" --certificate-oidc-issuer "$ISSUER" "$1" > /dev/null 2> "$TMP/err" || status=$?
  if [[ $status -eq 0 ]]; then
    echo signed
  elif grep -qE "$UNVERIFIED" "$TMP/err"; then
    echo unsigned
  else
    cat "$TMP/err" >&2
    return 1
  fi
}

probe_predicates() {
  local status=0
  cosign verify-attestation --type custom --certificate-identity-regexp "$(identity "$2")" --certificate-oidc-issuer "$ISSUER" "$1" > "$TMP/out" 2> "$TMP/err" || status=$?
  if [[ $status -eq 0 ]]; then
    jq -ce '.payload | @base64d | fromjson | .predicate.Data | fromjson' "$TMP/out" || die "$1: malformed attestation"
  elif grep -qE "$UNVERIFIED" "$TMP/err"; then
    echo unverified
  else
    cat "$TMP/err" >&2
    return 1
  fi
}

get() {
  local line
  [[ -f $FILE ]] || die "$FILE does not exist: run kernel-artifacts.sh resolve first"
  line=$(grep -m1 "^$1=" "$FILE") || die "$FILE has no $1"
  echo "${line#*=}"
}

write() { # write STATE LINE...: replace the file in one step
  mkdir -p "$DIR"
  printf '%s\n' "state=$1" "${@:2}" > "$FILE.tmp"
  mv "$FILE.tmp" "$FILE"
  echo "kernel-artifacts: state=$1"
}

module_verdict() { # module_verdict REF BRANCH KERNEL_DIGEST DEVEL_DIGEST: verified or unverified
  local signed predicates pins
  signed=$(ask signed "$1" modules)
  [[ $signed == signed ]] || { echo unverified; return 0; }
  predicates=$(ask predicates "$1" modules)
  [[ $predicates != unverified ]] || { echo unverified; return 0; }
  pins=$(sed -n "s/^\(NVIDIA_${2^^}_[A-Z0-9_]*\)=\(.*\)$/\1\t\2/p" "$PINS" | jq -Rn '[inputs | split("\t") | {(.[0]): .[1]}] | add')
  jq -sr --arg branch "$2" --arg kernel "$3" --arg devel "$4" --argjson pins "$pins" '
    if any(.[]; .driver == $branch and .kernel_digest == $kernel and .devel_digest == $devel and (.pins as $p | $pins | to_entries | all(.value == $p[.key])))
    then "verified" else "unverified" end' <<< "$predicates"
}

resolve() {
  local expect='' nvr kernel devel kernel_signed devel_signed branch version tag digest verdict state=ready
  while [[ $# -gt 0 ]]; do
    case $1 in
      --expect-kernel-digest) [[ $# -ge 2 ]] || usage; expect=$2; shift 2 ;;
      *) usage ;;
    esac
  done
  rm -f "$FILE"
  nvr=$(bash "$ROOT/forge/specs/azoth/nvr.sh")
  local -a lines=("nvr=$nvr" "registry=$REGISTRY")
  kernel=$(ask digest "$REGISTRY/azoth:$nvr")
  devel=$(ask digest "$REGISTRY/azoth-devel:$nvr")
  if [[ -z $kernel || -z $devel ]]; then
    [[ -z $expect ]] || die "$REGISTRY/azoth:$nvr is no longer published, the caller resolved $expect: the kernel was republished or withdrawn since"
    write kernel-missing "${lines[@]}"
    return 0
  fi
  [[ -z $expect || $kernel == "$expect" ]] || die "$REGISTRY/azoth:$nvr is $kernel, the caller resolved $expect: the kernel was republished since"
  kernel_signed=$(ask signed "$REGISTRY/azoth@$kernel" kernel)
  devel_signed=$(ask signed "$REGISTRY/azoth-devel@$devel" kernel)
  if [[ $kernel_signed != signed || $devel_signed != signed ]]; then
    [[ -z $expect ]] || die "$REGISTRY/azoth:$nvr is no longer signed, the caller resolved $expect: the kernel was republished or its signature was revoked since"
    write kernel-missing "${lines[@]}"
    return 0
  fi
  lines+=("kernel_digest=$kernel" "devel_digest=$devel")
  for branch in open legacy; do
    version=$(sed -n "s/^NVIDIA_${branch^^}_VERSION=//p" "$PINS")
    [[ -n $version ]] || die "NVIDIA_${branch^^}_VERSION is not set in $PINS"
    tag="$nvr-k${kernel:7:12}-$branch-$version"
    lines+=("nvidia_${branch}_version=$version" "nvidia_${branch}_tag=$tag")
    digest=$(ask digest "$REGISTRY/azoth-nvidia:$tag")
    verdict=unverified
    [[ -z $digest ]] || verdict=$(module_verdict "$REGISTRY/azoth-nvidia@$digest" "$branch" "$kernel" "$devel")
    if [[ $verdict == verified ]]; then
      lines+=("nvidia_${branch}_digest=$digest")
    else
      state=modules-missing
    fi
  done
  write "$state" "${lines[@]}"
}

[[ $# -ge 1 ]] || usage
command=$1
shift
case $command in
  resolve) resolve "$@" ;;
  require-ready)
    [[ $# -eq 0 ]] || usage
    resolve
    state=$(get state)
    [[ $state == ready ]] || die "state=$state: the kernel of the pins and both NVIDIA module branches must be published, signed and attested"
    ;;
  get) [[ $# -eq 1 ]] || usage; get "$1" ;;
  has) [[ $# -eq 1 ]] || usage; [[ -f $FILE ]] && grep -q "^$1=." "$FILE" ;;
  digest) [[ $# -eq 1 ]] || usage; ask digest "$1" ;;
  signed) [[ $# -eq 2 ]] || usage; ask signed "$1" "$2" ;;
  predicates) [[ $# -eq 2 ]] || usage; ask predicates "$1" "$2" ;;
  probe)
    [[ $# -ge 2 ]] || usage
    case $1 in
      digest) [[ $# -eq 2 ]] || usage; probe_digest "$2" ;;
      signed) [[ $# -eq 3 ]] || usage; probe_signed "$2" "$3" ;;
      predicates) [[ $# -eq 3 ]] || usage; probe_predicates "$2" "$3" ;;
      *) usage ;;
    esac
    ;;
  *) usage ;;
esac

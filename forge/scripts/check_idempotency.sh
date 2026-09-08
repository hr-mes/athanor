#!/bin/bash

# Deterministic Build Timestamp (Reproducible Builds)
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1723320000}
set -euo pipefail
# Bedrock Pure Bash Idempotency Checker
# Replaces python3 idempotency_checker.py with native system tools (find, sha256sum, skopeo)

PACKAGE=""
REGISTRY=""
OWNER=""
IMAGE_NAME=""

BASE_DIGEST=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --package) PACKAGE="$2"; shift 2 ;;
    --registry) REGISTRY="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    --image-name) IMAGE_NAME="$2"; shift 2 ;;
    --base-digest) BASE_DIGEST="$2"; shift 2 ;;
    *) echo "Argomento sconosciuto: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$IMAGE_NAME" ]]; then
  IMAGE_NAME="athanor-forge-${PACKAGE}"
fi

# Determina directory o seed per il calcolo dell'hash
if [[ "$PACKAGE" == "builder" ]]; then
  DIR="builder"
elif [[ -d "specs/athanor-${PACKAGE}" ]]; then
  DIR="specs/athanor-${PACKAGE}"
elif [[ -d "specs/${PACKAGE}" ]]; then
  DIR="specs/${PACKAGE}"
else
  DIR=""
fi

if [[ -n "$DIR" && -d "$DIR" ]]; then
  # Hash SHA-256 deterministico dei path relativi e dei contenuti
  CONTENT_HASH=$({
    find "$DIR" -type f -print0 | sort -z | xargs -0 sha256sum
    if [[ -f "config/rpmmacros" ]]; then
      echo -n "config/rpmmacros"
      cat "config/rpmmacros"
    fi
    if [[ -f "builder/Containerfile" ]]; then
      echo -n "builder/Containerfile"
      cat "builder/Containerfile"
    fi
    if [[ -f "builder/rpmfusion-custom.repo" ]]; then
      echo -n "builder/rpmfusion-custom.repo"
      cat "builder/rpmfusion-custom.repo"
    fi
    if [[ -f "config/packages.json" ]]; then
      echo -n "config/packages.json"
      cat "config/packages.json"
    fi
    if [[ "$PACKAGE" == "builder" ]]; then
      # L'immagine builder è definita dal flake: senza queste righe una modifica a
      # flake.nix o al lock darebbe CACHE_HIT e un builder stantio.
      for f in ../flake.nix ../flake.lock; do
        if [[ -f "$f" ]]; then
          echo -n "$f"
          cat "$f"
        fi
      done
    fi
    echo -n "CACHE_EPOCH=v12"
  } | sha256sum | awk '{print $1}')
else
  # Pacchetti upstream senza spec locale
  if command -v dnf >/dev/null 2>&1; then
    # Cerchiamo la versione effettiva nei repository abilitati
    UPSTREAM_VER=$(dnf repoquery --qf "%{VERSION}-%{RELEASE}\n" --arch x86_64,noarch "$PACKAGE" 2>/dev/null | sort -V | tail -n 1 || true)
  else
    UPSTREAM_VER=""
  fi
  
  # Invalidiamo la cache degli upstream (compilati da zero) ad ogni aggiornamento della Base Image
  # per prevenire desincronizzazione librerie (es. libx265 per ffmpeg).
  if [[ -z "${BASE_DIGEST:-}" ]]; then
    if command -v skopeo >/dev/null 2>&1; then
      BASE_DIGEST=$(skopeo inspect --no-tags "docker://ghcr.io/${OWNER}/ermete-base-nvidia:latest" 2>/dev/null | grep -oP '"Digest": "\K[^"]+' | head -n 1 || true)
    fi
  fi
  
  VERSION=${UPSTREAM_VER:-unknown}
  if [[ -n "$UPSTREAM_VER" ]]; then
    CONTENT_HASH=$(echo -n "${PACKAGE}-${UPSTREAM_VER}-${BASE_DIGEST}-v12" | sha256sum | awk '{print $1}')
  else
    CONTENT_HASH=$(echo -n "${PACKAGE}-${VERSION}-upstream-v12-${BASE_DIGEST}" | sha256sum | awk '{print $1}')
  fi
fi

echo ">>> Content Hash calcolato per ${PACKAGE}: ${CONTENT_HASH}" >&2

# Costruisce URL immagine GHCR
IMAGE_URL="docker://${REGISTRY}/${OWNER}/${IMAGE_NAME}:${CONTENT_HASH}"
IMAGE_URL_LOWER=$(echo "$IMAGE_URL" | tr '[:upper:]' '[:lower:]')

echo ">>> Verifica esistenza su GHCR: ${IMAGE_URL_LOWER}..." >&2

# Verifica con skopeo (se skopeo non è installato, tenta di installarlo o usa fallback)
if ! command -v skopeo >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    sudo -n dnf install -y skopeo >&2 || dnf install -y skopeo >&2 || :
  fi
fi

if ! command -v skopeo >/dev/null 2>&1; then
  echo "check_idempotency.sh: skopeo non trovato, impossibile interrogare il registro" >&2
  exit 1
fi

# Prima senza credenziali, poi con. Le immagini della forge sono pubbliche e si leggono
# anonimamente; passare --creds a un registro che poi rifiuta quelle credenziali fa
# fallire skopeo con 403 anche su un'immagine leggibile da chiunque. Quel fallimento era
# indistinguibile da "immagine assente" e ricostruiva l'intero DAG a ogni run: tutti e 47
# i nodi, 4,6 ore di runner, per un push che non toccava nessuno di quei pacchetti.
#
# L'esito viene distinto in tre casi, perché "non c'è" e "non sono riuscito a chiedere"
# richiedono risposte diverse: la prima è una build da fare, la seconda è un guasto.
inspect_status=""
for attempt in anonymous authenticated; do
  INSPECT_ARGS=("--no-tags")
  if [[ "$attempt" == "authenticated" ]]; then
    [[ -n "${GITHUB_TOKEN:-}" ]] || continue
    INSPECT_ARGS+=("--creds" "${OWNER}:${GITHUB_TOKEN}")
  fi

  set +e
  inspect_err=$(skopeo inspect "${INSPECT_ARGS[@]}" "${IMAGE_URL_LOWER}" 2>&1 >/dev/null)
  rc=$?
  set -e

  if [[ $rc -eq 0 ]]; then
    inspect_status="found"
    break
  fi
  # Il registro risponde "manifest unknown" quando il tag non esiste: è una risposta, non
  # un guasto, e non serve riprovare autenticati.
  if grep -qi 'manifest unknown\|name unknown\|not found' <<< "$inspect_err"; then
    inspect_status="absent"
    break
  fi
  inspect_status="error"
  last_error=$inspect_err
done

case "$inspect_status" in
  found) CACHE_HIT="true" ;;
  absent) CACHE_HIT="false" ;;
  *)
    # Né presente né assente: il registro non ha risposto. Costruire sarebbe uno spreco
    # silenzioso, dichiarare la cache valida sarebbe peggio: si ferma e lo dice.
    echo "check_idempotency.sh: il registro non ha risposto per ${IMAGE_URL_LOWER}" >&2
    echo "${last_error:-nessun dettaglio}" >&2
    exit 1
    ;;
esac

echo "CACHE_HIT=${CACHE_HIT}"
echo "CONTENT_HASH=${CONTENT_HASH}"
if [[ "$CACHE_HIT" == "true" ]]; then
  echo ">>> Cache Hit! L'immagine esiste già su GHCR." >&2
else
  echo ">>> Cache Miss. Procedo con la build." >&2
fi

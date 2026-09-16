#!/usr/bin/env bash
# Build gate of the system image (docs/architecture/doc_system_image.md, S3, S6, S8): run on the
# finished image root before the UKI is assembled.
#   none           no NVIDIA module, kernel argument, modprobe option, dracut configuration
#                  or negativo17 repository
#   nvidia         modules, driver packages, shim and GSP firmware at NVIDIA_OPEN_VERSION,
#                  and the EGL, GBM and Vulkan files of the userspace
#   nvidia-legacy  the same at NVIDIA_LEGACY_VERSION, with the RPM Fusion packages, no GSP check
# Usage: gate.sh none|nvidia|nvidia-legacy PINS_ENV [ROOT]
set -euo pipefail

GPU=${1:?usage: gate.sh none|nvidia|nvidia-legacy PINS_ENV [ROOT]}
PINS=${2:?usage: gate.sh none|nvidia|nvidia-legacy PINS_ENV [ROOT]}
ROOT=${3:-/}
bad=0
violation() { echo "nvidia gate: $*" >&2; bad=1; }

mapfile -t modules < <(find "$ROOT/usr/lib/modules" -path '*/extra/nvidia/*' -name 'nvidia*.ko*' 2> /dev/null | sort)

if [[ $GPU == none ]]; then
  for ko in "${modules[@]}"; do violation "${ko#"$ROOT"}: NVIDIA module in the default image"; done
  while IFS= read -r f; do
    violation "${f#"$ROOT"}: NVIDIA configuration in the default image"
  # Word-bounded: Fedora's dist-blacklist.conf names the unrelated framebuffer driver nvidiafb.
  done < <(grep -rlE '(^|[^[:alnum:]_])nvidia([^[:alnum:]_]|$)' "$ROOT/usr/lib/bootc/kargs.d" "$ROOT/usr/lib/modprobe.d" "$ROOT/etc/modprobe.d" "$ROOT/usr/lib/dracut/dracut.conf.d" 2> /dev/null | sort)
  while IFS= read -r f; do
    violation "${f#"$ROOT"}: negativo17 repository in the default image"
  done < <(grep -rl 'negativo17' "$ROOT/etc/yum.repos.d" 2> /dev/null | sort)
  exit "$bad"
fi

case $GPU in
  nvidia) expected=$(sed -n 's/^NVIDIA_OPEN_VERSION=//p' "$PINS"); packages=(nvidia-driver nvidia-driver-libs nvidia-kmod-common azoth-nvidia-kmod) ;;
  nvidia-legacy) expected=$(sed -n 's/^NVIDIA_LEGACY_VERSION=//p' "$PINS"); packages=(xorg-x11-drv-nvidia xorg-x11-drv-nvidia-libs azoth-nvidia-kmod) ;;
  *) echo "gate.sh: unknown GPU $GPU" >&2; exit 2 ;;
esac
[[ -n $expected ]] || { echo "gate.sh: no NVIDIA version for $GPU in $PINS" >&2; exit 2; }

[[ ${#modules[@]} -gt 0 ]] || violation "no nvidia*.ko under /usr/lib/modules/*/extra/nvidia"
for ko in "${modules[@]}"; do
  got=$(modinfo -F version "$ko")
  [[ $got == "$expected" ]] || violation "${ko##*/}: module $got, pin $expected"
done
for pkg in "${packages[@]}"; do
  if got=$(rpm --root "$ROOT" -q --qf '%{VERSION}' "$pkg"); then
    [[ $got == "$expected" ]] || violation "$pkg: package $got, pin $expected"
  else
    violation "$pkg: not installed"
  fi
done
if [[ $GPU == nvidia ]]; then
  for fw in gsp_ga10x.bin gsp_tu10x.bin; do
    [[ -f $ROOT/usr/lib/firmware/nvidia/$expected/$fw ]] || violation "/usr/lib/firmware/nvidia/$expected/$fw missing"
  done
fi
for f in usr/share/glvnd/egl_vendor.d/10_nvidia.json usr/lib64/gbm/nvidia-drm_gbm.so; do
  [[ -e $ROOT/$f ]] || violation "/$f missing"
done
compgen -G "$ROOT/usr/share/vulkan/icd.d/nvidia_icd*.json" > /dev/null || violation "/usr/share/vulkan/icd.d/nvidia_icd*.json missing"
exit "$bad"

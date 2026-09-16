%global debug_package %{nil}
Name:           athanor-nvidia-config
Version:        1.0.0
Release:        1%{?dist}
Summary:        Athanor configuration for the NVIDIA image variants
License:        MIT
URL:            https://github.com/hr-mes/athanor
BuildArch:      noarch
Requires:       azoth-nvidia-kmod

%description
Kernel arguments, modprobe and dracut settings, suspend and resume units and their presets
for the NVIDIA driver. Installed only by athanor-system-nvidia and
athanor-system-nvidia-legacy (docs/architecture/doc_system_image.md, S4).

%prep

%build

%install
mkdir -p %{buildroot}
cp -a %{_sourcedir}/usr %{buildroot}/

%files
/usr/bin/nvidia-sleep.sh
/usr/lib/bootc/kargs.d/01-nvidia.toml
/usr/lib/dracut/dracut.conf.d/nvidia-drm.conf
/usr/lib/modprobe.d/nvidia-drm.conf
/usr/lib/modprobe.d/nvidia-power-management.conf
/usr/lib/modules-load.d/10-nvidia.conf
/usr/lib/systemd/system-preset/70-nvidia.preset
/usr/lib/systemd/system-sleep/nvidia
/usr/lib/systemd/system/nvidia-*
/usr/lib/udev/rules.d/71-nvidia-uaccess.rules

%changelog
* Wed Sep 16 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- NVIDIA configuration moved out of athanor-base-config (doc_system_image.md, S4)

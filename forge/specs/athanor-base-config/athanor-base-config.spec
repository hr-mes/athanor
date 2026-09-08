%global debug_package %{nil}
Name:           athanor-base-config
Version:        43.0.0
Release:        2%{?dist}
Summary:        Athanor OS Base Configuration (NVIDIA, Systemd, Branding, GPG)

License:        MIT
URL:            https://github.com/hr-mes/athanor-forge
BuildArch:      noarch

Requires:       glibc-langpack-it glibc-langpack-en
Provides:       fedora-logos = 43
Provides:       fedora-logos = %{version}-%{release}
Obsoletes:      fedora-logos < 43
Provides:       fedora-logos-httpd = 43
Provides:       fedora-logos-httpd = %{version}-%{release}
Obsoletes:      fedora-logos-httpd < 43
Provides:       system-logos = 43
Provides:       system-logos = %{version}-%{release}
Obsoletes:      system-logos < 43
Provides:       system-logos-httpd = 43
Provides:       system-logos-httpd = %{version}-%{release}
Obsoletes:      system-logos-httpd < 43
Provides:       fedora-release = 43
Provides:       fedora-release = %{version}-%{release}
Obsoletes:      fedora-release < 43
Provides:       fedora-release-systemd = 43
Provides:       fedora-release-systemd = %{version}-%{release}
Obsoletes:      fedora-release-systemd < 43
Provides:       fedora-release-identity = 43
Provides:       fedora-release-identity = %{version}-%{release}
Obsoletes:      fedora-release-identity < 43
Provides:       fedora-release-common = 43
Provides:       fedora-release-common = %{version}-%{release}
Obsoletes:      fedora-release-common < 43
Provides:       system-release = 43
Provides:       system-release = %{version}-%{release}
Provides:       system-release(43)
Obsoletes:      system-release < 43
%description
This package provides the foundational configuration for Athanor Base.
It includes NVIDIA sleep scripts, Dracut configurations, modprobe rules,
Systemd presets, custom Plymouth/GDM branding, Polkit rules, and GPG keys.

%prep
# No extraction needed, files are injected in install phase.

%build
# Nothing to build

%install
mkdir -p %{buildroot}
find %{_sourcedir} -mindepth 1 -maxdepth 1 ! -name "*.spec" -exec cp -a {} %{buildroot}/ \;
mkdir -p %{buildroot}/usr/lib/tmpfiles.d
mv %{buildroot}/etc/tmpfiles.d/* %{buildroot}/usr/lib/tmpfiles.d/
rm -rf %{buildroot}/etc/tmpfiles.d

%files
/etc/pki/rpm-gpg/*
/etc/selinux/config
/etc/yum.repos.d/*
/etc/ssh/sshd_config.d/*
/etc/systemd/coredump.conf.d/*
/usr/lib/systemd/system/*
/usr/lib/tmpfiles.d/*
/usr/lib/systemd/journald.conf.d/*
/usr/bin/nvidia-sleep.sh
/usr/lib/fedora-release
/usr/lib/os-release
/usr/lib/bootc/kargs.d/01-nvidia.toml
/usr/lib/bootc/kargs.d/02-hardening.toml
/usr/lib/bootc/kargs.d/03-ima-evm.toml
/usr/lib/bootc/kargs.d/04-confidential-compute.toml
/usr/lib/bootc/kargs.d/05-dma-protection.toml
/usr/lib/bootc/kargs.d/06-mte-lam.toml
/etc/grub.d/01_athanor_grub_auth
/usr/lib/dracut/dracut.conf.d/*
/usr/lib/modprobe.d/*
/usr/lib/modules-load.d/*
/usr/lib/systemd/system-preset/*
/usr/lib/systemd/system-sleep/nvidia
/usr/lib/systemd/system/nvidia-*
/usr/lib/systemd/system/scx_loader.service.d/*
/usr/lib/sysusers.d/*
/usr/lib/udev/rules.d/*
/usr/share/pixmaps/*
/usr/share/plymouth/themes/spinner/watermark.png
/usr/share/polkit-1/rules.d/*
/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/override.conf

%changelog
* Fri Jul 31 2026 Athanor <athanor@customer.mlnnita1.isp.starlink.com> - 1.0.0-6
- Add Provides and Obsoletes for fedora-logos to avoid conflicts during system image build
* Thu Jul 30 2026 Athanor <athanor@customer.mlnnita1.isp.starlink.com> - 1.0.0-5
- Trigger rebuild to execute deduplication fix
* Tue Jul 14 2026 Athanor Forge <forge@athanor.os> - 1.0.0-3
- Require glibc-langpack-it and glibc-langpack-en to guarantee Bedrock locale availability across all apps when glibc-all-langpacks is pruned

* Mon Jul 06 2026 Athanor Forge <forge@athanor.os> - 1.0.0-2
- Add enable nvidia-persistenced.service to systemd preset for deterministic GPU node creation

* Wed Jul 01 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Initial encapsulation of raw files into RPM for Bedrock logic

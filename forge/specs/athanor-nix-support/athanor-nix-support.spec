%global debug_package %{nil}
Name:           athanor-nix-support
Version:        1.0.0
Release:        3%{?dist}
Summary:        Athanor OS athanor-nix-support
License:        MIT
URL:            https://github.com/hr-mes/athanor-forge
BuildArch:      noarch

# The Fedora Nix packages provide the binary, the store, the daemon and its systemd
# units. This package no longer reinvents any of that; it adds only what makes Nix work
# on an ostree system: the /nix bind mount from the writable /var/nix. The `nix` package
# is NOT required here: this package is installed in tier 0, long before the upstream
# packages, so a Requires would be unsatisfiable at that point. nix is installed with
# the other upstream packages (it is in upstream_core), and this package's mount unit
# waits for it at boot, ordered Before=nix-daemon, not at build time.

%description
Provides athanor-nix-support for Athanor OS: the /nix store bind mount that lets the
Fedora Nix packages work on the read-only ostree root, with the store living in the
writable, encrypted /var.

%prep
# Nothing to prep

%build
# Nothing to build

%install
mkdir -p %{buildroot}/usr/lib/tmpfiles.d
mkdir -p %{buildroot}/usr/lib/systemd/system

cp -a %{_sourcedir}/usr/lib/tmpfiles.d/* %{buildroot}/usr/lib/tmpfiles.d/
cp -a %{_sourcedir}/usr/lib/systemd/system/* %{buildroot}/usr/lib/systemd/system/

%files
/usr/lib/tmpfiles.d/10-athanor-nix.conf
/usr/lib/systemd/system/nix.mount

%changelog
* Fri Sep 12 2026 Athanor Forge <forge@athanor.os> - 1.0.0-3
- Make Nix actually work. The package used to hand-write a nix-daemon.service and
  .socket and create directories under /var/nix, but never installed Nix itself: the
  daemon was inactive, /nix did not exist and there was no nix binary. Require the
  Fedora `nix` package (nix-core, nix-daemon, nix-system, nix-filesystem), which brings
  the binary, the store layout, /etc/nix/nix.conf with flakes already enabled, and the
  daemon's own systemd units. Drop the duplicated hand-made units. Add nix.mount, which
  bind-mounts /nix from /var/nix so the store lives on the writable, encrypted volume
  while every Nix tool sees a native /nix -- the bootc approach, not a symlink. The
  tmpfiles now only creates the /var/nix backing directory.
* Wed Jul 01 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Initial Bedrock encapsulation with tmpfiles.d

%global debug_package %{nil}
%global crate_dir forge/specs/%{name}/%{name}-%{version}
Name:           athanor-recovery
Version:        1.0.0
Release:        4%{?dist}
Summary:        Athanor OS Pre-Boot GUI Recovery Kiosk & Rollback Manager

License:        MIT


BuildRequires:  rust cargo gcc gcc-c++ gtk4-devel glib2-devel pkgconf-pkg-config
Requires:       gtk4 glib2 cosmic-comp rpm-ostree systemd

%description
Pre-Boot GUI Wayland Kiosk recovery environment for Athanor OS (`athanor-recovery-ui`).
Provides 1-click OSTree/bootc visual rollback and automatic failover when `greetd` or the graphical session crashes.

%prep
# Built in place from the workspace checkout: nothing to unpack.

%build
%set_build_flags
# cargo generate-lockfile // FORBIDDEN BY RULE 4 (Offline Build)
cargo build --release --locked -p %{name}

%install
install -D -m 0755 target/release/athanor-recovery-ui %{buildroot}/usr/bin/athanor-recovery-ui

# systemd units and the greetd drop-in, from the crate directory.
install -D -m 0644 %{crate_dir}/systemd/athanor-recovery.service %{buildroot}/usr/lib/systemd/system/athanor-recovery.service
install -D -m 0644 %{crate_dir}/systemd/athanor-recovery.target %{buildroot}/usr/lib/systemd/system/athanor-recovery.target
install -D -m 0644 %{crate_dir}/systemd/greetd-recovery-fallback.conf %{buildroot}/usr/lib/systemd/system/greetd.service.d/recovery-fallback.conf

%files
/usr/bin/athanor-recovery-ui
/usr/lib/systemd/system/athanor-recovery.service
/usr/lib/systemd/system/athanor-recovery.target
%dir /usr/lib/systemd/system/greetd.service.d
/usr/lib/systemd/system/greetd.service.d/recovery-fallback.conf

%changelog
* Thu Sep 10 2026 Athanor Forge <forge@athanor.os> - recovery on cosmic-comp
- Run the pre-boot recovery kiosk on cosmic-comp instead of cage, the same single-client
  way the greeter and the session do. cage is no longer needed anywhere, so it leaves the
  image entirely; one compositor across greeter, session and recovery.
* Sun Sep 06 2026 Athanor Forge <forge@athanor.os> - 1.0.0-3
- Build only this crate from the workspace; install the systemd units and the
  greetd drop-in from the crate directory instead of empty placeholder files

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Initial release of athanor-recovery Pre-Boot GUI Wayland Kiosk (`cage` + `athanor-recovery-ui`)
- Automatic isolation to athanor-recovery.target when greetd fails StartLimitBurst=3 times
- Visual 1-click rollback to Bedrock Stable Commit (`8aa3fd4`) and previous stable OSTree deployments

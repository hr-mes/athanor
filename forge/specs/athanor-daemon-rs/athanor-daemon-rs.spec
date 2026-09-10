%global debug_package %{nil}
# Il crate vive nel workspace: la spec compila il checkout in place, non un tarball.
%global crate_dir forge/specs/%{name}/%{name}-%{version}
Name:           athanor-daemon-rs
Version:        0.2.1
Release:        4%{?dist}
Summary:        Athanor OS Native D-Bus Bedrock, ACID Settings & Multimedia Portal Daemon

License:        MIT

BuildRequires:  rust cargo gcc gcc-c++ pkgconf-pkg-config systemd-rpm-macros
Requires: pipewire wireplumber
Requires:       dconf athanor-matugen speech-dispatcher psmisc wlsunset

%description
Pure Rust native D-Bus IPC service for Athanor OS audio, system bedrock management, ACID settings database, and XDG Desktop Portal backend (Settings, ScreenCast, RemoteDesktop).

%prep

%build
%set_build_flags
# cargo generate-lockfile // FORBIDDEN BY RULE 4 (Offline Build)
cargo build --release --locked -p %{name}

%install
mkdir -p %{buildroot}/usr/bin
install -m 0755 target/release/athanor-daemon-rs %{buildroot}/usr/bin/athanor-daemon-rs

mkdir -p %{buildroot}%{_datadir}/dbus-1/services
install -m 0644 %{crate_dir}/org.athanor.Settings.service %{buildroot}%{_datadir}/dbus-1/services/org.athanor.Settings.service

# Polkit actions. Senza questo file le cinque azioni applicate dal daemon non
# sono registrate e CheckAuthorization nega sempre: niente rete, niente
# Bluetooth, niente live patch. Vedi ANALISI_2026-09-02.md 2.1.
install -D -m 0644 %{crate_dir}/os.athanor.daemon.policy %{buildroot}%{_datadir}/polkit-1/actions/os.athanor.daemon.policy

mkdir -p %{buildroot}/usr/lib/systemd/system
install -m 0644 %{crate_dir}/athanor-daemon.service %{buildroot}/usr/lib/systemd/system/athanor-daemon.service

%post
%systemd_post athanor-daemon.service

%preun
%systemd_preun athanor-daemon.service

%postun
%systemd_postun_with_restart athanor-daemon.service

%files
/usr/bin/athanor-daemon-rs
%{_datadir}/dbus-1/services/org.athanor.Settings.service
/usr/lib/systemd/system/athanor-daemon.service
%{_datadir}/polkit-1/actions/os.athanor.daemon.policy

%changelog
* Thu Sep 10 2026 Athanor Forge <forge@athanor.os> - drop niri dependency
- Drop the niri runtime dependency. The QoS window-focus observer and the screencast
  output query still speak the niri IPC socket, and both already degrade when it is absent
  (the observer logs and returns, the query falls back to a default output), so nothing
  crashes without niri; the cosmic backend replaces the socket in a later step.
* Thu Sep 03 2026 Athanor Forge <forge@athanor.os> - 0.2.1-3
- Compila il crate dal workspace in place (rpmbuild --build-in-place) invece di
  un tarball mai tracciato in git; file di dati riferiti tramite %%{crate_dir}
- Un solo athanor-daemon.service, quello del crate

* Fri Jul 17 2026 Athanor Forge <forge@athanor.os> - 0.2.1-1
- Remove portal configuration files (migrated to dedicated xdg-desktop-portal-athanor package)

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 0.2.0-3
- Implemented native XDG Desktop Portal ScreenCast and RemoteDesktop backends (org.freedesktop.impl.portal.ScreenCast & RemoteDesktop)
- Added Niri output discovery via UNIX socket ($NIRI_SOCKET) and PipeWire stream negotiation

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 0.2.0-2
- Added ACID JSON Settings engine (org.athanor.Settings) and XDG Desktop Portal backend (org.freedesktop.impl.portal.Settings)
- Installed portal configuration files and D-Bus service activation units

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 0.2.0-1
- Migrated from CLI subprocess wrappers (nmcli/bluetoothctl) to native zbus 5.17.0 D-Bus proxies
- Modularized source into network.rs, bluetooth.rs, and bedrock.rs

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 0.2.0-1
- Initial release of athanor-daemon-rs package

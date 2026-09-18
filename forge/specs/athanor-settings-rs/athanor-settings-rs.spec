%global debug_package %{nil}
# Il crate vive nel workspace: la spec compila il checkout in place, non un tarball.
%global crate_dir forge/specs/%{name}/%{name}-%{version}
Name:           athanor-settings-rs
Version:        1.0.0
Release:        12%{?dist}
Summary:        Pure Rust native System Settings for Athanor OS

License:        GPLv3+
URL:            https://github.com/hr-mes/athanor-forge

BuildRequires:  rust cargo
BuildRequires:  gtk4-devel

Requires: power-profiles-daemon
Requires:       ostree

%description
Athanor Settings is the native control panel for Athanor OS, written in pure Rust with GTK4.

%prep

%build
%set_build_flags
# cargo generate-lockfile // FORBIDDEN BY RULE 4 (Offline Build)
cargo build --release --locked -p %{name}

%install
rm -rf $RPM_BUILD_ROOT
install -d $RPM_BUILD_ROOT//usr/bin
install -m 0755 target/release/%{name} $RPM_BUILD_ROOT//usr/bin/%{name}
install -d $RPM_BUILD_ROOT/%{_datadir}/applications
install -m 0644 %{crate_dir}/os.athanor.Settings.desktop $RPM_BUILD_ROOT/%{_datadir}/applications/os.athanor.Settings.desktop

%files
/usr/bin/%{name}
%{_datadir}/applications/os.athanor.Settings.desktop

%changelog
* Fri Sep 18 2026 Athanor Forge <forge@athanor.os> - 1.0.0-12
- Drop Requires: mako. It was the only thing in the tree that pulled a second notification
  daemon into the image, and mako ships
  /usr/share/dbus-1/services/fr.emersion.mako.service: the one D-Bus activation file in
  the image that claims org.freedesktop.Notifications, so any client calling that name
  before cosmic-notifications owns it would have started mako instead, and the session's
  own daemon would then have failed to take its name. This package left the image in
  1.0.0-11 and is no longer built; the line is removed so that reviving it cannot bring
  the second daemon back. A desktop needs a notification daemon, not this one: the session
  starts cosmic-notifications.
* Thu Sep 03 2026 Athanor Forge <forge@athanor.os> - 1.0.0-11
- Compila il crate dal workspace in place (rpmbuild --build-in-place) invece di
  un tarball mai tracciato in git; file di dati riferiti tramite %%{crate_dir}

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-8
- Implemented Enterprise Wi-Fi (802.1x EAP-TLS/PEAP) and Native VPN tunnel management (WireGuard/OpenVPN) in network page
- Added Flatpak Sandbox Permissions Manager (`--socket=wayland/pulseaudio`, `--share=network`, `--filesystem=home`) in privacy page
- Added Focus Modes (Do Not Disturb, Gaming Mode, Work Session, Reading) and Niri automation rules in focus page

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-7
- Implement Phase 4c: native KDL updater without subprocesses, VRR/HDR switches, display spatial layout preview, and trackpad gestures
- Eliminate CLI subprocess calls (wpctl, nmcli, uname, whoami, niri) and integrate native Niri UNIX socket client (`niri_client.rs`), D-Bus `os.athanor.Bedrock` proxy, and sysfs/procfs readers.

* Mon Jul 13 2026 Athanor Forge <forge@athanor.os> - 1.0.0-3
- Dynamic Matugen theme generation & wallpaper integration

* Mon Jul 13 2026 Athanor Forge <forge@athanor.os> - 1.0.0-2
- Complete audio sync, desktop entry and bump spec release to 2


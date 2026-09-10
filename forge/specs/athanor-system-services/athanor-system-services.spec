%global debug_package %{nil}
Name:           athanor-system-services
Version:        1.0.1
Release:        8%{?dist}
Summary:        Athanor OS athanor-system-services
License:        MIT
URL:            https://github.com/hr-mes/athanor-forge
BuildArch:      noarch
Requires:       systemd
Requires:       athanor-shell-rs
Requires:       wayland-utils

%description
Provides core systemd user targets, desktop panel lifecycle services, and skeleton synchronization for Athanor OS.

%prep
# Nothing to prep

%build
# Nothing to build

%install
mkdir -p %{buildroot}/usr/share/athanor-system-services
mkdir -p %{buildroot}/usr/lib/systemd/user
cp -a %{_sourcedir}/usr/lib/systemd/user/* %{buildroot}/usr/lib/systemd/user/

%files
%dir /usr/share/athanor-system-services
/usr/lib/systemd/user/athanor-session.target
/usr/lib/systemd/user/athanor-desktop.service
/usr/lib/systemd/user/athanor-skel-sync.service
/usr/lib/systemd/user/athanor-shell.service
/usr/lib/systemd/user/athanor-dock.service

%changelog
* Thu Sep 10 2026 Athanor Forge <forge@athanor.os> - 1.0.1-8
- The shell and the dock allow mincore on top of @system-service: the GL stack calls
  it while the first frame is drawn, and the filter killed every start of both units
  (acceptance run 34515239432, SECCOMP syscall=27). Both units declare
  ConfigurationDirectory= and StateDirectory= athanor, the writable places for
  widgets.json and the notification history under ProtectHome=read-only.

* Thu Sep 10 2026 Athanor Forge <forge@athanor.os> - 1.0.1-7
- The session target is athanor-session.target, for cosmic-comp: it pulls the shell, the
  dock and the skeleton sync itself instead of relying on a user preset, and
  athanor-desktop, the compositor's client, starts and waits on it. niri-session.target,
  the preset (which also enabled an athanor-wallpaper.service that never existed) and the
  athanor-ags.service alias are gone; the %install no longer hides a missing source
  directory behind || true.
- Add athanor-desktop.service, a oneshot gate the target requires and the shell and dock
  order after: it publishes the display to the user manager and blocks on a Wayland
  round-trip (wayland-info), so no graphical unit starts before cosmic-comp can serve a
  surface. Without it the units raced the compositor and crash-looped (Failed to open
  display, then SIGSYS on GTK4's error path under the session sandbox).
* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.1-6
- Add athanor-dock.service as dedicated user systemd service for interactive Glassmorphic Dock

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.1-5
- Rename athanor-ags.service to athanor-shell.service with backward compatibility alias symlink

* Sat Jul 11 2026 Athanor Forge <forge@athanor.os> - 1.0.1-4
- Switch athanor-ags.service to run pure Rust athanor-shell-rs native binary instead of GJS/JS

* Tue Jul 07 2026 Athanor Forge <forge@athanor.os> - 1.0.1-3
- Refactored athanor-skel-sync to copy all missing dotfiles (Niri, Matugen, etc) securely without overwriting

* Tue Jul 07 2026 Athanor Forge <forge@athanor.os> - 1.0.1-2
- Fix Wayland socket race condition by changing After to graphical-session.target for ags and wallpaper

* Tue Jul 07 2026 Athanor Forge <forge@athanor.os> - 1.0.1-1
- Implement systemd user target niri-session.target
- Implement Astal AGS desktop panel lifecycle service
- Implement skeleton sync for seamless user upgrade migration

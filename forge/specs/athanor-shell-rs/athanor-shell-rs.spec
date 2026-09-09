%global debug_package %{nil}
# Il crate vive nel workspace: la spec compila il checkout in place, non un tarball.
Name:           athanor-shell-rs
Version:        1.0.0
Release:        24%{?dist}
Summary:        Athanor OS Native Rust GTK4 Shell

License:        MIT

BuildRequires:  rust cargo gcc gcc-c++ gtk4-devel glib2-devel pkgconf-pkg-config gtk4-layer-shell-devel clang-devel speech-dispatcher-devel upower-devel
Requires: gtk4 gtk4-layer-shell glib2 cage upower xdg-utils plocate foot wl-clipboard
Requires:       cliphist niri

%description
Pure Rust native shell for Athanor OS, replacing AGS/GJS.

%prep

%build
%set_build_flags
# cargo generate-lockfile // FORBIDDEN BY RULE 4 (Offline Build)
cargo build --release --locked -p %{name}

%install
mkdir -p %{buildroot}/usr/bin
install -m 0755 target/release/athanor-shell-rs %{buildroot}/usr/bin/athanor-shell-rs

%files
/usr/bin/athanor-shell-rs

%changelog
* Wed Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-24
- Stop aborting when no eBPF ring-buffer descriptor is provided. Nothing in the system
  sets ATHANOR_EBPF_RINGBUF_FD, so start_ebpf_dbus_listener panicked at every start of
  every shell mode once D-Bus was connected (acceptance run 34391930923). The push path
  stays off and the shell keeps to its D-Bus proxies; nothing is simulated.
* Wed Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-23
- Create a Tokio runtime in main() and enter it for the life of the process. The IPC
  actors call tokio::spawn from GLib's main loop with no runtime in existence, so the
  shell aborted on "there is no reactor running" at every start, in the greeter as in
  the session (acceptance run 34384585109).
* Thu Sep 03 2026 Athanor Forge <forge@athanor.os> - 1.0.0-22
- Compila il crate dal workspace in place (rpmbuild --build-in-place) invece di
  un tarball mai tracciato in git
- Release numerica, allineata al changelog

* Wed Jul 22 2026 Athanor Forge <forge@athanor.os> - 1.0.0-21
- Added upower and upower-devel dependencies for Battery Monitor D-Bus integration.

* Sun Jul 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-20
- Added Generative UI Engine foundation, Spotlight Premium (Glassmorphism + Web Search), and native interactive Desktop Widgets (Clock, CPU/RAM).

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-19
- Implemented automatic Keyring unlock during biometric / FIDO2 login via TPM 2.0 sealed secret (`systemd-creds decrypt`) or password fallback (`greeter.rs`)
- Implemented Inline Replies (`has_inline_reply`) with quick text field inside notification toast and center (`notifications.rs`)
- Added Master Do Not Disturb (`DND_ACTIVE`) atomic toggle across notification center and toasts (`core/mod.rs`)

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-18
- Implement Phase 4: interactive multi-step PAM Lockscreen (--lock), Notification Center history sidebar, and topbar bell icon
- Implement Phase 3 Visual Polish & Physics: Mica/Frosted Glass blur namespaces, SpringAnimator kinematics solver, and Spotlight FTS5 deeplinks

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-16
- Eradicate Niri CLI subprocess calls and implement native high-speed UNIX socket memory client (niri_client.rs)

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-15
- Implement multi-monitor independent dock instances per gdk::Monitor with intelligent Dodge/Overlap auto-hide

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-14
- Fix dock workspace tracking across monitors (prioritize focused workspace ID) and fix auto-hide hover tracking

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-13
- Separate single-instance dock process (`--dock`) with D-Bus toggle and active workspace intelli-hide

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-12
- Fix GTK4 Wayland size.width > 0 runtime failure by sizing trigger_win child box and container

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-11
- Implement native GTK4/Layer-Shell interactive Dock with Niri event-stream IPC and autohide trigger

* Tue Jul 14 2026 Athanor Forge <forge@athanor.os> - 1.0.0-10
- Prioritize packaged /usr/bin/athanor-session in greeter IPC StartSession dispatch

* Tue Jul 14 2026 Athanor Forge <forge@athanor.os> - 1.0.0-9
- Add cage dependency for native Wayland greeter kiosk mode (--greeter)

* Mon Jul 13 2026 Athanor Forge <forge@athanor.os> - 1.0.0-8
- Integrate cage Wayland kiosk execution and Big Tech Glassmorphism Greeter upgrade

* Mon Jul 13 2026 Athanor Forge <forge@athanor.os> - 1.0.0-7
- Redesign greeter login UI to BigTech macOS Lock Screen & Glassmorphism style with live clock and power actions

* Mon Jul 13 2026 Athanor Forge <forge@athanor.os> - 1.0.0-6
- Fix greeter PAM authentication username resolution and add premium GTK4 CSS design

* Mon Jul 13 2026 Athanor Forge <forge@athanor.os> - 1.0.0-5
- Add Control Center header Settings button and quick setting tile deeplinks (--page <id>)

* Mon Jul 13 2026 Athanor Forge <forge@athanor.os> - 1.0.0-4
- Implement single-instance command dispatching, Powermenu modal (--powermenu), and Clipboard Manager modal (--clipboard).

* Sat Jul 11 2026 Athanor Forge <forge@athanor.os> - 1.0.0-2
- Implement Full Rust GTK4 Layer Shell Top Bar with 3-zone layout and native styling

* Fri Jul 10 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Initial Rust Shell encapsulation

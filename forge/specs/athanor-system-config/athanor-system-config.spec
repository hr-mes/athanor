%global debug_package %{nil}
%global __requires_exclude ^kernel-rt$
Name:           athanor-system-config
Version:        1.0.0
Release:        %{?autorelease}%{!?autorelease:27.fc43}
Summary:        Athanor OS athanor-system-config
License:        MIT
URL:            https://github.com/hr-mes/athanor-forge
BuildArch:      noarch

Requires: cosmic-comp greetd greenboot systemd-ukify nodejs
# Core UI andDaemons
Requires: athanor-shell-rs athanor-settings-rs athanor-daemon-rs
Requires: athanor-store-rs xdg-desktop-portal-athanor
# The eBPF monitor and the cloud agent are integrations the configuration is ready
# for, not prerequisites of the configuration itself: weak dependencies.
Recommends: athanor-sysmon-ebpf athanor-cloud-rs
Requires: usbguard bolt

Requires:       bcachefs-tools
%description
Provides athanor-system-config for Athanor OS.

%prep
# Nothing to prep

%build
# Nothing to build

%install
mkdir -p %{buildroot}
cp -a %{_sourcedir}/usr %{buildroot}/ 2>/dev/null || true
cp -a %{_sourcedir}/etc %{buildroot}/ 2>/dev/null || true

mkdir -p %{buildroot}/usr/share/athanor-system-config
mv %{buildroot}/etc/usbguard/usbguard-daemon.conf %{buildroot}/usr/share/athanor-system-config/usbguard-daemon.conf
mv %{buildroot}/etc/yum.repos.d/athanor-forge.repo %{buildroot}/usr/share/athanor-system-config/athanor-forge.repo

%post
# Configurations are now managed declaratively via tmpfiles.d (10-athanor-greetd.conf)
#
# The greeter needs the devices it draws and listens on. Fedora creates the greetd user
# with no supplementary groups. That was not what kept the compositor from starting --
# logind grants the active session the card through an ACL, and runs 34293193136 and
# 34365841089 showed cage past libseat with the membership making no difference -- but
# a session that owns a screen belongs in video and tty either way.
#
# On this image video and tty live in /usr/lib/group, the read-only half of the split
# that ostree systems use, and every tool that edits group membership works on
# /etc/group alone. systemd-sysusers given an `m greetd video` line answers "Group video
# already exists" and makes no membership; gpasswd is blunter about it -- "group 'video'
# does not exist in /etc/group" -- and usermod fails silently. So the group is copied
# into /etc/group first, where nss then merges it with the /usr/lib entry, and the
# membership is added there.
for group in video tty; do
    if ! grep -q "^${group}:" /etc/group && getent group "$group" > /dev/null 2>&1; then
        getent group "$group" >> /etc/group
    fi
    gpasswd -a greetd "$group" > /dev/null 2>&1 || :
done
mkdir -p /etc/usbguard
mkdir -p /etc/yum.repos.d

%files
%dir /usr/share/athanor-system-config
%attr(0755,root,root) /usr/bin/athanor-session
%attr(0755,root,root) /usr/bin/athanor-desktop
%attr(0755,root,root) /usr/bin/athanor-greeter-session
%attr(0755,root,root) /usr/bin/athanor-usbguard-hook
%attr(0755,root,root) /usr/bin/athanor-uki-enroll
%attr(0755,root,root) /usr/libexec/athanor-snapshot-trigger.sh
%dir /usr/lib/systemd/system/greetd.service.d
/usr/lib/systemd/system/greetd.service.d/10-athanor-wantedby.conf
/usr/lib/systemd/system/athanor-timewarp.service
/usr/lib/systemd/system/athanor-timewarp.timer
/usr/lib/systemd/system-preset/99-Athanor.preset
/usr/lib/tmpfiles.d/10-athanor-greetd.conf
/usr/share/athanor-system-config/greetd.toml
/usr/share/athanor-system-config/usbguard-daemon.conf
/usr/share/athanor-system-config/athanor-forge.repo
%attr(0755,root,root) /etc/greenboot/check/required.d/10-greetd-running.sh
%config(noreplace) /etc/security/limits.d/99-athanor-realtime.conf

%changelog
* Thu Sep 10 2026 Athanor Forge <forge@athanor.os> - 1.0.0-27
- Drop the cage and niri runtime dependencies. Greeter and session are on cosmic-comp;
  neither cage nor niri is on the desktop boot path any more. cage stays out of this
  package but remains a dependency of athanor-recovery, whose pre-boot GUI is a cage kiosk.
* Thu Sep 10 2026 Athanor Forge <forge@athanor.os> - 1.0.0-26
- The session runs on cosmic-comp. athanor-session clears the user manager of what the
  previous session left, sets the desktop name and execs cosmic-comp with
  /usr/bin/athanor-desktop as its client; athanor-desktop publishes the display to the
  user manager and holds the session open by waiting on athanor-session.target, so
  stopping the target is the logout. niri-session is no longer started. The USB policy
  hook the session calls, /usr/bin/athanor-usbguard-hook, is finally in %files: it was
  never packaged, and the old session's "|| true" hid the missing file. The greetd.toml
  comment about choosing a renderer, left over from the cage probe, is corrected.
* Wed Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-25
- Draw the greeter on cosmic-comp instead of cage. cosmic-comp takes a client program
  as its argument the way cage does, hands it its own WAYLAND_DISPLAY and exits when the
  client exits, which is all greetd needs; unlike cage it implements wlr-layer-shell, so
  the greeter is a layer surface again and no longer a decorated toplevel. The GLES2
  probe goes with cage: cosmic-comp has no switch like WLR_RENDERER=pixman to flip, so a device
  it cannot render on is a failure to read in the journal, not one to route around.
  First step of the move of the whole session to cosmic-comp; cage stays in the image
  until the session follows.
* Wed Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-24
- Drop the greeter PAM stack override and greetd-seat.env added in -21. greetd 0.10.3
  already hands pam_systemd XDG_SEAT=seat0 and XDG_VTNR before it opens the session
  (session/worker.rs), so the two pam_env lines set what was already set. Fedora's own
  greetd-greeter file, pam_systemd included, is the one in force again.
* Wed Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-23
- Start the greeter through /usr/bin/athanor-greeter-session, which probes for a working
  GLES2 renderer with a headless cage before starting the compositor and forces pixman
  when there is none. wlroots falls back to pixman by itself only on a device with no
  render node, so a GPU with a render node and no working driver -- the acceptance VM's
  virtio-gpu without virgl, run 34365841089 -- left the greeter with no renderer at all.
* Tue Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-22
- Run the greeter session under systemd-cat, so the compositor's own errors reach the
  journal instead of being lost. Until now a failed greeter left only greetd's
  "greeter exited without creating a session", which names no cause.
* Tue Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-21
- Give the greeter PAM stack XDG_SEAT and XDG_VTNR. greetd sets neither, so pam_systemd
  registered the session with no seat and libseat could not open one for the compositor.
  The video and tty groups added in -20 were not the cause and are kept: a session that
  owns a screen needs them either way.
* Tue Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-20
- Add greetd to the video and tty groups from %post. The sysusers.d
  attempt in -19 had no effect: video and tty live in /usr/lib/group on this image and
  systemd-sysusers only writes /etc/group, so an m line finds the group already
  existing and makes no membership.
* Tue Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-19
- Put the greetd user in the video and tty groups. Fedora creates it with no
  supplementary groups, so its logind session had no seat, libseat could not open one
  and cage never started a compositor.
* Mon Sep 08 2026 Athanor Forge <forge@athanor.os> - 1.0.0-18
- Pull greetd into graphical.target with a drop-in. Fedora's unit declares only
  Alias=display-manager.service and no WantedBy=, so the preset created the alias
  and left default.target.wants empty: the installed system booted to a text getty
  on tty1 and the greeter never started.
* Mon Sep 08 2026 Athanor Forge <forge@athanor.os> - 1.0.0-17
- Run the greeter as greetd, the user that exists: the greeter configuration and
  the tmpfiles rules both named "greeter", which no package creates, so greetd
  refused to start with "configured default session user 'greeter' not found"
  and systemd-tmpfiles could not resolve the owner of its state directories

* Sun Sep 07 2026 Athanor Forge <forge@athanor.os> - 1.0.0-16
- Recommend athanor-sysmon-ebpf and athanor-cloud-rs instead of requiring them:
  the v0 image ships neither

* Fri Jul 17 2026 Athanor Forge <forge@athanor.os> - 1.0.0-15
- Fix DNF file conflicts: removed %dir ownerships for /etc/yum.repos.d and /etc/security/limits.d
- Fix usbguard-daemon.conf RPM file conflict by copying it in %post instead of packaging it in /etc

* Thu Jul 16 2026 Athanor Forge <forge@athanor.os> - 1.0.0-14
- Enforce PREEMPT_RT scheduling limits for sub-5ms latency and add kernel-rt requirement

* Thu Jul 16 2026 Athanor Forge <forge@athanor.os> - 1.0.0-12
- Add systemd-ukify dependency and athanor-uki-enroll script for UKI generation and TPM2 LUKS enrollment

* Thu Jul 16 2026 Athanor Forge <forge@athanor.os> - 1.0.0-11
- Add /etc/yum.repos.d/athanor-forge.repo for live DNF rolling release updates

* Tue Jul 14 2026 Athanor Forge <forge@athanor.os> - 1.0.0-10
- Encapsulate /usr/bin/athanor-session native script and add %post symlink for /etc/greetd/config.toml

* Tue Jul 14 2026 Athanor Forge <forge@athanor.os> - 1.0.0-9
- Add Requires: cage greetd athanor-shell-rs and remove obsolete niri-greeter.kdl and greeter-bundle.js

* Mon Jul 13 2026 Athanor Forge <forge@athanor.os> - 1.0.0-8
- Remove direct /etc/greetd/config.toml to eliminate RPM transaction file conflict with greetd package (using tmpfiles L+ symlink override)

* Mon Jul 13 2026 Athanor Forge <forge@athanor.os> - 1.0.0-7
- Configure default_session command for cage Wayland kiosk executing athanor-shell-rs --greeter

* Sat Jul 11 2026 Athanor Forge <forge@athanor.os> - 1.0.0-6
- Fix %install source path expansion to copy directly from %{_sourcedir}/usr.

* Sat Jul 11 2026 Athanor Forge <forge@athanor.os> - 1.0.0-5
- Package updated greeter-bundle.js and shadow tmpfiles overrides for instant greeter transitions.

* Wed Jul 01 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Initial Bedrock encapsulation

%global debug_package %{nil}
%global crate_dir forge/specs/%{name}/%{name}-%{version}
Name:           athanor-backup
Version:        1.0.0
Release:        4%{?dist}
Summary:        Athanor OS Time Machine & Bcachefs Home Snapshot Manager

License:        MIT


BuildRequires:  rust cargo gcc gcc-c++ gtk4-devel glib2-devel pkgconf-pkg-config
Requires:       gtk4 glib2 bcachefs-tools systemd

%description
Instant zero-overhead Bcachefs Copy-on-Write (CoW) Home snapshot manager: the
system D-Bus daemon (`athanor-backup-daemon`, org.athanor.Backup1) with its
polkit-guarded create/list/delete/restore calls and the automatic hourly timer
(`athanor-backup-hourly.timer`). The Time Machine GUI is not part of this
release.

%prep
# Built in place from the workspace checkout: nothing to unpack.

%build
%set_build_flags
# cargo generate-lockfile // FORBIDDEN BY RULE 4 (Offline Build)
cargo build --release --locked -p %{name}

%install
install -D -m 0755 target/release/athanor-backup-daemon %{buildroot}/usr/bin/athanor-backup-daemon

# systemd units and the D-Bus system policy, from the crate directory.
install -D -m 0644 %{crate_dir}/systemd/athanor-backup.service %{buildroot}/usr/lib/systemd/system/athanor-backup.service
install -D -m 0644 %{crate_dir}/systemd/athanor-backup-hourly.timer %{buildroot}/usr/lib/systemd/system/athanor-backup-hourly.timer
install -D -m 0644 %{crate_dir}/systemd/athanor-backup-hourly.service %{buildroot}/usr/lib/systemd/system/athanor-backup-hourly.service
install -D -m 0644 %{crate_dir}/systemd/org.athanor.Backup1.conf %{buildroot}/usr/share/dbus-1/system.d/org.athanor.Backup1.conf

%files
/usr/bin/athanor-backup-daemon
/usr/lib/systemd/system/athanor-backup.service
/usr/lib/systemd/system/athanor-backup-hourly.timer
/usr/lib/systemd/system/athanor-backup-hourly.service
/usr/share/dbus-1/system.d/org.athanor.Backup1.conf

%changelog
* Fri Sep 11 2026 Athanor Forge <forge@athanor.os> - 1.0.0-4
- The hourly snapshot trigger calls the daemon through busctl: dbus-send is not part
  of the image and the unit failed at every timer tick (status=203/EXEC).
* Sun Sep 06 2026 Athanor Forge <forge@athanor.os> - 1.0.0-3
- Build only this crate from the workspace; install the systemd units and the
  D-Bus policy from the crate directory instead of empty placeholder files
- Drop the athanor-backup-ui binary, which the crate never defined

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Initial release of athanor-backup Bcachefs CoW snapshot daemon and Time Machine GUI
- Automatic hourly snapshot creation via systemd user timer
- Instant single-click rollback and snapshot creation

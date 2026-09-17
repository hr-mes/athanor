Name:           athanor-scudo
Version:        1.0.0
Release:        4%{?dist}
Summary:        Athanor OS Scudo Hardened Allocator Configuration

License:        GPL-3.0-or-later
URL:            https://github.com/hr-mes/athanor-forge

BuildRequires:  systemd-rpm-macros
Requires:       compiler-rt

%description
Sets up Scudo standalone allocator via LD_PRELOAD globally for Athanor OS.

%prep
# No prep

%build
# No build

%install
mkdir -p %{buildroot}/etc
mkdir -p %{buildroot}%{_prefix}/lib/environment.d

# Global LD_PRELOAD injection removed to preserve system stability and immutability

# Scudo Options
cat <<EOF > %{buildroot}%{_prefix}/lib/environment.d/10-scudo.conf
SCUDO_OPTIONS="ZeroContents=1:PatternFillRet=1:DeallocationTypeMismatch=1:DeleteSizeMismatch=1"
EOF

%files
%{_prefix}/lib/environment.d/10-scudo.conf

%changelog
* Thu Sep 17 2026 Athanor Forge <forge@athanor.os> - 1.0.0-4
- Remove tmpfiles.d/10-scudo.conf. Its L+ rule tried to create /usr/lib64/libscudo.so
  at boot inside the read-only /usr, pointing at a clang 19 path that compiler-rt does
  not install, and nothing loads libscudo by that name: no LD_PRELOAD is set and the
  Gatekeeper is built without its scudo_ffi feature.

* Thu Sep 17 2026 Athanor Forge <forge@athanor.os> - 1.0.0-3
- Remove the greetd.service drop-in. A unit's sandboxing is inherited by every process
  the unit starts, so its seccomp filters, bounding set and read-only /proc/sys and
  cgroups reached cosmic-comp, Xwayland and the session launched from it. The greeter
  UI is now confined by its launch wrapper, athanor-greeter-client in
  athanor-system-config.

* Tue Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-2
- Drop MemoryDenyWriteExecute from the greetd override. A Wayland compositor compiles
  shaders at run time, so W^X killed athanor-shell-rs on every start and greetd restarted
  it in a loop. Every other restriction is kept.
- Remove the athanor-llm.service drop-in. No unit by that name exists anywhere in the
  image or the repository; the AI daemon is athanor-ai-daemon.service, and its own unit
  already declares this hardening, including MemoryDenyWriteExecute.

* Mon Aug 03 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Initial release

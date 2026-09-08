Name:           athanor-scudo
Version:        1.0.0
Release:        2%{?dist}
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
mkdir -p %{buildroot}/usr/lib/systemd/system/greetd.service.d

# Global LD_PRELOAD injection removed to preserve system stability and immutability

# Scudo Options
cat <<EOF > %{buildroot}%{_prefix}/lib/environment.d/10-scudo.conf
SCUDO_OPTIONS="ZeroContents=1:PatternFillRet=1:DeallocationTypeMismatch=1:DeleteSizeMismatch=1"
EOF

# Greetd override.
#
# MemoryDenyWriteExecute is deliberately absent. greetd runs the session compositor, and a
# Wayland stack compiles shaders at run time: Mesa and wlroots map a page, write machine
# code into it and then execute it, which is the transition that setting forbids. With it
# in place athanor-shell-rs died the moment greetd started it, and greetd restarted it in a
# loop -- acceptance run 34282184613:
#
#   athanor-shell-r[1206]: segfault at 7f62cc03d000 ip 00007f62cc03d000 error 15
#   Code: 00 00 00 00 ...
#
# An instruction pointer equal to the faulting address, with all-zero Code, is a jump into
# a page that may not be executed. The restriction is incompatible with graphics rather
# than merely awkward, which is why no distribution applies W^X to a display manager.
#
# Every other restriction stays: none of them touches how the compositor maps memory.
cat <<EOF > %{buildroot}/usr/lib/systemd/system/greetd.service.d/override.conf
[Service]
LockPersonality=true
RestrictSUIDSGID=true
RestrictRealtime=true
ProtectControlGroups=true
ProtectKernelLogs=true
ProtectKernelModules=true
ProtectKernelTunables=true
Environment="LD_PRELOAD="
EOF

# Declarative symlink configuration via tmpfiles.d
mkdir -p %{buildroot}%{_prefix}/lib/tmpfiles.d
cat <<EOF > %{buildroot}%{_prefix}/lib/tmpfiles.d/10-scudo.conf
L+ /usr/lib64/libscudo.so - - - - /usr/lib64/clang/19/lib/linux/libclang_rt.scudo_standalone.so
EOF


%files
%{_prefix}/lib/environment.d/10-scudo.conf
%{_prefix}/lib/tmpfiles.d/10-scudo.conf
/usr/lib/systemd/system/greetd.service.d/override.conf

%changelog
* Tue Sep 09 2026 Athanor Forge <forge@athanor.os> - 1.0.0-2
- Drop MemoryDenyWriteExecute from the greetd override. A Wayland compositor compiles
  shaders at run time, so W^X killed athanor-shell-rs on every start and greetd restarted
  it in a loop. Every other restriction is kept.
- Remove the athanor-llm.service drop-in. No unit by that name exists anywhere in the
  image or the repository; the AI daemon is athanor-ai-daemon.service, and its own unit
  already declares this hardening, including MemoryDenyWriteExecute.

* Mon Aug 03 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Initial release

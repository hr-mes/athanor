%global debug_package %{nil}
Name:           athanor-gatekeeper-rs
Version:        1.0.0
Release:        4%{?dist}
Summary:        Athanor OS Zero-Trust Gatekeeper (fanotify)

License:        GPLv3+
URL:            https://github.com/hr-mes/athanor-forge
Requires:       polkit bubblewrap


BuildRequires:  rust >= 1.83.0
BuildRequires:  cargo
BuildRequires:  systemd-rpm-macros

%description
Athanor OS Zero-Trust binary execution gatekeeper using fanotify.

%prep
# Stub prep

%build
%set_build_flags
# cargo generate-lockfile // FORBIDDEN BY RULE 4 (Offline Build)
cargo build --release -p %{name}

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}/usr/bin
install -m 0755 target/release/%{name} %{buildroot}/usr/bin/%{name}

# Polkit actions. Senza questo file nessun binario in quarantena puo' mai essere
# approvato: le quattro azioni os.athanor.gatekeeper.* non erano registrate.
# Vedi ANALISI_2026-09-02.md 2.1 e i commenti nel file .policy.
SRC_OS_ATHANOR_GATEKEEPER_POLICY=forge/specs/athanor-gatekeeper-rs/athanor-gatekeeper-rs-1.0.0/os.athanor.gatekeeper.policy
[ -f "$SRC_OS_ATHANOR_GATEKEEPER_POLICY" ] || SRC_OS_ATHANOR_GATEKEEPER_POLICY=os.athanor.gatekeeper.policy
install -D -m 0644 "$SRC_OS_ATHANOR_GATEKEEPER_POLICY" %{buildroot}%{_datadir}/polkit-1/actions/os.athanor.gatekeeper.policy

# Seccomp policy enforced on the crosvm VMM. It ships read-only under /usr so that no
# unprivileged user can supply it; the Gatekeeper refuses to launch crosvm otherwise.
SRC_CROSVM_POLICY=forge/specs/athanor-gatekeeper-rs/athanor-gatekeeper-rs-1.0.0/crosvm-strict.policy
[ -f "$SRC_CROSVM_POLICY" ] || SRC_CROSVM_POLICY=crosvm-strict.policy
install -D -m 0644 "$SRC_CROSVM_POLICY" %{buildroot}%{_datadir}/%{name}/crosvm/strict.policy

# systemd service
mkdir -p %{buildroot}/usr/lib/systemd/system
cat > %{buildroot}/usr/lib/systemd/system/%{name}.service <<EOF
[Unit]
Description=Athanor OS Zero-Trust Gatekeeper
After=network.target

[Service]
CPUWeight=150
CPUQuota=150%
MemoryHigh=192M
MemoryMax=256M

OOMScoreAdjust=-200
Type=simple
ExecStart=/usr/bin/%{name}
Restart=on-failure
RestartSec=5s
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=true
MemoryDenyWriteExecute=true
NoNewPrivileges=yes
AmbientCapabilities=CAP_SYS_ADMIN CAP_NET_ADMIN CAP_BPF CAP_SYS_PTRACE
CapabilityBoundingSet=CAP_SYS_ADMIN CAP_NET_ADMIN CAP_BPF CAP_SYS_PTRACE
SystemCallFilter=@system-service
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
EOF

%post
%systemd_post %{name}.service

%preun
%systemd_preun %{name}.service

%postun
%systemd_postun_with_restart %{name}.service

%files
/usr/bin/%{name}
/usr/lib/systemd/system/%{name}.service
%{_datadir}/polkit-1/actions/os.athanor.gatekeeper.policy
%{_datadir}/%{name}/

%changelog
* Thu Sep 17 2026 Athanor Forge <forge@athanor.os> - 1.0.0-4
- Report a launch as approved only when an isolation boundary is running: drop the
  unconfigured firecracker fallback, unshare the network in the bubblewrap
  compartment, and return an error to the D-Bus caller when no boundary starts
- Drop the signature check on quarantined files: it verified the file against a
  public key read from the file's own user xattrs, so it proved nothing

* Thu Sep 17 2026 Athanor Forge <forge@athanor.os> - 1.0.0-3
- Ship the crosvm seccomp policy read-only under /usr and refuse to launch when it is
  not root-owned or is writable by others; drop the runtime fallback to /tmp/crosvm

* Wed Jul 15 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Initial release


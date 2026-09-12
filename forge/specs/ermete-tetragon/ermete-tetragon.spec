Name:           ermete-tetragon
Version:        1.7.1
Release:        1%{?dist}
Summary:        Cilium Tetragon eBPF Runtime Security

License:        Apache-2.0
URL:            https://github.com/cilium/tetragon
Source0:        tetragon-v1.7.1-amd64.tar.gz

BuildRequires:  tar
Requires:       systemd

%description
Cilium Tetragon eBPF Runtime Security engine, packaged for Ermete OS.

%prep
%setup -q -c

%build
# Offline hermetic build using pre-fetched Source0 tarball

%install
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}%{_sharedstatedir}/tetragon
mkdir -p %{buildroot}/etc/tetragon/tetragon.tp.d
mkdir -p %{buildroot}/usr/lib/systemd/system

# Copy binaries
install -m 0755 tetragon-v%{version}-amd64/usr/local/bin/tetragon %{buildroot}/usr/bin/tetragon
install -m 0755 tetragon-v%{version}-amd64/usr/local/bin/tetra %{buildroot}/usr/bin/tetra

# Copy bpf bytecode
cp -r tetragon-v%{version}-amd64/usr/local/lib/tetragon/bpf %{buildroot}%{_sharedstatedir}/tetragon/

# Copy services and configs from SOURCES
install -m 0644 %{_sourcedir}/tetragon.service %{buildroot}/usr/lib/systemd/system/tetragon.service
install -m 0644 %{_sourcedir}/tetragon.yaml %{buildroot}/etc/tetragon/tetragon.yaml
install -m 0644 %{_sourcedir}/tetragon.tp.d/sys_execve.yaml %{buildroot}/etc/tetragon/tetragon.tp.d/sys_execve.yaml

%post
%systemd_post tetragon.service

%preun
%systemd_preun tetragon.service

%postun
%systemd_postun_with_restart tetragon.service

%files
/usr/bin/tetragon
/usr/bin/tetra
%{_sharedstatedir}/tetragon/bpf/
/usr/lib/systemd/system/tetragon.service
%config(noreplace) /etc/tetragon/tetragon.yaml
%config(noreplace) /etc/tetragon/tetragon.tp.d/sys_execve.yaml

%changelog
* Mon Aug 03 2026 Ermete Forge <forge@ermete.os> - 1.3.0-1
- Initial release for Ermete OS

%global debug_package %{nil}
Name:           athanor-kernel-profile
Version:        1.0.0
Release:        1%{?dist}
Summary:        Athanor kernel profile: effective settings per role combination and their checker

License:        MIT
URL:            https://github.com/hr-mes/athanor
BuildArch:      noarch
Requires:       python3 >= 3.11

%description
The effective kernel profile of every allowed role combination, generated from
profile.toml (docs/architecture/doc_kernel_profile.md), and athanor-profile-check, which
compares the running system with the profile of its role combination.

%prep
# Nothing to unpack: the installed files come from SOURCES.

%build
# Nothing to build: kernel_profile.py generates the profiles in the repository.

%install
install -D -m 0755 %{_sourcedir}/usr/bin/athanor-profile-check %{buildroot}%{_bindir}/athanor-profile-check
install -d %{buildroot}%{_datadir}/athanor/kernel-profile
install -m 0644 %{_sourcedir}/usr/share/athanor/kernel-profile/*.json %{buildroot}%{_datadir}/athanor/kernel-profile/

%files
%{_bindir}/athanor-profile-check
%dir %{_datadir}/athanor
%dir %{_datadir}/athanor/kernel-profile
%{_datadir}/athanor/kernel-profile/*.json

%changelog
* Mon Sep 14 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Block P1 of the kernel profile: manifest, generated profiles and checker

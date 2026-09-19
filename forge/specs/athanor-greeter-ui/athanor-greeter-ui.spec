%global debug_package %{nil}
Name:           athanor-greeter-ui
Version:        1.0.0
Release:        1%{?dist}
Summary:        The Athanor greeter
License:        MIT

BuildRequires:  rust cargo gcc pkgconf-pkg-config gtk4-devel glib2-devel gtk4-layer-shell-devel
Requires:       gtk4 gtk4-layer-shell greetd

%description
The greeter of Athanor OS: one GTK4 layer-shell surface that talks to greetd. A program
of its own, because it is the process that reads the password. It is started by
/usr/libexec/athanor-greeter-client inside a bubblewrap sandbox and confines its own
writes with Landlock before anything else.

%prep

%build
%set_build_flags
cargo build --release --locked -p %{name}

%install
install -D -m 0755 target/release/athanor-greeter-ui %{buildroot}/usr/bin/athanor-greeter-ui

%files
/usr/bin/athanor-greeter-ui

%changelog
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- The greeter as a program of its own (doc_shell.md, SH4: one crate per program), moved
  out of athanor-shell-rs unchanged in look and behaviour, on gtk4 0.11. Its Landlock
  write set is /tmp, the runtime directory and the DRM nodes; it loads no theme file,
  forces no renderer and no GDK_SCALE.

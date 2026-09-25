//! The shell's client of the compositor (doc_shell.md, package 2a): windows, workspaces,
//! outputs, the actions on them, and the launch of applications behind a security
//! context (doc_bar.md, BR2). Wayland and COSMIC types stay inside this crate; the shell
//! sees only the types of [`model`].

mod protocols;

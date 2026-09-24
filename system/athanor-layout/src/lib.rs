//! The layout of the Athanor desktop (doc_shell.md, SH6-SH8, SH10): the versioned,
//! layered document that names a preset and two knobs, and what follows from it.
//!
//! This crate is the permanent part of stage 1c. It knows no toolkit: the translator
//! that renders the layout for cosmic-panel and the chooser window both link it, and so
//! will the shell that one day reads the document itself.

pub mod document;
pub mod preset;

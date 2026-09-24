//! The layout of the Athanor desktop (doc_shell.md, SH6-SH8, SH10): the versioned,
//! layered document that names a preset and two knobs, and what follows from it.
//!
//! This crate is the permanent part of stage 1c. It knows no toolkit: the translator
//! that renders the layout for cosmic-panel and the chooser window both link it, and so
//! will the shell that one day reads the document itself.

pub mod cosmic;
pub mod document;
pub mod loader;
pub mod placement;
pub mod preset;

#[cfg(test)]
pub(crate) mod testing {
    use std::path::PathBuf;

    /// A fresh directory for one test, unique to this process and this name.
    pub fn scratch(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("athanor-layout-{}-{name}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("create the scratch directory");
        dir
    }
}

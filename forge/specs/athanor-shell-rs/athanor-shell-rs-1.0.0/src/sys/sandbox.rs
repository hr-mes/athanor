use landlock::{
    AccessFs, CompatLevel, Compatible, PathBeneath, PathFd, Ruleset, RulesetAttr, RulesetCreatedAttr, ABI,
};
use std::env;
use std::path::{Path, PathBuf};

/// Confines the process's writes with Landlock, mirroring the unit's sandbox.
///
/// The unit (`athanor-shell.service`) already runs the shell with
/// `ProtectSystem=strict`, `ProtectHome=read-only`, `ConfigurationDirectory=athanor`,
/// `StateDirectory=athanor` and `PrivateTmp=`: writes are only possible under the
/// configuration and state directories, the runtime directory and `/tmp`. This ruleset
/// restates that write set in-process, so that the confinement survives a unit that
/// lost its hardening. Reads are deliberately left alone: a desktop shell reads desktop
/// entries, icons, wallpapers and its own configuration from the home directory, and a
/// read policy written here would have to duplicate the unit's grants by hand. The
/// previous version of this policy did exactly that, denied reads of
/// `$XDG_CONFIG_HOME/athanor`, and left the shell unable to read the configuration it
/// had just written (theme.css "Permission denied" at every start, and the desktop
/// widgets rewriting widgets.json in a loop until systemd-oomd killed the process).
///
/// The ruleset is a hard requirement: a kernel without Landlock, or one that cannot
/// enforce every requested right, is an error rather than a best-effort no-op, so the
/// caller can refuse to run unconfined.
pub fn apply_landlock_sandbox() -> Result<(), Box<dyn std::error::Error>> {
    let abi = ABI::V1;
    let write_access = AccessFs::from_write(abi);

    let mut ruleset = Ruleset::default()
        .set_compatibility(CompatLevel::HardRequirement)
        .handle_access(write_access)?
        .create()?;

    for path in writable_paths() {
        if path.exists() {
            let path_fd = PathFd::new(&path)?;
            ruleset = ruleset.add_rule(PathBeneath::new(path_fd, write_access))?;
        }
    }

    ruleset.restrict_self()?;
    Ok(())
}

/// The directories the unit lets the shell write to.
fn writable_paths() -> Vec<PathBuf> {
    let home = env::var_os("HOME").map(PathBuf::from);
    let xdg_dir = |var: &str, fallback: &str| {
        env::var_os(var)
            .filter(|dir| !dir.is_empty())
            .map(PathBuf::from)
            .or_else(|| home.as_ref().map(|home| home.join(fallback)))
    };

    let mut paths = vec![PathBuf::from("/tmp")];
    if let Some(dir) = xdg_dir("XDG_CONFIG_HOME", ".config") {
        paths.push(dir.join("athanor"));
    }
    if let Some(dir) = xdg_dir("XDG_STATE_HOME", ".local/state") {
        paths.push(dir.join("athanor"));
    }
    if let Some(dir) = env::var_os("XDG_RUNTIME_DIR").filter(|dir| !dir.is_empty()) {
        paths.push(PathBuf::from(dir));
    }
    paths.retain(|path| Path::new(path).is_absolute());
    paths
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writable_set_follows_the_xdg_variables() {
        // Environment variables are process-wide; keep the test to a single thread of use.
        env::set_var("HOME", "/var/home/tester");
        env::set_var("XDG_CONFIG_HOME", "/var/home/tester/.config");
        env::remove_var("XDG_STATE_HOME");
        env::set_var("XDG_RUNTIME_DIR", "/run/user/1000");

        let paths = writable_paths();
        assert!(paths.contains(&PathBuf::from("/tmp")));
        assert!(paths.contains(&PathBuf::from("/var/home/tester/.config/athanor")));
        assert!(paths.contains(&PathBuf::from("/var/home/tester/.local/state/athanor")));
        assert!(paths.contains(&PathBuf::from("/run/user/1000")));
        assert_eq!(paths.len(), 4);
    }

    #[test]
    fn sandbox_is_enforced_on_writes_outside_the_allowed_set() {
        // Landlock confines the calling thread and its future children only, so the
        // restriction stays inside this thread and the rest of the test binary is free.
        std::thread::spawn(|| {
            apply_landlock_sandbox().expect("Landlock must be enforced, not skipped");

            let denied = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("landlock-probe");
            let err = std::fs::write(&denied, b"x").expect_err("write outside the set must fail");
            assert_eq!(err.kind(), std::io::ErrorKind::PermissionDenied);

            let allowed = PathBuf::from("/tmp").join(format!("landlock-probe-{}", std::process::id()));
            std::fs::write(&allowed, b"x").expect("write under /tmp must succeed");
            std::fs::remove_file(&allowed).expect("cleanup under /tmp must succeed");
        })
        .join()
        .expect("sandbox test thread");
    }
}

use landlock::{AccessFs, PathBeneath, PathFd, Ruleset, RulesetAttr, RulesetCreatedAttr, ABI};
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
pub fn apply_landlock_sandbox() -> Result<(), Box<dyn std::error::Error>> {
    let abi = ABI::V1;
    let write_access = AccessFs::from_write(abi);

    let mut ruleset = Ruleset::default().handle_access(write_access)?.create()?;

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
}

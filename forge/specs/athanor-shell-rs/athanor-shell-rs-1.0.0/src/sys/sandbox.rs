use landlock::{
    AccessFs, BitFlags, CompatLevel, Compatible, PathBeneath, PathFd, Ruleset, RulesetAttr, RulesetCreatedAttr,
    ABI,
};
use std::env;
use std::path::{Path, PathBuf};

/// Fails unless the calling process has exactly one thread.
///
/// Landlock confines the thread that calls `restrict_self` and the threads it creates
/// afterwards, not threads that already exist. The sandbox is therefore only complete
/// when it is applied while the process is still single-threaded, and this is checked
/// against the kernel's own thread list rather than assumed.
pub fn ensure_single_threaded() -> Result<(), Box<dyn std::error::Error>> {
    let threads = std::fs::read_dir("/proc/self/task")?.count();
    if threads != 1 {
        return Err(format!("{threads} threads exist; Landlock would leave all but one unconfined").into());
    }
    Ok(())
}

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
/// caller can refuse to run unconfined. Call it before any other thread exists (see
/// [`ensure_single_threaded`]).
pub fn apply_landlock_sandbox() -> Result<(), Box<dyn std::error::Error>> {
    restrict_writes_to(&grants())
}

/// The DRM device directory. GPU rendering opens its card and render nodes read-write,
/// and under a ruleset that handles write accesses opening a file for writing needs
/// `WriteFile`. Reads, directory listing and ioctls are not handled by the ABI V1 write
/// set, so they need no grant; creating or removing anything here is not granted.
const DRM_DEVICE_DIR: &str = "/dev/dri";

/// Every grant of the sandbox: the unit's writable directories with the whole write
/// set, and the DRM nodes with `WriteFile` alone.
fn grants() -> Vec<(PathBuf, BitFlags<AccessFs>)> {
    let write_access = AccessFs::from_write(ABI::V1);
    let mut grants: Vec<_> = writable_paths().into_iter().map(|path| (path, write_access)).collect();
    grants.push((PathBuf::from(DRM_DEVICE_DIR), AccessFs::WriteFile.into()));
    grants
}

/// Restricts the calling thread, and the threads it creates, to the write accesses
/// granted beneath each path; a path that does not exist is skipped.
fn restrict_writes_to(grants: &[(PathBuf, BitFlags<AccessFs>)]) -> Result<(), Box<dyn std::error::Error>> {
    let write_access = AccessFs::from_write(ABI::V1);

    let mut ruleset = Ruleset::default()
        .set_compatibility(CompatLevel::HardRequirement)
        .handle_access(write_access)?
        .create()?;

    for (path, access) in grants {
        if path.exists() {
            let path_fd = PathFd::new(path)?;
            ruleset = ruleset.add_rule(PathBeneath::new(path_fd, *access))?;
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

    /// Two sibling directories made for one test: `allowed` is granted, `denied` is not
    /// and can never be beneath `allowed`, wherever the temporary directory lives.
    fn probe_dirs(test: &str) -> (PathBuf, PathBuf, PathBuf) {
        let base = env::temp_dir().join(format!("athanor-landlock-{}-{test}", std::process::id()));
        let (allowed, denied) = (base.join("allowed"), base.join("denied"));
        std::fs::create_dir_all(&allowed).expect("create allowed dir");
        std::fs::create_dir_all(&denied).expect("create denied dir");
        (base, allowed, denied)
    }

    fn assert_denied(path: &Path) {
        let err = std::fs::write(path, b"x").expect_err("write outside the set must fail");
        assert_eq!(err.kind(), std::io::ErrorKind::PermissionDenied);
    }

    #[test]
    fn sandbox_is_enforced_on_writes_outside_the_allowed_set() {
        let (base, allowed, denied) = probe_dirs("enforced");
        // Landlock confines the calling thread and its future children only, so the
        // restriction stays inside this thread and the rest of the test binary is free.
        std::thread::spawn(move || {
            restrict_writes_to(&[(allowed.clone(), AccessFs::from_write(ABI::V1))]).expect("Landlock must be enforced, not skipped");
            assert_denied(&denied.join("probe"));
            std::fs::write(allowed.join("probe"), b"x").expect("write in the allowed set must succeed");
        })
        .join()
        .expect("sandbox test thread");
        std::fs::remove_dir_all(base).expect("cleanup outside the sandboxed thread");
    }

    #[test]
    fn threads_created_after_the_sandbox_inherit_it() {
        let (base, allowed, denied) = probe_dirs("inherit");
        std::thread::spawn(move || {
            restrict_writes_to(&[(allowed, AccessFs::from_write(ABI::V1))]).expect("Landlock must be enforced, not skipped");
            std::thread::spawn(move || assert_denied(&denied.join("probe")))
                .join()
                .expect("child thread");
        })
        .join()
        .expect("sandbox test thread");
        std::fs::remove_dir_all(base).expect("cleanup outside the sandboxed thread");
    }

    #[test]
    fn drm_nodes_are_granted_write_file_and_nothing_else() {
        let drm: Vec<_> = grants().into_iter().filter(|(path, _)| path.starts_with("/dev")).collect();
        assert_eq!(drm, vec![(PathBuf::from("/dev/dri"), BitFlags::from(AccessFs::WriteFile))]);
    }

    #[test]
    fn a_write_file_grant_opens_existing_nodes_read_write_but_creates_nothing() {
        let (base, nodes, _) = probe_dirs("write-file");
        let node = nodes.join("renderD128");
        std::fs::write(&node, b"").expect("create the stand-in node");
        std::thread::spawn(move || {
            restrict_writes_to(&[(nodes.clone(), AccessFs::WriteFile.into())])
                .expect("Landlock must be enforced, not skipped");
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(&node)
                .expect("an existing node opens read-write, as the DRM open path does");
            std::fs::read_dir(&nodes).expect("the directory stays listable");
            assert_denied(&nodes.join("card9"));
        })
        .join()
        .expect("sandbox test thread");
        std::fs::remove_dir_all(base).expect("cleanup outside the sandboxed thread");
    }

    #[test]
    fn a_second_thread_fails_the_single_thread_check() {
        let (release, wait) = std::sync::mpsc::channel::<()>();
        let other = std::thread::spawn(move || wait.recv());
        assert!(ensure_single_threaded().is_err(), "a live second thread must be detected");
        release.send(()).expect("release the second thread");
        other.join().expect("second thread").expect("released");
    }
}

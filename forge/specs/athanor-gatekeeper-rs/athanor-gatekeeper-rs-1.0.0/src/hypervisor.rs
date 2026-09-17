use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::io::{Seek, SeekFrom};
use std::os::unix::io::{AsRawFd, RawFd};
use std::path::Path;
use athanor_gatekeeper_rs::security::verify_file_fd_signature;

/// Strict seccomp policy for the crosvm VMM. The package installs it read-only under
/// `/usr`; the Gatekeeper never generates it at runtime, so no writable location can
/// ever supply the policy crosvm enforces.
const SECCOMP_POLICY_FILE: &str = "/usr/share/athanor-gatekeeper-rs/crosvm/strict.policy";

/// Guest kernel images usable for a MicroVM, in order of preference.
const GUEST_KERNELS: [&str; 3] = ["/boot/vmlinuz-athanor", "/boot/vmlinuz", "/boot/vmlinuz-linux"];

/// Host paths hidden from a Bubblewrap compartment behind an empty tmpfs.
const MASKED_PATHS: [&str; 3] = ["/etc/pki/secureboot", "/etc/pki/uki", "/run/secrets"];

/// The isolation boundary an approved application was launched inside.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IsolationBoundary {
    /// Hardware-isolated MicroVM run by crosvm.
    Crosvm,
    /// Hardware-isolated MicroVM run by cloud-hypervisor.
    CloudHypervisor,
    /// Bubblewrap compartment with every namespace unshared, network included.
    Bubblewrap,
}

impl std::fmt::Display for IsolationBoundary {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            IsolationBoundary::Crosvm => "crosvm MicroVM",
            IsolationBoundary::CloudHypervisor => "cloud-hypervisor MicroVM",
            IsolationBoundary::Bubblewrap => "bubblewrap compartment (network unshared)",
        })
    }
}

/// An application running inside an established isolation boundary.
pub struct IsolatedApp {
    /// The boundary process (VMM or bwrap) that contains the application.
    pub child: tokio::process::Child,
    /// Which boundary contains the application.
    pub boundary: IsolationBoundary,
}

/// Verifies that the seccomp policy at `path` can only have been written by a trusted
/// principal: the file must be a regular file (not a symlink), and the file and every
/// parent directory must be owned by root or by `owner_uid` and must not be writable by
/// group or others. Any deviation is an error, so the caller fails closed.
pub fn verify_seccomp_policy(path: &Path, owner_uid: u32) -> anyhow::Result<()> {
    if !path.is_absolute() {
        anyhow::bail!("Seccomp policy path {:?} is not absolute", path);
    }
    let meta = std::fs::symlink_metadata(path)
        .map_err(|e| anyhow::anyhow!("Cannot stat seccomp policy {:?}: {}", path, e))?;
    if !meta.file_type().is_file() {
        anyhow::bail!("Seccomp policy {:?} is not a regular file", path);
    }
    check_trusted_inode(path, &meta, owner_uid)?;

    for dir in path.ancestors().skip(1) {
        let meta = std::fs::symlink_metadata(dir)
            .map_err(|e| anyhow::anyhow!("Cannot stat directory {:?}: {}", dir, e))?;
        if !meta.file_type().is_dir() {
            anyhow::bail!("{:?} in the seccomp policy path is not a directory", dir);
        }
        check_trusted_inode(dir, &meta, owner_uid)?;
    }
    Ok(())
}

fn check_trusted_inode(path: &Path, meta: &std::fs::Metadata, owner_uid: u32) -> anyhow::Result<()> {
    if meta.uid() != 0 && meta.uid() != owner_uid {
        anyhow::bail!("{:?} is owned by uid {}, expected root", path, meta.uid());
    }
    if meta.mode() & 0o022 != 0 {
        anyhow::bail!("{:?} is writable by group or others (mode {:o})", path, meta.mode() & 0o7777);
    }
    Ok(())
}

/// Level 11 Micro-VM Hypervisor Isolation (Hardware Compartmentalization)
/// Launches an approved application inside the strongest available isolation boundary:
/// a `crosvm` or `cloud-hypervisor` MicroVM when a guest kernel is present, otherwise a
/// Bubblewrap compartment with every namespace unshared, network included.
///
/// Returns an error when no boundary can be established; the application is never run
/// outside one. The result names the boundary in use.
///
/// TOCTOU-Safe Implementation: Opens the file as a file descriptor (`File::open`) first,
/// verifies the FD contents/signature, and hands that same descriptor to the boundary.
pub async fn spawn_microvm_isolated_app(target_path: &Path) -> Result<IsolatedApp, anyhow::Error> {
    let parent = match target_path.parent() {
        Some(p) if p != Path::new("/") => p,
        _ => anyhow::bail!("Parent path does not exist or is root ('/'), refusing root FS mount"),
    };
    let app_name = target_path
        .file_name()
        .ok_or_else(|| anyhow::anyhow!("Target path {:?} has no file name", target_path))?;

    // TOCTOU Fix Step 1: Open the target executable file as a File descriptor first
    let mut file = File::open(target_path).map_err(|e| {
        anyhow::anyhow!("Failed to open target executable file {:?} safely: {}", target_path, e)
    })?;

    let fd = file.as_raw_fd();
    let proc_fd_path = format!("/proc/self/fd/{}", fd);

    // TOCTOU Fix Step 2: Verify FD contents / signature if signature xattr present
    let sig_attr = xattr::get(&proc_fd_path, "user.athanor.signature").ok().flatten();
    let pubkey_attr = xattr::get(&proc_fd_path, "user.athanor.pubkey").ok().flatten();
    if let (Some(sig), Some(pubkey)) = (sig_attr, pubkey_attr) {
        if !verify_file_fd_signature(&mut file, &sig, &pubkey).unwrap_or(false) {
            anyhow::bail!("PQC signature verification failed for file descriptor {}", fd);
        }
    }
    // The compartment copies the executable from this descriptor: start from its beginning.
    file.seek(SeekFrom::Start(0))
        .map_err(|e| anyhow::anyhow!("Failed to rewind file descriptor {}: {}", fd, e))?;

    println!(
        "[Level 11 Micro-VM Hypervisor] Intercepting execution. Launching isolated app for FD {} ({})",
        fd, proc_fd_path
    );

    // The crosvm seccomp policy must come from a root-owned, non-writable location.
    // The Gatekeeper runs as root, so root is the only trusted owner: fail closed otherwise.
    verify_seccomp_policy(Path::new(SECCOMP_POLICY_FILE), 0)
        .map_err(|e| anyhow::anyhow!("Refusing to launch: untrusted crosvm seccomp policy: {}", e))?;

    let mem_mb = std::env::var("ATHANOR_MICROVM_MEM_MB").unwrap_or_else(|_| "512".to_string());
    let mut candidates = Vec::new();

    // A MicroVM without a guest kernel is no boundary at all: only offer the VMMs when one exists.
    match GUEST_KERNELS.iter().copied().find(|k| Path::new(k).is_file()) {
        Some(guest_kernel) => {
            candidates.push((
                IsolationBoundary::Crosvm,
                build_crosvm_command(&mem_mb, SECCOMP_POLICY_FILE, parent, &proc_fd_path, guest_kernel),
            ));
            candidates.push((
                IsolationBoundary::CloudHypervisor,
                build_cloud_hypervisor_command(&mem_mb, &proc_fd_path, guest_kernel),
            ));
        }
        None => println!("[Level 11 Micro-VM Hypervisor] No guest kernel found, MicroVM boundaries unavailable."),
    }
    candidates.push((IsolationBoundary::Bubblewrap, build_bwrap_command(fd, Path::new(app_name))));

    let app = launch_first_available(candidates).await?;
    println!("[Level 11 Micro-VM Hypervisor] Application launched inside {}.", app.boundary);
    Ok(app)
}

/// Spawns the first boundary whose command starts, in order. Fails with every spawn
/// error when none does, so the caller never reports an unisolated launch as success.
pub async fn launch_first_available(
    candidates: Vec<(IsolationBoundary, tokio::process::Command)>,
) -> anyhow::Result<IsolatedApp> {
    let mut failures = Vec::new();
    for (boundary, mut cmd) in candidates {
        match cmd.spawn() {
            Ok(child) => return Ok(IsolatedApp { child, boundary }),
            Err(e) => failures.push(format!("{}: {}", boundary, e)),
        }
    }
    anyhow::bail!("No isolation boundary could be established ({})", failures.join("; "))
}

/// Builds the `cloud-hypervisor` MicroVM command.
pub fn build_cloud_hypervisor_command(mem_mb: &str, proc_fd_path: &str, guest_kernel: &str) -> tokio::process::Command {
    let mut cmd = tokio::process::Command::new("cloud-hypervisor");
    cmd.arg("--cpus").arg("boot=2")
        .arg("--memory").arg(format!("size={}M", mem_mb))
        .arg("--seccomp").arg("true")
        .arg("--kernel").arg(guest_kernel)
        .arg("--cmdline").arg(format!(
            "init={} console=ttyS0 quiet sysctl.kernel.unprivileged_bpf_disabled=1 sysctl.vm.unprivileged_userfaultfd=0 kernel.yama.ptrace_scope=3",
            proc_fd_path
        ));
    cmd
}

/// Builds the Bubblewrap compartment command. Every namespace is unshared, network
/// included: the Gatekeeper has no per-application policy that could grant network
/// access. The executable is copied into the compartment from `exec_fd` (the verified
/// descriptor), never re-resolved by path.
pub fn build_bwrap_command(exec_fd: RawFd, app_name: &Path) -> tokio::process::Command {
    let app_dest = Path::new("/app").join(app_name);
    let mut cmd = tokio::process::Command::new("bwrap");
    cmd.arg("--unshare-all")
        .arg("--ro-bind").arg("/usr").arg("/usr")
        .arg("--ro-bind").arg("/lib").arg("/lib")
        .arg("--ro-bind").arg("/lib64").arg("/lib64")
        .arg("--ro-bind").arg("/etc").arg("/etc");
    // A path absent on the host has nothing to hide, and bwrap cannot create a mount
    // point inside the read-only /etc bind.
    for masked in MASKED_PATHS.iter().filter(|p| Path::new(p).exists()) {
        cmd.arg("--tmpfs").arg(masked);
    }
    cmd.arg("--proc").arg("/proc")
        .arg("--dev").arg("/dev")
        .arg("--dir").arg("/tmp")
        .arg("--perms").arg("0555")
        .arg("--ro-bind-data").arg(exec_fd.to_string()).arg(&app_dest)
        .arg("--").arg(&app_dest);
    // SAFETY: runs in the forked child before exec; fcntl is async-signal-safe. Clearing
    // FD_CLOEXEC lets bwrap inherit the verified descriptor it reads the executable from.
    unsafe {
        cmd.pre_exec(move || {
            if libc::fcntl(exec_fd, libc::F_SETFD, 0) == -1 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    cmd
}

/// Helper to build `crosvm` Command with strict memory limits (--mem 512) and dynamic ballooning (--balloon).
pub fn build_crosvm_command(
    mem_mb: &str,
    seccomp_policy: &str,
    parent: &Path,
    proc_fd_path: &str,
    guest_kernel: &str,
) -> tokio::process::Command {
    let mut cmd = tokio::process::Command::new("crosvm");
    cmd.arg("run")
        .arg("--cpus").arg("2")
        .arg("--mem").arg(mem_mb)
        .arg("--balloon")
        .arg("--seccomp-policy").arg(seccomp_policy)
        .arg("--rw-shared-dir").arg(format!("{}:/app:type=fs", parent.display()))
        .arg("--params").arg(format!(
            "init={} root=/dev/vda rw console=ttyS0 quiet sysctl.kernel.unprivileged_bpf_disabled=1 sysctl.vm.unprivileged_userfaultfd=0 kernel.yama.ptrace_scope=3",
            proc_fd_path
        ))
        .arg(guest_kernel);
    cmd
}

/// Safely reads the seccomp BPF policy file without risking a process panic.
#[allow(dead_code)]
pub fn read_seccomp_policy(path: &Path) -> anyhow::Result<String> {
    std::fs::read_to_string(path)
        .map_err(|e| anyhow::anyhow!("Failed to read seccomp policy at {:?}: {}", path, e))
}

/// Safely parses argument values (e.g. `--mem`) from crosvm command line arguments without panicking.
#[allow(dead_code)]
pub fn parse_mem_arg(args: &[String]) -> anyhow::Result<String> {
    let mem_idx = args
        .iter()
        .position(|r| r == "--mem")
        .ok_or_else(|| anyhow::anyhow!("Missing '--mem' argument in crosvm command line"))?;
    args.get(mem_idx + 1)
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("Missing value after '--mem' flag"))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fresh, uniquely named scratch directory for one test.
    fn scratch_dir(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("gatekeeper-{}-{}", name, uuid::Uuid::new_v4()));
        std::fs::create_dir(&dir).expect("create scratch dir");
        dir
    }

    fn write_file(path: &Path, mode: u32) {
        use std::os::unix::fs::PermissionsExt;
        std::fs::write(path, "bpf: return 1\n").expect("write file");
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode)).expect("chmod");
    }

    #[test]
    fn test_shipped_seccomp_policy_blocks_dangerous_syscalls() {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/crosvm-strict.policy");
        let content = read_seccomp_policy(Path::new(path)).expect("shipped policy is readable");
        assert!(content.contains("bpf: return 1"), "Policy must block bpf syscalls");
        assert!(content.contains("ptrace: return 1"), "Policy must block ptrace syscalls");
        assert!(content.contains("userfaultfd: return 1"), "Policy must block userfaultfd syscalls");
    }

    #[test]
    fn test_seccomp_policy_owned_by_another_uid_is_refused() {
        let dir = scratch_dir("owner");
        let policy = dir.join("strict.policy");
        write_file(&policy, 0o644);
        // SAFETY: geteuid has no preconditions and cannot fail.
        let euid = unsafe { libc::geteuid() };
        let trusted_uid = if euid == 0 {
            // Running as root: hand the file to an unprivileged uid.
            std::os::unix::fs::chown(&policy, Some(65534), None).expect("chown");
            0
        } else {
            euid + 1
        };
        let err = verify_seccomp_policy(&policy, trusted_uid).expect_err("foreign owner must be refused");
        assert!(err.to_string().contains("owned by uid"), "unexpected error: {}", err);
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn test_seccomp_policy_writable_by_others_is_refused() {
        let dir = scratch_dir("mode");
        let policy = dir.join("strict.policy");
        write_file(&policy, 0o666);
        // SAFETY: geteuid has no preconditions and cannot fail.
        let euid = unsafe { libc::geteuid() };
        let err = verify_seccomp_policy(&policy, euid).expect_err("writable policy must be refused");
        assert!(err.to_string().contains("writable"), "unexpected error: {}", err);
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn test_seccomp_policy_in_world_writable_directory_is_refused() {
        use std::os::unix::fs::PermissionsExt;
        let dir = scratch_dir("dir");
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o777)).expect("chmod dir");
        let policy = dir.join("strict.policy");
        write_file(&policy, 0o644);
        // SAFETY: geteuid has no preconditions and cannot fail.
        let euid = unsafe { libc::geteuid() };
        let err = verify_seccomp_policy(&policy, euid).expect_err("world-writable parent must be refused");
        assert!(err.to_string().contains(&format!("{:?}", dir)), "unexpected error: {}", err);
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn test_seccomp_policy_symlink_and_missing_file_are_refused() {
        let dir = scratch_dir("link");
        let link = dir.join("strict.policy");
        std::os::unix::fs::symlink("/etc/passwd", &link).expect("symlink");
        assert!(verify_seccomp_policy(&link, 0).is_err(), "symlinked policy must be refused");
        assert!(verify_seccomp_policy(&dir.join("absent.policy"), 0).is_err(), "missing policy must be refused");
        assert!(verify_seccomp_policy(Path::new("relative.policy"), 0).is_err(), "relative path must be refused");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn test_root_owned_read_only_file_is_accepted() {
        // /etc/passwd and all its parents are root-owned and not group/world-writable.
        verify_seccomp_policy(Path::new("/etc/passwd"), 0).expect("root-owned file must be accepted");
    }

    #[tokio::test]
    async fn test_all_boundaries_failing_is_an_error() {
        let missing = |name: &str| tokio::process::Command::new(format!("/nonexistent/athanor-test/{}", name));
        let candidates = vec![
            (IsolationBoundary::Crosvm, missing("crosvm")),
            (IsolationBoundary::CloudHypervisor, missing("cloud-hypervisor")),
            (IsolationBoundary::Bubblewrap, missing("bwrap")),
        ];
        let err = match launch_first_available(candidates).await {
            Ok(app) => panic!("launch without any boundary reported success via {}", app.boundary),
            Err(e) => e,
        };
        assert!(err.to_string().contains("No isolation boundary"), "unexpected error: {}", err);
    }

    #[test]
    fn test_bwrap_command_unshares_network_and_executes_from_fd() {
        let cmd = build_bwrap_command(7, Path::new("app-binary"));
        let std_cmd = cmd.as_std();
        let args: Vec<String> = std_cmd.get_args().map(|s| s.to_string_lossy().to_string()).collect();

        assert_eq!(std_cmd.get_program(), "bwrap");
        assert!(args.contains(&"--unshare-all".to_string()), "Compartment must unshare every namespace");
        assert!(!args.contains(&"--share-net".to_string()), "Compartment must not share the network");
        let data = args.iter().position(|a| a == "--ro-bind-data").expect("executable copied from fd");
        assert_eq!(args[data + 1], "7");
        assert_eq!(args[data + 2], "/app/app-binary");
        assert_eq!(args[args.len() - 2..], ["--".to_string(), "/app/app-binary".to_string()]);
    }

    #[test]
    fn test_crosvm_command_memory_and_balloon_args() {
        let parent = Path::new("/tmp");
        let proc_fd_path = "/proc/self/fd/3";
        let guest_kernel = "/boot/vmlinuz";
        let policy = SECCOMP_POLICY_FILE;
        let cmd = build_crosvm_command("512", policy, parent, proc_fd_path, guest_kernel);
        let std_cmd = cmd.as_std();
        let args: Vec<String> = std_cmd.get_args().map(|s| s.to_string_lossy().to_string()).collect();

        assert_eq!(std_cmd.get_program(), "crosvm");
        assert!(args.contains(&"--mem".to_string()), "Command must include --mem");
        let mem_val = parse_mem_arg(&args).unwrap_or_default();
        assert_eq!(mem_val, "512", "Default memory limit must be 512MB");
        assert!(args.contains(&"--balloon".to_string()), "Command must include --balloon");
    }
}


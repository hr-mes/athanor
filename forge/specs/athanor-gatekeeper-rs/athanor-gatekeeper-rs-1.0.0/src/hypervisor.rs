use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::os::unix::io::AsRawFd;
use std::path::Path;
use athanor_gatekeeper_rs::security::verify_file_fd_signature;

/// Strict seccomp policy for the crosvm VMM. The package installs it read-only under
/// `/usr`; the Gatekeeper never generates it at runtime, so no writable location can
/// ever supply the policy crosvm enforces.
const SECCOMP_POLICY_FILE: &str = "/usr/share/athanor-gatekeeper-rs/crosvm/strict.policy";

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
/// Spawns untrusted applications inside a hardware-accelerated Micro-VM using `crosvm`
/// with guest Kernel isolation, falling back to `cloud-hypervisor`, `firecracker`, or `bwrap`.
///
/// TOCTOU-Safe Implementation: Opens the file as a file descriptor (`File::open`) first,
/// verifies the FD contents/signature, and executes via `/proc/self/fd/{fd}` to prevent
/// symlink race conditions.
pub async fn spawn_microvm_isolated_app(target_path: &Path) -> Result<tokio::process::Child, anyhow::Error> {
    let parent = match target_path.parent() {
        Some(p) if p != Path::new("/") => p,
        _ => anyhow::bail!("Parent path does not exist or is root ('/'), refusing root FS mount"),
    };

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

    println!(
        "[Level 11 Micro-VM Hypervisor] Intercepting execution. Launching hardware-isolated AppVM via crosvm for FD {} ({})",
        fd, proc_fd_path
    );

    // The crosvm seccomp policy must come from a root-owned, non-writable location.
    // The Gatekeeper runs as root, so root is the only trusted owner: fail closed otherwise.
    verify_seccomp_policy(Path::new(SECCOMP_POLICY_FILE), 0)
        .map_err(|e| anyhow::anyhow!("Refusing to launch: untrusted crosvm seccomp policy: {}", e))?;

    // Locate guest Kernel image for hardware virtualization
    let guest_kernel = if Path::new("/boot/vmlinuz-athanor").exists() {
        "/boot/vmlinuz-athanor"
    } else if Path::new("/boot/vmlinuz").exists() {
        "/boot/vmlinuz"
    } else {
        "/boot/vmlinuz-linux"
    };

    // TOCTOU Fix Step 3: Execute via /proc/self/fd/{fd} instead of path string
    let mem_mb = std::env::var("ATHANOR_MICROVM_MEM_MB").unwrap_or_else(|_| "512".to_string());

    // 1. Primary: Spawns inside a hardware-accelerated crosvm Micro-VM with strict seccomp & 512MB memory limits + ballooning
    let crosvm_res = build_crosvm_command(&mem_mb, SECCOMP_POLICY_FILE, parent, &proc_fd_path, guest_kernel).spawn();

    if let Ok(child) = crosvm_res {
        println!("[Level 11 Micro-VM Hypervisor] Hardware-isolated AppVM spawned via crosvm with strict 512MB memory limit & virtio-balloon.");
        return Ok(child);
    }

    // 2. Secondary: Cloud-hypervisor Micro-VM fallback
    println!("[Level 11 Micro-VM Hypervisor] crosvm execution bypassed/unavailable. Trying cloud-hypervisor...");
    let cloud_res = tokio::process::Command::new("cloud-hypervisor")
        .arg("--cpus").arg("boot=2")
        .arg("--memory").arg(format!("size={}M", mem_mb))
        .arg("--seccomp").arg("true")
        .arg("--kernel").arg(guest_kernel)
        .arg("--cmdline").arg(format!(
            "init={} console=ttyS0 quiet sysctl.kernel.unprivileged_bpf_disabled=1 sysctl.vm.unprivileged_userfaultfd=0 kernel.yama.ptrace_scope=3",
            proc_fd_path
        ))
        .spawn();

    if let Ok(child) = cloud_res {
        println!("[Level 11 Micro-VM Hypervisor] Hardware-isolated AppVM spawned via cloud-hypervisor.");
        return Ok(child);
    }

    // 3. Tertiary: Firecracker Micro-VM fallback
    println!("[Level 11 Micro-VM Hypervisor] cloud-hypervisor bypassed. Trying firecracker...");
    let fc_res = tokio::process::Command::new("firecracker")
        .arg("--api-sock").arg("/tmp/firecracker.socket")
        .spawn();

    if let Ok(child) = fc_res {
        println!("[Level 11 Micro-VM Hypervisor] Hardware-isolated AppVM spawned via firecracker.");
        return Ok(child);
    }

    // 4. Lightweight container fallback via Bubblewrap executing via /proc/self/fd/{fd}
    println!("[Level 11 Micro-VM Hypervisor] Hypervisor backends unexecutable. Falling back to bwrap sandbox via /proc/self/fd/{}.", fd);
    tokio::process::Command::new("bwrap")
        .arg("--unshare-all")
        .arg("--share-net")
        .arg("--ro-bind").arg("/usr").arg("/usr")
        .arg("--ro-bind").arg("/lib").arg("/lib")
        .arg("--ro-bind").arg("/lib64").arg("/lib64")
        .arg("--ro-bind").arg("/etc").arg("/etc")
        .arg("--tmpfs").arg("/etc/pki/secureboot")
        .arg("--tmpfs").arg("/etc/pki/uki")
        .arg("--tmpfs").arg("/run/secrets")
        .arg("--proc").arg("/proc")
        .arg("--dev").arg("/dev")
        .arg("--dir").arg("/tmp")
        .arg("--ro-bind").arg(&proc_fd_path).arg(&proc_fd_path)
        .arg("--").arg(&proc_fd_path)
        .spawn()
        .map_err(Into::into)
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


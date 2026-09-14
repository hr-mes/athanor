# Athanor OS: Kernel and Platform Profile

Status: **draft for maintainer review, 2026-09-14.** This document is the definitive
profile of the Athanor kernel and of the platform layer that makes its guarantees real:
what the kernel is, how it boots, how its integrity is proven, how machine roles compose,
and how every property is verified. It supersedes sections 4 (config), 6 (signing and
boot chain), 11 (outside the kernel) and 13 (maintainer decisions) of
[doc_kernel_build.md](doc_kernel_build.md), which remains the specification of *how the
kernel is built, pinned, published and maintained*.

The profile is definitive in one precise sense: every property below is recorded as a
decision with its rationale, every build and every installed machine is checked against
it, and it changes only through a new written decision. Upstream moves, so the profile is
re-verified at every kernel bump; it is not frozen.

## 1. Goals and constraints

- A single kernel binary for every machine, on par with or above competing distributions
  and with macOS and Windows on integrity, where Linux makes that possible.
- Full control of the kernel as a platform for purpose-built Athanor applications, built
  on stable kernel interfaces rather than a deeper fork.
- Maximum technical level with minimum maintenance: upstream mechanisms over custom code,
  every gate fails loudly, the system maintains itself.
- Hardware baseline: x86-64-v3 CPUs (the userland is already built for v3). The integrity
  chain (UEFI Secure Boot, TPM 2.0) is optional per machine, with a declared degraded mode.
- Roles: desktop, laptop, mesh node; a machine may hold several.
- Areas that require explicit maintainer approval before any code change remain so:
  the Gatekeeper (`forge/specs/athanor-gatekeeper-rs`), attestation
  (`system/confidential_computing/athanor-attestation`) and
  `system/athanor-bus-api/src/polkit.rs`. This document fixes requirements and kernel
  primitives for them, not their code.

## 2. Decision record

Provisional decisions carry a default and are closed by the benchmark phase (section 13).

| ID | Decision | Rationale | State |
| --- | --- | --- | --- |
| D1 | One kernel binary; roles are runtime profiles | one build, one signature, simple attestation | final |
| D2 | Roles compose; a machine holds zero or more | a workstation can also be a mesh node | final |
| D3 | CPU baseline x86-64-v3; integrity chain optional with declared degraded mode | matches the v3 userland; keeps machines without TPM/SB installable | final |
| D4 | Rust enabled; performance from AutoFDO and Propeller; ThinLTO re-checked at every bump | `RUST` still depends on `!DEBUG_INFO_BTF \|\| (PAHOLE_HAS_LANG_EXCLUDE && !LTO)`; AutoFDO/Propeller do not require LTO; Rust is the path to in-tree drivers such as nova | final |
| D5 | BORE is the base scheduler; sched_ext only through `scx_loader` as a role setting; `athanor-ebpf-sched` retired as a scheduler | one owner; sched_ext falls back to the fair class on failure | final |
| D6 | `/usr` on dm-verity with a signed root hash, A/B slots updated by `systemd-sysupdate`, UKI-only boot with systemd-boot | IPE and systemd's own exec restriction require dm-verity; boot counting, rollback and addons are native; the bootc composefs backend lacks them | final |
| D7 | Delta updates by content-defined chunking (desync), verified by the dm-verity signature | keeps small downloads without weakening integrity | final, efficiency measured in P4b |
| D8 | IPE is the single in-kernel enforcer for code integrity | upstream, compiled into the kernel, signed policies; a custom BPF LSM cannot see fs-verity through overlayfs on 7.1 | final |
| D9 | Role content ships inside the signed image; the active role set is a signed UKI addon per role | confext passed through the stub is unmerged at switch-root; addons are verified by shim and measured into PCR 12 | final |
| D10 | Composition follows NixOS semantics: type-based merge, conflict is a build error resolved only by explicit priority | explicit, no silent resolution, proven model | final |
| D11 | On a desktop or laptop, the mesh node role runs inside a MicroVM; mesh-only machines apply the mesh policy on the host | IPE allows one active policy; mesh default-deny excludes JIT and user code | final |
| D12 | The mesh node role requires attested mode | a node that keeps its key but runs altered code must not stay a node | final |
| D13 | Preemption `full` | desktop latency | provisional |
| D14 | `X86_64_VERSION=3` for the kernel | aligned with the baseline | provisional |
| D15 | Swap on zram (zstd), zswap off | no double compression, no disk swap on LUKS | final; swappiness provisional |
| D16 | IOMMU strict by default | DMA attacks through Thunderbolt/USB4 | provisional (throughput cost) |
| D17 | Minimal initramfs, ESP of 2 GiB | today's UKI carries 102 MB of initramfs, mostly modules only needed after boot | final |
| D18 | Laptop is an autonomous role; desktop and laptop share an `interactive` fragment of the manifest | a laptop without the desktop role keeps 32-bit, gaming and interactive settings, without duplicated definitions | final |
| D19 | `kernel.warn_limit=100` on mesh nodes only, off on interactive roles; `kernel.oops_limit=100` everywhere | a noisy driver must not power off a desktop; a mesh node emitting repeated warnings must stop | final |
| D20 | SELinux becomes non-disableable after zero AVC denials in Athanor domains; denials from Fedora packages are triaged and documented, and none may affect boot, login or security | a gate that does not depend on upstream policy bugs | final |
| D21 | Role addons are built and signed in CI and shipped inside the image; every update reinstalls the addons of the active roles from the new image in the same sysupdate transaction as the UKI | roles and image can never diverge; no second distribution channel | final |
| D22 | Hosting of the delta chunk store | chosen in P4b from measured delta sizes, chunk counts and expected traffic | open |
| D23 | Desktop class: execution allowed in the home and measured by IMA; `noexec` on `/tmp`, `/var/tmp`, `/dev/shm`, `/run/user`, removable media and a dedicated btrfs subvolume bound to each user's `~/Downloads` | blocks the common attack paths (downloaded or temporary payloads) without breaking development tools, Claude Code or build outputs in the home | final |
| D24 | SELinux denies `execmem` to system and Athanor service domains except those declared; user applications stay in `unconfined_t` as in Fedora | restricting user domains would break Electron, Java, .NET, Python ctypes and emulators, not only browsers | final |
| D25 | The Fedora 45 rebase starts on the beta as soon as P3 is green; the image that reinstalls the maintainer's desktop is built only on the final release (target 2026-10-20) | problems surface early, production waits for a supported release | final |

## 3. Architecture overview

```
firmware (Microsoft UEFI CA)
  └─ shim (Fedora, Microsoft-signed)                      verifies with db + MokList
       └─ systemd-boot            signed: Secure Boot key  boot counting (+3)
            └─ UKI                signed: Secure Boot key  .cmdline (usrhash=, base params)
                 │                                          .pcrsig (signed PCR 11 policy)
                 ├─ /loader/addons/athanor-role-<r>.addon.efi   signed: Secure Boot key → PCR 12
                 └─ kernel (Azoth, IPE boot policy, integrity certificate compiled in)
                      └─ /usr: dm-verity, root hash signed with the integrity key
                           ├─ /usr/lib/athanor/roles/<r>/     role content
                           └─ athanor-roles generator → /run/{sysctl.d,modprobe.d,tmpfiles.d,systemd}
/ , /var, /home: btrfs on LUKS (TPM: PCR 7 + signed PCR 11 + PCR 14; passphrase otherwise)
```

Four layers, one source of truth each:

1. **Kernel build profile**: `forge/specs/azoth/kernel-local` (section 5).
2. **Runtime base profile**: the package `forge/specs/athanor-kernel-profile`, which
   replaces the kernel-related files scattered today in `athanor-base-config` (`kargs.d`,
   `modprobe.d`, `scx_loader` drop-in) and `athanor-system-tweaks` (`sysctl.d`) (section 6).
3. **Roles**: `athanor-kernel-profile/roles/<role>/`, installed under
   `/usr/lib/athanor/roles/<role>/`, activated by signed addons (section 7).
4. **Manifest**: `athanor-kernel-profile/profile.toml` declares every setting of the base
   and of each role with its type and priority; a repository script generates the files,
   validates every role combination and computes the expected effective profile that the
   drift checker enforces (sections 7 and 12).

## 4. Integrity modes

- **Attested**: Secure Boot on, the project Secure Boot certificate enrolled in MokList,
  TPM 2.0 present, the signed PCR 11 policy valid, PCR 12 consistent with the declared
  role set. Required by the mesh node role (D12).
- **Degraded** (declared "not attested"): anything missing. The UKI still boots and
  dm-verity still verifies `/usr` on every read. Without Secure Boot, systemd-stub accepts
  a command line from the boot loader and the UKI itself is not verified by firmware, so
  an attacker with physical access can replace them. `athanor-profile-check` reports the
  mode and the reasons; the mesh node role is refused.
- In degraded mode the role addons are not verified either: shim verifies them only
  under Secure Boot, so someone with physical access can add a forged addon such as
  `athanor.role=mesh`. Roles are therefore *declared*, not *proven*, on a degraded
  machine: `athanor-profile-check` reports them as declared, `athanor-role` never grants
  anything on the strength of the command line alone, and no trust decision (mesh
  admission, attestation, IPE policy class stronger than the one the machine actually
  enforces) may rest on a role that is not backed by attested mode.
- First boot starts degraded. A guided step imports the Secure Boot certificate
  (`mokutil --import`); the confirmation in MokManager is a human action by design. The
  next boot with Secure Boot on is attested.

## 5. Kernel build profile (`kernel-local`)

Principle: what holds for every role and must not be changeable at boot lives in the
build configuration, not on the command line.

**From the command line into the build:**
`LOCK_DOWN_KERNEL_FORCE_INTEGRITY=y`, `INIT_ON_FREE_DEFAULT_ON=y`,
`EFI_DISABLE_PCI_DMA=y`, `LEGACY_VSYSCALL_NONE=y`, `DEBUG_FS_ALLOW_NONE=y`,
`PANIC_ON_OOPS=y`, `PANIC_TIMEOUT=10`, `INTEL_IOMMU_DEFAULT_ON=y`.

**New hardening:** `KSTACK_ERASE=y`, `PAGE_TABLE_CHECK=y`, `PAGE_TABLE_CHECK_ENFORCED=y`,
`DEBUG_VIRTUAL=y`, `DEBUG_SG=y`, `DEBUG_NOTIFIERS=y`, `ARCH_MMAP_RND_BITS=32`,
`ARCH_MMAP_RND_COMPAT_BITS=16`, `PROC_MEM_FORCE_PTRACE=y`,
`IOMMU_DEFAULT_DMA_STRICT=y` (D16), `IA32_EMULATION_DEFAULT_DISABLED=y` (the desktop
and laptop roles re-enable it), `SECURITY_SELINUX_DEVELOP` and `SECURITY_SELINUX_BOOTPARAM`
off (D20: zero AVC denials in Athanor domains in acceptance before they are switched off;
denials from Fedora packages triaged and documented, none affecting boot, login or security).

**Integrity:** `DM_VERITY=y` (built in, not a module), `SECURITY_IPE=y`,
`IPE_BOOT_POLICY` set to the compiled boot policy (section 10),
`DM_VERITY_VERIFY_ROOTHASH_SIG=y` with `DM_VERITY_VERIFY_ROOTHASH_SIG_SECONDARY_KEYRING=y`
and **`DM_VERITY_VERIFY_ROOTHASH_SIG_PLATFORM_KEYRING` off**, `IPE_POLICY_SIG_SECONDARY_KEYRING=y`
and **`IPE_POLICY_SIG_PLATFORM_KEYRING` off**. The platform keyring holds the UEFI db,
which includes third-party CAs: it must not be able to sign executable code or policy.
`SYSTEM_TRUSTED_KEYS` carries the module signing and integrity certificates;
`SYSTEM_REVOCATION_KEYS` the retired ones.

**Attack surface removed** (unused by every role): `KEXEC`, `KEXEC_FILE`, `CRASH_DUMP`
(crash data comes from pstore), `LIVEPATCH` (updates are images), `HIBERNATION` (blocked
by lockdown), `SECURITY_TOMOYO`, `X86_IOPL_IOPERM`. `LSM="lockdown,yama,integrity,selinux,bpf,landlock,ipe"`.

**Kept on purpose:** `IA32_EMULATION` and `MODIFY_LDT_SYSCALL` (Steam, Wine), `MODULES`
(NVIDIA), `BPF_LSM`, `KALLSYMS`, kprobes and ftrace (the eBPF nerve, observability),
`IMA_ARCH_POLICY` (attestation), `ZRAM`.

**Rejected:** `STATIC_USERMODEHELPER` (needs a single helper Athanor does not have),
`RESET_ATTACK_MITIGATION` (without userspace support the firmware wipes RAM at every
boot), `TRIM_UNUSED_KSYMS` (breaks the NVIDIA modules), `RANDSTRUCT` (excluded by Rust),
`SECURITY_LOADPIN` (IPE covers `KMODULE` and `FIRMWARE`).

**Codegen:** `RUST=y`, `AUTOFDO_CLANG=y`, `PROPELLER_CLANG=y` (profiles arrive in P7),
`X86_64_VERSION=3` (D14), preemption `full` (D13).

## 6. Runtime base profile

**Kernel command line.** Nearly empty: only what installation knows (LUKS device, root)
and `usrhash=` from the image build. Removed from today's `kargs.d` and kickstart:
`slab_nomerge`, `randomize_kstack_offset`, `ima_hash` (already defaults), `pti=on`
(forces page table isolation on CPUs not affected by Meltdown, a pure cost),
`amd_iommu=on` (rejected by the kernel), `mem_encrypt=on`, `lam=on`, `arm64.mte=on`,
`kvm_intel.tdx=1` (invalid or wrong platform), `module.sig_enforce`, `lockdown`,
`init_on_free`, `vsyscall`, `debugfs`, `oops` (moved into the build). NVIDIA parameters
move to `modprobe.d`. `ima_policy=tcb` is replaced by an IMA policy loaded at boot that
measures code executed from the writable areas only.

**sysctl (base, locked):** `kernel.yama.ptrace_scope=1`, `kernel.kptr_restrict=2`,
`kernel.dmesg_restrict=1`, `dev.tty.ldisc_autoload=0`, `fs.protected_fifos=2`,
`fs.protected_regular=2`, `fs.suid_dumpable=0`, `kernel.oops_limit=100`,
`kernel.io_uring_disabled=1` with `kernel.io_uring_group` set to
the `athanor-io-uring` group, `net.core.default_qdisc=fq`. The TCP congestion control is
not set, so the kernel default BBRv3 applies. `athanor-system-tweaks/.../99-bore.conf`
is removed with its CFS tunables that no longer exist under EEVDF.

**Scheduler:** EEVDF with BORE at the defaults of the pinned patch
(`sched_burst_penalty_offset=24`, `sched_burst_penalty_scale=1536`), `HZ=1000`.

**Memory:** zram swap with zstd (`zram-size = min(ram / 2, 8192)`), MGLRU on, THP
`madvise` with defrag `defer+madvise`.

**Power:** power-profiles-daemon is the only owner of EPP and platform profile;
`amd_pstate` active.

## 7. Roles

**Content.** Each role is a directory in the signed image,
`/usr/lib/athanor/roles/<role>/`, holding `sysctl.d`, `modprobe.d`, `tmpfiles.d`,
`systemd` units and drop-ins, `power-profiles-daemon` and `scx_loader` configuration.
It is protected by dm-verity like the rest of `/usr` and updated atomically with the OS.

**Activation.** A role is active when its signed addon
`/loader/addons/athanor-role-<role>.addon.efi` exists. The addon carries
`athanor.role=<role>` and the role's kernel parameters, has no `.uname` section so it
survives kernel updates, is verified through shim, and is measured into PCR 12 together
with the other command line fragments. Addons are built and signed in CI and shipped
inside the image as `/usr/lib/athanor/roles/<role>/athanor-role-<role>.addon.efi`,
protected by dm-verity like the role content; `athanor-role` copies the addons of the
chosen roles to the ESP, and every update reinstalls them from the new image (D21), so
a role can never run with parameters from another image version.

**Application.** The `athanor-roles` systemd generator reads `/proc/cmdline`
(authenticated under Secure Boot) and links the role files into
`/run/sysctl.d`, `/run/modprobe.d`, `/run/tmpfiles.d` and `/run/systemd/`. Configuration
that is read only from `/etc` (`power-profiles-daemon`, `scx_loader`) is reached through
a tmpfiles symlink. P5 verifies the ordering of the generator against
`systemd-sysctl.service` and module coldplug.

**Composition (`profile.toml`).** Settings have types. Lists merge by union, maps merge
recursively, scalars from two roles with different values are a build error unless one
definition carries an explicit higher priority; numeric sysctls may declare an ordering
(`max`, `min`) when the direction is obvious. Base settings marked locked cannot be
overridden. The validator evaluates every role combination and fails on any unresolved
conflict. The effective profile of each combination is the input of the drift checker.
Shared definitions live in manifest fragments that are not roles and cannot be
activated alone: desktop and laptop both include the `interactive` fragment (32-bit
emulation, autogroup, MGLRU `min_ttl_ms`, `ntsync`, `vm.max_map_count`,
`split_lock_mitigate=0`, `kernel.warn_limit=0`), so the laptop stands alone without
duplicating the desktop (D18).

**Roles:**

| Setting | Desktop | Laptop | Mesh node |
| --- | --- | --- | --- |
| addon parameters | `rhgb`, `ia32_emulation=1` (interactive) | `rhgb`, `ia32_emulation=1` (interactive) | KVM parameters for SEV-SNP/TDX hosts |
| scheduler | BORE; `scx_lavd` Gaming only on demand (`scxctl`) | `scx_lavd` PowerSave (provisional) | BORE |
| autogroup | on | on | off (interactive roles take priority) |
| power profile | `balanced` | `balanced` on AC, `power-saver` on battery | `performance` (priority over laptop) |
| memory and sleep | MGLRU `min_ttl_ms=1000`, `vm.max_map_count` high, `ntsync` (interactive) | interactive settings, `MemorySleepMode=`, ASPM `powersupersave` via tmpfiles | network buffers, `netdev_max_backlog`, busy polling (provisional) |
| other | `split_lock_mitigate=0`, `warn_limit=0` (interactive), SysRq emergency subset | interactive settings, Wi-Fi power saving | `sysrq=0`, `bpf_jit_harden=2`, `warn_limit=100` (D19), attested mode required |
| IPE policy class | desktop (section 10) | desktop | mesh |

**Mesh node on a desktop** (D11). The host keeps the desktop role; `athanor-role add mesh`
on a machine that also holds desktop or laptop provisions a MicroVM running the Azoth
guest kernel (`forge/specs/azoth/microvm`) with the mesh policy. On hosts with SEV-SNP or
TDX the guest is isolated from the host; elsewhere its attestation requires the host to
be attested as well.

**Assignment.** Roles are chosen at installation (a kickstart variable) and changed with
`athanor-role add|remove`, which installs or removes signed addons, refuses the mesh
role when the machine is not attested, and states when a reboot is needed. IPE allows a
single active policy, so a signed policy is generated at build time for every allowed
role combination.

## 8. Image, boot and updates

**Disk layout** (installation creates it): ESP 2 GiB (vfat), `/usr` A and B partitions
with their verity and verity-signature partitions, root and data on btrfs inside LUKS
(`/`, `/var`, `/home` subvolumes). Slot size is fixed at installation and sized from the
largest expected image with margin; P4b measures it.

**Image build.** The existing OCI build (GitHub Actions, dnf5, tier repositories, cosign,
SBOM) stays the source of the root filesystem and of provenance. A new stage exports the
rootfs and produces with `systemd-repart` a `/usr` image (EROFS, reproducible:
fixed timestamps, stable file order, compression per block) with its verity and signed
root hash partitions, and a UKI with `ukify` (`usrhash=`, base command line, signed
PCR 11 policy, SBAT). Role addons are built with `ukify` and the addon stub.

**Minimal initramfs** (D17): storage, LUKS, btrfs and dm-verity only; GPU, network and
everything else load after switch-root. The `bcachefs` userspace tools leave the image.

**Boot counting.** UKIs are installed with three tries (`+3`). `boot-complete.target`
requires `athanor-profile-check` and the critical services; `systemd-bless-boot`
marks a good boot; after three failed boots, panic reboots included, systemd-boot falls
back to the previous UKI and slot.

**Updates.** `systemd-sysupdate` owns versions, A/B slots and UKI installation.
Transport with deltas (D7):

1. The build publishes, per release, the `/usr` image chunked by `desync make` into an
   HTTPS chunk store (its hosting is decision D22, taken in P4b from the measured delta sizes, chunk counts
   and expected traffic),
   the index `.caibx`, and a manifest signed with the integrity key.
2. `athanor-update-fetch` verifies manifest and index signatures, runs `desync extract`
   seeded from the running `/usr` slot and earlier downloads, and verifies the assembled
   image twice: SHA-256 against the signed manifest and `veritysetup verify` with the
   root hash signature.
3. Only then `systemd-sysupdate` installs it from a local `regular-file` source (which
   by itself performs no verification, hence step 2) into the inactive slot, with its UKI and the addons of the active roles taken from the
   new image (D21). Verification and installation run in the same service over a staging
   directory accessible only to root, so the verified image cannot be replaced before it
   is written.
4. If the chunk store is unreachable, `systemd-sysupdate` downloads the full image from
   its `url-file` source, authenticated by `SHA256SUMS.gpg`.

**Prerequisite.** systemd ≥ 261 (`systemd-sysupdate` out of experimental,
`RestrictFileSystemAccess=`): Fedora 45 ships systemd 262. Rebasing from Fedora 43 is
block P4a.

## 9. Keys, measurements and attestation

| Key | Signs | Trusted by |
| --- | --- | --- |
| Secure Boot (`SECUREBOOT_SIGNING_KEY`) | systemd-boot, UKIs, role addons, PCR 11 policy | shim via MokList |
| Module signing (`MODULE_SIGNING_KEY`) | external kernel modules (NVIDIA) | kernel, compiled-in certificate |
| Integrity (new) | `/usr` verity root hashes, IPE policies, update manifests and indices | kernel, compiled-in certificate |

The integrity key signs both root hashes and IPE policies because both decide which code
may run. Revocation: the SBAT generation in UKIs and addons (`athanor,N`,
`uki-addon`) makes older images unbootable after a security fix; `keys/revoked/` covers
compiled-in certificates; MokListX covers the Secure Boot key.

**Measurements:** PCR 7 (Secure Boot state and certificates), PCR 11 (UKI sections,
including `usrhash=`), PCR 12 (command line and role addons), PCR 14 (shim MOK state),
PCR 15 (machine identity, LUKS), IMA log (code executed from writable areas).

**LUKS:** TPM 2.0 policy on PCR 7, the signed PCR 11 policy and PCR 14; never PCR 12, so
role changes do not require resealing. A recovery key is always enrolled; without a TPM,
a passphrase.

**Attestation** (restricted area): mesh node admission requires the PQC identity and a
verified TPM quote through Keylime. Keylime's example policy ignores PCR 12, so a
dedicated measured-boot policy accepts the command line events of the allowed role sets.

## 10. Execution integrity and security primitives

**IPE policies** (D8). The boot policy compiled into the kernel sets
`DEFAULT action=DENY` for every operation and admits only `boot_verified=TRUE`
(initramfs) and `dmverity_signature=TRUE`. Nothing outside `/usr` can therefore execute,
load as a module or firmware, or be kexec'ed before userspace activates the signed
runtime policy of the machine's role combination. That activation happens from `/usr`
early in boot, before any unit that executes code from a writable area; a machine whose
role policy fails to load stays under the boot policy and fails its health check.

- **Mesh class:** `DEFAULT action=DENY` for `EXECUTE`, `KMODULE`, `FIRMWARE`, `KEXEC_*`,
  `POLICY`; allowed only `dmverity_signature=TRUE` and `boot_verified=TRUE`. Containers run
  from signed dm-verity volumes. No JIT.
- **Desktop class:** enforcement on `KMODULE`, `FIRMWARE`, `KEXEC_*`, `POLICY`;
  `EXECUTE` allowed, because browsers and Mesa need JIT. Code in the home runs
  and is measured by IMA (D23). `noexec` covers the places where nothing legitimate is
  executed: `/tmp`, `/var/tmp`, `/dev/shm`, `/run/user`, removable media, and a dedicated
  btrfs subvolume bound to each user's `~/Downloads`; `noexec` also blocks executable
  `mmap` there. SELinux denies `execmem` to system and Athanor service domains except those
  declared; user applications stay in `unconfined_t` as in Fedora (D24).
- **Rollout:** every policy runs in audit mode in acceptance and on the maintainer's
  machine before enforcement; enforcement is gated (P6).

**Gatekeeper** (restricted area): leaves the blocking path (`FAN_OPEN_EXEC_PERM`), where a
hung daemon blocks the system and a dead one disables protection; it may remain an audit
consumer. Its new specification is written separately and approved before any change.
No custom BPF LSM is written. `RestrictFileSystemAccess=` (systemd ≥ 261) is available
as a per-service second layer.

**Application self-confinement:** Landlock (ABI 9 on this kernel) is a platform rule;
Athanor applications declare filesystem, network and IPC access through a shared crate
`athanor-sandbox` over the `landlock` crate. Services also use systemd sandboxing.

**eBPF without root:** unprivileged BPF stays off. Services receive BPF tokens with
`PrivateBPF=yes` and comma-separated delegation lists, for example
`BPFDelegateCommands=BPFMapCreate,BPFProgLoad,BPFTokenCreate`,
`BPFDelegateMaps=BPFMapTypeXskmap`, `BPFDelegatePrograms=BPFProgTypeXdp`,
`BPFDelegateAttachments=BPFXdp` (syntax verified with systemd 258).

**io_uring:** disabled except for services given the `athanor-io-uring` group.

**User namespaces:** available (Flatpak, rootless podman, browser sandboxes). Creation is
restricted per domain through SELinux once the loaded policy exposes the `userns_create`
capability (absent today); until then, services set `RestrictNamespaces=`, and the mesh
role limits `user.max_user_namespaces` to what its container runtime needs.

**Network:** per-service `IPAddressAllow=`/`IPAddressDeny=`, `RestrictNetworkInterfaces=`,
`SocketBindAllow=`, and host nftables. Tetragon leaves the image.

**Residual risks, stated:** a script passed to a verified interpreter escapes IPE
(no widespread interpreter uses `AT_EXECVE_CHECK` yet); JIT remains allowed on the
desktop class; IPE has almost no production experience in enforcement; Linux has no
hypervisor-isolated code integrity comparable to Windows HVCI or Apple's page protection.

## 11. Reliability

A panic reboots after 10 seconds; three failed boots fall back to the previous slot;
repeated oops or warnings become a panic (`oops_limit`, `warn_limit`). Crash evidence
comes from pstore archived by `systemd-pstore`, the persistent journal and
`DRM_PANIC` with its QR code. There is no kdump.

## 12. Verification

1. **CI, no VM:** the `profile.toml` validator over every role combination;
   `check_delta` on the kernel configuration (existing).
2. **Kernel boot matrix** (`forge/specs/azoth/boot.sh`): CPU model Haswell instead of
   Nehalem; new assertions for forced lockdown, preemption mode, IOMMU domain type,
   ASLR bits, compiled-in certificates (existing), IPE boot policy active; under Secure
   Boot an unsigned addon must be rejected.
3. **ISO acceptance** (`forge/test/iso`): a required `profile-ok` marker emitted by
   `athanor-profile-check`, whose failure report lists the drifting settings. The desktop
   role runs on every acceptance; laptop and desktop+mesh combinations in the weekly run.
4. **On the machine:** `athanor-profile-check` gates `boot-complete.target` and checks
   `/proc/config.gz`, `/proc/cmdline`, sysctls, `scx_loader` state, integrity mode, and
   that the roles applied under `/run` match the role addons in the PCR 12 event log.
5. **Attestation** of mesh nodes (restricted area).

## 13. Benchmarks and provisional decisions

Last phase, on the target hardware and not in a VM: latency (`schbench`, `cyclictest`),
throughput (`hackbench`, kernel compilation, `fio`), network (`netperf`, then AF_XDP).
At least ten runs per configuration, reported as median and dispersion. The results
close D13 (preemption), D14 (ISA level), D16 (IOMMU strict cost), the costs of
`KSTACK_ERASE` and `INIT_ON_FREE`, zram swappiness, `scx_lavd` PowerSave against BORE
with `power-saver` on battery, THP, and the mesh network settings. AutoFDO and
Propeller profiles are collected with representative workloads and committed with their
hashes. A setting that costs too much is recorded as a decision, never silently removed.

## 14. Outside the profile, tracked

- `athanor-timewarp` and `athanor-backup-hourly` target bcachefs, which left mainline in
  Linux 6.18: they are ported to btrfs subvolume snapshots.
- `cosmic-panel.service` memory limits (`MemoryHigh=1G`) kill the panel under normal use;
  they are fixed with the reinstallation while COSMIC remains the temporary desktop.
- `athanor-ebpf-sched` (contains an AI model contradicting `doc_kernel_layer.md`) is
  retired as a scheduler; `athanor-tetragon` leaves the image.
- `ermete-base-config`, the package from before the rename, is still installed next to
  `athanor-base-config` and duplicates files such as the `scx_loader` drop-in:
  `athanor-base-config` declares `Obsoletes: ermete-base-config` (P3).
- `athanor-journal-seal.service` fails on every boot because Fedora's systemd is built
  without forward-secure sealing: the unit leaves the image (P3); tamper evidence for logs
  is a separate decision.
- `athanor-tpm-luks-seal.sh` has a syntax error (`|| {` after `fi`) and binds LUKS to
  PCRs this profile rejects: it is replaced by the LUKS policy of section 9 (P4b).
- `system/athanor-install.ks` still appends the obsolete kernel command line
  (`iommu=pt`, `pti=on`, `zswap.enabled=1`, ...): it is removed with the command line
  cleanup (P3).
- The zero-trust services shipped disabled (`athanor-gatekeeper-rs`, `athanor-daemon`,
  `athanor-secure-boot`, the TPM rollback units) are reviewed in a dedicated session;
  the Gatekeeper and attestation are restricted areas.
- The userland build flags in `forge/config/rpmmacros` include `-mlam=u48`, an
  Intel-only feature, on an AMD-first baseline: reviewed with the Forge pipeline.
- `MOK_PRIVATE_KEY` is deleted from the `signing` environment once a deployed system
  loads `nvidia` signed by the module signing key (signing key rotation plan, task 9).

## 15. Implementation blocks

A new "BLOCCO P" in `NEXT.md`; no block starts before the previous gate is green. Pull
request #24 (signing key rotation) was merged on 2026-09-14, which unblocks P2.

| Block | Content | Gate |
| --- | --- | --- |
| P0 | this specification | maintainer approval |
| P1 | `profile.toml`, validator, `athanor-profile-check` covering settings already in force; later blocks extend it | acceptance with `profile-ok` |
| P2 | kernel build profile (section 5), boot matrix on Haswell with new assertions | Kernel gate green |
| P3 | `athanor-kernel-profile` base package, removal of old `kargs.d` and `99-bore.conf`, zram, BORE defaults, retirements of section 14 | acceptance `profile-ok`, desktop role |
| P4a | rebase on Fedora 45 (systemd 262), starting on the beta as soon as P3 is green (D25) | full DAG, image and acceptance green; the reinstall image waits for the final release |
| P4b | spike in a VM, then dm-verity images, systemd-boot, boot counting, sysupdate with desync deltas, integrity key (generated offline by the maintainer), minimal initramfs, ESP 2 GiB | in a VM with Secure Boot and swtpm: attested mode, fallback proven with a deliberately failing health check, update applied as a delta and verified, delta size measured on two consecutive images |
| P5 | roles, addons, generator, composition and precedence, `athanor-role`, mesh in MicroVM on desktops | validator over every combination; acceptance desktop and desktop+mesh |
| P6 | IPE policies in audit then enforce, `noexec` layout (D23), SELinux `execmem` restrictions on system and Athanor domains (D24), BPF token delegation, io_uring group, `athanor-sandbox` crate | negative tests: unverified execution denied in the mesh class, execution from `/tmp` and `~/Downloads` denied in the desktop class, module outside dm-verity refused |
| P7 | benchmarks, AutoFDO and Propeller, closing the provisional decisions | decision record closed, report |

After P5 is green in a VM: backup of `/var/home` and reinstallation of the maintainer's
desktop on the new image.

## 16. Sources

Verified during the design (2026-09-13/14):

- Kernel: `init/Kconfig` (`RUST` dependencies), `arch/Kconfig` (`AUTOFDO_CLANG`,
  `PROPELLER_CLANG`), `certs/Kconfig`, `certs/blacklist.c`, `security/ipe/*`,
  `Documentation/admin-guide/LSM/ipe.rst`, `fs/verity/measure.c`,
  `fs/bpf_fs_kfuncs.c`; commits f2c61db29f27 (bcachefs removal), 0c8c88b8eb82
  (overlayfs verity fix, contained in v7.1); running configuration of Azoth 7.1.8.
- systemd v258 sources: `man/systemd-stub.xml`, `man/systemd-boot.xml`,
  `man/sysupdate.d.xml`, `man/systemd.exec.xml`, `src/core/namespace.c`,
  `src/sysext/sysext.c`, `units/systemd-confext-initrd.service`,
  `docs/TPM2_PCR_MEASUREMENTS.md`; systemd v261 release notes; Fedora systemd versions
  (F43 258.10, F44 259.x, F45 262~rc1).
- bootc: `docs/src/experimental-composefs.md`, `bootloaders.md`,
  `boot-failure-detection.md`, issues #7, #1976, #2079, #2174; composefs issue #360.
- desync README and releases (v1.1.3); RAUC advanced documentation; CachyOS
  `linux-cachyos/PKGBUILD` and `kernel-patches` at the pinned commits.
- Keylime measured boot documentation; Azure Linux OS Guard documentation;
  kernel-hardening-checker run on the installed system (214 OK, 152 FAIL, reviewed).

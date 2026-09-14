# Athanor OS: Kernel and Platform Profile

Status: **draft for maintainer review, revision 2 (2026-09-14).** Revision 2 folds in a
second full audit (kernel, boot and updates, security, mesh and strategy, spec against the
running system) and the maintainer's decisions taken after it. This document is the
definitive profile of the Athanor kernel and of the platform layer that makes its
guarantees real: what the kernel is, how it boots, how its integrity is proven, how
machine roles compose, and how every property is verified. It supersedes sections 4
(config), 6 (signing and boot chain), 11 (outside the kernel) and 13 (maintainer
decisions) of [doc_kernel_build.md](doc_kernel_build.md), which remains the specification
of *how the kernel is built, pinned, published and maintained*.

The profile is definitive in one precise sense: every property below is recorded as a
decision with its rationale, every build and every installed machine is checked against
it, and it changes only through a new written decision. Upstream moves, so the profile is
re-verified at every kernel bump; it is not frozen.

**What exists today.** Almost nothing of sections 5 to 13 is implemented: the running
system still carries the previous configuration (section 14). What is real is the Azoth
kernel pipeline (Fedora and CachyOS merge, clang, kCFI, Rust, BORE, boot matrix), the
split of the Secure Boot and module signing keys with the module certificate compiled
into the kernel, module verification restricted to the kernel's own keyrings
(`patches/redhat/0001`), and the self-hosted KVM runner. Section 15 turns the rest into
gated blocks.

## 1. Goals and constraints

- A single kernel binary for every machine, on par with or above competing distributions
  and with macOS and Windows on integrity, where Linux makes that possible; where it does
  not, the gap is stated (section 10).
- Full control of the kernel as a platform for purpose-built Athanor applications, built
  on stable kernel interfaces rather than a deeper fork.
- Maximum technical level with minimum maintenance: upstream mechanisms over custom code,
  every gate fails loudly, the system maintains itself. The scope of each release is
  sized for one maintainer (D36).
- Designed for everyone: features are defined by capability tiers detected at runtime,
  never by one hardware configuration. The userland requires x86-64-v3 and the installer
  enforces it; the kernel itself stays bootable on any x86-64 CPU so that an unsupported
  machine gets a clear message (D14).
- The integrity chain (UEFI Secure Boot, TPM 2.0) is optional per machine, with a
  declared degraded mode (section 4).
- Updates never force a reboot: the user decides when a system update takes effect
  (section 8).
- Roles: desktop, laptop, mesh node; a machine may hold several. The mesh is personal:
  it joins the devices of one owner, and it comes after release 1.0 (D26, D38).
- Areas that require explicit maintainer approval before any code change remain so:
  the Gatekeeper (`forge/specs/athanor-gatekeeper-rs`), attestation
  (`system/confidential_computing/athanor-attestation`) and
  `system/athanor-bus-api/src/polkit.rs`. This document fixes requirements and kernel
  primitives for them, not their code.

## 2. Decision record

States: **final**; **provisional** (a default, closed by the benchmarks of section 13);
**open** (closed by the named spike or block); **after 1.0** (kept as the target, outside
the release 1.0 scope of D36); **superseded** (replaced by the named decision).

| ID | Decision | Rationale | State |
| --- | --- | --- | --- |
| D1 | One kernel binary; roles are runtime profiles | one build, one signature, simple attestation | final |
| D2 | Roles compose; a machine holds zero or more | a workstation can also be a mesh node | final |
| D3 | Userland baseline x86-64-v3, enforced by the installer; integrity chain optional with declared degraded mode | matches the v3 userland; keeps machines without TPM/SB installable | final |
| D4 | Rust enabled; performance from AutoFDO; ThinLTO re-checked at every bump; Propeller deferred until profiling runs automatically on more than one CPU vendor | `RUST` still depends on `!DEBUG_INFO_BTF \|\| (PAHOLE_HAS_LANG_EXCLUDE && !LTO)`; AutoFDO and Propeller do not require LTO; a Propeller profile is bound to one binary and one test machine's workload | final |
| D5 | BORE is the base scheduler; sched_ext only through `scx_loader` as a role setting; `athanor-ebpf-sched` retired as a scheduler. If the BORE patch does not apply to a bump required by D37, the kernel ships on plain EEVDF rather than waiting | one owner; sched_ext falls back to the fair class; an out-of-tree patch must never delay a security bump | provisional (BORE against plain EEVDF in P7) |
| D6 | The verified image and A/B update mechanism: either `/usr` on dm-verity with a signed root hash, A/B slots with `systemd-sysupdate` and UKI boot with systemd-boot, or bootc with sealed composefs and UKI | the audit found that the first option leaves `/etc` unspecified, depends on a `systemd-sysupdate` marked experimental again in systemd 262, and makes Athanor maintain its own update system; bootc's sealed composefs backend is close to stable and plans boot counting, but IPE cannot cover composefs | open (spike S1, no time box) |
| D7 | Delta updates by content-defined chunking, verified by the image signature | small downloads without weakening integrity | after 1.0 (D36); if S1 selects bootc, OCI layer pulls provide partial downloads first |
| D8 | IPE is the single in-kernel enforcer for code integrity on dm-verity images | upstream, compiled in, signed policies; a custom BPF LSM cannot see fs-verity through overlayfs; IPE's documentation positions it for fixed-function systems, so its full default-deny use is the mesh class, and the desktop class enforces only module, firmware, kexec and policy loading | final; its value depends on S1 (D6) |
| D9 | Role content ships inside the signed image; the active role set is a signed UKI addon per role | confext passed through the stub is unmerged at switch-root; addons are verified by shim and measured into PCR 12 | final; revisited if S1 selects bootc |
| D10 | Composition follows NixOS semantics: type-based merge, conflict is a build error resolved only by explicit priority | explicit, no silent resolution, proven model | final |
| D11 | On a desktop or laptop, the mesh node role runs inside a MicroVM | the services that matter (backup, inference, remote sessions) run on the host anyway, and on consumer CPUs without SEV-SNP or TDX the VM adds no trust | superseded by D38 |
| D12 | The mesh node role requires attested mode | a node that keeps its key but runs altered code must not stay a node | revised by D38: required for the host tier only |
| D13 | Preemption `lazy` as the base (Fedora's choice); `full` through a role addon (`preempt=full`, possible with `PREEMPT_DYNAMIC`) only if P7 measures a gain | x86 offers only FULL and LAZY; LAZY delays preemption of normal tasks by at most one tick; a boot parameter belongs to a role, not to the build | provisional |
| D14 | Kernel built with `X86_64_VERSION=1`; x86-64-v3 is enforced by the installer and the userland | the kernel is compiled without SSE and AVX, so a v3 kernel gains only integer extensions with no measurable effect, and it turns an unsupported CPU into a crash instead of a message | final |
| D15 | Swap on zram (zstd), zswap off; writeback of cold pages to an encrypted swap file evaluated for machines with 8 GiB or less | no double compression; swap on LUKS is encrypted, so disk swap is not excluded on security grounds, only on wear and latency | provisional (swappiness and writeback in P7) |
| D16 | IOMMU in lazy mode by default; external ports are forced into strict DMA domains by the kernel when firmware marks them untrusted, and acceptance verifies that marking; `iommu.strict=1` is available per role | the kernel already bounces untrusted devices; global strict only costs throughput on internal NVMe and NICs | provisional |
| D17 | Minimal generic initramfs (never host-only): storage (`nvme`, `vmd`, AHCI), `dm_crypt`, `dm_verity`, btrfs, and input for the LUKS passphrase (`i2c_hid_acpi`, USB HID); no GPU driver, so the passphrase prompt uses the firmware framebuffer. ESP of 2 GiB when Athanor owns the disk, an XBOOTLDR partition next to a smaller existing ESP otherwise | today's UKI carries 102 MB of initramfs; dual boot with a preinstalled Windows ESP of 100–260 MB must work | final |
| D18 | Laptop is an autonomous role; desktop and laptop share an `interactive` fragment of the manifest | a laptop without the desktop role keeps 32-bit, gaming and interactive settings, without duplicated definitions | final |
| D19 | `PANIC_ON_OOPS` stays off in the build; `kernel.panic_on_oops=1` and `kernel.warn_limit=100` on mesh nodes; `kernel.panic_on_oops=0` with `kernel.oops_limit=100` and `kernel.warn_limit=0` on interactive roles. Crash evidence comes from EFI pstore, enabled by policy and emptied by `systemd-pstore` | with `PANIC_ON_OOPS=y` the first oops panics before `oops_limit` is consulted, so a desktop would reboot and lose work at the first driver oops; without a pstore backend a panic leaves no record | final |
| D20 | SELinux `DEVELOP` and `BOOTPARAM` are switched off only after zero AVC denials in Athanor domains in acceptance; recovery from a denial that breaks the system after boot is the previous image in the boot menu, not `enforcing=0` | a gate that does not depend on upstream policy bugs, and a recovery path that survives the switch | final |
| D21 | Role addons are built and signed in CI and shipped inside the image; every update installs the addons of the active roles from the new image before the new boot entry becomes the default | roles and image can never diverge; no second distribution channel | final |
| D22 | Hosting of the delta chunk store | chosen from measured delta sizes, chunk counts and expected traffic | after 1.0 |
| D23 | Desktop class: no `noexec` on user-writable locations; code in the home runs and is measured by IMA; protection against downloaded executables is a desktop feature (a quarantine prompt), specified outside this profile | `noexec` on `/tmp`, removable media or `~/Downloads` is bypassed by passing the file to an interpreter and breaks `go test`, Java native libraries, PyInstaller and .NET single-file apps, Steam libraries on external drives and AppImages | final |
| D24 | SELinux denies `execmem` to system and Athanor service domains except those declared; user applications stay in `unconfined_t` as in Fedora | restricting user domains would break Electron, Java, .NET, Python ctypes and emulators, not only browsers | final |
| D25 | The Fedora 45 rebase starts on the beta as soon as P3 is green; the image that reinstalls the maintainer's desktop is built only on the final release (target 2026-10-20); any block that needs a systemd 262 feature waits for systemd 262 final in Fedora 45 updates | problems surface early, production waits for supported releases | final |
| D26 | The mesh is personal: its nodes are the devices of one owner. It provides a private network between them, synchronisation and backup, compute sharing and remote applications; it is not an update channel | the purposes the maintainer set; updates keep one signed source and one verification path | final purpose; delivery after 1.0 (D38) |
| D27 | The mesh subsystem has its own specification, a rewrite of `doc_cloud_mesh.md`; this profile holds only its kernel and platform requirements | protocol, identity, discovery and scheduling are not kernel decisions | final |
| D28 | Compute sharing by capability tiers: CPU workloads in MicroVMs; GPU inference through a signed host service; a GPU inside a guest with SR-IOV, a second GPU in its own IOMMU group, or virtio-gpu Venus for Linux guests | works on any machine; extra hardware unlocks more. Today SR-IOV exists on consumer hardware only for some Intel GPUs, and Venus only with QEMU, crosvm or libkrun | after 1.0; the GPU-in-guest tiers need hardware evidence before they are promised |
| D29 | Remote applications from interactive hosts, by tiers: a session on a virtual output with hardware encoding, applications of a Windows VM forwarded one by one, a 3D-accelerated VM where the hardware allows; the local session is never closed | usable across GPU vendors; the owner keeps working locally | after 1.0; blocked until the session compositor provides virtual outputs (COSMIC does not today) |
| D30 | Updates ship as a base image plus signed layers that apply without a reboot | most changes could apply without rebooting | after 1.0; redesign required (section 8) |
| D31 | Update classes: A applications, no interruption; B service layers, applied by restarting only their services; C the desktop layer, at the end of the session or at a soft reboot the user chooses; D the base, at a full reboot the user chooses and never forced; mesh-only nodes reboot in a maintenance window set by the owner | no forced reboots; each change costs only the interruption it needs | classes A and D in 1.0; B and C after 1.0 |
| D32 | A layer is trusted only when the kernel verifies its signature, under an image policy set from `/usr` that writable `/etc` cannot loosen | systemd's default image policy accepts unsigned images, and IPE sees `dmverity_signature=TRUE` only for signatures the kernel verified | after 1.0 |
| D33 | Channels stable and beta; a release is promoted from beta to stable as the same signed artefacts | stable runs, bit for bit, what beta tested | after 1.0 |
| D34 | Gradual rollout without telemetry: each machine derives its rollout day locally, a signed stop manifest halts a release, security releases skip the window | nothing leaves the machine by design; the download server still sees requests, so its logs follow a retention rule | after 1.0 |
| D35 | Rollback returns the base and every layer to the versions that belong together | a failure returns to a known pair, never to a mix; layers are selected by the booted base, not by the newest version | after 1.0 |
| D36 | Release 1.0 scope: verified A/B base image (D6), boot counting and automatic fallback, full-image system updates that take effect at a reboot the user chooses, applications through Flatpak, IPE in audit with enforcement of `KMODULE` and `FIRMWARE`. Deltas, layers, classes B and C, channels, gradual rollout and the mesh follow in later releases | the smallest release that is robust for everyone; the audit found the layer and rollout design unsafe as written | final |
| D37 | Kernel series: the stable channel, with a mandatory bump when the pinned series reaches end of life on kernel.org; the bump bot fails while it does, and `KERNEL_CHANNEL=lts` is the maintainer's fallback when no stable pair exists | a series without fixes must never stay pinned in silence, as 7.1 did after 2026-09-02 | final |
| D38 | The mesh has two tiers: attested hosts (backup, compute, remote sessions) and non-attested clients (phones, other operating systems, degraded machines) with limited keys. It composes upstream components (kernel WireGuard with an existing coordination server, Syncthing-class sync, btrfs send and receive) rather than new protocol code. No mesh code with placeholder cryptography or attestation ships | mandatory attestation for every device excludes phones and most ordinary machines; the existing mesh crates contain placeholder PQC keys and file-existence attestation | final; delivery after 1.0 |
| D39 | `/etc` is part of the update design: its handling across a rollback (factory defaults in `/usr` with `/etc` as a local overlay, or a per-slot `/etc`) is chosen with D6, before P4b | with A/B `/usr` and a shared `/etc`, a rollback would keep the newer configuration and SELinux policy | open (spike S1) |
| D40 | Keyrings: dm-verity root hashes and IPE policies are verified against the builtin keyring only; modules against the builtin and secondary keyrings; `SECONDARY_TRUSTED_KEYRING_SIGNED_BY_BUILTIN=y`. A CA enrolled in MokList with physical presence reaches the secondary keyring and can authorise user modules; attested mode requires that MokList holds only the project certificate | the platform keyring (UEFI db, non-CA MOKs) must not authorise code or policy; users keep a visible, physical path to their own modules | final |
| D41 | Anti-rollback: every manifest carries an expiry and a minimum version, enforced by the updater and by `athanor-profile-check`; revoking an integrity certificate through `SYSTEM_REVOCATION_KEYS` invalidates every image it signed. SBAT sections stay in UKIs and addons, but do not revoke: with Fedora's shim only shim publishes SBAT levels | the first draft claimed SBAT revocation that Athanor cannot issue; a replayed old manifest must not hide a security release | final |
| D42 | LUKS: TPM-only unlock only in attested mode; a degraded machine uses TPM plus PIN, or a passphrase. The seal is renewed after the Secure Boot certificate is enrolled and after db or dbx updates. The installer checks that the firmware trusts the certificate authority that signs the shipped shim | without Secure Boot the command line is measured only into PCR 12, which the policy excludes, so TPM-only unlock would release the key to a modified boot | final |
| D43 | The Secure Boot, integrity and update keys are used only in sign-only CI jobs that receive built artefacts, never in a job that runs third-party actions or the image build; the integrity key has its own environment with required reviewers | a compromised build step must not be able to sign | final |
| D44 | Root boundary: an Azoth patch makes IPE enforcement one-way once enforcing under lockdown; SELinux confines writes to IPE securityfs and SELinux policy loading to one domain | `CAP_MAC_ADMIN` alone can write `enforce=0` today, and an unconfined root can load policy modules | final; the patch is written in P6 |

## 3. Architecture overview

The chain below is the dm-verity option of D6; spike S1 compares it with bootc sealed
composefs, which keeps the firmware, shim, UKI and kernel levels and replaces `/usr` on
dm-verity with a composefs image verified by fs-verity.

```
firmware (UEFI CA)
  └─ shim (Fedora, Microsoft-signed)                      verifies with db + MokList
       └─ systemd-boot            signed: Secure Boot key  boot counting (+3)
            └─ UKI                signed: Secure Boot key  .cmdline (usrhash=, base params)
                 │                                          .pcrsig (signed PCR 11 policy)
                 ├─ /loader/addons/athanor-role-<r>.addon.efi   signed: Secure Boot key → PCR 12
                 └─ kernel (Azoth, IPE boot policy, module and integrity certificates compiled in)
                      └─ /usr: dm-verity, root hash signed with the integrity key
                           ├─ /usr/lib/athanor/roles/<r>/     role content
                           └─ athanor-roles generator → /run/{sysctl.d,modprobe.d,tmpfiles.d,systemd}
/etc: handling per D39
/ , /var, /home: btrfs on LUKS (TPM-only in attested mode, TPM+PIN or passphrase otherwise)
```

Four layers, one source of truth each:

1. **Kernel build profile**: `forge/specs/azoth/kernel-local` (section 5).
2. **Runtime base profile**: the package `forge/specs/athanor-kernel-profile`, which
   replaces the kernel-related files scattered today in `athanor-base-config` (`kargs.d`,
   `modprobe.d`, `scx_loader` drop-in, NVIDIA dracut configuration) and
   `athanor-system-tweaks` (`sysctl.d`) (section 6).
3. **Roles**: `athanor-kernel-profile/roles/<role>/`, installed under
   `/usr/lib/athanor/roles/<role>/`, activated by signed addons (section 7).
4. **Manifest**: `athanor-kernel-profile/profile.toml` declares every setting of the base
   and of each role with its type and priority; a repository script generates the files,
   validates every role combination and computes the expected effective profile that the
   drift checker enforces (sections 7 and 12).

## 4. Integrity modes

- **Attested**: Secure Boot on, MokList holding only the project Secure Boot certificate
  (D40), TPM 2.0 present, the signed PCR 11 policy valid, PCR 12 consistent with the
  declared role set. Required by the mesh host tier (D38) and by TPM-only disk unlock
  (D42).
- **Degraded** (declared "not attested"): anything missing. The UKI still boots and the
  image is still verified on every read. Without Secure Boot, systemd-stub accepts a
  command line from the boot loader and the UKI itself is not verified by firmware, so an
  attacker with physical access can replace them; the disk therefore needs a PIN or a
  passphrase (D42). `athanor-profile-check` reports the mode and the reasons.
- In degraded mode the role addons are not verified either: shim verifies them only
  under Secure Boot, so someone with physical access can add a forged addon such as
  `athanor.role=mesh`. Roles are therefore *declared*, not *proven*, on a degraded
  machine: `athanor-profile-check` reports them as declared, `athanor-role` never grants
  anything on the strength of the command line alone, and no trust decision (mesh
  admission, attestation, IPE policy class stronger than the one the machine actually
  enforces) may rest on a role that is not backed by attested mode.
- First boot starts degraded. A guided step imports the Secure Boot certificate
  (`mokutil --import`); the confirmation in MokManager is a human action by design. The
  next boot with Secure Boot on is attested, and the disk seal is renewed (D42).

## 5. Kernel build profile (`kernel-local`)

Principle: what holds for every role and must not be changeable at boot lives in the
build configuration; what a role or a compatibility case must change stays a boot
parameter, set by a signed addon. Items marked (P4b) or (P5) or (P6) depend on a later
block and are not part of P2.

**From the command line into the build:**
`LOCK_DOWN_KERNEL_FORCE_INTEGRITY=y`, `INIT_ON_FREE_DEFAULT_ON=y`, `LEGACY_VSYSCALL_NONE=y`,
`DEBUG_FS_ALLOW_NONE=y`, `PANIC_TIMEOUT=10`, `INTEL_IOMMU_DEFAULT_ON=y`,
`EFI_DISABLE_PCI_DMA=y` (its Kconfig warns about firmware that misbehaves: a signed
compatibility addon carries `efi=no_disable_early_pci_dma`, because users cannot edit a
signed command line).

**New hardening:** `KSTACK_ERASE=y`, `PAGE_TABLE_CHECK=y`, `PAGE_TABLE_CHECK_ENFORCED=y`,
`DEBUG_VIRTUAL=y`, `DEBUG_SG=y`, `DEBUG_NOTIFIERS=y`, `ARCH_MMAP_RND_BITS=32`,
`ARCH_MMAP_RND_COMPAT_BITS=16`, `PROC_MEM_FORCE_PTRACE=y`,
`SECONDARY_TRUSTED_KEYRING_SIGNED_BY_BUILTIN=y` (D40),
`IA32_EMULATION_DEFAULT_DISABLED=y` (P5, together with the addons of the interactive
roles that re-enable it, so 32-bit applications never break between blocks),
`SECURITY_SELINUX_DEVELOP` and `SECURITY_SELINUX_BOOTPARAM` off (P6, after the D20 gate).
Evaluated in P2 with their cost measured in P7: `UBSAN_TRAP`, `MSEAL_SYSTEM_MAPPINGS`
(hidden while `CHECKPOINT_RESTORE=y`), `PROC_KCORE` off, `BLK_DEV_WRITE_MOUNTED` off.

**Integrity** (D40): `DM_VERITY_VERIFY_ROOTHASH_SIG=y` and `SECURITY_IPE=y` with
`DM_VERITY_VERIFY_ROOTHASH_SIG_SECONDARY_KEYRING`, `DM_VERITY_VERIFY_ROOTHASH_SIG_PLATFORM_KEYRING`,
`IPE_POLICY_SIG_SECONDARY_KEYRING` and `IPE_POLICY_SIG_PLATFORM_KEYRING` all off, so root
hashes and policies verify against the builtin keyring only. The dm-verity signature code
falls back to the platform keyring on `-ENOKEY` and on `-EKEYREJECTED` when its option is
on. Module verification uses the builtin and secondary keyrings; the Red Hat fallback to
the platform keyring is removed by `patches/redhat/0001`. `SYSTEM_TRUSTED_KEYS` carries
the module signing certificate and, from P4b, the integrity certificate;
`SYSTEM_REVOCATION_KEYS` the retired ones. The kernel cannot restrict a builtin
certificate to one purpose, so the module and integrity keys are separated by custody
(D43), not by the kernel. From P4b: `DM_VERITY=y` (built in) and `IPE_BOOT_POLICY` set to
the compiled boot policy (section 10).

**Attack surface removed** (unused by every role): `KEXEC`, `KEXEC_FILE` (its signature
check also falls back to the platform keyring), `CRASH_DUMP`, `LIVEPATCH` (updates are
images), `HIBERNATION` (blocked by lockdown), `SECURITY_TOMOYO`, `X86_IOPL_IOPERM`.
`LSM="lockdown,yama,integrity,selinux,bpf,landlock,ipe"`.

**Kept on purpose:** `IA32_EMULATION` and `MODIFY_LDT_SYSCALL` (Steam, Wine), `MODULES`
(NVIDIA and user modules through D40), `BPF_LSM`, `KALLSYMS`, kprobes and ftrace (the
eBPF nerve, observability), `IMA_ARCH_POLICY` (attestation), `ZRAM` with
`ZRAM_WRITEBACK`, `PREEMPT_DYNAMIC`, `INTEGRITY_MACHINE_KEYRING` with
`INTEGRITY_CA_MACHINE_KEYRING_MAX` (D40).

**Rejected:** `PANIC_ON_OOPS` (D19), `IOMMU_DEFAULT_DMA_STRICT` (D16),
`STATIC_USERMODEHELPER` (modprobe and the coredump pipe need helpers),
`RESET_ATTACK_MITIGATION` (without userspace support the firmware wipes RAM at every
boot), `TRIM_UNUSED_KSYMS` (breaks the NVIDIA modules), `RANDSTRUCT` (excluded by Rust),
`SECURITY_LOADPIN` (IPE covers `KMODULE` and `FIRMWARE`).

**Codegen:** `RUST=y`, `AUTOFDO_CLANG=y` (profiles arrive in P7), `X86_64_VERSION=1`
(D14), preemption `lazy` (D13).

## 6. Runtime base profile

**Kernel command line.** Nearly empty: only what installation knows (LUKS device, root),
`usrhash=` from the image build, and `efi_pstore.pstore_disable=0` (D19). Removed from
today's `kargs.d` and kickstart: `slab_nomerge`, `randomize_kstack_offset`, `ima_hash`
(already defaults), `pti=on` (forces page table isolation on CPUs not affected by
Meltdown), `iommu=pt`, `amd_iommu=on` (not a valid option), `lam=on`, `arm64.mte=on`
(unknown to this kernel), `mem_encrypt=on` and `kvm_intel.tdx=1` (capability-specific,
never global), `zswap.enabled=1`, `module.sig_enforce`, `lockdown`, `init_on_free`,
`vsyscall`, `debugfs`, `oops` (moved into the build or into roles). NVIDIA parameters and
dracut configuration move out of the base: they apply only where an NVIDIA GPU is
detected. `ima_policy=tcb` is replaced by a signed IMA policy that measures code executed
from writable areas: under Secure Boot the architecture policy requires a signed policy
(`appraise func=POLICY_CHECK appraise_type=imasig`), and its signing path is defined in
P4b.

**sysctl (base, locked):** `kernel.yama.ptrace_scope=1`, `kernel.kptr_restrict=2`,
`kernel.dmesg_restrict=1`, `dev.tty.ldisc_autoload=0`, `fs.protected_fifos=2`,
`fs.protected_regular=2`, `fs.suid_dumpable=0`, `kernel.oops_limit=100`,
`kernel.io_uring_disabled=1` with `kernel.io_uring_group` set to the `athanor-io-uring`
group, `net.core.default_qdisc=fq`, `kernel.sysrq=176` (sync, remount read-only, reboot).
The TCP congestion control is not set, so the kernel default BBRv3 applies.
`athanor-system-tweaks/.../99-bore.conf` is removed with its CFS tunables that no longer
exist under EEVDF and its override to BBRv1. KSM stays off unless a role declares it.

**Scheduler:** EEVDF with BORE at the defaults of the pinned patch, `HZ=1000`.

**Memory:** zram swap with zstd (`zram-size = min(ram / 2, 8192)`), MGLRU on, THP
`madvise` with defrag `defer+madvise`.

**Power:** power-profiles-daemon is the only owner of EPP and platform profile; the CPU
vendor's driver in active mode (`amd_pstate` or `intel_pstate`).

## 7. Roles

**Content.** Each role is a directory in the signed image,
`/usr/lib/athanor/roles/<role>/`, holding `sysctl.d`, `modprobe.d`, `tmpfiles.d`,
`systemd` units and drop-ins, `power-profiles-daemon` and `scx_loader` configuration.
It is protected by the image verification like the rest of `/usr` and updated atomically
with the OS.

**Activation.** A role is active when its signed addon
`/loader/addons/athanor-role-<role>.addon.efi` exists. The addon carries
`athanor.role=<role>` and the role's kernel parameters, has no `.uname` section so it
survives kernel updates, is verified through shim, and is measured into PCR 12 together
with the other command line fragments. Addons are built and signed in CI and shipped
inside the image as `/usr/lib/athanor/roles/<role>/athanor-role-<role>.addon.efi`;
`athanor-role` copies the addons of the chosen roles to the ESP, and every update
installs them from the new image before its boot entry becomes the default (D21).
Compatibility addons (for example `efi=no_disable_early_pci_dma`) follow the same
mechanism.

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
`split_lock_mitigate=0`, `panic_on_oops=0`, `warn_limit=0`), so the laptop stands alone
without duplicating the desktop (D18).

**Roles:**

| Setting | Desktop | Laptop | Mesh node (mesh-only host) |
| --- | --- | --- | --- |
| addon parameters | `rhgb`, `ia32_emulation=1` (interactive) | `rhgb`, `ia32_emulation=1` (interactive) | none in 1.0; confidential-computing parameters are defined by the mesh specification |
| scheduler | BORE; `scx_lavd` Gaming only on demand (`scxctl`) | `scx_lavd` PowerSave (provisional, P7) | BORE |
| autogroup | on | on | off |
| power profile | `balanced` | `balanced` on AC, `power-saver` on battery | `performance` |
| memory and sleep | MGLRU `min_ttl_ms=1000`, `vm.max_map_count=1048576`, `ntsync` (interactive) | interactive settings; suspend mode and ASPM left to the firmware defaults unless P7 measures a gain | network buffers `net.core.rmem_max` and `wmem_max` 16 MiB, `netdev_max_backlog=16384` (provisional, P7) |
| other | `split_lock_mitigate=0`, `panic_on_oops=0`, `warn_limit=0` (interactive) | interactive settings, Wi-Fi power saving | `sysrq=0`, `bpf_jit_harden=2`, `panic_on_oops=1`, `warn_limit=100` (D19), attested mode required |
| IPE policy class | desktop (section 10) | desktop | mesh |

A machine holding both an interactive role and the mesh role is a host of the mesh
(D38); the composition of their settings is defined with the mesh specification (D27),
and the validator rejects the combination until then.

**Purpose of the mesh** (D26, D38; after 1.0). The mesh joins the devices of one owner:
a private network over kernel WireGuard with an existing coordination server;
synchronisation and backup between nodes (Syncthing-class sync, btrfs send and receive);
compute sharing by capability tier (D28); remote applications from interactive hosts
(D29). Attested hosts hold data and run workloads; clients (phones, other systems,
degraded machines) connect with limited keys. The mesh never distributes updates.
Protocol, identity, discovery and scheduling belong to the mesh specification (D27).

**Platform requirements of the mesh**, enabled in the kernel today and asserted by the
boot matrix from P2: WireGuard, KVM (AMD and Intel), vhost-vsock, virtio-fs, virtio-gpu
with `udmabuf`, VFIO for the optional GPU tier, and the TPM and attestation chain of
section 9. The virtual machine monitor is chosen once, in the mesh specification.

**Assignment.** Roles are chosen at installation (a kickstart variable) and changed with
`athanor-role add|remove`, which installs or removes signed addons, refuses the mesh
role when the machine is not attested, and states when a reboot is needed. IPE allows a
single active policy, so a signed policy is generated at build time for every allowed
role combination.

## 8. Image, boot and updates

**Disk layout** (installation creates it): ESP of 2 GiB when Athanor owns the disk, or
XBOOTLDR next to an existing ESP (D17); the image slots per D6; root and data on btrfs
inside LUKS (`/`, `/var`, `/home` subvolumes); `/etc` per D39. Slot size is fixed at
installation and sized from the largest expected image with margin; P4b measures it.

**Image build.** The existing OCI build (GitHub Actions, dnf5, tier repositories, cosign,
SBOM) stays the source of the root filesystem and of provenance. For the dm-verity
option a new stage produces with `systemd-repart` a `/usr` image (EROFS, reproducible:
fixed timestamps, stable file order, compression per block) with its verity and signed
root hash partitions; for either option a UKI is built with `ukify` (`usrhash=` or the
composefs digest, base command line, signed PCR 11 policy, SBAT section) and role addons
with the addon stub. Signing happens only in sign-only jobs (D43).

**Minimal initramfs** (D17): generic, never host-only. The `bcachefs` userspace tools
leave the image.

**Boot counting.** UKIs are installed with three tries (`+3`). `boot-complete.target`
requires `athanor-profile-check` and the critical services; `systemd-bless-boot` marks a
good boot; after three failed boots, panic reboots included, systemd-boot falls back to
the previous UKI and slot.

**Release 1.0 updates** (D31 classes A and D, D36, D41):

1. Applications update through Flatpak with no interruption (class A).
2. A system update is a full image. It is downloaded and verified in the background:
   manifest signature, expiry and minimum version (D41), then the image signature. With
   the dm-verity option, `systemd-sysupdate` installs from a local verified copy into the
   inactive slot, because its `regular-file` source performs no verification itself;
   verification and installation run in one root-only service over a staging directory,
   so the verified image cannot be replaced before it is written.
3. The new boot entry becomes the default only when the user confirms, so an unrelated
   reboot or a crash never applies an update the user has not accepted; the boot menu
   also offers the previous version for one boot. Nothing reboots by itself (class D).
4. If the new version fails its health check three times, the machine returns to the
   previous one.

**After 1.0: the target update model** (D7, D30–D35). Kept as the goal, redesigned before
implementation because the audit found the first version unsafe:

- **Deltas** (D7, D22): content-defined chunks seeded from the running image, verified
  by the image signature; or, if S1 selects bootc, OCI layer pulls.
- **Layers** (D30, D32): a global `systemd-sysext refresh` unmerges and remounts every
  layer at once, with a moment where no overlay is mounted, so a service update would
  also apply a staged desktop layer mid-session. Service layers therefore attach to
  their own units (`ExtensionImages=` or portable services) and restart alone; the
  desktop layer merges only at boot or at a soft reboot. The image policy comes from
  `/usr`, not from writable `/etc`. `systemd-sysupdate-notify-sysext` stays disabled.
- **Selection and rollback** (D35): layers are stored per base version and selected from
  the booted base (its root hash), not from `SYSEXT_LEVEL` alone, which would only skip a
  mismatching layer.
- **Measurement:** the verity NvPCR exists from systemd 260; from 262 its definitions ship
  inside the UKI, which then needs signed initrd-phase PCR policies.
- **Interface:** the update interface is built on the Varlink API of `systemd-sysupdate`
  itself; the D-Bus API of `systemd-sysupdated` is being removed.
- **Channels and rollout** (D33, D34): signed channel manifests with expiry; rollout day
  from an application-specific identifier derived from `machine-id` and the release
  version; a signed stop manifest; security releases skip the window.

**Prerequisites.** `systemd-sysupdate` was marked experimental again in systemd 262
("more breaking changes are forthcoming"); the dm-verity option of D6 depends on it
becoming stable, which S1 weighs. `RestrictFileSystemAccess=` (systemd 261) denies
execution from overlayfs on kernels older than 7.2. Fedora 45 carries systemd 262 release
candidates today (D25).

## 9. Keys, measurements and attestation

| Key | Signs | Trusted by | Custody |
| --- | --- | --- | --- |
| Secure Boot (`SECUREBOOT_SIGNING_KEY`) | systemd-boot, UKIs, role and compatibility addons, PCR 11 policy | shim via MokList | `signing` environment, sign-only job (D43) |
| Module signing (`MODULE_SIGNING_KEY`) | external kernel modules (NVIDIA) | kernel, builtin certificate | `signing` environment, sign-only job |
| Integrity (new, P4b) | image root hashes, IPE policies, the IMA policy, update and channel manifests | kernel, builtin certificate | own environment with required reviewers (D43) |
| Update (new, P4b, OpenPGP) | `SHA256SUMS` of the full-image source of `systemd-sysupdate` | the keyring shipped in the image | as the integrity key |

The integrity key signs root hashes and policies because both decide which code may run.
**Revocation and rollback** (D41): `keys/revoked/` covers compiled-in certificates, and
revoking an integrity certificate invalidates every image it signed; MokListX covers the
Secure Boot key; manifests carry an expiry and a minimum version. SBAT sections are kept
because shim requires them, not as an Athanor revocation mechanism.

**Measurements:** PCR 7 (Secure Boot state and certificates), PCR 11 (UKI sections,
including `usrhash=`), PCR 12 (command line and addons), PCR 14 (shim MOK state),
PCR 15 (machine identity, LUKS), the verity NvPCR (after 1.0, with layers), IMA log
(code executed from writable areas).

**LUKS** (D42): in attested mode, TPM 2.0 policy on PCR 7, the signed PCR 11 policy and
PCR 14, never PCR 12, so role changes do not require resealing; in degraded mode TPM plus
PIN, or a passphrase. The PCR 11 policy is signed for the initrd phase only, so a running
system cannot unseal the disk key again. A recovery key is always enrolled. The seal is
renewed after MOK enrolment and after firmware db or dbx updates.

**Attestation** (restricted area): admission of a mesh host requires its identity and a
verified TPM quote (D38). Keylime's example measured-boot policy considers PCRs 0–9 and
14 only, so a dedicated policy covers PCR 11 and the command line events of the allowed
role sets in PCR 12. The attestation code in the repository today returns fixed results
and quotes the wrong PCRs; it is replaced, with the maintainer's approval, before any
mesh admission depends on it.

## 10. Execution integrity and security primitives

**IPE policies** (D8). The boot policy compiled into the kernel (from P4b) sets
`DEFAULT action=DENY` for every operation and admits only `boot_verified=TRUE`
(initramfs) and `dmverity_signature=TRUE`. Nothing outside the verified image can
therefore execute, load as a module or firmware, or be kexec'ed before userspace
activates the signed runtime policy of the machine's role combination. That activation
happens from `/usr` early in boot, before any unit that executes code from a writable
area; a machine whose role policy fails to load stays under the boot policy and fails its
health check. IPE evaluates the real inode under overlayfs, so signatures stay visible
under later layers.

- **Mesh class:** `DEFAULT action=DENY` for `EXECUTE`, `KMODULE`, `FIRMWARE`, `KEXEC_*`,
  `POLICY`; allowed only `dmverity_signature=TRUE` and `boot_verified=TRUE`. Anonymous
  executable memory is denied as well, so no user-space JIT runs on the host; workloads
  of other nodes run in virtual machines. The BPF JIT is a kernel component and stays on
  with `bpf_jit_harden=2`.
- **Desktop class:** enforcement on `KMODULE`, `FIRMWARE`, `KEXEC_*`, `POLICY`;
  `EXECUTE` allowed, because browsers, Mesa and development tools need it. Code in the
  home runs and is measured by IMA (D23). A module outside the image loads only if it is
  signed by the module key or by a CA the user enrolled with physical presence (D40),
  which makes the machine not attested. SELinux denies `execmem` to system and Athanor
  service domains except those declared; user applications stay in `unconfined_t` as in
  Fedora (D24).
- **Rollout:** every policy runs in audit mode in acceptance and on the maintainer's
  machine before enforcement; enforcement is gated (P6), and release 1.0 enforces
  `KMODULE` and `FIRMWARE` only (D36).
- **Root boundary** (D44): enforcement is one-way once enforcing under lockdown, and only
  one SELinux domain may write IPE securityfs or load SELinux policy.

**Gatekeeper** (restricted area): leaves the blocking path (`FAN_OPEN_EXEC_PERM`), where a
hung daemon blocks the system and a dead one disables protection; it may remain an audit
consumer. Its new specification is written separately and approved before any change.
No custom BPF LSM is written. `RestrictFileSystemAccess=` is a per-service second layer on
kernels from 7.2.

**Application self-confinement:** Landlock (ABI 9) is a platform rule; Athanor
applications declare filesystem, network and IPC access through a shared crate
`athanor-sandbox` over the `landlock` crate. Services also use systemd sandboxing.

**eBPF without root:** unprivileged BPF stays off. Services receive BPF tokens with
`PrivateBPF=yes`, `PrivateUsers=` (a token cannot be created in the initial user
namespace) and comma-separated delegation lists, for example
`BPFDelegateCommands=BPFMapCreate,BPFProgLoad,BPFTokenCreate`,
`BPFDelegateMaps=BPFMapTypeXskmap`, `BPFDelegatePrograms=BPFProgTypeXdp`,
`BPFDelegateAttachments=BPFXdp` (syntax verified with systemd 258). Attaching XDP to a
host interface still requires `CAP_NET_ADMIN` in the host network namespace.

**io_uring:** disabled except for services given the `athanor-io-uring` group.

**User namespaces:** available (Flatpak, rootless podman, browser sandboxes). The loaded
SELinux policy already exposes `user_namespace create`, so creation is restricted per
domain through SELinux; services also set `RestrictNamespaces=`.

**Network:** per-service `IPAddressAllow=`/`IPAddressDeny=`, `RestrictNetworkInterfaces=`,
`SocketBindAllow=`, and host nftables. Tetragon leaves the image.

**Residual risks, stated:**

- A script passed to a verified interpreter escapes IPE (no widespread interpreter uses
  `AT_EXECVE_CHECK` yet).
- JIT and code in the home remain allowed on the desktop class, and IMA there measures
  without appraisal; nothing comparable to macOS Gatekeeper or Windows Smart App Control
  exists yet.
- Root keeps persistence in `/etc` and `/var`, and can mount an older image signed with a
  valid integrity key until that certificate is revoked.
- IPE has almost no production experience in enforcement.
- Linux has no hypervisor-isolated code integrity comparable to Windows HVCI or Apple's
  kernel page protection.
- TPM-only unlock on an attested machine is exposed to TPM bus sniffing and DMA attacks,
  as with BitLocker without a PIN.

## 11. Reliability

A panic reboots after 10 seconds; three failed boots fall back to the previous version;
on mesh nodes an oops or repeated warnings become a panic, on interactive roles repeated
oops do (D19). Crash evidence comes from EFI pstore archived by `systemd-pstore`, the
persistent journal and `DRM_PANIC` with its QR code; acceptance verifies that a
deliberate panic leaves a pstore record. There is no kdump.

## 12. Verification

1. **CI, no VM:** the `profile.toml` validator over every role combination;
   `check_delta` on the kernel configuration (existing); the bump bot fails while the
   pinned series is end of life (D37).
2. **Kernel boot matrix** (`forge/specs/azoth/boot.sh`): CPU models Nehalem (the kernel is
   x86-64 v1, D14) and host; new assertions for forced lockdown, the preemption mode from
   the `Dynamic Preempt:` line of the kernel log (debugfs is not available), IOMMU domain
   type, ASLR bits, the exact set of builtin certificates, the absence of
   `dm_verity.keyring_unsealed`, a module signed by an enrolled non-CA MOK rejected
   (existing), and from P4b the IPE boot policy active; under Secure Boot an unsigned
   addon must be rejected.
3. **ISO acceptance** (`forge/test/iso`): a required `profile-ok` marker emitted by
   `athanor-profile-check`, whose failure report lists the drifting settings; the
   installer refuses a CPU without x86-64-v3; a deliberate panic leaves a pstore record.
   The desktop role runs on every acceptance; the laptop role in the weekly run.
4. **On the machine:** `athanor-profile-check` gates `boot-complete.target` and checks
   `/proc/config.gz`, `/proc/cmdline`, sysctls, `scx_loader` state, integrity mode,
   external PCIe ports marked untrusted (D16), and that the roles applied under `/run`
   match the role addons in the PCR 12 event log.
5. **Release 1.0 updates** (P4b, in a VM with Secure Boot and swtpm): an image with an
   invalid signature, an expired manifest and a version below the minimum are refused; an
   update does not become the boot default before the user confirms; a reboot without
   confirmation boots the running version; a deliberately failing health check returns to
   the previous version; TPM-only unlock is refused in degraded mode.
6. **Attestation** of mesh hosts (restricted area, after 1.0).

## 13. Benchmarks and provisional decisions

Last phase before 1.0, on real hardware of more than one CPU vendor and not in a VM:
latency (`schbench`, `cyclictest`), throughput (`hackbench`, kernel compilation, `fio`),
network (`netperf`). At least ten runs per configuration, reported as median and
dispersion. The results close D5 (BORE against plain EEVDF), D13 (lazy against full), D15
(swappiness, zram writeback on small machines), D16 (the cost of `iommu.strict=1` where a
role wants it), the costs of `KSTACK_ERASE`, `INIT_ON_FREE`, `PAGE_TABLE_CHECK`,
`DEBUG_VIRTUAL`, `DEBUG_SG` and `UBSAN_TRAP`, `scx_lavd` PowerSave against BORE with
`power-saver` on battery, THP, and the mesh network settings. AutoFDO profiles are
collected with representative workloads and committed with their hashes; a stale profile
is tolerated across bumps. A setting that costs too much is recorded as a decision, never
silently removed.

## 14. Outside the profile, tracked

Found on the running system and in the repository (2026-09-14):

- **NVIDIA** does not load on the deployed image: its modules are signed by the retired
  MOK and the image predates the new module certificate. The cut-over is the redeploy
  after the release chain; `MOK_PRIVATE_KEY` is deleted once a deployed system loads
  `nvidia` signed by the module signing key (signing key rotation plan, task 9). Until
  then `cosmic-comp` floods the journal with `VRR_ENABLED` warnings under nouveau.
- **Kernel series:** Azoth is pinned to 7.1.8 while 7.1 is end of life; the bump bot, now
  scheduled from `iso-v0`, moves it to 7.2 (D37).
- **CI signing:** the Secure Boot key is used in the same job as the image build and
  third-party actions (D43).
- **Base configuration:** `ermete-base-config` is still installed and duplicates
  `10-ermete.conf` (scx_loader), `99-ermete-slim-boot.conf`, `99-Ermete-Base.preset` and
  `10-ermete-hw-groups.conf`; `athanor-base-config` declares
  `Obsoletes: ermete-base-config` (P3). `athanor-base-config` also ships NVIDIA dracut and
  kargs configuration to every machine (P3, section 6).
- **Command line sources:** `kargs.d` 02–06, `system/athanor-install.ks` (`iommu=pt`,
  `pti=on`, `zswap.enabled=1`, ...) and `forge/specs/azoth/cmdline`, which the boot
  matrix uses with `zswap.enabled=1`, `lockdown=` and `preempt=`: all aligned to section 6
  (P3).
- **Sysctl and memory:** `99-bore.conf` forces BBRv1 and CFS tunables that fail under
  EEVDF; `99-azoth-sysfs.conf` enables KSM; the machine has no swap at all (P3).
- **Image content:** `kernel-devel` and `kernel-headers` 6.18 from another vendor, the
  `akmods@` and `dkms` units, `kernel-uki-virt` with addons unused by the boot path,
  `bcachefs-tools`, and `athanor-tetragon` are in the image (P3).
- **Units:** `athanor-journal-seal.service` fails on every boot because Fedora's systemd
  lacks forward-secure sealing: the unit, `Seal=yes` in `99-immutable.conf` and its preset
  line leave the image (P3). `Containerfile` enables `tetragon` and `tpm-luks-seal`, and
  `preset-all` disables them again. Shipped disabled and reviewed in a dedicated session:
  `athanor-gatekeeper-rs`, `athanor-daemon`, `athanor-secure-boot`, `store-rs`, `lvfs-rs`,
  `backup`, `recovery`, the TPM rollback units and `tpm-luks-seal`; the Gatekeeper and
  attestation are restricted areas.
- **Snapshots:** `athanor-timewarp` and `athanor-backup-hourly` target bcachefs, which left
  mainline in Linux 6.18, and misdetect `/var/home` as tmpfs: they are ported to btrfs
  subvolume snapshots.
- **LUKS script:** `athanor-tpm-luks-seal.sh` has a syntax error (`|| {` after `fi`) and
  binds LUKS to PCRs 0, 2, 7 and 11: it is replaced by the LUKS policy of D42 (P4b).
- **Boot ordering:** udev reports unknown groups (`disk`, `kvm`, `render`, `audio`, `lp`)
  and tmpfiles cannot apply the journal ACLs early in boot (P3).
- **Desktop:** `cosmic-panel.service` memory limits (`MemoryHigh=1G`) kill the panel under
  normal use; they are fixed with the reinstallation while COSMIC remains the temporary
  desktop.
- **Mesh code:** the mesh crates are excluded from the build; `athanor-mesh-sync` returns
  all-zero Kyber and Dilithium public keys while logging post-quantum key exchange, and
  the attestation code reports success from the existence of a device file. They are
  removed or made to fail explicitly before any mesh crate re-enters the DAG (D38).
  `doc_cloud_mesh.md` is replaced by the mesh specification (D27).
- **Retirements:** `athanor-ebpf-sched` (contains an AI model contradicting
  `doc_kernel_layer.md`) is retired as a scheduler.
- **Userland flags:** `forge/config/rpmmacros` includes `-mlam=u48`, an Intel-only
  feature, for every CPU vendor: reviewed with the Forge pipeline.
- **Maintainer machine:** MokList still holds certificates from earlier installations
  (Fedora CA, a uBlue kernel key, three akmods keys), and the project Secure Boot
  certificate is not enrolled; the machine is cleaned up at the reinstallation.

## 15. Implementation blocks

A new "BLOCCO P" in `NEXT.md`; no block starts before the previous gate is green.

**Immediate, independent of P0:** the release chain of pull request #25 (module
verification against the kernel's keyrings) and the NVIDIA cut-over; pull request #26
(the end-of-life rule of D37) and the 7.2 bump that follows; the sign-only CI jobs of D43.

| Block | Content | Gate |
| --- | --- | --- |
| P0 | this specification | maintainer approval |
| S1 | spike, no time box: bootc sealed composefs with UKI against dm-verity with `systemd-sysupdate`, built and exercised in a VM with Secure Boot and swtpm; covers `/etc` (D39), boot counting, fallback, update and rollback, IPE coverage, signing and maintenance cost | a written comparison with measurements; D6 and D39 closed by the maintainer. Runs alongside P1–P3; P4b waits for it |
| P1 | `profile.toml`, validator, `athanor-profile-check` covering settings already in force; later blocks extend it | acceptance with `profile-ok` |
| P2 | kernel build profile (section 5) without the items marked P4b, P5 or P6; boot matrix assertions of section 12 item 2 | Kernel gate green |
| P3 | `athanor-kernel-profile` base package, removal of old `kargs.d`, `99-bore.conf` and the other command line sources, zram, pstore, NVIDIA configuration by detection, the clean-ups of section 14 marked P3 | acceptance `profile-ok`, desktop role |
| P4a | rebase on Fedora 45, starting on the beta as soon as P3 is green (D25) | full DAG, image and acceptance green; the reinstall image waits for the final release |
| P4b | the release 1.0 update chain on the mechanism chosen by S1: verified images, boot counting, full-image updates with manifest expiry and minimum version, confirmation before the new default, `/etc` per D39, generic minimal initramfs, ESP or XBOOTLDR, integrity and update keys (generated offline by the maintainer), `DM_VERITY=y` and the IPE boot policy if dm-verity is chosen, LUKS per D42, signed IMA policy | section 12 item 5 green in a VM with Secure Boot and swtpm |
| P5 | roles, addons (roles and compatibility), generator, composition and precedence, `athanor-role`, `IA32_EMULATION_DEFAULT_DISABLED` with the interactive addons | validator over every combination; acceptance desktop and laptop |
| P6 | IPE policies in audit, then enforcement of `KMODULE` and `FIRMWARE`; the D20 gate and SELinux `DEVELOP`/`BOOTPARAM` off; SELinux `execmem` restrictions (D24); the root boundary patch (D44); BPF token delegation, io_uring group, `athanor-sandbox` crate | negative tests: module outside the image and unsigned module refused, firmware outside the image refused, `enforce=0` refused under lockdown, IPE securityfs write refused outside its domain |
| P7 | benchmarks, AutoFDO, closing the provisional decisions | decision record closed, report |
| 1.0 | release gate | P1–P7 green; acceptance on real hardware of more than one CPU vendor |

After 1.0, each with its own specification and gates: deltas, layers and update classes B
and C, channels and gradual rollout (section 8); the mesh specification (D27), then the
mesh network, sync and backup with the two tiers of D38; later compute sharing and
remote applications once their prerequisites (D28, D29) hold.

After P5 is green in a VM: backup of `/var/home` and reinstallation of the maintainer's
desktop on the new image.

## 16. Sources

Verified during the design (2026-09-13/14):

- Kernel: `init/Kconfig` (`RUST` dependencies), `arch/Kconfig` (`AUTOFDO_CLANG`,
  `PROPELLER_CLANG`), `arch/x86/Makefile` (`-mno-sse -mno-avx`), `kernel/Kconfig.preempt`,
  `certs/Kconfig`, `certs/blacklist.c`, `security/ipe/*` (`fs.c` enforce handling,
  `eval.c` real inode), `Documentation/admin-guide/LSM/ipe.rst`,
  `drivers/md/dm-verity-verify-sig.c` (platform keyring fallback),
  `kernel/kexec_file.c`, `kernel/module/signing.c` (upstream and Red Hat patch
  `patch-7.1-redhat.patch` of kernel 7.1.8-100.fc43), `drivers/iommu/iommu.c` (strict
  domains for untrusted devices), `arch/x86/kernel/dumpstack.c` and `kernel/exit.c`
  (panic on oops before `oops_limit`), `kernel/bpf/token.c`, `fs/verity/measure.c`,
  `fs/bpf_fs_kfuncs.c`; commits f2c61db29f27 (bcachefs removal), 0c8c88b8eb82 (overlayfs
  verity fix); kernel.org `releases.json` (7.1 end of life on 2026-09-02); running
  configuration of Azoth 7.1.8 and the NVIDIA kmod boot run 34834656982.
- systemd: v258 `man/systemd-stub.xml`, `man/systemd-boot.xml`, `man/sysupdate.d.xml`,
  `man/systemd.exec.xml`, `src/core/namespace.c`, `src/sysext/sysext.c`,
  `docs/TPM2_PCR_MEASUREMENTS.md`; v262-rc2 `man/systemd-sysext.xml`; `NEWS` for 260–262
  (sysupdate experimental again, sysupdated D-Bus removal, NvPCR); Fedora systemd
  versions (F43 258.10, F44 259.x, F45 262~rc).
- bootc: `docs/src/experimental-composefs.md`, `bootloaders.md`,
  `boot-failure-detection.md`, issues #7, #1976, #2079, #2174; composefs issue #360.
- shim `SbatLevel_Variable.txt`; Red Hat article on the Microsoft UEFI CA 2011 expiry;
  Keylime measured boot documentation; Azure Linux OS Guard documentation.
- desync README and releases (v1.1.3); RAUC advanced documentation; CachyOS
  `linux-cachyos/PKGBUILD` and `kernel-patches` at the pinned commits; Mesa Venus
  documentation; `drivers/gpu/drm/xe/xe_pci.c` (SR-IOV platforms); cosmic-comp and
  xdg-desktop-portal-cosmic issues on remote desktop and virtual outputs.
- kernel-hardening-checker runs on the installed system.

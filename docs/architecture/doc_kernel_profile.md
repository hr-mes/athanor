# Athanor OS: Kernel and Platform Profile

Status: **draft for maintainer review, revision 3 (2026-09-14).** Revision 2 folded in a
second full audit of the platform; revision 3 folds in an approval-gate verification of
every statement against kernel v7.2, systemd v258–v262, shim, bootc and the running
system. This document is the definitive profile of the Athanor kernel and of the platform
layer that makes its guarantees real: what the kernel is, how it boots, how its integrity
is proven, how machine roles compose, and how every property is verified. It supersedes
sections 4 (config), 6 (signing and boot chain), 11 (outside the kernel) and 13
(maintainer decisions) of [doc_kernel_build.md](doc_kernel_build.md), which remains the
specification of *how the kernel is built, pinned, published and maintained*.

The profile is definitive in one precise sense: every property below is recorded as a
decision with its rationale, every build and every installed machine is checked against
it, and it changes only through a new written decision. Upstream moves, so the profile is
re-verified at every kernel bump; it is not frozen. Kernel statements refer to Linux 7.2,
the series the next bump moves to (D37).

**What exists today.** Almost nothing of sections 5 to 13 is implemented: the running
system still carries the previous configuration (section 14). What is real is the Azoth
kernel pipeline (Fedora and CachyOS merge, clang, kCFI, Rust, BORE, boot matrix), the
split of the Secure Boot and module signing keys with the module certificate compiled
into the kernel, module verification restricted to the kernel's own keyrings
(`patches/redhat/0001`, on the default branch `iso-v0` and not yet deployed), and the
self-hosted KVM runner. Section 15 turns the rest into gated blocks.

## 1. Goals and constraints

- A single kernel binary for every machine, matching or exceeding other Linux
  distributions, macOS and Windows on integrity wherever Linux allows; remaining gaps are
  stated (section 10).
- Full control of the kernel as a platform for purpose-built Athanor applications, built
  on stable kernel interfaces rather than a deeper fork. Athanor patches are small, each
  one explains why, and each one is proposed upstream.
- Maximum technical level with minimum maintenance: upstream mechanisms over custom code,
  every gate fails loudly, the system maintains itself. The scope of each release is
  sized for one maintainer (D36).
- Designed for everyone: features are defined by capability tiers detected at runtime,
  never by one hardware configuration. The userland requires x86-64-v3 and UEFI; the
  kernel itself stays bootable on any x86-64 CPU so that an unsupported machine gets a
  clear message (D14).
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

**Terms.** *Image*: the signed operating system (`/usr` and its UKI) of one version.
*Slot*: A/B storage for an image (dm-verity option of D6 only). *Role*: a runtime profile
activated by a signed addon. *Mesh host*: an attested machine that holds data or runs
workloads for the owner's other devices; *mesh-only host*: a mesh host with no
interactive role. *Client*: a device that uses the mesh without being a host.

## 2. Decision record

States: **final**; **provisional** (a default, closed by the benchmarks of section 13);
**open** (closed by the named spike or block); **after 1.0** (kept as the target, outside
the release 1.0 scope of D36); **revised** (amended by the named decision);
**superseded** (replaced by the named decision).

| ID | Decision | Rationale | State |
| --- | --- | --- | --- |
| D1 | One kernel binary; roles are runtime profiles | one build, one signature, simple attestation | final |
| D2 | Roles compose; a machine holds zero or more. A machine with no role runs the base profile with the desktop IPE class | a workstation can also be a mesh node | final; combinations of an interactive role with the mesh role from the mesh specification (D27) |
| D3 | Userland baseline x86-64-v3 and UEFI, enforced by the installer; integrity chain optional with declared degraded mode | matches the v3 userland; keeps machines without TPM or Secure Boot installable | final |
| D4 | Rust enabled; performance from AutoFDO; ThinLTO re-checked at every bump; Propeller deferred until profiling runs automatically on more than one CPU vendor | `RUST` still depends on `!DEBUG_INFO_BTF \|\| (PAHOLE_HAS_LANG_EXCLUDE && !LTO)`; AutoFDO and Propeller do not require LTO; a Propeller profile is bound to one binary and one test machine's workload | final |
| D5 | BORE is the base scheduler; sched_ext only through `scx_loader` as a role setting; `athanor-ebpf-sched` retired as a scheduler. If the BORE patch does not apply to a bump required by D37, the kernel ships on plain EEVDF rather than waiting | one owner; sched_ext falls back to the fair class; an out-of-tree patch must never delay a security bump | provisional (BORE against plain EEVDF in P7) |
| D6 | The verified image and A/B update mechanism: either `/usr` on dm-verity with a signed root hash, A/B slots with `systemd-sysupdate` and UKI boot with systemd-boot, or bootc with sealed composefs and UKI | the first option leaves `/etc` to be designed, depends on a `systemd-sysupdate` marked experimental again in systemd 262, and makes Athanor maintain its own update system; bootc's sealed composefs backend is close to stable, handles `/etc` per deployment and plans boot counting, but IPE cannot cover composefs | open (spike S1 on Fedora 45, no time box) |
| D7 | Delta updates by content-defined chunking, verified by the image signature | small downloads without weakening integrity | after 1.0 (D36); if S1 selects bootc, OCI layer pulls provide partial downloads first |
| D8 | IPE is the in-kernel enforcer for code integrity on dm-verity images. Class policies carry versions ordered by class, so a running machine can only move to an equal or stronger class | upstream, compiled in, signed policies; IPE refuses only a lower policy version and never compares policy names, so without the ordering root could activate a weaker signed policy; IPE's documentation positions it for fixed-function devices, so its full default-deny use is the mesh class | final; applies if S1 selects dm-verity (D6) |
| D9 | Role content ships inside the signed image; the active role set is a signed UKI addon per role | confext passed through the stub is unmerged at switch-root; addons are verified through shim and measured into PCR 12 | final; revisited if S1 selects bootc |
| D10 | Composition follows NixOS semantics: type-based merge, conflict is a build error resolved only by explicit priority | explicit, no silent resolution, proven model | final |
| D11 | On a desktop or laptop, the mesh node role runs inside a MicroVM | the services that matter (backup, inference, remote sessions) run on the host anyway, and on consumer CPUs without SEV-SNP or TDX the VM adds no trust | superseded by D38 |
| D12 | The mesh node role requires attested mode | a node that keeps its key but runs altered code must not stay a node | revised by D38: required for mesh hosts only |
| D13 | Preemption `lazy` as the base (Fedora's choice); `full` through a role addon (`preempt=full`, possible with `PREEMPT_DYNAMIC`) only if P7 measures a gain | x86 offers only FULL and LAZY; LAZY delays preemption of normal tasks by at most one tick; a boot parameter belongs to a role, not to the build | provisional |
| D14 | Kernel built with `X86_64_VERSION=1`; x86-64-v3 is enforced by the installer and by `athanor-cpu-check` in the initramfs, which stops the boot with a clear message on an unsupported CPU | the kernel is compiled with `-mno-sse -mno-avx` (`arch/x86/Makefile`), so a v3 build gains only integer extensions, while a v1 kernel can still boot far enough to explain why the machine is unsupported | final |
| D15 | Swap on zram (zstd), zswap off; writeback of idle or incompressible pages to an encrypted block device evaluated for machines with 8 GiB or less | no double compression; swap on LUKS is encrypted, so disk-backed writeback is excluded only on wear and latency grounds, which P7 measures; zram writeback requires a block device, not a file | provisional (swappiness and writeback in P7) |
| D16 | IOMMU in lazy mode by default; external ports are forced into strict DMA domains with bounce buffering by the kernel when firmware marks them untrusted, and `athanor-profile-check` verifies that marking; `iommu.strict=1` is available per role | the kernel already isolates untrusted devices; global strict only costs throughput on internal NVMe and NICs | provisional |
| D17 | Minimal generic initramfs (never host-only), validated by an acceptance hardware matrix rather than by module names: storage (`nvme`, `vmd`, `sdhci_pci` and `mmc_block`, `virtio_scsi`, `hv_storvsc`; AHCI and `virtio_blk` are built in), `dm_crypt`, input for the LUKS passphrase (`i2c_hid_acpi` with the Intel `pinctrl_*` drivers, `surface_hid`, `hyperv_keyboard`; USB HID and i8042 are built in), `thunderbolt` for keyboards behind docks; no GPU driver, so the passphrase prompt uses the firmware framebuffer (`simpledrm`). ESP of 2 GiB when Athanor owns the disk, an XBOOTLDR partition next to a smaller existing ESP otherwise | today's UKI carries 102 MB of initramfs; dual boot with a preinstalled Windows ESP of 100–260 MB must work | final |
| D18 | Laptop is an autonomous role; desktop and laptop share an `interactive` fragment of the manifest | a laptop without the desktop role keeps 32-bit, gaming and interactive settings, without duplicated definitions | final |
| D19 | `PANIC_ON_OOPS` stays off in the build; `kernel.panic_on_oops=1` and `kernel.warn_limit=100` on mesh-only hosts; `kernel.panic_on_oops=0` with `kernel.oops_limit=100` and `kernel.warn_limit=0` on interactive roles. Crash evidence comes from EFI pstore, enabled in the build and emptied by `systemd-pstore` | with `PANIC_ON_OOPS=y` the first oops panics before `oops_limit` is consulted, so a desktop would reboot and lose work at the first driver oops; Fedora disables EFI pstore by default, and without a backend a panic leaves no record | final |
| D20 | SELinux `DEVELOP` and `BOOTPARAM` are switched off only after zero AVC denials in Athanor domains in acceptance; denials from Fedora packages are triaged and documented, and none may affect boot, login or security. Recovery from a denial that breaks the system after boot is the previous image in the boot menu, not `enforcing=0` | a gate that does not depend on upstream policy bugs, and a recovery path that survives the switch | final |
| D21 | Role addons are built and signed in CI, shipped inside the image, and installed per UKI in `<uki>.efi.extra.d/` on the partition that holds the UKI, together with that UKI | the stub reads global addons only from the volume of the loaded UKI, and a global addon without `.uname` would be used by every UKI, so a fallback boot would run the previous image with the new image's parameters; no second distribution channel | final |
| D22 | Hosting of the delta chunk store | chosen from measured delta sizes, chunk counts and expected traffic | after 1.0 |
| D23 | Desktop class: no `noexec` on user-writable locations; code in the home runs and is measured by IMA. Protection against downloaded executables is a quarantine prompt in the launcher and file manager, based on the `user.xdg.origin.url` attribute, specified in the desktop specification after 1.0 | `noexec` on `/tmp`, removable media or `~/Downloads` is bypassed by passing the file to an interpreter and breaks `go test`, Java native libraries, PyInstaller and .NET single-file apps, Steam libraries on external drives and AppImages; a prompt outside the kernel is bypassable from a terminal, which is a stated residual risk | final |
| D24 | SELinux denies `execmem` to system and Athanor service domains except those declared; user applications stay in `unconfined_t` as in Fedora. For a Fedora policy module that grants `execmem`, "declared" means the module is patched or disabled, recorded per module | restricting user domains would break Electron, Java, .NET, Python ctypes and emulators, not only browsers; SELinux allow rules only add, so a local module cannot remove Fedora's grants | final |
| D25 | The Fedora 45 rebase starts on the beta as soon as P3 is green; the image that reinstalls the maintainer's desktop is built only on the final release (target 2026-10-20); any block that needs a systemd 262 feature waits for systemd 262 final in Fedora 45 updates | problems surface early, production waits for supported releases | final |
| D26 | The mesh is personal: its nodes are the devices of one owner. It provides a private network between them, synchronisation and backup, compute sharing and remote applications; it is not an update channel | the purposes the maintainer set; updates keep one signed source and one verification path | final purpose; delivery after 1.0 (D38) |
| D27 | The mesh subsystem has its own specification, a rewrite of `doc_cloud_mesh.md`; this profile holds only its kernel and platform requirements | protocol, identity, discovery and scheduling are not kernel decisions | final |
| D28 | Compute sharing by capability tiers: CPU workloads in MicroVMs; GPU inference through a signed host service; a GPU inside a guest with SR-IOV, a second GPU in its own IOMMU group, or virtio-gpu Venus for Linux guests | works on any machine; extra hardware unlocks more. Today SR-IOV exists on consumer hardware only for some Intel GPUs, and Venus only with QEMU, crosvm or libkrun | after 1.0; the GPU-in-guest tiers need hardware evidence before they are promised |
| D29 | Remote applications from interactive hosts, by tiers: a session on a virtual output with hardware encoding, applications of a Windows VM forwarded one by one, a 3D-accelerated VM where the hardware allows; the local session is never closed | usable across GPU vendors; the owner keeps working locally | after 1.0; blocked until the session compositor provides virtual outputs (COSMIC does not today) |
| D30 | Updates ship as a base image plus signed layers that apply without a reboot | most changes could apply without rebooting | after 1.0; redesign required (section 8) |
| D31 | Update classes: A applications, no interruption; B service layers, applied by restarting only their services; C the desktop layer, at the end of the session or at a soft reboot the user chooses; D the base, at a full reboot the user chooses and never forced; mesh-only hosts reboot in a maintenance window set by the owner | no forced reboots; each change costs only the interruption it needs | classes A and D in 1.0; B and C after 1.0 |
| D32 | A layer is trusted only when the kernel verifies its signature: the UKI command line sets `systemd.allow_userspace_verity=0`, and image policies are passed with `--image-policy=` and `ExtensionImagePolicy=` from units shipped in `/usr` | systemd's default extension image policy accepts unprotected images, userspace verity trusts certificates in `/etc/verity.d`, and IPE sees `dmverity_signature=TRUE` only for signatures the kernel verified | after 1.0 |
| D33 | Channels stable and beta; a release is promoted from beta to stable as the same signed artefacts | stable runs, bit for bit, what beta tested | after 1.0 |
| D34 | Gradual rollout without telemetry: each machine derives its rollout day locally, a signed stop manifest halts a release, security releases skip the window; the download server's log retention is set by the update specification after 1.0 | nothing leaves the machine by design; the server still sees requests | after 1.0 |
| D35 | Rollback returns the base and every layer to the versions that belong together | a failure returns to a known pair, never to a mix; layers are selected by the booted base, not by the newest version | after 1.0 |
| D36 | Release 1.0 scope: verified A/B image (D6), boot counting and automatic fallback, full-image system updates that take effect only after the user confirms, applications through Flatpak. With the dm-verity option, IPE enforces a policy whose `EXECUTE` table defaults to allow and whose `KMODULE` and `FIRMWARE` tables default to deny; with bootc, module and firmware integrity rely on module signatures and the measures S1 decides. Deltas, layers, classes B and C, channels and gradual rollout follow in releases 1.1 and 1.2, the mesh after them | the smallest release that is robust for everyone; the audit found the layer and rollout design unsafe as written | final |
| D37 | Kernel series: the stable channel, with a mandatory bump when the pinned series reaches end of life on kernel.org; the bump bot fails while it does, and `KERNEL_CHANNEL=lts` is the maintainer's fallback when no stable pair exists | a series without fixes must never stay pinned in silence, as 7.1 did after 2026-09-02 | final |
| D38 | The mesh has two tiers: attested mesh hosts (backup, compute, remote sessions) and non-attested clients (phones, other operating systems, degraded machines) with limited keys. It composes upstream components (kernel WireGuard with an existing coordination server, Syncthing-class sync, btrfs send and receive) rather than new protocol code. An interactive mesh host enforces the desktop class, so its attestation proves the boot state, not runtime code integrity. No mesh code with placeholder cryptography or attestation ships | mandatory attestation for every device excludes phones and most ordinary machines; the existing mesh crates contain placeholder PQC keys and file-existence attestation | final; delivery after 1.0 |
| D39 | `/etc` is part of the update design. S1 compares factory defaults in `/usr` with `/etc` as a local overlay (`tmpfiles` from `/usr/share/factory`), a per-slot `/etc`, and bootc's per-deployment `/etc` with a three-way merge, judged on user and group databases, `machine-id`, NetworkManager connections and the SELinux policy store | with A/B `/usr` and a shared `/etc`, a rollback would keep the newer configuration and SELinux policy | open (spike S1) |
| D40 | Keyrings: dm-verity root hashes, IPE policies and signed BPF programs are trusted only from the builtin keyring; modules from the builtin and secondary keyrings; `SECONDARY_TRUSTED_KEYRING_SIGNED_BY_BUILTIN=y`. Attested mode requires that `.machine` and `.secondary_trusted_keys` hold exactly the expected certificates. A user who needs modules outside the image enrols a CA certificate (CA=true, keyCertSign, no digitalSignature) in MokList with physical presence, signs the modules directly with that CA key, and runs the `user-modules` IPE variant; the machine is then reported as not attested, and `mokutil --untrust-mok` closes the path | the platform keyring (UEFI db, non-CA MOKs) must not authorise code or policy; with `CA_MACHINE_KEYRING_MAX` only such CAs reach the secondary keyring, leaf certificates they issue cannot be added under `SIGNED_BY_BUILTIN`, and `sign-file` embeds no chain | final |
| D41 | Anti-rollback: manifest expiry and minimum version protect the update path; boot-time downgrade is prevented by revoking superseded UKIs (MokListX hashes, or rotation of the Secure Boot key) and rotating the PCR policy key; a revoked integrity certificate is enforced only by kernels built after the revocation. SBAT sections stay in UKIs and addons because shim requires them, not as an Athanor revocation mechanism | with Fedora's shim only shim publishes SBAT levels; an older UKI with a valid signature boots its own kernel, which still trusts old images, and a signed PCR policy never expires | final |
| D42 | LUKS: TPM-only unlock only in attested mode, offered and never applied automatically; a degraded machine uses TPM plus PIN, or a passphrase. PCR 7 and PCR 14 are bound through a `systemd-pcrlock` policy, updated before known firmware, db or dbx changes; an unforeseen change falls back to the recovery key with a guided reseal that keeps the unlock method the user chose. The signed PCR 11 policy is valid for the initrd phase only (systemd 262). The installer checks that the firmware db accepts a certificate authority that signs the shipped shim | without Secure Boot the command line is measured only into PCR 12, which the policy excludes, so TPM-only unlock would release the key to a modified boot; a dbx update from Windows Update on a dual-boot machine can land before Athanor runs | final |
| D43 | The Secure Boot, module signing, integrity and update keys are used only in sign-only CI jobs that receive built artefacts, never in a job that runs third-party actions or the image build. The module signing and integrity keys share one custody: their own environment with required reviewers | a compromised build step must not be able to sign; any builtin key can sign modules, IPE policies and root hashes, so the weaker custody would set the protection of both | final |
| D44 | Root boundary: an Azoth patch, proposed upstream, makes IPE enforcement one-way once enforcing; class-ordered policy versions (D8) prevent activating a weaker signed policy. SELinux is not a boundary against an unconfined root under Fedora's targeted policy, which lets `unconfined_t` enter any domain and load policy: this is a stated residual risk | `CAP_MAC_ADMIN` can write `enforce=0` today; confining root would require `sysadm_u` and break the Fedora administration model | final; the patch is written in P6 |
| D45 | Compatibility boot profile: the UKI carries a second signed profile with `efi=no_disable_early_pci_dma intel_iommu=off`, selectable from the boot menu and offered by the installer when the first boot fails | firmware that misbehaves with `EFI_DISABLE_PCI_DMA` or broken DMAR tables hangs before an addon could be installed; users cannot edit a signed command line | final |

## 3. Architecture overview

The chain below is the dm-verity option of D6; spike S1 compares it with bootc sealed
composefs, which keeps the firmware, shim, UKI and kernel levels and replaces `/usr` on
dm-verity with a composefs image verified by fs-verity.

```
firmware (UEFI db)
  └─ shim (Fedora, Microsoft-signed)    verifies with db, shim's built-in Fedora certificate, MokList
       └─ systemd-boot as shim's second stage   signed: Secure Boot key   boot counting (+3)
            └─ UKI                      signed: Secure Boot key   .cmdline (usrhash=, base params)
                 │                                                .pcrsig (signed PCR 11 policy, initrd phase)
                 │                                                second profile: compatibility (D45)
                 ├─ <uki>.efi.extra.d/athanor-role-<r>.addon.efi   signed: Secure Boot key → PCR 12
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

- **Attested**: Secure Boot on; MokList holding only the project Secure Boot certificate,
  and the PCR 7 event log showing only project-signed authorities after shim; `.machine`
  and `.secondary_trusted_keys` holding exactly the expected certificates (D40); TPM 2.0
  present; the signed PCR 11 policy valid; PCR 12 consistent with the declared role set.
  Required by mesh hosts (D38) and by TPM-only disk unlock (D42).
- **Degraded** (declared "not attested"): anything missing. The UKI still boots and the
  image is still verified on every read. Without Secure Boot, systemd-stub accepts a
  command line from the boot loader and the UKI itself is not verified by firmware, so an
  attacker with root or physical access can replace the UKI, its command line and its
  addons on the ESP, including `ipe.enforce=0`. IPE enforcement, the root boundary (D44)
  and image verification are guarantees of attested mode only; on a degraded machine a
  TPM+PIN prompt can come from a replaced boot chain. `athanor-profile-check` reports the
  mode and the reasons.
- In degraded mode the role addons are not verified either: shim verifies them only
  under Secure Boot, so someone with physical access can add a forged addon such as
  `athanor.role=mesh`. Roles are therefore *declared*, not *proven*, on a degraded
  machine: `athanor-profile-check` reports them as declared, `athanor-role` never grants
  anything on the strength of the command line alone, and no trust decision (mesh
  admission, attestation, IPE policy class stronger than the one the machine actually
  enforces) may rest on a role that is not backed by attested mode.
- A machine using the `user-modules` variant (D40) is reported as not attested even when
  everything else holds.
- First boot starts degraded. A guided step imports the Secure Boot certificate
  (`mokutil --import`); the confirmation in MokManager is a human action by design. The
  next boot with Secure Boot on is attested, and TPM-only unlock is offered (D42).

## 5. Kernel build profile (`kernel-local`)

Principle: what holds for every role and must not be changeable at boot lives in the
build configuration; what a role or a compatibility case must change stays a boot
parameter, set by a signed addon or profile. Items marked (P4b), (P5) or (P6) depend on a
later block and are not part of P2. Fedora enables several of the options below, so
`kernel-local` sets every disabled option explicitly (`# CONFIG_X is not set`).

**From the command line into the build:**
`LOCK_DOWN_KERNEL_FORCE_INTEGRITY=y`, `INIT_ON_FREE_DEFAULT_ON=y`, `LEGACY_VSYSCALL_NONE=y`,
`DEBUG_FS_ALLOW_NONE=y`, `PANIC_TIMEOUT=10`, `INTEL_IOMMU_DEFAULT_ON=y`,
`EFI_DISABLE_PCI_DMA=y` (with the compatibility profile of D45),
`EFI_VARS_PSTORE_DEFAULT_DISABLE` off (D19).

**New hardening:** `KSTACK_ERASE=y`, `PAGE_TABLE_CHECK=y`, `PAGE_TABLE_CHECK_ENFORCED=y`,
`DEBUG_VIRTUAL=y`, `DEBUG_SG=y`, `DEBUG_NOTIFIERS=y`, `ARCH_MMAP_RND_BITS=32`,
`ARCH_MMAP_RND_COMPAT_BITS=16`, `PROC_MEM_FORCE_PTRACE=y`,
`SECONDARY_TRUSTED_KEYRING_SIGNED_BY_BUILTIN=y` (D40),
`IA32_EMULATION_DEFAULT_DISABLED=y` (P5, together with the addons of the interactive
roles that re-enable it, so 32-bit applications never break between blocks),
`SECURITY_SELINUX_DEVELOP` and `SECURITY_SELINUX_BOOTPARAM` off (P6, after the D20 gate).
Enabled in P2 unless the boot matrix or acceptance fails, with their cost recorded in P7:
`UBSAN_TRAP`, `MSEAL_SYSTEM_MAPPINGS` (requires `CHECKPOINT_RESTORE` off), `PROC_KCORE`
off, `BLK_DEV_WRITE_MOUNTED` off.

**Keyrings** (D40): `DM_VERITY_VERIFY_ROOTHASH_SIG=y` and `SECURITY_IPE=y` with
`DM_VERITY_VERIFY_ROOTHASH_SIG_SECONDARY_KEYRING`, `DM_VERITY_VERIFY_ROOTHASH_SIG_PLATFORM_KEYRING`,
`IPE_POLICY_SIG_SECONDARY_KEYRING` and `IPE_POLICY_SIG_PLATFORM_KEYRING` all off (Fedora
enables all four), so root hashes and policies verify against the builtin keyring only.
With its options on, the dm-verity signature code falls back to the secondary and platform
keyrings on `-ENOKEY` and on `-EKEYREJECTED`, and finally to the `.dm-verity` keyring,
which stays sealed and empty unless `dm_verity.keyring_unsealed=1`. Module verification
uses the builtin and secondary keyrings; the Red Hat fallback to the platform keyring is
removed by `patches/redhat/0001`. Signed BPF programs may name the builtin, secondary or
platform keyring: any policy that grants trust to a signed BPF program requires the
builtin keyring. `SYSTEM_TRUSTED_KEYS` carries the module signing certificate and, from
P4b, the integrity certificate; `SYSTEM_REVOCATION_KEYS` the retired ones. The kernel
cannot restrict a builtin certificate to one purpose, so the module and integrity keys
share one custody (D43). `INTEGRITY_MACHINE_KEYRING` with
`INTEGRITY_CA_MACHINE_KEYRING_MAX` stays on for the user path of D40. From P4b:
`DM_VERITY=y` (built in) and `IPE_BOOT_POLICY` set to the compiled boot policy
(section 10).

**Attack surface removed** (unused by every role): `KEXEC`, `KEXEC_FILE` (its signature
check falls back to the platform keyring) and `KEXEC_HANDOVER` (which selects
`KEXEC_FILE`), `CRASH_DUMP`, `LIVEPATCH` (updates are images), `HIBERNATION` (blocked by
lockdown), `SECURITY_TOMOYO`, `X86_IOPL_IOPERM`.
`LSM="lockdown,yama,selinux,bpf,landlock,ipe"` (IMA and EVM always initialise last and
take no position in the list).

**Kept on purpose:** `IA32_EMULATION` and `MODIFY_LDT_SYSCALL` (Steam, Wine), `MODULES`
(NVIDIA, and user modules through D40), `BPF_LSM`, `KALLSYMS`, kprobes and ftrace (the
eBPF nerve, observability), `IMA_ARCH_POLICY` (attestation), `ZRAM` with
`ZRAM_WRITEBACK`, `PREEMPT_DYNAMIC`, `SHUFFLE_PAGE_ALLOCATOR`.

**Rejected:** `PANIC_ON_OOPS` (D19), `IOMMU_DEFAULT_DMA_STRICT` (D16),
`STATIC_USERMODEHELPER` (modprobe and the coredump pipe need helpers),
`RESET_ATTACK_MITIGATION` (without userspace support the firmware wipes RAM at every
boot), `TRIM_UNUSED_KSYMS` (breaks the NVIDIA modules), `RANDSTRUCT` (excluded by Rust),
`SECURITY_LOADPIN` (IPE covers `KMODULE` and `FIRMWARE` with the dm-verity option;
reconsidered by S1 if bootc is chosen).

**Codegen:** `RUST=y`, `AUTOFDO_CLANG=y` (profiles arrive in P7), `X86_64_VERSION=1`
(D14), preemption `lazy` (D13).

## 6. Runtime base profile

**Kernel command line.** Nearly empty: what installation knows (LUKS device, root),
`usrhash=` from the image build, and `page_alloc.shuffle=1` (page allocator randomisation
is off by default even when built in). Removed from today's `kargs.d`, kickstart and
`forge/specs/azoth/cmdline`:

- already defaults: `slab_nomerge`, `randomize_kstack_offset`, `ima_hash`,
  `init_on_alloc`, `amd_pstate=active`;
- moved into the build: `module.sig_enforce`, `lockdown`, `init_on_free`, `vsyscall`,
  `debugfs`, `intel_iommu=on`, `efi=disable_early_pci_dma`;
- moved into roles, or dropped: `oops`, `preempt=full` (the base becomes lazy, D13),
  `zswap.enabled=1` and `zswap.compressor=zstd` (D15);
- wrong or invalid: `pti=on` (forces page table isolation on CPUs not affected by
  Meltdown), `iommu=pt`, `amd_iommu=on` (not a valid option), `lam=on` and `arm64.mte=on`
  (unknown to this kernel);
- capability-specific, never global: `mem_encrypt=on`, `kvm_amd.sev=1`, `kvm_intel.tdx=1`.

NVIDIA parameters and dracut configuration move out of the base: they apply only where an
NVIDIA GPU is detected. `ima_policy=tcb` is removed; IMA measurement follows D23, and its
policy is signed, because under Secure Boot the architecture policy requires
`appraise func=POLICY_CHECK appraise_type=imasig`. The IMA certificate ships in `/usr`, and
its trust path is fixed in P4b: with `IMA_KEYRINGS_PERMIT_SIGNED_BY_BUILTIN_OR_SECONDARY`
the `.ima` keyring also accepts keys vouched by the secondary keyring, which a
user-enrolled CA reaches (D40).

**sysctl (base, locked):** `kernel.yama.ptrace_scope=1`, `kernel.kptr_restrict=2`,
`kernel.dmesg_restrict=1`, `dev.tty.ldisc_autoload=0`, `fs.protected_fifos=2`,
`fs.protected_regular=2`, `fs.suid_dumpable=0`, `kernel.oops_limit=100`,
`kernel.io_uring_disabled=1` with `kernel.io_uring_group` set to the numeric GID of the
`athanor-io-uring` group (fixed in `sysusers.d`, because sysctl takes no group names;
processes with `CAP_SYS_ADMIN` are also allowed), `net.core.default_qdisc=fq`.
**sysctl (base, overridable by roles):** `kernel.sysrq=176` (sync, remount read-only,
reboot). The TCP congestion control is not set, so the kernel default BBRv3 applies.
`athanor-system-tweaks/.../99-bore.conf` is removed with its CFS tunables that no longer
exist under EEVDF and its override to BBRv1. KSM stays off unless a role declares it.

**Scheduler:** EEVDF with BORE at the defaults of the pinned patch, `HZ=1000`.

**Memory:** zram swap with zstd (`zram-size = min(ram / 2, 8192)`), MGLRU on, THP
`madvise` with defrag `defer+madvise`; `vm.max_map_count` keeps Fedora's default
(1048576).

**Power:** power-profiles-daemon is the only owner of EPP and platform profile; the CPU
vendor's driver in active mode (`amd_pstate` or `intel_pstate`).

## 7. Roles

**Content.** Each role is a directory in the signed image,
`/usr/lib/athanor/roles/<role>/`, holding `sysctl.d`, `modprobe.d`, `tmpfiles.d`,
`systemd` units and drop-ins, `power-profiles-daemon` and `scx_loader` configuration.
It is protected by the image verification like the rest of `/usr` and updated atomically
with the OS.

**Activation.** A role is active when its signed addon is installed next to the UKI in
`<uki>.efi.extra.d/athanor-role-<role>.addon.efi` (D21). The addon carries
`athanor.role=<role>` and the role's kernel parameters, is verified through shim, and is
measured into PCR 12 together with the other command line fragments. Addons are built
and signed in CI and shipped inside the image as
`/usr/lib/athanor/roles/<role>/athanor-role-<role>.addon.efi`; `athanor-role` installs the
addons of the chosen roles for the running and the pending UKI, and every update installs
them for the new UKI from the new image, so a UKI never boots with parameters from
another image version.

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
emulation, autogroup, MGLRU `min_ttl_ms`, `ntsync`, `split_lock_mitigate=0`,
`panic_on_oops=0`, `warn_limit=0`), so the laptop stands alone without duplicating the
desktop (D18).

**Roles:**

| Setting | No role | Desktop | Laptop | Mesh-only host |
| --- | --- | --- | --- | --- |
| addon parameters | none | `rhgb`, `ia32_emulation=1` (interactive) | `rhgb`, `ia32_emulation=1` (interactive) | none in 1.0; confidential-computing parameters are defined by the mesh specification |
| scheduler | BORE | BORE; `scx_lavd` Gaming only on demand (`scxctl`) | `scx_lavd` PowerSave (provisional, P7) | BORE |
| autogroup | kernel default | on | on | off |
| power profile | `balanced` | `balanced` | `balanced` on AC, `power-saver` on battery, switched by a role unit that follows UPower's `OnBattery` | `performance` where the platform offers it, otherwise `balanced` |
| memory and sleep | base | MGLRU `min_ttl_ms=1000`, `ntsync` (interactive) | interactive settings; suspend mode and ASPM left to the firmware defaults unless P7 measures a gain | network buffers `net.core.rmem_max` and `wmem_max` 16 MiB, `netdev_max_backlog=16384` (provisional, P7) |
| other | base | `split_lock_mitigate=0`, `panic_on_oops=0`, `warn_limit=0` (interactive) | interactive settings, Wi-Fi power saving | `kernel.sysrq=0`, `bpf_jit_harden=2`, `panic_on_oops=1`, `warn_limit=100` (D19), attested mode required |
| IPE policy class | desktop | desktop (section 10) | desktop | mesh |

A machine holding both an interactive role and the mesh role is an interactive mesh host
(D38): it enforces the desktop class, and the composition of its settings (including
`split_lock_mitigate=0`, which lets a local process stall other cores while guests run)
is defined with the mesh specification (D27). Until then the validator rejects the
combination.

**Purpose of the mesh** (D26, D38; after 1.0). The mesh joins the devices of one owner:
a private network over kernel WireGuard with an existing coordination server;
synchronisation and backup between nodes (Syncthing-class sync, btrfs send and receive);
compute sharing by capability tier (D28); remote applications from interactive hosts
(D29). Mesh hosts hold data and run workloads; clients (phones, other systems, degraded
machines) connect with limited keys. The mesh never distributes updates. Protocol,
identity, discovery and scheduling belong to the mesh specification (D27).

**Platform requirements of the mesh**, enabled in the kernel today and asserted by the
boot matrix from P2: WireGuard, KVM (AMD and Intel), vhost-vsock, virtio-fs, virtio-gpu
with `udmabuf`, VFIO for the optional GPU tier, and the TPM and attestation chain of
section 9. The virtual machine monitor is chosen once, in the mesh specification. GPU
inference stacks that compile code into writable caches do not run on the mesh class.

**Assignment.** Roles are chosen at installation (a kickstart variable) and changed with
`athanor-role add|remove`, which installs or removes signed addons, refuses the mesh
role when the machine is not attested, and states when a reboot is needed. IPE allows a
single active policy, so a signed policy is generated at build time for every allowed
role combination, with a version ordered by class (D8); removing a role that lowers the
class takes effect at the next boot.

## 8. Image, boot and updates

**Boot requirements.** UEFI is required; the installer refuses legacy BIOS and CSM
boot. systemd-boot is installed as shim's second stage, and its installation and updates
belong to the update chain (P4b), because bootc does not update the boot loader after
installation.

**Disk layout** (installation creates it): ESP of 2 GiB when Athanor owns the disk, or
XBOOTLDR next to an existing ESP (D17); the image slots per D6, each sized to twice the
largest image built in P4b; root and data on btrfs inside LUKS (`/`, `/var`, `/home`
subvolumes); `/etc` per D39.

**Image build.** The existing OCI build (GitHub Actions, dnf5, tier repositories, cosign,
SBOM) stays the source of the root filesystem and of provenance. With the dm-verity
option a new stage produces with `systemd-repart` a `/usr` image (EROFS, reproducible:
fixed timestamps, stable file order, compression per block) with its verity and signed
root hash partitions; for either option a UKI is built with `ukify` (`usrhash=` or the
composefs digest, base command line, the compatibility profile of D45, PCR 11 policy
signed for the initrd phase, SBAT section) and role addons with the addon stub. Signing
happens only in sign-only jobs (D43).

**Minimal initramfs** (D17): generic, never host-only, with `athanor-cpu-check` (D14).
The `bcachefs` userspace tools leave the image.

**Boot counting.** UKIs are installed with three tries (`+3`). `boot-complete.target`
requires `athanor-profile-check` and the critical services; `systemd-bless-boot` marks a
good boot; after three failed boots, panic reboots included, the previous version boots.
Only drift attributable to the image fails `boot-complete.target`: degraded mode and
hardware findings (a missing TPM, firmware that does not mark external ports) are
reported, never failed, so no machine is locked out of updates by its hardware.

**Release 1.0 updates** (D31 classes A and D, D36, D41):

1. Applications update through Flatpak with no interruption (class A).
2. A system update is a full image, downloaded and verified in the background. S1 chooses
   one verification path: `systemd-sysupdate` with a `url-file` source and `Verify=yes`,
   with its OpenPGP keyring only in `/usr` and `/etc/systemd/import-pubring.*` masked and
   checked by `athanor-profile-check`; or an Athanor verifier with the integrity key
   followed by a `regular-file` source, which performs no verification itself, run in
   one root-only service over a staging directory so the verified image cannot be
   replaced before it is written. With bootc, `bootc upgrade --download-only` stages a
   deployment that is locked against being applied.
3. The new version is installed but does not become the boot default until the user
   confirms. With systemd-boot, `LoaderEntryPreferred` keeps the running entry preferred
   and moves to the new entry on confirmation; `LoaderEntryDefault` is never used,
   because it ignores boot assessment. With bootc, `bootc upgrade --from-downloaded`
   unlocks the staged deployment on confirmation. A reboot or crash before confirmation
   boots the running version. The previous version stays in the boot menu, and
   `LoaderEntryOneShot` selects it for one boot. Nothing reboots by itself (class D).
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
  desktop layer merges only at boot or at a soft reboot. Image policies follow D32.
  `systemd-sysupdate-notify-sysext.socket` (systemd 262) stays disabled.
- **Selection and rollback** (D35): layers are stored per base version and selected from
  the booted base (its root hash), not from `SYSEXT_LEVEL` alone, which only skips a
  mismatching layer.
- **Measurement:** the verity NvPCR exists from systemd 260; from 262 its definitions ship
  inside the UKI, which then needs signed initrd-phase PCR policies.
- **Interface:** the update interface is built on the Varlink API of `systemd-sysupdate`,
  which today lists targets and checks for new versions only; the D-Bus API of
  `systemd-sysupdated` is removed in systemd 263.
- **Channels and rollout** (D33, D34): signed channel manifests with expiry; rollout day
  from an application-specific identifier derived from `machine-id` and the release
  version; a signed stop manifest; security releases skip the window.

**Prerequisites.** `systemd-sysupdate` was marked experimental again in systemd 262
("more breaking changes are forthcoming"), and `LoaderEntryPreferred` needs systemd 260;
the dm-verity option of D6 depends on both, which S1 weighs on Fedora 45.
`RestrictFileSystemAccess=` (systemd 261) allows execution only from signed dm-verity;
systemd 262 extends this to overlayfs over verity on kernel 7.2 and later.

## 9. Keys, measurements and attestation

| Key | Signs | Trusted by | Custody (D43) |
| --- | --- | --- | --- |
| Secure Boot (`SECUREBOOT_SIGNING_KEY`) | systemd-boot, UKIs and their profiles, role addons, PCR 11 policy | shim via MokList | `signing` environment, sign-only job |
| Module signing (`MODULE_SIGNING_KEY`) | external kernel modules (NVIDIA) | kernel, builtin certificate | own environment with required reviewers, shared with the integrity key |
| Integrity (new, P4b) | image root hashes, IPE policies, the IMA policy, update manifests | kernel, builtin certificate | own environment with required reviewers |
| Update (new, P4b, OpenPGP; only if S1 selects `url-file` with `Verify=yes`) | `SHA256SUMS` of the image source of `systemd-sysupdate` | the keyring shipped in `/usr` | as the integrity key |

The integrity key signs root hashes and policies because both decide which code may run;
the module key could sign them too, because both are builtin, hence the shared custody.
**Revocation and rollback** (D41): `keys/revoked/` covers compiled-in certificates for the
kernels built after the revocation; superseded UKIs are revoked through MokListX hashes
or a rotation of the Secure Boot key, together with a rotation of the PCR policy key;
manifests carry an expiry and a minimum version.

**Measurements:** PCR 7 (Secure Boot state and the authorities used, including db, dbx,
MOK and shim's built-in certificate), PCR 11 (UKI sections, including `usrhash=`), PCR 12
(command line, addons, credentials), PCR 13 (system extensions), PCR 14 (MokList,
MokListX, MokSBState), PCR 15 (machine identity, root file system, LUKS volume key), the
verity NvPCR (after 1.0, with layers), IMA log (D23).

**LUKS** (D42): in attested mode, TPM 2.0 policy through `systemd-pcrlock` on PCR 7 and
PCR 14 plus the signed PCR 11 policy (initrd phase only), never PCR 12, so role changes do
not require resealing; in degraded mode TPM plus PIN, or a passphrase. A recovery key is
always enrolled.

**Attestation** (restricted area): admission of a mesh host requires its identity and a
verified TPM quote (D38). Keylime's example measured-boot policy considers PCRs 0–9 and
14 only, so a dedicated policy covers PCR 11 and the command line events of the allowed
role sets in PCR 12. The attestation code in the repository today returns fixed results
and quotes the wrong PCRs; it is replaced, with the maintainer's approval, before any
mesh admission depends on it.

## 10. Execution integrity and security primitives

**IPE policies** (D8, with the dm-verity option). IPE operations are `EXECUTE` (including
executable mappings of files and of anonymous memory), `FIRMWARE`, `KMODULE`,
`KEXEC_IMAGE`, `KEXEC_INITRAMFS`, `POLICY` (policy files the kernel reads, such as the
IMA policy) and `X509_CERT` (certificates the kernel reads, such as the IMA certificate).
Loading an IPE policy is controlled by its signature (D40), not by an operation. IPE's
audit or enforce state is global, not per operation.

- **Boot policy** (compiled into the kernel from P4b): `EXECUTE` defaults to allow;
  `FIRMWARE`, `KMODULE`, `KEXEC_*`, `POLICY` and `X509_CERT` default to deny, admitting
  `boot_verified=TRUE` (the initramfs) and `dmverity_signature=TRUE`. It becomes
  default-deny for `EXECUTE` only through the mesh class in P6. Firmware built into the
  kernel does not pass through IPE.
- **Runtime class policies** do not use `boot_verified`, as IPE's documentation advises
  after switch-root. Each class has a version whose major number is its class (desktop 1,
  mesh 2) and whose minor number is its release, so a running machine can only activate
  an equal or stronger class (D8).
- **Mesh class:** `DEFAULT action=DENY` for every operation, allowing only
  `dmverity_signature=TRUE`. Anonymous executable memory is denied as well, so no
  user-space JIT runs on a mesh-only host; workloads of other nodes run in virtual
  machines. The BPF JIT is a kernel component and stays on with `bpf_jit_harden=2`.
- **Desktop class:** `EXECUTE` defaults to allow, because browsers, Mesa and development
  tools need it; code in the home runs and is measured by IMA (D23). `KMODULE`:
  `dmverity_signature=TRUE` allowed, then default deny, so modules outside the image are
  refused even when signed. `FIRMWARE`, `KEXEC_*`, `POLICY` and `X509_CERT` as in the boot
  policy. SELinux denies `execmem` to system and Athanor service domains except those
  declared; user applications stay in `unconfined_t` as in Fedora (D24).
- **`user-modules` variant** of the desktop class (D40): `KMODULE` defaults to allow, the
  module signature is still enforced by lockdown against the builtin and secondary
  keyrings, and the machine is reported as not attested.
- **Rollout:** release 1.0 enforces the boot policy and the desktop class (D36). Coverage
  of a default-deny `EXECUTE` table is measured in acceptance with `ipe.enforce=0` and the
  full class policy, never on deployed machines; the mesh class is enforced in P6.
- **Root boundary** (D44): the Azoth patch makes `enforce` one-way once enforcing, and
  class-ordered versions prevent activating a weaker signed policy.

**Gatekeeper** (restricted area): leaves the blocking path (`FAN_OPEN_EXEC_PERM`), where a
hung daemon blocks the system and a dead one disables protection; it may remain an audit
consumer. Its new specification is written separately and approved before any change.
No custom BPF LSM is written. `RestrictFileSystemAccess=` is a per-service second layer
(section 8, prerequisites).

**Application self-confinement:** Landlock (ABI 10 on Linux 7.2, negotiated best-effort)
is a platform rule; Athanor applications declare filesystem, network and IPC access
through a shared crate `athanor-sandbox` over the `landlock` crate. Services also use
systemd sandboxing.

**eBPF without root:** unprivileged BPF stays off. Services receive BPF tokens with
`PrivateBPF=yes`, `PrivateUsers=` (a token cannot be created in the initial user
namespace) and comma-separated delegation lists, for example
`BPFDelegateCommands=BPFMapCreate,BPFProgLoad,BPFTokenCreate`,
`BPFDelegateMaps=BPFMapTypeXskmap`, `BPFDelegatePrograms=BPFProgTypeXdp`,
`BPFDelegateAttachments=BPFXdp` (syntax verified with systemd 258). A service holding an
XDP token can attach through `BPF_LINK_CREATE` to any interface of its own network
namespace without further capability checks, so a service delegated
`BPFProgTypeXdp` runs with `PrivateNetwork=` or a dedicated network namespace. Signed BPF
programs are trusted only from the builtin keyring (D40).

**io_uring:** disabled except for services given the `athanor-io-uring` group and
processes with `CAP_SYS_ADMIN`.

**User namespaces:** available (Flatpak, rootless podman, browser sandboxes). The loaded
SELinux policy exposes `user_namespace create`, so creation is restricted per system
domain through SELinux; services also set `RestrictNamespaces=`.

**Network:** per-service `IPAddressAllow=`/`IPAddressDeny=`, `RestrictNetworkInterfaces=`,
`SocketBindAllow=`, and host nftables. Tetragon leaves the image.

**Residual risks, stated:**

- A script passed to a verified interpreter escapes IPE (no widespread interpreter uses
  `AT_EXECVE_CHECK` yet).
- On the desktop class, JIT and code in the home remain allowed; the quarantine prompt of
  D23 is bypassable from a terminal; nothing comparable to macOS Gatekeeper or Windows
  Smart App Control exists yet.
- Code running as the user persists through autostart entries, `systemd --user` units and
  shell startup files; a Flatpak application with home access can write those files and
  leave its sandbox.
- Unconfined user code can create user namespaces and reach kernel code gated by
  in-namespace capabilities, such as `nf_tables`.
- An unconfined root is not bounded by SELinux under Fedora's targeted policy (D44), keeps
  persistence in `/etc` and `/var`, and can mount an older image signed with a valid
  integrity key until kernels carrying the revocation are deployed.
- Any builtin key can sign modules, IPE policies and root hashes (D43).
- Degraded machines have no boot-chain guarantees (section 4).
- IPE has almost no production experience in enforcement.
- Linux has no hypervisor-isolated code integrity comparable to Windows HVCI or Apple's
  kernel page protection.
- TPM-only unlock on an attested machine is exposed to TPM bus sniffing and DMA attacks,
  as with BitLocker without a PIN.

## 11. Reliability

A panic reboots after 10 seconds; three failed boots fall back to the previous version;
on mesh-only hosts an oops or repeated warnings become a panic, on interactive roles
repeated oops do (D19). Crash evidence comes from EFI pstore archived by
`systemd-pstore`, the persistent journal and `DRM_PANIC` with its QR code where the GPU
driver supports it; acceptance verifies that a deliberate panic leaves a pstore record.
There is no kdump.

## 12. Verification

1. **CI, no VM:** the `profile.toml` validator over every role combination;
   `check_delta` on the kernel configuration (existing); the bump bot fails while the
   pinned series is end of life (D37); `scripts/verify.py workflows` fails if a signing
   secret reaches a job that runs third-party actions or a build step (D43).
2. **Kernel boot matrix** (`forge/specs/azoth/boot.sh`, with the external module chain in
   `nvidia-kmod.yml`): CPU models Penryn (x86-64-v1, no POPCNT or SSE4.2; D14) and host;
   an Intel IOMMU case (`-device intel-iommu,intremap=on` with `kernel-irqchip=split`) and
   an AMD IOMMU case; assertions for forced lockdown, the preemption mode from the
   `Dynamic Preempt:` line of the kernel log (debugfs is not available), the IOMMU domain
   type, ASLR bits, the exact set of builtin certificates, `keyring_unsealed` reading `N`
   with an empty `.dm-verity` keyring, the mesh platform requirements of section 7; the
   module chain: a module signed by the module key accepted, one signed by an enrolled
   non-CA MOK rejected (existing), one signed directly by an enrolled CA key accepted and
   one signed by a leaf certificate of that CA rejected (D40). From P4b the IPE boot
   policy is active; from P5, under Secure Boot, an unsigned addon is rejected.
3. **ISO acceptance** (`forge/test/iso`) on a hardware matrix (NVMe, VMD, eMMC, a laptop
   with an I2C keyboard, a Thunderbolt dock, a Hyper-V guest; D17): a required
   `profile-ok` marker emitted by `athanor-profile-check`, whose failure report lists the
   drifting settings; the installer refuses a CPU without x86-64-v3 and a non-UEFI boot;
   `athanor-cpu-check` stops an unsupported CPU with its message; a deliberate panic
   leaves a pstore record; zero AVC denials in Athanor domains, with Fedora denials
   triaged (D20). The base profile runs on every acceptance, and from P5 the desktop role
   on every run and the laptop role weekly.
4. **On the machine:** `athanor-profile-check` gates `boot-complete.target` on
   image-attributable drift only and reports the rest: `/proc/config.gz`,
   `/proc/cmdline`, sysctls, `scx_loader` state, integrity mode, the contents of
   `.machine` and `.secondary_trusted_keys`, external PCIe ports marked untrusted (D16),
   the absence of `/etc/systemd/import-pubring.*` where applicable, and, when a TPM is
   present, that the roles applied under `/run` match the role addons in the PCR 12 event
   log.
5. **Release 1.0 updates** (P4b, in a VM with Secure Boot and swtpm): an image with an
   invalid signature, an expired manifest and a version below the minimum are refused; a
   new version does not become the boot default before the user confirms; a reboot and a
   crash without confirmation boot the running version; the previous version boots once
   from the menu; a deliberately failing health check returns to the previous version; the
   new default entry finds the addons of the active roles (from P5); TPM-only unlock is
   refused in degraded mode; a PCR 7 change not announced to `systemd-pcrlock` falls back
   to the recovery key and the guided reseal keeps the chosen unlock method; the
   installer refuses firmware whose db does not accept the shim's certificate authority.
6. **Execution integrity** (P6): a module outside the image and an unsigned module are
   refused on the desktop class; firmware outside the image is refused; `enforce=0` is
   refused once enforcing; activating a signed policy of a lower class is refused; a
   system domain calling `mprotect(PROT_EXEC)` on anonymous memory is denied (D24); an XDP
   program of a delegated service cannot attach to a host interface; on the mesh class,
   execution outside the image and anonymous executable memory are denied.
7. **Attestation** of mesh hosts (restricted area, after 1.0).

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

- **NVIDIA** does not load on the deployed image (`Key was rejected by service`,
  `systemd-modules-load.service` failed, nouveau in use): its modules are signed by the
  retired MOK, which the running kernel cannot verify with Secure Boot disabled, and the
  image predates the new module certificate. The cut-over is the redeploy after the
  release chain; `MOK_PRIVATE_KEY` is deleted once a deployed system loads `nvidia`
  signed by the module signing key (task 9 of
  `docs/superpowers/plans/2026-09-13-signing-key-rotation.md`). Until then `cosmic-comp`
  floods the journal with `VRR_ENABLED` warnings under nouveau.
- **Kernel series:** Azoth is pinned to 7.1.8 while 7.1 is end of life; the bump bot, now
  scheduled from `iso-v0`, moves it to 7.2 (D37).
- **CI signing:** the Secure Boot key is used in the same job as the image build and
  third-party actions (D43).
- **Base configuration:** `ermete-base-config` is still installed and duplicates
  `10-ermete.conf` (scx_loader), `99-ermete-slim-boot.conf`, `99-Ermete-Base.preset` and
  `10-ermete-hw-groups.conf`; `athanor-base-config` does not obsolete it yet, and P3 adds
  `Obsoletes: ermete-base-config`. `athanor-base-config` also ships NVIDIA dracut and
  kargs configuration to every machine (P3, section 6), and overrides
  `bootc-fetch-apply-updates` to stage updates automatically, which conflicts with the
  confirmation of section 8 once enabled (disabled on the maintainer's machine).
- **Command line sources:** `kargs.d` 02–06, `system/athanor-install.ks` (`iommu=pt`,
  `pti=on`, `zswap.enabled=1`, ...) and `forge/specs/azoth/cmdline`, which the boot
  matrix uses with `zswap.enabled=1`, `lockdown=` and `preempt=full`: all aligned to
  section 6 (P3; the boot matrix command line in P2).
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
- **Snapshots:** `athanor-timewarp` targets bcachefs, which left mainline in Linux 6.18,
  and misdetects `/var/home` as tmpfs; `athanor-backup-hourly` fails because
  `athanor-backup` is disabled. Both are ported to btrfs subvolume snapshots.
- **LUKS script:** `athanor-tpm-luks-seal.sh` has a syntax error (`|| {` after `fi`) and
  binds LUKS to PCRs 0, 2, 7 and 11: it is replaced by the LUKS policy of D42 (P4b).
- **Boot ordering:** udev reports unknown groups (`disk`, `kvm`, `render`, `audio`, `lp`
  and others) and tmpfiles cannot apply the journal ACLs early in boot (P3).
- **Desktop:** `cosmic-panel.service`, shipped by `athanor-system-services`, sets
  `MemoryHigh=1G` and `MemoryMax=1536M`, which kill the panel under normal use; the limits
  are removed in that package (P3).
- **Mesh code:** `athanor-mesh-sync`, `athanor-cluster-mesh` and `athanor-mesh-bus` are
  workspace members excluded from the package DAG (`experimental/EXEMPT`);
  `athanor-mesh-sync` returns all-zero Kyber and Dilithium public keys while logging
  post-quantum key exchange, and the attestation code reports success from the existence
  of a device file. They are removed or made to fail explicitly before any mesh crate
  re-enters the DAG (D38). `doc_cloud_mesh.md` is replaced by the mesh specification
  (D27).
- **Retirements:** `athanor-ebpf-sched` (contains an AI model contradicting
  `doc_kernel_layer.md`) is retired as a scheduler.
- **Userland flags:** `forge/config/rpmmacros` includes `-mlam=u48`, an Intel-only
  feature, for every CPU vendor: reviewed with the Forge pipeline.
- **Maintainer machine:** Secure Boot is disabled; MokList holds the Fedora CA, a uBlue
  kernel key, three akmods keys and three retired Ermete OS certificates, including the
  retired project MOK, while the new Athanor Secure Boot certificate is not enrolled. The
  machine is cleaned up at the reinstallation.

## 15. Implementation blocks

A new block group P in `NEXT.md` (Italian heading `BLOCCO P`); no block starts before the
previous gate is green.

**Immediate, independent of P0**, each with its own gate:

| Item | Gate |
| --- | --- |
| Release chain of pull request #25 and the NVIDIA cut-over | NVIDIA kmod green, `modinfo -F signer nvidia` on the redeployed machine names the module signing key |
| Pull request #26 (D37) and the 7.2 bump | the bump pull request merged with the Kernel gate green |
| Sign-only CI jobs (D43) | the `verify.py workflows` check of section 12 item 1 green |

| Block | Content | Gate |
| --- | --- | --- |
| P0 | this specification | maintainer approval |
| S1 | spike, no time box, on Fedora 45 (beta, systemd 262): bootc sealed composefs with UKI against dm-verity with `systemd-sysupdate`, built and exercised in a VM with Secure Boot and swtpm; covers `/etc` (D39), boot counting, the confirmation of section 8, fallback, update and rollback, the verification path and the update key, IPE coverage, signing and maintenance cost | a written comparison with measurements; D6 and D39 closed by the maintainer. Runs alongside P1–P4a; P4b waits for it |
| P1 | `profile.toml`, validator, `athanor-profile-check` covering settings already in force; later blocks extend it | acceptance with `profile-ok` |
| P2 | kernel build profile (section 5) without the items marked P4b, P5 or P6; the boot matrix of section 12 item 2 without its P4b and P5 parts, with its command line aligned to section 6 | Kernel gate green |
| P3 | `athanor-kernel-profile` base package, removal of old `kargs.d`, `99-bore.conf` and the kickstart command line, zram, NVIDIA configuration by detection, the clean-ups of section 14 marked P3 | acceptance `profile-ok` on the base profile |
| P4a | rebase on Fedora 45, starting on the beta as soon as P3 is green (D25) | full DAG, image and acceptance green; the reinstall image waits for the final release |
| P4b | the release 1.0 update chain on the mechanism chosen by S1: systemd-boot as shim's second stage and its updates, UKIs with the compatibility profile, verified images, boot counting, full-image updates with manifest expiry and minimum version, confirmation before the new default, `/etc` per D39, generic minimal initramfs with `athanor-cpu-check`, ESP or XBOOTLDR, integrity key (generated offline by the maintainer), `DM_VERITY=y` and the IPE boot policy if dm-verity is chosen, LUKS per D42, signed IMA policy | section 12 item 5 green in a VM with Secure Boot and swtpm, without its P5 part |
| P5 | roles and their addons per UKI, generator, composition and precedence, `athanor-role`, `IA32_EMULATION_DEFAULT_DISABLED` with the interactive addons | validator over every combination; section 12 items 2 and 5 parts marked P5; acceptance desktop and laptop |
| P6 | IPE desktop class enforced with the `user-modules` variant, class-ordered policy versions, the one-way `enforce` patch (D44), the mesh class policy; the D20 gate and SELinux `DEVELOP`/`BOOTPARAM` off; SELinux `execmem` restrictions (D24); BPF token delegation, io_uring group, `athanor-sandbox` crate | section 12 items 3 (AVC) and 6 green |
| P7 | benchmarks, AutoFDO, closing the provisional decisions | no decision left provisional; report |
| 1.0 | release gate | P1–P7 green; acceptance on real hardware of more than one CPU vendor |

After 1.0, each with its own specification and gates: deltas, layers and update classes B
and C, channels and gradual rollout (releases 1.1 and 1.2, section 8); the mesh
specification (D27), then the mesh network, sync and backup with the two tiers of D38;
later compute sharing and remote applications once their prerequisites (D28, D29) hold.

After P5 is green in a VM: backup of `/var/home` and reinstallation of the maintainer's
desktop on the new image.

## 16. Sources

Verified during the design and its verification (2026-09-13/14):

- Kernel v7.2 (and v7.1 where compared): `init/Kconfig` (`RUST` dependencies),
  `arch/Kconfig` (`AUTOFDO_CLANG`, `PROPELLER_CLANG`), `arch/x86/Makefile`,
  `kernel/Kconfig.preempt`, `kernel/sched/core.c` (`Dynamic Preempt:`), `certs/Kconfig`,
  `certs/system_keyring.c`, `certs/blacklist.c`, `crypto/asymmetric_keys/restrict.c` and
  `pkcs7_trust.c`, `security/integrity/Kconfig`, `security/integrity/platform_certs/machine_keyring.c`,
  `security/integrity/ima/ima_efi.c`, `security/integrity/digsig.c`, `security/ipe/*`
  (`fs.c`, `eval.c`, `policy.c`, `policy_parser.c`, `audit.c`),
  `Documentation/admin-guide/LSM/ipe.rst`, `drivers/md/dm-verity-verify-sig.c`,
  `drivers/firmware/efi/Kconfig` and `efi-pstore.c`, `drivers/block/zram/zram_drv.c`,
  `drivers/iommu/iommu.c` and `dma-iommu.c`, `arch/x86/kernel/dumpstack.c` and
  `kernel/exit.c`, `kernel/kexec_file.c`, `kernel/liveupdate/Kconfig`,
  `kernel/module/signing.c` (upstream and Red Hat patch `patch-7.1-redhat.patch` of
  kernel 7.1.8-100.fc43), `kernel/bpf/token.c` and `syscall.c`, `net/core/dev.c`,
  `io_uring/io_uring.c`, `security/landlock/syscalls.c`, `mm/Kconfig`,
  `scripts/sign-file.c`; commits f2c61db29f27 (bcachefs removal), 0c8c88b8eb82
  (overlayfs verity fix); kernel.org `releases.json` (7.1 end of life on 2026-09-02);
  the running configuration of Azoth 7.1.8 and the NVIDIA kmod boot run 34834656982.
- systemd: v258 `man/systemd-stub.xml`, `man/systemd-boot.xml`, `man/sysupdate.d.xml`,
  `man/systemd.exec.xml`, `src/core/exec-invoke.c`, `docs/TPM2_PCR_MEASUREMENTS.md`;
  main `src/boot/boot.c` and `src/boot/stub.c` (entry sorting, `LoaderEntryPreferred`,
  addon locations); v262-rc2 `man/systemd-sysext.xml`, `man/kernel-command-line.xml`,
  `man/systemd-cryptenroll.xml`, `man/ukify.xml`; `NEWS` for 260–262; Fedora systemd
  versions (F43 258.10, F44 259.8, F45 262~rc1).
- bootc: `docs/src/experimental-composefs.md`, `bootloaders.md`, `filesystem.md`,
  `upgrades.md`, `boot-failure-detection.md`, `crates/lib/src/bootc_composefs/update.rs`,
  issues #7, #1976, #2079, #2174; composefs issue #360.
- shim `README.tpm`, `mok.c`, `SbatLevel_Variable.txt`, Fedora `shim-unsigned-x64.spec`;
  Red Hat article on the Microsoft UEFI CA 2011 expiry; Keylime measured boot
  documentation and `example.py`; Azure Linux OS Guard documentation;
  power-profiles-daemon README.
- Fedora `selinux-policy-targeted` 43.8 (queried with setools on the running system).
- desync README and releases (v1.1.3); RAUC advanced documentation; CachyOS
  `linux-cachyos/PKGBUILD` and `kernel-patches` at the pinned commits (BORE 6.6.3 on 7.1,
  6.8.0 on 7.2); Mesa Venus documentation; `drivers/gpu/drm/xe/xe_pci.c` (SR-IOV
  platforms); cosmic-comp and xdg-desktop-portal-cosmic issues on remote desktop and
  virtual outputs; QEMU `target/i386/cpu.c` (CPU model features).
- kernel-hardening-checker runs on the installed system.

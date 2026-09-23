# Shell 1b-system: Updates and Trust State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an Athanor machine download signed system images by itself, apply them only on the user's word, verify them against a key on disk, and publish one root-owned state file from which the greeter, the shield and the notifier compute the trust badge.

**Architecture:** One root binary, `athanor-update` (`check`, `serve`, `migrate`, `recover-key`), drives bootc, skopeo and ostree behind a small trait, so the logic of the check and of the two requests is unit-tested with fakes; it verifies the stored cosign signature object itself with `p256` and publishes `/run/athanor-update/state.json`. A library crate, `athanor-trust-state`, owns the schema, the hardened reader and the badge rule, so the rule exists once. The signature policy is rendered from templates at image build time from the registry variable and the public keys committed under `system/keys/`, and the pipeline adds a key-based signature in a job that holds the key and does nothing else. Everything is developed and tested with throwaway keys; the real key enters in one maintainer step, and only the last task (the cut-over) needs it.

**Tech Stack:** Rust 1.98 (workspace crates: `zbus` 5 on `tokio`, `serde`, `serde_json`, `sha2`, `hex`, `clap`, `tracing`; already in `Cargo.lock`: `p256` 0.13.2 with `ecdsa` and `pem`, `base64` 0.21, `chrono` 0.4, `landlock` 0.4.7); `athanor_bus_api::polkit::check_polkit_auth_zbus`; bash with `skopeo` 1.22, `podman`, `gh`, `jq`; Python 3 standard library `unittest`; systemd 258, bootc 1.16, containers-common 0.67; `actionlint`; the dev VM of `scripts/devvm/`.

**Spec:** `docs/architecture/doc_update_trust.md` revision 3 (UT1 to UT12, D1 to D3, acceptance 1 to 15), under `docs/architecture/doc_shell.md` SH11, SH12 and its nine constraints. Evidence: `.superpowers/spike-u1-update-trust.md`, `.superpowers/spike-u1/`, `.superpowers/update-trust-security-review.md`.

## Global Constraints

Copied from the spec and from `CLAUDE.md`, `.claude/rules/security.md`, `.claude/rules/ci.md`. Every task's requirements include this section.

- Commit messages, code comments, workflow output and new documentation are in English, enterprise tone. One commit per problem.
- Formal, idiomatic solutions. No `|| true`, no `continue-on-error`, no band-aid that hides a failure.
- Portable pipeline: logic lives in scripts under the repository; workflow YAML checks out, calls them and uploads their output; no `run:` block beyond a few lines; steps exchange data through files in a known directory. No literal `ghcr.io/hr-mes` in new code: a variable with a default.
- Workflows are validated locally before a commit: `actionlint`, `python3 scripts/verify.py workflows`, `bash -n` on every non-trivial `run:` block. Never a step with only `name:`. Never an empty `if … then … fi`.
- Python tests live under `<area>/tests/` and run with `python3 -B -m unittest discover -s <dir>`. Rust tests run with `cargo test -p <crate>`.
- No placeholder implementation in a security path: cryptography, signature and hash checks are real. `panic = "abort"` on dev and release: no `unwrap`/`expect` outside tests. The workspace builds with `-D unsafe_code`.
- **Read-only paths:** `system/athanor-bus-api/src/polkit.rs`, `forge/specs/athanor-gatekeeper-rs`, `system/confidential_computing/athanor-attestation`. This plan edits none of them; it only calls `athanor_bus_api::polkit::check_polkit_auth_zbus(conn, sender, action_id, allow_user_interaction)`.
- Never `cd` in a command; paths are relative to the repository root. Never open `docs/architecture/graph-vaults/`. Scratch files go to `/.scratch/`. Do not rename anything. `just all` is not run without asking.
- The polkit subject is the bus sender, "Never a PID from the caller, never `unix_process`." Actions are `os.athanor.update.apply` and `os.athanor.update.rollback`; "`Apply()`: `auth_admin_keep` / `auth_admin_keep` / `yes`"; "`GoBack()`: `auth_admin` for all three, never kept".
- Hardening of both services, verbatim from UT1: `NoNewPrivileges`, `ProtectHome`, `PrivateTmp`, `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups`, `ProtectProc=invisible`, `LockPersonality`, `MemoryDenyWriteExecute`, `UMask=0022`, `SystemCallFilter=@system-service @mount`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK`, `RestrictNamespaces=~user`, `CapabilityBoundingSet=~CAP_SYS_MODULE CAP_SYS_BOOT CAP_SYS_RAWIO CAP_NET_ADMIN`. Never `RestrictSUIDSGID`, never an allow-list `CapabilityBoundingSet`, never `ProtectSystem=strict`. The serve unit adds `PrivateNetwork=yes`; the check unit carries neither that nor `IPAddressDeny=any`.
- "`default` is `reject`"; `transports.docker[""]` and `docker-archive`, `oci`, `oci-archive`, `dir`, `containers-storage`, `docker-daemon` are `insecureAcceptAnything`; the three system image repositories are `sigstoreSigned` with a `keyPaths` list and `matchRepository`. Our `registries.d` file declares only the three repositories.
- The signature is the classic cosign attachment at `<repo>:sha256-<hex>.sig`, made with `skopeo copy --sign-by-sigstore-private-key` through `retry.sh`, verified by `skopeo copy --policy <the shipped policy>`, "not `cosign verify`". "The key is alone in its job." "The agent never sees the private key" (D3).
- The verifier: every key of the policy's `keyPaths` against every layer; the signed bytes are the payload blob as stored, checked against its descriptor's SHA-256; base64 ASN.1 DER read with `from_der`; `critical.type` must be `cosign container image signature`, "a missing or unknown field is a refusal"; digest and repository compared, the tag never.
- The check "offers and downloads only a digest whose `org.opencontainers.image.created` is strictly newer than the booted deployment's". Booted build time: `status.booted.image.timestamp` of `bootc status --format json`; candidate: `skopeo inspect --config`. Never `bootc upgrade --check` output, never `status.booted.cachedUpdate`.
- State file: `/run/athanor-update/state.json`, `0644 root root`, temporary name then rename; readers use `O_NOFOLLOW` and check the owner. Closed lists: reasons `signature`, `media`, `no-signature`, `key-not-in-policy`, `policy-not-in-force`, `reference-out-of-scope`; states `none`, `available`, `downloaded`, `will-apply-at-next-shutdown`, `refused`, `held`, `older-than-booted`; error codes `none`, `network`, `registry`, `policy`, `storage`, `internal`. "No raw error text and no URL ever enters the file." `/run/athanor` is not used.
- The badge (SH12): check = verified, newest the machine has booted, last successful check at most 14 days old; cross = the last download was refused by the policy; exclamation mark otherwise. `older-than-booted` "is not a badge state". Secure Boot readings never move the badge.
- `Apply()` never downloads, calls `login1.Manager.Reboot(false)`, never `RebootWithFlags` with the skip-inhibitors flag, never `CanReboot`; on a refusal after the unlock it runs `ostree admin lock-finalization`.
- Host limit: 31 GB host, 16 GB CI runner guest, 8 GB dev VM. **The dev VM must not run while a CI job runs on the self-hosted runner.**

## Preconditions

1. **Branch.** Work on a new branch `shell-1b-system` created from `origin/iso-v0`. If the executor runs in a git worktree, check out `origin/iso-v0` first and record its commit: worktrees start from a stale `main`.
2. **PR #49 (`build-ordering`) is merged into `iso-v0`.** Tasks 11 to 14 build on files that exist only there: `system/tests/fake_registry.py`, `system/tests/test_kernel_artifacts.py` (class `Tool`), `system/tests/test_build_image.py`, `system/tests/test_clean_ghcr.py`, and its rewrite of `forge/scripts/clean_ghcr.sh` and `system/build-image.sh`. Check: `test -f system/tests/fake_registry.py && test -f system/tests/test_clean_ghcr.py`. If the check fails, do Tasks 1 to 10 and stop; do not re-create those files.
3. **Plan 1a runs in parallel** (`.claude/worktrees/shell-1a`, do not touch it). Both plans edit the root `Cargo.toml` members list, `Cargo.lock`, `scripts/verify.py` (`check_shipped`) and `.github/workflows/call-lint.yml`. This plan keeps its additions in functions and files of its own (`scripts/tests/test_verify_update_trust.py`), so the merge is textual.
4. **Rust builds run in a container**: the host has no C linker. Define once per shell session, and use wherever a step says `cargo-in-box`:

```bash
cargo-in-box() {
    podman run --rm --memory 6g --security-opt label=disable \
        -v "$PWD:/repo" -v athanor-cargo-registry:/root/.cargo/registry \
        -e CARGO_TARGET_DIR=/repo/target -w /repo localhost/p2-gtk-bump:fedora43 cargo "$@"
}
```

   (`localhost/p2-gtk-bump:fedora43` is the image spike P2 left on the host; plan 1a's `localhost/athanor-shell-rig:build` works as well. It needs `rust`, `cargo`, `clippy`, `gcc`.)

## Architecture decisions the spec leaves to the plan

**A1. Crate locations.** Verified against the tree: libraries live in `system/` (`system/athanor-bus-api`, `system/athanor-style`, plan 1a's `system/athanor-i18n`); packaged programs live in `forge/specs/<name>/<name>-<version>/` and are built in place by their spec with `cargo build --release --locked -p %{name}` (`forge/specs/athanor-backup/athanor-backup.spec`). Therefore `system/athanor-trust-state` (library), `forge/specs/athanor-update/athanor-update-1.0.0` (root binary) and `forge/specs/athanor-update/athanor-update-notify-1.0.0` (user binary: one crate per program, SH4; one package, UT11). `scripts/verify.py shipped` today demands a spec directory named after every binary crate, so Task 9 teaches it that a crate is shipped when some spec in a tier builds it with `-p <crate>`.

**A2. The policy is rendered at image build time, by one script with three callers.** `forge/specs/athanor-update/SOURCES/usr/libexec/athanor-update/render-policy` (bash, no dependency) takes `--registry`, `--keys-dir`, `--out` and writes `policy.json`, `attachments-policy.json` and `registries.d/athanor.yaml` from the templates beside it; `keyPaths` is every `*.pub` of the keys directory, sorted. Callers: `system/Containerfile` (installed script, `IMAGE_REGISTRY` build argument that `build-image.sh` sets from its `--registry`, keys copied from `system/keys/`), the signing job (script from the checkout, so CI verifies with the policy a machine will have), and the dev VM acceptance (throwaway registry and key). Rotation is therefore a commit that adds or removes a file under `system/keys/`. **Deviation from UT3's wording:** the RPM ships the templates and the renderer; the rendered policy and the keys are image build output under `/usr`, not RPM payload, because the registry is an image build variable and a key must not need an RPM bump. `verify.py shipped` asserts the Containerfile wiring.

**A3. Files under `/var/lib/athanor-update/`** (0755 root, declared in `tmpfiles.d`): `held`, `refused`, `newest-booted`, `last-success`, `migrated`, `signatures/<hex>/`. One value per file, each replaced by rename. `refused` is persisted so the cross survives a reboot until "a later download passes the policy" (SH12).

**A4. "The policy is in force"** means: the bytes of `/etc/containers/policy.json` equal the bytes of `/usr/share/athanor/containers/policy.json` **and** the bytes of `/etc/containers/registries.d/athanor.yaml` equal the shipped entry. The second half is there because a dangling `registries.d` link is silently ignored and makes a signed image read as unsigned (spike U1, section 1b). containers/image prefers `$HOME/.config/containers/policy.json` (review, L2); the units run with `ProtectHome=yes`, which hides `/root`, so that path cannot shadow the policy for them.

**A5. The download gate.** The check talks to the registry and downloads only when the booted origin enforces the policy (`status.booted.image.image.signature == "containerPolicy"`) and the policy in force has a strict scope for the repository the machine follows. Before the migration nothing is downloaded: a root service does not fetch images nothing verifies. The policy need not be the shipped one, which is what lets the recovery of UT2 work.

**A6. `serve` exits when idle.** It counts requests in flight (a polkit prompt can last minutes), and after 60 s with none it releases the bus name, answers a call that raced the release, and returns; D-Bus activation starts it again.

**A7. A fourth system unit, `athanor-update-state.service`.** UT5 requires the verification "at boot before the network is up" and UT1's table has no unit for it. It runs `athanor-update check --offline` (no registry, no download) with the serve unit's hardening including `PrivateNetwork=yes`, before the display manager.

**A8. The units are tested under their own hardening twice.** In the repository, `forge/specs/athanor-update/tests/test_units.py` asserts the directive list of each unit file verbatim, the forbidden directives, and `systemd-analyze security --offline` below a threshold: measured on systemd 258 while writing this plan, the check unit scores **5.7** and the serve unit **5.3**; the thresholds are **6.0** and **5.5**. On the dev VM, acceptance 14 is acceptance 1 and 2 run through the real units (`systemctl start athanor-update-check.service`, `busctl call … Apply`), never through a shell.

**A9. The notifier writes one directory.** UT11 says "no write access", and also "one after the first boot into a new deployment", which needs a per-user record that outlives the session. The Landlock ruleset grants read on `/usr` and `/run/athanor-update` and write on `$XDG_STATE_HOME/athanor-update-notify` alone.

**A10. The migration never moves a machine back and never applies an update unconfirmed.** `migrate` reads the build time of `:stable` first and waits while it is older than the booted image; when it is newer, it locks the deployment `bootc switch` staged (`ostree admin lock-finalization`), so it waits for `Apply()` like any update.

## File Structure

| Path | Responsibility |
|---|---|
| `system/athanor-trust-state/{Cargo.toml,src/lib.rs}` | Create. Schema 1, closed lists, `O_NOFOLLOW` reader with owner check, `badge()`, `display()`. |
| `forge/specs/athanor-update/athanor-update-1.0.0/Cargo.toml` | Create. The root binary crate. |
| `…/src/sigobj.rs` | Create. Signature object verification (UT5's four rules). |
| `…/src/tools.rs` | Create. Trait `Tools`, the real bootc/skopeo/ostree/busctl calls, error classification. |
| `…/src/policy.rs` | Create. Policy in force, strict scopes, `keyPaths`. |
| `…/src/store.rs` | Create. Lock, persisted files, atomic state write. |
| `…/src/secureboot.rs` | Create. The four readings of UT8. |
| `…/src/check.rs` | Create. The check: reason, build-time rule, held digest, download, publication. |
| `…/src/requests.rs` | Create. `apply` and `go_back` over `Tools` and a `Power` trait. |
| `…/src/serve.rs` | Create. `os.athanor.Update1`, polkit, logind, idle exit. |
| `…/src/migrate.rs`, `…/src/recover.rs`, `…/src/main.rs` | Create. UT4, the recovery command of UT2, the command line. |
| `…/tests/vectors/{make.sh,made/,real/}`, `…/tests/state-verified.json` | Create. Test vectors: public material only. |
| `forge/specs/athanor-update/athanor-update-notify-1.0.0/{Cargo.toml,src/*.rs}` | Create. The notifier (UT11). |
| `forge/specs/athanor-update/SOURCES/…` | Create. Units, timer, presets, `tmpfiles.d`, D-Bus policy and activation, polkit policy, policy templates and renderer. |
| `forge/specs/athanor-update/athanor-update.spec`, `RECOVERY.md`, `tests/test_units.py`, `tests/test_render_policy.py` | Create. |
| `forge/config/packages.json` | Modify. `update` in `custom_packages` and `custom_tier3`. |
| `forge/specs/athanor-system-config/…/80-athanor-system.preset`, its spec | Modify. Remove `enable bootc-fetch-apply.timer`. |
| `forge/specs/athanor-base-config/…/bootc-fetch-apply-updates.service.d/override.conf`, its spec | Delete / modify. |
| `forge/specs/athanor-secure-boot/…` | Modify (D2): the daemon source, `athanor-secure-boot.service` and the measure script leave. |
| `scripts/verify.py`, `scripts/tests/test_verify_update_trust.py` | Modify / create. `shipped` assertions. |
| `system/build-image.sh`, `system/tests/test_build_image.py` | Modify. UT9 labels, `IMAGE_REGISTRY` build argument. |
| `system/sign-images.sh`, `system/tests/test_sign_images.py` | Create. Key-based signature and client-style verification. |
| `system/promote.sh`, `system/tests/test_promote.py`, `.github/workflows/promote-stable.yml` | Create. D1. |
| `forge/scripts/clean_ghcr.sh`, `system/tests/test_clean_ghcr.py`, `system/tests/fake_registry.py` | Modify. UT10. |
| `system/Containerfile`, `system/keys/athanor-image-1.pub`, `.github/workflows/call-system-image.yml` | Modify / create in the cut-over (Task 16), after the maintainer step. |
| `scripts/devvm/acceptance/*.sh` | Create. Acceptance 1 to 15, scripted. |
| `docs/architecture/doc_system_image.md`, `doc_kernel_profile.md`, `doc_shell.md` | Modify. Section 5 of the spec. |

## Task list

1. `athanor-trust-state`: schema, reader, badge
2. `athanor-update`: signature object verifier and its vectors
3. `athanor-update`: tools trait, policy, store, Secure Boot readings
4. `athanor-update`: the check
5. `athanor-update`: the two requests and the D-Bus service
6. `athanor-update`: migration, key recovery, command line
7. Policy templates and the renderer
8. The notifier `athanor-update-notify`
9. Package `athanor-update`: units, bus and polkit files, presets, spec, `verify.py shipped`; remove the broken preset line and override
10. D2: retire the `athanor-secure-boot` daemon, keep the TPM files
11. UT9: version and `created` labels in `system/build-image.sh`
12. `system/sign-images.sh`: key-based signature and client-style verification
13. D1: `system/promote.sh` and the manual workflow
14. UT10: retention in `forge/scripts/clean_ghcr.sh`
15. Dev VM acceptance harness (items 1 to 15), with a throwaway registry and key
16. **MAINTAINER STEP**, then the cut-over: public key, Containerfile, signing job, documents

Tasks 1 to 15 need no real key. Task 16 starts with the only step the maintainer performs.

---

### Task 1: `athanor-trust-state`: schema, reader, badge

**Files:**
- Create: `system/athanor-trust-state/Cargo.toml`
- Create: `system/athanor-trust-state/src/lib.rs`
- Modify: `Cargo.toml` (workspace member `"system/athanor-trust-state"`, after `"system/athanor-telemetry"`)

**Interfaces:**
- Consumes: nothing.
- Produces (crate `athanor_trust_state`): `STATE_PATH`, `SCHEMA`, `STALE_AFTER_SECS`; `struct State { schema, booted: Deployment, downloaded: Option<Deployment>, previous: Option<Deployment>, verified: Verified, update: UpdateState, policy: Policy, secure_boot: SecureBoot, newest_booted_build_time: i64, last_successful_check: Option<i64>, last_error: ErrorCode, last_error_host: Option<String> }`; `struct Deployment { image, digest, version: String, build_time: i64 }`; `struct Verified { value: bool, reason: Reason }` with `From<Reason>`; enums `Reason`, `UpdateState`, `ErrorCode` (kebab-case, closed); `struct Policy { path, sha256: String, shipped: bool }`; `struct SecureBoot { secure_boot, setup_mode, mok_sb_state: Option<u8>, lockdown: Option<String> }` with `on()`; `parse(&str) -> Result<State, ReadError>`; `read() -> Result<State, ReadError>`; `read_owned_by(&Path, u32)`; `enum Badge { Check, Attention, Cross }`; `badge(&State, now: i64) -> Badge`; `display(&str) -> String`. All times are seconds since the Unix epoch, so this crate needs no time library.

- [ ] **Step 1: Create the crate manifest and register the member**

`system/athanor-trust-state/Cargo.toml`:

````toml
[package]
name = "athanor-trust-state"
version = "1.0.0"
edition = "2021"
description = "Reads the update and trust state file of athanor-update and computes the shield badge"
license = "MIT"

[dependencies]
serde = { workspace = true }
serde_json = { workspace = true }
libc = { workspace = true }
````

In the root `Cargo.toml`, add the line `    "system/athanor-trust-state",` to `[workspace] members`, after `"system/athanor-telemetry",`.

- [ ] **Step 2: Write the failing tests of `system/athanor-trust-state/src/lib.rs`**

Create `system/athanor-trust-state/src/lib.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt as _;

    const DAY: i64 = 24 * 60 * 60;
    const NOW: i64 = 1_790_000_000;

    fn deployment(build_time: i64) -> Deployment {
        Deployment {
            image: "registry.example/athanor-system:stable".into(),
            digest: format!("sha256:{build_time:064x}"),
            version: "43.20260915.2".into(),
            build_time,
        }
    }

    fn verified_state() -> State {
        State {
            schema: SCHEMA,
            booted: deployment(1000),
            downloaded: None,
            previous: Some(deployment(900)),
            verified: Reason::Signature.into(),
            update: UpdateState::None,
            policy: Policy { path: "/etc/containers/policy.json".into(), sha256: "ab".repeat(32), shipped: true },
            secure_boot: SecureBoot { secure_boot: Some(1), setup_mode: Some(0), mok_sb_state: None, lockdown: Some("integrity".into()) },
            newest_booted_build_time: 1000,
            last_successful_check: Some(NOW - DAY),
            last_error: ErrorCode::None,
            last_error_host: None,
        }
    }

    #[test]
    fn verified_newest_and_fresh_is_the_check() {
        assert_eq!(badge(&verified_state(), NOW), Badge::Check);
    }

    #[test]
    fn every_reason_but_signature_is_attention() {
        for reason in [Reason::Media, Reason::NoSignature, Reason::KeyNotInPolicy, Reason::PolicyNotInForce, Reason::ReferenceOutOfScope] {
            let state = State { verified: reason.into(), ..verified_state() };
            assert_eq!(badge(&state, NOW), Badge::Attention, "{reason:?}");
        }
    }

    #[test]
    fn fourteen_days_is_the_last_fresh_day() {
        let at_limit = State { last_successful_check: Some(NOW - STALE_AFTER_SECS), ..verified_state() };
        assert_eq!(badge(&at_limit, NOW), Badge::Check);
        let past = State { last_successful_check: Some(NOW - STALE_AFTER_SECS - 1), ..verified_state() };
        assert_eq!(badge(&past, NOW), Badge::Attention);
        let never = State { last_successful_check: None, ..verified_state() };
        assert_eq!(badge(&never, NOW), Badge::Attention);
    }

    #[test]
    fn a_machine_that_went_back_is_attention_and_never_a_cross() {
        for update in [UpdateState::Held, UpdateState::OlderThanBooted] {
            let state = State { update, newest_booted_build_time: 2000, ..verified_state() };
            assert_eq!(badge(&state, NOW), Badge::Attention);
            // The update state alone does not move the badge.
            assert_eq!(badge(&State { update, ..verified_state() }, NOW), Badge::Check);
        }
    }

    #[test]
    fn a_refusal_is_the_cross_whatever_else_holds() {
        assert_eq!(badge(&State { update: UpdateState::Refused, ..verified_state() }, NOW), Badge::Cross);
    }

    #[test]
    fn secure_boot_never_moves_the_badge() {
        let off = SecureBoot { secure_boot: Some(0), setup_mode: Some(1), mok_sb_state: Some(1), lockdown: Some("none".into()) };
        assert!(!off.on());
        assert!(verified_state().secure_boot.on());
        assert_eq!(badge(&State { secure_boot: off, ..verified_state() }, NOW), Badge::Check);
    }

    #[test]
    fn the_lists_are_closed_and_the_schema_is_one() {
        let good = serde_json::to_string(&verified_state()).expect("serialize");
        assert_eq!(parse(&good), Ok(verified_state()));
        assert!(good.contains(r#""reason":"signature""#) && good.contains(r#""update":"none""#));
        for (from, to) in [
            (r#""reason":"signature""#, r#""reason":"trusted""#),
            (r#""update":"none""#, r#""update":"ready""#),
            (r#""last_error":"none""#, r#""last_error":"dns: lookup registry.example""#),
            (r#""schema":1"#, r#""schema":2"#),
            (r#""schema":1"#, r#""schema":1,"extra":true"#),
            // The two halves of `verified` disagree.
            (r#""reason":"signature""#, r#""reason":"media""#),
        ] {
            assert_eq!(parse(&good.replace(from, to)), Err(ReadError::Malformed), "{to}");
        }
    }

    #[test]
    fn will_apply_at_next_shutdown_is_spelled_as_the_spec_spells_it() {
        let text = serde_json::to_string(&UpdateState::WillApplyAtNextShutdown).expect("serialize");
        assert_eq!(text, r#""will-apply-at-next-shutdown""#);
        assert_eq!(serde_json::to_string(&UpdateState::OlderThanBooted).expect("serialize"), r#""older-than-booted""#);
        assert_eq!(serde_json::to_string(&Reason::ReferenceOutOfScope).expect("serialize"), r#""reference-out-of-scope""#);
    }

    fn scratch(test: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("athanor-trust-state-{}-{test}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("scratch directory");
        dir
    }

    #[test]
    fn the_reader_refuses_a_link_a_foreign_owner_and_a_writable_file() {
        let dir = scratch("reader");
        let me = std::fs::metadata(&dir).expect("metadata").uid();
        let file = dir.join("state.json");
        std::fs::write(&file, serde_json::to_string(&verified_state()).expect("serialize")).expect("write");
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o644)).expect("chmod");

        assert_eq!(read_owned_by(&file, me), Ok(verified_state()));
        assert_eq!(read_owned_by(&file, me + 1), Err(ReadError::Untrusted));
        assert_eq!(read_owned_by(&dir.join("absent.json"), me), Err(ReadError::Missing));

        let link = dir.join("link.json");
        std::os::unix::fs::symlink(&file, &link).expect("symlink");
        assert_eq!(read_owned_by(&link, me), Err(ReadError::Untrusted));

        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o666)).expect("chmod");
        assert_eq!(read_owned_by(&file, me), Err(ReadError::Untrusted));
        std::fs::remove_dir_all(dir).expect("cleanup");
    }

    #[test]
    fn display_strips_controls_and_bidi_and_truncates() {
        assert_eq!(display("43.2026\u{202E}0915\n.2\u{2066}"), "43.20260915.2");
        assert_eq!(display(&"x".repeat(500)).chars().count(), 128);
    }
}
````

- [ ] **Step 3: Run them to see them fail**

Run: `cargo-in-box test -p athanor-trust-state`
Expected: FAIL to compile, `cannot find type State in this scope` and similar.

- [ ] **Step 4: Write the implementation**

Put this above the test module in `system/athanor-trust-state/src/lib.rs`:

````rust
//! The update and trust state of an Athanor machine, as `athanor-update` publishes it in
//! `/run/athanor-update/state.json` (docs/architecture/doc_update_trust.md, UT7), and the
//! badge rule of the trust shield (docs/architecture/doc_shell.md, SH12).
//!
//! The greeter, the shield and the notifier all read the file through this crate, so the
//! rule exists once. The file is untrusted input for a reader: it is opened without
//! following a link, its owner is checked, its size is capped, every list in it is closed,
//! and [`display`] is the only way one of its strings should reach a widget.

use serde::{Deserialize, Serialize};
use std::io::Read as _;
use std::os::unix::fs::{MetadataExt as _, OpenOptionsExt as _};
use std::path::Path;

/// Where `athanor-update` publishes the state.
pub const STATE_PATH: &str = "/run/athanor-update/state.json";
/// The only schema this crate reads and writes.
pub const SCHEMA: u32 = 1;
/// A machine whose last successful check is older than this is not shown as verified.
pub const STALE_AFTER_SECS: i64 = 14 * 24 * 60 * 60;
const MAX_STATE_BYTES: u64 = 64 * 1024;
const MAX_DISPLAY_CHARS: usize = 128;

/// One deployment of the system image. Times are seconds since the Unix epoch, UTC.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Deployment {
    pub image: String,
    pub digest: String,
    pub version: String,
    pub build_time: i64,
}

/// Why the booted image is, or is not, verified. Only `Signature` means verified.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Reason {
    Signature,
    Media,
    NoSignature,
    KeyNotInPolicy,
    PolicyNotInForce,
    ReferenceOutOfScope,
}

/// The `verified` member of the file. The pair is redundant on purpose, so a reader can
/// refuse a file whose two halves disagree.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Verified {
    pub value: bool,
    pub reason: Reason,
}

impl From<Reason> for Verified {
    fn from(reason: Reason) -> Self {
        Self { value: reason == Reason::Signature, reason }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum UpdateState {
    None,
    Available,
    Downloaded,
    WillApplyAtNextShutdown,
    Refused,
    Held,
    OlderThanBooted,
}

/// The result of the last check. A code, never the text of an error.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ErrorCode {
    None,
    Network,
    Registry,
    Policy,
    Storage,
    Internal,
}

/// The signature policy the container tools resolve on this machine.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub path: String,
    pub sha256: String,
    pub shipped: bool,
}

/// The four readings of UT8, each absent when its source cannot be read.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SecureBoot {
    pub secure_boot: Option<u8>,
    pub setup_mode: Option<u8>,
    pub mok_sb_state: Option<u8>,
    pub lockdown: Option<String>,
}

impl SecureBoot {
    /// "On" means `SecureBoot` 1, `SetupMode` 0, shim validation not disabled (the MOK
    /// variable absent) and a kernel lockdown other than `none`.
    #[must_use]
    pub fn on(&self) -> bool {
        self.secure_boot == Some(1)
            && self.setup_mode == Some(0)
            && self.mok_sb_state.is_none()
            && self.lockdown.as_deref().is_some_and(|mode| mode != "none")
    }
}

/// Schema 1 of the state file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub schema: u32,
    pub booted: Deployment,
    pub downloaded: Option<Deployment>,
    pub previous: Option<Deployment>,
    pub verified: Verified,
    pub update: UpdateState,
    pub policy: Policy,
    pub secure_boot: SecureBoot,
    /// The newest build time this machine has ever booted; persisted under `/var/lib`.
    pub newest_booted_build_time: i64,
    /// When the registry last answered a check; persisted under `/var/lib`.
    pub last_successful_check: Option<i64>,
    pub last_error: ErrorCode,
    /// At most the registry's host name, and only beside a `network` or `registry` code.
    pub last_error_host: Option<String>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum ReadError {
    /// The file does not exist: `athanor-update` has not run yet.
    Missing,
    /// It is a link, not a regular file, not owned by the expected user, writable by
    /// others, or larger than a state file can be.
    Untrusted,
    /// It is not schema 1, a list in it holds an unknown value, or its halves disagree.
    Malformed,
    Io(std::io::ErrorKind),
}

/// Parses the text of a state file.
///
/// # Errors
/// `Malformed` when the text is not schema 1 or contradicts itself.
pub fn parse(text: &str) -> Result<State, ReadError> {
    let state: State = serde_json::from_str(text).map_err(|_| ReadError::Malformed)?;
    let consistent = state.verified.value == (state.verified.reason == Reason::Signature);
    if state.schema != SCHEMA || !consistent {
        return Err(ReadError::Malformed);
    }
    Ok(state)
}

/// Reads the published state, which must be a regular file owned by root.
///
/// # Errors
/// See [`ReadError`].
pub fn read() -> Result<State, ReadError> {
    read_owned_by(Path::new(STATE_PATH), 0)
}

/// Reads `path`, refusing a link, a file not owned by `owner`, and one others can write.
///
/// # Errors
/// See [`ReadError`].
pub fn read_owned_by(path: &Path, owner: u32) -> Result<State, ReadError> {
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)
        .map_err(|err| match err.kind() {
            std::io::ErrorKind::NotFound => ReadError::Missing,
            // ELOOP: the last component is a symbolic link.
            _ if err.raw_os_error() == Some(libc::ELOOP) => ReadError::Untrusted,
            kind => ReadError::Io(kind),
        })?;
    // The checks are made on the open descriptor, so they describe the bytes read below.
    let meta = file.metadata().map_err(|err| ReadError::Io(err.kind()))?;
    if !meta.is_file() || meta.uid() != owner || meta.mode() & 0o022 != 0 || meta.len() > MAX_STATE_BYTES {
        return Err(ReadError::Untrusted);
    }
    let mut text = String::new();
    file.by_ref().take(MAX_STATE_BYTES).read_to_string(&mut text).map_err(|_| ReadError::Malformed)?;
    parse(&text)
}

/// The three badges of SH12.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Badge {
    /// Verified, the newest version this machine has booted, checked within 14 days.
    Check,
    /// Anything else that is not a refusal.
    Attention,
    /// The last download was refused by the policy.
    Cross,
}

/// The badge for `state` at `now` (seconds since the epoch).
///
/// `older-than-booted` and `held` are not badge states: they are the normal answers on a
/// machine that went back, and that machine is already at `Attention` because it runs an
/// older version than one it has booted.
#[must_use]
pub fn badge(state: &State, now: i64) -> Badge {
    if state.update == UpdateState::Refused {
        return Badge::Cross;
    }
    let newest = state.booted.build_time >= state.newest_booted_build_time;
    let fresh = state.last_successful_check.is_some_and(|at| now.saturating_sub(at) <= STALE_AFTER_SECS);
    if state.verified.value && newest && fresh {
        Badge::Check
    } else {
        Badge::Attention
    }
}

/// A string of the state file made safe to show: control characters and bidirectional
/// controls removed, at most 128 characters. Set the result as plain text, never markup.
#[must_use]
pub fn display(text: &str) -> String {
    text.chars()
        .filter(|c| !c.is_control() && !matches!(c, '\u{061C}' | '\u{200E}' | '\u{200F}' | '\u{202A}'..='\u{202E}' | '\u{2066}'..='\u{2069}'))
        .take(MAX_DISPLAY_CHARS)
        .collect()
}
````

- [ ] **Step 5: Run the tests**

Run: `cargo-in-box test -p athanor-trust-state`
Expected: PASS, 10 tests.

- [ ] **Step 6: Commit**

````bash
git add Cargo.toml Cargo.lock system/athanor-trust-state
git commit -m "feat(trust-state): schema 1 of the update state, its hardened reader and the badge rule"
````

`git diff --stat HEAD~1 -- Cargo.lock` must show only the new package entry: every dependency is already locked.

### Task 2: `athanor-update`: signature object verifier and its vectors

**Files:**
- Create: `forge/specs/athanor-update/athanor-update-1.0.0/Cargo.toml`
- Create: `forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs` (module list only, grows in later tasks)
- Create: `forge/specs/athanor-update/athanor-update-1.0.0/src/sigobj.rs`
- Create: `forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/make.sh`, generated and committed `forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/made/`
- Create: `forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/real/` (copied from `.superpowers/spike-u1/`: public material only)
- Modify: `Cargo.toml` (member `"forge/specs/athanor-update/athanor-update-1.0.0"`, after `"forge/specs/athanor-store-rs/athanor-store-rs-1.0.0"`), `experimental/EXEMPT` (temporary line `athanor-update`, removed by Task 8)

**Interfaces:**
- Consumes: nothing.
- Produces (`crate::sigobj`): `struct Claim { manifest_digest: String, repository: String, backed: bool }`; `enum Error { Unreadable, Malformed }`; `load_key(pem: &str) -> Option<p256::ecdsa::VerifyingKey>`; `repository_of(reference: &str) -> &str`; `claims(dir: &Path, keys: &[VerifyingKey]) -> Result<Vec<Claim>, Error>`.

This verifier was compiled and run while this plan was written: it accepts the two-layer object containers/image 5.39.2 wrote in spike U1 with `k1.pub` and with `k2.pub`, which is the cross-check that the Rust code and the shipped tools agree.

- [ ] **Step 1: Manifest, member, exemption, empty program**

`forge/specs/athanor-update/athanor-update-1.0.0/Cargo.toml`:

````toml
[package]
name = "athanor-update"
version = "1.0.0"
edition = "2021"
authors = ["Athanor Forge <forge@athanor.os>"]
description = "Checks, downloads and applies Athanor system image updates, and publishes the trust state"
license = "MIT"

[dependencies]
athanor-trust-state = { path = "../../../../system/athanor-trust-state" }
athanor-bus-api = { path = "../../../../system/athanor-bus-api" }
zbus = { workspace = true }
tokio = { workspace = true }
serde = { workspace = true }
serde_json = { workspace = true }
sha2 = { workspace = true }
hex = { workspace = true }
clap = { workspace = true }
tracing = { workspace = true }
tracing-subscriber = { workspace = true }
p256 = { version = "0.13", features = ["ecdsa", "pem"] }
base64 = "0.21"
chrono = { version = "0.4", default-features = false, features = ["std"] }
````

Add `    "forge/specs/athanor-update/athanor-update-1.0.0",` to the root `Cargo.toml` members. Append the line `athanor-update` to `experimental/EXEMPT` (the crate has no spec until Task 8, and `verify.py shipped` would fail in between). `forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs`:

````rust
//! `athanor-update`: see docs/architecture/doc_update_trust.md.
mod sigobj;

fn main() {}
````

- [ ] **Step 2: The vector generator**

`forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/make.sh`:

````bash
#!/usr/bin/env bash
# Regenerates the signature-object test vectors of athanor-update under tests/vectors/made.
# Two throwaway P-256 keys are created, used and deleted: only public material is left
# (public keys, payloads, signatures), and that is what gets committed. ECDSA signatures
# are randomised, so a second run gives different bytes with the same meaning; the tests
# assert meaning. tests/vectors/real is not generated here: it is what
# `skopeo copy --sign-by-sigstore-private-key` (containers/image 5.39.2) wrote during
# spike U1, fetched back with `skopeo copy … dir:`.
# Needs openssl and python3 (standard library only).
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
out=$here/made
secrets=$(mktemp -d)
trap 'rm -rf "$secrets"' EXIT
rm -rf "$out"
mkdir -p "$out"
for key in a b; do
  openssl ecparam -name prime256v1 -genkey -noout -out "$secrets/$key.pem"
  openssl ec -in "$secrets/$key.pem" -pubout -out "$out/$key.pub" 2> /dev/null
done

DIGEST=sha256:$(printf 'the image manifest' | sha256sum | cut -d' ' -f1)
export DIGEST
echo "$DIGEST" > "$out/image-digest"

payload() { # payload REFERENCE TYPE [EXTRA-CRITICAL-MEMBER]
  python3 - "$@" <<'PY'
import json, os, sys
critical = {"identity": {"docker-reference": sys.argv[1]}, "image": {"docker-manifest-digest": os.environ["DIGEST"]}, "type": sys.argv[2]}
if len(sys.argv) > 3:
    critical[sys.argv[3]] = True
sys.stdout.write(json.dumps({"critical": critical, "optional": {"creator": "make.sh"}}, separators=(",", ":")))
PY
}

sign() { # sign KEY FILE -> base64 DER
  openssl dgst -sha256 -sign "$secrets/$1.pem" "$2" | base64 -w0
}

# The layers of an object arrive on stdin, so the script is an argument and not a here-document.
OBJECT_PY='
import hashlib, json, pathlib, sys
dest = pathlib.Path(sys.argv[1]); dest.mkdir(parents=True)
layers = []
for line in sys.stdin.read().splitlines():
    blob_file, signature = line.split(" ", 1)
    blob = pathlib.Path(blob_file).read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    (dest / digest).write_bytes(blob)
    layers.append({"mediaType": "application/vnd.dev.cosign.simplesigning.v1+json", "digest": "sha256:" + digest, "size": len(blob),
                   "annotations": {"dev.cosignproject.cosign/signature": signature}})
config = b"{}"
config_digest = hashlib.sha256(config).hexdigest()
(dest / config_digest).write_bytes(config)
manifest = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": "sha256:" + config_digest, "size": len(config)},
            "layers": layers}
(dest / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))
'
object() { # object NAME: reads "BLOBFILE SIGNATURE" lines on stdin, one layer each
  python3 -c "$OBJECT_PY" "$out/$1"
}

work=$secrets/work
mkdir "$work"
REPO=registry.example/owner/athanor-system

# good: two layers in push order, b first and a second, as a rotation leaves them.
payload "$REPO:101" "cosign container image signature" > "$work/good"
printf '%s %s\n%s %s\n' "$work/good" "$(sign b "$work/good")" "$work/good" "$(sign a "$work/good")" | object good

payload "$REPO:101" "atomic container signature" > "$work/wrong-type"
printf '%s %s\n' "$work/wrong-type" "$(sign a "$work/wrong-type")" | object wrong-type

payload "$REPO:101" "cosign container image signature" unexpected > "$work/extra-field"
printf '%s %s\n' "$work/extra-field" "$(sign a "$work/extra-field")" | object extra-field

payload "registry.example/owner/athanor-system-nvidia:101" "cosign container image signature" > "$work/other-repo"
printf '%s %s\n' "$work/other-repo" "$(sign a "$work/other-repo")" | object other-repo

# raw-signature: the 64 bytes r||s instead of ASN.1 DER.
raw=$(openssl dgst -sha256 -sign "$secrets/a.pem" "$work/good" | python3 -c '
import base64, sys
der = sys.stdin.buffer.read()
def integers(buf):
    assert buf[0] == 0x30; i = 2
    while i < len(buf):
        assert buf[i] == 0x02; n = buf[i + 1]; yield int.from_bytes(buf[i + 2:i + 2 + n], "big"); i += 2 + n
r, s = integers(der)
sys.stdout.write(base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode())')
printf '%s %s\n' "$work/good" "$raw" | object raw-signature

# reserialised: the same JSON value with other bytes, under the signature of the original.
python3 -c 'import json,sys; sys.stdout.write(json.dumps(json.load(open(sys.argv[1])), indent=1))' "$work/good" > "$work/reserialised"
printf '%s %s\n' "$work/reserialised" "$(sign a "$work/good")" | object reserialised

# descriptor-mismatch: a validly signed blob stored under the name of other bytes.
printf '%s %s\n' "$work/good" "$(sign a "$work/good")" | object descriptor-mismatch
good_hex=$(sha256sum "$work/good" | cut -d' ' -f1)
other_hex=$(printf 'other bytes' | sha256sum | cut -d' ' -f1)
mv "$out/descriptor-mismatch/$good_hex" "$out/descriptor-mismatch/$other_hex"
sed -i "s/$good_hex/$other_hex/" "$out/descriptor-mismatch/manifest.json"

# bundle: what cosign 3 publishes instead, an index with no layers of ours.
mkdir "$out/bundle"
printf '%s' '{"schemaVersion":2,"mediaType":"application/vnd.oci.image.index.v1+json","manifests":[{"mediaType":"application/vnd.oci.image.manifest.v1+json","artifactType":"application/vnd.dev.sigstore.bundle.v0.3+json","digest":"sha256:0000000000000000000000000000000000000000000000000000000000000000","size":2}]}' > "$out/bundle/manifest.json"

find "$out" -type f | sort
````

- [ ] **Step 3: Generate the vectors and copy the real object**

````bash
bash forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/make.sh
mkdir -p forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/real
cp .superpowers/spike-u1/sigobj-v1/* .superpowers/spike-u1/k1.pub .superpowers/spike-u1/k2.pub forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/real/
grep -rl 'PRIVATE KEY' forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors
````

Expected: `make.sh` lists 25 files; the `grep` prints nothing and exits 1 (no private key under the vectors). `*.pub` is not git-ignored (`*.key` and `*.pem` are); confirm with `git check-ignore -v forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/made/a.pub`, which must print nothing.

- [ ] **Step 4: Write the failing tests of `forge/specs/athanor-update/athanor-update-1.0.0/src/sigobj.rs`**

Create `forge/specs/athanor-update/athanor-update-1.0.0/src/sigobj.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn vectors(name: &str) -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/vectors").join(name)
    }

    fn key(file: &str) -> VerifyingKey {
        load_key(&std::fs::read_to_string(vectors(file)).expect("key file")).expect("a P-256 public key")
    }

    fn backed(object: &str, keys: &[VerifyingKey]) -> Vec<Claim> {
        claims(&vectors(object), keys).expect("readable object").into_iter().filter(|claim| claim.backed).collect()
    }

    #[test]
    fn what_containers_image_wrote_verifies_with_either_key_of_its_two_layers() {
        // Layer 0 was pushed with k2 and layer 1 with k1: a verifier that reads only
        // layers[0] fails with k1.
        for file in ["real/k1.pub", "real/k2.pub"] {
            let found = backed("real", &[key(file)]);
            assert_eq!(found.len(), 1, "{file}");
            assert_eq!(found[0].repository, "localhost:5000/spike/athanor-system");
            assert_eq!(found[0].manifest_digest, "sha256:08d9f3ab2f3fd065175df48841e6434914170493578a3f59d6f6fc5dcdb971f9");
        }
        assert_eq!(backed("real", &[key("real/k1.pub"), key("real/k2.pub")]).len(), 2);
    }

    #[test]
    fn a_key_that_signed_nothing_backs_nothing_but_the_claim_is_still_reported() {
        let all = claims(&vectors("real"), &[key("made/a.pub")]).expect("readable object");
        assert_eq!(all.len(), 2);
        assert!(all.iter().all(|claim| !claim.backed));
        assert!(backed("real", &[]).is_empty());
    }

    #[test]
    fn every_key_is_tried_against_every_layer() {
        let digest = std::fs::read_to_string(vectors("made/image-digest")).expect("digest").trim().to_owned();
        for file in ["made/a.pub", "made/b.pub"] {
            let found = backed("made/good", &[key("real/k1.pub"), key(file)]);
            assert_eq!(found.len(), 1, "{file}");
            assert_eq!(found[0], Claim { manifest_digest: digest.clone(), repository: "registry.example/owner/athanor-system".into(), backed: true });
        }
    }

    #[test]
    fn the_signed_bytes_are_the_stored_blob_not_a_reserialised_value() {
        assert!(backed("made/reserialised", &[key("made/a.pub")]).is_empty());
    }

    #[test]
    fn a_blob_that_does_not_match_its_descriptor_is_no_claim_at_all() {
        assert!(claims(&vectors("made/descriptor-mismatch"), &[key("made/a.pub")]).expect("readable").is_empty());
    }

    #[test]
    fn a_raw_signature_is_refused_because_only_der_is_read() {
        assert!(claims(&vectors("made/raw-signature"), &[key("made/a.pub")]).expect("readable").is_empty());
    }

    #[test]
    fn another_type_or_an_unknown_critical_member_is_refused_even_when_signed() {
        for object in ["made/wrong-type", "made/extra-field"] {
            assert!(claims(&vectors(object), &[key("made/a.pub")]).expect("readable").is_empty(), "{object}");
        }
    }

    #[test]
    fn a_signature_made_for_another_repository_says_so() {
        let found = backed("made/other-repo", &[key("made/a.pub")]);
        assert_eq!(found[0].repository, "registry.example/owner/athanor-system-nvidia");
    }

    #[test]
    fn a_cosign_3_bundle_is_not_a_signature_object() {
        assert_eq!(claims(&vectors("made/bundle"), &[key("made/a.pub")]), Err(Error::Malformed));
        assert_eq!(claims(&vectors("made/absent"), &[]), Err(Error::Unreadable));
    }

    #[test]
    fn the_repository_is_the_reference_without_its_tag_or_digest() {
        assert_eq!(repository_of("localhost:5000/a/b:v1"), "localhost:5000/a/b");
        assert_eq!(repository_of("localhost:5000/a/b"), "localhost:5000/a/b");
        assert_eq!(repository_of("registry.example/o/n@sha256:abc"), "registry.example/o/n");
        assert_eq!(repository_of("registry.example/o/n:1@sha256:abc"), "registry.example/o/n");
    }
}
````

- [ ] **Step 5: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update sigobj`
Expected: FAIL to compile, `cannot find function claims`.

- [ ] **Step 6: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-1.0.0/src/sigobj.rs`:

````rust
//! Verification of a cosign "simple signing" attachment as `skopeo copy … dir:` stores it
//! (docs/architecture/doc_update_trust.md, UT5). Four rules, each with a test below:
//! every key is tried against every layer; the signed bytes are the payload blob exactly
//! as stored, checked against its descriptor; the signature is base64 ASN.1 DER, read with
//! `from_der`; `critical.type` must be the cosign type and an unknown member is a refusal.
use base64::Engine as _;
use p256::ecdsa::signature::Verifier as _;
use p256::ecdsa::{Signature, VerifyingKey};
use p256::pkcs8::DecodePublicKey as _;
use serde::Deserialize;
use sha2::{Digest as _, Sha256};
use std::path::Path;

pub const LAYER_MEDIA_TYPE: &str = "application/vnd.dev.cosign.simplesigning.v1+json";
pub const SIGNATURE_ANNOTATION: &str = "dev.cosignproject.cosign/signature";
pub const PAYLOAD_TYPE: &str = "cosign container image signature";
const MAX_MANIFEST: u64 = 1 << 20;
const MAX_PAYLOAD: u64 = 64 << 10;

/// What one verified signature layer states.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Claim {
    pub manifest_digest: String,
    pub repository: String,
    /// One of the given keys verifies the layer. A claim that is not backed is reported
    /// only so the caller can tell `key-not-in-policy` from `no-signature`.
    pub backed: bool,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Error {
    Unreadable,
    Malformed,
}

#[derive(Deserialize)]
struct Manifest {
    layers: Vec<Descriptor>,
}

#[derive(Deserialize)]
struct Descriptor {
    #[serde(rename = "mediaType")]
    media_type: String,
    digest: String,
    size: u64,
    #[serde(default)]
    annotations: std::collections::BTreeMap<String, String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Payload {
    critical: Critical,
    #[allow(dead_code)]
    #[serde(default)]
    optional: Option<serde_json::Value>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Critical {
    identity: Identity,
    image: Image,
    #[serde(rename = "type")]
    kind: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Identity {
    #[serde(rename = "docker-reference")]
    docker_reference: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Image {
    #[serde(rename = "docker-manifest-digest")]
    docker_manifest_digest: String,
}

/// Parses one PEM public key as `cosign generate-key-pair` and `skopeo generate-sigstore-key` write it.
pub fn load_key(pem: &str) -> Option<VerifyingKey> {
    VerifyingKey::from_public_key_pem(pem).ok()
}

/// `registry/path:tag` or `registry/path@digest` without the tag or digest.
pub fn repository_of(reference: &str) -> &str {
    let reference = reference.split('@').next().unwrap_or(reference);
    match reference.rfind(':') {
        Some(colon) if !reference[colon..].contains('/') => &reference[..colon],
        _ => reference,
    }
}

fn read_capped(path: &Path, cap: u64) -> Option<Vec<u8>> {
    let meta = std::fs::symlink_metadata(path).ok()?;
    if !meta.is_file() || meta.len() > cap {
        return None;
    }
    std::fs::read(path).ok()
}

/// One layer: the descriptor first, then the signature over the stored bytes, then the JSON.
fn claim_of(dir: &Path, layer: &Descriptor, keys: &[VerifyingKey]) -> Option<Claim> {
    if layer.media_type != LAYER_MEDIA_TYPE {
        return None;
    }
    let hex_digest = layer.digest.strip_prefix("sha256:")?;
    if hex_digest.len() != 64 || !hex_digest.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')) {
        return None;
    }
    let blob = read_capped(&dir.join(hex_digest), MAX_PAYLOAD)?;
    if blob.len() as u64 != layer.size || hex::encode(Sha256::digest(&blob)) != hex_digest {
        return None;
    }
    let der = base64::engine::general_purpose::STANDARD.decode(layer.annotations.get(SIGNATURE_ANNOTATION)?).ok()?;
    let signature = Signature::from_der(&der).ok()?;
    let backed = keys.iter().any(|key| key.verify(&blob, &signature).is_ok());
    let payload: Payload = serde_json::from_slice(&blob).ok()?;
    if payload.critical.kind != PAYLOAD_TYPE {
        return None;
    }
    Some(Claim {
        manifest_digest: payload.critical.image.docker_manifest_digest,
        repository: repository_of(&payload.critical.identity.docker_reference).to_owned(),
        backed,
    })
}

/// The claims of the well-formed layers of the signature object in `dir`, each marked with
/// whether one of `keys` backs it: every key against every layer.
///
/// # Errors
/// The manifest is missing, oversized or not JSON with a `layers` list.
pub fn claims(dir: &Path, keys: &[VerifyingKey]) -> Result<Vec<Claim>, Error> {
    let manifest = read_capped(&dir.join("manifest.json"), MAX_MANIFEST).ok_or(Error::Unreadable)?;
    let manifest: Manifest = serde_json::from_slice(&manifest).map_err(|_| Error::Malformed)?;
    Ok(manifest.layers.iter().filter_map(|layer| claim_of(dir, layer, keys)).collect())
}
````

- [ ] **Step 7: Run the tests**

Run: `cargo-in-box test -p athanor-update sigobj`
Expected: PASS, 10 tests.

- [ ] **Step 8: Commit**

````bash
git add Cargo.toml Cargo.lock experimental/EXEMPT forge/specs/athanor-update/athanor-update-1.0.0
git commit -m "feat(update): verify a cosign signature object with p256, with vectors from a throwaway key"
````

### Task 3: `athanor-update`: tools trait, policy, store, Secure Boot readings

**Files:**
- Create: `forge/specs/athanor-update/athanor-update-1.0.0/src/tools.rs`, `forge/specs/athanor-update/athanor-update-1.0.0/src/policy.rs`, `forge/specs/athanor-update/athanor-update-1.0.0/src/store.rs`, `forge/specs/athanor-update/athanor-update-1.0.0/src/secureboot.rs`, `forge/specs/athanor-update/athanor-update-1.0.0/tests/state-verified.json`
- Modify: `forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs` (module list)

**Interfaces:**
- Consumes: `athanor_trust_state::{ErrorCode, Policy, SecureBoot, State}` (Task 1); `crate::sigobj::repository_of` (Task 2).
- Produces:
  - `crate::tools`: `struct Failure { code: ErrorCode, host: Option<String> }`; `struct Deployed { image, digest, version: String, build_time: i64, enforcing: bool, download_only: bool }`; `struct Status { booted: Deployed, staged: Option<Deployed>, rollback: Option<Deployed> }`; `struct Candidate { digest, version: String, build_time: i64 }`; `trait Tools { status, candidate(&str), download, apply_downloaded, relock, rollback, switch(&str), fetch_signature(&str, &str, &Path), metered }`; `struct System` (the real one); `parse_status(&str) -> Option<Status>`; `classify(&str) -> ErrorCode`; `unix_time(&str) -> Option<i64>`; `host_of(&str) -> Option<String>`.
  - `crate::policy`: `type Scopes = BTreeMap<String, Vec<PathBuf>>`; `scopes(&[u8]) -> Scopes`; `struct PolicyPaths { etc_policy, etc_registries, shipped }` with `system()`; `struct InForce { info: Policy, scopes: Scopes }`; `in_force(&PolicyPaths) -> InForce`.
  - `crate::store`: `struct Store { run, var }` with `system()`, `lock()`, `try_lock()`, `held()`, `set_held(&str)`, `refused()`, `set_refused(Option<&str>)`, `newest_booted()`, `record_booted(i64) -> io::Result<i64>`, `last_success()`, `set_last_success(i64)`, `migrated()`, `set_migrated()`, `signature_dir(&str) -> Option<PathBuf>`, `publish(&State)`, `pub(crate) replace(dir, name, mode, contents)`.
  - `crate::secureboot::read(efivars: &Path, lockdown: &Path) -> SecureBoot`.

Every error string matched by `classify` is one spike U1 recorded (`.superpowers/spike-u1-update-trust.md`, sections 1 and 7). The lock uses `std::fs::File::lock` and `try_lock` (stable since Rust 1.89), so no `flock` binding and no `unsafe`.

- [ ] **Step 1: The state fixture and the module list**

`forge/specs/athanor-update/athanor-update-1.0.0/tests/state-verified.json` (one line):

````json
{"schema":1,"booted":{"image":"registry.example/owner/athanor-system:stable","digest":"sha256:1111111111111111111111111111111111111111111111111111111111111111","version":"43.20260915.2","build_time":1789466400},"downloaded":null,"previous":null,"verified":{"value":true,"reason":"signature"},"update":"none","policy":{"path":"/etc/containers/policy.json","sha256":"abababababababababababababababababababababababababababababababab","shipped":true},"secure_boot":{"secure_boot":1,"setup_mode":0,"mok_sb_state":null,"lockdown":"integrity"},"newest_booted_build_time":1789466400,"last_successful_check":1789900000,"last_error":"none","last_error_host":null}
````

`forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs`:

````rust
//! `athanor-update`: see docs/architecture/doc_update_trust.md.
#![allow(dead_code)] // removed in Task 6, when the command line uses every module
mod policy;
mod secureboot;
mod sigobj;
mod store;
mod tools;

fn main() {}
````

- [ ] **Step 2: Write the failing tests of `forge/specs/athanor-update/athanor-update-1.0.0/src/tools.rs`**

Create `forge/specs/athanor-update/athanor-update-1.0.0/src/tools.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;

    /// `bootc status --format json` of spike U1 after `--download-only`, reduced to the members read.
    const STAGED: &str = r#"{"apiVersion":"org.containers.bootc/v1","kind":"BootcHost","status":{
      "staged":{"downloadOnly":true,"softRebootCapable":false,"pinned":false,"image":{"imageDigest":"sha256:e64f7608","timestamp":"2026-09-15T10:00:00Z","version":"43.20260915.2",
        "image":{"image":"localhost:5000/spike/athanor-system:stable","signature":"containerPolicy","transport":"registry"}}},
      "booted":{"image":{"imageDigest":"sha256:08d9f3ab","timestamp":"2026-09-10T10:00:00Z","version":"43.20260910.1",
        "image":{"image":"localhost:5000/spike/athanor-system:stable","signature":"containerPolicy","transport":"registry"}},"cachedUpdate":{"imageDigest":"sha256:stale"}},
      "rollback":{"image":{"imageDigest":"sha256:40daa320","timestamp":null,"version":null,
        "image":{"image":"ghcr.io/owner/athanor-system:35355843782","transport":"registry"}}}}}"#;

    #[test]
    fn the_status_gives_the_lock_the_build_time_and_the_enforcement() {
        let status = parse_status(STAGED).expect("status");
        assert_eq!(status.booted.build_time, 1_789_034_400);
        assert!(status.booted.enforcing && !status.booted.download_only);
        let staged = status.staged.expect("staged");
        assert!(staged.download_only);
        assert_eq!(staged.digest, "sha256:e64f7608");
        let rollback = status.rollback.expect("rollback");
        assert!(!rollback.enforcing, "an origin without `signature` is ostree-unverified-registry");
        assert_eq!((rollback.build_time, rollback.version.as_str()), (0, ""));
    }

    #[test]
    fn a_host_not_booted_from_an_image_has_no_status() {
        assert_eq!(parse_status(r#"{"status":{"booted":null,"staged":null,"rollback":null}}"#), None);
        assert_eq!(parse_status("not json"), None);
    }

    #[test]
    fn the_recorded_messages_map_to_their_codes() {
        for (stderr, code) in [
            ("error: Upgrading: … failed to invoke method OpenImage: A signature was required, but no signature exists", ErrorCode::Policy),
            ("… cryptographic signature verification failed: invalid signature when validating ASN.1 encoded signature", ErrorCode::Policy),
            ("containers-policy.json specifies a default of `insecureAcceptAnything`; refusing usage", ErrorCode::Policy),
            ("pinging container registry localhost:5000: Get \"http://localhost:5000/v2/\": dial tcp: i/o timeout", ErrorCode::Network),
            ("reading manifest stable in registry.example/o/athanor-system: manifest unknown", ErrorCode::Registry),
            ("error: Initializing storage: … Read-only file system (os error 30)", ErrorCode::Storage),
            ("error: something nobody has seen yet", ErrorCode::Internal),
        ] {
            assert_eq!(classify(stderr), code, "{stderr}");
        }
    }

    #[test]
    fn times_and_hosts() {
        assert_eq!(unix_time("2026-09-15T10:00:00Z"), unix_time("2026-09-15T12:00:00.5+02:00"));
        assert_eq!(unix_time("yesterday"), None);
        assert_eq!(host_of("localhost:5000/spike/athanor-system:stable").as_deref(), Some("localhost:5000"));
    }
}
````

- [ ] **Step 3: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update tools::`
Expected: FAIL to compile, `cannot find function parse_status`.

- [ ] **Step 4: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-1.0.0/src/tools.rs`:

````rust
//! The external programs `athanor-update` drives, behind a trait so the logic of the
//! check and of the two requests is tested with fakes. Every message matched here was
//! recorded by spike U1 against bootc 1.16.11, skopeo 1.22.2 and containers/image 5.39.
use athanor_trust_state::ErrorCode;
use serde::Deserialize;
use std::path::Path;
use std::process::Command;

/// A failed call, reduced to what may enter the state file: a code and the registry host.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Failure {
    pub code: ErrorCode,
    pub host: Option<String>,
}

/// One deployment as `bootc status --format json` reports it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Deployed {
    pub image: String,
    pub digest: String,
    pub version: String,
    /// `org.opencontainers.image.created`, seconds since the epoch; 0 when absent.
    pub build_time: i64,
    /// The deployment's origin is `ostree-image-signed:`, so bootc applies the host policy.
    pub enforcing: bool,
    /// Staged and locked against finalization (`bootc upgrade --download-only`).
    pub download_only: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Status {
    pub booted: Deployed,
    pub staged: Option<Deployed>,
    pub rollback: Option<Deployed>,
}

/// What the tag points at in the registry, read without downloading a layer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Candidate {
    pub digest: String,
    pub version: String,
    pub build_time: i64,
}

pub trait Tools {
    fn status(&self) -> Result<Status, Failure>;
    fn candidate(&self, image: &str) -> Result<Candidate, Failure>;
    fn download(&self) -> Result<(), Failure>;
    fn apply_downloaded(&self) -> Result<(), Failure>;
    fn relock(&self) -> Result<(), Failure>;
    fn rollback(&self) -> Result<(), Failure>;
    fn switch(&self, image: &str) -> Result<(), Failure>;
    /// Copies `<repository>:sha256-<hex>.sig` into `dest` under the attachments policy.
    fn fetch_signature(&self, repository: &str, digest: &str, dest: &Path) -> Result<(), Failure>;
    /// NetworkManager's `Metered` is 1 (yes) or 3 (guessed yes). No NetworkManager: false.
    fn metered(&self) -> bool;
}

/// Seconds since the epoch of an RFC 3339 time, as the image labels carry it.
#[must_use]
pub fn unix_time(rfc3339: &str) -> Option<i64> {
    chrono::DateTime::parse_from_rfc3339(rfc3339).ok().map(|time| time.timestamp())
}

/// The registry host of `registry/path[:tag]`.
#[must_use]
pub fn host_of(image: &str) -> Option<String> {
    image.split('/').next().filter(|host| !host.is_empty()).map(str::to_owned)
}

/// Maps the error text of bootc, skopeo or ostree to a code. The text goes no further.
#[must_use]
pub fn classify(stderr: &str) -> ErrorCode {
    let has = |needles: &[&str]| needles.iter().any(|needle| stderr.contains(needle));
    if has(&["A signature was required, but no signature exists", "cryptographic signature verification failed", "Source image rejected", "refusing usage"]) {
        ErrorCode::Policy
    } else if has(&["pinging container registry", "i/o timeout", "connection refused", "no such host", "dial tcp", "network is unreachable", "TLS handshake"]) {
        ErrorCode::Network
    } else if has(&["manifest unknown", "unauthorized", "denied", "toomanyrequests", "received unexpected HTTP status"]) {
        ErrorCode::Registry
    } else if has(&["No space left on device", "Read-only file system", "Input/output error"]) {
        ErrorCode::Storage
    } else {
        ErrorCode::Internal
    }
}

#[derive(Deserialize)]
struct BootcStatus {
    status: BootcHost,
}

#[derive(Deserialize)]
struct BootcHost {
    booted: Option<BootcEntry>,
    staged: Option<BootcEntry>,
    rollback: Option<BootcEntry>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct BootcEntry {
    image: Option<BootcImage>,
    #[serde(default)]
    download_only: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct BootcImage {
    image: BootcReference,
    version: Option<String>,
    timestamp: Option<String>,
    image_digest: String,
}

#[derive(Deserialize)]
struct BootcReference {
    image: String,
    signature: Option<serde_json::Value>,
}

fn deployed(entry: BootcEntry) -> Option<Deployed> {
    let image = entry.image?;
    Some(Deployed {
        enforcing: image.image.signature.as_ref().and_then(serde_json::Value::as_str) == Some("containerPolicy"),
        image: image.image.image,
        digest: image.image_digest,
        version: image.version.unwrap_or_default(),
        build_time: image.timestamp.as_deref().and_then(unix_time).unwrap_or(0),
        download_only: entry.download_only,
    })
}

/// Parses `bootc status --format json`. `None` when the host is not booted from an image.
#[must_use]
pub fn parse_status(json: &str) -> Option<Status> {
    let host = serde_json::from_str::<BootcStatus>(json).ok()?.status;
    Some(Status { booted: deployed(host.booted?)?, staged: host.staged.and_then(deployed), rollback: host.rollback.and_then(deployed) })
}

/// The real programs, at their absolute paths in the image.
pub struct System;

const BOOTC: &str = "/usr/bin/bootc";
const SKOPEO: &str = "/usr/bin/skopeo";
const OSTREE: &str = "/usr/bin/ostree";
const BUSCTL: &str = "/usr/bin/busctl";
pub const ATTACHMENTS_POLICY: &str = "/usr/share/athanor/containers/attachments-policy.json";

fn run(program: &str, args: &[&str], host: Option<String>) -> Result<String, Failure> {
    let output = Command::new(program).args(args).env("LC_ALL", "C").output().map_err(|_| Failure { code: ErrorCode::Internal, host: None })?;
    if output.status.success() {
        return Ok(String::from_utf8_lossy(&output.stdout).into_owned());
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    // The text stays in the journal of this unit; only the code leaves the process.
    tracing::warn!(program, status = ?output.status.code(), %stderr, "command failed");
    let code = classify(&stderr);
    let host = host.filter(|_| matches!(code, ErrorCode::Network | ErrorCode::Registry));
    Err(Failure { code, host })
}

impl Tools for System {
    fn status(&self) -> Result<Status, Failure> {
        let json = run(BOOTC, &["status", "--format", "json"], None)?;
        parse_status(&json).ok_or(Failure { code: ErrorCode::Internal, host: None })
    }

    fn candidate(&self, image: &str) -> Result<Candidate, Failure> {
        let host = host_of(image);
        let digest = run(SKOPEO, &["inspect", "--format", "{{.Digest}}", &format!("docker://{image}")], host.clone())?.trim().to_owned();
        // The configuration is read by digest, so both facts describe one image even if
        // the tag moves between the two calls.
        let pinned = format!("docker://{}@{digest}", crate::sigobj::repository_of(image));
        let config = run(SKOPEO, &["inspect", "--config", &pinned], host)?;
        let labels = serde_json::from_str::<serde_json::Value>(&config).ok().map(|value| value["config"]["Labels"].clone()).unwrap_or_default();
        let label = |name: &str| labels[name].as_str().unwrap_or_default().to_owned();
        Ok(Candidate {
            digest,
            version: label("org.opencontainers.image.version"),
            build_time: unix_time(&label("org.opencontainers.image.created")).unwrap_or(0),
        })
    }

    fn download(&self) -> Result<(), Failure> {
        let host = self.status().ok().and_then(|status| host_of(&status.booted.image));
        run(BOOTC, &["upgrade", "--download-only"], host).map(drop)
    }

    fn apply_downloaded(&self) -> Result<(), Failure> {
        run(BOOTC, &["upgrade", "--from-downloaded"], None).map(drop)
    }

    fn relock(&self) -> Result<(), Failure> {
        run(OSTREE, &["admin", "lock-finalization"], None).map(drop)
    }

    fn rollback(&self) -> Result<(), Failure> {
        run(BOOTC, &["rollback"], None).map(drop)
    }

    fn switch(&self, image: &str) -> Result<(), Failure> {
        run(BOOTC, &["switch", "--enforce-container-sigpolicy", "--transport", "registry", image], host_of(image)).map(drop)
    }

    fn fetch_signature(&self, repository: &str, digest: &str, dest: &Path) -> Result<(), Failure> {
        let hex = digest.strip_prefix("sha256:").filter(|hex| hex.len() == 64 && hex.bytes().all(|b| b.is_ascii_hexdigit())).ok_or(Failure { code: ErrorCode::Internal, host: None })?;
        let source = format!("docker://{repository}:sha256-{hex}.sig");
        let dest = format!("dir:{}", dest.display());
        run(SKOPEO, &["copy", "--policy", ATTACHMENTS_POLICY, &source, &dest], host_of(repository)).map(drop)
    }

    fn metered(&self) -> bool {
        let property = ["--system", "get-property", "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager", "Metered"];
        matches!(run(BUSCTL, &property, None).as_deref().map(str::trim), Ok("u 1" | "u 3"))
    }
}
````

- [ ] **Step 5: Run the tests**

Run: `cargo-in-box test -p athanor-update tools::`
Expected: PASS, 4 tests.

- [ ] **Step 6: Write the failing tests of `forge/specs/athanor-update/athanor-update-1.0.0/src/policy.rs`**

Create `forge/specs/athanor-update/athanor-update-1.0.0/src/policy.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;

    pub(crate) const SHIPPED: &str = r#"{"default":[{"type":"reject"}],"transports":{
      "docker":{"":[{"type":"insecureAcceptAnything"}],
        "registry.example/owner/athanor-system":[{"type":"sigstoreSigned","keyPaths":["/usr/share/athanor/keys/athanor-image-1.pub","/usr/share/athanor/keys/athanor-image-2.pub"],"signedIdentity":{"type":"matchRepository"}}],
        "registry.example/owner/relaxed":[{"type":"insecureAcceptAnything"}]},
      "oci":{"":[{"type":"insecureAcceptAnything"}]}}}"#;

    #[test]
    fn only_strict_repository_scopes_are_ours_and_they_carry_their_keys() {
        let found = scopes(SHIPPED.as_bytes());
        assert_eq!(found.keys().collect::<Vec<_>>(), ["registry.example/owner/athanor-system"]);
        assert_eq!(found["registry.example/owner/athanor-system"].len(), 2);
        assert!(scopes(br#"{"default":[{"type":"insecureAcceptAnything"}]}"#).is_empty());
        assert!(scopes(b"not json").is_empty());
    }

    #[test]
    fn a_local_file_or_a_missing_registries_entry_is_not_the_shipped_policy() {
        let dir = std::env::temp_dir().join(format!("athanor-update-policy-{}", std::process::id()));
        let paths = PolicyPaths { etc_policy: dir.join("etc/policy.json"), etc_registries: dir.join("etc/registries.d/athanor.yaml"), shipped: dir.join("usr") };
        for sub in ["etc/registries.d", "usr/registries.d"] {
            std::fs::create_dir_all(dir.join(sub)).expect("mkdir");
        }
        std::fs::write(dir.join("usr/policy.json"), SHIPPED).expect("write");
        std::fs::write(dir.join("usr/registries.d/athanor.yaml"), "docker: {}\n").expect("write");
        std::os::unix::fs::symlink(dir.join("usr/policy.json"), &paths.etc_policy).expect("symlink");
        assert!(!in_force(&paths).info.shipped, "the registries.d entry is missing");

        std::os::unix::fs::symlink(dir.join("usr/registries.d/athanor.yaml"), &paths.etc_registries).expect("symlink");
        let linked = in_force(&paths);
        assert!(linked.info.shipped);
        assert_eq!(linked.scopes.len(), 1);

        std::fs::remove_file(&paths.etc_policy).expect("unlink");
        std::fs::write(&paths.etc_policy, r#"{"default":[{"type":"insecureAcceptAnything"}]}"#).expect("write");
        let shadowed = in_force(&paths);
        assert!(!shadowed.info.shipped && shadowed.scopes.is_empty());
        assert_ne!(shadowed.info.sha256, linked.info.sha256);
        std::fs::remove_dir_all(dir).expect("cleanup");
    }
}
````

- [ ] **Step 7: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update policy::`
Expected: FAIL to compile, `cannot find function scopes`.

- [ ] **Step 8: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-1.0.0/src/policy.rs`:

````rust
//! The container signature policy: which one is in force, whether it is the shipped one,
//! and which keys it names for a repository (docs/architecture/doc_update_trust.md, UT3, UT5).
//! The policy file is the single list of keys; the key directory is only where files live.
use athanor_trust_state::Policy;
use sha2::{Digest as _, Sha256};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Repository scope -> the `keyPaths` of its `sigstoreSigned` requirements. A scope is
/// listed only when every requirement on it is `sigstoreSigned` with `matchRepository`,
/// so a scope somebody relaxed to `insecureAcceptAnything` is not one of ours any more.
pub type Scopes = BTreeMap<String, Vec<PathBuf>>;

#[must_use]
pub fn scopes(policy_json: &[u8]) -> Scopes {
    let Ok(policy) = serde_json::from_slice::<serde_json::Value>(policy_json) else { return Scopes::new() };
    let Some(docker) = policy["transports"]["docker"].as_object() else { return Scopes::new() };
    let mut found = Scopes::new();
    for (scope, requirements) in docker {
        let Some(requirements) = requirements.as_array().filter(|list| !list.is_empty()) else { continue };
        let strict = requirements.iter().all(|req| req["type"] == "sigstoreSigned" && req["signedIdentity"]["type"] == "matchRepository");
        if scope.is_empty() || !strict {
            continue;
        }
        let keys = requirements.iter().flat_map(|req| req["keyPaths"].as_array().cloned().unwrap_or_default()).filter_map(|path| path.as_str().map(PathBuf::from)).collect();
        found.insert(scope.clone(), keys);
    }
    found
}

/// Where the files of this module live; tests point them at a scratch directory.
#[derive(Debug, Clone)]
pub struct PolicyPaths {
    /// `/etc/containers/policy.json`: what the units' bootc and skopeo resolve. The units
    /// run with `ProtectHome=yes`, so `$HOME/.config/containers/policy.json`, which
    /// containers/image prefers, is not visible to them and cannot shadow this path.
    pub etc_policy: PathBuf,
    pub etc_registries: PathBuf,
    /// `/usr/share/athanor/containers`
    pub shipped: PathBuf,
}

impl PolicyPaths {
    #[must_use]
    pub fn system() -> Self {
        Self {
            etc_policy: "/etc/containers/policy.json".into(),
            etc_registries: "/etc/containers/registries.d/athanor.yaml".into(),
            shipped: "/usr/share/athanor/containers".into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InForce {
    pub info: Policy,
    /// The scopes of the policy in force, shipped or not: the download gate reads these.
    pub scopes: Scopes,
}

fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// Reads the policy the tools resolve and compares it, and the `registries.d` entry
/// without which a signed image reads as unsigned, with the shipped files by content.
#[must_use]
pub fn in_force(paths: &PolicyPaths) -> InForce {
    let etc = std::fs::read(&paths.etc_policy).unwrap_or_default();
    let same = |etc_file: &Path, shipped_name: &str| match (std::fs::read(etc_file), std::fs::read(paths.shipped.join(shipped_name))) {
        (Ok(a), Ok(b)) => !a.is_empty() && a == b,
        _ => false,
    };
    let shipped = same(&paths.etc_policy, "policy.json") && same(&paths.etc_registries, "registries.d/athanor.yaml");
    InForce {
        info: Policy { path: paths.etc_policy.display().to_string(), sha256: sha256_hex(&etc), shipped },
        scopes: scopes(&etc),
    }
}
````

- [ ] **Step 9: Run the tests**

Run: `cargo-in-box test -p athanor-update policy::`
Expected: PASS, 2 tests.

- [ ] **Step 10: Write the failing tests of `forge/specs/athanor-update/athanor-update-1.0.0/src/secureboot.rs`**

Create `forge/specs/athanor-update/athanor-update-1.0.0/src/secureboot.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_four_readings_are_read_separately() {
        let dir = std::env::temp_dir().join(format!("athanor-update-sb-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("mkdir");
        std::fs::write(dir.join(format!("SecureBoot-{EFI_GLOBAL}")), [6, 0, 0, 0, 1]).expect("write");
        std::fs::write(dir.join(format!("SetupMode-{EFI_GLOBAL}")), [6, 0, 0, 0, 0]).expect("write");
        std::fs::write(dir.join("lockdown"), "none [integrity] confidentiality\n").expect("write");
        let on = read(&dir, &dir.join("lockdown"));
        assert_eq!((on.secure_boot, on.setup_mode, on.mok_sb_state, on.lockdown.as_deref()), (Some(1), Some(0), None, Some("integrity")));
        assert!(on.on());

        std::fs::write(dir.join(format!("MokSBStateRT-{SHIM_LOCK}")), [6, 0, 0, 0, 1]).expect("write");
        assert!(!read(&dir, &dir.join("lockdown")).on(), "shim validation disabled");
        let bios = read(&dir.join("absent"), &dir.join("absent"));
        assert_eq!((bios.secure_boot, bios.lockdown), (None, None));
        std::fs::remove_dir_all(dir).expect("cleanup");
    }
}
````

- [ ] **Step 11: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update secureboot::`
Expected: FAIL to compile, `cannot find function read`.

- [ ] **Step 12: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-1.0.0/src/secureboot.rs`:

````rust
//! The four Secure Boot readings of UT8. They are published; they never move the badge.
use athanor_trust_state::SecureBoot;
use std::path::Path;

const EFI_GLOBAL: &str = "8be4df61-93ca-11d2-aa0d-00e098032b8c";
const SHIM_LOCK: &str = "605dab50-e046-4300-abb6-3dd810dd8b23";

/// An efivarfs file is four attribute bytes and then the value.
fn efi_byte(efivars: &Path, name: &str, guid: &str) -> Option<u8> {
    std::fs::read(efivars.join(format!("{name}-{guid}"))).ok()?.get(4).copied()
}

/// `none [integrity] confidentiality` -> `integrity`.
fn lockdown_mode(text: &str) -> Option<String> {
    text.split_whitespace().find_map(|word| word.strip_prefix('[')?.strip_suffix(']')).map(str::to_owned)
}

#[must_use]
pub fn read(efivars: &Path, lockdown: &Path) -> SecureBoot {
    SecureBoot {
        secure_boot: efi_byte(efivars, "SecureBoot", EFI_GLOBAL),
        setup_mode: efi_byte(efivars, "SetupMode", EFI_GLOBAL),
        mok_sb_state: efi_byte(efivars, "MokSBStateRT", SHIM_LOCK),
        lockdown: std::fs::read_to_string(lockdown).ok().as_deref().and_then(lockdown_mode),
    }
}
````

- [ ] **Step 13: Run the tests**

Run: `cargo-in-box test -p athanor-update secureboot::`
Expected: PASS, 1 test.

- [ ] **Step 14: Write the failing tests of `forge/specs/athanor-update/athanor-update-1.0.0/src/store.rs`**

Create `forge/specs/athanor-update/athanor-update-1.0.0/src/store.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;

    pub(crate) fn scratch(test: &str) -> Store {
        let dir = std::env::temp_dir().join(format!("athanor-update-store-{}-{test}", std::process::id()));
        let store = Store { run: dir.join("run"), var: dir.join("var") };
        std::fs::create_dir_all(&store.run).expect("mkdir");
        std::fs::create_dir_all(store.var.join("signatures")).expect("mkdir");
        store
    }

    #[test]
    fn the_newest_booted_build_time_only_grows() {
        let store = scratch("newest");
        assert_eq!(store.record_booted(2000).expect("write"), 2000);
        assert_eq!(store.record_booted(1000).expect("write"), 2000, "booting an older image after going back");
        assert_eq!(store.newest_booted(), 2000);
    }

    #[test]
    fn held_and_refused_survive_and_only_refused_clears() {
        let store = scratch("held");
        assert_eq!((store.held(), store.refused()), (None, None));
        store.set_held("sha256:aa").expect("write");
        store.set_refused(Some("sha256:bb")).expect("write");
        assert_eq!((store.held().as_deref(), store.refused().as_deref()), (Some("sha256:aa"), Some("sha256:bb")));
        store.set_refused(None).expect("clear");
        store.set_refused(None).expect("clearing twice is fine");
        assert_eq!(store.refused(), None);
    }

    #[test]
    fn a_second_taker_of_the_lock_is_told_it_is_busy() {
        let store = scratch("lock");
        let held = store.lock().expect("lock");
        assert_eq!(store.try_lock().err().map(|err| err.kind()), Some(std::io::ErrorKind::WouldBlock));
        drop(held);
        assert!(store.try_lock().is_ok());
    }

    #[test]
    fn a_signature_directory_exists_only_for_a_sha256_digest() {
        let store = scratch("sigdir");
        assert!(store.signature_dir(&format!("sha256:{}", "a".repeat(64))).is_some());
        for bad in ["sha256:../../etc", "sha512:aa", "", &format!("sha256:{}", "A".repeat(64))] {
            assert_eq!(store.signature_dir(bad), None, "{bad}");
        }
    }

    #[test]
    fn the_state_is_replaced_by_rename_and_is_world_readable() {
        use std::os::unix::fs::PermissionsExt as _;
        let store = scratch("publish");
        std::os::unix::fs::symlink("/etc/passwd", store.run.join(format!(".state.json.{}", std::process::id()))).expect("plant a link at the temporary name");
        let state: State = serde_json::from_str(include_str!("../tests/state-verified.json")).expect("fixture");
        store.publish(&state).expect("publish");
        let meta = std::fs::symlink_metadata(store.run.join("state.json")).expect("metadata");
        assert!(meta.is_file());
        assert_eq!(meta.permissions().mode() & 0o777, 0o644);
        assert_eq!(athanor_trust_state::read_owned_by(&store.run.join("state.json"), std::os::unix::fs::MetadataExt::uid(&meta)), Ok(state));
    }
}
````

- [ ] **Step 15: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update store::`
Expected: FAIL to compile, `cannot find struct Store`.

- [ ] **Step 16: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-1.0.0/src/store.rs`:

````rust
//! What `athanor-update` keeps on disk (docs/architecture/doc_update_trust.md, UT1, UT6, UT7).
//!
//! `/run/athanor-update/`   `lock`, `state.json` (0644, written to a temporary name and renamed)
//! `/var/lib/athanor-update/`
//!   `held`            the digest the user went back from; nothing releases it
//!   `refused`         the digest the policy last refused; cleared by a download that passes
//!   `newest-booted`   the newest build time this machine has booted, seconds since the epoch
//!   `last-success`    when the registry last answered a check, seconds since the epoch
//!   `migrated`        stamp of `athanor-update migrate`
//!   `signatures/<hex>/`  the signature object of a digest, as `skopeo copy … dir:` wrote it
use athanor_trust_state::State;
use std::fs::File;
use std::io::Write as _;
use std::os::unix::fs::OpenOptionsExt as _;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct Store {
    pub run: PathBuf,
    pub var: PathBuf,
}

/// Holds the lock of UT1 until dropped.
pub struct Lock(#[allow(dead_code)] File);

impl Store {
    #[must_use]
    pub fn system() -> Self {
        Self { run: "/run/athanor-update".into(), var: "/var/lib/athanor-update".into() }
    }

    fn lock_file(&self) -> std::io::Result<File> {
        std::fs::OpenOptions::new().create(true).truncate(false).write(true).mode(0o600).open(self.run.join("lock"))
    }

    /// Waits for the lock: the check may have to wait for a request, never the reverse.
    ///
    /// # Errors
    /// The run directory is missing or the lock cannot be taken.
    pub fn lock(&self) -> std::io::Result<Lock> {
        let file = self.lock_file()?;
        file.lock()?;
        Ok(Lock(file))
    }

    /// Takes the lock or reports that a check or another request holds it.
    ///
    /// # Errors
    /// `WouldBlock` when the lock is held; otherwise as [`Store::lock`].
    pub fn try_lock(&self) -> std::io::Result<Lock> {
        let file = self.lock_file()?;
        file.try_lock().map_err(|err| match err {
            std::fs::TryLockError::WouldBlock => std::io::ErrorKind::WouldBlock.into(),
            std::fs::TryLockError::Error(err) => err,
        })?;
        Ok(Lock(file))
    }

    fn read_line(&self, name: &str) -> Option<String> {
        let text = std::fs::read_to_string(self.var.join(name)).ok()?;
        Some(text.trim().to_owned()).filter(|line| !line.is_empty())
    }

    pub(crate) fn replace(dir: &Path, name: &str, mode: u32, contents: &[u8]) -> std::io::Result<()> {
        let temporary = dir.join(format!(".{name}.{}", std::process::id()));
        // A leftover of a killed run would make create_new fail for ever. create_new is
        // O_EXCL, which never follows a link planted at the temporary name.
        match std::fs::remove_file(&temporary) {
            Err(err) if err.kind() != std::io::ErrorKind::NotFound => return Err(err),
            _ => {}
        }
        let mut file = std::fs::OpenOptions::new().write(true).create_new(true).mode(mode).open(&temporary)?;
        file.write_all(contents)?;
        file.sync_all()?;
        std::fs::rename(&temporary, dir.join(name))
    }

    #[must_use]
    pub fn held(&self) -> Option<String> {
        self.read_line("held")
    }

    /// # Errors
    /// The file cannot be written.
    pub fn set_held(&self, digest: &str) -> std::io::Result<()> {
        Self::replace(&self.var, "held", 0o644, format!("{digest}\n").as_bytes())
    }

    #[must_use]
    pub fn refused(&self) -> Option<String> {
        self.read_line("refused")
    }

    /// # Errors
    /// The file cannot be written or removed.
    pub fn set_refused(&self, digest: Option<&str>) -> std::io::Result<()> {
        match digest {
            Some(digest) => Self::replace(&self.var, "refused", 0o644, format!("{digest}\n").as_bytes()),
            None => match std::fs::remove_file(self.var.join("refused")) {
                Err(err) if err.kind() != std::io::ErrorKind::NotFound => Err(err),
                _ => Ok(()),
            },
        }
    }

    #[must_use]
    pub fn newest_booted(&self) -> i64 {
        self.read_line("newest-booted").and_then(|line| line.parse().ok()).unwrap_or(0)
    }

    /// Records `build_time` when it is newer than the record, and returns the record.
    ///
    /// # Errors
    /// The file cannot be written.
    pub fn record_booted(&self, build_time: i64) -> std::io::Result<i64> {
        let newest = self.newest_booted();
        if build_time <= newest {
            return Ok(newest);
        }
        Self::replace(&self.var, "newest-booted", 0o644, format!("{build_time}\n").as_bytes())?;
        Ok(build_time)
    }

    #[must_use]
    pub fn last_success(&self) -> Option<i64> {
        self.read_line("last-success").and_then(|line| line.parse().ok())
    }

    /// # Errors
    /// The file cannot be written.
    pub fn set_last_success(&self, now: i64) -> std::io::Result<()> {
        Self::replace(&self.var, "last-success", 0o644, format!("{now}\n").as_bytes())
    }

    #[must_use]
    pub fn migrated(&self) -> bool {
        self.var.join("migrated").exists()
    }

    /// # Errors
    /// The file cannot be written.
    pub fn set_migrated(&self) -> std::io::Result<()> {
        Self::replace(&self.var, "migrated", 0o644, b"")
    }

    /// The directory of the signature object of `digest`; `None` for anything but `sha256:<64 hex>`.
    #[must_use]
    pub fn signature_dir(&self, digest: &str) -> Option<PathBuf> {
        let hex = digest.strip_prefix("sha256:")?;
        (hex.len() == 64 && hex.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))).then(|| self.var.join("signatures").join(hex))
    }

    /// Publishes the state: a temporary name in the same directory, then a rename.
    ///
    /// # Errors
    /// The file cannot be written.
    pub fn publish(&self, state: &State) -> std::io::Result<()> {
        let json = serde_json::to_vec(state).map_err(std::io::Error::other)?;
        Self::replace(&self.run, "state.json", 0o644, &json)
    }
}
````

- [ ] **Step 17: Run the tests**

Run: `cargo-in-box test -p athanor-update store::`
Expected: PASS, 5 tests.

- [ ] **Step 18: Commit**

````bash
git add forge/specs/athanor-update/athanor-update-1.0.0
git commit -m "feat(update): bootc and skopeo behind a trait, the policy in force, the persisted store, the Secure Boot readings"
````

### Task 4: `athanor-update`: the check

**Files:**
- Create: `forge/specs/athanor-update/athanor-update-1.0.0/src/check.rs`
- Modify: `forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs` (add `mod check;`)

**Interfaces:**
- Consumes: everything Task 3 produces; `sigobj::{claims, load_key, repository_of}`.
- Produces (`crate::check`): `struct Context<'a, T: Tools> { tools: &'a T, store: &'a Store, policy: PolicyPaths, efivars: PathBuf, lockdown: PathBuf, now: i64 }` with `Context::system(tools, store, now)`; `run(ctx, offline: bool) -> Result<State, Failure>`; for the tests of later tasks, `pub(crate) mod tests` exports `REPO`, `SIGNED`, `digest(u8)`, `deployed(&str, i64)`, `struct Fake` (scripted `Tools` recording `calls`), `struct Machine` (scratch store and policy in force).

The order of the reasons: `policy-not-in-force`, then `reference-out-of-scope`, then `media` (the booted origin does not enforce the policy: an install from the ISO, or a machine not migrated yet), then `signature`, `key-not-in-policy` (a well-formed claim covers the digest and the repository and no key of the policy backs it), `no-signature`. The tests map to the acceptance: held digest (5, 13), older build (9), refusal as a code with no registry text (4, 12), metered (UT12), copy from another repository (9), a key that left the policy (UT5).

**UT12 against UT5.** UT12 says the check "always runs `bootc upgrade --check`"; UT5 forbids using it. The check reads the digest and the label with `skopeo inspect`, which costs the same manifest and configuration (55 kB).

- [ ] **Step 1: Add `mod check;` to `forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs`** (alphabetical, before `mod policy;`).

- [ ] **Step 2: Write the failing tests of `forge/specs/athanor-update/athanor-update-1.0.0/src/check.rs`**

Create `forge/specs/athanor-update/athanor-update-1.0.0/src/check.rs` holding only this test module:

````rust
#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::tools::Candidate;
    use std::cell::RefCell;
    use std::path::Path;

    pub(crate) const REPO: &str = "localhost:5000/spike/athanor-system";
    /// The digest the signature object under tests/vectors/real covers.
    pub(crate) const SIGNED: &str = "sha256:08d9f3ab2f3fd065175df48841e6434914170493578a3f59d6f6fc5dcdb971f9";

    pub(crate) fn digest(n: u8) -> String {
        format!("sha256:{}", format!("{n:02x}").repeat(32))
    }

    pub(crate) fn deployed(digest: &str, build_time: i64) -> Deployed {
        Deployed { image: format!("{REPO}:stable"), digest: digest.into(), version: format!("43.{build_time}"), build_time, enforcing: true, download_only: false }
    }

    /// bootc, skopeo, ostree and NetworkManager as one scripted object that records its calls.
    pub(crate) struct Fake {
        pub status: RefCell<Status>,
        pub candidate: Result<Candidate, Failure>,
        /// What `download` stages, or how it fails.
        pub download: Result<Deployed, Failure>,
        pub metered: bool,
        pub relock: Result<(), Failure>,
        pub calls: RefCell<Vec<String>>,
    }

    impl Fake {
        pub(crate) fn booted(booted: Deployed) -> Self {
            Self {
                status: RefCell::new(Status { booted, staged: None, rollback: None }),
                candidate: Err(Failure { code: ErrorCode::Network, host: Some("localhost:5000".into()) }),
                download: Err(Failure { code: ErrorCode::Internal, host: None }),
                metered: false,
                relock: Ok(()),
                calls: RefCell::new(Vec::new()),
            }
        }

        pub(crate) fn offering(mut self, digest: &str, build_time: i64) -> Self {
            self.candidate = Ok(Candidate { digest: digest.into(), version: format!("43.{build_time}"), build_time });
            self.download = Ok(Deployed { download_only: true, ..deployed(digest, build_time) });
            self
        }

        fn call(&self, what: impl Into<String>) {
            self.calls.borrow_mut().push(what.into());
        }

        pub(crate) fn called(&self, what: &str) -> bool {
            self.calls.borrow().iter().any(|call| call.starts_with(what))
        }
    }

    impl Tools for Fake {
        fn status(&self) -> Result<Status, Failure> {
            Ok(self.status.borrow().clone())
        }
        fn candidate(&self, image: &str) -> Result<Candidate, Failure> {
            self.call(format!("candidate {image}"));
            self.candidate.clone()
        }
        fn download(&self) -> Result<(), Failure> {
            self.call("download");
            self.status.borrow_mut().staged = Some(self.download.clone()?);
            Ok(())
        }
        fn apply_downloaded(&self) -> Result<(), Failure> {
            self.call("apply_downloaded");
            if let Some(staged) = self.status.borrow_mut().staged.as_mut() {
                staged.download_only = false;
            }
            Ok(())
        }
        fn relock(&self) -> Result<(), Failure> {
            self.call("relock");
            self.relock.clone()?;
            if let Some(staged) = self.status.borrow_mut().staged.as_mut() {
                staged.download_only = true;
            }
            Ok(())
        }
        fn rollback(&self) -> Result<(), Failure> {
            self.call("rollback");
            Ok(())
        }
        fn switch(&self, image: &str) -> Result<(), Failure> {
            self.call(format!("switch {image}"));
            self.status.borrow_mut().staged = Some(self.download.clone()?);
            Ok(())
        }
        fn fetch_signature(&self, repository: &str, digest: &str, dest: &Path) -> Result<(), Failure> {
            self.call(format!("fetch_signature {repository} {digest}"));
            if digest != SIGNED {
                return Err(Failure { code: ErrorCode::Registry, host: Some("localhost:5000".into()) });
            }
            let real = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/vectors/real");
            std::fs::create_dir_all(dest).expect("mkdir");
            for entry in std::fs::read_dir(real).expect("vectors") {
                let entry = entry.expect("entry");
                std::fs::copy(entry.path(), dest.join(entry.file_name())).expect("copy");
            }
            Ok(())
        }
        fn metered(&self) -> bool {
            self.metered
        }
    }

    /// A scratch machine: the store, and a shipped policy in force that names `keys` for REPO.
    pub(crate) struct Machine {
        pub store: Store,
        pub policy: PolicyPaths,
        pub root: PathBuf,
    }

    impl Machine {
        pub(crate) fn new(test: &str, keys: &[&str]) -> Self {
            let root = std::env::temp_dir().join(format!("athanor-update-check-{}-{test}", std::process::id()));
            if root.exists() {
                std::fs::remove_dir_all(&root).expect("clean");
            }
            let store = Store { run: root.join("run"), var: root.join("var") };
            for dir in [store.run.clone(), store.var.join("signatures"), root.join("etc/registries.d"), root.join("usr/registries.d")] {
                std::fs::create_dir_all(dir).expect("mkdir");
            }
            let vectors = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/vectors");
            let key_paths: Vec<_> = keys.iter().map(|key| vectors.join(key).display().to_string()).collect();
            let policy = serde_json::json!({"default": [{"type": "reject"}], "transports": {"docker": {
                "": [{"type": "insecureAcceptAnything"}],
                REPO: [{"type": "sigstoreSigned", "keyPaths": key_paths, "signedIdentity": {"type": "matchRepository"}}]}}});
            std::fs::write(root.join("usr/policy.json"), policy.to_string()).expect("write");
            std::fs::write(root.join("usr/registries.d/athanor.yaml"), "docker: {}\n").expect("write");
            let paths = PolicyPaths { etc_policy: root.join("etc/policy.json"), etc_registries: root.join("etc/registries.d/athanor.yaml"), shipped: root.join("usr") };
            std::os::unix::fs::symlink(root.join("usr/policy.json"), &paths.etc_policy).expect("symlink");
            std::os::unix::fs::symlink(root.join("usr/registries.d/athanor.yaml"), &paths.etc_registries).expect("symlink");
            Self { store, policy: paths, root }
        }

        pub(crate) fn ctx<'a>(&'a self, tools: &'a Fake, now: i64) -> Context<'a, Fake> {
            Context { tools, store: &self.store, policy: self.policy.clone(), efivars: self.root.join("efivars"), lockdown: self.root.join("lockdown"), now }
        }

        pub(crate) fn store_signature(&self, digest: &str, vector: &str) {
            let dest = self.store.signature_dir(digest).expect("digest");
            std::fs::create_dir_all(&dest).expect("mkdir");
            for entry in std::fs::read_dir(Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/vectors").join(vector)).expect("vectors") {
                let entry = entry.expect("entry");
                std::fs::copy(entry.path(), dest.join(entry.file_name())).expect("copy");
            }
        }
    }

    #[test]
    fn a_newer_digest_is_downloaded_and_its_signature_stored() {
        let machine = Machine::new("download", &["real/k1.pub"]);
        let tools = Fake::booted(deployed(&digest(1), 1000)).offering(SIGNED, 2000);
        let state = run(&machine.ctx(&tools, 5000), false).expect("check");
        assert_eq!(state.update, UpdateState::Downloaded);
        assert_eq!(state.downloaded.as_ref().map(|d| d.digest.as_str()), Some(SIGNED));
        assert_eq!((state.last_error, state.last_successful_check), (ErrorCode::None, Some(5000)));
        assert!(machine.store.signature_dir(SIGNED).expect("dir").join("manifest.json").exists());
        assert_eq!(athanor_trust_state::read_owned_by(&machine.store.run.join("state.json"), std::os::unix::fs::MetadataExt::uid(&std::fs::metadata(&machine.root).expect("meta"))), Ok(state));
    }

    #[test]
    fn the_held_digest_is_never_downloaded_but_a_newer_one_is() {
        let machine = Machine::new("held", &["real/k1.pub"]);
        machine.store.set_held(&digest(2)).expect("held");
        let tools = Fake::booted(deployed(&digest(1), 1000)).offering(&digest(2), 2000);
        for _ in 0..3 {
            assert_eq!(run(&machine.ctx(&tools, 5000), false).expect("check").update, UpdateState::Held);
        }
        assert!(!tools.called("download"));
        let newer = Fake::booted(deployed(&digest(1), 1000)).offering(&digest(3), 3000);
        assert_eq!(run(&machine.ctx(&newer, 5000), false).expect("check").update, UpdateState::Downloaded);
    }

    #[test]
    fn a_tag_moved_to_an_older_or_equal_build_is_published_and_not_downloaded() {
        let machine = Machine::new("older", &["real/k1.pub"]);
        for build_time in [500, 1000] {
            let tools = Fake::booted(deployed(&digest(1), 1000)).offering(&digest(2), build_time);
            assert_eq!(run(&machine.ctx(&tools, 5000), false).expect("check").update, UpdateState::OlderThanBooted);
            assert!(!tools.called("download"));
        }
    }

    #[test]
    fn a_refusal_is_a_code_survives_a_reboot_and_clears_when_a_download_passes() {
        let machine = Machine::new("refused", &["real/k1.pub"]);
        let mut tools = Fake::booted(deployed(&digest(1), 1000)).offering(&digest(2), 2000);
        tools.download = Err(Failure { code: ErrorCode::Policy, host: None });
        let state = run(&machine.ctx(&tools, 5000), false).expect("check");
        assert_eq!((state.update, state.last_error, state.last_error_host.clone()), (UpdateState::Refused, ErrorCode::Policy, None));
        let text = std::fs::read_to_string(machine.store.run.join("state.json")).expect("state");
        assert!(!text.contains("signature was required") && !text.contains("http"), "no registry text in the file");

        let after_reboot = Fake::booted(deployed(&digest(1), 1000));
        assert_eq!(run(&machine.ctx(&after_reboot, 5000), true).expect("offline").update, UpdateState::Refused);

        let passing = Fake::booted(deployed(&digest(1), 1000)).offering(&digest(3), 3000);
        assert_eq!(run(&machine.ctx(&passing, 6000), false).expect("check").update, UpdateState::Downloaded);
        assert_eq!(machine.store.refused(), None);
    }

    #[test]
    fn a_metered_connection_checks_and_does_not_download() {
        let machine = Machine::new("metered", &["real/k1.pub"]);
        let mut tools = Fake::booted(deployed(&digest(1), 1000)).offering(&digest(2), 2000);
        tools.metered = true;
        let state = run(&machine.ctx(&tools, 5000), false).expect("check");
        assert_eq!((state.update, state.last_successful_check), (UpdateState::Available, Some(5000)));
        assert!(tools.called("candidate") && !tools.called("download"));
    }

    #[test]
    fn a_registry_that_does_not_answer_is_a_code_a_host_and_no_successful_check() {
        let machine = Machine::new("network", &["real/k1.pub"]);
        let tools = Fake::booted(deployed(&digest(1), 1000));
        let state = run(&machine.ctx(&tools, 5000), false).expect("check");
        assert_eq!((state.last_error, state.last_error_host.as_deref(), state.last_successful_check), (ErrorCode::Network, Some("localhost:5000"), None));
    }

    #[test]
    fn nothing_is_downloaded_through_a_reference_that_does_not_enforce_the_policy() {
        let machine = Machine::new("media", &["real/k1.pub"]);
        let tools = Fake::booted(Deployed { enforcing: false, ..deployed(&digest(1), 1000) }).offering(&digest(2), 2000);
        let state = run(&machine.ctx(&tools, 5000), false).expect("check");
        assert_eq!((state.verified.reason, state.update), (Reason::Media, UpdateState::None));
        assert!(tools.calls.borrow().is_empty(), "no registry call at all: {:?}", tools.calls.borrow());
    }

    #[test]
    fn verified_is_derived_from_the_stored_object_and_the_keys_of_the_policy() {
        let booted = || Fake::booted(deployed(SIGNED, 1000));
        let with_key = Machine::new("reason-signature", &["real/k1.pub"]);
        with_key.store_signature(SIGNED, "real");
        let state = run(&with_key.ctx(&booted(), 5000), true).expect("offline");
        assert!(state.verified.value);
        assert_eq!(state.verified.reason, Reason::Signature);

        // The same object once its key has left the policy: nothing stored says "verified".
        let rotated = Machine::new("reason-rotated", &["made/a.pub"]);
        rotated.store_signature(SIGNED, "real");
        assert_eq!(run(&rotated.ctx(&booted(), 5000), true).expect("offline").verified.reason, Reason::KeyNotInPolicy);

        let none = Machine::new("reason-none", &["real/k1.pub"]);
        assert_eq!(run(&none.ctx(&booted(), 5000), true).expect("offline").verified.reason, Reason::NoSignature);

        // A valid object of another digest, as a copy from another of our repositories is.
        let other = Machine::new("reason-other", &["made/a.pub"]);
        other.store_signature(SIGNED, "made/other-repo");
        assert_eq!(run(&other.ctx(&booted(), 5000), true).expect("offline").verified.reason, Reason::NoSignature);
    }

    #[test]
    fn a_missing_signature_object_of_the_booted_digest_is_fetched_by_the_next_check() {
        let machine = Machine::new("heal", &["real/k1.pub"]);
        let tools = Fake::booted(deployed(SIGNED, 1000)).offering(SIGNED, 1000);
        assert_eq!(run(&machine.ctx(&tools, 5000), false).expect("check").verified.reason, Reason::Signature);
    }

    #[test]
    fn a_shadowed_policy_and_a_foreign_repository_have_their_own_reasons() {
        let machine = Machine::new("shadow", &["real/k1.pub"]);
        machine.store_signature(SIGNED, "real");
        let foreign = Fake::booted(Deployed { image: "registry.example/someone/else:latest".into(), ..deployed(SIGNED, 1000) });
        assert_eq!(run(&machine.ctx(&foreign, 5000), true).expect("offline").verified.reason, Reason::ReferenceOutOfScope);

        std::fs::remove_file(&machine.policy.etc_policy).expect("unlink");
        std::fs::write(&machine.policy.etc_policy, r#"{"default":[{"type":"insecureAcceptAnything"}]}"#).expect("write");
        let tools = Fake::booted(deployed(SIGNED, 1000)).offering(&digest(2), 2000);
        let state = run(&machine.ctx(&tools, 5000), false).expect("check");
        assert_eq!((state.verified.reason, state.policy.shipped), (Reason::PolicyNotInForce, false));
        assert!(!tools.called("download"), "a permissive policy downloads nothing");
    }

    #[test]
    fn the_newest_booted_build_time_is_published_after_going_back() {
        let machine = Machine::new("went-back", &["real/k1.pub"]);
        run(&machine.ctx(&Fake::booted(deployed(&digest(2), 2000)), 5000), true).expect("offline");
        let state = run(&machine.ctx(&Fake::booted(deployed(&digest(1), 1000)), 6000), true).expect("offline");
        assert_eq!((state.booted.build_time, state.newest_booted_build_time), (1000, 2000));
    }
}
````

- [ ] **Step 3: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update check::`
Expected: FAIL to compile, `cannot find function run`.

- [ ] **Step 4: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-1.0.0/src/check.rs`:

````rust
//! `athanor-update check`: derive the verification of the booted digest again, ask the
//! registry, download, publish (docs/architecture/doc_update_trust.md, UT1, UT5, UT6, UT12).
use crate::policy::{InForce, PolicyPaths};
use crate::sigobj;
use crate::store::Store;
use crate::tools::{Deployed, Failure, Status, Tools};
use athanor_trust_state::{Deployment, ErrorCode, Reason, State, UpdateState, SCHEMA};
use std::path::PathBuf;

pub struct Context<'a, T: Tools> {
    pub tools: &'a T,
    pub store: &'a Store,
    pub policy: PolicyPaths,
    pub efivars: PathBuf,
    pub lockdown: PathBuf,
    /// Seconds since the epoch.
    pub now: i64,
}

impl<'a, T: Tools> Context<'a, T> {
    /// The paths of an installed machine.
    #[must_use]
    pub fn system(tools: &'a T, store: &'a Store, now: i64) -> Self {
        Self {
            tools,
            store,
            policy: PolicyPaths::system(),
            efivars: "/sys/firmware/efi/efivars".into(),
            lockdown: "/sys/kernel/security/lockdown".into(),
            now,
        }
    }
}

fn deployment(deployed: &Deployed) -> Deployment {
    Deployment { image: deployed.image.clone(), digest: deployed.digest.clone(), version: deployed.version.clone(), build_time: deployed.build_time }
}

/// Why the booted image is, or is not, verified. Never a stored answer: the stored
/// signature object is verified again, against the keys the shipped policy names today.
fn reason<T: Tools>(ctx: &Context<'_, T>, policy: &InForce, booted: &Deployed) -> Reason {
    if !policy.info.shipped {
        return Reason::PolicyNotInForce;
    }
    let repository = sigobj::repository_of(&booted.image);
    let Some(key_paths) = policy.scopes.get(repository) else { return Reason::ReferenceOutOfScope };
    if !booted.enforcing {
        // The installer's reference, or an install that has not migrated yet (UT4).
        return Reason::Media;
    }
    let keys: Vec<_> = key_paths.iter().filter_map(|path| std::fs::read_to_string(path).ok()).filter_map(|pem| sigobj::load_key(&pem)).collect();
    let claims = ctx.store.signature_dir(&booted.digest).and_then(|dir| sigobj::claims(&dir, &keys).ok()).unwrap_or_default();
    let covers = |claim: &&sigobj::Claim| claim.manifest_digest == booted.digest && claim.repository == repository;
    match claims.iter().filter(covers).map(|claim| claim.backed).max() {
        Some(true) => Reason::Signature,
        Some(false) => Reason::KeyNotInPolicy,
        None => Reason::NoSignature,
    }
}

/// The update state that needs no network: what is staged, and what was refused.
fn local_update(ctx: &Context<'_, impl Tools>, status: &Status) -> UpdateState {
    match &status.staged {
        Some(staged) if !staged.download_only => UpdateState::WillApplyAtNextShutdown,
        Some(staged) if offerable(ctx.store, &status.booted, &staged.digest, staged.build_time) == UpdateState::Available => UpdateState::Downloaded,
        _ if ctx.store.refused().is_some() => UpdateState::Refused,
        _ => UpdateState::None,
    }
}

/// `Available` when `digest` may be offered; otherwise why not. The order of the build
/// times is the only ordering: bootc has none, and a moved tag is a downgrade the policy
/// cannot see.
fn offerable(store: &Store, booted: &Deployed, digest: &str, build_time: i64) -> UpdateState {
    if digest == booted.digest {
        UpdateState::None
    } else if store.held().as_deref() == Some(digest) {
        UpdateState::Held
    } else if build_time <= booted.build_time {
        UpdateState::OlderThanBooted
    } else {
        UpdateState::Available
    }
}

/// True when a download would be verified: the booted origin makes bootc apply the host
/// policy, and that policy demands a signature for the repository the machine follows.
/// The policy need not be the shipped one: the recovery of UT2 installs a local one.
fn enforced(policy: &InForce, booted: &Deployed) -> bool {
    booted.enforcing && policy.scopes.contains_key(sigobj::repository_of(&booted.image))
}

fn online_update<T: Tools>(ctx: &Context<'_, T>, policy: &InForce, status: &mut Status) -> (UpdateState, Option<Failure>) {
    let local = local_update(ctx, status);
    if !enforced(policy, &status.booted) || local == UpdateState::WillApplyAtNextShutdown {
        return (local, None);
    }
    let candidate = match ctx.tools.candidate(&status.booted.image) {
        Ok(candidate) => candidate,
        Err(failure) => return (local, Some(failure)),
    };
    // The registry answered: that is a successful check, whatever it said.
    if let Err(err) = ctx.store.set_last_success(ctx.now) {
        tracing::error!(%err, "cannot record the successful check");
        return (local, Some(Failure { code: ErrorCode::Storage, host: None }));
    }
    let verdict = offerable(ctx.store, &status.booted, &candidate.digest, candidate.build_time);
    if verdict != UpdateState::Available {
        return (if verdict == UpdateState::None { local } else { verdict }, None);
    }
    if status.staged.as_ref().is_some_and(|staged| staged.download_only && staged.digest == candidate.digest) {
        return (UpdateState::Downloaded, None);
    }
    if ctx.tools.metered() {
        return (UpdateState::Available, None);
    }
    match ctx.tools.download() {
        Err(failure) if failure.code == ErrorCode::Policy => {
            let stored = ctx.store.set_refused(Some(&candidate.digest));
            (UpdateState::Refused, Some(stored.map_or(Failure { code: ErrorCode::Storage, host: None }, |()| failure)))
        }
        Err(failure) => (UpdateState::Available, Some(failure)),
        Ok(()) => {
            *status = match ctx.tools.status() {
                Ok(status) => status,
                Err(failure) => return (UpdateState::Available, Some(failure)),
            };
            // What bootc staged is what counts, not what the tag said a moment earlier.
            let after = local_update(ctx, status);
            if after != UpdateState::Downloaded {
                return (UpdateState::Available, None);
            }
            let staged = status.staged.as_ref().map(|staged| staged.digest.clone()).unwrap_or_default();
            let mut failure = ctx.store.set_refused(None).err().map(|_| Failure { code: ErrorCode::Storage, host: None });
            if let Some(dir) = ctx.store.signature_dir(&staged).filter(|dir| !dir.join("manifest.json").exists()) {
                failure = failure.or(ctx.tools.fetch_signature(sigobj::repository_of(&status.booted.image), &staged, &dir).err());
            }
            (UpdateState::Downloaded, failure)
        }
    }
}

/// Runs one check and publishes the state. `offline` is the run at boot, before the
/// network is up, and the run after a request: it verifies and publishes, nothing else.
///
/// # Errors
/// Only when bootc gives no status or the state cannot be published; everything else is
/// an error code inside the published state.
pub fn run<T: Tools>(ctx: &Context<'_, T>, offline: bool) -> Result<State, Failure> {
    let mut status = ctx.tools.status()?;
    let storage = |_| Failure { code: ErrorCode::Storage, host: None };
    let newest = ctx.store.record_booted(status.booted.build_time).map_err(storage)?;
    let policy = crate::policy::in_force(&ctx.policy);
    let (update, failure) = if offline { (local_update(ctx, &status), None) } else { online_update(ctx, &policy, &mut status) };
    if !offline && enforced(&policy, &status.booted) {
        // A machine whose signature object was never stored, or was lost, heals here. A
        // failure is not the check's: the reason below already says `no-signature`.
        if let Some(dir) = ctx.store.signature_dir(&status.booted.digest).filter(|dir| !dir.join("manifest.json").exists()) {
            if let Err(failure) = ctx.tools.fetch_signature(sigobj::repository_of(&status.booted.image), &status.booted.digest, &dir) {
                tracing::warn!(code = ?failure.code, "the signature object of the booted digest could not be fetched");
            }
        }
    }
    let state = State {
        schema: SCHEMA,
        verified: reason(ctx, &policy, &status.booted).into(),
        booted: deployment(&status.booted),
        downloaded: status.staged.as_ref().map(deployment),
        previous: status.rollback.as_ref().map(deployment),
        update,
        policy: policy.info,
        secure_boot: crate::secureboot::read(&ctx.efivars, &ctx.lockdown),
        newest_booted_build_time: newest,
        last_successful_check: ctx.store.last_success(),
        last_error: failure.as_ref().map_or(ErrorCode::None, |failure| failure.code),
        last_error_host: failure.and_then(|failure| failure.host),
    };
    ctx.store.publish(&state).map_err(storage)?;
    Ok(state)
}
````

- [ ] **Step 5: Run the tests**

Run: `cargo-in-box test -p athanor-update check::`
Expected: PASS, 11 tests.

- [ ] **Step 6: Commit**

````bash
git add forge/specs/athanor-update/athanor-update-1.0.0
git commit -m "feat(update): the check: verification derived again, build-time rule, held digest, error codes only"
````

### Task 5: `athanor-update`: the two requests and the D-Bus service

**Files:**
- Create: `forge/specs/athanor-update/athanor-update-1.0.0/src/requests.rs`, `forge/specs/athanor-update/athanor-update-1.0.0/src/serve.rs`
- Modify: `forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs` (add `mod requests;` and `mod serve;`)

**Interfaces:**
- Consumes: `check::{Context, run}`, `tools::Tools`, `store::Store::{try_lock, held, set_held}`, `policy::in_force`; `athanor_bus_api::polkit::check_polkit_auth_zbus(conn: &zbus::Connection, sender: &str, action_id: &str, allow_user_interaction: bool) -> zbus::Result<bool>` (read-only crate; `forge/specs/athanor-backup/athanor-backup-1.0.0/src/daemon.rs:340-349` is the pattern for the header and the connection, not for the action names).
- Produces: `requests::{trait Power { async fn blocked(&self) -> bool; async fn reboot(&self) -> Result<(), RebootError> }, enum RebootError { Blocked, Failed }, enum Refusal { Busy, NothingDownloaded, NoPreviousVersion, Blocked, Failed }, apply(ctx, power), go_back(ctx, power)}`; `serve::{BUS_NAME = "os.athanor.Update1", OBJECT_PATH = "/os/athanor/Update1", run() -> zbus::Result<()>}`. D-Bus errors are `os.athanor.Update1.Error.{NotAuthorized, Busy, NothingDownloaded, NoPreviousVersion, Blocked, Failed}` with fixed messages.

Two points beyond the letter of UT6, both in its spirit. `Apply()` asks logind's `ListInhibitors` before unlocking, so that with an inhibitor held "nothing is unlocked" (acceptance 2) is true and not merely restored; logind's own refusal inside `Reboot(false)` stays the authority and is followed by the re-lock. "The state is `downloaded`" is read from bootc (`staged.downloadOnly`), not from the world-readable file.

- [ ] **Step 1: Add `mod requests;` and `mod serve;` to `forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs`.**

- [ ] **Step 2: Write the failing tests of `forge/specs/athanor-update/athanor-update-1.0.0/src/requests.rs`**

Create `forge/specs/athanor-update/athanor-update-1.0.0/src/requests.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::check::tests::{deployed, digest, Fake, Machine};
    use crate::tools::Deployed;
    use athanor_trust_state::UpdateState;
    use std::cell::Cell;

    struct FakePower {
        blocked: bool,
        reboot: Result<(), RebootError>,
        rebooted: Cell<bool>,
    }

    impl FakePower {
        fn new(blocked: bool, reboot: Result<(), RebootError>) -> Self {
            Self { blocked, reboot, rebooted: Cell::new(false) }
        }
    }

    impl Power for FakePower {
        async fn blocked(&self) -> bool {
            self.blocked
        }
        async fn reboot(&self) -> Result<(), RebootError> {
            self.rebooted.set(self.reboot.is_ok());
            self.reboot
        }
    }

    fn downloaded() -> Fake {
        let tools = Fake::booted(deployed(&digest(1), 1000));
        tools.status.borrow_mut().staged = Some(Deployed { download_only: true, ..deployed(&digest(2), 2000) });
        tools
    }

    fn published(machine: &Machine) -> UpdateState {
        let text = std::fs::read_to_string(machine.store.run.join("state.json")).expect("state");
        athanor_trust_state::parse(&text).expect("schema 1").update
    }

    #[tokio::test]
    async fn apply_unlocks_and_reboots() {
        let machine = Machine::new("apply", &["real/k1.pub"]);
        let (tools, power) = (downloaded(), FakePower::new(false, Ok(())));
        assert_eq!(apply(&machine.ctx(&tools, 5000), &power).await, Ok(()));
        assert!(power.rebooted.get());
        assert_eq!(*tools.calls.borrow(), ["apply_downloaded"]);
        assert_eq!(published(&machine), UpdateState::WillApplyAtNextShutdown);
    }

    #[tokio::test]
    async fn apply_refuses_with_nothing_downloaded_and_never_downloads() {
        let machine = Machine::new("apply-nothing", &["real/k1.pub"]);
        let unlocked = downloaded();
        unlocked.status.borrow_mut().staged.as_mut().expect("staged").download_only = false;
        let held = downloaded();
        machine.store.set_held(&digest(2)).expect("held");
        for tools in [Fake::booted(deployed(&digest(1), 1000)).offering(&digest(2), 2000), unlocked, held] {
            let power = FakePower::new(false, Ok(()));
            assert_eq!(apply(&machine.ctx(&tools, 5000), &power).await, Err(Refusal::NothingDownloaded));
            assert!(tools.calls.borrow().is_empty() && !power.rebooted.get());
        }
    }

    #[tokio::test]
    async fn apply_with_an_inhibitor_held_unlocks_nothing() {
        let machine = Machine::new("apply-blocked", &["real/k1.pub"]);
        let (tools, power) = (downloaded(), FakePower::new(true, Ok(())));
        assert_eq!(apply(&machine.ctx(&tools, 5000), &power).await, Err(Refusal::Blocked));
        assert!(tools.calls.borrow().is_empty());
    }

    #[tokio::test]
    async fn a_reboot_refused_after_the_unlock_locks_the_deployment_again() {
        let machine = Machine::new("apply-relock", &["real/k1.pub"]);
        let (tools, power) = (downloaded(), FakePower::new(false, Err(RebootError::Blocked)));
        assert_eq!(apply(&machine.ctx(&tools, 5000), &power).await, Err(Refusal::Blocked));
        assert_eq!(*tools.calls.borrow(), ["apply_downloaded", "relock"]);
        assert_eq!(published(&machine), UpdateState::Downloaded);

        let mut stuck = downloaded();
        stuck.relock = Err(crate::tools::Failure { code: athanor_trust_state::ErrorCode::Internal, host: None });
        assert_eq!(apply(&machine.ctx(&stuck, 5000), &FakePower::new(false, Err(RebootError::Failed))).await, Err(Refusal::Failed));
        assert_eq!(published(&machine), UpdateState::WillApplyAtNextShutdown, "the truthful state when the re-lock fails");
    }

    #[tokio::test]
    async fn a_request_during_a_check_is_told_busy() {
        let machine = Machine::new("apply-busy", &["real/k1.pub"]);
        let _check = machine.store.lock().expect("lock");
        assert_eq!(apply(&machine.ctx(&downloaded(), 5000), &FakePower::new(false, Ok(()))).await, Err(Refusal::Busy));
    }

    #[tokio::test]
    async fn go_back_holds_the_digest_it_leaves() {
        let machine = Machine::new("go-back", &["real/k1.pub"]);
        let tools = Fake::booted(deployed(&digest(2), 2000));
        assert_eq!(go_back(&machine.ctx(&tools, 5000), &FakePower::new(false, Ok(()))).await, Err(Refusal::NoPreviousVersion));
        tools.status.borrow_mut().rollback = Some(deployed(&digest(1), 1000));
        let power = FakePower::new(false, Ok(()));
        assert_eq!(go_back(&machine.ctx(&tools, 5000), &power).await, Ok(()));
        assert_eq!(machine.store.held(), Some(digest(2)));
        assert_eq!(*tools.calls.borrow(), ["rollback"]);
        assert!(power.rebooted.get());
    }
}
````

- [ ] **Step 3: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update requests::`
Expected: FAIL to compile, `cannot find function apply`.

- [ ] **Step 4: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-1.0.0/src/requests.rs`:

````rust
//! The two requests of UT6, free of D-Bus so they are tested with fakes. `serve.rs` adds
//! the bus, polkit and logind around them.
use crate::check::Context;
use crate::sigobj;
use crate::tools::Tools;

/// logind, as far as the requests need it.
pub trait Power {
    /// A block inhibitor on shutdown is held.
    async fn blocked(&self) -> bool;
    /// `login1.Manager.Reboot(false)`: inhibitors honoured, never the skip-inhibitors flag.
    async fn reboot(&self) -> Result<(), RebootError>;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RebootError {
    /// `org.freedesktop.login1.BlockedByInhibitorLock`
    Blocked,
    Failed,
}

/// Why a request did nothing. Each becomes one D-Bus error name; none carries free text.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Refusal {
    Busy,
    NothingDownloaded,
    NoPreviousVersion,
    Blocked,
    Failed,
}

impl From<RebootError> for Refusal {
    fn from(err: RebootError) -> Self {
        match err {
            RebootError::Blocked => Self::Blocked,
            RebootError::Failed => Self::Failed,
        }
    }
}

fn republish<T: Tools>(ctx: &Context<'_, T>) {
    if let Err(failure) = crate::check::run(ctx, true) {
        tracing::error!(code = ?failure.code, "cannot publish the state");
    }
}

/// `Apply()`: unlock what the timer downloaded and reboot, in one request. Never downloads.
///
/// # Errors
/// See [`Refusal`]. After any refusal the staged deployment is locked again.
pub async fn apply<T: Tools, P: Power>(ctx: &Context<'_, T>, power: &P) -> Result<(), Refusal> {
    let _lock = ctx.store.try_lock().map_err(|_| Refusal::Busy)?;
    let status = ctx.tools.status().map_err(|_| Refusal::Failed)?;
    let policy = crate::policy::in_force(&ctx.policy);
    let ready = status.staged.as_ref().is_some_and(|staged| {
        staged.download_only
            && status.booted.enforcing
            && policy.scopes.contains_key(sigobj::repository_of(&status.booted.image))
            && staged.build_time > status.booted.build_time
            && ctx.store.held().as_deref() != Some(staged.digest.as_str())
    });
    if !ready {
        return Err(Refusal::NothingDownloaded);
    }
    // A courtesy that keeps the deployment locked in the common case. The authority is
    // logind's own check inside Reboot, handled below.
    if power.blocked().await {
        return Err(Refusal::Blocked);
    }
    ctx.tools.apply_downloaded().map_err(|_| Refusal::Failed)?;
    republish(ctx);
    if let Err(err) = power.reboot().await {
        if ctx.tools.relock().is_err() {
            tracing::error!("the deployment could not be locked again: it applies at the next shutdown");
        }
        republish(ctx);
        return Err(err.into());
    }
    Ok(())
}

/// `GoBack()`: the immediately previous deployment, the digest left recorded as held, a reboot.
///
/// # Errors
/// See [`Refusal`].
pub async fn go_back<T: Tools, P: Power>(ctx: &Context<'_, T>, power: &P) -> Result<(), Refusal> {
    let _lock = ctx.store.try_lock().map_err(|_| Refusal::Busy)?;
    let status = ctx.tools.status().map_err(|_| Refusal::Failed)?;
    if status.rollback.is_none() {
        return Err(Refusal::NoPreviousVersion);
    }
    if power.blocked().await {
        return Err(Refusal::Blocked);
    }
    // Held first: if the rollback then fails, the worst case is a digest not offered again.
    ctx.store.set_held(&status.booted.digest).map_err(|_| Refusal::Failed)?;
    ctx.tools.rollback().map_err(|_| Refusal::Failed)?;
    republish(ctx);
    power.reboot().await.map_err(Refusal::from)
}
````

- [ ] **Step 5: Run the tests**

Run: `cargo-in-box test -p athanor-update requests::`
Expected: PASS, 6 tests.

- [ ] **Step 6: The service**

`forge/specs/athanor-update/athanor-update-1.0.0/src/serve.rs` (no unit test: it is the bus, polkit and logind, which acceptance 2 and 5 exercise on the dev VM):

````rust
//! `athanor-update serve`: the D-Bus service `os.athanor.Update1` (UT6). Two methods, no
//! arguments, no property. The subject polkit judges is the bus sender, never a PID.
use crate::check::Context;
use crate::requests::{self, Power, RebootError, Refusal};
use crate::tools::System;
use athanor_bus_api::polkit::check_polkit_auth_zbus;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use zbus::message::Header;
use zbus::{interface, Connection};

pub const BUS_NAME: &str = "os.athanor.Update1";
pub const OBJECT_PATH: &str = "/os/athanor/Update1";
const ACTION_APPLY: &str = "os.athanor.update.apply";
const ACTION_ROLLBACK: &str = "os.athanor.update.rollback";
/// The service is D-Bus activated: it leaves after this long without a request.
const IDLE: Duration = Duration::from_secs(60);

#[derive(Debug, zbus::DBusError)]
#[zbus(prefix = "os.athanor.Update1.Error")]
pub enum Error {
    #[zbus(error)]
    ZBus(zbus::Error),
    NotAuthorized(String),
    Busy(String),
    NothingDownloaded(String),
    NoPreviousVersion(String),
    Blocked(String),
    Failed(String),
}

impl From<Refusal> for Error {
    fn from(refusal: Refusal) -> Self {
        match refusal {
            Refusal::Busy => Self::Busy("a check or another request is running".into()),
            Refusal::NothingDownloaded => Self::NothingDownloaded("no update is downloaded; the timer downloads at its next run".into()),
            Refusal::NoPreviousVersion => Self::NoPreviousVersion("there is no previous version to go back to".into()),
            Refusal::Blocked => Self::Blocked("a restart is blocked by an inhibitor".into()),
            Refusal::Failed => Self::Failed("the request failed; the journal of athanor-update.service has the detail".into()),
        }
    }
}

struct Logind<'a>(&'a Connection);

impl Logind<'_> {
    async fn call<B: serde::Serialize + zbus::zvariant::DynamicType>(&self, method: &str, body: &B) -> zbus::Result<zbus::Message> {
        self.0.call_method(Some("org.freedesktop.login1"), "/org/freedesktop/login1", Some("org.freedesktop.login1.Manager"), method, body).await
    }
}

impl Power for Logind<'_> {
    async fn blocked(&self) -> bool {
        type Inhibitor = (String, String, String, String, u32, u32);
        let Ok(reply) = self.call("ListInhibitors", &()).await else { return false };
        let inhibitors: Vec<Inhibitor> = reply.body().deserialize().unwrap_or_default();
        inhibitors.iter().any(|(what, _, _, mode, _, _)| mode == "block" && what.split(':').any(|kind| kind == "shutdown"))
    }

    async fn reboot(&self) -> Result<(), RebootError> {
        // Reboot(interactive = false). Never RebootWithFlags: flag 16 skips the inhibitors.
        match self.call("Reboot", &(false,)).await {
            Ok(_) => Ok(()),
            Err(zbus::Error::MethodError(name, _, _)) if name.as_str() == "org.freedesktop.login1.BlockedByInhibitorLock" => Err(RebootError::Blocked),
            Err(err) => {
                tracing::error!(%err, "logind refused the reboot");
                Err(RebootError::Failed)
            }
        }
    }
}

/// Counts the requests in flight, so the idle exit never cuts a polkit prompt short.
#[derive(Default)]
struct Activity {
    in_flight: AtomicUsize,
    last: Mutex<Option<Instant>>,
}

struct InFlight(Arc<Activity>);

impl Activity {
    fn enter(self: &Arc<Self>) -> InFlight {
        self.in_flight.fetch_add(1, Ordering::SeqCst);
        InFlight(Arc::clone(self))
    }

    fn idle_for(&self, started: Instant) -> Option<Duration> {
        let last = self.last.lock().map(|last| *last).unwrap_or(None);
        (self.in_flight.load(Ordering::SeqCst) == 0).then(|| last.unwrap_or(started).elapsed())
    }
}

impl Drop for InFlight {
    fn drop(&mut self) {
        if let Ok(mut last) = self.0.last.lock() {
            *last = Some(Instant::now());
        }
        self.0.in_flight.fetch_sub(1, Ordering::SeqCst);
    }
}

struct Update1 {
    activity: Arc<Activity>,
}

async fn authorize(conn: &Connection, header: &Header<'_>, action: &str) -> Result<String, Error> {
    let sender = header.sender().ok_or_else(|| Error::NotAuthorized("the call has no sender".into()))?.to_string();
    match check_polkit_auth_zbus(conn, &sender, action, true).await {
        Ok(true) => Ok(sender),
        Ok(false) => Err(Error::NotAuthorized("not authorized".into())),
        Err(err) => {
            tracing::error!(%err, action, "polkit could not be asked");
            Err(Error::NotAuthorized("polkit could not be asked".into()))
        }
    }
}

async fn uid_of(conn: &Connection, sender: &str) -> Option<u32> {
    let name = zbus::names::BusName::try_from(sender).ok()?;
    zbus::fdo::DBusProxy::new(conn).await.ok()?.get_connection_unix_user(name).await.ok()
}

fn now() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |since| i64::try_from(since.as_secs()).unwrap_or(i64::MAX))
}

#[interface(name = "os.athanor.Update1")]
impl Update1 {
    async fn apply(&self, #[zbus(header)] header: Header<'_>, #[zbus(connection)] conn: &Connection) -> Result<(), Error> {
        let _in_flight = self.activity.enter();
        authorize(conn, &header, ACTION_APPLY).await?;
        let (tools, store) = (System, crate::store::Store::system());
        let ctx = Context::system(&tools, &store, now());
        Ok(requests::apply(&ctx, &Logind(conn)).await?)
    }

    async fn go_back(&self, #[zbus(header)] header: Header<'_>, #[zbus(connection)] conn: &Connection) -> Result<(), Error> {
        let _in_flight = self.activity.enter();
        let sender = authorize(conn, &header, ACTION_ROLLBACK).await?;
        // UT6: the caller's uid at notice. It identifies who asked; polkit already decided.
        let uid = uid_of(conn, &sender).await;
        tracing::info!(?uid, "going back to the previous version was requested and authorized");
        let (tools, store) = (System, crate::store::Store::system());
        let ctx = Context::system(&tools, &store, now());
        Ok(requests::go_back(&ctx, &Logind(conn)).await?)
    }
}

/// Serves until idle, then releases the name and returns; the bus starts it again on demand.
///
/// # Errors
/// The name cannot be owned: the `system.d` policy file is missing, or another owner exists.
pub async fn run() -> zbus::Result<()> {
    let activity = Arc::new(Activity::default());
    let conn = zbus::connection::Builder::system()?.name(BUS_NAME)?.serve_at(OBJECT_PATH, Update1 { activity: Arc::clone(&activity) })?.build().await?;
    let started = Instant::now();
    loop {
        tokio::time::sleep(Duration::from_secs(5)).await;
        if activity.idle_for(started).is_some_and(|idle| idle >= IDLE) {
            conn.release_name(BUS_NAME).await?;
            // A call that raced the release is answered before leaving.
            if activity.idle_for(started).is_some() {
                return Ok(());
            }
            conn.request_name(BUS_NAME).await?;
        }
    }
}
````

- [ ] **Step 7: Build**

Run: `cargo-in-box build -p athanor-update`
Expected: `Finished`, no warning from this crate.

- [ ] **Step 8: Commit**

````bash
git add forge/specs/athanor-update/athanor-update-1.0.0
git commit -m "feat(update): Apply and GoBack on os.athanor.Update1, polkit on the bus sender, idle exit"
````

### Task 6: `athanor-update`: migration, key recovery, command line

**Files:**
- Create: `forge/specs/athanor-update/athanor-update-1.0.0/src/migrate.rs`, `forge/specs/athanor-update/athanor-update-1.0.0/src/recover.rs`, `forge/specs/athanor-update/RECOVERY.md`
- Modify: `forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs` (final form)

**Interfaces:**
- Consumes: `check::Context`, `tools::Tools`, `store::Store::{migrated, set_migrated, signature_dir, replace}`, `policy::{PolicyPaths, scopes, in_force}`, `sigobj::load_key`.
- Produces: `migrate::{CHANNEL = "stable", enum Outcome { Done, Switched, Waiting(&'static str) }, run(ctx) -> Result<Outcome, Failure>}`; `recover::{RECOVERY_KEY = "recovery.pub", begin(&PolicyPaths, etc_keys: &Path, new_key: &Path) -> Result<(), String>, finish(&PolicyPaths, etc_keys: &Path) -> Result<(), String>}`; the command line `athanor-update check [--offline] | serve | migrate | recover-key begin NEW_KEY | recover-key finish`.

- [ ] **Step 1: Write the failing tests of `forge/specs/athanor-update/athanor-update-1.0.0/src/migrate.rs`**

Create `forge/specs/athanor-update/athanor-update-1.0.0/src/migrate.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::check::tests::{deployed, digest, Fake, Machine, REPO, SIGNED};
    use crate::tools::Deployed;

    fn from_media(build_time: i64) -> Deployed {
        Deployed { enforcing: false, image: format!("{REPO}:35355843782"), ..deployed(&digest(9), build_time) }
    }

    #[test]
    fn a_machine_from_media_is_switched_to_the_channel_once() {
        let machine = Machine::new("migrate", &["real/k1.pub"]);
        let tools = Fake::booted(from_media(1000)).offering(SIGNED, 1000);
        assert_eq!(run(&machine.ctx(&tools, 5000)), Ok(Outcome::Switched));
        assert!(tools.called(&format!("switch {REPO}:stable")));
        assert!(!tools.called("relock"), "the same build is not an update");
        assert!(machine.store.signature_dir(SIGNED).expect("dir").join("manifest.json").exists());
        assert_eq!(run(&machine.ctx(&tools, 5000)), Ok(Outcome::Done));
        assert_eq!(tools.calls.borrow().iter().filter(|call| call.starts_with("switch")).count(), 1);
    }

    #[test]
    fn a_newer_channel_is_staged_locked_and_an_older_one_is_not_followed() {
        let machine = Machine::new("migrate-newer", &["real/k1.pub"]);
        let newer = Fake::booted(from_media(1000)).offering(SIGNED, 2000);
        assert_eq!(run(&machine.ctx(&newer, 5000)), Ok(Outcome::Switched));
        assert!(newer.called("relock"));

        let machine = Machine::new("migrate-older", &["real/k1.pub"]);
        let older = Fake::booted(from_media(1000)).offering(SIGNED, 500);
        assert_eq!(run(&machine.ctx(&older, 5000)), Ok(Outcome::Waiting("channel-older-than-booted")));
        assert!(!older.called("switch") && !machine.store.migrated());
    }

    #[test]
    fn without_the_policy_in_force_nothing_is_switched_and_no_stamp_is_written() {
        let machine = Machine::new("migrate-policy", &["real/k1.pub"]);
        std::fs::remove_file(&machine.policy.etc_registries).expect("unlink");
        let tools = Fake::booted(from_media(1000)).offering(SIGNED, 1000);
        assert_eq!(run(&machine.ctx(&tools, 5000)), Ok(Outcome::Waiting("policy-not-in-force")));
        assert!(tools.calls.borrow().is_empty() && !machine.store.migrated());
    }

    #[test]
    fn a_failed_switch_leaves_no_stamp() {
        let machine = Machine::new("migrate-fail", &["real/k1.pub"]);
        let mut tools = Fake::booted(from_media(1000)).offering(SIGNED, 1000);
        tools.download = Err(Failure { code: athanor_trust_state::ErrorCode::Policy, host: None });
        assert_eq!(run(&machine.ctx(&tools, 5000)).map_err(|failure| failure.code), Err(athanor_trust_state::ErrorCode::Policy));
        assert!(!machine.store.migrated());
    }
}
````

- [ ] **Step 2: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update migrate::`
Expected: FAIL to compile, `cannot find function run`.

- [ ] **Step 3: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-1.0.0/src/migrate.rs`:

````rust
//! `athanor-update migrate`: move the machine, once, onto the signed reference
//! (docs/architecture/doc_update_trust.md, UT4). One mechanism for a fresh install from
//! the ISO and for a machine installed before the policy existed.
use crate::check::Context;
use crate::sigobj;
use crate::tools::{Failure, Tools};

/// The tag machines follow (decision D1).
pub const CHANNEL: &str = "stable";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    /// The stamp exists, or the booted reference already enforces the policy.
    Done,
    /// The reference was switched; the signed digest boots at the next restart.
    Switched,
    /// Nothing was done and nothing is wrong: the unit succeeds and the next boot tries again.
    Waiting(&'static str),
}

/// # Errors
/// bootc, the registry or the disk failed: the unit fails and systemd starts it again.
pub fn run<T: Tools>(ctx: &Context<'_, T>) -> Result<Outcome, Failure> {
    let storage = |_| Failure { code: athanor_trust_state::ErrorCode::Storage, host: None };
    if ctx.store.migrated() {
        return Ok(Outcome::Done);
    }
    let status = ctx.tools.status()?;
    if status.booted.enforcing {
        ctx.store.set_migrated().map_err(storage)?;
        return Ok(Outcome::Done);
    }
    let policy = crate::policy::in_force(&ctx.policy);
    if !policy.info.shipped {
        return Ok(Outcome::Waiting("policy-not-in-force"));
    }
    let repository = sigobj::repository_of(&status.booted.image);
    if !policy.scopes.contains_key(repository) {
        return Ok(Outcome::Waiting("reference-out-of-scope"));
    }
    let target = format!("{repository}:{CHANNEL}");
    // The build-time rule of UT5 holds here too: the migration never moves a machine back.
    let candidate = ctx.tools.candidate(&target)?;
    if candidate.build_time < status.booted.build_time {
        return Ok(Outcome::Waiting("channel-older-than-booted"));
    }
    ctx.tools.switch(&target)?;
    let staged = ctx.tools.status()?.staged;
    if let Some(staged) = &staged {
        if staged.build_time > status.booted.build_time {
            // A newer build is an update, and an update waits for the user (SH11).
            ctx.tools.relock()?;
        }
        if let Some(dir) = ctx.store.signature_dir(&staged.digest) {
            if let Err(failure) = ctx.tools.fetch_signature(repository, &staged.digest, &dir) {
                tracing::warn!(code = ?failure.code, "the signature object was not fetched; the next check fetches it");
            }
        }
    }
    ctx.store.set_migrated().map_err(storage)?;
    Ok(Outcome::Switched)
}
````

- [ ] **Step 4: Run the tests**

Run: `cargo-in-box test -p athanor-update migrate::`
Expected: PASS, 4 tests.

- [ ] **Step 5: Write the failing tests of `forge/specs/athanor-update/athanor-update-1.0.0/src/recover.rs`**

Create `forge/specs/athanor-update/athanor-update-1.0.0/src/recover.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::check::tests::{Machine, REPO};
    use std::path::PathBuf;

    fn vector(name: &str) -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/vectors").join(name)
    }

    #[test]
    fn begin_names_the_new_key_alone_and_finish_waits_for_an_image_that_ships_it() {
        let old = Machine::new("recover", &["real/k1.pub"]);
        let etc_keys = old.root.join("etc/athanor/keys");
        begin(&old.policy, &etc_keys, &vector("made/a.pub")).expect("begin");

        let local = crate::policy::in_force(&old.policy);
        assert!(!local.info.shipped, "the policy in force is the administrator's");
        assert_eq!(local.scopes[REPO], [etc_keys.join(RECOVERY_KEY)], "the old key is gone from the policy in force");
        assert!(std::fs::symlink_metadata(&old.policy.etc_policy).expect("meta").is_file());
        assert!(old.root.join("usr/policy.json").exists(), "the shipped policy is untouched");

        assert!(finish(&old.policy, &etc_keys).is_err(), "the booted image still ships the old key only");

        // The next image ships the new key: same machine, new /usr.
        let next = Machine::new("recover-next", &["made/a.pub"]);
        std::fs::copy(next.root.join("usr/policy.json"), old.root.join("usr/policy.json")).expect("new /usr");
        finish(&old.policy, &etc_keys).expect("finish");
        assert!(crate::policy::in_force(&old.policy).info.shipped);
        assert!(std::fs::symlink_metadata(&old.policy.etc_policy).expect("meta").is_symlink());
        assert!(!etc_keys.join(RECOVERY_KEY).exists());
    }

    #[test]
    fn begin_refuses_what_is_not_a_p256_public_key() {
        let machine = Machine::new("recover-bad", &["real/k1.pub"]);
        assert!(begin(&machine.policy, &machine.root.join("etc/athanor/keys"), &vector("made/image-digest")).is_err());
        assert!(crate::policy::in_force(&machine.policy).info.shipped, "nothing was touched");
    }
}
````

- [ ] **Step 6: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update recover::`
Expected: FAIL to compile, `cannot find function begin`.

- [ ] **Step 7: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-1.0.0/src/recover.rs`:

````rust
//! `athanor-update recover-key`: the out-of-band recovery of UT2. An administrator moves
//! one machine to a new signing key, with the old one removed, when the project has said
//! the old key is exposed. See forge/specs/athanor-update/RECOVERY.md.
//!
//! `begin NEW.pub` installs a local policy that names the new key alone, so the next
//! check accepts only images signed with it. `finish`, run after the machine has booted an
//! image whose shipped policy names the new key, gives `/etc/containers/policy.json` back
//! to the link into `/usr`. Between the two the state reads `policy-not-in-force`, which
//! is the truth: the policy in force is the administrator's.
use crate::policy::PolicyPaths;
use crate::sigobj;
use crate::store::Store;
use std::path::Path;

pub const RECOVERY_KEY: &str = "recovery.pub";

fn io(context: &str) -> impl Fn(std::io::Error) -> String + '_ {
    move |err| format!("{context}: {err}")
}

/// # Errors
/// A message for the administrator's terminal.
pub fn begin(paths: &PolicyPaths, etc_keys: &Path, new_key: &Path) -> Result<(), String> {
    let pem = std::fs::read_to_string(new_key).map_err(io("reading the new key"))?;
    sigobj::load_key(&pem).ok_or("the new key is not a PEM ECDSA P-256 public key")?;
    let shipped = std::fs::read(paths.shipped.join("policy.json")).map_err(io("reading the shipped policy"))?;
    let mut policy: serde_json::Value = serde_json::from_slice(&shipped).map_err(|err| format!("the shipped policy is not JSON: {err}"))?;
    let key_path = etc_keys.join(RECOVERY_KEY);
    let scopes: Vec<String> = crate::policy::scopes(&shipped).into_keys().collect();
    if scopes.is_empty() {
        return Err("the shipped policy has no signed repository: nothing to recover".into());
    }
    for scope in &scopes {
        for requirement in policy["transports"]["docker"][scope].as_array_mut().into_iter().flatten() {
            requirement["keyPaths"] = serde_json::json!([key_path]);
        }
    }
    std::fs::create_dir_all(etc_keys).map_err(io("creating the key directory"))?;
    Store::replace(etc_keys, RECOVERY_KEY, 0o644, pem.as_bytes()).map_err(io("installing the new key"))?;
    let (dir, name) = split(&paths.etc_policy)?;
    // The rename replaces the link into /usr with a regular file; the link target is untouched.
    Store::replace(dir, name, 0o644, policy.to_string().as_bytes()).map_err(io("installing the local policy"))
}

/// # Errors
/// A message for the administrator's terminal.
pub fn finish(paths: &PolicyPaths, etc_keys: &Path) -> Result<(), String> {
    let key_path = etc_keys.join(RECOVERY_KEY);
    let recovery = std::fs::read_to_string(&key_path).map_err(io("reading the recovery key (was `begin` run?)"))?;
    let shipped_file = paths.shipped.join("policy.json");
    let shipped = std::fs::read(&shipped_file).map_err(io("reading the shipped policy"))?;
    let scopes = crate::policy::scopes(&shipped);
    let named_everywhere = !scopes.is_empty()
        && scopes.values().all(|keys| keys.iter().any(|key| std::fs::read_to_string(key).is_ok_and(|pem| pem.trim() == recovery.trim())));
    if !named_everywhere {
        return Err("the booted image does not ship the new key in its policy yet: update and restart first".into());
    }
    let (dir, name) = split(&paths.etc_policy)?;
    let temporary = dir.join(format!(".{name}.link.{}", std::process::id()));
    match std::fs::remove_file(&temporary) {
        Err(err) if err.kind() != std::io::ErrorKind::NotFound => return Err(io("clearing a leftover")(err)),
        _ => {}
    }
    std::os::unix::fs::symlink(&shipped_file, &temporary).map_err(io("creating the link"))?;
    std::fs::rename(&temporary, &paths.etc_policy).map_err(io("restoring the link"))?;
    std::fs::remove_file(&key_path).map_err(io("removing the recovery key"))
}

fn split(path: &Path) -> Result<(&Path, &str), String> {
    match (path.parent(), path.file_name().and_then(|name| name.to_str())) {
        (Some(dir), Some(name)) => Ok((dir, name)),
        _ => Err(format!("{} has no directory or name", path.display())),
    }
}
````

- [ ] **Step 8: Run the tests**

Run: `cargo-in-box test -p athanor-update recover::`
Expected: PASS, 2 tests.

- [ ] **Step 9: The command line**

`forge/specs/athanor-update/athanor-update-1.0.0/src/main.rs`, complete (the `#![allow(dead_code)]` of Task 3 is gone):

````rust
//! `athanor-update`: checks for, downloads and applies system image updates, and publishes
//! the trust state (docs/architecture/doc_update_trust.md). One binary, run by four units:
//! `check` by the timer, `check --offline` at boot, `serve` by D-Bus activation, `migrate`
//! once per machine. `recover-key` is the administrator's command of UT2.
mod check;
mod migrate;
mod policy;
mod recover;
mod requests;
mod secureboot;
mod serve;
mod sigobj;
mod store;
mod tools;

use clap::{Parser, Subcommand};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

#[derive(Parser)]
#[command(name = "athanor-update", version, about = "Athanor system image updates and trust state")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Verify the booted image, ask the registry, download, publish the state.
    Check {
        /// Verify and publish only: no registry, no download (the run at boot).
        #[arg(long)]
        offline: bool,
    },
    /// Serve os.athanor.Update1 on the system bus until idle.
    Serve,
    /// Move this machine onto the signed reference, once.
    Migrate,
    /// Move this machine to a new image signing key (see RECOVERY.md).
    RecoverKey {
        #[command(subcommand)]
        step: RecoverStep,
    },
}

#[derive(Subcommand)]
enum RecoverStep {
    /// Trust NEW_KEY alone from now on.
    Begin { new_key: PathBuf },
    /// Return to the shipped policy, once the booted image ships the new key.
    Finish,
}

const ETC_KEYS: &str = "/etc/athanor/keys";

fn now() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |since| i64::try_from(since.as_secs()).unwrap_or(i64::MAX))
}

fn failed(what: &str, code: athanor_trust_state::ErrorCode) -> ExitCode {
    tracing::error!(?code, "{what} failed");
    ExitCode::FAILURE
}

fn main() -> ExitCode {
    tracing_subscriber::fmt().with_writer(std::io::stderr).without_time().init();
    let (tools, store) = (tools::System, store::Store::system());
    let ctx = check::Context::system(&tools, &store, now());
    match Cli::parse().command {
        Command::Check { offline } => {
            let _lock = match store.lock() {
                Ok(lock) => lock,
                Err(err) => {
                    tracing::error!(%err, "cannot take the lock: is /run/athanor-update declared in tmpfiles.d?");
                    return ExitCode::FAILURE;
                }
            };
            match check::run(&ctx, offline) {
                Ok(state) => {
                    tracing::info!(update = ?state.update, reason = ?state.verified.reason, error = ?state.last_error, "state published");
                    ExitCode::SUCCESS
                }
                Err(failure) => failed("the check", failure.code),
            }
        }
        Command::Serve => {
            let runtime = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
                Ok(runtime) => runtime,
                Err(err) => {
                    tracing::error!(%err, "cannot start the runtime");
                    return ExitCode::FAILURE;
                }
            };
            match runtime.block_on(serve::run()) {
                Ok(()) => ExitCode::SUCCESS,
                Err(err) => {
                    tracing::error!(%err, "cannot serve {}", serve::BUS_NAME);
                    ExitCode::FAILURE
                }
            }
        }
        Command::Migrate => {
            let Ok(_lock) = store.lock() else { return ExitCode::FAILURE };
            let outcome = migrate::run(&ctx);
            if let Err(failure) = check::run(&ctx, true) {
                return failed("publishing the state", failure.code);
            }
            match outcome {
                Ok(outcome) => {
                    tracing::info!(?outcome, "migration");
                    ExitCode::SUCCESS
                }
                Err(failure) => failed("the migration", failure.code),
            }
        }
        Command::RecoverKey { step } => {
            let paths = policy::PolicyPaths::system();
            let result = match step {
                RecoverStep::Begin { new_key } => recover::begin(&paths, Path::new(ETC_KEYS), &new_key),
                RecoverStep::Finish => recover::finish(&paths, Path::new(ETC_KEYS)),
            };
            match result {
                Ok(()) => ExitCode::SUCCESS,
                Err(message) => {
                    eprintln!("athanor-update: {message}");
                    ExitCode::FAILURE
                }
            }
        }
    }
}
````

- [ ] **Step 10: The administrator's document**

`forge/specs/athanor-update/RECOVERY.md`:

````markdown
# Moving a machine to a new image signing key

The image signing key is the whole of client-side trust and has no revocation
(`docs/architecture/doc_update_trust.md`, UT2). When the project announces that a key is
exposed, a machine leaves it by a new ISO or by the two commands below, run by an
administrator on the machine itself. A machine that installed an attacker's image before
this is not recoverable remotely: reinstall it.

Get the new public key from the project's announcement, over a channel other than the
registry, and compare its SHA-256 with the published one:

    sha256sum athanor-image-2.pub

1. Trust the new key alone:

       sudo athanor-update recover-key begin athanor-image-2.pub

   `/etc/containers/policy.json` becomes a local file naming only that key, stored as
   `/etc/athanor/keys/recovery.pub`. Images signed with the old key are refused from now on.
   The shield shows the exclamation mark with `policy-not-in-force`: the policy in force is
   yours, not the shipped one.

2. Let the machine update (`sudo systemctl start athanor-update-check.service`, then
   "Restart to update"), so it boots an image that ships the new key.

3. Return to the shipped policy:

       sudo athanor-update recover-key finish

   It refuses until the booted image names the new key for every system image repository.
````

- [ ] **Step 11: Whole crate**

Run: `cargo-in-box test -p athanor-update && cargo-in-box build -p athanor-update`
Expected: 45 tests pass; the build prints no warning from this crate. Then `python3 scripts/verify.py paths panics` — expected: both green (no `/tmp` literal, no `unwrap` outside tests).

- [ ] **Step 12: Commit**

````bash
git add forge/specs/athanor-update/athanor-update-1.0.0 forge/specs/athanor-update/RECOVERY.md
git commit -m "feat(update): one-time migration to the signed reference and the key recovery command"
````

### Task 7: Policy templates and the renderer

**Files:**
- Create: `forge/specs/athanor-update/SOURCES/usr/share/athanor/containers/templates/policy.json.in`, `forge/specs/athanor-update/SOURCES/usr/share/athanor/containers/templates/attachments-policy.json.in`, `forge/specs/athanor-update/SOURCES/usr/share/athanor/containers/templates/athanor.yaml.in`
- Create: `forge/specs/athanor-update/SOURCES/usr/libexec/athanor-update/render-policy` (mode 0755)
- Test: `forge/specs/athanor-update/tests/test_render_policy.py`
- Modify: `.github/workflows/call-lint.yml` (run the tests of this package)

**Interfaces:**
- Consumes: the vectors of Task 2 (`made/a.pub`, `made/b.pub`, `real/`).
- Produces: `render-policy --registry REGISTRY/OWNER --keys-dir DIR --out DIR [--link-etc ETC]`, writing `OUT/policy.json`, `OUT/attachments-policy.json`, `OUT/registries.d/athanor.yaml`; exit 2 on a registry that needs quoting, on no `*.pub`, on a `*.pub` that is not a PEM public key. `ATHANOR_POLICY_TEMPLATES` overrides the template directory (default: `../../share/athanor/containers/templates` beside the script, which is right both in the checkout's `SOURCES` tree and installed).

The rendered policy was loaded by skopeo 1.22.2 while this plan was written (`skopeo copy --policy … dir: dir:`), which is the last test below. The shape is the one spike U1 proved on the guest: `default: reject`, `transports.docker[""]` open, strict repository scopes.

- [ ] **Step 1: Write the failing tests**

`forge/specs/athanor-update/tests/test_render_policy.py`:

````python
"""Unit tests of the policy renderer
(python3 -B -m unittest discover -s forge/specs/athanor-update/tests -v)."""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
RENDER = PACKAGE / "SOURCES/usr/libexec/athanor-update/render-policy"
VECTORS = PACKAGE / "athanor-update-1.0.0/tests/vectors"
REPOSITORIES = ["athanor-system", "athanor-system-nvidia", "athanor-system-nvidia-legacy"]
OPEN_TRANSPORTS = ["docker-archive", "oci", "oci-archive", "dir", "containers-storage", "docker-daemon"]
ACCEPT = [{"type": "insecureAcceptAnything"}]


class Render(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name).resolve()
        self.keys = self.dir / "keys"
        self.keys.mkdir()
        shutil.copy(VECTORS / "made/b.pub", self.keys / "athanor-image-2.pub")
        shutil.copy(VECTORS / "made/a.pub", self.keys / "athanor-image-1.pub")

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, *extra, registry="registry.example/owner"):
        return subprocess.run(["bash", str(RENDER), "--registry", registry, "--keys-dir", str(self.keys), "--out", str(self.dir / "out"), *extra],
                              capture_output=True, text=True)

    def test_default_rejects_users_lose_nothing_and_our_three_repositories_are_strict(self):
        r = self.render()
        self.assertEqual(r.returncode, 0, r.stderr)
        policy = json.loads((self.dir / "out/policy.json").read_text())
        self.assertEqual(policy["default"], [{"type": "reject"}])
        self.assertEqual(policy["transports"]["docker"][""], ACCEPT)
        for transport in OPEN_TRANSPORTS:
            self.assertEqual(policy["transports"][transport], {"": ACCEPT}, transport)
        keys = [str(self.keys / "athanor-image-1.pub"), str(self.keys / "athanor-image-2.pub")]
        for name in REPOSITORIES:
            self.assertEqual(policy["transports"]["docker"][f"registry.example/owner/{name}"],
                             [{"type": "sigstoreSigned", "keyPaths": keys, "signedIdentity": {"type": "matchRepository"}}])
        self.assertEqual(len(policy["transports"]["docker"]), 4)

    def test_the_attachments_policy_opens_only_our_repositories(self):
        self.render()
        policy = json.loads((self.dir / "out/attachments-policy.json").read_text())
        self.assertEqual(policy["default"], [{"type": "reject"}])
        self.assertEqual(policy["transports"]["docker"], {f"registry.example/owner/{name}": ACCEPT for name in REPOSITORIES})

    def test_registries_d_declares_the_three_repositories_and_no_wider_scope(self):
        self.render()
        text = (self.dir / "out/registries.d/athanor.yaml").read_text()
        scopes = [line.strip().rstrip(":") for line in text.splitlines() if line.startswith("  ") and not line.startswith("    ")]
        self.assertEqual(scopes, [f"registry.example/owner/{name}" for name in REPOSITORIES])
        self.assertEqual(text.count("use-sigstore-attachments: true"), 3)
        self.assertNotIn("default-docker", text)

    def test_link_etc_makes_both_links(self):
        self.render("--link-etc", str(self.dir / "etc"))
        for link, target in (("policy.json", "policy.json"), ("registries.d/athanor.yaml", "registries.d/athanor.yaml")):
            path = self.dir / "etc/containers" / link
            self.assertTrue(path.is_symlink())
            self.assertEqual(path.resolve(), self.dir / "out" / target)

    def test_no_key_a_non_key_and_a_registry_that_needs_quoting_are_refused(self):
        self.assertEqual(self.render(registry='evil"/x').returncode, 2)
        (self.keys / "athanor-image-3.pub").write_text("not a key\n")
        self.assertEqual(self.render().returncode, 2)
        for key in self.keys.iterdir():
            key.unlink()
        r = self.render()
        self.assertEqual(r.returncode, 2)
        self.assertIn("no *.pub", r.stderr)

    @unittest.skipUnless(shutil.which("skopeo"), "skopeo is not installed")
    def test_containers_image_loads_the_rendered_policy(self):
        self.render()
        r = subprocess.run(["skopeo", "copy", "--policy", str(self.dir / "out/policy.json"), f"dir:{VECTORS / 'real'}", f"dir:{self.dir / 'copy'}"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
````

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-update/tests -v`
Expected: 6 errors or failures, `bash: …/render-policy: No such file or directory`.

- [ ] **Step 3: The three templates**

`forge/specs/athanor-update/SOURCES/usr/share/athanor/containers/templates/policy.json.in`:

````json
{
  "default": [{"type": "reject"}],
  "transports": {
    "docker": {
      "": [{"type": "insecureAcceptAnything"}],
      "@REGISTRY@/athanor-system": [{"type": "sigstoreSigned", "keyPaths": [@KEY_PATHS@], "signedIdentity": {"type": "matchRepository"}}],
      "@REGISTRY@/athanor-system-nvidia": [{"type": "sigstoreSigned", "keyPaths": [@KEY_PATHS@], "signedIdentity": {"type": "matchRepository"}}],
      "@REGISTRY@/athanor-system-nvidia-legacy": [{"type": "sigstoreSigned", "keyPaths": [@KEY_PATHS@], "signedIdentity": {"type": "matchRepository"}}]
    },
    "docker-archive": {"": [{"type": "insecureAcceptAnything"}]},
    "oci": {"": [{"type": "insecureAcceptAnything"}]},
    "oci-archive": {"": [{"type": "insecureAcceptAnything"}]},
    "dir": {"": [{"type": "insecureAcceptAnything"}]},
    "containers-storage": {"": [{"type": "insecureAcceptAnything"}]},
    "docker-daemon": {"": [{"type": "insecureAcceptAnything"}]}
  }
}
````

`forge/specs/athanor-update/SOURCES/usr/share/athanor/containers/templates/attachments-policy.json.in`:

````json
{
  "default": [{"type": "reject"}],
  "transports": {
    "docker": {
      "@REGISTRY@/athanor-system": [{"type": "insecureAcceptAnything"}],
      "@REGISTRY@/athanor-system-nvidia": [{"type": "insecureAcceptAnything"}],
      "@REGISTRY@/athanor-system-nvidia-legacy": [{"type": "insecureAcceptAnything"}]
    },
    "dir": {"": [{"type": "insecureAcceptAnything"}]}
  }
}
````

`forge/specs/athanor-update/SOURCES/usr/share/athanor/containers/templates/athanor.yaml.in`:

````yaml
# Only the three system image repositories: two registries.d files that declare the same
# scope are a hard error in containers/image, so no registry-wide or default scope here.
docker:
  @REGISTRY@/athanor-system:
    use-sigstore-attachments: true
  @REGISTRY@/athanor-system-nvidia:
    use-sigstore-attachments: true
  @REGISTRY@/athanor-system-nvidia-legacy:
    use-sigstore-attachments: true
````

- [ ] **Step 4: The renderer**

`forge/specs/athanor-update/SOURCES/usr/libexec/athanor-update/render-policy`, then `chmod 0755` it:

````bash
#!/usr/bin/env bash
# Renders the container signature policy of an Athanor image from its templates
# (docs/architecture/doc_update_trust.md, UT3): policy.json, attachments-policy.json and
# registries.d/athanor.yaml under --out. keyPaths is every *.pub of --keys-dir, sorted, so
# a key rotation is a file added to or removed from that directory.
# Callers: system/Containerfile (image build), system/sign-images.sh (the pipeline verifies
# with the policy a machine will have), scripts/devvm/acceptance (throwaway registry and key).
# Usage: render-policy --registry REGISTRY/OWNER --keys-dir DIR --out DIR [--link-etc ETC]
#   --link-etc ETC  also make ETC/containers/policy.json and ETC/containers/registries.d/athanor.yaml
#                   symbolic links to the rendered files (the image build passes /etc)
set -euo pipefail

usage() { echo "usage: ${0##*/} --registry REGISTRY/OWNER --keys-dir DIR --out DIR [--link-etc ETC]" >&2; exit 2; }
registry='' keys_dir='' out='' etc=''
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --registry) registry=$2 ;;
    --keys-dir) keys_dir=$2 ;;
    --out) out=$2 ;;
    --link-etc) etc=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n $registry && -n $keys_dir && -n $out ]] || usage
templates=${ATHANOR_POLICY_TEMPLATES:-$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../share/athanor/containers/templates}

# Both values are pasted into JSON and YAML: refuse anything that would need quoting.
[[ $registry =~ ^[a-z0-9]([a-z0-9._:/-]*[a-z0-9])?$ ]] || { echo "${0##*/}: not a registry/owner: '$registry'" >&2; exit 2; }
keys_dir=$(readlink -f "$keys_dir")
shopt -s nullglob
keys=("$keys_dir"/*.pub)
[[ ${#keys[@]} -gt 0 ]] || { echo "${0##*/}: no *.pub under $keys_dir: a policy with no key refuses every image" >&2; exit 2; }
key_paths=''
for key in "${keys[@]}"; do
  [[ $key =~ ^/[A-Za-z0-9._/-]+$ ]] || { echo "${0##*/}: key path needs quoting: '$key'" >&2; exit 2; }
  grep -q -- '-----BEGIN PUBLIC KEY-----' "$key" || { echo "${0##*/}: $key is not a PEM public key" >&2; exit 2; }
  key_paths+="${key_paths:+, }\"$key\""
done

mkdir -p "$out/registries.d"
render() { sed -e "s|@REGISTRY@|$registry|g" -e "s|@KEY_PATHS@|$key_paths|g" "$templates/$1" > "$2"; }
render policy.json.in "$out/policy.json"
render attachments-policy.json.in "$out/attachments-policy.json"
render athanor.yaml.in "$out/registries.d/athanor.yaml"
chmod 0644 "$out/policy.json" "$out/attachments-policy.json" "$out/registries.d/athanor.yaml"

if [[ -n $etc ]]; then
  mkdir -p "$etc/containers/registries.d"
  ln -sfn "$(readlink -f "$out")/policy.json" "$etc/containers/policy.json"
  ln -sfn "$(readlink -f "$out")/registries.d/athanor.yaml" "$etc/containers/registries.d/athanor.yaml"
fi
````

- [ ] **Step 5: Run the tests and the linters**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-update/tests -v && shellcheck forge/specs/athanor-update/SOURCES/usr/libexec/athanor-update/render-policy forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/make.sh`
Expected: `Ran 6 tests … OK`; shellcheck prints nothing.

- [ ] **Step 6: Run them in CI**

In `.github/workflows/call-lint.yml`, after the step `Session services (unit tests)`, add:

````yaml
      - name: Update and trust package (unit tests)
        run: python3 -B -m unittest discover -s forge/specs/athanor-update/tests -v
````

Run: `actionlint .github/workflows/call-lint.yml && python3 scripts/verify.py workflows`
Expected: no output from actionlint; `workflows` green.

- [ ] **Step 7: Commit**

````bash
git add forge/specs/athanor-update/SOURCES forge/specs/athanor-update/tests/test_render_policy.py .github/workflows/call-lint.yml
git commit -m "feat(update): signature policy templates and their renderer, scoped to the three system images"
````

### Task 8: The notifier `athanor-update-notify`

**Files:**
- Create: `forge/specs/athanor-update/athanor-update-notify-1.0.0/Cargo.toml`, `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/main.rs`, `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/sandbox.rs`, `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/notices.rs`, `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/text.rs`
- Modify: `Cargo.toml` (member `"forge/specs/athanor-update/athanor-update-notify-1.0.0"`), `experimental/EXEMPT` (temporary line `athanor-update-notify`, removed by Task 9)

**Interfaces:**
- Consumes: `athanor_trust_state::{read, parse, display, State, UpdateState, Deployment}` (Task 1); the bus interface of Task 5 (`os.athanor.Update1` at `/os/athanor/Update1`, methods `Apply` and `GoBack`, no arguments); `tests/state-verified.json` of Task 3.
- Produces: the binary `athanor-update-notify`; `notices::{Notice, Request, Sent, Notices::{due, invoked}, seen_booted, record_booted}`; `sandbox::{ensure_single_threaded, restrict(read: &[&Path], write: &Path), state_dir}`; `text::{texts, session_locale}`.

Decisions: **"Later" against the re-offer.** `doc_shell.md` acceptance 4 says "Later is never asked again for that digest"; UT11, the later and more specific text, says a pending digest is offered "again once per session start" while no shield exists. The set of offered digests therefore lives in the process, and a new session is a new process. **The write grant** is decision A9. **Sender filtering** is a pure function, `Notices::invoked`, so the forged-signal cases are unit tests; the owner of `org.freedesktop.Notifications` is read before each `Notify` and stored with the id. **Translations** are a two-entry table until plan 1a's `athanor-i18n` exists; the call sites do not change when it does.

- [ ] **Step 1: Manifest, member, exemption**

`forge/specs/athanor-update/athanor-update-notify-1.0.0/Cargo.toml`:

````toml
[package]
name = "athanor-update-notify"
version = "1.0.0"
edition = "2021"
authors = ["Athanor Forge <forge@athanor.os>"]
description = "Tells the user that a system update is ready, or that a new version is running"
license = "MIT"

[dependencies]
athanor-trust-state = { path = "../../../../system/athanor-trust-state" }
zbus = { workspace = true }
tokio = { workspace = true }
futures-util = { workspace = true }
tracing = { workspace = true }
tracing-subscriber = { workspace = true }
landlock = "0.4"
chrono = { version = "0.4", default-features = false, features = ["std"] }
````

Add `    "forge/specs/athanor-update/athanor-update-notify-1.0.0",` to the root `Cargo.toml` members, after the `athanor-update` line, and the line `athanor-update-notify` to `experimental/EXEMPT`.

- [ ] **Step 2: Write the failing tests of `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/sandbox.rs`**

Create `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/sandbox.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_outside_the_grants_and_writes_outside_the_state_directory_are_denied() {
        let base = std::env::temp_dir().join(format!("athanor-update-notify-landlock-{}", std::process::id()));
        let (readable, writable, hidden) = (base.join("readable"), base.join("writable"), base.join("hidden"));
        for dir in [&readable, &writable, &hidden] {
            std::fs::create_dir_all(dir).expect("mkdir");
            std::fs::write(dir.join("file"), b"x").expect("write");
        }
        let base_for_thread = base.clone();
        // Landlock confines the calling thread and its children: the test binary stays free.
        std::thread::spawn(move || {
            restrict(&[&readable], &writable).expect("Landlock must be enforced, not skipped");
            assert!(std::fs::read(readable.join("file")).is_ok());
            assert_eq!(std::fs::write(readable.join("new"), b"x").expect_err("read-only").kind(), std::io::ErrorKind::PermissionDenied);
            assert!(std::fs::write(writable.join("new"), b"x").is_ok());
            assert_eq!(std::fs::read(hidden.join("file")).expect_err("not granted").kind(), std::io::ErrorKind::PermissionDenied);
            assert_eq!(std::fs::read(base_for_thread.join("hidden/file")).expect_err("not granted").kind(), std::io::ErrorKind::PermissionDenied);
        })
        .join()
        .expect("sandboxed thread");
        std::fs::remove_dir_all(base).expect("cleanup");
    }

    #[test]
    fn a_second_thread_fails_the_single_thread_check() {
        let (release, wait) = std::sync::mpsc::channel::<()>();
        let other = std::thread::spawn(move || wait.recv());
        assert!(ensure_single_threaded().is_err());
        release.send(()).expect("release");
        other.join().expect("join").expect("released");
    }
}
````

- [ ] **Step 3: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update-notify sandbox::`
Expected: FAIL to compile, `cannot find function restrict`.

- [ ] **Step 4: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/sandbox.rs`:

````rust
//! Landlock at start, as the greeter does (`athanor-shell-rs`, `src/sys/sandbox.rs`):
//! first prove the process is single-threaded, then restrict. Unlike the greeter, this
//! process needs almost nothing, so reads are handled too: `/usr` (its libraries and the
//! translations), the state directory of athanor-update, and one directory of its own to
//! write. Connecting to the bus sockets is not a filesystem access Landlock mediates.
use landlock::{Access, AccessFs, CompatLevel, Compatible, PathBeneath, PathFd, Ruleset, RulesetAttr, RulesetCreatedAttr, ABI};
use std::path::{Path, PathBuf};

/// Fails unless the calling process has exactly one thread: Landlock confines the calling
/// thread and those it creates afterwards, not threads that already exist.
pub fn ensure_single_threaded() -> Result<(), Box<dyn std::error::Error>> {
    let threads = std::fs::read_dir("/proc/self/task")?.count();
    if threads != 1 {
        return Err(format!("{threads} threads exist; Landlock would leave all but one unconfined").into());
    }
    Ok(())
}

/// Read-only beneath `read`, read-write beneath `write`, nothing else. A kernel that cannot
/// enforce the ruleset is an error, not a best effort.
pub fn restrict(read: &[&Path], write: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let all = AccessFs::from_all(ABI::V1);
    let mut ruleset = Ruleset::default().set_compatibility(CompatLevel::HardRequirement).handle_access(all)?.create()?;
    for path in read.iter().filter(|path| path.exists()) {
        ruleset = ruleset.add_rule(PathBeneath::new(PathFd::new(path)?, AccessFs::from_read(ABI::V1)))?;
    }
    ruleset = ruleset.add_rule(PathBeneath::new(PathFd::new(write)?, all))?;
    ruleset.restrict_self()?;
    Ok(())
}

/// `$XDG_STATE_HOME/athanor-update-notify`, created if missing.
pub fn state_dir() -> Result<PathBuf, Box<dyn std::error::Error>> {
    let base = std::env::var_os("XDG_STATE_HOME").filter(|dir| !dir.is_empty()).map(PathBuf::from).or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/state")));
    let dir = base.filter(|dir| dir.is_absolute()).ok_or("neither XDG_STATE_HOME nor HOME is an absolute path")?.join("athanor-update-notify");
    std::fs::create_dir_all(&dir)?;
    Ok(dir)
}
````

- [ ] **Step 5: Run the tests**

Run: `cargo-in-box test -p athanor-update-notify sandbox::`
Expected: PASS, 2 tests (they need a kernel with Landlock; the build container on this host has it).

- [ ] **Step 6: Write the failing tests of `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/text.rs`**

Create `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/text.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn italian_for_an_italian_session_english_otherwise() {
        assert_eq!(texts(Some("it_IT.UTF-8")).later, "Più tardi");
        assert_eq!(texts(Some("de_DE.UTF-8")).later, "Later");
        assert_eq!(texts(None).restart, "Restart to update");
    }
}
````

- [ ] **Step 7: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update-notify text::`
Expected: FAIL to compile, `cannot find function texts`.

- [ ] **Step 8: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/text.rs`:

````rust
//! The words of the two notifications, in the two shipped locales.
// ponytail: a two-language table. When plan 1a's `system/athanor-i18n` lands, replace the
// body of `texts` with catalog lookups; the callers do not change.

pub struct Texts {
    pub ready_summary: &'static str,
    pub ready_body: &'static str,
    pub restart: &'static str,
    pub later: &'static str,
    pub running_summary: &'static str,
    /// `{version}` and `{date}` are replaced.
    pub running_body: &'static str,
    pub go_back: &'static str,
}

const EN: Texts = Texts {
    ready_summary: "A system update is ready",
    ready_body: "It is installed when you restart. Nothing changes until then.",
    restart: "Restart to update",
    later: "Later",
    running_summary: "The system was updated",
    running_body: "Version {version} of {date} is now running.",
    go_back: "Go back to the previous version",
};

const IT: Texts = Texts {
    ready_summary: "Un aggiornamento di sistema è pronto",
    ready_body: "Viene installato al riavvio. Fino ad allora non cambia nulla.",
    restart: "Riavvia per aggiornare",
    later: "Più tardi",
    running_summary: "Il sistema è stato aggiornato",
    running_body: "Ora è in esecuzione la versione {version} del {date}.",
    go_back: "Torna alla versione precedente",
};

/// The locale of the session: `LC_ALL`, then `LC_MESSAGES`, then `LANG`.
#[must_use]
pub fn texts(locale: Option<&str>) -> &'static Texts {
    if locale.is_some_and(|locale| locale.starts_with("it")) { &IT } else { &EN }
}

#[must_use]
pub fn session_locale() -> Option<String> {
    ["LC_ALL", "LC_MESSAGES", "LANG"].iter().find_map(|name| std::env::var(name).ok().filter(|value| !value.is_empty()))
}
````

- [ ] **Step 9: Run the tests**

Run: `cargo-in-box test -p athanor-update-notify text::`
Expected: PASS, 1 test.

- [ ] **Step 10: Write the failing tests of `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/notices.rs`**

Create `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/notices.rs` holding only this test module:

````rust
#[cfg(test)]
mod tests {
    use super::*;

    fn state(booted: &str, downloaded: Option<&str>, update: UpdateState) -> State {
        let text = include_str!("../../athanor-update-1.0.0/tests/state-verified.json");
        let mut state = athanor_trust_state::parse(text).expect("fixture");
        state.booted.digest = booted.into();
        state.previous = Some(state.booted.clone());
        state.downloaded = downloaded.map(|digest| athanor_trust_state::Deployment { digest: digest.into(), ..state.booted.clone() });
        state.update = update;
        state
    }

    #[test]
    fn one_notice_per_downloaded_digest_per_session() {
        let mut notices = Notices::default();
        let ready = state("sha256:a", Some("sha256:b"), UpdateState::Downloaded);
        assert_eq!(notices.due(&ready, Some("sha256:a")), Some(Notice::Ready { digest: "sha256:b".into() }));
        assert_eq!(notices.due(&ready, Some("sha256:a")), None, "\"Later\" is not asked again in this session");
        // A new session is a new process: the pending digest is offered once more.
        assert!(Notices::default().due(&ready, Some("sha256:a")).is_some());
        let newer = state("sha256:a", Some("sha256:c"), UpdateState::Downloaded);
        assert_eq!(notices.due(&newer, Some("sha256:a")), Some(Notice::Ready { digest: "sha256:c".into() }));
    }

    #[test]
    fn only_a_downloaded_update_is_announced() {
        for update in [UpdateState::Available, UpdateState::Held, UpdateState::OlderThanBooted, UpdateState::Refused, UpdateState::WillApplyAtNextShutdown] {
            assert_eq!(Notices::default().due(&state("sha256:a", Some("sha256:b"), update), Some("sha256:a")), None, "{update:?}");
        }
    }

    #[test]
    fn a_new_deployment_is_announced_once_and_never_on_a_first_session() {
        let mut notices = Notices::default();
        let booted = state("sha256:b", None, UpdateState::None);
        assert_eq!(notices.due(&booted, None), None, "first session of this user");
        assert!(matches!(notices.due(&booted, Some("sha256:a")), Some(Notice::Running { .. })));
        assert_eq!(notices.due(&booted, Some("sha256:a")), None);
        assert_eq!(notices.due(&booted, Some("sha256:b")), None);
    }

    #[test]
    fn a_forged_action_is_dropped() {
        let mut notices = Notices::default();
        notices.sent.insert(7, Sent { server: ":1.42".into(), notice: Notice::Running { digest: "sha256:b".into(), version: "43".into(), build_time: 0 } });
        assert_eq!(notices.invoked(":1.666", 7, ACTION_GO_BACK), None, "another sender");
        assert_eq!(notices.invoked(":1.42", 8, ACTION_GO_BACK), None, "an id this process does not hold");
        assert_eq!(notices.invoked(":1.42", 7, ACTION_APPLY), None, "an action that notification never offered");
        assert_eq!(notices.invoked(":1.42", 7, ACTION_GO_BACK), None, "the id was forgotten by the wrong action");
        notices.sent.insert(9, Sent { server: ":1.42".into(), notice: Notice::Ready { digest: "sha256:c".into() } });
        assert_eq!(notices.invoked(":1.42", 9, ACTION_APPLY), Some(Request::Apply));
        assert_eq!(notices.invoked(":1.42", 9, ACTION_APPLY), None, "once");
    }

    #[test]
    fn the_seen_record_round_trips() {
        let dir = std::env::temp_dir().join(format!("athanor-update-notify-seen-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("mkdir");
        assert_eq!(seen_booted(&dir), None);
        record_booted(&dir, "sha256:a").expect("write");
        assert_eq!(seen_booted(&dir).as_deref(), Some("sha256:a"));
        std::fs::remove_dir_all(dir).expect("cleanup");
    }
}
````

- [ ] **Step 11: Run them to see them fail**

Run: `cargo-in-box test -p athanor-update-notify notices::`
Expected: FAIL to compile, `cannot find struct Notices`.

- [ ] **Step 12: Write the implementation**

Put this above the test module in `forge/specs/athanor-update/athanor-update-notify-1.0.0/src/notices.rs`:

````rust
//! What to tell the user, and which `ActionInvoked` signals to believe (UT11). No bus here:
//! `main.rs` sends what this module decides.
use athanor_trust_state::{State, UpdateState};
use std::collections::{HashMap, HashSet};
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Notice {
    /// A downloaded digest waits for a restart.
    Ready { digest: String },
    /// A new deployment booted for the first time, and there is a way back.
    Running { digest: String, version: String, build_time: i64 },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Request {
    Apply,
    GoBack,
}

pub const ACTION_APPLY: &str = "apply";
pub const ACTION_LATER: &str = "later";
pub const ACTION_GO_BACK: &str = "go-back";

/// A notification this process sent and still answers for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Sent {
    /// The unique name that owned `org.freedesktop.Notifications` when it was sent.
    pub server: String,
    pub notice: Notice,
}

#[derive(Default)]
pub struct Notices {
    /// Digests offered since this process started: one notice per digest and per session.
    offered: HashSet<String>,
    pub sent: HashMap<u32, Sent>,
}

impl Notices {
    /// The notice `state` calls for, if any. `seen_booted` is the digest recorded by the
    /// last run; `None` means this user has never run the notifier, and a first session is
    /// not greeted with "the system was updated".
    pub fn due(&mut self, state: &State, seen_booted: Option<&str>) -> Option<Notice> {
        if seen_booted.is_some_and(|seen| seen != state.booted.digest) && state.previous.is_some() && self.offered.insert(format!("running {}", state.booted.digest)) {
            return Some(Notice::Running { digest: state.booted.digest.clone(), version: state.booted.version.clone(), build_time: state.booted.build_time });
        }
        let downloaded = state.downloaded.as_ref().filter(|_| state.update == UpdateState::Downloaded)?;
        self.offered.insert(downloaded.digest.clone()).then(|| Notice::Ready { digest: downloaded.digest.clone() })
    }

    /// The request an `ActionInvoked(id, action)` from `sender` stands for. Any session
    /// process can emit that signal, and a forged one would summon the administrator prompt
    /// of `GoBack()` out of nowhere: only the server that took the notification, and only an
    /// id this process holds, are believed. The id is forgotten either way.
    pub fn invoked(&mut self, sender: &str, id: u32, action: &str) -> Option<Request> {
        if self.sent.get(&id)?.server != sender {
            return None;
        }
        match (self.sent.remove(&id)?.notice, action) {
            (Notice::Ready { .. }, ACTION_APPLY) => Some(Request::Apply),
            (Notice::Running { .. }, ACTION_GO_BACK) => Some(Request::GoBack),
            _ => None,
        }
    }
}

const SEEN_FILE: &str = "seen-booted";

#[must_use]
pub fn seen_booted(state_dir: &Path) -> Option<String> {
    std::fs::read_to_string(state_dir.join(SEEN_FILE)).ok().map(|text| text.trim().to_owned())
}

/// # Errors
/// The record cannot be written.
pub fn record_booted(state_dir: &Path, digest: &str) -> std::io::Result<()> {
    let temporary = state_dir.join(format!(".{SEEN_FILE}.{}", std::process::id()));
    std::fs::write(&temporary, format!("{digest}\n"))?;
    std::fs::rename(temporary, state_dir.join(SEEN_FILE))
}
````

- [ ] **Step 13: Run the tests**

Run: `cargo-in-box test -p athanor-update-notify notices::`
Expected: PASS, 5 tests.

For Steps 2 to 13 the crate needs a `src/main.rs` to compile: start it as `mod notices;\nmod sandbox;\nmod text;\n\nfn main() {}` with `#![allow(dead_code)]` on top, and replace it in the next step.

- [ ] **Step 14: The program**

`forge/specs/athanor-update/athanor-update-notify-1.0.0/src/main.rs`, complete:

````rust
//! `athanor-update-notify`: the user side of updates until the shield exists
//! (docs/architecture/doc_update_trust.md, UT11). It reads the state file, sends
//! notifications, and calls `Apply()` and `GoBack()`. Nothing else.
mod notices;
mod sandbox;
mod text;

use futures_util::StreamExt as _;
use notices::{Notice, Notices, Request, Sent};
use std::collections::HashMap;
use std::path::Path;
use std::process::ExitCode;
use std::time::Duration;
use zbus::zvariant::Value;
use zbus::{Connection, MatchRule, MessageStream};

const SERVER: &str = "org.freedesktop.Notifications";
const SERVER_PATH: &str = "/org/freedesktop/Notifications";
const UPDATE: &str = "os.athanor.Update1";
const UPDATE_PATH: &str = "/os/athanor/Update1";
// ponytail: the file changes a few times a day and is 1 kB; a poll is enough. Watch the
// directory with inotify if a surface ever needs the change within a second.
const POLL: Duration = Duration::from_secs(30);

async fn send(session: &Connection, notice: &Notice) -> zbus::Result<(u32, String)> {
    let t = text::texts(text::session_locale().as_deref());
    let (summary, body, actions) = match notice {
        Notice::Ready { .. } => (t.ready_summary, t.ready_body.to_owned(), vec![notices::ACTION_APPLY, t.restart, notices::ACTION_LATER, t.later]),
        Notice::Running { version, build_time, .. } => {
            let date = chrono::DateTime::from_timestamp(*build_time, 0).map(|time| time.format("%Y-%m-%d").to_string()).unwrap_or_default();
            // The version comes from a world-readable file: plain text, stripped, truncated.
            let body = t.running_body.replace("{version}", &athanor_trust_state::display(version)).replace("{date}", &date);
            (t.running_summary, body, vec![notices::ACTION_GO_BACK, t.go_back])
        }
    };
    // The owner is read before the call, so the id returned is tied to the server asked.
    let owner = zbus::fdo::DBusProxy::new(session).await?.get_name_owner(zbus::names::BusName::try_from(SERVER)?).await?.to_string();
    let hints: HashMap<&str, Value<'_>> = HashMap::from([("urgency", Value::U8(1)), ("resident", Value::Bool(true))]);
    let reply = session
        .call_method(Some(SERVER), SERVER_PATH, Some(SERVER), "Notify", &("Athanor", 0u32, "software-update-available-symbolic", summary, body.as_str(), actions, hints, 0i32))
        .await?;
    Ok((reply.body().deserialize::<u32>()?, owner))
}

async fn request(system: &Connection, request: Request) {
    let method = match request {
        Request::Apply => "Apply",
        Request::GoBack => "GoBack",
    };
    if let Err(err) = system.call_method(Some(UPDATE), UPDATE_PATH, Some(UPDATE), method, &()).await {
        tracing::warn!(%err, method, "the request was refused");
    }
}

async fn run(state_dir: &Path) -> zbus::Result<()> {
    let (session, system) = (Connection::session().await?, Connection::system().await?);
    let rule = MatchRule::builder().msg_type(zbus::message::Type::Signal).interface(SERVER)?.member("ActionInvoked")?.path(SERVER_PATH)?.build();
    let mut invoked = MessageStream::for_match_rule(rule, &session, None).await?;
    let mut notices = Notices::default();
    let mut poll = tokio::time::interval(POLL);
    loop {
        tokio::select! {
            _ = poll.tick() => {
                let Ok(state) = athanor_trust_state::read() else { continue };
                let seen = notices::seen_booted(state_dir);
                if let Some(notice) = notices.due(&state, seen.as_deref()) {
                    match send(&session, &notice).await {
                        Ok((id, server)) => { notices.sent.insert(id, Sent { server, notice }); }
                        Err(err) => tracing::warn!(%err, "the notification was not sent"),
                    }
                }
                if seen.as_deref() != Some(state.booted.digest.as_str()) {
                    if let Err(err) = notices::record_booted(state_dir, &state.booted.digest) {
                        tracing::warn!(%err, "the booted digest was not recorded");
                    }
                }
            }
            Some(Ok(message)) = invoked.next() => {
                let header = message.header();
                let (Some(sender), Ok((id, action))) = (header.sender(), message.body().deserialize::<(u32, String)>()) else { continue };
                if let Some(wanted) = notices.invoked(sender.as_str(), id, &action) {
                    request(&system, wanted).await;
                }
            }
        }
    }
}

fn main() -> ExitCode {
    tracing_subscriber::fmt().with_writer(std::io::stderr).without_time().init();
    // The sandbox comes first, while the process has one thread; the runtime is single-threaded too.
    let confined = sandbox::state_dir().and_then(|dir| {
        sandbox::ensure_single_threaded()?;
        sandbox::restrict(&[Path::new("/usr"), Path::new("/run/athanor-update")], &dir)?;
        Ok(dir)
    });
    let state_dir = match confined {
        Ok(dir) => dir,
        Err(err) => {
            tracing::error!(%err, "refusing to run unconfined");
            return ExitCode::FAILURE;
        }
    };
    let runtime = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
        Ok(runtime) => runtime,
        Err(err) => {
            tracing::error!(%err, "cannot start the runtime");
            return ExitCode::FAILURE;
        }
    };
    match runtime.block_on(run(&state_dir)) {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            tracing::error!(%err, "the session or system bus is not reachable");
            ExitCode::FAILURE
        }
    }
}
````

- [ ] **Step 15: Whole crate**

Run: `cargo-in-box test -p athanor-update-notify && cargo-in-box build -p athanor-update-notify`
Expected: 8 tests pass; no warning from this crate.

- [ ] **Step 16: Commit**

````bash
git add Cargo.toml Cargo.lock experimental/EXEMPT forge/specs/athanor-update/athanor-update-notify-1.0.0
git commit -m "feat(update): the notifier, confined with Landlock, deaf to forged ActionInvoked signals"
````

### Task 9: Package `athanor-update`; remove the broken preset line and override

**Files:**
- Create: `forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update-check.timer`
- Create: `forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update-check.service`
- Create: `forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update.service`
- Create: `forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update-state.service`
- Create: `forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update-migrate.service`
- Create: `forge/specs/athanor-update/SOURCES/usr/lib/systemd/user/athanor-update-notify.service`
- Create: `forge/specs/athanor-update/SOURCES/usr/lib/systemd/system-preset/80-athanor-update.preset`
- Create: `forge/specs/athanor-update/SOURCES/usr/lib/systemd/user-preset/80-athanor-update.preset`
- Create: `forge/specs/athanor-update/SOURCES/usr/lib/tmpfiles.d/athanor-update.conf`
- Create: `forge/specs/athanor-update/SOURCES/usr/share/dbus-1/system.d/os.athanor.Update1.conf`
- Create: `forge/specs/athanor-update/SOURCES/usr/share/dbus-1/system-services/os.athanor.Update1.service`
- Create: `forge/specs/athanor-update/SOURCES/usr/share/polkit-1/actions/os.athanor.update.policy`
- Create: `forge/specs/athanor-update/athanor-update.spec`, `forge/specs/athanor-update/tests/test_units.py`, `scripts/tests/test_verify_update_trust.py`
- Modify: `scripts/verify.py` (`crates_built_by_specs`, `update_trust_problems`, two hooks in `check_shipped`)
- Modify: `forge/config/packages.json` (`"update"` in `custom_packages` and in `custom_tier3`), `experimental/EXEMPT` (remove the two temporary lines)
- Modify: `forge/specs/athanor-system-config/SOURCES/usr/lib/systemd/system-preset/80-athanor-system.preset:8` (delete `enable bootc-fetch-apply.timer`), `forge/specs/athanor-system-config/athanor-system-config.spec` (Release 41 to 42, changelog)
- Delete: `forge/specs/athanor-base-config/SOURCES/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/override.conf`; modify `forge/specs/athanor-base-config/athanor-base-config.spec` (line 82 of `%files`, Release 9 to 10, changelog)

**Interfaces:**
- Consumes: the binaries of Tasks 6 and 8, the renderer and templates of Task 7.
- Produces: the RPM `athanor-update`; units `athanor-update-check.timer`, `athanor-update-check.service`, `athanor-update.service`, `athanor-update-state.service`, `athanor-update-migrate.service`, user unit `athanor-update-notify.service`; `verify.update_trust_problems(root=None) -> list[str]`, `verify.crates_built_by_specs(root=None) -> dict[str, str]`.

An image that carries this RPM before Task 16 is inert and honest: without the `/etc/containers` links the policy is not in force, so `migrate` waits, the check downloads nothing (decision A5), and the state reads `policy-not-in-force`. The activation file keeps `Name=` and `Exec=`, which the file format requires; UT6's "nothing else" is read as: no other key.

- [ ] **Step 1: Write the failing tests of the unit, bus and polkit files**

`forge/specs/athanor-update/tests/test_units.py`:

````python
"""The units of athanor-update carry the hardening spike U1 measured, and nothing it found
to break bootc (python3 -B -m unittest discover -s forge/specs/athanor-update/tests -v)."""

import pathlib
import re
import shutil
import subprocess
import unittest
import xml.dom.minidom

SOURCES = pathlib.Path(__file__).resolve().parents[1] / "SOURCES"
UNITS = SOURCES / "usr/lib/systemd/system"
MEASURED = [
    "NoNewPrivileges=yes", "ProtectHome=yes", "PrivateTmp=yes", "ProtectKernelTunables=yes",
    "ProtectKernelModules=yes", "ProtectControlGroups=yes", "ProtectProc=invisible", "LockPersonality=yes",
    "MemoryDenyWriteExecute=yes", "UMask=0022", "SystemCallFilter=@system-service @mount",
    "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK", "RestrictNamespaces=~user",
    "CapabilityBoundingSet=~CAP_SYS_MODULE CAP_SYS_BOOT CAP_SYS_RAWIO CAP_NET_ADMIN",
]
# unit -> (reaches the network, systemd-analyze exposure threshold in tenths)
SERVICES = {
    "athanor-update-check.service": (True, 60),
    "athanor-update-migrate.service": (True, 60),
    "athanor-update.service": (False, 55),
    "athanor-update-state.service": (False, 55),
}


def directives(unit):
    return [line.strip() for line in (UNITS / unit).read_text().splitlines() if "=" in line and not line.lstrip().startswith("#")]


class Units(unittest.TestCase):
    def test_every_service_carries_the_measured_list_verbatim(self):
        for unit in SERVICES:
            for directive in MEASURED:
                self.assertIn(directive, directives(unit), f"{unit}: {directive}")

    def test_no_service_carries_what_breaks_bootc(self):
        for unit in SERVICES:
            text = "\n".join(directives(unit))
            self.assertNotIn("RestrictSUIDSGID", text, unit)
            self.assertNotIn("ProtectSystem", text, unit)
            for bounding in re.findall(r"^CapabilityBoundingSet=(.*)$", text, re.M):
                self.assertTrue(bounding.startswith("~"), f"{unit}: capabilities are subtracted, never enumerated")

    def test_only_the_units_that_need_the_registry_reach_the_network(self):
        for unit, (network, _) in SERVICES.items():
            lines = directives(unit)
            self.assertEqual("PrivateNetwork=yes" not in lines, network, unit)
            self.assertFalse(any(line.startswith("IPAddressDeny") for line in lines) and network, unit)

    def test_each_unit_runs_the_subcommand_it_is_named_for(self):
        expected = {"athanor-update-check.service": "check", "athanor-update-migrate.service": "migrate",
                    "athanor-update.service": "serve", "athanor-update-state.service": "check --offline"}
        for unit, arguments in expected.items():
            self.assertIn(f"ExecStart=/usr/bin/athanor-update {arguments}", directives(unit))

    def test_the_timer_is_fifteen_minutes_then_six_hours_with_a_random_delay(self):
        lines = directives("athanor-update-check.timer")
        for directive in ("OnBootSec=15min", "OnUnitActiveSec=6h"):
            self.assertIn(directive, lines)
        self.assertTrue(any(line.startswith("RandomizedDelaySec=") for line in lines))

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze is not installed")
    def test_exposure_stays_below_the_stated_threshold(self):
        for unit, (_, threshold) in SERVICES.items():
            r = subprocess.run(["systemd-analyze", "security", "--offline=true", f"--threshold={threshold}", "--no-pager", str(UNITS / unit)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{unit}: {r.stdout[-200:]}{r.stderr[-200:]}")


class Presets(unittest.TestCase):
    def test_our_units_are_enabled_and_the_stock_timer_is_not(self):
        preset = (SOURCES / "usr/lib/systemd/system-preset/80-athanor-update.preset").read_text()
        for line in ("enable athanor-update-check.timer", "enable athanor-update-state.service",
                     "enable athanor-update-migrate.service", "disable bootc-fetch-apply-updates.timer"):
            self.assertIn(line, preset.splitlines())
        self.assertIn("enable athanor-update-notify.service", (SOURCES / "usr/lib/systemd/user-preset/80-athanor-update.preset").read_text())

    def test_tmpfiles_declares_both_directories_and_not_the_disk_key_directory(self):
        lines = [l for l in (SOURCES / "usr/lib/tmpfiles.d/athanor-update.conf").read_text().splitlines() if l and not l.startswith("#")]
        self.assertIn("d /run/athanor-update 0755 root root -", lines)
        self.assertIn("d /var/lib/athanor-update 0755 root root -", lines)
        self.assertFalse(any(re.search(r"\s/run/athanor(\s|/\s|$)", line) for line in lines))


class Bus(unittest.TestCase):
    def test_the_bus_policy_allows_two_members_and_introspection_only(self):
        doc = xml.dom.minidom.parse(str(SOURCES / "usr/share/dbus-1/system.d/os.athanor.Update1.conf"))
        allows = [dict(node.attributes.items()) for node in doc.getElementsByTagName("allow")]
        sends = [a for a in allows if "send_destination" in a]
        self.assertEqual(sorted((a["send_interface"], a["send_member"]) for a in sends),
                         [("org.freedesktop.DBus.Introspectable", "Introspect"), ("os.athanor.Update1", "Apply"), ("os.athanor.Update1", "GoBack")])
        self.assertTrue(all(a["send_destination"] == "os.athanor.Update1" for a in sends))
        self.assertEqual([a for a in allows if "own" in a], [{"own": "os.athanor.Update1"}])

    def test_the_activation_file_starts_the_systemd_unit_as_root(self):
        lines = (SOURCES / "usr/share/dbus-1/system-services/os.athanor.Update1.service").read_text().splitlines()
        self.assertEqual(lines, ["[D-BUS Service]", "Name=os.athanor.Update1", "Exec=/bin/false", "User=root", "SystemdService=athanor-update.service"])

    def test_the_polkit_defaults_are_logind_s_for_apply_and_auth_admin_for_going_back(self):
        doc = xml.dom.minidom.parse(str(SOURCES / "usr/share/polkit-1/actions/os.athanor.update.policy"))
        found = {}
        for action in doc.getElementsByTagName("action"):
            defaults = action.getElementsByTagName("defaults")[0]
            found[action.getAttribute("id")] = tuple(defaults.getElementsByTagName(tag)[0].firstChild.data for tag in ("allow_any", "allow_inactive", "allow_active"))
        self.assertEqual(found, {"os.athanor.update.apply": ("auth_admin_keep", "auth_admin_keep", "yes"),
                                 "os.athanor.update.rollback": ("auth_admin", "auth_admin", "auth_admin")})


if __name__ == "__main__":
    unittest.main()
````

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-update/tests -p 'test_units.py' -v`
Expected: 11 errors, `FileNotFoundError`.

- [ ] **Step 3: The files**

`forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update-check.timer`:

````ini
[Unit]
Description=Check for Athanor system image updates
Documentation=https://github.com/hr-mes/athanor/blob/iso-v0/docs/architecture/doc_update_trust.md

[Timer]
OnBootSec=15min
OnUnitActiveSec=6h
RandomizedDelaySec=30min
Persistent=no

[Install]
WantedBy=timers.target
````

`forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update-check.service`:

````ini
[Unit]
Description=Check for, verify and download an Athanor system image update
Documentation=https://github.com/hr-mes/athanor/blob/iso-v0/docs/architecture/doc_update_trust.md
After=network-online.target athanor-update-migrate.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/athanor-update check
# The only unit of this package that reaches the network: no PrivateNetwork, no IPAddressDeny.
# Measured by spike U1 against a real `bootc upgrade --download-only` and a real
# `--from-downloaded` (doc_update_trust.md, UT1). Do not add RestrictSUIDSGID (bootc fails on
# its runtime auth file), an allow-list CapabilityBoundingSet (breaks the setpriv bootc starts
# its skopeo proxy with) or ProtectSystem=strict (bootc writes the sysroot).
NoNewPrivileges=yes
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
ProtectProc=invisible
LockPersonality=yes
MemoryDenyWriteExecute=yes
UMask=0022
SystemCallFilter=@system-service @mount
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
RestrictNamespaces=~user
CapabilityBoundingSet=~CAP_SYS_MODULE CAP_SYS_BOOT CAP_SYS_RAWIO CAP_NET_ADMIN
````

`forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update.service`:

````ini
[Unit]
Description=Athanor update requests (os.athanor.Update1)
Documentation=https://github.com/hr-mes/athanor/blob/iso-v0/docs/architecture/doc_update_trust.md

[Service]
Type=dbus
BusName=os.athanor.Update1
ExecStart=/usr/bin/athanor-update serve
# The unit unprivileged callers talk to never reaches the network: Apply() never downloads.
PrivateNetwork=yes
# Measured by spike U1 against a real `bootc upgrade --download-only` and a real
# `--from-downloaded` (doc_update_trust.md, UT1). Do not add RestrictSUIDSGID (bootc fails on
# its runtime auth file), an allow-list CapabilityBoundingSet (breaks the setpriv bootc starts
# its skopeo proxy with) or ProtectSystem=strict (bootc writes the sysroot).
NoNewPrivileges=yes
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
ProtectProc=invisible
LockPersonality=yes
MemoryDenyWriteExecute=yes
UMask=0022
SystemCallFilter=@system-service @mount
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
RestrictNamespaces=~user
CapabilityBoundingSet=~CAP_SYS_MODULE CAP_SYS_BOOT CAP_SYS_RAWIO CAP_NET_ADMIN
````

`forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update-state.service`:

````ini
[Unit]
Description=Publish the Athanor trust state at boot
Documentation=https://github.com/hr-mes/athanor/blob/iso-v0/docs/architecture/doc_update_trust.md
After=systemd-tmpfiles-setup.service
Before=display-manager.service greetd.service

[Service]
Type=oneshot
ExecStart=/usr/bin/athanor-update check --offline
PrivateNetwork=yes
# Measured by spike U1 against a real `bootc upgrade --download-only` and a real
# `--from-downloaded` (doc_update_trust.md, UT1). Do not add RestrictSUIDSGID (bootc fails on
# its runtime auth file), an allow-list CapabilityBoundingSet (breaks the setpriv bootc starts
# its skopeo proxy with) or ProtectSystem=strict (bootc writes the sysroot).
NoNewPrivileges=yes
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
ProtectProc=invisible
LockPersonality=yes
MemoryDenyWriteExecute=yes
UMask=0022
SystemCallFilter=@system-service @mount
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
RestrictNamespaces=~user
CapabilityBoundingSet=~CAP_SYS_MODULE CAP_SYS_BOOT CAP_SYS_RAWIO CAP_NET_ADMIN

[Install]
WantedBy=multi-user.target
````

`forge/specs/athanor-update/SOURCES/usr/lib/systemd/system/athanor-update-migrate.service`:

````ini
[Unit]
Description=Move this machine onto the signed Athanor image reference
Documentation=https://github.com/hr-mes/athanor/blob/iso-v0/docs/architecture/doc_update_trust.md
ConditionPathExists=!/var/lib/athanor-update/migrated
After=network-online.target athanor-update-state.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/athanor-update migrate
# NetworkManager-wait-online is disabled on this image (80-athanor-base.preset), so
# network-online.target says little: a run without a network fails and is tried again.
Restart=on-failure
RestartSec=5min
# Measured by spike U1 against a real `bootc upgrade --download-only` and a real
# `--from-downloaded` (doc_update_trust.md, UT1). Do not add RestrictSUIDSGID (bootc fails on
# its runtime auth file), an allow-list CapabilityBoundingSet (breaks the setpriv bootc starts
# its skopeo proxy with) or ProtectSystem=strict (bootc writes the sysroot).
NoNewPrivileges=yes
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
ProtectProc=invisible
LockPersonality=yes
MemoryDenyWriteExecute=yes
UMask=0022
SystemCallFilter=@system-service @mount
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
RestrictNamespaces=~user
CapabilityBoundingSet=~CAP_SYS_MODULE CAP_SYS_BOOT CAP_SYS_RAWIO CAP_NET_ADMIN

[Install]
WantedBy=multi-user.target
````

`forge/specs/athanor-update/SOURCES/usr/lib/systemd/user/athanor-update-notify.service`:

````ini
[Unit]
Description=Athanor update notifications
Documentation=https://github.com/hr-mes/athanor/blob/iso-v0/docs/architecture/doc_update_trust.md
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=/usr/bin/athanor-update-notify
Restart=on-failure
RestartSec=30
NoNewPrivileges=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_UNIX
RestrictNamespaces=yes
SystemCallFilter=@system-service

[Install]
WantedBy=graphical-session.target
````

`forge/specs/athanor-update/SOURCES/usr/lib/systemd/system-preset/80-athanor-update.preset`:

````text
# Numbered below 81: the first preset line that matches a unit wins, and Fedora's
# 90-default.preset would otherwise decide first (see 80-athanor-base.preset).
enable athanor-update-check.timer
enable athanor-update-state.service
enable athanor-update-migrate.service
# The stock timer applies an update and reboots by itself (doc_shell.md, SH11: never).
disable bootc-fetch-apply-updates.timer
````

`forge/specs/athanor-update/SOURCES/usr/lib/systemd/user-preset/80-athanor-update.preset`:

````text
enable athanor-update-notify.service
````

`forge/specs/athanor-update/SOURCES/usr/lib/tmpfiles.d/athanor-update.conf`:

````text
# State of athanor-update (doc_update_trust.md, UT7). /run/athanor, which holds the
# released disk key, is deliberately not used.
d /run/athanor-update 0755 root root -
d /var/lib/athanor-update 0755 root root -
d /var/lib/athanor-update/signatures 0755 root root -
````

`forge/specs/athanor-update/SOURCES/usr/share/dbus-1/system.d/os.athanor.Update1.conf`:

````xml
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="root">
    <allow own="os.athanor.Update1"/>
  </policy>
  <!-- Two methods and introspection, nothing else: no Properties, no Peer. Polkit decides
       who may call (doc_update_trust.md, UT6). -->
  <policy context="default">
    <allow send_destination="os.athanor.Update1" send_interface="os.athanor.Update1" send_member="Apply"/>
    <allow send_destination="os.athanor.Update1" send_interface="os.athanor.Update1" send_member="GoBack"/>
    <allow send_destination="os.athanor.Update1" send_interface="org.freedesktop.DBus.Introspectable" send_member="Introspect"/>
  </policy>
</busconfig>
````

`forge/specs/athanor-update/SOURCES/usr/share/dbus-1/system-services/os.athanor.Update1.service`:

````ini
[D-BUS Service]
Name=os.athanor.Update1
Exec=/bin/false
User=root
SystemdService=athanor-update.service
````

`forge/specs/athanor-update/SOURCES/usr/share/polkit-1/actions/os.athanor.update.policy`:

````xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <vendor>Athanor</vendor>
  <vendor_url>https://github.com/hr-mes/athanor</vendor_url>

  <!-- logind's own defaults for a reboot on this image: the request grants nothing beyond
       the reboot logind already allows the active local user (doc_shell.md, SH11). -->
  <action id="os.athanor.update.apply">
    <description>Restart to install the downloaded system update</description>
    <description xml:lang="it">Riavvia per installare l'aggiornamento di sistema scaricato</description>
    <message>Authentication is required to restart and install the system update</message>
    <message xml:lang="it">È richiesta l'autenticazione per riavviare e installare l'aggiornamento di sistema</message>
    <defaults>
      <allow_any>auth_admin_keep</allow_any>
      <allow_inactive>auth_admin_keep</allow_inactive>
      <allow_active>yes</allow_active>
    </defaults>
  </action>

  <!-- Never kept: every return to the previous version is authenticated on its own. -->
  <action id="os.athanor.update.rollback">
    <description>Go back to the previous system version</description>
    <description xml:lang="it">Torna alla versione di sistema precedente</description>
    <message>Authentication is required to go back to the previous system version</message>
    <message xml:lang="it">È richiesta l'autenticazione per tornare alla versione di sistema precedente</message>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin</allow_active>
    </defaults>
  </action>
</policyconfig>
````

- [ ] **Step 4: Run the tests**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-update/tests -v`
Expected: `Ran 17 tests … OK`. The exposure test is the plan's stated threshold for acceptance 11: 6.0 for the units that reach the network (measured 5.7), 5.5 for the others (measured 5.3).

- [ ] **Step 5: The spec**

`forge/specs/athanor-update/athanor-update.spec`:

````spec
%global debug_package %{nil}
%global crate_dir forge/specs/%{name}/%{name}-%{version}
%global notify_dir forge/specs/%{name}/%{name}-notify-%{version}
%global sources forge/specs/%{name}/SOURCES
Name:           athanor-update
Version:        1.0.0
Release:        1%{?dist}
Summary:        Athanor system image updates and trust state

License:        MIT
URL:            https://github.com/hr-mes/athanor

BuildRequires:  rust cargo gcc systemd-rpm-macros
Requires:       bootc skopeo ostree systemd polkit containers-common

%description
Checks for, verifies, downloads and applies Athanor system image updates, never without
the user's confirmation, and publishes the trust state the greeter, the shield and the
notifier read (docs/architecture/doc_update_trust.md). Ships the root binary
athanor-update with its timer, services, D-Bus and polkit policy, the user notifier
athanor-update-notify, and the templates and renderer of the container signature policy.

%prep
# Built in place from the workspace checkout: nothing to unpack.

%build
%set_build_flags
cargo build --release --locked -p %{name} -p %{name}-notify

%check
cargo test --release --locked -p athanor-trust-state -p %{name} -p %{name}-notify
python3 -B -m unittest discover -s forge/specs/%{name}/tests

%install
install -D -m 0755 target/release/athanor-update %{buildroot}/usr/bin/athanor-update
install -D -m 0755 target/release/athanor-update-notify %{buildroot}/usr/bin/athanor-update-notify
install -D -m 0755 %{sources}/usr/libexec/athanor-update/render-policy %{buildroot}/usr/libexec/athanor-update/render-policy
for template in policy.json.in attachments-policy.json.in athanor.yaml.in; do
    install -D -m 0644 %{sources}/usr/share/athanor/containers/templates/$template %{buildroot}/usr/share/athanor/containers/templates/$template
done
for unit in athanor-update-check.timer athanor-update-check.service athanor-update.service athanor-update-state.service athanor-update-migrate.service; do
    install -D -m 0644 %{sources}/usr/lib/systemd/system/$unit %{buildroot}/usr/lib/systemd/system/$unit
done
install -D -m 0644 %{sources}/usr/lib/systemd/user/athanor-update-notify.service %{buildroot}/usr/lib/systemd/user/athanor-update-notify.service
install -D -m 0644 %{sources}/usr/lib/systemd/system-preset/80-athanor-update.preset %{buildroot}/usr/lib/systemd/system-preset/80-athanor-update.preset
install -D -m 0644 %{sources}/usr/lib/systemd/user-preset/80-athanor-update.preset %{buildroot}/usr/lib/systemd/user-preset/80-athanor-update.preset
install -D -m 0644 %{sources}/usr/lib/tmpfiles.d/athanor-update.conf %{buildroot}/usr/lib/tmpfiles.d/athanor-update.conf
install -D -m 0644 %{sources}/usr/share/dbus-1/system.d/os.athanor.Update1.conf %{buildroot}/usr/share/dbus-1/system.d/os.athanor.Update1.conf
install -D -m 0644 %{sources}/usr/share/dbus-1/system-services/os.athanor.Update1.service %{buildroot}/usr/share/dbus-1/system-services/os.athanor.Update1.service
install -D -m 0644 %{sources}/usr/share/polkit-1/actions/os.athanor.update.policy %{buildroot}/usr/share/polkit-1/actions/os.athanor.update.policy
install -D -m 0644 forge/specs/%{name}/RECOVERY.md %{buildroot}/usr/share/doc/athanor-update/RECOVERY.md

%files
/usr/bin/athanor-update
/usr/bin/athanor-update-notify
/usr/libexec/athanor-update/render-policy
/usr/share/athanor/containers/templates/policy.json.in
/usr/share/athanor/containers/templates/attachments-policy.json.in
/usr/share/athanor/containers/templates/athanor.yaml.in
/usr/lib/systemd/system/athanor-update-check.timer
/usr/lib/systemd/system/athanor-update-check.service
/usr/lib/systemd/system/athanor-update.service
/usr/lib/systemd/system/athanor-update-state.service
/usr/lib/systemd/system/athanor-update-migrate.service
/usr/lib/systemd/user/athanor-update-notify.service
/usr/lib/systemd/system-preset/80-athanor-update.preset
/usr/lib/systemd/user-preset/80-athanor-update.preset
/usr/lib/tmpfiles.d/athanor-update.conf
/usr/share/dbus-1/system.d/os.athanor.Update1.conf
/usr/share/dbus-1/system-services/os.athanor.Update1.service
/usr/share/polkit-1/actions/os.athanor.update.policy
%doc /usr/share/doc/athanor-update/RECOVERY.md

%changelog
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- First release: update check timer, os.athanor.Update1 with Apply and GoBack, one-time
  migration to the signed reference, trust state file, notifier, signature policy templates
````

- [ ] **Step 6: Write the failing tests of the `verify.py` assertions**

`scripts/tests/test_verify_update_trust.py`:

````python
"""Unit tests of the update and trust assertions of scripts/verify.py shipped
(python3 -B -m unittest discover -s scripts/tests -v)."""

import importlib.util
import pathlib
import shutil
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verify", ROOT / "scripts" / "verify.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

TEMPLATES = "forge/specs/athanor-update/SOURCES/usr/share/athanor/containers/templates"


class UpdateTrust(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        shutil.copytree(ROOT / "forge/specs/athanor-update", self.root / "forge/specs/athanor-update",
                        ignore=shutil.ignore_patterns("target", "vectors"))

    def tearDown(self):
        self.tmp.cleanup()

    def edit(self, relative, old, new):
        path = self.root / relative
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new))

    def problems(self):
        return verify.update_trust_problems(self.root)

    def test_the_package_as_committed_has_no_problem(self):
        self.assertEqual(self.problems(), [])
        self.assertEqual(verify.update_trust_problems(), [])

    def test_a_permissive_default_is_reported(self):
        self.edit(f"{TEMPLATES}/policy.json.in", '"default": [{"type": "reject"}]', '"default": [{"type": "insecureAcceptAnything"}]')
        self.assertTrue(any("`default` must be reject" in p for p in self.problems()))

    def test_a_closed_user_transport_is_reported(self):
        self.edit(f"{TEMPLATES}/policy.json.in", '    "oci": {"": [{"type": "insecureAcceptAnything"}]},\n', "")
        self.assertTrue(any("transport oci must stay open" in p for p in self.problems()))

    def test_a_repository_without_match_repository_is_reported(self):
        self.edit(f"{TEMPLATES}/policy.json.in", '"@REGISTRY@/athanor-system-nvidia": [{"type": "sigstoreSigned", "keyPaths": [@KEY_PATHS@], "signedIdentity": {"type": "matchRepository"}}]',
                  '"@REGISTRY@/athanor-system-nvidia": [{"type": "sigstoreSigned", "keyPaths": [@KEY_PATHS@]}]')
        self.assertTrue(any("athanor-system-nvidia must be sigstoreSigned" in p for p in self.problems()))

    def test_a_missing_registries_entry_is_reported(self):
        self.edit(f"{TEMPLATES}/athanor.yaml.in", "  @REGISTRY@/athanor-system-nvidia-legacy:\n    use-sigstore-attachments: true\n", "")
        self.assertTrue(any("athanor.yaml.in" in p for p in self.problems()))

    def test_a_file_the_spec_does_not_list_is_reported(self):
        self.edit("forge/specs/athanor-update/athanor-update.spec", "/usr/share/polkit-1/actions/os.athanor.update.policy\n%doc", "%doc")
        self.assertTrue(any("%files does not list /usr/share/polkit-1/actions/os.athanor.update.policy" in p for p in self.problems()))

    def test_the_wiring_this_package_replaces_must_be_gone(self):
        preset = self.root / "forge/specs/athanor-system-config/SOURCES/usr/lib/systemd/system-preset/80-athanor-system.preset"
        preset.parent.mkdir(parents=True)
        preset.write_text("enable greetd.service\nenable bootc-fetch-apply.timer\n")
        override = self.root / "forge/specs/athanor-base-config/SOURCES/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/override.conf"
        override.parent.mkdir(parents=True)
        override.write_text("[Service]\nExecStart=\nExecStart=/usr/bin/bootc upgrade --stage --quiet\n")
        found = self.problems()
        self.assertTrue(any("bootc-fetch-apply.timer" in p for p in found))
        self.assertTrue(any("--stage" in p for p in found))

    def test_a_literal_registry_owner_is_reported(self):
        self.edit(f"{TEMPLATES}/athanor.yaml.in", "  @REGISTRY@/athanor-system:\n", "  ghcr.io/hr-mes/athanor-system:\n")
        self.assertTrue(any("literal ghcr.io/hr-mes" in p for p in self.problems()))

    def test_a_package_may_build_more_than_one_crate(self):
        built = verify.crates_built_by_specs()
        self.assertEqual(built.get("athanor-update"), "athanor-update")
        self.assertEqual(built.get("athanor-update-notify"), "athanor-update")


if __name__ == "__main__":
    unittest.main()
````

Run: `python3 -B -m unittest discover -s scripts/tests -p 'test_verify_update_trust.py' -v`
Expected: errors, `module 'verify' has no attribute 'update_trust_problems'`.

- [ ] **Step 7: The assertions**

In `scripts/verify.py`, above `@check("shipped", …)`, add:

````python
def crates_built_by_specs(root=None):
    """crate -> spec directory, for every `-p <crate>` a spec under forge/specs builds.
    A package may build more than one crate (one crate per program, doc_shell.md SH4)."""
    built = {}
    for spec in walk((root or ROOT) / "forge" / "specs", ".spec"):
        text = read(spec)
        name = re.search(r"^Name:\s*(\S+)", text, re.M)
        if not name:
            continue
        for line in text.split("\n"):
            if "cargo build" not in line:
                continue
            for crate in re.findall(r"-p\s+(\S+)", line):
                built[crate.replace("%{name}", name.group(1))] = spec.parent.name
    return built


UPDATE_SOURCES = "forge/specs/athanor-update/SOURCES"
UPDATE_SHIPPED = [
    "/usr/bin/athanor-update", "/usr/bin/athanor-update-notify", "/usr/libexec/athanor-update/render-policy",
    "/usr/share/athanor/containers/templates/policy.json.in",
    "/usr/share/athanor/containers/templates/attachments-policy.json.in",
    "/usr/share/athanor/containers/templates/athanor.yaml.in",
    "/usr/lib/systemd/system/athanor-update-check.timer", "/usr/lib/systemd/system/athanor-update-check.service",
    "/usr/lib/systemd/system/athanor-update.service", "/usr/lib/systemd/system/athanor-update-state.service",
    "/usr/lib/systemd/system/athanor-update-migrate.service", "/usr/lib/systemd/user/athanor-update-notify.service",
    "/usr/lib/systemd/system-preset/80-athanor-update.preset", "/usr/lib/systemd/user-preset/80-athanor-update.preset",
    "/usr/lib/tmpfiles.d/athanor-update.conf", "/usr/share/dbus-1/system.d/os.athanor.Update1.conf",
    "/usr/share/dbus-1/system-services/os.athanor.Update1.service", "/usr/share/polkit-1/actions/os.athanor.update.policy",
]
SYSTEM_IMAGES = ["athanor-system", "athanor-system-nvidia", "athanor-system-nvidia-legacy"]


def update_trust_problems(root=None):
    """The update and trust package ships what docs/architecture/doc_update_trust.md says
    (UT1, UT3, UT5, UT6, UT7), and the wiring it replaces is gone."""
    root = root or ROOT
    problems = []
    spec = root / "forge/specs/athanor-update/athanor-update.spec"
    if not spec.exists():
        return [f"{rel(spec)}: missing"]
    files = read(spec).split("%files", 1)[-1]
    for shipped in UPDATE_SHIPPED:
        if not re.search(rf"^{re.escape(shipped)}$", files, re.M):
            problems.append(f"athanor-update.spec: %files does not list {shipped}")
        source = root / UPDATE_SOURCES / shipped.lstrip("/")
        if "/usr/bin/" not in shipped and not source.exists():
            problems.append(f"{UPDATE_SOURCES}{shipped}: missing")

    templates = root / UPDATE_SOURCES / "usr/share/athanor/containers/templates"
    scopes = [f"@REGISTRY@/{name}" for name in SYSTEM_IMAGES]
    try:
        policy = json.loads(read(templates / "policy.json.in").replace("@KEY_PATHS@", '"/k.pub"'))
        attachments = json.loads(read(templates / "attachments-policy.json.in"))
        registries = read(templates / "athanor.yaml.in")
    except (OSError, ValueError) as err:
        return problems + [f"policy templates: {err}"]
    for name, doc in (("policy.json.in", policy), ("attachments-policy.json.in", attachments)):
        if doc.get("default") != [{"type": "reject"}]:
            problems.append(f"{name}: `default` must be reject (bootc refuses insecureAcceptAnything; "
                            f"the attachments policy must open our repositories only)")
    docker = policy.get("transports", {}).get("docker", {})
    if sorted(docker) != sorted([""] + scopes):
        problems.append(f"policy.json.in: docker scopes are {sorted(docker)}, expected the three system images and \"\"")
    for scope in scopes:
        for req in docker.get(scope, [{}]):
            if req.get("type") != "sigstoreSigned" or req.get("signedIdentity") != {"type": "matchRepository"} or not req.get("keyPaths"):
                problems.append(f"policy.json.in: {scope} must be sigstoreSigned with keyPaths and matchRepository")
    for transport in ("docker-archive", "oci", "oci-archive", "dir", "containers-storage", "docker-daemon"):
        if policy.get("transports", {}).get(transport) != {"": [{"type": "insecureAcceptAnything"}]}:
            problems.append(f"policy.json.in: transport {transport} must stay open, or podman users lose it")
    if sorted(attachments.get("transports", {}).get("docker", {})) != sorted(scopes):
        problems.append("attachments-policy.json.in: docker scopes must be exactly the three system images")
    declared = re.findall(r"^  (\S+):$", registries, re.M)
    if declared != scopes or registries.count("use-sigstore-attachments: true") != 3:
        problems.append("athanor.yaml.in: must declare use-sigstore-attachments for exactly the three system images "
                        "(a missing entry makes a signed image read as unsigned, a wider scope collides with default.yaml)")

    preset = root / "forge/specs/athanor-system-config/SOURCES/usr/lib/systemd/system-preset/80-athanor-system.preset"
    if preset.exists() and re.search(r"^enable bootc-fetch-apply\.timer$", read(preset), re.M):
        problems.append(f"{rel(preset)}: enables bootc-fetch-apply.timer, which does not exist")
    override = root / "forge/specs/athanor-base-config/SOURCES/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/override.conf"
    if override.exists():
        problems.append(f"{rel(override)}: calls `bootc upgrade --stage`, a flag bootc 1.16 does not have")
    for literal in walk(root / "forge/specs/athanor-update", ""):
        if literal.is_file() and "target" not in literal.parts and "vectors" not in literal.parts and "ghcr.io/hr-mes" in read(literal):
            problems.append(f"{rel(literal)}: literal ghcr.io/hr-mes; the registry comes from the build's variables")
    return problems
````

In `check_shipped`, add `built = crates_built_by_specs()` on the line before `for m in members:`; after the two lines that compute `has_spec` and `in_dag`, add:

````python
        owner = built.get(name)
        if owner and not has_spec:
            # Built and installed by another package's spec: shipped if that package is.
            has_spec, in_dag = True, owner in dag or owner.replace("athanor-", "") in dag
````

and before `return r` at the end of `check_shipped`:

````python
    for problem in update_trust_problems():
        r.fail(problem)
````

- [ ] **Step 8: Register the package, drop the exemptions, remove the broken wiring**

1. `forge/config/packages.json`: add `"update"` to `custom_packages` (after `"backup"`) and to `custom_tier3` (after `"backup"`).
2. `experimental/EXEMPT`: delete the lines `athanor-update` and `athanor-update-notify`.
3. `forge/specs/athanor-system-config/SOURCES/usr/lib/systemd/system-preset/80-athanor-system.preset`: delete line 8, `enable bootc-fetch-apply.timer`. In `athanor-system-config.spec`, change `41.fc43` to `42.fc43` on the `Release:` line and put this entry first under `%changelog`:

````spec
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-42
- Stop enabling bootc-fetch-apply.timer: no unit of that name exists, so no update ever
  ran by itself. athanor-update ships the timer that does (doc_update_trust.md, UT1).
````

4. `git rm forge/specs/athanor-base-config/SOURCES/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/override.conf`. In `athanor-base-config.spec` delete line 82 (`/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/override.conf`), change `Release:        9%{?dist}` to `10%{?dist}`, and put this entry first under `%changelog`:

````spec
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 43.0.0-10
- Drop the override of bootc-fetch-apply-updates.service: it called `bootc upgrade --stage`,
  a flag bootc 1.16 does not have. The stock timer stays disabled by athanor-update's preset.
````

If `%files` of `athanor-base-config.spec` lists the directory `bootc-fetch-apply-updates.service.d` on its own line, delete that line too (`grep -n 'bootc-fetch' forge/specs/athanor-base-config/athanor-base-config.spec` must print nothing afterwards).

- [ ] **Step 9: Everything green**

````bash
python3 -B -m unittest discover -s scripts/tests -v
python3 -B -m unittest discover -s forge/specs/athanor-update/tests -v
python3 scripts/verify.py shipped polkit specs paths
just check-syntax
````

Expected: both suites `OK`; `shipped` lists no problem for `athanor-update` or `athanor-update-notify`; `polkit` reports `os.athanor.update.apply` and `os.athanor.update.rollback` declared in `os.athanor.update.policy` and installed; `specs` has no finding in `athanor-update.spec`. Compare `python3 scripts/verify.py` with its result on `origin/iso-v0` before this task: no new failure (the baseline has known ones).

- [ ] **Step 10: Build the RPM once**

Run: `bash forge/scripts/build_rolling_local.sh update`
Expected: `athanor-update-1.0.0-1.fc43.x86_64.rpm`; its `%check` ran the Rust and Python tests. `rpm -qlp <the rpm>` lists the 19 paths of `%files`.

- [ ] **Step 11: Commit** (three commits, one per problem)

````bash
git add forge/specs/athanor-update scripts/verify.py scripts/tests/test_verify_update_trust.py forge/config/packages.json experimental/EXEMPT
git commit -m "feat(update): package athanor-update: hardened units, bus and polkit policy, presets, tmpfiles"
git add forge/specs/athanor-system-config
git commit -m "fix(system-config): stop enabling a timer that does not exist"
git add -A forge/specs/athanor-base-config
git commit -m "fix(base-config): drop the bootc override that calls a flag bootc 1.16 does not have"
````

### Task 10: D2: retire the `athanor-secure-boot` daemon, keep the TPM files

**Files:**
- Delete: `forge/specs/athanor-secure-boot/athanor-secure-boot-1.0.0/src/main.rs` (and the then empty directories)
- Delete: `forge/specs/athanor-secure-boot/SOURCES/usr/libexec/athanor-secure-boot-measure.sh`
- Modify: `forge/specs/athanor-secure-boot/athanor-secure-boot.spec`
- Modify: `scripts/verify.py` (`update_trust_problems`), `scripts/tests/test_verify_update_trust.py`
- Untouched, on purpose: `forge/specs/athanor-secure-boot/SOURCES/usr/libexec/athanor-tpm-luks-seal.sh`, `…/usr/libexec/athanor/athanor-tpm-rollback-{check,update}.sh`, the three `athanor-tpm-*.service` files, `…/systemd-pcrphase-sysinit.service.d/10-rollback-check.conf`, `system/Containerfile:137-139,155`, `forge/config/packages.json` (the package stays in tier 0: it still ships the TPM files).

**Interfaces:**
- Consumes: `verify.update_trust_problems` (Task 9).
- Produces: nothing a later task uses.

**What the tree really holds** (the spec's D2 and `.superpowers/update-trust-facts.md` each have half of it). The D-Bus daemon on `org.athanor.SecureBoot` is `athanor-secure-boot-1.0.0/src/main.rs`: it has no `Cargo.toml`, is no workspace member, and no spec builds it, so it never reached an image. What the RPM ships under that name is `athanor-secure-boot.service`, a oneshot the spec writes with a here-document, running `athanor-secure-boot-measure.sh`, which would generate a self-signed key on the machine, assemble and sign a UKI with it, and ends three commands in `|| true`. D2 retires "the binary, its unit and its bus name"; the measure script has no other caller and goes with its unit.

- [ ] **Step 1: Record what the image enables today, before changing anything**

````bash
scripts/devvm/ssh.sh 'rpm -q athanor-secure-boot; systemctl is-enabled athanor-secure-boot.service athanor-tpm-luks-seal.service athanor-tpm-rollback-check.service athanor-tpm-rollback-update.service; systemctl is-active athanor-secure-boot.service athanor-tpm-luks-seal.service athanor-tpm-rollback-check.service athanor-tpm-rollback-update.service; busctl --system list | grep -c org.athanor.SecureBoot'
````

Expected, as measured on the maintainer's desktop on 2026-09-19 (package `athanor-secure-boot-1.0.0-1`): all four units `disabled`; `athanor-tpm-rollback-check.service` `active` (the pcrphase drop-in `Requires=` it), the other three `inactive`; the bus name count `0`. The reason the sealing and rollback-update units are disabled although `system/Containerfile:155` enables them: the same `RUN` then calls `systemctl preset-all`, no preset file names them, and Fedora's `99-default-disable.preset` disables what nothing names. **Write the four lines into the commit message of Step 5. Do not fix the enablement here:** it is outside D2, it changes what a machine does with its TPM, and it is reported to the maintainer in this plan's hand-over. If the dev VM is not available (a CI job is running), run the same command on the desktop without `scripts/devvm/ssh.sh`.

- [ ] **Step 2: Write the failing test**

Append to class `UpdateTrust` in `scripts/tests/test_verify_update_trust.py`:

````python
    def test_the_retired_secure_boot_daemon_must_stay_gone(self):
        self.assertEqual([p for p in verify.update_trust_problems() if "SecureBoot" in p or "secure-boot" in p], [])
        daemon = self.root / "forge/specs/athanor-secure-boot/athanor-secure-boot-1.0.0/src/main.rs"
        daemon.parent.mkdir(parents=True)
        daemon.write_text('#[interface(name = "org.athanor.SecureBoot")]\n')
        spec = self.root / "forge/specs/athanor-secure-boot/athanor-secure-boot.spec"
        spec.write_text("%files\n/usr/lib/systemd/system/athanor-secure-boot.service\n/usr/lib/systemd/system/athanor-tpm-luks-seal.service\n")
        found = self.problems()
        self.assertTrue(any("org.athanor.SecureBoot" in p for p in found))
        self.assertTrue(any("athanor-secure-boot.service" in p for p in found))

    def test_the_tpm_files_the_image_reads_must_stay(self):
        spec = self.root / "forge/specs/athanor-secure-boot/athanor-secure-boot.spec"
        spec.parent.mkdir(parents=True)
        spec.write_text("%files\n")
        self.assertTrue(any("athanor-tpm-luks-seal.sh" in p for p in self.problems()))
````

Run: `python3 -B -m unittest discover -s scripts/tests -p 'test_verify_update_trust.py' -v`
Expected: the two new tests FAIL (the first on its first assertion, because the daemon still exists).

- [ ] **Step 3: The assertion**

In `scripts/verify.py`, at the end of `update_trust_problems`, before `return problems`:

````python
    # D2: the Secure Boot daemon is retired, the TPM files of its package are not.
    secure_boot = root / "forge/specs/athanor-secure-boot"
    for source in walk(secure_boot, ".rs"):
        if "org.athanor.SecureBoot" in read(source):
            problems.append(f"{rel(source)}: serves org.athanor.SecureBoot, a name no bus policy lets it own (retired by D2)")
    if (secure_boot / "athanor-secure-boot.spec").exists():
        text = read(secure_boot / "athanor-secure-boot.spec")
        if "athanor-secure-boot.service" in text:
            problems.append("athanor-secure-boot.spec: still ships athanor-secure-boot.service (retired by D2)")
        for kept in ("athanor-tpm-luks-seal.sh", "athanor-tpm-luks-seal.service", "athanor-tpm-rollback-check.service",
                     "athanor-tpm-rollback-update.service", "10-rollback-check.conf"):
            if kept not in text or not list(walk(secure_boot / "SOURCES", kept)):
                problems.append(f"athanor-secure-boot: {kept} must stay; system/Containerfile and the rollback check use it")
````

- [ ] **Step 4: Retire**

````bash
git rm -r forge/specs/athanor-secure-boot/athanor-secure-boot-1.0.0
git rm forge/specs/athanor-secure-boot/SOURCES/usr/libexec/athanor-secure-boot-measure.sh
````

In `forge/specs/athanor-secure-boot/athanor-secure-boot.spec`: delete the line `install -m 0755 %{_sourcedir}/usr/libexec/athanor-secure-boot-measure.sh …`; delete the whole here-document from `cat <<EOF > %{buildroot}/usr/lib/systemd/system/athanor-secure-boot.service` to its closing `EOF`; delete from `%files` the lines `%{_libexecdir}/athanor-secure-boot-measure.sh` and `/usr/lib/systemd/system/athanor-secure-boot.service`; change `Release:        1%{?dist}` to `3%{?dist}` (the changelog already names `-2`); change `Summary:` to `Athanor OS TPM sealing and rollback protection`; leave `Requires:` as it is (removing a requirement could drop `systemd-ukify` or `sbsigntools` from the image, which is not this task's business); and put first under `%changelog`:

````spec
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-3
- Retire athanor-secure-boot.service and its measure script (doc_update_trust.md, D2): the
  unit was never enabled, and the script generated a signing key on the machine. The four
  Secure Boot readings are published by athanor-update. The TPM sealing, rollback check and
  pcrphase drop-in stay.
````

- [ ] **Step 5: Verify and commit**

````bash
python3 -B -m unittest discover -s scripts/tests -v
python3 scripts/verify.py shipped specs
grep -rn 'org.athanor.SecureBoot\|athanor-secure-boot-measure\|athanor-secure-boot.service' --include='*.rs' --include='*.spec' --include='*.sh' --include='*.yml' --include='Containerfile' system forge .github
grep -n 'athanor-tpm-luks-seal' system/Containerfile
````

Expected: tests `OK`; no new `verify.py` failure; the first `grep` prints nothing; the second still prints lines 137 to 139 and 155.

````bash
git add -A forge/specs/athanor-secure-boot scripts/verify.py scripts/tests/test_verify_update_trust.py
git commit -m "refactor(secure-boot): retire the daemon, its unit and its measure script; keep the TPM files (D2)"
````

### Task 11: UT9: version and `created` labels in `system/build-image.sh`

**Precondition 2 applies** (the file and its tests are PR #49's).

**Files:**
- Modify: `system/build-image.sh`
- Modify: `system/tests/test_build_image.py`
- Modify: `.github/workflows/call-system-image.yml` (the build step passes `--serial`)

**Interfaces:**
- Consumes: `ARG FEDORA_VERSION=43` of `system/Containerfile:27` (the base major).
- Produces: `build-image.sh … [--serial N]`; every image carries `org.opencontainers.image.version=<base major>.<UTC build date>.<serial>` and `org.opencontainers.image.created=<RFC 3339 UTC>`; `SOURCE_DATE_EPOCH` overrides the build time. `bootc status` reports the second label as `status.booted.image.timestamp` (spike U1, section 4), which is what Task 4 orders by.

- [ ] **Step 1: Write the failing tests**

In `system/tests/test_build_image.py`, add to class `BuildImage`, before `test_nvidia_builds_from_the_open_module_digest`:

````python
    def test_every_image_carries_its_own_version_and_build_time(self):
        self.artifacts_file()
        self.env["SOURCE_DATE_EPOCH"] = "1789466400"  # 2026-09-15T10:00:00Z
        r = subprocess.run(["bash", str(BUILD), "--gpu", "none", "--registry", "localhost", "--tag", "check", "--serial", "412"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        args = (self.dir / "podman.args").read_text().splitlines()
        self.assertIn("org.opencontainers.image.version=43.20260915.412", args)
        self.assertIn("org.opencontainers.image.created=2026-09-15T10:00:00Z", args)

    def test_a_local_build_has_serial_zero_and_a_serial_is_a_number(self):
        self.artifacts_file()
        self.env["SOURCE_DATE_EPOCH"] = "1789466400"
        r, args = self.build("none")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("org.opencontainers.image.version=43.20260915.0", args)
        r = subprocess.run(["bash", str(BUILD), "--gpu", "none", "--registry", "localhost", "--tag", "check", "--serial", "v2"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 2)
````

Run: `python3 -B -m unittest discover -s system/tests -p 'test_build_image.py' -v`
Expected: the two new tests FAIL (`--serial` is a usage error, exit 2; no version label).

- [ ] **Step 2: Implement**

Apply to `system/build-image.sh`:

````diff
@@ -3,7 +3,9 @@
 # system/Containerfile, in CI and locally, from the kernel and NVIDIA module digests that
 # system/kernel-artifacts.sh verified (docs/architecture/doc_build_ordering.md, O4): run its
 # resolve (or require-ready) first. Every image carries the digests it was built from as labels.
-# Usage: build-image.sh --gpu none|nvidia|nvidia-legacy --registry REG --tag TAG [--tag TAG]... [--push|--push-only]
+# Usage: build-image.sh --gpu none|nvidia|nvidia-legacy --registry REG --tag TAG [--tag TAG]... [--serial N] [--push|--push-only]
+#   --serial N   last field of the version label (doc_update_trust.md, UT9): the CI run number
+#                in the pipeline, 0 in a local build
 #   --push       build, then push every tag
 #   --push-only  push every tag of an image built earlier, without building
 # SECUREBOOT_SIGNING_KEY in the environment signs the UKI with the project key (release).
@@ -11,13 +13,13 @@
 # check, local rehearsal): such an image carries the label below and is never pushed.
 set -euo pipefail
 
-usage() { echo "usage: ${0##*/} --gpu none|nvidia|nvidia-legacy --registry REG --tag TAG [--tag TAG]... [--push|--push-only]" >&2; exit 2; }
-GPU='' REGISTRY='' MODE=build TAGS=()
+usage() { echo "usage: ${0##*/} --gpu none|nvidia|nvidia-legacy --registry REG --tag TAG [--tag TAG]... [--serial N] [--push|--push-only]" >&2; exit 2; }
+GPU='' REGISTRY='' MODE=build TAGS=() SERIAL=0
 while [[ $# -gt 0 ]]; do
   case $1 in
-    --gpu | --registry | --tag)
+    --gpu | --registry | --tag | --serial)
       [[ $# -ge 2 && -n $2 && $2 != --* ]] || usage
-      case $1 in --gpu) GPU=$2 ;; --registry) REGISTRY=$2 ;; --tag) TAGS+=("$2") ;; esac
+      case $1 in --gpu) GPU=$2 ;; --registry) REGISTRY=$2 ;; --tag) TAGS+=("$2") ;; --serial) SERIAL=$2 ;; esac
       shift 2 ;;
     --push) MODE=push; shift ;;
     --push-only) MODE=push-only; shift ;;
@@ -30,7 +32,7 @@
   nvidia-legacy) NAME=athanor-system-nvidia-legacy ;;
   *) usage ;;
 esac
-[[ -n $REGISTRY && ${#TAGS[@]} -gt 0 ]] || usage
+[[ -n $REGISTRY && ${#TAGS[@]} -gt 0 && $SERIAL =~ ^[0-9]+$ ]] || usage
 
 ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
 IMAGE="$REGISTRY/$NAME"
@@ -63,6 +65,14 @@
 kernel=$(artifact kernel_digest)
 args=(--layers --pull=newer --format docker --build-arg "AZOTH_NVR=$nvr" --build-arg "GPU=$GPU"
   --build-arg "KERNEL_REGISTRY=$registry" --label "io.athanor.azoth.digest=$kernel")
+# Every published image has a version of its own and says when it was built (UT9). Machines
+# order images by `created`, never by the version string; bootc reports it as the
+# deployment's timestamp. SOURCE_DATE_EPOCH, when set, is the build time.
+now=${SOURCE_DATE_EPOCH:-$(date -u +%s)}
+fedora=$(sed -n 's/^ARG FEDORA_VERSION=//p' "$ROOT/system/Containerfile")
+[[ $fedora =~ ^[0-9]+$ ]] || { echo "${0##*/}: system/Containerfile declares no ARG FEDORA_VERSION=<major>" >&2; exit 2; }
+args+=(--label "org.opencontainers.image.version=$fedora.$(date -u -d "@$now" +%Y%m%d).$SERIAL"
+  --label "org.opencontainers.image.created=$(date -u -d "@$now" +%Y-%m-%dT%H:%M:%SZ)")
 case $GPU in
   nvidia) modules=$(artifact nvidia_open_digest); args+=(--build-arg "NVIDIA_OPEN_DIGEST=$modules" --label "io.athanor.azoth-nvidia.digest=$modules") ;;
   nvidia-legacy) modules=$(artifact nvidia_legacy_digest); args+=(--build-arg "NVIDIA_LEGACY_DIGEST=$modules" --label "io.athanor.azoth-nvidia.digest=$modules") ;;
````

- [ ] **Step 3: Run the tests**

Run: `python3 -B -m unittest discover -s system/tests -p 'test_build_image.py' -v && shellcheck system/build-image.sh`
Expected: `Ran 7 tests … OK`.

- [ ] **Step 4: Pass the run number from the pipeline**

In `.github/workflows/call-system-image.yml`, step `🐳 Build OS Images`: add `RUN_NUMBER: ${{ github.run_number }}` under `env:` and append `--serial "${RUN_NUMBER}"` to the `bash system/build-image.sh …` line of the build loop (not to the `--push-only` loop, which builds nothing).

Run: `actionlint .github/workflows/call-system-image.yml && python3 scripts/verify.py workflows`
Expected: no output; green.

- [ ] **Step 5: Commit**

````bash
git add system/build-image.sh system/tests/test_build_image.py .github/workflows/call-system-image.yml
git commit -m "feat(system-image): a version label of its own and a created label on every image (UT9)"
````

### Task 12: `system/sign-images.sh`: key-based signature and client-style verification

**Files:**
- Create: `system/image-digests.sh`, `system/sign-images.sh`, `system/tests/test_sign_images.py`
- The workflow job that calls them lands in Task 16, after the secrets exist: a job that "fails when the key is absent" must not reach `iso-v0` before the key does.

**Interfaces:**
- Consumes: `render-policy` (Task 7), `forge/scripts/retry.sh`, the vectors of Task 2 (a public key for the rendered policy).
- Produces: `image-digests.sh --registry REGISTRY/OWNER --tag TAG --out FILE`, writing lines `REPOSITORY TAG DIGEST`; `sign-images.sh DIGESTS_FILE` with `COSIGN_PRIVATE_KEY`, `COSIGN_PASSWORD` and optional `SIGN_KEYS_DIR` (default `system/keys`) in the environment; exit 2 without the key, 1 when a tag moved or a verification fails.

**How skopeo gets the key.** `--sign-by-sigstore-private-key` and `--sign-passphrase-file` take paths only. The script writes both with the shell's built-in `printf` under `umask 077` into a `mktemp -d` directory on tmpfs (`$XDG_RUNTIME_DIR`, else `/dev/shm`), removes it on exit, and unsets the two variables before the first child starts. The test stub asserts the modes (0600 in 0700), that no `COSIGN_*` variable reaches skopeo, and that neither value appears on a command line or in the output. **Cost of the verification:** `skopeo copy --policy … dir:` pulls each image (about 6 GB each, one at a time, deleted at once); that is the price of verifying "the way a machine will" and the spec asks for exactly it. `--preserve-digests` was not part of spike U1's command; Task 15 runs this script against the throwaway registry, which is where it is measured before the real key exists.

- [ ] **Step 1: Write the failing tests**

`system/tests/test_sign_images.py`:

````python
"""Unit tests of system/image-digests.sh and system/sign-images.sh with a skopeo stub that
keeps a registry in a directory (python3 -B -m unittest discover -s system/tests -v)."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIGN = ROOT / "system" / "sign-images.sh"
DIGESTS = ROOT / "system" / "image-digests.sh"
A_KEY = ROOT / "forge/specs/athanor-update/athanor-update-1.0.0/tests/vectors/made/a.pub"
NAMES = ["athanor-system", "athanor-system-nvidia", "athanor-system-nvidia-legacy"]
REG = "registry.example/owner"
SECRET = "-----BEGIN ENCRYPTED SIGSTORE PRIVATE KEY-----\nnot-a-real-key\n-----END ENCRYPTED SIGSTORE PRIVATE KEY-----\n"

STUB = textwrap.dedent("""\
    #!/usr/bin/env python3
    # A skopeo that knows tags.json (ref -> digest) and records what it signs in signed.json.
    import json, os, pathlib, stat, sys
    state = pathlib.Path(os.environ["STUB_STATE"])
    args = sys.argv[1:]
    with open(state / "calls.log", "a") as log:
        log.write(json.dumps({"args": args, "env": sorted(k for k in os.environ if k.startswith("COSIGN_"))}) + "\\n")
    tags = json.loads((state / "tags.json").read_text())
    signed = json.loads((state / "signed.json").read_text())
    if args[0] == "inspect":
        ref = args[-1].removeprefix("docker://")
        if ref not in tags:
            sys.exit("manifest unknown")
        print(tags[ref])
    elif "--sign-by-sigstore-private-key" in args:
        key = pathlib.Path(args[args.index("--sign-by-sigstore-private-key") + 1])
        phrase = pathlib.Path(args[args.index("--sign-passphrase-file") + 1])
        for secret in (key, phrase):
            mode = stat.S_IMODE(secret.stat().st_mode)
            parent = stat.S_IMODE(secret.parent.stat().st_mode)
            assert mode == 0o600 and parent == 0o700, (secret, oct(mode), oct(parent))
        (state / "key.seen").write_text(key.read_text())
        (state / "passphrase.seen").write_text(phrase.read_text())
        signed.append(tags[args[-1].removeprefix("docker://")])
        (state / "signed.json").write_text(json.dumps(signed))
    elif "--policy" in args:
        policy = json.loads(pathlib.Path(args[args.index("--policy") + 1]).read_text())
        assert policy["default"] == [{"type": "reject"}]
        digest = args[-2].split("@")[1]
        if digest not in signed or os.environ.get("STUB_REFUSE"):
            sys.exit("Source image rejected: A signature was required, but no signature exists")
        pathlib.Path(args[-1].removeprefix("dir:")).mkdir()
    else:
        sys.exit(f"stub skopeo: unsupported {args}")
    """)


class SignImages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        (self.dir / "bin").mkdir()
        stub = self.dir / "bin" / "skopeo"
        stub.write_text(STUB)
        stub.chmod(0o755)
        self.state = self.dir / "state"
        self.state.mkdir()
        self.tags = {f"{REG}/{name}:412": "sha256:" + f"{i + 1}" * 64 for i, name in enumerate(NAMES)}
        (self.state / "tags.json").write_text(json.dumps(self.tags))
        (self.state / "signed.json").write_text("[]")
        (self.dir / "keys").mkdir()
        shutil.copy(A_KEY, self.dir / "keys" / "athanor-image-1.pub")
        (self.dir / "runtime").mkdir(mode=0o700)
        self.env = {"PATH": f"{self.dir / 'bin'}:{os.environ['PATH']}", "STUB_STATE": str(self.state), "RETRY_ATTEMPTS": "1",
                    "SIGN_KEYS_DIR": str(self.dir / "keys"), "XDG_RUNTIME_DIR": str(self.dir / "runtime"),
                    "COSIGN_PRIVATE_KEY": SECRET, "COSIGN_PASSWORD": "correct horse"}
        self.file = self.dir / "artifacts" / "image-digests.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def digests(self):
        return subprocess.run(["bash", str(DIGESTS), "--registry", REG, "--tag", "412", "--out", str(self.file)], capture_output=True, text=True, env=self.env)

    def sign(self, **env):
        return subprocess.run(["bash", str(SIGN), str(self.file)], capture_output=True, text=True, env={**self.env, **env})

    def calls(self):
        return [json.loads(line) for line in (self.state / "calls.log").read_text().splitlines()]

    def test_the_build_job_records_three_digests(self):
        r = self.digests()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.file.read_text().splitlines(), [f"{REG}/{name} 412 {self.tags[f'{REG}/{name}:412']}" for name in NAMES])

    def test_three_images_are_signed_then_pulled_through_the_rendered_policy(self):
        self.digests()
        r = self.sign()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.state / "signed.json").read_text()), list(self.tags.values()))
        verified = [c["args"] for c in self.calls() if "--policy" in c["args"]]
        self.assertEqual([a[-2] for a in verified], [f"docker://{REG}/{name}@{self.tags[f'{REG}/{name}:412']}" for name in NAMES])
        self.assertTrue(all("--registries.d" in a for a in verified))
        self.assertEqual(r.stdout.count("signed and verified with the shipped policy"), 3)

    def test_the_key_reaches_skopeo_as_a_private_file_and_nowhere_else(self):
        self.digests()
        r = self.sign()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.state / "key.seen").read_text(), SECRET)
        self.assertEqual((self.state / "passphrase.seen").read_text(), "correct horse")
        for call in self.calls()[3:]:  # the calls of sign-images.sh
            self.assertEqual(call["env"], [], "COSIGN_* must not be in the environment of skopeo")
            self.assertNotIn("not-a-real-key", " ".join(call["args"]))
            self.assertNotIn("correct horse", " ".join(call["args"]))
        self.assertEqual(list((self.dir / "runtime").iterdir()), [], "the private directory is removed on exit")
        self.assertNotIn("not-a-real-key", r.stdout + r.stderr)

    def test_without_the_key_the_job_fails_before_touching_the_registry(self):
        self.digests()
        before = len(self.calls())
        r = self.sign(COSIGN_PRIVATE_KEY="")
        self.assertEqual(r.returncode, 2)
        self.assertIn("COSIGN_PRIVATE_KEY is not available", r.stderr)
        self.assertEqual(len(self.calls()), before)

    def test_a_tag_that_moved_since_the_build_is_not_signed(self):
        self.digests()
        self.tags[f"{REG}/athanor-system:412"] = "sha256:" + "9" * 64
        (self.state / "tags.json").write_text(json.dumps(self.tags))
        r = self.sign()
        self.assertEqual(r.returncode, 1)
        self.assertIn("the build job recorded", r.stderr)
        self.assertEqual(json.loads((self.state / "signed.json").read_text()), [])

    def test_a_signature_a_machine_would_not_accept_fails_the_job(self):
        self.digests()
        r = self.sign(STUB_REFUSE="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("A signature was required", r.stderr)


if __name__ == "__main__":
    unittest.main()
````

Run: `python3 -B -m unittest discover -s system/tests -p 'test_sign_images.py' -v`
Expected: 6 failures, `No such file or directory`.

- [ ] **Step 2: The two scripts**

`system/image-digests.sh`:

````bash
#!/usr/bin/env bash
# Writes the digests file the signing job reads (docs/architecture/doc_update_trust.md, UT2):
# one line per system image, "REPOSITORY TAG DIGEST", for the tag this run pushed. The build
# job runs it after the push; the file travels to the signing job, which holds the key and
# builds nothing.
# Usage: image-digests.sh --registry REGISTRY/OWNER --tag TAG --out FILE
set -euo pipefail

usage() { echo "usage: ${0##*/} --registry REGISTRY/OWNER --tag TAG --out FILE" >&2; exit 2; }
registry='' tag='' out=''
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case $1 in --registry) registry=$2 ;; --tag) tag=$2 ;; --out) out=$2 ;; *) usage ;; esac
  shift 2
done
[[ -n $registry && -n $tag && -n $out ]] || usage

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$(dirname "$out")"
: > "$out.tmp"
for name in athanor-system athanor-system-nvidia athanor-system-nvidia-legacy; do
  digest=$(bash "$root/forge/scripts/retry.sh" skopeo inspect --format '{{.Digest}}' "docker://$registry/$name:$tag")
  [[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "${0##*/}: $registry/$name:$tag has no digest: '$digest'" >&2; exit 1; }
  echo "$registry/$name $tag $digest" >> "$out.tmp"
done
mv "$out.tmp" "$out"
cat "$out"
````

`system/sign-images.sh`:

````bash
#!/usr/bin/env bash
# Key-based signature of the published system images, and the verification a machine will
# make (docs/architecture/doc_update_trust.md, UT2). Runs in a job that holds the key and
# does nothing else: it reads the digests file the build job wrote, signs, verifies, ends.
#
# The signature must be the classic cosign attachment at <repo>:sha256-<hex>.sig, the only
# format containers/image reads, so it is made with `skopeo copy
# --sign-by-sigstore-private-key` and never with cosign 3, which writes a bundle every
# Athanor machine treats as no signature. Each image is then pulled through the policy
# rendered from this checkout (`skopeo copy --policy`), not checked with `cosign verify`:
# that also catches a wrong registries.d entry before a machine meets it.
#
# The key and its passphrase arrive in COSIGN_PRIVATE_KEY and COSIGN_PASSWORD. skopeo takes
# both as files only, so they are written by the shell's own printf, under umask 077, into a
# private directory on tmpfs that is removed on exit, and the variables are unset before the
# first child process starts: neither value is ever on a command line, in a world-readable
# file, or in the environment of skopeo.
#
# Usage: sign-images.sh DIGESTS_FILE      (lines: "REPOSITORY TAG DIGEST", image-digests.sh)
# Environment: COSIGN_PRIVATE_KEY, COSIGN_PASSWORD; SIGN_KEYS_DIR (default system/keys);
#              the registry login is the caller's business.
set -euo pipefail

[[ $# -eq 1 && -s $1 ]] || { echo "usage: ${0##*/} DIGESTS_FILE" >&2; exit 2; }
digests=$1
[[ -n ${COSIGN_PRIVATE_KEY:-} ]] || { echo "${0##*/}: COSIGN_PRIVATE_KEY is not available to this job: check the signing environment" >&2; exit 2; }
[[ -n ${COSIGN_PASSWORD+set} ]] || { echo "${0##*/}: COSIGN_PASSWORD is not available to this job: check the signing environment" >&2; exit 2; }

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
retry="$root/forge/scripts/retry.sh"
keys_dir=${SIGN_KEYS_DIR:-$root/system/keys}

umask 077
work=$(mktemp -d -p "${XDG_RUNTIME_DIR:-/dev/shm}" sign-images.XXXXXX)
trap 'rm -rf "$work"' EXIT
printf '%s' "$COSIGN_PRIVATE_KEY" > "$work/key"
printf '%s' "$COSIGN_PASSWORD" > "$work/passphrase"
unset COSIGN_PRIVATE_KEY COSIGN_PASSWORD

registry=''
while read -r repository tag digest; do
  [[ $digest =~ ^sha256:[0-9a-f]{64}$ && -n $tag ]] || { echo "${0##*/}: malformed line in $digests: '$repository $tag $digest'" >&2; exit 2; }
  [[ -z $registry || $registry == "${repository%/*}" ]] || { echo "${0##*/}: $digests names two registries" >&2; exit 2; }
  registry=${repository%/*}
done < "$digests"
bash "$root/forge/specs/athanor-update/SOURCES/usr/libexec/athanor-update/render-policy" \
  --registry "$registry" --keys-dir "$keys_dir" --out "$work/policy"

while read -r repository tag digest; do
  # The signature covers a digest; the tag is only how skopeo addresses the copy. A tag that
  # no longer names the digest the build job recorded is not signed.
  now=$(bash "$retry" skopeo inspect --format '{{.Digest}}' "docker://$repository:$tag")
  [[ $now == "$digest" ]] || { echo "${0##*/}: $repository:$tag is $now, the build job recorded $digest" >&2; exit 1; }
  bash "$retry" skopeo copy --preserve-digests --sign-by-sigstore-private-key "$work/key" --sign-passphrase-file "$work/passphrase" \
    "docker://$repository:$tag" "docker://$repository:$tag"
done < "$digests"

n=0
while read -r repository _ digest; do
  n=$((n + 1))
  bash "$retry" skopeo --registries.d "$work/policy/registries.d" copy --policy "$work/policy/policy.json" \
    "docker://$repository@$digest" "dir:$work/verified-$n"
  rm -rf "$work/verified-$n"
  echo "signed and verified with the shipped policy: $repository@$digest"
done < "$digests"
````

- [ ] **Step 3: Run the tests**

Run: `python3 -B -m unittest discover -s system/tests -p 'test_sign_images.py' -v && shellcheck system/sign-images.sh system/image-digests.sh`
Expected: `Ran 6 tests … OK`; shellcheck silent.

- [ ] **Step 4: Commit**

````bash
git add system/image-digests.sh system/sign-images.sh system/tests/test_sign_images.py
git commit -m "feat(system-image): key-based signature with skopeo and verification through the shipped policy"
````

### Task 13: D1: `system/promote.sh` and the manual workflow

**Files:**
- Create: `system/promote.sh`, `system/tests/test_promote.py`, `.github/workflows/promote-stable.yml`
- Modify: `system/tests/fake_registry.py` (`skopeo copy`)

**Interfaces:**
- Consumes: class `Tool` of `system/tests/test_kernel_artifacts.py` and `fake_registry.py` (PR #49); the labels of Task 11.
- Produces: `promote.sh RUN_ID` with `REGISTRY` (default `ghcr.io/<GITHUB_REPOSITORY_OWNER>`, lower case); tags `stable`, `stable-previous`, `stable-<YYYYMMDD>` on the three images, which Task 14 keeps.

Two refusals protect the channel, because the client cannot: a run whose only signature is a cosign 3 bundle (every machine would read `refused`), and a run not newer than the current `stable` (every machine would read `older-than-booted` and the channel would stand still). All three images are checked before any tag moves.

- [ ] **Step 1: Teach the fake registry `skopeo copy`**

````diff
@@ -40,6 +40,9 @@
 
 
 def skopeo(args, fx):
+    if args[0] == "copy":
+        # Recorded in FAKE_LOG by main(); the fixture is read-only, so nothing moves.
+        return fail("fake skopeo: copy failed", 1) if args[-1].removeprefix("docker://") in fx.get("errors", []) else 0
     ref = args[-1].removeprefix("docker://")
     if ref in fx.get("errors", []):
         return fail(f'time="2026-09-17T00:00:00Z" level=fatal msg="Error parsing image name \\"docker://{ref}\\": pinging container registry: dial tcp: i/o timeout"')
````

- [ ] **Step 2: Write the failing tests**

`system/tests/test_promote.py`:

````python
"""Unit tests of system/promote.sh against an offline registry
(python3 -B -m unittest discover -s system/tests -v)."""

import json
import pathlib
import subprocess
import unittest

from test_kernel_artifacts import Tool

PROMOTE = pathlib.Path(__file__).resolve().parents[2] / "system" / "promote.sh"
REG = "registry.example/owner"
NAMES = ["athanor-system", "athanor-system-nvidia", "athanor-system-nvidia-legacy"]
SIGNATURE = {"layers": [{"mediaType": "application/vnd.dev.cosign.simplesigning.v1+json"}]}
BUNDLE = {"manifests": [{"artifactType": "application/vnd.dev.sigstore.bundle.v0.3+json"}]}


def digest(n):
    return "sha256:" + f"{n:x}" * 64


class Promote(Tool):
    def published(self, run_created="2026-09-15T10:00:00Z", stable_created="2026-09-10T10:00:00Z", signature=SIGNATURE):
        fx = {"tags": {}, "configs": {}, "raw": {}}
        for i, name in enumerate(NAMES):
            new, old = digest(i + 1), digest(i + 4)
            fx["tags"][f"{REG}/{name}:412"] = new
            fx["configs"][f"{REG}/{name}@{new}"] = {"org.opencontainers.image.created": run_created}
            fx["raw"][f"{REG}/{name}:sha256-{new[7:]}.sig"] = signature
            if stable_created:
                fx["tags"][f"{REG}/{name}:stable"] = old
                fx["configs"][f"{REG}/{name}@{old}"] = {"org.opencontainers.image.created": stable_created}
        self.registry(fx)

    def promote(self, run="412"):
        r = subprocess.run(["bash", str(PROMOTE), run], capture_output=True, text=True, env={**self.env, "REGISTRY": REG})
        log = self.dir / "calls.log"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return r, [(c[-2].removeprefix("docker://"), c[-1].removeprefix("docker://")) for c in calls if c[:2] == ["skopeo", "copy"]]

    def test_stable_moves_forward_and_the_previous_stable_keeps_a_tag(self):
        self.published()
        r, copies = self.promote()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(copies), 9)
        for name in NAMES:
            self.assertIn((f"{REG}/{name}:stable", f"{REG}/{name}:stable-previous"), copies)
            self.assertIn((f"{REG}/{name}:412", f"{REG}/{name}:stable"), copies)
            self.assertLess(copies.index((f"{REG}/{name}:stable", f"{REG}/{name}:stable-previous")), copies.index((f"{REG}/{name}:412", f"{REG}/{name}:stable")))
        self.assertTrue(any(dest.rsplit(":", 1)[1].startswith("stable-2") for _, dest in copies))

    def test_the_first_promotion_has_no_previous_stable(self):
        self.published(stable_created=None)
        r, copies = self.promote()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(copies), 6)
        self.assertFalse(any(dest.endswith(":stable-previous") for _, dest in copies))

    def test_an_older_or_equal_build_is_refused_and_nothing_moves(self):
        for run_created in ("2026-09-01T10:00:00Z", "2026-09-10T10:00:00Z"):
            self.published(run_created=run_created)
            (self.dir / "calls.log").unlink(missing_ok=True)
            r, copies = self.promote()
            self.assertEqual(r.returncode, 1)
            self.assertIn("not newer than the current stable", r.stderr)
            self.assertEqual(copies, [])

    def test_a_run_signed_only_with_a_cosign_3_bundle_is_refused(self):
        self.published(signature=BUNDLE)
        r, copies = self.promote()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no signature a machine can verify", r.stderr)
        self.assertEqual(copies, [])

    def test_a_run_id_is_a_number(self):
        self.published()
        r, _ = self.promote(run="latest")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
````

Run: `python3 -B -m unittest discover -s system/tests -p 'test_promote.py' -v`
Expected: 5 failures, `No such file or directory`.

- [ ] **Step 3: The script**

`system/promote.sh`:

````bash
#!/usr/bin/env bash
# Points the `stable` tag of the three system images at the digests of one pipeline run
# (docs/architecture/doc_update_trust.md, D1). Users follow :stable; :latest stays for
# testing. The signature is by digest, so it carries: nothing is signed here and no key is
# needed. Nothing moves unless all three images pass every check:
#   - the run's image exists and carries the classic cosign attachment machines verify;
#   - its build time is newer than the current stable's: a machine never follows a tag
#     backwards (UT5), so an older promotion would only strand the channel.
# Besides `stable`, each image gets `stable-previous` (the digest stable pointed at) and
# `stable-<YYYYMMDD>`; forge/scripts/clean_ghcr.sh keeps all three (UT10).
# Usage: promote.sh RUN_ID
# Environment: REGISTRY (default ghcr.io/<GITHUB_REPOSITORY_OWNER>); skopeo logged in.
set -euo pipefail
shopt -s inherit_errexit

[[ $# -eq 1 && $1 =~ ^[0-9]+$ ]] || { echo "usage: ${0##*/} RUN_ID" >&2; exit 2; }
run=$1
owner=${GITHUB_REPOSITORY_OWNER:-}
REGISTRY=${REGISTRY:-${owner:+ghcr.io/${owner,,}}}
[[ -n $REGISTRY ]] || { echo "${0##*/}: set REGISTRY or GITHUB_REPOSITORY_OWNER" >&2; exit 2; }
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
retry="$root/forge/scripts/retry.sh"
SIMPLE_SIGNING=application/vnd.dev.cosign.simplesigning.v1+json
err=$(mktemp)
trap 'rm -f "$err"' EXIT

created() { # created REPOSITORY DIGEST -> seconds since the epoch
  local label
  label=$(skopeo inspect --config "docker://$1@$2" | jq -r '.config.Labels["org.opencontainers.image.created"] // empty')
  [[ -n $label ]] || { echo "${0##*/}: $1@$2 has no org.opencontainers.image.created label" >&2; return 1; }
  date -u -d "$label" +%s
}

declare -A has_stable=()
for name in athanor-system athanor-system-nvidia athanor-system-nvidia-legacy; do
  repository=$REGISTRY/$name
  digest=$(skopeo inspect --format '{{.Digest}}' "docker://$repository:$run")
  skopeo inspect --raw "docker://$repository:sha256-${digest#sha256:}.sig" \
    | jq -e --arg type "$SIMPLE_SIGNING" '.layers | any(.mediaType == $type)' > /dev/null \
    || { echo "${0##*/}: $repository@$digest has no signature a machine can verify (sha256-<hex>.sig)" >&2; exit 1; }
  if stable=$(skopeo inspect --format '{{.Digest}}' "docker://$repository:stable" 2> "$err"); then
    has_stable[$name]=1
    if [[ $stable != "$digest" && $(created "$repository" "$digest") -le $(created "$repository" "$stable") ]]; then
      echo "${0##*/}: $repository:$run is not newer than the current stable: machines would not follow it" >&2
      exit 1
    fi
  elif ! grep -q 'manifest unknown' "$err"; then
    # Anything but "there is no stable tag yet" is a real failure.
    cat "$err" >&2
    exit 1
  fi
done

day=$(date -u +%Y%m%d)
for name in athanor-system athanor-system-nvidia athanor-system-nvidia-legacy; do
  repository=$REGISTRY/$name
  if [[ -n ${has_stable[$name]:-} ]]; then
    bash "$retry" skopeo copy --preserve-digests "docker://$repository:stable" "docker://$repository:stable-previous"
  fi
  bash "$retry" skopeo copy --preserve-digests "docker://$repository:$run" "docker://$repository:stable-$day"
  bash "$retry" skopeo copy --preserve-digests "docker://$repository:$run" "docker://$repository:stable"
  echo "stable -> $repository:$run"
done
````

- [ ] **Step 4: Run the tests**

Run: `python3 -B -m unittest discover -s system/tests -v && shellcheck system/promote.sh`
Expected: every test of `system/tests` passes, `test_promote` with 5.

- [ ] **Step 5: The manual workflow**

`.github/workflows/promote-stable.yml`:

````yaml
name: Promote a system image run to stable

# Manual, by decision D1 of docs/architecture/doc_update_trust.md: users follow :stable,
# :latest stays for testing. The logic is system/promote.sh; no signing key is involved.

on:
  workflow_dispatch:
    inputs:
      run_id:
        description: "Run id of the Orchestrator run whose three system images become stable"
        required: true
        type: string

concurrency:
  group: promote-stable
  cancel-in-progress: false

permissions:
  contents: read
  packages: write

jobs:
  lint:
    uses: ./.github/workflows/call-lint.yml

  promote:
    name: Point stable at the run
    needs: [lint]
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - name: Log in to the registry
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_ACTOR: ${{ github.actor }}
          REGISTRY_HOST: ${{ vars.REGISTRY_HOST || 'ghcr.io' }}
        run: echo "${GITHUB_TOKEN}" | skopeo login "${REGISTRY_HOST}" -u "${GITHUB_ACTOR}" --password-stdin
      - name: Promote (system/promote.sh)
        env:
          RUN_ID: ${{ inputs.run_id }}
          REGISTRY: ${{ vars.REGISTRY_HOST || 'ghcr.io' }}/${{ github.repository_owner }}
        run: bash system/promote.sh "${RUN_ID}" | tee -a "${GITHUB_STEP_SUMMARY}"
````

`github.repository_owner` is lower case for this project; `promote.sh` lower-cases only its own default. Run: `actionlint .github/workflows/promote-stable.yml && python3 scripts/verify.py workflows`
Expected: no output; green. (`call-lint.yml` is a reusable workflow with no required input: check its `on: workflow_call` block; if it requires inputs the other callers pass, pass the same.)

- [ ] **Step 6: Commit**

````bash
git add system/promote.sh system/tests/test_promote.py system/tests/fake_registry.py .github/workflows/promote-stable.yml
git commit -m "feat(system-image): promote a signed run to the stable channel by hand (D1)"
````

### Task 14: UT10: retention in `forge/scripts/clean_ghcr.sh`

**Files:**
- Modify: `forge/scripts/clean_ghcr.sh` (PR #49's version), `system/tests/test_clean_ghcr.py`, `.github/workflows/forge-ghcr-cleanup.yml` (skopeo login)

**Interfaces:**
- Consumes: the tags of Task 13; `fake_registry.py` (`gh api`, `skopeo inspect --raw`).
- Produces: environment `RETENTION_DAYS` (default 90), `REGISTRY_HOST` (default `ghcr.io`), `CLEAN_GHCR_NOW` (tests).

The reachability model is `forge/specs/azoth/retention.sh`'s: a kept image keeps every `sha256-<hex>*` tag of its digest and the untagged members of the cosign 3 index at `sha256-<hex>`, read from the registry because the packages API does not know them. "Was tagged `latest` in the last 90 days" cannot be asked of ghcr, which keeps no tag history; every pushed image was `latest` when pushed, so "pushed in the last 90 days" is the same set. "Was tagged `stable`" is answered by the dated tag `promote.sh` leaves. PR #49 already removed the `|| true` the review's L1 names.

- [ ] **Step 1: Write the failing tests**

Apply to `system/tests/test_clean_ghcr.py` (the existing test moves to a package that keeps the old rule):

````diff
@@ -17,20 +17,67 @@
 
 class Janitor(Tool):
     def test_kernel_packages_are_never_touched(self):
-        self.registry({"user_packages": ["azoth", "azoth-nvidia", "athanor-system"], "packages": {
+        self.registry({"user_packages": ["azoth", "azoth-nvidia", "athanor-forge-tier0-repo"], "packages": {
             "azoth": [version(1, [], 1)],
             "azoth-nvidia": [version(2, [], 1)],
-            "athanor-system": [version(3, ["101"], 1), version(4, ["102"], 2), version(5, ["103"], 3),
+            "athanor-forge-tier0-repo": [version(3, ["101"], 1), version(4, ["102"], 2), version(5, ["103"], 3),
                                version(6, ["latest"], 0), version(7, [], 4)],
         }})
         r = subprocess.run(["bash", str(JANITOR), "hr-mes"], capture_output=True, text=True, env=self.env)
         self.assertEqual(r.returncode, 0, r.stderr)
         calls = [json.loads(line) for line in (self.dir / "calls.log").read_text().splitlines()]
         deleted = sorted(c[-1] for c in calls if "DELETE" in c)
-        self.assertEqual(deleted, ["/users/hr-mes/packages/container/athanor-system/versions/3",
-                                   "/users/hr-mes/packages/container/athanor-system/versions/7"])
+        self.assertEqual(deleted, ["/users/hr-mes/packages/container/athanor-forge-tier0-repo/versions/3",
+                                   "/users/hr-mes/packages/container/athanor-forge-tier0-repo/versions/7"])
         self.assertFalse(any("azoth" in " ".join(c) and "versions" in " ".join(c) for c in calls))
 
 
+NOW = "1789776000"  # 2026-09-19T00:00:00Z
+OLD, RECENT = "2026-05-01", "2026-08-01"  # outside and inside the 90 days before NOW
+
+
+def image(id_, tags, day):
+    return {"id": id_, "name": f"sha256:{id_:064x}", "created_at": f"{day}T00:00:00Z", "metadata": {"container": {"tags": tags}}}
+
+
+def referrers(id_, of, day=OLD):
+    """What signs image OF: the .sig tag of containers/image, the cosign 3 index and its untagged member."""
+    hex_ = f"{of:064x}"
+    return [image(id_, [f"sha256-{hex_}.sig"], day), image(id_ + 1, [f"sha256-{hex_}"], day), image(id_ + 2, [], day)]
+
+
+class SystemImages(Tool):
+    def prune(self, versions, raw=None):
+        self.registry({"user_packages": ["athanor-system"], "packages": {"athanor-system": versions}, "raw": raw or {}})
+        r = subprocess.run(["bash", str(JANITOR), "hr-mes"], capture_output=True, text=True, env={**self.env, "CLEAN_GHCR_NOW": NOW})
+        self.assertEqual(r.returncode, 0, r.stderr)
+        calls = [json.loads(line) for line in (self.dir / "calls.log").read_text().splitlines()]
+        return sorted(int(c[-1].rsplit("/", 1)[1]) for c in calls if "DELETE" in c)
+
+    def index(self, of, member):
+        return {f"ghcr.io/hr-mes/athanor-system:sha256-{of:064x}": {"manifests": [{"digest": f"sha256:{member:064x}"}]}}
+
+    def test_stable_latest_and_the_previous_stable_stay_however_old_with_everything_that_signs_them(self):
+        versions = [image(1, ["100", "stable", "stable-20260101"], OLD), *referrers(10, 1),
+                    image(2, ["90", "stable-previous"], OLD), *referrers(20, 2),
+                    image(3, ["110", "latest"], OLD), *referrers(30, 3)]
+        raw = {**self.index(1, 12), **self.index(2, 22), **self.index(3, 32)}
+        self.assertEqual(self.prune(versions, raw), [])
+
+    def test_an_old_image_nothing_names_goes_with_its_signatures(self):
+        versions = [image(1, ["100", "stable"], OLD), *referrers(10, 1), image(4, ["80"], OLD), *referrers(40, 4)]
+        self.assertEqual(self.prune(versions, {**self.index(1, 12), **self.index(4, 42)}), [4, 40, 41, 42])
+
+    def test_ninety_days_of_pushes_and_of_promotions_stay(self):
+        versions = [image(5, ["105"], RECENT), *referrers(50, 5, RECENT),
+                    image(6, ["70", "stable-20260801"], OLD), *referrers(60, 6),
+                    image(7, ["60", "stable-20260501"], OLD)]
+        self.assertEqual(self.prune(versions, {**self.index(5, 52), **self.index(6, 62)}), [7])
+
+    def test_an_untagged_manifest_no_kept_index_lists_is_deleted(self):
+        versions = [image(1, ["100", "stable"], OLD), *referrers(10, 1), image(99, [], RECENT)]
+        self.assertEqual(self.prune(versions, self.index(1, 12)), [99])
+
+
 if __name__ == "__main__":
     unittest.main()
````

Run: `python3 -B -m unittest discover -s system/tests -p 'test_clean_ghcr.py' -v`
Expected: the four `SystemImages` tests FAIL (signatures of kept images deleted, the 90 days ignored).

- [ ] **Step 2: The script**

`forge/scripts/clean_ghcr.sh`, complete:

````bash
#!/usr/bin/env bash
# Janitor of the container packages on ghcr. Three kinds of package:
#   - the kernel packages (azoth*) are excluded: their only pruner is
#     forge/specs/azoth/retention.sh (docs/architecture/doc_build_ordering.md, O6);
#   - the system images (athanor-system*) keep what a machine can still use
#     (docs/architecture/doc_update_trust.md, UT10): every image tagged latest, stable or
#     stable-previous, every image pushed in the last RETENTION_DAYS (each was `latest` when
#     pushed), every image promoted in that time (tag stable-<YYYYMMDD>, system/promote.sh),
#     and whatever signs a kept image: the tags sha256-<hex>, sha256-<hex>.sig, .att and
#     .sbom, and the untagged members of the cosign 3 index at sha256-<hex>. cosign 3 and
#     containers/image write the signatures of one digest to two different tags, and a
#     signature is never deleted while its digest is kept. Ninety days is an interim number;
#   - every other package keeps its two newest tagged versions and every version tagged
#     latest, main or stable; the other tagged versions and the untagged ones are deleted.
# Usage: clean_ghcr.sh OWNER. Needs gh with read:packages and delete:packages, and for the
# system images skopeo logged in to the registry.
set -euo pipefail
shopt -s inherit_errexit

OWNER=${1:?usage: clean_ghcr.sh OWNER}
REGISTRY_HOST=${REGISTRY_HOST:-ghcr.io}
RETENTION_DAYS=${RETENTION_DAYS:-90}
NOW=${CLEAN_GHCR_NOW:-$(date -u +%s)}

delete() { # delete PACKAGE API: version ids on stdin
  local id
  while IFS= read -r id; do
    [[ -n $id ]] || continue
    echo "$1: deleting version ${id}"
    gh api --method DELETE "$2/${id}" > /dev/null
  done
}

prune_system_image() { # prune_system_image PACKAGE API VERSIONS
  local package=$1 api=$2 versions=$3 cutoff cutoff_day digest hex member
  local -A live=()
  cutoff=$((NOW - RETENTION_DAYS * 86400))
  cutoff_day=$(date -u -d "@$cutoff" +%Y%m%d)
  while IFS= read -r digest; do
    [[ -n $digest ]] || continue
    live[$digest]=1
    hex=${digest#sha256:}
    while IFS= read -r member; do [[ -z $member ]] || live[$member]=1; done < <(jq -r --arg hex "$hex" '
      .[] | select(.metadata.container.tags | any(startswith("sha256-" + $hex))) | .name' <<< "$versions")
    if jq -e --arg tag "sha256-${hex}" 'any(.[]; .metadata.container.tags | index($tag))' <<< "$versions" > /dev/null; then
      while IFS= read -r member; do [[ -z $member ]] || live[$member]=1; done < <(
        skopeo inspect --raw "docker://${REGISTRY_HOST}/${OWNER}/${package}:sha256-${hex}" | jq -r '.manifests[]?.digest')
    fi
  done < <(jq -r --argjson cutoff "$cutoff" --arg day "$cutoff_day" '
    .[]
    | select(.metadata.container.tags | any(startswith("sha256-") | not))
    | select((.metadata.container.tags | any(test("^(latest|stable|stable-previous)$")))
          or ((.created_at | fromdateiso8601) >= $cutoff)
          or (.metadata.container.tags | any(capture("^stable-(?<day>[0-9]{8})$") | .day >= $day)))
    | .name' <<< "$versions")
  echo "${package}: ${#live[@]} manifests reachable from a kept image"
  while read -r id digest; do
    [[ -n ${live[$digest]:-} ]] || echo "$id"
  done < <(jq -r '.[] | "\(.id) \(.name)"' <<< "$versions") | delete "$package" "$api"
}

packages=$(gh api --paginate "/users/${OWNER}/packages?package_type=container" | jq -rs 'add // [] | .[].name')
while IFS= read -r package; do
  [[ -n $package ]] || continue
  case $package in
    azoth*) echo "${package}: pruned by forge/specs/azoth/retention.sh, skipped"; continue ;;
  esac
  encoded=$(jq -rn --arg name "$package" '$name | @uri')
  api="/users/${OWNER}/packages/container/${encoded}/versions"
  versions=$(gh api --paginate "${api}?per_page=100" | jq -s 'add // []')
  case $package in
    athanor-system | athanor-system-nvidia | athanor-system-nvidia-legacy)
      prune_system_image "$package" "$api" "$versions"
      continue ;;
  esac
  jq -r '
    ([.[] | select(.metadata.container.tags | length > 0)] | sort_by(.created_at) | reverse | .[:2] | map(.id)) as $newest
    | .[]
    | select((.id as $id | $newest | index($id)) | not)
    | select(.metadata.container.tags | any(test("^(latest|main|stable)$")) | not)
    | .id' <<< "$versions" | delete "$package" "$api"
done <<< "$packages"
````

- [ ] **Step 3: Run the tests**

Run: `python3 -B -m unittest discover -s system/tests -p 'test_clean_ghcr.py' -v && shellcheck forge/scripts/clean_ghcr.sh`
Expected: `Ran 5 tests … OK`.

- [ ] **Step 4: Give the janitor a registry login**

In `.github/workflows/forge-ghcr-cleanup.yml`, before the step `Prune the container packages (clean_ghcr.sh)`, add:

````yaml
      - name: Log in to the registry (the janitor reads the signature indexes)
        env:
          GH_TOKEN: ${{ secrets.FORGE_PAT }}
          GITHUB_ACTOR: ${{ github.actor }}
        run: echo "${GH_TOKEN}" | skopeo login ghcr.io -u "${GITHUB_ACTOR}" --password-stdin
````

Run: `actionlint .github/workflows/forge-ghcr-cleanup.yml && python3 scripts/verify.py workflows`
Expected: no output; green. Then a dry look at what the first real run would delete, without deleting: `CLEAN=$(mktemp -d) && printf '#!/bin/sh\ncase "$*" in *DELETE*) echo "WOULD $*" >&2;; *) exec /usr/bin/gh "$@";; esac\n' > $CLEAN/gh && chmod +x $CLEAN/gh && PATH=$CLEAN:$PATH bash forge/scripts/clean_ghcr.sh hr-mes 2>&1 | grep -c WOULD` — report the number to the maintainer before the workflow's next scheduled run.

- [ ] **Step 5: Commit**

````bash
git add forge/scripts/clean_ghcr.sh system/tests/test_clean_ghcr.py .github/workflows/forge-ghcr-cleanup.yml
git commit -m "fix(ghcr-cleanup): keep every system image a machine can still use, and what signs it (UT10)"
````

### Task 15: Dev VM acceptance harness (items 1 to 15), with a throwaway registry and key

**Files:**
- Create: `scripts/devvm/acceptance/lib.sh`, `scripts/devvm/acceptance/Containerfile`, `scripts/devvm/acceptance/images.sh`, `scripts/devvm/acceptance/run.sh`, `scripts/devvm/acceptance/README.md`

**Interfaces:**
- Consumes: the RPM of Task 9 (`forge/scripts/build_rolling_local.sh update`), `system/image-digests.sh` and `system/sign-images.sh` (Task 12), `scripts/devvm/{devvm.env,start.sh,reset.sh,screenshot.sh}`.
- Produces: `images.sh` (registry, keys, ten images), `run.sh [START_AT]` printing one `PASS` line per acceptance item and stopping at the first `FAIL`.

This is spike U1's hand procedure turned into scripts: a `registry:2` container on the host, reached from the guest through an SSH reverse forward on the guest's own `127.0.0.1:5000`, so both sides spell the repository identically. A file deployed under `/usr` with `deploy.sh` vanishes at the next reboot, and this acceptance reboots a dozen times, so the package travels **inside** the images: each is the published system image plus the locally built RPM, the policy rendered for the throwaway registry, and three test conveniences (insecure local registry, a two-minute timer, automatic login of the guest user so that an active local session exists). **Host limit:** `run.sh` refuses to start while any workflow run is in progress (`guard_no_ci`), and the executor must not dispatch a workflow while it runs.

Unlike every earlier task, these scripts were not executed while this plan was written (they need the RPM). They pass `bash -n` and shellcheck. Treat the first run as debugging the harness, with `superpowers:systematic-debugging`, and fix the harness, never the product, to make a `FAIL` go away unless the product is wrong. Three outcomes are open and the plan wants them reported, not worked around: whether `bootc upgrade --from-downloaded` accepts a deployment that `bootc switch` staged and `ostree admin lock-finalization` locked (decision A10; seen only if `stable` is newer than the installed image at migration time); whether `skopeo copy --preserve-digests --sign-by-sigstore-private-key` behaves as the plain form spike U1 measured; whether a process in the user manager of the logged-in user gets polkit's `allow_active` (the notifier depends on it).

- [ ] **Step 1: `scripts/devvm/acceptance/lib.sh`**

````bash
# shellcheck shell=bash
# Shared helpers of the update and trust acceptance (scripts/devvm/acceptance/README.md).
# Sourced, never run. Everything here uses a throwaway registry and throwaway keys.
ACC_HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$ACC_HERE/../../.." && pwd)
# shellcheck source-path=SCRIPTDIR/..
source "$ACC_HERE/../devvm.env"

ACC_REGISTRY=${ACC_REGISTRY:-localhost:5000/acc}
ACC_PORT=${ACC_PORT:-5000}
ACC_STATE=${ACC_STATE:-$STATE/acceptance}
ACC_BASE=${ACC_BASE:-$SYSTEM_IMAGE:latest}
ACC_RPM_DIR=${ACC_RPM_DIR:-$ROOT/RPMS_OUT}
REPO=$ACC_REGISTRY/athanor-system
UPDATE1=(os.athanor.Update1 /os/athanor/Update1 os.athanor.Update1)
mkdir -p "$ACC_STATE"

# The 31 GB host cannot hold the 16 GB runner guest and this 8 GB VM together.
guard_no_ci() {
  local busy
  busy=$(gh api "repos/${GITHUB_REPOSITORY:-hr-mes/athanor}/actions/runs?status=in_progress&per_page=1" --jq .total_count)
  [[ $busy -eq 0 ]] || die "$busy workflow run(s) in progress: the dev VM must not run beside a CI job on this host"
}

wait_ssh() {
  for _ in $(seq 180); do
    if guest_ssh -q true 2> /dev/null; then tunnel; return 0; fi
    sleep 2
  done
  die "no SSH on 127.0.0.1:$SSH_PORT after 6 minutes"
}

# The guest reaches the host's registry on its own 127.0.0.1, so signer and verifier spell
# the repository identically (a signature records the reference it was made for).
tunnel() {
  guest_ssh -q "ss -ltn | grep -q ':$ACC_PORT '" 2> /dev/null && return 0
  ssh -i "$(ssh_key)" -p "$SSH_PORT" -o "UserKnownHostsFile=$STATE/known_hosts" -o ExitOnForwardFailure=yes \
    -f -N -R "$ACC_PORT:127.0.0.1:$ACC_PORT" "$GUEST_USER@127.0.0.1"
}

# Scheduled two seconds ahead, so the SSH command returns before the connection drops and
# its exit status means something.
reboot_guest() { guest_ssh sudo systemd-run --quiet --on-active=2 systemctl reboot; sleep 10; wait_ssh; }
power_cycle() {
  guest_ssh sudo systemd-run --quiet --on-active=2 systemctl poweroff
  for _ in $(seq 60); do systemctl --user -q is-active "$UNIT" || break; sleep 2; done
  "$ACC_HERE/../start.sh" > /dev/null
  wait_ssh
}

state() { guest_ssh cat /run/athanor-update/state.json | jq -r "$1"; }
marker() { guest_ssh cat /usr/share/athanor-acceptance-marker; }
check_now() { guest_ssh sudo systemctl start athanor-update-check.service; }
point_stable() { skopeo copy --src-tls-verify=false --dest-tls-verify=false "docker://$REPO:$1" "docker://$REPO:stable" > /dev/null; }

pass() { echo "PASS  $*"; }
expect() { # expect DESCRIPTION JQ-FILTER VALUE
  local got
  got=$(state "$2")
  [[ $got == "$3" ]] || die "FAIL  $1: $2 is '$got', expected '$3'"
  pass "$1"
}
expect_until() { # expect_until DESCRIPTION JQ-FILTER VALUE MINUTES
  for _ in $(seq $(($4 * 6))); do
    [[ $(state "$2" 2> /dev/null) == "$3" ]] && { pass "$1"; return 0; }
    sleep 10
  done
  die "FAIL  $1: $2 never became '$3' in $4 minutes (it is '$(state "$2")')"
}

# A call as the user of the graphical session (active, local): what the notifier is.
call_active() { guest_ssh sudo systemd-run --quiet --wait --pipe --user --machine="$GUEST_USER@.host" busctl --system call "${UPDATE1[@]}" "$1" 2>&1; }
# A call from this SSH session (inactive, no polkit agent).
call_ssh() { guest_ssh -T busctl --system call "${UPDATE1[@]}" "$1" 2>&1; }
# A call as root, which polkit always authorizes: drives a scenario past a password prompt.
call_root() { guest_ssh sudo busctl --system call "${UPDATE1[@]}" "$1" 2>&1; }
expect_error() { # expect_error DESCRIPTION OUTPUT ERROR-NAME
  [[ $2 == *"$3"* ]] || die "FAIL  $1: expected $3, got: $2"
  pass "$1"
}

# A request that ends in a reboot: the bus connection may drop before the reply, so the exit
# status of the call says nothing. What is asserted is the version that boots.
request_and_reboot() { # request_and_reboot CALLER METHOD EXPECTED-MARKER DESCRIPTION
  local out status=0
  out=$("$1" "$2") || status=$?
  sleep 10
  wait_ssh
  [[ $(marker) == "$3" ]] || die "FAIL  $4: booted $(marker), expected $3 (call exit $status: $out)"
  pass "$4"
}
````

- [ ] **Step 2: `scripts/devvm/acceptance/Containerfile`**

````dockerfile
# One acceptance image: the published system image plus the locally built athanor-update
# RPM, the policy rendered for the throwaway registry and keys, and three test conveniences
# (an insecure local registry, a two-minute timer, an automatic login of the guest user).
ARG BASE
FROM ${BASE}
ARG REGISTRY
ARG MARKER
ARG GUEST_USER
COPY rpm/ /tmp/acceptance-rpm/
COPY keys/ /usr/share/athanor/keys/
RUN rpm -Uvh --replacepkgs --replacefiles /tmp/acceptance-rpm/athanor-update-*.rpm && rm -rf /tmp/acceptance-rpm && \
    /usr/libexec/athanor-update/render-policy --registry "${REGISTRY}" --keys-dir /usr/share/athanor/keys \
        --out /usr/share/athanor/containers --link-etc /etc && \
    systemctl preset athanor-update-check.timer athanor-update-state.service athanor-update-migrate.service bootc-fetch-apply-updates.timer && \
    systemctl --global preset athanor-update-notify.service && \
    printf '[[registry]]\nlocation = "%s"\ninsecure = true\n' "${REGISTRY%%/*}" > /etc/containers/registries.conf.d/50-acceptance.conf && \
    mkdir -p /usr/lib/systemd/system/athanor-update-check.timer.d && \
    printf '[Timer]\nOnBootSec=\nOnBootSec=2min\nRandomizedDelaySec=0\n' > /usr/lib/systemd/system/athanor-update-check.timer.d/10-acceptance.conf && \
    printf '\n[initial_session]\ncommand = "/usr/bin/athanor-session"\nuser = "%s"\n' "${GUEST_USER}" >> /usr/share/athanor-system-config/greetd.toml && \
    echo "${MARKER}" > /usr/share/athanor-acceptance-marker && \
    bootc container lint
````

- [ ] **Step 3: `scripts/devvm/acceptance/images.sh`**

````bash
#!/usr/bin/env bash
# Builds, publishes and signs the images of the acceptance in a throwaway registry on the
# host (docs/architecture/doc_update_trust.md, section 6). Keys are generated here, stay
# under $ACC_STATE/keys and sign nothing else.
#   tag  created     keys shipped  signed with
#   v1   2026-09-10  1             1            the machine's starting point
#   v2   2026-09-15  1             1            through system/sign-images.sh, as the pipeline will
#   v3   2026-09-16  1             (nothing)
#   v3w  2026-09-16  1             other
#   v3b  2026-09-16  cosign-1      cosign-1, as a cosign 3 bundle only
#   old  2026-09-01  1             1
#   v4   2026-09-17  1 and 2       1            rotation, first half
#   v5   2026-09-18  1 and 2       2            rotation, second half
#   v6   2026-09-19  1 and 2       2            after the recovery it is "signed with the old key"
#   v7   2026-09-20  3             3            the recovery target
# Usage: images.sh     (needs podman, skopeo, jq; `nix` for the cosign 3 bundle of v3b)
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

keys=$ACC_STATE/keys
mkdir -p "$keys"
: > "$keys/empty.pass"
for key in acc-1 acc-2 acc-3 other; do
  [[ -f $keys/$key.pub ]] || skopeo generate-sigstore-key --output-prefix "$keys/$key" --passphrase-file "$keys/empty.pass"
done

printf '[[registry]]\nlocation = "%s"\ninsecure = true\n' "${ACC_REGISTRY%%/*}" > "$ACC_STATE/registries.conf"

podman container exists athanor-acc-registry || podman run -d --name athanor-acc-registry -p "127.0.0.1:$ACC_PORT:5000" docker.io/library/registry:2
rpm=$(find "$ACC_RPM_DIR" -name 'athanor-update-1*.x86_64.rpm' | sort -V | tail -n 1)
[[ -n $rpm ]] || die "no athanor-update RPM under $ACC_RPM_DIR: run forge/scripts/build_rolling_local.sh update"

build() { # build TAG CREATED KEY...
  local tag=$1 created=$2 context
  shift 2
  context=$(mktemp -d)
  mkdir "$context/rpm" "$context/keys"
  cp "$rpm" "$context/rpm/"
  for key in "$@"; do cp "$keys/$key.pub" "$context/keys/athanor-image-${key#acc-}.pub"; done
  podman build --format docker -f "$ACC_HERE/Containerfile" -t "$REPO:$tag" \
    --build-arg "BASE=$ACC_BASE" --build-arg "REGISTRY=$ACC_REGISTRY" --build-arg "MARKER=$tag" --build-arg "GUEST_USER=$GUEST_USER" \
    --label "org.opencontainers.image.created=${created}T10:00:00Z" --label "org.opencontainers.image.version=43.${created//-/}.0" "$context"
  rm -rf "$context"
  podman push --tls-verify=false "$REPO:$tag"
}
sign() { # sign TAG KEY
  skopeo copy --src-tls-verify=false --dest-tls-verify=false --sign-by-sigstore-private-key "$keys/$2.private" \
    --sign-passphrase-file "$keys/empty.pass" "docker://$REPO:$1" "docker://$REPO:$1"
}

build v1 2026-09-10 acc-1; sign v1 acc-1
build old 2026-09-01 acc-1; sign old acc-1
build v3 2026-09-16 acc-1
build v3w 2026-09-16 acc-1; sign v3w other
build v4 2026-09-17 acc-1 acc-2; sign v4 acc-1
build v5 2026-09-18 acc-1 acc-2; sign v5 acc-2
build v6 2026-09-19 acc-1 acc-2; sign v6 acc-2
build v7 2026-09-20 acc-3; sign v7 acc-3

# v2 goes the pipeline's way: three repositories, the digests file, sign-images.sh.
build v2 2026-09-15 acc-1
for name in athanor-system-nvidia athanor-system-nvidia-legacy; do
  skopeo copy --src-tls-verify=false --dest-tls-verify=false "docker://$REPO:v2" "docker://$ACC_REGISTRY/$name:v2"
done
mkdir -p "$ACC_STATE/pipeline-keys"
cp "$keys/acc-1.pub" "$ACC_STATE/pipeline-keys/athanor-image-1.pub"
bash "$ROOT/system/image-digests.sh" --registry "$ACC_REGISTRY" --tag v2 --out "$ACC_STATE/image-digests.txt"
COSIGN_PRIVATE_KEY=$(< "$keys/acc-1.private") COSIGN_PASSWORD='' SIGN_KEYS_DIR=$ACC_STATE/pipeline-keys \
  CONTAINERS_REGISTRIES_CONF=$ACC_STATE/registries.conf bash "$ROOT/system/sign-images.sh" "$ACC_STATE/image-digests.txt"

# v3b: the only signature is what cosign 3 writes, a bundle index at sha256-<hex>.
# cosign signs with a key pair of its own making; the image ships that public key, so the
# refusal is about the format and not about the key.
[[ -f $keys/cosign-1.pub ]] || (cd "$keys" && COSIGN_PASSWORD='' nix run nixpkgs#cosign -- generate-key-pair --output-key-prefix cosign-1)
build v3b 2026-09-16 cosign-1
printf '%s' '{"mediaType":"application/vnd.dev.sigstore.signingconfig.v0.2+json","rekorTlogConfig":{},"tsaConfig":{}}' > "$ACC_STATE/no-rekor.json"
digest=$(skopeo inspect --tls-verify=false --format '{{.Digest}}' "docker://$REPO:v3b")
COSIGN_PASSWORD='' nix run nixpkgs#cosign -- sign --yes --allow-insecure-registry --signing-config "$ACC_STATE/no-rekor.json" \
  --key "$keys/cosign-1.key" "$REPO@$digest"
point_stable v1
echo "images published under $ACC_REGISTRY; stable -> v1"
````

- [ ] **Step 4: `scripts/devvm/acceptance/run.sh`**

````bash
#!/usr/bin/env bash
# The acceptance of docs/architecture/doc_update_trust.md, section 6, items 1 to 15, on the
# development VM, against the registry and keys of images.sh. Repeatable: `reset.sh` first.
# Every bootc call is made by the units themselves (item 14): this script only starts units
# and calls the bus. Usage: run.sh [START_AT]   (a stage name below; default: the first)
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

guard_no_ci
STAGES=(install migrate download apply refuse older goback rotate recover podman report)
start=${1:-install}
[[ " ${STAGES[*]} " == *" $start "* ]] || die "unknown stage '$start': one of ${STAGES[*]}"

stage_install() { # the machine starts from v1, on a reference that verifies nothing
  wait_ssh
  guest_ssh sudo bootc switch --transport registry "$REPO:v1"
  reboot_guest
  [[ $(marker) == v1 ]] || die "the guest did not boot v1"
}

stage_migrate() { # items 7 and 8
  expect "7: not verified before the migration" .verified.reason media
  expect "7: and nothing is downloaded meanwhile" .update none
  guest_ssh 'systemctl is-active athanor-update-migrate.service || sudo journalctl -u athanor-update-migrate.service -n 5 --no-pager'
  for _ in $(seq 60); do guest_ssh test -e /var/lib/athanor-update/migrated && break; sleep 10; done
  guest_ssh test -e /var/lib/athanor-update/migrated || die "FAIL  the migration did not complete in 10 minutes"
  reboot_guest
  [[ $(marker) == v1 ]] || die "FAIL  7: the migration changed the version"
  expect "7: verified after the migration, with no update in between" .verified.reason signature
  [[ $(guest_ssh sudo bootc status --format json | jq -r .status.booted.image.image.signature) == containerPolicy ]] || die "FAIL  8: the reference does not enforce the policy"
  pass "8: the machine follows the signed reference"
}

stage_download() { # item 1
  point_stable v2
  expect_until "1: downloaded by the timer with no user action" .update downloaded 20
  power_cycle
  [[ $(marker) == v1 ]] || die "FAIL  1: a poweroff applied the update"
  pass "1: a poweroff boots the old version"
  expect_until "8: and it keeps updating" .update downloaded 20
}

stage_apply() { # items 2, 3 and 14
  expect_error "2: from an SSH session it asks for administrator authentication" "$(call_ssh Apply)" os.athanor.Update1.Error.NotAuthorized
  for member in "org.freedesktop.DBus.Properties GetAll s os.athanor.Update1" "org.freedesktop.DBus.Peer Ping"; do
    # shellcheck disable=SC2086  # the member and its arguments are separate words
    expect_error "2: busctl cannot reach $member" "$(guest_ssh busctl --system call os.athanor.Update1 /os/athanor/Update1 $member 2>&1)" "ccess denied"
  done
  guest_ssh "sudo systemd-run --quiet --unit=acc-inhibit systemd-inhibit --what=shutdown --mode=block --who=acceptance --why=item-2 sleep 600"
  expect_error "2: with a reboot inhibitor held it refuses" "$(call_active Apply)" os.athanor.Update1.Error.Blocked
  [[ $(guest_ssh sudo bootc status --format json | jq -r .status.staged.downloadOnly) == true ]] || die "FAIL  2: the deployment was unlocked"
  pass "2: and nothing is unlocked"
  guest_ssh sudo systemctl stop acc-inhibit.service
  request_and_reboot call_active Apply v2 "2: Apply() from the active session reboots into the new version with no password"
  pass "14: both bootc calls succeeded under the units' own hardening"
  expect "3: verified after the reboot" .verified.reason signature
  expect_error "2: with nothing downloaded it refuses" "$(call_active Apply)" os.athanor.Update1.Error.NothingDownloaded
  guest_ssh "sudo cp --remove-destination /dev/stdin /etc/containers/policy.json" <<< '{"default":[{"type":"insecureAcceptAnything"}]}'
  check_now
  expect "3: a permissive local policy reads not verified" .verified.reason policy-not-in-force
  guest_ssh sudo ln -sfn /usr/share/athanor/containers/policy.json /etc/containers/policy.json
  check_now
  expect "3: and the link restores it" .verified.reason signature
  for unit in athanor-update.service athanor-update-check.service; do
    guest_ssh systemd-analyze security --no-pager "--threshold=$([[ $unit == athanor-update.service ]] && echo 55 || echo 60)" "$unit" > /dev/null || die "FAIL  11: $unit is above its exposure threshold"
  done
  pass "11: both services are below the stated exposure"
}

stage_refuse() { # items 4 and 12
  for tag in v3 v3w v3b; do
    point_stable "$tag"
    check_now
    expect "4/12: $tag is refused" .update refused
    expect "4/12: with the error code policy" .last_error policy
    guest_ssh "! grep -Ei 'signature was required|cryptographic|http|$ACC_PORT/' /run/athanor-update/state.json" || die "FAIL  4: registry text in the state file"
  done
  pass "4: no registry text appears in the state file"
}

stage_older() { # item 9
  point_stable old
  check_now
  expect "9: an older signed digest is published as older-than-booted" .update older-than-booted
  [[ $(guest_ssh sudo bootc status --format json | jq -r .status.staged) == null ]] || die "FAIL  9: something was downloaded"
  pass "9: and nothing is downloaded"
  booted=$(state .booted.digest)
  # images.sh copied v2 to the nvidia repository and sign-images.sh signed it there: the
  # same digest, under a signature made for another repository.
  other=$(skopeo inspect --tls-verify=false --format '{{.Digest}}' "docker://$ACC_REGISTRY/athanor-system-nvidia:v2")
  [[ $booted == "$other" ]] || die "the nvidia copy of v2 must share the digest of the booted image"
  guest_ssh "sudo rm -rf /var/lib/athanor-update/signatures/${booted#sha256:} && sudo skopeo copy --policy /usr/share/athanor/containers/attachments-policy.json docker://$ACC_REGISTRY/athanor-system-nvidia:sha256-${other#sha256:}.sig dir:/var/lib/athanor-update/signatures/${booted#sha256:}"
  guest_ssh sudo systemctl start athanor-update-state.service
  expect "9: a valid signature object copied from another of our repositories reads no-signature" .verified.reason no-signature
  guest_ssh "sudo rm -rf /var/lib/athanor-update/signatures/${booted#sha256:}"
  point_stable v2
  check_now
  expect "9: the next check fetches the right object again" .verified.reason signature
  # The same image under a repository the policy does not scope.
  skopeo copy --src-tls-verify=false --dest-tls-verify=false "docker://$REPO:v2" "docker://${ACC_REGISTRY%/*}/elsewhere/athanor-system:v2"
  guest_ssh sudo bootc switch --enforce-container-sigpolicy --transport registry "${ACC_REGISTRY%/*}/elsewhere/athanor-system:v2"
  reboot_guest
  expect "9: a deployment outside the policy reads reference-out-of-scope" .verified.reason reference-out-of-scope
  guest_ssh sudo bootc switch --enforce-container-sigpolicy --transport registry "$REPO:stable"
  reboot_guest
  expect "9: and back inside it reads verified" .verified.reason signature
}

stage_goback() { # items 5 and 13
  point_stable v2
  expect_error "5: GoBack() asks for administrator authentication from an SSH session" "$(call_ssh GoBack)" os.athanor.Update1.Error.NotAuthorized
  guest_ssh pkaction --verbose --action-id os.athanor.update.rollback | grep -c auth_admin$ | grep -qx 3 || die "FAIL  5: the rollback action is not auth_admin for every kind of session"
  pass "5: and the action is auth_admin for every kind of session (the prompt in the session is looked at by hand: screenshot.sh)"
  left=$(state .booted.digest)
  request_and_reboot call_root GoBack v1 "5: GoBack() boots the previous digest"
  [[ $(guest_ssh cat /var/lib/athanor-update/held) == "$left" ]] || die "FAIL  5: the digest left is not held"
  for n in 1 2 3; do
    check_now
    expect "5/13: check $n does not download the held digest" .update held
    [[ $(guest_ssh sudo bootc status --format json | jq -r .status.staged) == null ]] || die "FAIL  13: the held digest was staged"
  done
  point_stable v4
  check_now
  expect "5: a newer digest is offered" .update downloaded
}

stage_rotate() { # item 6
  request_and_reboot call_root Apply v4 "6: an image that ships a second key and is signed with the first is accepted"
  point_stable v5
  check_now
  expect "6: the next image, signed with the second key, is accepted" .update downloaded
  request_and_reboot call_root Apply v5 "6: and it boots"
  expect "6: and reads verified" .verified.reason signature
}

stage_recover() { # item 10
  guest_ssh "sudo cp /dev/stdin /root/acc-3.pub" < "$ACC_STATE/keys/acc-3.pub"
  guest_ssh sudo athanor-update recover-key begin /root/acc-3.pub
  point_stable v6
  check_now
  expect "10: after the recovery an image signed with the old key is refused" .update refused
  point_stable v7
  check_now
  expect "10: and one signed with the new key is downloaded" .update downloaded
  guest_ssh sudo athanor-update recover-key finish && die "FAIL  10: finish must wait for an image that ships the new key"
  request_and_reboot call_root Apply v7 "10: the image signed with the new key boots"
  guest_ssh sudo athanor-update recover-key finish
  check_now
  expect "10: the machine is on the new key with the old one removed" .verified.reason signature
  [[ $(guest_ssh readlink /etc/containers/policy.json) == /usr/share/athanor/containers/policy.json ]] || die "FAIL  10: the policy link was not restored"
}

stage_podman() { # item 15
  guest_ssh 'podman pull docker.io/library/busybox:latest && podman save -o /var/tmp/acc-busybox.tar busybox && podman rmi busybox && podman load -i /var/tmp/acc-busybox.tar && printf "FROM busybox\nRUN true\n" | podman build -t acc-build - && rm /var/tmp/acc-busybox.tar'
  pass "15: podman pull from another registry, podman load and podman build work with the policy in force"
}

stage_report() {
  guest_ssh "systemctl --user --machine=$GUEST_USER@.host is-active athanor-update-notify.service" || die "FAIL  the notifier is not running under its Landlock ruleset"
  pass "UT11: the notifier runs confined; its notifications are looked at by hand (scripts/devvm/screenshot.sh)"
  echo "acceptance complete"
}

run=''
for stage in "${STAGES[@]}"; do
  [[ $stage == "$start" ]] && run=1
  [[ -n $run ]] || continue
  echo "== $stage"
  "stage_$stage"
done
````

- [ ] **Step 5: `scripts/devvm/acceptance/README.md`**

````markdown
# Update and trust acceptance

Runs section 6 of `docs/architecture/doc_update_trust.md` on the development VM with a
throwaway registry and throwaway keys. Nothing here touches the project registry or key.

    bash forge/scripts/build_rolling_local.sh update     # the RPM under test
    scripts/devvm/acceptance/images.sh                   # registry, keys, ten images (about 20 min)
    scripts/devvm/reset.sh && scripts/devvm/start.sh     # a freshly installed guest
    scripts/devvm/acceptance/run.sh                      # about 90 minutes, a dozen reboots
    scripts/devvm/acceptance/run.sh goback               # resume at a stage

The 31 GB host cannot hold the CI runner guest (16 GB) and this VM (8 GB) together:
`run.sh` refuses to start while a workflow run is in progress. Do not dispatch one meanwhile.

Looked at by hand, with `scripts/devvm/screenshot.sh`: the "update ready" notification after
the `download` stage, the "now running" notification after `apply`, and the administrator
prompt that `busctl --system call os.athanor.Update1 /os/athanor/Update1 os.athanor.Update1 GoBack`
raises when typed in a terminal of the graphical session.

Item 7 has a second half this harness cannot give: a machine really installed from an ISO
that carries the package. After the first pipeline run with the package, `create.sh` a new
VM from that ISO and check that the state reads `media`, then `signature` after the
migration and a restart.

Clean up: `podman rm -f athanor-acc-registry`, `rm -rf ~/.local/share/athanor-devvm/acceptance`.
````

- [ ] **Step 6: Lint**

Run: `shellcheck -x scripts/devvm/acceptance/*.sh && bash -n scripts/devvm/acceptance/run.sh`
Expected: silent. Check `head -5 /usr/bin/athanor-session` on the guest: it must be the session command greetd's `initial_session` can run; if the session is started another way on this image, fix the `printf` of the Containerfile, not greetd.

- [ ] **Step 7: Run it**

Run the four commands of the README. Expected: every line `PASS`, ending in `acceptance complete`. Save the output to `/.scratch/acceptance-<date>.log` and quote it in the pull request. Items and stages: `migrate` 7, 8; `download` 1, 8; `apply` 2, 3, 11, 14; `refuse` 4, 12; `older` 9; `goback` 5, 13; `rotate` 6; `recover` 10; `podman` 15; item 11's `verify.py` and unit-test half is Task 9, Step 9.

- [ ] **Step 8: Commit**

````bash
git add scripts/devvm/acceptance
git commit -m "test(devvm): scripted acceptance of updates and trust state with a throwaway registry and key"
````

### Task 16: MAINTAINER STEP, then the cut-over

**Files:**
- Create (maintainer): `system/keys/athanor-image-1.pub`
- Modify: `system/Containerfile`, `system/build-image.sh`, `system/tests/test_build_image.py`, `.github/workflows/call-system-image.yml`, `scripts/verify.py`, `scripts/tests/test_verify_update_trust.py`
- Modify: `docs/architecture/doc_system_image.md`, `docs/architecture/doc_kernel_profile.md`, `docs/architecture/doc_shell.md` (section 5 of the spec), `NEXT.md`

**Interfaces:**
- Consumes: everything. **Gate:** Task 15 is green, and the recovery command has passed its stage (UT2: "written and tested before the key signs its first image").
- Produces: images whose policy is in force and whose digests carry the key-based signature.

> ## MAINTAINER STEP (D3). The agent stops here and hands over.
>
> The agent never sees the private key, never reads `cosign.key`, never runs these commands.
>
> 1. On an offline machine: `cosign generate-key-pair` (it asks for a password; it writes `cosign.key` and `cosign.pub`). `skopeo generate-sigstore-key --output-prefix athanor-image-1` is the equivalent made by the tool that will sign, and is the safer choice if the rehearsal of point 2 fails.
> 2. Rehearse once, still offline from the project: sign any image in a local `registry:2` with `skopeo copy --sign-by-sigstore-private-key cosign.key --sign-passphrase-file <file on tmpfs> docker://localhost:5000/t:1 docker://localhost:5000/t:1` and pull it back through a policy rendered with `forge/specs/athanor-update/SOURCES/usr/libexec/athanor-update/render-policy --registry localhost:5000/x --keys-dir <dir holding cosign.pub> --out /run/user/$UID/p`. Spike U1 signed with skopeo-made keys only; this proves a cosign-made key works with skopeo before it matters.
> 3. `gh secret set COSIGN_PRIVATE_KEY --env signing < cosign.key` and `gh secret set COSIGN_PASSWORD --env signing` (typed at the prompt).
> 4. Copy `cosign.key` and its password to the offline kit (USB `ATHANOR-KIT`) beside the Secure Boot and module keys; delete every other copy.
> 5. `cp cosign.pub system/keys/athanor-image-1.pub`, commit it (`feat(update-trust): the public image signing key`), push, and record its SHA-256 where the project would announce a key (`sha256sum system/keys/athanor-image-1.pub`).
>
> `system/cosign.pub` is another, older key (`athanor-store`'s); it is not reused and not touched.

- [ ] **Step 1: Check what the maintainer committed**

````bash
openssl pkey -pubin -in system/keys/athanor-image-1.pub -noout -text | grep -E 'prime256v1|P-256'
git ls-files system/keys
git log --oneline -1 -- system/keys/athanor-image-1.pub
````

Expected: the curve line; exactly one tracked file, `system/keys/athanor-image-1.pub`; the maintainer's commit. No `*.key` anywhere: `git ls-files | grep -E '\.(key|private)$'` prints nothing.

- [ ] **Step 2: Failing tests for the image wiring**

Append to class `UpdateTrust` in `scripts/tests/test_verify_update_trust.py`:

````python
    def test_the_image_build_renders_the_policy_and_links_etc(self):
        self.assertEqual(verify.image_policy_problems(), [])
        system = self.root / "system"
        (system / "keys").mkdir(parents=True)
        (system / "Containerfile").write_text("FROM scratch\nRUN systemctl preset-all\n")
        found = verify.image_policy_problems(self.root)
        self.assertTrue(any("render-policy" in p for p in found))
        self.assertTrue(any("system/keys" in p for p in found))
        (system / "keys/athanor-image-1.pub").write_text("-----BEGIN PUBLIC KEY-----\n")
        (system / "keys/leak.key").write_text("x")
        (system / "Containerfile").write_text(
            "ARG IMAGE_REGISTRY\nCOPY system/keys/ /usr/share/athanor/keys/\n"
            'RUN /usr/libexec/athanor-update/render-policy --registry "${IMAGE_REGISTRY}" --keys-dir /usr/share/athanor/keys '
            "--out /usr/share/athanor/containers --link-etc /etc\nRUN systemctl preset-all\n")
        self.assertEqual(verify.image_policy_problems(self.root), ["system/keys/leak.key: only *.pub files belong under system/keys"])
````

and to `system/tests/test_build_image.py`, inside `test_every_image_carries_its_own_version_and_build_time`, one more assertion: `self.assertIn("IMAGE_REGISTRY=localhost", args)`.

Run both suites. Expected: FAIL (`no attribute 'image_policy_problems'`; `IMAGE_REGISTRY=localhost` not in the arguments).

- [ ] **Step 3: The wiring**

1. `system/build-image.sh`: in the `args=(…)` line that starts the build arguments, add `--build-arg "IMAGE_REGISTRY=$REGISTRY"`.
2. `system/Containerfile`, immediately **before** the `# Declarative Systemd presets & sysusers` block (the presets of the package must be applied by the `preset-all` that follows):

````dockerfile
# Signature policy of the system images (docs/architecture/doc_update_trust.md, UT3). The
# container tools read /etc/containers only, so the policy is rendered under /usr, for the
# registry this image is published to and the public keys committed under system/keys, and
# /etc/containers/policy.json and registries.d/athanor.yaml become links to it. No default:
# build-image.sh always passes the registry, and the renderer refuses an empty one.
ARG IMAGE_REGISTRY
COPY system/keys/ /usr/share/athanor/keys/
RUN /usr/libexec/athanor-update/render-policy --registry "${IMAGE_REGISTRY}" --keys-dir /usr/share/athanor/keys \
        --out /usr/share/athanor/containers --link-etc /etc && \
    test "$(readlink /etc/containers/policy.json)" = /usr/share/athanor/containers/policy.json && \
    test "$(readlink /etc/containers/registries.d/athanor.yaml)" = /usr/share/athanor/containers/registries.d/athanor.yaml && \
    test "$(grep -c sigstoreSigned /etc/containers/policy.json)" -eq 3
````

   That the rendered policy is one containers/image accepts is proven by `test_render_policy.py` (skopeo loads it) and again by every run of `sign-images.sh`; the build only checks that the links and the three scopes are there.
3. `scripts/verify.py`, below `update_trust_problems`, and one more hook at the end of `check_shipped` (`for problem in image_policy_problems(): r.fail(problem)`):

````python
def image_policy_problems(root=None):
    """system/Containerfile puts the policy in force and system/keys holds public keys only."""
    root = root or ROOT
    problems = []
    containerfile = read(root / "system/Containerfile")
    if not re.search(r"^ARG IMAGE_REGISTRY$", containerfile, re.M) or "render-policy" not in containerfile or "--link-etc /etc" not in containerfile:
        problems.append("system/Containerfile: does not run render-policy --link-etc /etc with ARG IMAGE_REGISTRY: "
                        "the policy is never in force and no machine verifies an image")
    elif containerfile.index("render-policy") > containerfile.index("systemctl preset-all"):
        problems.append("system/Containerfile: render-policy runs after preset-all")
    if "COPY system/keys/ /usr/share/athanor/keys/" not in containerfile:
        problems.append("system/Containerfile: does not copy system/keys to /usr/share/athanor/keys")
    keys = sorted((root / "system/keys").glob("*")) if (root / "system/keys").is_dir() else []
    if not any(key.suffix == ".pub" for key in keys):
        problems.append("system/keys: no *.pub: the rendered policy would name no key")
    for key in keys:
        if key.suffix != ".pub":
            problems.append(f"system/keys/{key.name}: only *.pub files belong under system/keys")
    return problems
````

- [ ] **Step 4: The signing job**

In `.github/workflows/call-system-image.yml`:

1. Under `on.workflow_call.secrets`, declare `COSIGN_PRIVATE_KEY` and `COSIGN_PASSWORD` the way `SECUREBOOT_SIGNING_KEY` is declared (`required: false`, description "supplied by the signing environment").
2. In job `dag-system-image`, after the step `📤 Push OS Images`, add:

````yaml
      - name: 🧾 Record the pushed digests for the signing job
        env:
          RUN_ID: ${{ github.run_id }}
        run: bash system/image-digests.sh --registry "${IMAGE_REGISTRY}" --tag "${RUN_ID}" --out artifacts/image-digests.txt
      - name: 📎 Hand the digests to the signing job
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: image-digests
          path: artifacts/image-digests.txt
          if-no-files-found: error
````

   (Both pins are the ones this repository already uses. The file on disk is the interface; the artifact is only how a file crosses jobs on GitHub.)
3. A new job after `dag-system-image`:

````yaml
  sign-system-images:
    name: 🔏 Key-based signature of the system images
    # The only job that receives COSIGN_*. It builds nothing and runs no third-party tool
    # beside the key: checkout, registry login, system/sign-images.sh (UT2).
    needs: [dag-system-image]
    runs-on: ubuntu-24.04
    environment: signing
    timeout-minutes: 60
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - name: 📎 Digests recorded by the build job
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c
        with:
          name: image-digests
          path: artifacts
      - name: 🔑 Login to the registry
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_ACTOR: ${{ github.actor }}
        run: echo "${GITHUB_TOKEN}" | skopeo login "$(cut -d/ -f1 artifacts/image-digests.txt | head -n 1)" -u "${GITHUB_ACTOR}" --password-stdin
      - name: 🔏 Sign, then verify as a machine will (system/sign-images.sh)
        env:
          COSIGN_PRIVATE_KEY: ${{ secrets.COSIGN_PRIVATE_KEY }}
          COSIGN_PASSWORD: ${{ secrets.COSIGN_PASSWORD }}
        run: bash system/sign-images.sh artifacts/image-digests.txt | tee -a "${GITHUB_STEP_SUMMARY}"
````

   The ISO steps stay in `dag-system-image`: the ISO is not an update source. The keyless `sign_attest.sh` step stays where it is. If the hosted runner's skopeo is older than 1.14 (`skopeo --version` in a throwaway run of the lint job), install it from the builder image the other jobs use rather than from a third-party action: the job must stay free of third-party binaries.

Run: `actionlint && python3 scripts/verify.py workflows` and `bash -n` on nothing (no `run:` block is longer than one line).
Expected: silent; green.

- [ ] **Step 5: Rehearse the image build locally**

Run: `bash system/build-image.sh --gpu none --registry localhost --tag check` (long; ask the maintainer before starting it, and not while a CI job runs). Then:

````bash
podman run --rm localhost/athanor-system:check sh -c 'readlink /etc/containers/policy.json /etc/containers/registries.d/athanor.yaml; grep -c sigstoreSigned /etc/containers/policy.json; ls /usr/share/athanor/keys; systemctl is-enabled athanor-update-check.timer athanor-update-state.service athanor-update-migrate.service bootc-fetch-apply-updates.timer'
podman image inspect localhost/athanor-system:check --format '{{ index .Labels "org.opencontainers.image.version" }} {{ index .Labels "org.opencontainers.image.created" }}'
````

Expected: the two link targets under `/usr/share/athanor/containers`; `3`; `athanor-image-1.pub`; `enabled enabled enabled disabled`; a version `43.<today>.0` and today's time.

- [ ] **Step 6: The documents of section 5 of the spec**

- `docs/architecture/doc_system_image.md`: a short section "Version and signatures" stating the two labels of UT9 (format, the serial's source, "ordering uses the build time"), and that the three images carry a key-based signature made by `system/sign-images.sh` beside the keyless one, with pointers to `doc_update_trust.md` UT2 and UT9.
- `docs/architecture/doc_kernel_profile.md`, section 8: one sentence pointing at `doc_update_trust.md` as the interim update service, and the note on the override that "stages updates automatically" replaced by a pointer to `doc_shell.md` SH11.
- `docs/architecture/doc_shell.md`: nothing to do if revision 3 already carries the "installed from media" wording in SH12 and acceptance 8, and constraint 7 already points at D2 (`grep -n 'installed from media\|D2' docs/architecture/doc_shell.md`: it does today).
- `NEXT.md`: mark package 1b-system done with the acceptance log's date.

Run: `python3 scripts/verify.py docs`
Expected: green.

- [ ] **Step 7: Commit, push, watch one pipeline run**

````bash
git add system/Containerfile system/build-image.sh system/tests/test_build_image.py scripts/verify.py scripts/tests/test_verify_update_trust.py
git commit -m "feat(system-image): put the signature policy in force: rendered policy, /etc links, public keys"
git add .github/workflows/call-system-image.yml
git commit -m "feat(ci): sign the system images with the project key in a job of its own, and verify as a machine will"
git add docs/architecture NEXT.md
git commit -m "docs: version labels, key-based signature and the interim update service"
````

Never push `forge/**` while an Orchestrator cycle runs. After the pull request merges, the first Orchestrator run must show job `sign-system-images` green with three `signed and verified with the shipped policy` lines. Then, with the maintainer: `gh workflow run promote-stable.yml -f run_id=<that run>`; on the dev VM installed from that run's ISO, the second half of acceptance 7; on the maintainer's desktop, acceptance 8 (`systemctl status athanor-update-migrate.service`, a restart, then `jq .verified /run/athanor-update/state.json` reads `signature`).

---

## Self-review

**Spec coverage.** UT1: Tasks 5, 6, 9 (units, lock in Task 3, presets, override and preset line removed, hardening asserted verbatim, only the check and migrate units reach the network). UT2: Tasks 12, 16 (own job, skopeo, client-style verification), Task 6 and 15 (recovery written and tested before the key signs). UT3: Tasks 7, 16 (templates, renderer, `/etc` links, `verify.py shipped`), Task 4 (SHA-256 comparison, `reference-out-of-scope`), Task 15 (rotation). UT4: Task 6, Task 9 (unit), Task 15. UT5: Tasks 2, 4 (four rules by test, keys from `keyPaths`, digest and repository, build-time rule, `media`). UT6: Task 5, Task 9 (bus and polkit files). UT7: Tasks 1, 3, 9 (`tmpfiles.d`). UT8: Task 3. UT9: Task 11. UT10: Task 14. UT11: Task 8. UT12: Task 4. D1: Task 13. D2: Task 10. D3: Task 16. Acceptance 1 to 15: Task 15, with item 11 split between Task 9 and the `apply` stage, and the second half of item 7 after the cut-over.

**Known gaps, stated rather than hidden.** (1) `reference-out-of-scope`, the permissive-policy reason and the notifier's notifications are seen on the dev VM; the administrator prompt of `GoBack()` in the graphical session is looked at by hand. (2) The enablement of the TPM sealing and rollback-update units (Task 10, Step 1) is reported, not changed. (3) `athanor-updater-rs`, a second bootc updater still in the workspace (`Cargo.toml`, member `system/athanor-updater-rs`), is not shipped and is not touched; the maintainer decides whether it retires. (4) `cargo clippy` is not in the build container used while writing this plan; CI's `just forge/lint` runs it with `-D warnings`, so run `cargo-in-box clippy -p athanor-trust-state -p athanor-update -p athanor-update-notify --all-targets -- -D warnings` in an image that has it (plan 1a's rig) before the pull request.

**Type consistency.** `Context`, `Fake`, `Machine`, `deployed`, `digest`, `REPO`, `SIGNED` are defined in Task 4 and used unchanged in Tasks 5 and 6. `Store::replace` is `pub(crate)` from Task 3 because Task 6 uses it. `Tools::switch` and `Tools::relock` exist from Task 3 although first used in Tasks 5 and 6. The bus name, object path and error names of Task 5 are the ones Tasks 8, 9 and 15 spell. `update_trust_problems(root=None)` is extended, never redefined, by Tasks 10 and 16.

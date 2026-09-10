# athanor-shell-rs

A single native Rust/GTK4 binary (`athanor-shell-rs`) that implements essentially all of Athanor OS's desktop shell: top bar, control center, notifications/OSD, launcher, dock, greeter/lockscreen, mission control, app store, spotlight search, clipboard manager, security/privacy prompt dialogs, and more — one process wearing many hats, selected at launch via CLI flag (see `Args` in `main.rs`). It talks to system daemons over D-Bus (audio/network/bluetooth/display/power/MPRIS controllers) and to `niri` over its native Wayland IPC socket.

## Status: Partial (large, mostly-implemented codebase; a few notable gaps and one architectural surprise)

## Subsystems

| Subsystem | Status | Notes |
|---|---|---|
| Top bar / OSD / desktop widgets (default mode) | Implemented | Launched unconditionally when no mode flag is passed; Relm4-based top bar plus OSD and desktop widget overlays. |
| Greeter / lockscreen (`--greeter`/`--lock`) | Implemented | Talks to the **real, standard `greetd` daemon** over `/run/greetd.sock` via `greetd_ipc` (`sys/auth.rs`) — this crate does not reimplement PAM, it drives greetd's own conversation. |
| Launcher / Dock (`--launcher`/`--dock`) | Implemented | Single-instance GTK Layer Shell surfaces toggled via a `connect_command_line` re-invocation pattern. |
| Security/privacy prompt dialogs (`--gatekeeper-prompt`, `--privacy-prompt`, `--file-chooser`) | Implemented | Standalone one-shot GTK windows that other daemons (`athanor-gatekeeper-rs`, `xdg-desktop-portal-athanor`) shell out to for the actual UI — see those crates' subprocess calls. |
| D-Bus system controllers (`ipc/`) | Implemented | Audio/network/bluetooth/display/power/MPRIS controllers registered in a type-erased [`ControllerBackend`] registry (`ipc/system_proxies.rs`); connects to both session and system buses. |
| Landlock sandboxing (`sys/sandbox.rs`) | Partial | Applies a real Landlock V1 policy (read-only `/usr`, `/etc`, `$XDG_RUNTIME_DIR`, deny-by-default elsewhere) — but a failure to apply it only logs a warning in `main.rs`; the process still runs unsandboxed rather than refusing to start. |
| Theming (`theme/`) | Implemented | Static shell CSS plus a dynamic, wallpaper-derived Material 3 palette with live file-monitor hot-reload. |
| "Security Audit Center" UI | **Not implemented** | Not found anywhere in this crate (verified by grep for this pass); AUDIT_REPORT.md's DOC-04 attributes this "Advanced Feature" claim to `athanor-settings-rs` (a different crate, outside this group), not to this one. |

## How it fits in Athanor OS

Builds the `athanor-shell-rs` binary via `forge/specs/athanor-shell-rs/athanor-shell-rs.spec` (`cargo build --release --locked`, installed to `/usr/bin/athanor-shell-rs`; the spec `Requires:` real runtime deps — `gtk4-layer-shell`, `cage`, `niri`, `wl-clipboard`, `cliphist`, `upower`, etc.). It is a member of the root Cargo workspace and links `athanor-style` as a path dependency for theming.

**Architectural finding from this documentation pass:** the shipped `greetd.toml` (`forge/specs/athanor-system-config/SOURCES/usr/share/athanor-system-config/greetd.toml`) launches `cage -s -- /usr/bin/athanor-shell-rs --greeter` as the actual login/greeter session — meaning this crate, not `system/athanor-greeter`, is what real users hit at the login screen. `athanor-shell-rs`'s greeter mode then authenticates by talking back to `greetd` itself over its IPC socket, the standard greetd architecture. `system/athanor-greeter` (a separate crate in this same documentation group) is a functioning but currently unwired-in standalone binary — see its own README.

The dedicated systemd user unit `forge/specs/athanor-system-services/SOURCES/usr/lib/systemd/user/athanor-shell.service` runs the default (no-flag) top-bar/OSD/widgets mode as part of the graphical session. No `just` recipe in the root/`forge`/`system` Justfiles references this crate by name.

## Known issues

- Landlock sandbox failure is non-fatal (logs and continues unsandboxed) rather than fail-closed — a deliberate startup-robustness tradeoff, but worth knowing if sandboxing is assumed guaranteed.
- Given the crate's size (~80 source files, ~16,700 lines), this documentation pass added module-level docs to every module boundary (`main.rs` and all 12 `mod.rs` files) and full doc coverage to the security/architecture-critical files (`sys/auth.rs`, `sys/sandbox.rs`, `ipc/mod.rs`, `ipc/system_proxies.rs`, `control_center/mod.rs`, `desktop_canvas/mod.rs`); it does not claim exhaustive `///` coverage of every public item in every UI widget file.
- Zero `unsafe` blocks were found anywhere in this crate (verified by grep for this pass).
- See CQ-05 in AUDIT_REPORT.md for the repo-wide doc-comment coverage baseline this pass addresses.

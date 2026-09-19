# Shell Stage 1, Package 1a: Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the "Calmo" design system: one tokens file that generates the GTK4 CSS of our surfaces and the default `CosmicTheme`, gated in CI by GTK's own parser and a WCAG AA contrast check, together with the font, the hearth wallpaper, the seal icons, and the greeter re-skinned on the tokens with accessible roles and gettext.

**Architecture:** A Python standard-library toolchain under `system/athanor-style/calmo/` owns the tokens, the contrast gate and the generators; everything it emits is committed under `calmo/generated/` and a `--check` mode fails CI when the committed output drifts from the tokens. The `athanor-style` crate embeds the generated CSS (`include_str!`) and exposes it per variant, so a surface cannot start without its stylesheet and the RPM carries no CSS file. COSMIC receives Calmo through a data directory of our own placed ahead of `/usr/share` in `XDG_DATA_DIRS`, never by touching a file a COSMIC RPM owns. The greeter becomes a program of its own, the crate `athanor-greeter-ui` (SH4, "one crate per program"), and the old `athanor-shell-rs` binary is frozen at GTK 0.7 in a workspace of its own instead of being bumped. The screenshot and accessibility rig is spike P3's container recipe turned into maintained scripts under `forge/test/shell/`.

**Tech Stack:** Python 3.11+ standard library (`tomllib`, `colorsys`, `zlib`, `unittest`); PyGObject with GTK 4.20 inside the rig container only; Rust with gtk4 0.11.4, gtk4-layer-shell 0.8.1, glib 0.22.9, relm4 0.11.0 (for `athanor-recovery` only), translations in gettext's format read by our own dependency-free crate `athanor-i18n`; GNU gettext tools (`xgettext`, `msgfmt`); podman rootless, `registry.fedoraproject.org/fedora:43`; cosmic-theme at libcosmic revision `2a73fbc0edfe1525381bf999e241d73def79b222` (the one cosmic-settings `epoch-1.8.0` locks) in a standalone tool outside the workspace.

**Spec:** `docs/architecture/doc_shell.md` (approved 2026-09-18, revision 3): SH4, SH5, SH12 (the seal's look only), SH13, section 3 row 1a, section 5, acceptance items 1, 2, 3 (greeter part) and 11 (the greeter's 12 surface cases). Evidence: `.superpowers/spike-p1-applet.md`, `.superpowers/spike-p2-gtk-bump.md`, `.superpowers/spike-p3-headless.md`, and the approved mockup `.superpowers/brainstorm/89841-1789751828/content/interfaccia-athanor-v3.html` (`.superpowers/` is git-ignored: the values this plan needs from it are copied here).

## Global Constraints

- English for every new file, comment, commit message and workflow output; conventional-commit subjects; one problem per commit. End every commit message with the attribution lines the session gives.
- Never prefix a command with `cd`. Paths are relative to the repository root; use `cargo -p <crate>`, `git -C <dir>`.
- Never open anything under `docs/architecture/graph-vaults/`.
- No `|| true`, no `continue-on-error`, no fallback that hides a failure.
- Pipeline portable: logic lives in scripts in the repository, workflow YAML checks out, calls them and uploads their output; no `run:` block beyond a few lines; steps exchange data through files in a known directory; no hard-coded `ghcr.io/hr-mes` (a variable with a default).
- Python tests live in `<area>/tests/` and run with `python3 -B -m unittest discover -s <dir>`.
- Scratch files go under `/.scratch/` (git-ignored) and are never committed.
- Do not edit `system/athanor-bus-api/src/polkit.rs`, `forge/specs/athanor-gatekeeper-rs/`, or `system/confidential_computing/athanor-attestation/`. No task in this plan touches them.
- Rust: `panic = "abort"` on dev and release; no `.unwrap()`/`.expect()` outside tests; versions live in `[workspace.dependencies]` and crates use `{ workspace = true }`. **This plan adds no third-party crate that is new to the project.** `greetd_ipc 0.10.3` and `landlock 0.4`, which `athanor-shell-rs` pins directly today, move into `[workspace.dependencies]` with the greeter (Task 11).
- Factory accent (SH5, as corrected on 2026-09-19): hue 231, saturation 62 % in the HSL tokens; `#2e44c2` on light (`hsl(231 62% 47%)`), `#8898f7` on dark (`hsl(231 87% 75%)`).
- Trust colours (SH5) "are fixed and never derived from the accent": light `#12805f` / `#a36a00` / `#b3261e`, dark `#5fdcc0` / `#ffcf70` / `#ffa79d`.
- Contrast (SH5): "every text/background pair of the tokens meets WCAG AA in four variants, light and dark, each normal and high-contrast": 4.5:1 for text, 3:1 for large text and for non-text UI (WCAG 2.1, 1.4.3 and 1.4.11).
- CSS (SH5): "CI parses the generated CSS with GTK's own parser; a parse warning fails the build." "Nothing in the identity relies on an effect GTK4 cannot draw."
- One crate per program (SH4, maintainer's decision of 2026-09-19): "Every surface is its own binary in its own crate, with only the dependencies, the Landlock rules and the review surface it needs: the greeter first"; "`athanor-shell-rs` … is not bumped: it leaves the workspace frozen at GTK 0.7 and is mined for the code worth keeping until it is empty, then deleted."
- Shim (SH4): "the package's `%check` asserts the `DT_NEEDED` order, and every layer-shell surface asserts at start that it is a layer surface and exits with an error when it is not."
- Seal (SH12, SH1): the greeter's seal shows the exclamation badge and the words "Not verified" as a constant until package 1b-shield binds the state file. It never shows the check. "No facades."
- Tests (SH13): surfaces run "scale {1.0, 1.5} × theme {light, dark} × text {English, German for length, a right-to-left pseudo-locale}"; "isolated `XDG_*` directories per case, a frozen wall clock with a live monotonic clock, `TZ=UTC`, `LC_ALL` per case, a fixed set of running clients, the runner label `ubuntu-24.04` and the container pinned by digest". "Italian and English are the shipped locales." "All strings go through gettext from the first commit."
- Golden tolerance (the number SH13 asks the plan to state): a case passes when **at most 64 pixels** differ from its golden (`magick compare -metric AE -fuzz 2%`). Spike P3 measured 0 on one machine; 64 pixels is 0.003 % of a 1920×1080 frame and absorbs llvmpipe code-path differences between runner CPU generations without hiding a moved widget, the smallest of which (a 12 px badge) is 113 pixels.

## Architecture decisions

### D1. Tokens format and generator

- **Format:** `system/athanor-style/calmo/tokens.toml`. TOML because `tomllib` is in the standard library of the Python the hosted runner and the RPM builder already have (`flake.nix` build-tools list `python3`), and because the workspace already reads TOML everywhere. A colour is a hex string or a table `{ s, l }` on the accent hue with optional `dh`, `a`, and `s = "accent"`/`"accent+N"`: this is the mockup's own derivation (`hsl(var(--h) var(--s) 47%)`), so a later curated palette changes two numbers.
- **Generator:** `system/athanor-style/calmo/generate.py`, standard library only. Sub-commands `css`, `cosmic`, `wallpaper`, `icons`, `all`, and `--check` (regenerate in memory, compare with the committed files, exit 1 on drift). Output is committed under `calmo/generated/`, so `cargo build` never needs Python and a reviewer sees every generated change in the diff.
- **GTK CSS:** four files, `calmo-light.css`, `calmo-dark.css`, `calmo-light-hc.css`, `calmo-dark-hc.css`. Each is a block of `@define-color ath_<name>` lines for that variant followed by the shared rules rendered from `templates/surfaces.css.in` (`string.Template`, `$name` placeholders for radii, sizes, font). Colours stay named colours so that package 1b's surfaces can re-define `ath_acc` at run time from `CosmicTheme` with a higher-priority provider; the greeter never does. Measured in the P3 image (GTK 4.20.4, PyGObject): `@define-color`, `radial-gradient(circle at 80% 122%, …)`, `font-feature-settings`, `letter-spacing` in `em`, `line-height`, `-gtk-icon-palette` and multi-layer `box-shadow` all parse with zero `parsing-error` signals; `backdrop-filter` and `!important` are reported, and the provider needs neither a display nor `Gtk.init()`.
- **No animation in 1a.** The template has no `transition` and no `animation`, which satisfies "every animation has a disabled path" trivially and keeps captures deterministic.
- **CosmicTheme: how COSMIC 1.8 is structured** (read on this machine, `cosmic-settings-1.8.0-1.fc43`, and in libcosmic at the locked revision):
  - `com.system76.CosmicTheme.{Light,Dark}.Builder/v2`: 21 *input* keys (`accent`, `bg_color`, `neutral_tint`, `text_tint`, `primary_container_bg`, `secondary_container_bg`, `success`, `warning`, `destructive`, `corner_radii`, `spacing`, `gaps`, `active_hint`, `window_hint`, `palette`, `alpha_map`, `frosted*`). Stock values for every colour input are `None`.
  - `com.system76.CosmicTheme.{Light,Dark}/v2`: 34 *derived* keys. `Theme::get_active()` reads **these**, never the Builder; the Builder is read only when the user changes something in Settings, which then runs `ThemeBuilder::build()` and writes the derived theme into `~/.config/cosmic`.
  - `com.system76.CosmicTheme.Mode/v1`: `is_dark` (stock: `true`) and `auto_switch`.
  - `v1` directories of the two theme configs still ship for binaries built against an older libcosmic; nothing in our image is one, so this plan generates `v2` only.
  - **The derived theme must come from COSMIC's own code.** `ThemeBuilder::build()` is about 570 lines of OKLCH step arithmetic; a Python port would drift at every COSMIC bump, and a derived theme that disagrees with the Builder makes every colour jump the first time the user touches Appearance. No shipped binary builds a theme from the command line (`cosmic-settings` has page sub-commands only; cosmic-settings-daemon does not rebuild). Therefore: the Python generator writes the **five Builder inputs** Calmo sets (`accent`, `bg_color`, `primary_container_bg`, `neutral_tint`, `text_tint`), and a 40-line standalone Rust tool, `forge/tools/calmo-cosmic-theme/`, loads the stock Builder defaults, applies those five, calls `build()`, and writes the complete Builder and derived directories plus `Mode`. The tool depends on `cosmic-theme` by git revision, so it lives **outside the workspace** (own `Cargo.toml`, own `Cargo.lock`, listed in `[workspace] exclude`): the workspace keeps `allow-git = []` and its offline RPM builds. Its output is committed under `calmo/generated/cosmic/` with a stamp file holding the SHA-256 of the five inputs and the libcosmic revision; `generate.py --check` recomputes the stamp in pure Python, so CI detects "tokens changed, derived theme not regenerated" without compiling libcosmic.
  - Mapping (semantics read in `build()`): `accent` ← `acc`; `bg_color` ← `surf2` (COSMIC's window background, where it draws headers and side bars, as the mockup does); `primary_container_bg` ← `surf` (content area); `neutral_tint` ← `ink3` (tints the 11 control steps); `text_tint` ← `ink`. Whether this mapping *looks* like the mockup is the one thing that cannot be settled by reading: Task 7 starts with a capture of cosmic-panel and cosmic-settings under the overlay and names what to change for each outcome.

### D2. How the defaults reach COSMIC: an overlay data directory

- **Evidence that cosmic-config honours `XDG_DATA_DIRS`.** Source, at the revision cosmic-settings 1.8.0 locks: `cosmic-config/src/lib.rs` lines 192 and 225, `xdg::BaseDirectories::with_prefix("cosmic").find_data_file(&path)` with `path = <name>/v<version>`; `find_data_file` walks `XDG_DATA_HOME`, then `XDG_DATA_DIRS` in order. Empirically, on 2026-09-19 in the P3 container with the shipped `cosmic-panel-1.8.0-1.fc43`: a directory holding only a copy of `cosmic/com.system76.CosmicPanel.Panel/v1` with `anchor` set to `Left`, placed first in `XDG_DATA_DIRS`, moved the panel to the left edge (capture differs from the baseline by 1.16e9 AE; the same run without the variable is byte-identical to the baseline).
- **Resolution is per directory, not per key:** the first data directory that contains `<name>/v<N>` supplies *every* system default of that config. An overlay must therefore carry the complete key set of each config it shadows. The Rust tool writes complete sets, so this costs nothing.
- **Choice: the overlay.** Files live in `/usr/share/athanor/cosmic-defaults/cosmic/…`, owned by our `athanor-calmo` RPM: no file conflict, no modified RPM-owned file, `rpm -V cosmic-settings` stays clean. The build-step alternative (overwriting `/usr/share/cosmic` after the COSMIC RPMs in `system/Containerfile`) is rejected because it silently reverts whenever a later layer reinstalls a COSMIC package and leaves the image with files that disagree with their RPM database.
- **Where the variable is set:** `/usr/lib/environment.d/60-athanor-cosmic-defaults.conf` (read by the systemd user manager, which starts cosmic-panel, the applets, cosmic-bg and every D-Bus-activated COSMIC application) and one `export` in `/usr/bin/athanor-session` before `cosmic-comp` (the compositor and its children, the locker and cosmic-idle, are not children of the user manager).
- **"A user whose `~/.config/cosmic` already holds a theme keeps it"** holds by construction: cosmic-config reads the user directory first and the system default only for a missing key.
- **Checkable by `scripts/verify.py shipped`:** the check gains three assertions: every file under `calmo/generated/cosmic/` is installed by `athanor-calmo.spec` beneath `/usr/share/athanor/cosmic-defaults/`; the `environment.d` file exists in the package sources and names that directory first; `athanor-session` exports the same value. A rig scene (Task 7) proves the running behaviour.
- **Known limit, stated rather than hidden:** a process started with a rebuilt `XDG_DATA_DIRS` that drops our directory sees stock COSMIC defaults until the user has a theme of their own. Flatpak's and Nix's profile hooks prepend or append and do not rebuild it.

### D3. CI gates

- **Contrast gate:** `calmo/contrast.py`, pure Python, unit-tested, run in `call-lint.yml` next to the other unit-test steps. It composites translucent layers (the hearth discs under the clock) before measuring.
- **GTK parse gate:** `forge/test/shell/css_parse_gate.py`, PyGObject, `Gtk.CssProvider` with the `parsing-error` signal, exit 1 on any report. It runs in the rig image, because the hosted runner's Ubuntu GTK is older than Fedora 43's 4.20 and the product's parser is the one that counts.
- Both, and the surface cases, are jobs of one thin workflow, `.github/workflows/shell-surfaces.yml`, that only calls `forge/test/shell/rig.sh`.

### D4. One crate per program, and the GTK bump that is left

- **The greeter is the crate `athanor-greeter-ui`,** at `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/`, package and binary `athanor-greeter-ui`, RPM `athanor-greeter-ui`, short name `greeter-ui` in `packages.json`. The name avoids `system/athanor-greeter`, which is the PAM/TPM daemon (unshipped, in `experimental/EXEMPT`) and keeps its name. The application id stays `os.athanor.Greeter`, because the confinement wrapper's D-Bus filter names it.
- **What moves into it, and nothing else:** `ui/greeter/greeter.rs` (as `src/ui.rs`), `sys/auth.rs` (`src/auth.rs`), `sys/sandbox.rs` (`src/sandbox.rs`, with a smaller write set), the three-method logind proxy out of `ipc/power.rs` (`src/power.rs`), and from `main.rs` the Landlock-first start, the Tokio runtime (the workspace's zbus is built on Tokio) and the tracing set-up. **No theme code moves:** the old `theme::init_css()` loads `/usr/share/athanor/style.css`, which no package installs, the glass sheet GTK rejects, and writes a Material palette into the configuration directory; the greeter's own inline sheet is what draws it, and Task 16 replaces that sheet with Calmo. The global `mimalloc` allocator, `GSK_RENDERER=ngl`, `GDK_BACKEND` and `GDK_SCALE=1` do not move either.
- **The old `athanor-shell-rs` RPM cannot leave the image yet.** Checked on the tree: the shipped `xdg-desktop-portal-athanor` (tier 3, `UseIn=athanor`, selected by `XDG_CURRENT_DESKTOP=Athanor:COSMIC`) runs `athanor-shell-rs --privacy-prompt` for Camera, Microphone and Location and `athanor-shell-rs --file-chooser` for FileChooser, and denies by default when the binary is missing. Removing the package would break every file dialog of a sandboxed application. `athanor-desktop-ui` and the portal keep their `Requires: athanor-shell-rs`; `athanor-system-config` switches to `athanor-greeter-ui`. Moving those two prompts out is the next mining step and belongs to the portal's own plan.
- **Frozen, and still buildable: measured.** `links = "gtk-4"` constrains one dependency graph, which is one lock file, not the machine: two workspaces with two lock files build side by side. What does not work is the naive version, for two reasons found by trying: the crate's dependencies say `{ workspace = true }`, which needs a workspace root, and its path dependency `athanor-style` would drag the live crate at gtk4 0.11 into the 0.7 graph. The frozen tree therefore gets a workspace root of its own, `forge/specs/athanor-shell-rs/Cargo.toml` (members: the shell, `athanor-dock` through `package.workspace`, and `athanor-style-0.7`, a frozen copy of today's `system/athanor-style` sources, 1,733 lines), its own `[workspace.dependencies]` copied from the root at today's versions, and its own `Cargo.lock` pruned from the root's. Built on a scratch copy on 2026-09-19 in the P2 image: `cargo check -p athanor-shell-rs` finishes in 45 s at gtk4 0.7.3 with 274 locked packages, while the main workspace on the same tree resolves gtk4 0.11.4; `athanor-niri-ipc` stays a member of the main workspace and is used across the boundary as a path dependency without trouble.
- **Workspace change (Task 9, confirmed by the maintainer on 2026-09-19):** `athanor-shell-rs`, `athanor-dock`, `athanor-settings-rs`, `athanor-store-rs`, `athanor-daemon-rs` and `system/athanor-oobe` leave `[workspace.members]` and enter `exclude`; files stay. `system/athanor-greeter` stays a member and loses its dead optional `gtk` feature. Verified against the tree: the nine manifests spike P2 lists are exactly the ones that mention gtk4, relm4 or `athanor-style`; `athanor-style` is an implicit member (a path dependency inside the workspace root). The four unshipped crates that path-depend on the live `athanor-style` are built by nothing after this; that is what "retired" means here.
- **What is left of the bump: one line.** Versions from spike P2: gtk4 0.11.4, gtk4-layer-shell 0.8.1, glib 0.22.9, relm4 0.11.0. Measured on the scratch copy with the six crates out: `athanor-style` has its 1 known error (`glib::ObjectExt::downgrade(win)` → `win.downgrade()`), and **`athanor-recovery` has 0 errors** at relm4 0.11.0. It is bumped with `athanor-style`, not given a frozen workspace of its own, because a second frozen workspace would cost more than zero. `async-channel` is no longer needed: every removed `glib::MainContext::channel` was in the shell or the dock.
- **Lints.** The new crate never carries `#![allow(clippy::all, warnings)]` and is gated by `cargo clippy -- -D warnings` from its first commit. `athanor-style`'s three legacy modules (`accent_engine`, `appearance_engine`, `glass`), which only `athanor-recovery` still uses, get a module-level `#[allow]` so that the gate covers the crate's new code, `calmo`; they leave when recovery is re-skinned. The frozen shell keeps its crate-level allow: nobody edits it except to remove code.

### D5. The greeter, extracted and then re-skinned

- Two steps, two reviews: Task 11 **moves** the greeter as it is (same look, same strings, one `Some(...)`), so that the diff of the security-relevant code, `auth.rs` and `sandbox.rs`, is a move and little else; Task 16 **rewrites** `ui.rs` on the tokens.
- The greeter **reads nothing from COSMIC**: factory accent, variant from `ATHANOR_GREETER_VARIANT` (`light` default, `dark`, `light-hc`, `dark-hc`), and a real high-contrast toggle on the accessibility button. The old "🎨 Theme" button, which was connected to nothing, is deleted.
- Native widgets over hand-made ones: `gtk4::PasswordEntry` with `show-peek-icon` replaces the `Entry`, the reveal button, the Caps Lock pill and the key controller (GTK draws its own Caps Lock warning and exposes the right accessible role).
- Every interactive widget gets an accessible label through `update_property(&[Property::Label(..)])`; the AT-SPI check in the rig enforces it.
- The keyboard-layout chip shows `gdk::Device::layout_names()` of the seat keyboard (GTK 4.18 API, real data) and is hidden when the seat reports none; it is never a constant.
- The seal: `athanor-seal-attention-symbolic` and the words "Not verified", constant, with a comment and a changelog entry saying that 1b-shield replaces the constant with the state file.
- **gettext's format, our own reader (maintainer's decision, 2026-09-19).** Translations stay `.po`/`.mo`: that is the permanent asset, the one Weblate, Poedit and GTK itself use. Our programs do not read them through glibc. A small library crate, `system/athanor-i18n`, loads `.mo` catalogs in safe Rust with no dependency and gives `tr`, `tr_n` (plurals) and `tr_c` (context). Why: (1) no C FFI and no process-global `setlocale`/`textdomain` state in the process that handles the password; (2) glibc's gettext translates only when the system locale is installed, so it is silently English inside the greeter's bubblewrap sandbox or in a test container that lacks the locale; (3) it is toolkit-agnostic logic (SH4), which the notifier of 1b-system can use without GTK. Language: `LC_ALL`, `LC_MESSAGES`, `LANG` from the environment, else `LANG` of `/etc/locale.conf`, else English; catalog `/usr/share/locale/<lang>/LC_MESSAGES/<domain>.mo` with the `it_IT` → `it` fallback; `ATHANOR_I18N_CATALOG=<file.mo>` loads one file directly, which is how the rig's German and pseudo-RTL cases work. GTK's own strings keep going through the system's gettext, so the greeter session still has to export the locale (Task 15).
- **The crates.io crate `gettext` (the pure-Rust catalog parser, not `gettext-rs`) was checked and rejected:** version 0.4.0 of 2019-06-04 is the last release, the last commit is of 2021-09, eight issues are open; MIT; it parses both byte orders and evaluates arbitrary `Plural-Forms` expressions, but it depends on `encoding` 0.2.33 (2016), which RustSec lists as unmaintained (RUSTSEC-2021-0153) and which brings five multi-megabyte index crates for charsets we refuse anyway, and its plural evaluator computes `lhs % rhs` on catalog data, a division by zero, which under `panic = "abort"` is a dead greeter. Our reader was written and tested while revising this plan: 291 lines, 10 tests against real `msgfmt` output of both byte orders, UTF-8 only, every offset bounds-checked, and a **table** of plural rules (the languages we ship or test) instead of an expression evaluator.
- **Text direction comes from the catalog's language,** through a four-entry table (`ar`, `he`, `fa`, `ur`), and the greeter applies it with `gtk4::Widget::set_default_direction`. It no longer comes from a process locale, in production or in the rig; the pseudo-RTL test catalog declares `Language: ar`.
- Sandbox: `athanor-greeter-client` binds the whole of `/usr` read-only, and the Landlock policy restricts writes only. Fonts, icons, catalogs and the embedded CSS are all readable. The wrapper changes in two places only: the last line execs `/usr/bin/athanor-greeter-ui`, and the `theme.css` binds go, because the new program reads no such file. greetd hands the session only PAM's environment, so `LANG` is unset there today: `athanor-greeter-session` reads `/etc/locale.conf` (Task 15).
- The greeter's Landlock write set shrinks to what it uses: `/tmp`, `$XDG_RUNTIME_DIR`, and `WriteFile` beneath `/dev/dri`. The configuration and state directories were there for the shell's `theme.css` and notification history.

### D6. Assets

- **Inter:** Fedora package `rsms-inter-fonts` (verified in Fedora 43: `rsms-inter-fonts-4.1-2.fc43.noarch`, family name `Inter`, static weights including Light 300 and SemiBold 600). It is already in `upstream_desktop` of `forge/config/packages.json`; `athanor-calmo` adds `Requires: rsms-inter-fonts` so the dependency is declared where it is used. The mockup's weight 650 becomes 600, the nearest static weight.
- **Hearth wallpaper:** `generate.py wallpaper` renders PNG with the standard library (`zlib`, `struct`), 3840×2160, light and dark, in the RPM's `%build` (the builder has `python3`, not `librsvg`). No binary is committed. Installed as `/usr/share/backgrounds/athanor/hearth-light.png` and `hearth-dark.png`. cosmic-bg's default comes from the same overlay: `cosmic/com.system76.CosmicBackground/v1/{all,same-on-all}` pointing at the light image.
- **cosmic-bg cannot follow the mode.** `filter_by_theme` is an unimplemented TODO upstream and the shipped 1.8.0 binary contains the field name and no reference to `CosmicTheme.Mode`. Stage 1 therefore ships both images, defaults to the light one (the default mode is light), and the dark one is a choice in Settings → Wallpaper. See "Spec findings".
- **Seal icons:** four symbolic SVGs generated from the mockup's paths into `calmo/generated/icons/`: `athanor-mark-symbolic`, `athanor-seal-verified-symbolic`, `athanor-seal-attention-symbolic`, `athanor-seal-blocked-symbolic`. The badge disc carries the GTK symbolic class `success`, `warning` or `error`, recoloured through `-gtk-icon-palette` to the trust tokens; the glyph is cut out of the disc, so each state differs in shape as well as colour (SH12). Installed under `/usr/share/icons/hicolor/scalable/status/`.

### D7. Tests

- Unit tests: `system/athanor-style/calmo/tests/` (colour math, contrast, generator, wallpaper, icons), `forge/test/shell/tests/` (case matrix, golden comparison logic), `scripts/tests/` (the new `shipped` assertions).
- Rig: `forge/test/shell/` with `Containerfile` (targets `rig` and `build`), `rig.sh` (the single entry point), `scene.sh` (P3's scene, parameterised), `atspi_check.py`, `compare.py`, `cases.py`.
- Goldens live in `forge/test/shell/golden/<surface>/<case>.png`, committed. They are updated only by `forge/test/shell/rig.sh update-goldens <surface>`, which refuses to run with uncommitted changes under `golden/` and prints each replaced file; the commit that carries them says why they changed.
- The RTL pseudo-locale and German are test-only catalogs under `forge/test/shell/locale/`, compiled by the rig and mounted at `/usr/share/locale/{ar,de}/LC_MESSAGES/`; the product ships `it` and `en` only and carries no test hook.
- The rig starts the greeter binary directly, not through `athanor-greeter-client`: bubblewrap needs user namespaces the rootless container does not grant. Landlock still applies (it is in `main()`), and the wrapper keeps its own acceptance test on the ISO.

## File Structure

| Path | Responsibility |
|---|---|
| `system/athanor-style/calmo/tokens.toml` | Create. The single source: accent, fonts, radii, sizes, hearth geometry, four colour variants, contrast pairs. |
| `system/athanor-style/calmo/color.py` | Create. HSL→sRGB, compositing, WCAG luminance and contrast. |
| `system/athanor-style/calmo/tokens.py` | Create. Load the tokens, resolve a variant to concrete colours. |
| `system/athanor-style/calmo/contrast.py` | Create. The contrast gate (library and command). |
| `system/athanor-style/calmo/generate.py` | Create. Generators and `--check`. |
| `system/athanor-style/calmo/png.py` | Create. Minimal deterministic PNG writer. |
| `system/athanor-style/calmo/templates/surfaces.css.in` | Create. The rules of our surfaces, GTK4 properties only. |
| `system/athanor-style/calmo/generated/` | Create. Committed generator output: `css/`, `cosmic/`, `icons/`. |
| `system/athanor-style/calmo/tests/test_*.py` | Create. Unit tests of all of the above. |
| `system/athanor-style/src/calmo.rs` | Create. `Variant`, `css()`, `load()`; embeds the four CSS files. |
| `system/athanor-style/src/lib.rs` | Modify. Export `calmo`; drop the crate-level allow. |
| `forge/tools/calmo-cosmic-theme/{Cargo.toml,Cargo.lock,src/main.rs}` | Create. Standalone tool: Builder inputs → complete COSMIC defaults. |
| `forge/specs/athanor-calmo/athanor-calmo.spec` | Create. noarch package: overlay, `environment.d`, wallpapers, icons. |
| `forge/specs/athanor-calmo/SOURCES/usr/lib/environment.d/60-athanor-cosmic-defaults.conf` | Create. Puts the overlay first in `XDG_DATA_DIRS`. |
| `forge/config/packages.json` | Modify. Add `calmo` to `custom_packages` and `custom_tier2`. |
| `forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-session` | Modify. Export `XDG_DATA_DIRS` for the compositor. |
| `forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-greeter-session` | Modify. Export `LANG` from `/etc/locale.conf`. |
| `forge/specs/athanor-system-config/athanor-system-config.spec` | Modify. `Requires: athanor-calmo`, release bump, changelog. |
| `scripts/verify.py` | Modify. `shipped` asserts the overlay wiring. |
| `scripts/tests/test_verify_shipped.py` | Create. Tests of those assertions. |
| `Cargo.toml` | Modify. Members/exclude; GTK versions; `greetd_ipc`, `landlock` as workspace dependencies. |
| `forge/specs/athanor-shell-rs/Cargo.toml`, `Cargo.lock` | Create. The frozen GTK 0.7 workspace of the old shell. |
| `forge/specs/athanor-shell-rs/athanor-style-0.7/` | Create. Frozen copy of today's `system/athanor-style` sources, for the old shell and dock. |
| `forge/specs/athanor-shell-rs/athanor-shell-rs.spec`, `forge/specs/athanor-dock/athanor-dock-1.0.0/Cargo.toml` | Modify. Build from the frozen workspace. |
| `forge/specs/athanor-shell-rs/athanor-shell-rs-1.0.0/src/{main.rs,ui/mod.rs,sys/mod.rs}`, `src/ui/greeter/`, `src/sys/auth.rs` | Modify/Delete. The greeter is mined out of the old shell. |
| `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/Cargo.toml` | Create. The greeter's crate. |
| `…/athanor-greeter-ui-1.0.0/src/main.rs` | Create. Landlock first, tracing, Tokio runtime, the GTK application. |
| `…/src/ui.rs` | Create (moved in Task 11, rewritten in Task 16). The surface. |
| `…/src/auth.rs` | Create (moved). greetd IPC. |
| `…/src/sandbox.rs` | Create (moved, smaller write set). Landlock. |
| `…/src/power.rs` | Create. The three-method logind proxy. |
| `…/src/layer_guard.rs` | Create. The start-up layer-surface assertion. |
| `…/src/i18n.rs` | Create. The process's catalog; `tr`, `tr_with` for the surface. |
| `system/athanor-i18n/{Cargo.toml,src/lib.rs,tests/catalog.rs,tests/fixtures/*}` | Create. The `.mo` reader: `Catalog`, `PluralRule`, `languages`. |
| `…/po/{POTFILES.in,update.sh,athanor-greeter-ui.pot,it.po,en.po}` | Create. Catalogs. |
| `forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec` | Create. Binary, `%check` for `DT_NEEDED`, `.mo` files. |
| `forge/scripts/check_shim_link_order.py`, `forge/scripts/tests/test_check_shim_link_order.py` | Create. The `DT_NEEDED` contract. |
| `forge/specs/athanor-system-config/SOURCES/usr/libexec/athanor-greeter-client` | Modify. Exec the new binary; drop the `theme.css` binds. |
| `forge/test/iso/console.py` | Modify. The greeter-alive probe looks for `athanor-greeter`. |
| `forge/specs/athanor-recovery/athanor-recovery.spec` | Modify. Release and changelog only: the crate needs no source change. |
| `forge/test/shell/Containerfile` | Create. P3's image, maintained: targets `rig` and `build`. |
| `forge/test/shell/rig.sh` | Create. Entry point: `build-image`, `css-parse`, `build-greeter`, `surface`, `atspi`, `update-goldens`. |
| `forge/test/shell/scene.sh`, `sway.conf`, `session.sh` | Create. P3's scene, parameterised per case. |
| `forge/test/shell/css_parse_gate.py` | Create. GTK parse gate. |
| `forge/test/shell/atspi_check.py` | Create. Role-and-name check over the AT-SPI tree. |
| `forge/test/shell/cases.py`, `compare.py` | Create. The case matrix; pixel-count comparison. |
| `forge/test/shell/locale/{de.po,make_pseudo_rtl.py}` | Create. Test-only catalogs. |
| `forge/test/shell/golden/greeter/*.png` | Create. 12 goldens. |
| `forge/test/shell/tests/test_*.py` | Create. Unit tests of `cases.py` and `compare.py`. |
| `.github/workflows/shell-surfaces.yml` | Create. Thin workflow calling `rig.sh`. |
| `.github/workflows/call-lint.yml` | Modify. One step: Calmo unit tests, contrast gate, `generate.py --check`. |

## Task list

Part A, toolkit-independent and permanent:
1. Tokens and colour arithmetic
2. Contrast gate, wired into lint
3. GTK CSS generator with the drift check
4. Rig image and the GTK parse gate
5. Seal icons
6. Hearth wallpaper
7. Default `CosmicTheme` (Builder inputs, derive tool, committed output)
8. Package `athanor-calmo`, the overlay wiring and `verify.py shipped`

Part B, one crate per program:
9. Workspace membership (confirmed by the maintainer on 2026-09-19) and the frozen workspace of the old shell
10. Bump the workspace: `athanor-style` (one line) and `athanor-recovery` (none)
11. Extract the greeter into `athanor-greeter-ui`, package it, switch the image to it
12. Shim guards: `%check` and the start-up assertion
13. Lint gate: clippy `-D warnings` on the new crate and on `athanor-style`

Part C, the greeter on the tokens:
14. `athanor_style::calmo`
15. `athanor-i18n`, catalogs, `.mo` packaging, the greeter's locale
16. Greeter re-skin
17. AT-SPI check in the rig
18. The 12 surface cases, goldens and the workflow

---

# Part A: tokens, generator, gates

### Task 1: Tokens and colour arithmetic

**Files:**
- Create: `system/athanor-style/calmo/tokens.toml`
- Create: `system/athanor-style/calmo/color.py`
- Create: `system/athanor-style/calmo/tokens.py`
- Test: `system/athanor-style/calmo/tests/test_color.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `color.from_hex(text: str) -> tuple[float, float, float, float]`
  - `color.resolve(spec: str | dict, hue: float, saturation: float) -> tuple[float, float, float, float]`
  - `color.over(top: rgba, bottom: rgba) -> rgba` (source-over on an opaque bottom)
  - `color.to_hex(color) -> str`, `color.luminance(color) -> float`, `color.contrast(a, b) -> float`
  - `tokens.VARIANTS = ("light", "dark", "light-hc", "dark-hc")`
  - `tokens.load(path=HERE / "tokens.toml") -> dict`
  - `tokens.colors(tokens: dict, variant: str) -> dict[str, rgba]`
  - Token colour names (every variant): `bg1 bg2 d1 d2 d3 d4 surf surf2 bar line ink ink2 ink3 chip acc acc_ink acc_soft acc_soft_ink clock_ink shadow_near shadow_panel shadow_float ok ok_bg warn warn_bg bad bad_bg`.

Where the values come from: the `.light` and `.dark` blocks of the mockup's `<style>` (lines 7 to 24), name for name (`accInk` → `acc_ink`, `okB` → `ok_bg`, `wr` → `warn`, `shP`/`shW` split into their colour stops). High contrast is not in the mockup; the rule that derives it is written in the file.

- [ ] **Step 1: Write the failing test**

Create `system/athanor-style/calmo/tests/test_color.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import color
import tokens as tk


class ColorTest(unittest.TestCase):
    def test_hex_round_trip(self):
        self.assertEqual(color.to_hex(color.from_hex("#12805f")), "#12805f")

    def test_bad_hex_is_rejected(self):
        with self.assertRaises(ValueError):
            color.from_hex("#fff")

    def test_factory_accent_matches_the_mockup(self):
        # hsl(231 62% 47%) on light, hsl(231 87% 75%) on dark.
        self.assertEqual(color.to_hex(color.resolve({"s": "accent", "l": 47}, 231, 62)), "#2e44c2")
        self.assertEqual(color.to_hex(color.resolve({"s": "accent+25", "l": 75}, 231, 62)), "#8898f7")

    def test_accent_saturation_is_capped(self):
        self.assertEqual(color.resolve({"s": "accent+80", "l": 50}, 0, 62), color.resolve({"s": 100, "l": 50}, 0, 62))

    def test_hue_offset_and_alpha(self):
        r, g, b, a = color.resolve({"dh": -38, "s": 72, "l": 86, "a": 0.42}, 231, 62)
        self.assertEqual(a, 0.42)
        self.assertEqual(color.to_hex((r, g, b)), color.to_hex(color.resolve({"s": 72, "l": 86}, 193, 62)))

    def test_unknown_saturation_word_is_rejected(self):
        with self.assertRaises(ValueError):
            color.resolve({"s": "brand", "l": 50}, 231, 62)

    def test_contrast_extremes(self):
        black, white = color.from_hex("#000000"), color.from_hex("#ffffff")
        self.assertAlmostEqual(color.contrast(black, white), 21.0, places=6)
        self.assertAlmostEqual(color.contrast(white, white), 1.0, places=6)
        self.assertEqual(color.contrast(black, white), color.contrast(white, black))

    def test_known_ratio(self):
        # #767676 on white is the textbook 4.54:1.
        self.assertAlmostEqual(color.contrast(color.from_hex("#767676"), color.from_hex("#ffffff")), 4.54, places=2)

    def test_over_composites_towards_the_top_layer(self):
        half_black = (0.0, 0.0, 0.0, 0.5)
        self.assertEqual(color.to_hex(color.over(half_black, color.from_hex("#ffffff"))), "#808080")


class TokensTest(unittest.TestCase):
    def setUp(self):
        self.tokens = tk.load()

    def test_four_variants_resolve_to_the_same_names(self):
        names = [set(tk.colors(self.tokens, v)) for v in tk.VARIANTS]
        self.assertTrue(all(n == names[0] for n in names))

    def test_high_contrast_inherits_what_it_does_not_override(self):
        self.assertEqual(tk.colors(self.tokens, "light-hc")["surf"], tk.colors(self.tokens, "light")["surf"])
        self.assertNotEqual(tk.colors(self.tokens, "light-hc")["ink2"], tk.colors(self.tokens, "light")["ink2"])

    def test_trust_colours_do_not_follow_the_accent(self):
        moved = {**self.tokens, "accent": {"hue": 18, "saturation": 72}}
        for name in ("ok", "warn", "bad"):
            self.assertEqual(tk.colors(moved, "light")[name], tk.colors(self.tokens, "light")[name])
        self.assertNotEqual(tk.colors(moved, "light")["acc"], tk.colors(self.tokens, "light")["acc"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and see it fail**

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `ModuleNotFoundError: No module named 'color'`, exit status 1.

- [ ] **Step 3: Write `color.py`**

```python
"""Colour arithmetic for the Calmo tokens: HSL to sRGB, compositing, WCAG contrast."""
import colorsys


def from_hex(text):
    """'#rrggbb' -> (r, g, b, 1.0), channels in 0..1."""
    text = text.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"not a #rrggbb colour: {text!r}")
    return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1.0,)


def resolve(spec, hue, saturation):
    """A token colour (hex string or table) -> (r, g, b, a)."""
    if isinstance(spec, str):
        return from_hex(spec)
    alpha = float(spec.get("a", 1.0))
    if "hex" in spec:
        return from_hex(spec["hex"])[:3] + (alpha,)
    sat = spec["s"]
    if isinstance(sat, str):
        if not sat.startswith("accent"):
            raise ValueError(f"saturation must be a number or accent[+N]: {sat!r}")
        sat = min(100.0, saturation + float(sat[len("accent"):] or 0))
    h = (hue + spec.get("dh", 0)) % 360
    r, g, b = colorsys.hls_to_rgb(h / 360, spec["l"] / 100, sat / 100)
    return (r, g, b, alpha)


def over(top, bottom):
    """Source-over compositing of `top` on an opaque `bottom`."""
    a = top[3]
    return tuple(t * a + b * (1 - a) for t, b in zip(top[:3], bottom[:3])) + (1.0,)


def to_hex(color):
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in color[:3])


def luminance(color):
    def linear(u):
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(c) for c in color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG 2.1 contrast ratio of two opaque colours, 1.0 to 21.0."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
```

- [ ] **Step 4: Write `tokens.py`**

```python
"""Loads tokens.toml and resolves each variant to concrete colours."""
import tomllib
from pathlib import Path

from color import resolve

HERE = Path(__file__).resolve().parent
VARIANTS = ("light", "dark", "light-hc", "dark-hc")


def load(path=HERE / "tokens.toml"):
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def colors(tokens, variant):
    """{name: (r, g, b, a)} for one variant, with `inherits` applied."""
    section = tokens["variant"][variant]
    specs = {}
    if "inherits" in section:
        specs.update(tokens["variant"][section["inherits"]]["color"])
    specs.update(section.get("color", {}))
    accent = tokens["accent"]
    return {name: resolve(spec, accent["hue"], accent["saturation"]) for name, spec in specs.items()}
```

- [ ] **Step 5: Write `tokens.toml`**

```toml
# Calmo design tokens: the single source of the Athanor identity (doc_shell.md, SH5).
# Values are the ones of the approved mockup (interfaccia-athanor-v3). A colour is a hex
# string, or a table: { s, l } in HSL on the accent hue, with optional dh (hue offset in
# degrees), a (alpha), and s = "accent" / "accent+N" for the accent saturation.
schema = 1

[accent]
hue = 231
saturation = 62

[font]
family = "Inter"
features = '"tnum", "cv11"'

[radius]
control = 8
chip = 10
field = 11
card = 18
round = 9999

[size]
clock = 74
date = 14
title = 16
body = 13
small = 11.5

[hearth]
# Concentric discs rising from the bottom right corner. Centre in fractions of the
# image; radii in fractions of the distance from the centre to the farthest corner,
# which is how the mockup's CSS radial gradients measure them. Disc colours are d1..d4.
center = [0.80, 1.22]
radii = [0.22, 0.37, 0.54, 0.74]
gradient_angle = 165

[variant.light.color]
bg1 = { s = 42, l = 95 }
bg2 = { s = 44, l = 88 }
d1 = { s = 88, l = 76, a = 0.50 }
d2 = { s = 84, l = 80, a = 0.42 }
d3 = { s = 80, l = 84, a = 0.36 }
d4 = { dh = -38, s = 72, l = 86, a = 0.42 }
surf = { s = 40, l = 99.5 }
surf2 = { s = 36, l = 96.5 }
bar = { s = 40, l = 99 }
line = { s = 26, l = 87 }
ink = { s = 32, l = 15 }
ink2 = { s = 14, l = 40 }
ink3 = { s = 12, l = 58 }
chip = { s = 30, l = 93.5 }
acc = { s = "accent", l = 47 }
acc_ink = "#ffffff"
acc_soft = { s = "accent", l = 93 }
acc_soft_ink = { s = "accent", l = 32 }
clock_ink = { s = 40, l = 18 }
shadow_near = { s = 40, l = 20, a = 0.10 }
shadow_panel = { s = 40, l = 20, a = 0.08 }
shadow_float = { s = 50, l = 18, a = 0.22 }
ok = "#12805f"
ok_bg = "#dbf4ec"
warn = "#a36a00"
warn_bg = "#fdf0d2"
bad = "#b3261e"
bad_bg = "#fde1de"

[variant.dark.color]
bg1 = { s = 38, l = 10 }
bg2 = { s = 42, l = 5.5 }
d1 = { s = 70, l = 42, a = 0.50 }
d2 = { s = 66, l = 34, a = 0.42 }
d3 = { s = 60, l = 26, a = 0.38 }
d4 = { dh = -38, s = 60, l = 20, a = 0.45 }
surf = { s = 26, l = 14.5 }
surf2 = { s = 28, l = 11.5 }
bar = { s = 28, l = 15.5 }
line = { s = 22, l = 25 }
ink = { s = 40, l = 95 }
ink2 = { s = 18, l = 72 }
ink3 = { s = 14, l = 54 }
chip = { s = 24, l = 21 }
acc = { s = "accent+25", l = 75 }
acc_ink = { s = 50, l = 10 }
acc_soft = { s = 42, l = 26 }
acc_soft_ink = { s = 95, l = 90 }
clock_ink = { s = 60, l = 96 }
shadow_near = { hex = "#000000", a = 0.60 }
shadow_panel = { hex = "#000000", a = 0.40 }
shadow_float = { hex = "#000000", a = 0.73 }
ok = "#5fdcc0"
ok_bg = "#103d38"
warn = "#ffcf70"
warn_bg = "#4a3812"
bad = "#ffa79d"
bad_bg = "#4a1a17"

# High contrast is not in the mockup. It is derived by one rule: every secondary ink
# moves one step towards the primary ink, hairlines become visible boundaries, and the
# accent moves away from the surface. Trust colours stay fixed.
[variant.light-hc]
inherits = "light"
[variant.light-hc.color]
ink = { s = 32, l = 8 }
ink2 = { s = 20, l = 25 }
ink3 = { s = 14, l = 40 }
line = { s = 14, l = 45 }
acc = { s = "accent", l = 38 }
clock_ink = { s = 40, l = 10 }

[variant.dark-hc]
inherits = "dark"
[variant.dark-hc.color]
ink = { s = 40, l = 98 }
ink2 = { s = 18, l = 84 }
ink3 = { s = 18, l = 72 }
line = { s = 14, l = 54 }
acc = { s = "accent+25", l = 82 }
clock_ink = { s = 60, l = 99 }

# Every foreground/background pair a surface uses. kind: "text" needs 4.5:1, "large"
# (24 px and up, or 19 px bold) and "ui" (icons, badges, component boundaries) need
# 3:1 (WCAG 2.1 AA, 1.4.3 and 1.4.11). bg may be a list, composited bottom to top.
# only = [...] restricts a pair to the named variants.
[[pair]]
fg = "ink"
bg = ["surf", "surf2", "bar", "chip"]
each = true
kind = "text"
[[pair]]
fg = "ink2"
bg = ["surf", "surf2", "bar"]
each = true
kind = "text"
[[pair]]
fg = "ink3"
bg = ["surf", "surf2", "bar"]
each = true
kind = "ui"
[[pair]]
fg = "acc_ink"
bg = "acc"
kind = "text"
[[pair]]
fg = "acc_soft_ink"
bg = "acc_soft"
kind = "text"
[[pair]]
fg = "acc"
bg = ["surf", "surf2", "bar"]
each = true
kind = "ui"
[[pair]]
fg = "bad"
bg = ["surf", "bar"]
each = true
kind = "text"
[[pair]]
fg = "ok"
bg = "surf"
kind = "text"
[[pair]]
fg = "ok"
bg = ["bar", "ok_bg"]
each = true
kind = "ui"
[[pair]]
fg = "warn"
bg = ["bar", "surf", "warn_bg"]
each = true
kind = "ui"
[[pair]]
fg = "bad"
bg = "bad_bg"
kind = "ui"
[[pair]]
fg = "bar"
bg = ["ok", "warn", "bad"]
each = true
kind = "ui"
[[pair]]
fg = "clock_ink"
bg = ["bg1", "d4"]
kind = "large"
[[pair]]
fg = "clock_ink"
bg = ["bg2", "d4", "d3", "d2", "d1"]
kind = "large"
[[pair]]
fg = "ink"
bg = ["bg1", "d4"]
kind = "text"
[[pair]]
fg = "ink"
bg = ["bg2", "d4", "d3", "d2", "d1"]
kind = "text"
[[pair]]
fg = "line"
bg = ["surf", "bar"]
each = true
kind = "ui"
only = ["light-hc", "dark-hc"]
```

Two deliberate departures from the mockup, both forced by the contrast gate of Task 2 and both recorded under "Spec findings": the date under the clock uses `ink` instead of `ink2` (4.38:1 on the light wallpaper where three discs overlap), and `ink3` is declared for icons only (3.06:1 on `surf2`), so the password placeholder uses `ink2`.

- [ ] **Step 6: Run the test and see it pass**

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `Ran 12 tests` … `OK`.

- [ ] **Step 7: Commit**

```bash
git add system/athanor-style/calmo/tokens.toml system/athanor-style/calmo/color.py system/athanor-style/calmo/tokens.py system/athanor-style/calmo/tests/test_color.py
git commit -m "feat(calmo): add the design tokens and their colour arithmetic"
```

### Task 2: Contrast gate, wired into lint

**Files:**
- Create: `system/athanor-style/calmo/contrast.py`
- Test: `system/athanor-style/calmo/tests/test_contrast.py`
- Modify: `.github/workflows/call-lint.yml` (append one step after "Repository scripts (unit tests)")

**Interfaces:**
- Consumes: `tokens.load`, `tokens.colors`, `tokens.VARIANTS`, `color.contrast`, `color.over` (Task 1).
- Produces:
  - `contrast.THRESHOLD = {"text": 4.5, "large": 3.0, "ui": 3.0}`
  - `contrast.expand(pairs) -> iterator[dict]`
  - `contrast.check(tokens: dict) -> list[tuple[variant, fg, bg, kind, ratio, needed]]`
  - command `python3 -B system/athanor-style/calmo/contrast.py`, exit 1 when any pair fails.

- [ ] **Step 1: Write the failing test**

Create `system/athanor-style/calmo/tests/test_contrast.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import contrast
import tokens as tk

GREY = {"schema": 1, "accent": {"hue": 0, "saturation": 0},
        "variant": {v: {"color": {"fg": "#777777", "bg": "#ffffff", "veil": {"hex": "#000000", "a": 0.5}}}
                    for v in tk.VARIANTS}}


class ContrastTest(unittest.TestCase):
    def test_a_failing_text_pair_is_reported_in_every_variant(self):
        rows = contrast.check({**GREY, "pair": [{"fg": "fg", "bg": "bg", "kind": "text"}]})
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(ratio < needed for *_, ratio, needed in rows))

    def test_the_same_pair_passes_as_ui(self):
        rows = contrast.check({**GREY, "pair": [{"fg": "fg", "bg": "bg", "kind": "ui"}]})
        self.assertTrue(all(ratio >= needed for *_, ratio, needed in rows))

    def test_each_expands_to_one_pair_per_background(self):
        pairs = list(contrast.expand([{"fg": "fg", "bg": ["bg", "bg"], "each": True, "kind": "ui"}]))
        self.assertEqual([p["bg"] for p in pairs], ["bg", "bg"])

    def test_a_list_background_is_composited(self):
        rows = contrast.check({**GREY, "pair": [{"fg": "fg", "bg": ["bg", "veil"], "kind": "ui"}]})
        # #777 on white veiled by 50 % black (#808080) is almost no contrast at all.
        self.assertLess(rows[0][4], 1.2)

    def test_only_restricts_a_pair_to_the_named_variants(self):
        rows = contrast.check({**GREY, "pair": [{"fg": "fg", "bg": "bg", "kind": "ui", "only": ["dark"]}]})
        self.assertEqual([r[0] for r in rows], ["dark"])

    def test_a_translucent_bottom_layer_is_an_error(self):
        with self.assertRaises(ValueError):
            contrast.check({**GREY, "pair": [{"fg": "fg", "bg": ["veil", "bg"], "kind": "ui"}]})

    def test_the_shipped_tokens_pass(self):
        failing = [r for r in contrast.check(tk.load()) if r[4] < r[5]]
        self.assertEqual(failing, [])

    def test_high_contrast_never_lowers_a_ratio(self):
        rows = {(v, fg, str(bg)): ratio for v, fg, bg, _, ratio, _ in contrast.check(tk.load())}
        for (variant, fg, bg), ratio in rows.items():
            if variant.endswith("-hc") and (variant[:-3], fg, bg) in rows:
                self.assertGreaterEqual(ratio + 1e-9, rows[(variant[:-3], fg, bg)], (variant, fg, bg))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and see it fail**

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `ModuleNotFoundError: No module named 'contrast'`.

- [ ] **Step 3: Write `contrast.py`**

```python
"""WCAG AA gate over every declared pair of the tokens, in the four variants."""
import sys

import tokens as tk
from color import contrast, over

THRESHOLD = {"text": 4.5, "large": 3.0, "ui": 3.0}


def expand(pairs):
    """Pairs with each = true become one pair per background."""
    for pair in pairs:
        if pair.get("each"):
            for bg in pair["bg"]:
                yield {**pair, "bg": bg, "each": False}
        else:
            yield pair


def flatten(names, palette):
    """One name, or a bottom-to-top list of names, to an opaque colour."""
    names = [names] if isinstance(names, str) else names
    result = palette[names[0]]
    if result[3] != 1.0:
        raise ValueError(f"the bottom layer must be opaque: {names[0]}")
    for name in names[1:]:
        result = over(palette[name], result)
    return result


def check(tokens):
    """[(variant, fg, bg, kind, ratio, needed)] for every pair, failures included."""
    rows = []
    for variant in tk.VARIANTS:
        palette = tk.colors(tokens, variant)
        for pair in expand(tokens["pair"]):
            if "only" in pair and variant not in pair["only"]:
                continue
            bg = flatten(pair["bg"], palette)
            fg = over(palette[pair["fg"]], bg)
            rows.append((variant, pair["fg"], pair["bg"], pair["kind"], contrast(fg, bg), THRESHOLD[pair["kind"]]))
    return rows


def main():
    failures = 0
    for variant, fg, bg, kind, ratio, needed in check(tk.load()):
        ok = ratio >= needed
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {variant:9s} {fg:13s} on {str(bg):34s} {kind:5s} {ratio:5.2f} (needs {needed})")
    print(f"{failures} failing pair(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and the gate**

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `Ran 20 tests` … `OK`.

Run: `python3 -B system/athanor-style/calmo/contrast.py`
Expected: 132 lines starting with `ok`, then `0 failing pair(s)`, exit 0. The tightest pairs are `light ink3 on surf2 ui 3.06` and `light warn on warn_bg ui 4.02`.

- [ ] **Step 5: Add the lint step**

In `.github/workflows/call-lint.yml`, after the step named "Repository scripts (unit tests)", append:

```yaml
      - name: Calmo design tokens (unit tests, contrast gate)
        run: |
          set -euo pipefail
          python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v
          python3 -B system/athanor-style/calmo/contrast.py
```

- [ ] **Step 6: Validate the workflow locally**

Run: `actionlint .github/workflows/call-lint.yml && python3 scripts/verify.py workflows`
Expected: no output from actionlint; `verify.py` reports the `workflows` check green.

- [ ] **Step 7: Commit**

```bash
git add system/athanor-style/calmo/contrast.py system/athanor-style/calmo/tests/test_contrast.py .github/workflows/call-lint.yml
git commit -m "feat(calmo): gate every token pair on WCAG AA in the four variants"
```

### Task 3: GTK CSS generator with the drift check

This task creates the whole of `generate.py`, `png.py` and the template in one go, because `--check` compares every generated file and a half-written generator cannot pass it. Tasks 5, 6 and 7 add the tests and the packaging of the icon, wallpaper and COSMIC parts; this task tests and commits the CSS part and the drift check.

**Files:**
- Create: `system/athanor-style/calmo/generate.py`
- Create: `system/athanor-style/calmo/png.py`
- Create: `system/athanor-style/calmo/templates/surfaces.css.in`
- Create (generated, committed): `system/athanor-style/calmo/generated/css/calmo-{light,dark,light-hc,dark-hc}.css`
- Test: `system/athanor-style/calmo/tests/test_generate.py` (classes `CssTest` and `CheckTest` here; the others arrive in Tasks 5 to 7)
- Modify: `.github/workflows/call-lint.yml` (one line in the step of Task 2)

**Interfaces:**
- Consumes: `tokens.load`, `tokens.colors`, `tokens.VARIANTS`, `color.over`, `color.to_hex`.
- Produces:
  - `generate.css(tokens: dict, variant: str) -> str`
  - `generate.cosmic_inputs(tokens) -> str` (JSON), `generate.cosmic_background() -> dict[str, str]`
  - `generate.icons() -> dict[str, str]` (file name → SVG)
  - `generate.hearth_rows(tokens, variant, width, height, block=16) -> iterator[bytes]`, `generate.wallpaper(tokens, variant, width, height) -> bytes`
  - `generate.generated_files(tokens) -> dict[str, str]`, `generate.check(tokens, out=OUT) -> list[str]`
  - `png.encode(width: int, height: int, rows) -> bytes`
  - commands: `generate.py css|cosmic|icons|all`, `generate.py --check`, `generate.py wallpaper <variant> <w> <h> <out.png>`
  - CSS classes later tasks use: `athanor-surface`, `athanor-greeter` (on the window), `greeter-wordmark`, `greeter-clock`, `greeter-date`, `greeter-card`, `greeter-avatar`, `greeter-name`, `greeter-field`, `greeter-submit`, `greeter-status`, `greeter-error`, `greeter-chip`, `athanor-seal`; named colours `ath_<token>`.

- [ ] **Step 1: Write the failing tests**

Create `system/athanor-style/calmo/tests/test_generate.py` with the imports, `WEB_ONLY`, `CssTest` and `CheckTest` below (the complete file, as it stands after Task 7, is this one; Tasks 5 to 7 name the classes they add):

```python
import hashlib
import json
import re
import struct
import sys
import tempfile
import unittest
import xml.dom.minidom
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generate
import tokens as tk

# Properties GTK4 does not implement; the old stylesheet used every one of them.
WEB_ONLY = ("backdrop-filter", "!important", ":root", "var(--", "transform:", "cursor:")


class CssTest(unittest.TestCase):
    def setUp(self):
        self.tokens = tk.load()

    def test_every_variant_defines_every_colour_the_rules_use(self):
        for variant in tk.VARIANTS:
            text = generate.css(self.tokens, variant)
            defined = set(re.findall(r"@define-color (ath_\w+)", text))
            used = set(re.findall(r"@(ath_\w+)", text.split("\n\n", 1)[1]))
            self.assertEqual(used - defined, set(), variant)

    def test_no_placeholder_survives(self):
        self.assertNotIn("$", generate.css(self.tokens, "light"))

    def test_no_web_only_construct(self):
        text = generate.css(self.tokens, "dark")
        for construct in WEB_ONLY:
            self.assertNotIn(construct, text)

    def test_no_animation(self):
        text = generate.css(self.tokens, "light")
        self.assertNotRegex(text, r"\b(transition|animation)[a-z-]*\s*:")

    def test_the_accent_is_the_factory_accent(self):
        self.assertIn("@define-color ath_acc #2e44c2;", generate.css(self.tokens, "light"))
        self.assertIn("@define-color ath_acc #8898f7;", generate.css(self.tokens, "dark"))

    def test_translucent_colours_keep_their_alpha(self):
        self.assertRegex(generate.css(self.tokens, "light"), r"@define-color ath_d1 rgba\(\d+, \d+, \d+, 0\.5\);")


class CosmicTest(unittest.TestCase):
    def test_inputs_are_the_five_builder_keys_per_mode(self):
        inputs = json.loads(generate.cosmic_inputs(tk.load()))
        self.assertEqual(set(inputs), {"light", "dark"})
        for mode in inputs.values():
            self.assertEqual(set(mode), {"accent", "bg_color", "primary_container_bg", "neutral_tint", "text_tint"})
            self.assertTrue(all(len(v) == 3 and all(0 <= c <= 1 for c in v) for v in mode.values()))

    def test_background_points_at_the_shipped_wallpaper(self):
        self.assertIn('Path("/usr/share/backgrounds/athanor/hearth-light.png")', generate.cosmic_background()["all"])


class IconsTest(unittest.TestCase):
    def test_four_well_formed_symbolic_icons(self):
        files = generate.icons()
        self.assertEqual(sorted(files), ["athanor-mark-symbolic.svg", "athanor-seal-attention-symbolic.svg",
                                         "athanor-seal-blocked-symbolic.svg", "athanor-seal-verified-symbolic.svg"])
        for text in files.values():
            xml.dom.minidom.parseString(text)

    def test_icons_are_fill_only(self):
        # GTK recolours symbolic icons by forcing `fill`; a stroked path would be filled in.
        for text in generate.icons().values():
            self.assertNotIn("stroke", text)

    def test_each_state_has_its_own_class_and_its_own_shape(self):
        files = generate.icons()
        badges = {}
        for state, css_class in (("verified", "success"), ("attention", "warning"), ("blocked", "error")):
            text = files[f"athanor-seal-{state}-symbolic.svg"]
            self.assertEqual(re.findall(r'class="(\w+)"', text), [css_class])
            badges[state] = re.search(r'class="\w+"[^>]* d="([^"]+)"', text).group(1)
        self.assertEqual(len(set(badges.values())), 3)

    def test_the_mark_alone_has_no_badge(self):
        self.assertNotIn("class=", generate.icons()["athanor-mark-symbolic.svg"])


class WallpaperTest(unittest.TestCase):
    def setUp(self):
        self.tokens = tk.load()

    def decode(self, data):
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        raw = zlib.decompress(idat)
        stride = width * 3 + 1
        return width, height, [raw[y * stride + 1:(y + 1) * stride] for y in range(height)]

    def test_size_and_determinism(self):
        first = generate.wallpaper(self.tokens, "light", 64, 36)
        self.assertEqual(first, generate.wallpaper(self.tokens, "light", 64, 36))
        width, height, rows = self.decode(first)
        self.assertEqual((width, height, len(rows)), (64, 36, 36))

    def test_the_discs_rise_from_the_bottom_right(self):
        _, _, rows = self.decode(generate.wallpaper(self.tokens, "light", 160, 90))
        top_left, bottom_right = rows[0][0:3], rows[89][-3:]
        self.assertNotEqual(top_left, bottom_right)
        # Light variant: the corner under four discs is more saturated, so its red drops.
        self.assertLess(bottom_right[0], top_left[0])

    def test_light_and_dark_differ(self):
        self.assertNotEqual(generate.wallpaper(self.tokens, "light", 32, 18), generate.wallpaper(self.tokens, "dark", 32, 18))

    def test_block_fill_matches_the_exact_render_within_one_level(self):
        rows = list(generate.hearth_rows(self.tokens, "dark", 96, 54))
        exact = list(generate.hearth_rows(self.tokens, "dark", 96, 54, block=1))
        worst = max(abs(a - b) for fast, slow in zip(rows, exact) for a, b in zip(fast, slow))
        self.assertLessEqual(worst, 1)


class CheckTest(unittest.TestCase):
    def test_check_reports_drift_and_a_stale_cosmic_stamp(self):
        tokens = tk.load()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for name, text in generate.generated_files(tokens).items():
                (out / name).parent.mkdir(parents=True, exist_ok=True)
                (out / name).write_text(text, encoding="utf-8")
            (out / "cosmic").mkdir()
            (out / "cosmic" / "STAMP").write_text(hashlib.sha256(generate.cosmic_inputs(tokens).encode()).hexdigest() + "\n")
            self.assertEqual(generate.check(tokens, out), [])

            (out / "css" / "calmo-light.css").write_text("edited by hand")
            (out / "cosmic" / "STAMP").write_text("0" * 64 + "\n")
            problems = generate.check(tokens, out)
            self.assertEqual(len(problems), 2)
            self.assertTrue(problems[0].startswith("css/calmo-light.css"))
            self.assertTrue(problems[1].startswith("cosmic/"))


if __name__ == "__main__":
    unittest.main()
```

For this task keep only `CssTest` and `CheckTest`; leave `CosmicTest`, `IconsTest` and `WallpaperTest` out until their tasks.

- [ ] **Step 2: Run and see it fail**

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `ModuleNotFoundError: No module named 'generate'`.

- [ ] **Step 3: Write the template**

Create `system/athanor-style/calmo/templates/surfaces.css.in`. Every construct in it was parsed by GTK 4.20.4 with zero reports while this plan was written:

```css
/* Rules of the Athanor surfaces. GTK4 properties only: the parse gate rejects the rest.
 * Nothing here moves, so nothing needs a reduced-motion path. */

window.athanor-surface {
    font-family: "$font_family";
    font-feature-settings: $font_features;
    font-size: ${size_body}px;
    color: @ath_ink;
}

window.athanor-surface *:focus-visible {
    outline: 2px solid @ath_acc;
    outline-offset: 2px;
}

/* The hearth: concentric discs rising from the bottom right corner. */
window.athanor-greeter {
    background-image:
        radial-gradient(circle at $hearth_x% $hearth_y%, @ath_d1 0%, @ath_d1 $hearth_r1%, transparent $hearth_e1%),
        radial-gradient(circle at $hearth_x% $hearth_y%, @ath_d2 0%, @ath_d2 $hearth_r2%, transparent $hearth_e2%),
        radial-gradient(circle at $hearth_x% $hearth_y%, @ath_d3 0%, @ath_d3 $hearth_r3%, transparent $hearth_e3%),
        radial-gradient(circle at $hearth_x% $hearth_y%, @ath_d4 0%, @ath_d4 $hearth_r4%, transparent $hearth_e4%),
        linear-gradient(${hearth_angle}deg, @ath_bg1, @ath_bg2);
}

.greeter-wordmark {
    font-size: ${size_date}px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: @ath_ink;
}

.greeter-clock {
    font-size: ${size_clock}px;
    font-weight: 300;
    letter-spacing: -0.035em;
    line-height: 1;
    color: @ath_clock_ink;
}

.greeter-date {
    font-size: ${size_date}px;
    font-weight: 500;
    color: @ath_ink;
}

.greeter-card {
    background-color: @ath_surf;
    border: 1px solid @ath_line;
    border-radius: ${radius_card}px;
    box-shadow: 0 2px 6px @ath_shadow_near, 0 24px 60px @ath_shadow_float;
    padding: 22px 22px 18px 22px;
    min-width: 276px;
}

.greeter-avatar {
    min-width: 60px;
    min-height: 60px;
    border-radius: ${radius_round}px;
    background-color: @ath_acc;
    color: @ath_acc_ink;
    font-size: 24px;
    font-weight: 600;
}

.greeter-name {
    font-size: ${size_title}px;
    font-weight: 600;
}

.greeter-field {
    min-height: 40px;
    border-radius: ${radius_field}px;
    background-color: @ath_surf2;
    border: 1.5px solid @ath_acc;
    color: @ath_ink;
    caret-color: @ath_acc;
    padding: 0 5px 0 12px;
    box-shadow: none;
    outline: none;
}

.greeter-field image {
    color: @ath_ink3;
}

.greeter-submit {
    min-width: 30px;
    min-height: 30px;
    padding: 0;
    border: none;
    border-radius: ${radius_control}px;
    background-image: none;
    background-color: @ath_acc;
    color: @ath_acc_ink;
    box-shadow: none;
}

.greeter-submit:disabled {
    background-color: @ath_chip;
    color: @ath_ink2;
}

.greeter-status {
    font-size: ${size_small}px;
    font-weight: 500;
    color: @ath_ink2;
}

.greeter-error {
    font-size: ${size_small}px;
    font-weight: 600;
    color: @ath_bad;
}

/* The chips in the corners: the seal, the keyboard layout, accessibility, power. */
.greeter-chip {
    min-height: 34px;
    min-width: 34px;
    padding: 0 10px;
    border: 1px solid @ath_line;
    border-radius: ${radius_chip}px;
    background-image: none;
    background-color: @ath_bar;
    color: @ath_ink;
    box-shadow: 0 1px 2px @ath_shadow_near, 0 6px 18px @ath_shadow_panel;
    font-size: ${size_small}px;
    font-weight: 600;
}

button.greeter-chip:hover,
button.greeter-chip:checked {
    background-color: @ath_chip;
}

/* The seal: the mark in the ink colour, the badge in the fixed trust colours. */
.athanor-seal {
    -gtk-icon-size: 22px;
    -gtk-icon-palette: success @ath_ok, warning @ath_warn, error @ath_bad;
    color: @ath_ink;
}
```

- [ ] **Step 4: Write `png.py`**

```python
"""A deterministic 8-bit RGB PNG writer: no timestamps, fixed compression level."""
import struct
import zlib


def _chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def encode(width, height, rows):
    """`rows` yields `height` byte strings of `width * 3` bytes each."""
    raw = bytearray()
    count = 0
    for row in rows:
        if len(row) != width * 3:
            raise ValueError(f"row {count} has {len(row)} bytes, expected {width * 3}")
        raw += b"\x00" + row
        count += 1
    if count != height:
        raise ValueError(f"{count} rows, expected {height}")
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b""))
```

- [ ] **Step 5: Write `generate.py`**

```python
#!/usr/bin/env python3
"""Generates everything the Calmo tokens drive.

    generate.py css | cosmic | icons | all     write calmo/generated/
    generate.py --check                        fail when generated/ differs from the tokens
    generate.py wallpaper <variant> <w> <h> <out.png>

The wallpaper is rendered at package build time and is not committed.
"""
import hashlib
import json
import math
import string
import sys
from pathlib import Path

import png
import tokens as tk
from color import over, to_hex

HERE = Path(__file__).resolve().parent
OUT = HERE / "generated"
HEADER = "/* Generated by system/athanor-style/calmo/generate.py from tokens.toml. Do not edit. */\n"


# ---------------------------------------------------------------- GTK CSS

def _css_color(color):
    r, g, b = (round(c * 255) for c in color[:3])
    if color[3] == 1.0:
        return "#%02x%02x%02x" % (r, g, b)
    return f"rgba({r}, {g}, {b}, {color[3]:g})"


def _num(value):
    return f"{value:g}"


def template_values(tokens):
    hearth = tokens["hearth"]
    values = {"font_family": tokens["font"]["family"], "font_features": tokens["font"]["features"],
              "hearth_x": _num(hearth["center"][0] * 100), "hearth_y": _num(hearth["center"][1] * 100),
              "hearth_angle": _num(hearth["gradient_angle"])}
    for index, radius in enumerate(hearth["radii"], 1):
        values[f"hearth_r{index}"] = _num(radius * 100)
        # A 0.12 % ramp, as in the mockup, is the anti-aliased edge of the disc.
        values[f"hearth_e{index}"] = _num(round(radius * 100 + 0.12, 2))
    values.update({f"radius_{k}": _num(v) for k, v in tokens["radius"].items()})
    values.update({f"size_{k}": _num(v) for k, v in tokens["size"].items()})
    return values


def css(tokens, variant):
    palette = tk.colors(tokens, variant)
    lines = [HEADER, f"/* Variant: {variant} */\n"]
    lines += [f"@define-color ath_{name} {_css_color(palette[name])};\n" for name in sorted(palette)]
    template = string.Template((HERE / "templates" / "surfaces.css.in").read_text(encoding="utf-8"))
    return "".join(lines) + "\n" + template.substitute(template_values(tokens))


# ---------------------------------------------------------------- COSMIC inputs

# Builder input <- token. Semantics read in cosmic-theme's ThemeBuilder::build().
COSMIC_INPUTS = {"accent": "acc", "bg_color": "surf2", "primary_container_bg": "surf",
                 "neutral_tint": "ink3", "text_tint": "ink"}


def cosmic_inputs(tokens):
    modes = {}
    for mode in ("light", "dark"):
        palette = tk.colors(tokens, mode)
        modes[mode] = {key: [round(c, 6) for c in palette[name][:3]] for key, name in COSMIC_INPUTS.items()}
    return json.dumps(modes, indent=2, sort_keys=True) + "\n"


def cosmic_background():
    """cosmic-bg's two default keys, in RON."""
    entry = ('(\n    output: "all",\n    source: Path("/usr/share/backgrounds/athanor/hearth-light.png"),\n'
             "    filter_by_theme: false,\n    rotation_frequency: 3600,\n    filter_method: Lanczos,\n"
             "    scaling_mode: Zoom,\n    sampling_method: Alphanumeric,\n)\n")
    return {"all": entry, "same-on-all": "true\n"}


# ---------------------------------------------------------------- seal icons

MARK = ('<path fill-rule="evenodd" d="M12 1.6a10.4 10.4 0 1 0 0 20.8a10.4 10.4 0 1 0 0-20.8z'
        'M12 3.4a8.6 8.6 0 1 1 0 17.2a8.6 8.6 0 1 1 0-17.2z"/>'
        '<path d="M12 6.2c2.3 2.7 3.8 4.6 3.8 6.9a3.8 3.8 0 0 1-7.6 0c0-2.3 1.5-4.2 3.8-6.9z"/>')
BADGE_CENTER, BADGE_RADIUS = (17.5, 17.5), 6.5


def _polygon(points):
    cx, cy = BADGE_CENTER
    return "M" + "L".join(f"{_num(round(cx + x, 3))} {_num(round(cy + y, 3))}" for x, y in points) + "z"


def _check_glyph(width=1.7):
    """The outline of a two-segment stroke with a mitred elbow, as one polygon."""
    a, b, c = (-3.2, 0.2), (-1.0, 2.4), (3.3, -2.3)

    def normal(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy)
        return (-dy / length * width / 2, dx / length * width / 2)

    n1, n2 = normal(a, b), normal(b, c)

    def miter(sign):
        # Intersection of the two offset lines on one side of the elbow.
        p = (a[0] + sign * n1[0], a[1] + sign * n1[1])
        q = (c[0] + sign * n2[0], c[1] + sign * n2[1])
        d1, d2 = (b[0] - a[0], b[1] - a[1]), (b[0] - c[0], b[1] - c[1])
        t = ((q[0] - p[0]) * d2[1] - (q[1] - p[1]) * d2[0]) / (d1[0] * d2[1] - d1[1] * d2[0])
        return (p[0] + t * d1[0], p[1] + t * d1[1])

    return [(a[0] + n1[0], a[1] + n1[1]), miter(1), (c[0] + n2[0], c[1] + n2[1]),
            (c[0] - n2[0], c[1] - n2[1]), miter(-1), (a[0] - n1[0], a[1] - n1[1])]


def _cross_glyph(half=0.85, arm=3.3):
    plus = [(-half, -arm), (half, -arm), (half, -half), (arm, -half), (arm, half), (half, half),
            (half, arm), (-half, arm), (-half, half), (-arm, half), (-arm, -half), (-half, -half)]
    k = math.sqrt(0.5)
    return [((x - y) * k, (x + y) * k) for x, y in plus]


def _bang_glyphs():
    return [[(-0.9, -3.7), (0.9, -3.7), (0.9, 1.0), (-0.9, 1.0)],
            [(-0.9, 2.1), (0.9, 2.1), (0.9, 3.7), (-0.9, 3.7)]]


# state -> (GTK symbolic class, glyph polygons). Three shapes, three colours (SH12).
SEALS = {"verified": ("success", [_check_glyph()]), "attention": ("warning", _bang_glyphs()),
         "blocked": ("error", [_cross_glyph()])}


def _svg(body):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!-- Generated by calmo/generate.py. Do not edit. -->\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">{body}</svg>\n')


def icons():
    cx, cy = BADGE_CENTER
    r = BADGE_RADIUS
    disc = f"M{_num(cx - r)} {_num(cy)}a{_num(r)} {_num(r)} 0 1 0 {_num(2 * r)} 0a{_num(r)} {_num(r)} 0 1 0 {_num(-2 * r)} 0z"
    files = {"athanor-mark-symbolic.svg": _svg(MARK)}
    for state, (css_class, glyphs) in SEALS.items():
        badge = f'<path class="{css_class}" fill-rule="evenodd" d="{disc}{"".join(_polygon(g) for g in glyphs)}"/>'
        files[f"athanor-seal-{state}-symbolic.svg"] = _svg(MARK + badge)
    return files


# ---------------------------------------------------------------- hearth wallpaper

def hearth_rows(tokens, variant, width, height, block=16):
    """Rows of RGB bytes. Exact at every disc edge, constant over runs of at most `block`
    pixels elsewhere: at 3840 px the gradient moves by under 0.03 of an 8-bit level in 16
    pixels, and a 4K frame renders in 2.5 s instead of minutes."""
    palette = tk.colors(tokens, variant)
    hearth = tokens["hearth"]
    cx, cy = hearth["center"][0] * width, hearth["center"][1] * height
    reach = max(math.hypot(cx - x, cy - y) for x in (0, width) for y in (0, height))
    discs = [(palette[f"d{i}"], r * reach) for i, r in reversed(list(enumerate(hearth["radii"], 1)))]
    angle = math.radians(hearth["gradient_angle"])
    ax, ay = math.sin(angle), -math.cos(angle)
    length = abs(width * ax) + abs(height * ay)
    bg1, bg2 = palette["bg1"], palette["bg2"]

    def pixel(x, y):
        t = min(1.0, max(0.0, ((x + 0.5 - width / 2) * ax + (y + 0.5 - height / 2) * ay) / length + 0.5))
        color = tuple(p + (q - p) * t for p, q in zip(bg1[:3], bg2[:3])) + (1.0,)
        distance = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
        for disc, radius in discs:
            coverage = min(1.0, max(0.0, radius - distance + 0.5))
            if coverage:
                color = over(disc[:3] + (disc[3] * coverage,), color)
        return bytes(round(c * 255) for c in color[:3])

    for y in range(height):
        edges = set()
        for _, radius in discs:
            dy = y + 0.5 - cy
            if abs(dy) < radius + 1:
                half = math.sqrt(max(0.0, (radius + 1) ** 2 - dy * dy))
                inner = math.sqrt(max(0.0, (radius - 1) ** 2 - dy * dy)) if abs(dy) < radius - 1 else 0.0
                for lo, hi in ((cx - half, cx - inner), (cx + inner, cx + half)):
                    edges.update(range(max(0, int(lo) - 1), min(width, int(hi) + 2)))
        row = bytearray()
        x = 0
        while x < width:
            if x in edges:
                row += pixel(x, y)
                x += 1
                continue
            end = min(width, (x // block + 1) * block)
            stop = x + 1
            while stop < end and stop not in edges:
                stop += 1
            row += pixel((x + stop - 1) // 2, y) * (stop - x)
            x = stop
        yield bytes(row)


def wallpaper(tokens, variant, width, height):
    return png.encode(width, height, hearth_rows(tokens, variant, width, height))


# ---------------------------------------------------------------- files and --check

def generated_files(tokens):
    """{path relative to generated/: text}. Everything committed; not the wallpaper and
    not generated/cosmic/, which COSMIC's own code derives (forge/tools/calmo-cosmic-theme)."""
    files = {f"css/calmo-{v}.css": css(tokens, v) for v in tk.VARIANTS}
    files["cosmic-inputs.json"] = cosmic_inputs(tokens)
    files.update({f"cosmic-bg/com.system76.CosmicBackground/v1/{k}": v for k, v in cosmic_background().items()})
    files.update({f"icons/{name}": text for name, text in icons().items()})
    return files


def check(tokens, out=OUT):
    problems = []
    for name, text in generated_files(tokens).items():
        path = out / name
        if not path.exists():
            problems.append(f"{name}: missing, run generate.py all")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"{name}: differs from the tokens, run generate.py all")
    stamp = out / "cosmic" / "STAMP"
    wanted = hashlib.sha256(cosmic_inputs(tokens).encode()).hexdigest()
    if not stamp.exists():
        problems.append("cosmic/STAMP: missing, run forge/tools/calmo-cosmic-theme/derive.sh")
    elif stamp.read_text(encoding="utf-8").strip() != wanted:
        problems.append("cosmic/: derived from other inputs, run forge/tools/calmo-cosmic-theme/derive.sh")
    return problems


def main(argv):
    tokens = tk.load()
    if argv == ["--check"]:
        problems = check(tokens)
        print("\n".join(problems) if problems else "generated/ matches tokens.toml")
        return 1 if problems else 0
    if len(argv) == 5 and argv[0] == "wallpaper":
        Path(argv[4]).write_bytes(wallpaper(tokens, argv[1], int(argv[2]), int(argv[3])))
        return 0
    prefixes = {"css": ("css/",), "cosmic": ("cosmic-inputs.json", "cosmic-bg/"), "icons": ("icons/",),
                "all": ("",)}
    if len(argv) != 1 or argv[0] not in prefixes:
        print(__doc__)
        return 2
    for name, text in generated_files(tokens).items():
        if name.startswith(prefixes[argv[0]]):
            path = OUT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 6: Generate and run the tests**

Run: `python3 -B system/athanor-style/calmo/generate.py all`
Expected: eleven `wrote generated/...` lines (four CSS files, `cosmic-inputs.json`, two `cosmic-bg` keys, four icons).

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `OK` (27 tests with the two classes of this task).

Run: `python3 -B system/athanor-style/calmo/generate.py --check`
Expected at this point: exactly one line, `cosmic/STAMP: missing, run forge/tools/calmo-cosmic-theme/derive.sh`, exit 1. Task 7 produces the stamp. Until then CI calls the check through the unit test `CheckTest`, not through the command.

- [ ] **Step 7: Commit the CSS part**

```bash
git add system/athanor-style/calmo/generate.py system/athanor-style/calmo/png.py system/athanor-style/calmo/templates/surfaces.css.in system/athanor-style/calmo/generated/css system/athanor-style/calmo/tests/test_generate.py
git commit -m "feat(calmo): generate the GTK4 stylesheets of the four variants from the tokens"
```

The icons, `cosmic-inputs.json` and `cosmic-bg/` that `generate.py all` also wrote stay uncommitted until Tasks 5 and 7 (`git status` shows them as untracked; that is expected).

### Task 4: Rig image and the GTK parse gate

The rig is spike P3's recipe (`.superpowers/spike-p3-headless.md`, section 10) as maintained files. Three things change against the spike, each measured while this plan was written: (1) `weston`, `cosmic-screenshot`, the Vulkan loader and the portal packages are dropped, as P3 recommends; (2) `cosmic-settings` is added, because without it the image has no `com.system76.CosmicTheme.*` defaults at all and COSMIC silently uses its compiled-in dark theme; (3) every `podman run` carries `--security-opt label=disable`: GTK 4.20 decodes SVG icons through glycin, whose loaders run in bubblewrap, and under SELinux's `container_t` bubblewrap dies on `Can't mount devpts on /dev/pts: Permission denied`, after which every icon is drawn blank **with no error anywhere**. The option is a no-op on the hosted Ubuntu runner, which has no SELinux; Step 1 proves the nested sandbox there.

**Files:**
- Create: `forge/test/shell/Containerfile`
- Create: `forge/test/shell/rig.sh`
- Create: `forge/test/shell/scene.sh`, `forge/test/shell/sway.conf`, `forge/test/shell/session.sh`
- Create: `forge/test/shell/css_parse_gate.py`
- Create: `.github/workflows/shell-surfaces.yml`

**Interfaces:**
- Consumes: `system/athanor-style/calmo/generated/css/*.css` (Task 3).
- Produces:
  - `forge/test/shell/rig.sh <sub-command>`; this task defines `build-image`, `publish-image`, `probe-sandbox`, `css-parse`. Environment: `ATHANOR_RIG_IMAGE` (explicit image), `ATHANOR_REGISTRY` (default `ghcr.io/hr-mes`), `ATHANOR_RIG_OUT` (default `.scratch/shell-rig`).
  - Inside the container: the repository read-only at `/repo`, the output directory at `/out`.
  - `scene.sh <width> <height> <scale> <tag> -- <client command…>`, with `RIG_PANEL=1` (start cosmic-panel), `RIG_LOCALE` (default `C.UTF-8`), `RIG_DATA_OVERLAY` (a directory put first in `XDG_DATA_DIRS`), `RIG_CONFIG_SEED` (a directory copied into the fresh `XDG_CONFIG_HOME`), `RIG_HOLD=<command>` (run after the settle time, before the capture). Writes `/out/<tag>.png`.
  - `css_parse_gate.py [--self-test] <file.css>…`, exit 1 on any GTK parsing report.

- [ ] **Step 1: Write the Containerfile**

Create `forge/test/shell/Containerfile`:

```dockerfile
# The shell test rig: a headless sway on pixman, cosmic-comp nested in it on llvmpipe,
# grim over ext-image-copy-capture-v1. Spike P3, maintained. Rootless, no GPU, no device.
# The base is pinned by digest; the published rig image is pinned by digest as well
# (rig-image.digest), because fonts, Mesa, GTK and COSMIC all move pixels.
FROM registry.fedoraproject.org/fedora@sha256:0b52d7c65426cdb567000481d0d1b056040b4d80c1a479bc967383c41aae5809 AS rig

RUN dnf5 -y install --setopt=install_weak_deps=False \
      cosmic-comp cosmic-panel cosmic-applets cosmic-settings cosmic-settings-daemon \
      cosmic-randr cosmic-bg cosmic-icon-theme adwaita-icon-theme hicolor-icon-theme \
      mesa-dri-drivers mesa-libEGL mesa-libGL mesa-libgbm libxkbcommon \
      sway grim wayland-utils ImageMagick libfaketime \
      dbus-daemon dbus-tools at-spi2-core \
      gtk4 gtk4-layer-shell python3-gobject gobject-introspection librsvg2 glycin-loaders bubblewrap \
      rsms-inter-fonts google-noto-sans-fonts google-noto-sans-arabic-fonts \
      glibc-langpack-en glibc-langpack-de glibc-langpack-it glibc-langpack-ar gettext \
      procps-ng libcap jq binutils \
  && dnf5 clean all \
  && setcap -r /usr/bin/sway
# Fedora ships sway with cap_sys_nice=ep, which a rootless container's bounding set
# refuses at exec with a bare "Operation not permitted"; dropping it here is portable.

ENV XDG_RUNTIME_DIR=/run/user/1000 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    GALLIUM_DRIVER=llvmpipe \
    GSK_RENDERER=cairo \
    RUST_BACKTRACE=1
RUN mkdir -p /run/user/1000 && chmod 700 /run/user/1000

# The build stage compiles our GTK crates against the same GTK the rig runs.
FROM rig AS build
RUN dnf5 -y install --setopt=install_weak_deps=False \
      rust cargo clippy gcc gcc-c++ clang-devel pkgconf-pkg-config \
      gtk4-devel glib2-devel gtk4-layer-shell-devel \
      speech-dispatcher-devel upower-devel pam-devel tpm2-tss-devel \
  && dnf5 clean all
```

`GSK_RENDERER=cairo` makes GTK's output independent of the GL stack of the runner; the greeter itself forces no renderer (Task 11 leaves the old `GSK_RENDERER=ngl` behind).

- [ ] **Step 2: Write the parent compositor's files**

Create `forge/test/shell/sway.conf`:

```
default_border none
default_floating_border none
gaps inner 0
gaps outer 0
focus_follows_mouse no
exec /repo/forge/test/shell/session.sh
```

Create `forge/test/shell/session.sh` (mode 0755):

```bash
#!/usr/bin/env bash
# Started by sway, so that cosmic-comp inherits sway's WAYLAND_DISPLAY and nests in it.
export COSMIC_BACKEND=winit
exec cosmic-comp --no-xwayland &> "/out/${RIG_TAG:-scene}-cosmic-comp.log"
```

- [ ] **Step 3: Write `scene.sh`**

Create `forge/test/shell/scene.sh` (mode 0755):

```bash
#!/usr/bin/env bash
# scene.sh <width> <height> <scale> <tag> -- <client command...>
# One scene, one PNG: /out/<tag>.png. Runs inside the rig container under
# dbus-run-session. What makes the capture reproducible (doc_shell.md, SH13): fresh XDG
# directories, a frozen wall clock with a live monotonic clock, TZ=UTC, one locale per
# case, a fixed set of clients.
set -euo pipefail

width=$1 height=$2 scale=$3 tag=$4
shift 4
[ "${1:-}" = "--" ] && shift
settle=${RIG_SETTLE:-4}
export RIG_TAG=$tag

export XDG_RUNTIME_DIR=/run/user/1000
scratch=$(mktemp -d)
export XDG_CONFIG_HOME=$scratch/config XDG_DATA_HOME=$scratch/data XDG_CACHE_HOME=$scratch/cache XDG_STATE_HOME=$scratch/state
mkdir -p "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME" "$XDG_STATE_HOME"
export HOME=$scratch
if [ -n "${RIG_CONFIG_SEED:-}" ]; then
    cp -r "$RIG_CONFIG_SEED"/. "$XDG_CONFIG_HOME"/
fi
if [ -n "${RIG_DATA_OVERLAY:-}" ]; then
    export XDG_DATA_DIRS=$RIG_DATA_OVERLAY:/usr/local/share:/usr/share
fi
export XDG_CURRENT_DESKTOP=COSMIC XDG_SESSION_TYPE=wayland XDG_SESSION_DESKTOP=COSMIC
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 WLR_HEADLESS_OUTPUTS=1
export TZ=UTC LC_ALL=${RIG_LOCALE:-C.UTF-8} LANG=${RIG_LOCALE:-C.UTF-8}
frozen="@2026-09-18 10:00:00"
export FAKETIME_DONT_FAKE_MONOTONIC=1

wait_for() { # wait_for <seconds> <command...>: poll four times a second
    local tries=$(($1 * 4))
    shift
    until "$@"; do
        tries=$((tries - 1))
        if [ "$tries" -le 0 ]; then
            echo "scene.sh: timed out waiting for: $*" >&2
            return 1
        fi
        sleep 0.25
    done
}

# 1. The parent: wlroots headless on pixman, one output of the requested size.
sway -c /repo/forge/test/shell/sway.conf &> "/out/$tag-sway.log" &
sway_socket() { ls "$XDG_RUNTIME_DIR"/sway-ipc.*.sock > /dev/null 2>&1; }
wait_for 20 sway_socket
SWAYSOCK=$(ls "$XDG_RUNTIME_DIR"/sway-ipc.*.sock | head -1)
export SWAYSOCK
sway_display=$(basename "$(ls -tr "$XDG_RUNTIME_DIR"/wayland-[0-9] | head -1)")
swaymsg output HEADLESS-1 mode "${width}x${height}" > /dev/null

# 2. cosmic-comp takes the next free socket; its one tiled window fills the output.
cosmic_display() {
    for socket in "$XDG_RUNTIME_DIR"/wayland-[0-9]; do
        [ "$(basename "$socket")" != "$sway_display" ] && basename "$socket" && return 0
    done
    return 1
}
wait_for 30 cosmic_display > /dev/null
WAYLAND_DISPLAY=$(cosmic_display)
export WAYLAND_DISPLAY
wait_for 20 cosmic-randr list > /dev/null

# 3. Size and fractional scale of the nested output.
cosmic-randr mode --scale "$scale" WINIT-0 "$width" "$height" &> "/out/$tag-randr.txt"
sleep 1

# 4. The scene: optionally the panel, then the client under test.
if [ "${RIG_PANEL:-0}" = 1 ]; then
    faketime -f "$frozen" cosmic-panel &> "/out/$tag-panel.log" &
fi
faketime -f "$frozen" "$@" &> "/out/$tag-client.log" &
client=$!
sleep "$settle"
if ! kill -0 "$client" 2> /dev/null; then
    echo "scene.sh: the client exited before the capture; see /out/$tag-client.log" >&2
    exit 1
fi
if [ -n "${RIG_HOLD:-}" ]; then
    $RIG_HOLD
fi

# 5. One PNG, from inside the compositor.
grim -o WINIT-0 "/out/$tag.png"
```

- [ ] **Step 4: Write the parse gate**

Create `forge/test/shell/css_parse_gate.py` (mode 0755):

```python
#!/usr/bin/python3
"""Fails when GTK's own CSS parser reports anything about a stylesheet.

    css_parse_gate.py [--self-test] <file.css>...

GTK never fails a load: it reports through the provider's `parsing-error` signal and
carries on, which is how a sheet with 27 errors reached the old greeter. The provider
needs no display and no Gtk.init(). --self-test first proves that the gate can fail.
"""
import sys
import tempfile

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk  # noqa: E402

KNOWN_BAD = ".x { backdrop-filter: blur(4px); color: red !important; }\n"


def reports(path):
    found = []

    def on_error(_provider, section, error):
        start = section.get_start_location()
        found.append(f"{path}:{start.lines + 1}:{start.line_chars + 1}: {error.message}")

    provider = Gtk.CssProvider()
    provider.connect("parsing-error", on_error)
    provider.load_from_file(Gio.File.new_for_path(path))
    return found


def self_test():
    with tempfile.NamedTemporaryFile("w", suffix=".css") as bad:
        bad.write(KNOWN_BAD)
        bad.flush()
        found = reports(bad.name)
    if len(found) != 2:
        print(f"self-test: expected 2 reports on the known-bad sheet, got {found}", file=sys.stderr)
        return False
    return True


def main(argv):
    if argv and argv[0] == "--self-test":
        if not self_test():
            return 2
        argv = argv[1:]
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    found = [line for path in argv for line in reports(path)]
    for line in found:
        print(line)
    print(f"{len(argv)} stylesheet(s), {len(found)} GTK parsing report(s), GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Write `rig.sh`**

Create `forge/test/shell/rig.sh` (mode 0755):

```bash
#!/usr/bin/env bash
# rig.sh - the one entry point of the shell test rig. Workflows call this and nothing
# else, so every gate runs the same way on a laptop and on the hosted runner.
#
#   rig.sh build-image      build the rig and build stages locally
#   rig.sh publish-image    push the rig stage and print its digest (needs a registry login)
#   rig.sh probe-sandbox    prove that bubblewrap, and with it glycin, works in the rig
#   rig.sh css-parse        GTK parse gate over the generated stylesheets
set -euo pipefail

root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
rig=$root/forge/test/shell
out=${ATHANOR_RIG_OUT:-$root/.scratch/shell-rig}
registry=${ATHANOR_REGISTRY:-ghcr.io/hr-mes}
local_image=localhost/athanor-shell-rig

# The image: an explicit one, else the published one pinned by digest, else the local build.
rig_image() {
    if [ -n "${ATHANOR_RIG_IMAGE:-}" ]; then
        echo "$ATHANOR_RIG_IMAGE"
    elif [ -s "$rig/rig-image.digest" ]; then
        echo "$registry/athanor-shell-rig@$(cat "$rig/rig-image.digest")"
    else
        echo "$local_image:rig"
    fi
}

# label=disable: under SELinux's container_t bubblewrap cannot mount devpts, glycin's
# loaders die, and GTK draws every SVG icon blank without reporting anything.
in_rig() { # in_rig <image> <command...>
    local image=$1
    shift
    mkdir -p "$out"
    podman run --rm --memory 6g --security-opt label=disable \
        -v "$root:/repo:ro" -v "$out:/out" "$image" "$@"
}

case "${1:-}" in
build-image)
    podman build --target rig -t "$local_image:rig" -f "$rig/Containerfile" "$rig"
    podman build --target build -t "$local_image:build" -f "$rig/Containerfile" "$rig"
    ;;
publish-image)
    podman build --target rig -t "$local_image:rig" -f "$rig/Containerfile" "$rig"
    podman push --digestfile "$out/rig-image.digest" "$local_image:rig" "docker://$registry/athanor-shell-rig:latest"
    echo "published $registry/athanor-shell-rig@$(cat "$out/rig-image.digest")"
    echo "commit that digest as forge/test/shell/rig-image.digest together with the goldens it changes"
    ;;
probe-sandbox)
    in_rig "$(rig_image)" bwrap --unshare-all --ro-bind /usr /usr --symlink usr/lib64 /lib64 --dev /dev /usr/bin/true
    echo "bubblewrap works inside the rig: glycin can decode icons"
    ;;
css-parse)
    in_rig "$(rig_image)" bash -c 'python3 /repo/forge/test/shell/css_parse_gate.py --self-test /repo/system/athanor-style/calmo/generated/css/*.css'
    ;;
*)
    sed -n '2,9p' "${BASH_SOURCE[0]}" >&2
    exit 2
    ;;
esac
```

- [ ] **Step 6: Build the image and run the gate locally**

Run: `bash forge/test/shell/rig.sh build-image`
Expected: two successful builds; `podman images localhost/athanor-shell-rig` lists the tags `rig` (about 1.4 GB) and `build`.

Run: `bash forge/test/shell/rig.sh probe-sandbox`
Expected: `bubblewrap works inside the rig: glycin can decode icons`.

Run: `bash forge/test/shell/rig.sh css-parse`
Expected: `4 stylesheet(s), 0 GTK parsing report(s), GTK 4.20.4`, exit 0.

- [ ] **Step 7: See the gate fail**

Append `.x { backdrop-filter: blur(2px); }` to `system/athanor-style/calmo/generated/css/calmo-light.css`, run `bash forge/test/shell/rig.sh css-parse`.
Expected: `…/calmo-light.css:<line>:6: No property named "backdrop-filter"`, `1 GTK parsing report(s)`, exit 1. Then restore the file: `python3 -B system/athanor-style/calmo/generate.py css`.

- [ ] **Step 8: Write the workflow**

Create `.github/workflows/shell-surfaces.yml`:

```yaml
name: Shell surfaces

on:
  push:
    branches: [iso-v0]
    paths:
      - "system/athanor-style/**"
      - "forge/specs/athanor-greeter-ui/**"
      - "forge/test/shell/**"
      - ".github/workflows/shell-surfaces.yml"
  pull_request:
    paths:
      - "system/athanor-style/**"
      - "forge/specs/athanor-greeter-ui/**"
      - "forge/test/shell/**"
      - ".github/workflows/shell-surfaces.yml"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  lint:
    uses: ./.github/workflows/call-lint.yml

  css-parse:
    name: GTK parse gate over the generated stylesheets
    needs: lint
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - name: Rig image
        run: bash forge/test/shell/rig.sh build-image
      - name: Nested sandbox probe
        run: bash forge/test/shell/rig.sh probe-sandbox
      - name: GTK parse gate
        run: bash forge/test/shell/rig.sh css-parse
```

`probe-sandbox` on the hosted runner is the explicit check the plan cannot make from here. **Outcome A:** it passes; nothing changes. **Outcome B:** it fails with an AppArmor denial (`bwrap: setting up uid map: Permission denied` or similar): add `--security-opt apparmor=unconfined` next to `label=disable` in `in_rig`, state the reason in the comment above it, and re-run; the container stays rootless and unprivileged either way.

- [ ] **Step 9: Validate the workflow and commit**

Run: `actionlint .github/workflows/shell-surfaces.yml && python3 scripts/verify.py workflows && shellcheck forge/test/shell/rig.sh forge/test/shell/scene.sh forge/test/shell/session.sh`
Expected: no findings.

```bash
git add forge/test/shell/Containerfile forge/test/shell/rig.sh forge/test/shell/scene.sh forge/test/shell/sway.conf forge/test/shell/session.sh forge/test/shell/css_parse_gate.py .github/workflows/shell-surfaces.yml
git commit -m "ci(shell): add the headless rig and the GTK parse gate for the stylesheets"
```

### Task 5: Seal icons

**Files:**
- Create (generated, committed): `system/athanor-style/calmo/generated/icons/athanor-{mark,seal-verified,seal-attention,seal-blocked}-symbolic.svg`
- Test: `system/athanor-style/calmo/tests/test_generate.py` (add class `IconsTest`)

**Interfaces:**
- Consumes: `generate.icons()` (Task 3).
- Produces: icon names `athanor-mark-symbolic`, `athanor-seal-verified-symbolic`, `athanor-seal-attention-symbolic`, `athanor-seal-blocked-symbolic`; the CSS class `athanor-seal`, which maps GTK's symbolic classes to the trust tokens (`success` → `ath_ok`, `warning` → `ath_warn`, `error` → `ath_bad`).

Why the icons are fill-only: GTK recolours a symbolic icon by forcing `fill` on every path, so the mockup's stroked mark would come out as a filled disc. The ring is an even-odd path, the glyph is a hole cut out of the badge disc, and a state is therefore a shape as well as a colour. Verified while writing this plan, in the rig, through `Gtk.Image` with the class `athanor-seal`: the mark draws in the ink colour and the three badges in `#12805f`, `#a36a00`, `#b3261e`.

- [ ] **Step 1: Add the failing test**

Add the class `IconsTest` from the listing in Task 3 to `system/athanor-style/calmo/tests/test_generate.py`, then break one invariant to see the test bite: in `generate.py`, temporarily change `"blocked": ("error", [_cross_glyph()])` to use `_check_glyph()`.

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `test_each_state_has_its_own_class_and_its_own_shape` fails with `2 != 3`. Restore `_cross_glyph()`.

- [ ] **Step 2: Run and see it pass**

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `OK` (31 tests).

- [ ] **Step 3: Generate and look at them**

Run: `python3 -B system/athanor-style/calmo/generate.py icons`
Expected: four `wrote generated/icons/…` lines.

- [ ] **Step 4: Commit**

```bash
git add system/athanor-style/calmo/generated/icons system/athanor-style/calmo/tests/test_generate.py
git commit -m "feat(calmo): add the seal icons, one shape and one trust colour per state"
```

### Task 6: Hearth wallpaper

**Files:**
- Test: `system/athanor-style/calmo/tests/test_generate.py` (add class `WallpaperTest`)

**Interfaces:**
- Consumes: `generate.wallpaper`, `generate.hearth_rows`, `png.encode` (Task 3).
- Produces: the command `generate.py wallpaper <light|dark> <width> <height> <out.png>`, which Task 8's spec calls at 3840×2160. Geometry: the mockup's `radial-gradient(circle at 80% 122%, …)` with stops at 22, 37, 54 and 74 % of the farthest-corner distance over `linear-gradient(165deg, bg1, bg2)`; the greeter draws the same geometry in CSS, so the wallpaper and the greeter cannot drift apart.

- [ ] **Step 1: Add the failing test**

Add the class `WallpaperTest` from the listing in Task 3. To see it bite, run it once with `block=16` changed to `block=4096` in the signature of `hearth_rows`.

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `test_block_fill_matches_the_exact_render_within_one_level` fails (`worst` is 3 or more). Restore `block=16`.

- [ ] **Step 2: Run and see it pass**

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `OK` (35 tests).

- [ ] **Step 3: Render at full size**

Run: `python3 -B system/athanor-style/calmo/generate.py wallpaper light 3840 2160 .scratch/hearth-light.png`
Expected: about 2.5 s, a PNG of about 96 KB. Open it: four discs rise from the bottom right corner over a pale indigo gradient, as in the mockup's "Desktop" section.

- [ ] **Step 4: Commit**

```bash
git add system/athanor-style/calmo/tests/test_generate.py
git commit -m "test(calmo): cover the hearth wallpaper renderer"
```

### Task 7: Default `CosmicTheme`

**Files:**
- Create: `forge/tools/calmo-cosmic-theme/Cargo.toml`, `forge/tools/calmo-cosmic-theme/src/main.rs`, `forge/tools/calmo-cosmic-theme/derive.sh`
- Create (produced by `derive.sh`, committed): `forge/tools/calmo-cosmic-theme/Cargo.lock`, `system/athanor-style/calmo/generated/cosmic/` (`STAMP` and `cosmic/com.system76.CosmicTheme.{Light,Dark}{,.Builder}/v2/*`, `cosmic/com.system76.CosmicTheme.Mode/v1/*`)
- Create (generated, committed): `system/athanor-style/calmo/generated/cosmic-inputs.json`, `system/athanor-style/calmo/generated/cosmic-bg/com.system76.CosmicBackground/v1/{all,same-on-all}`
- Modify: `Cargo.toml` (root: add `"forge/tools/calmo-cosmic-theme"` to `[workspace] exclude`)
- Modify: `forge/test/shell/rig.sh` (sub-command `cosmic-preview`)
- Modify: `.github/workflows/call-lint.yml` (the Calmo step gains `generate.py --check`)
- Test: `system/athanor-style/calmo/tests/test_generate.py` (add class `CosmicTest`)

**Interfaces:**
- Consumes: `generate.cosmic_inputs`, `generate.check` (Task 3); `scene.sh`, `in_rig`, `rig_image` (Task 4).
- Produces:
  - `calmo-cosmic-theme <cosmic-inputs.json> <out-dir>`: writes `<out-dir>/cosmic/<config>/v<N>/<key>` and `<out-dir>/STAMP` (SHA-256 of the inputs file).
  - `forge/tools/calmo-cosmic-theme/derive.sh`: regenerates `generated/cosmic/` in a container.
  - The overlay tree Task 8 installs: `generated/cosmic/cosmic/` plus `generated/cosmic-bg/`.

The tool was built and run while this plan was written (34 s in a `fedora:43` container with Rust 1.98): it wrote 39 derived keys and 22 Builder keys per mode, `Mode/v1/is_dark` = `false`, no empty `v1` directory, and colours in the same `"#RRGGBBAA"` form the shipped Settings writes into `~/.config/cosmic`. Against the key files Fedora's `cosmic-settings-1.8.0-1.fc43` installs, the tool's set is a superset by `frosted_maximized_apps` and `list_button`; an unknown key file is ignored by cosmic-config, a missing one would not be.

- [ ] **Step 1: Add the failing test, see it pass**

Add the class `CosmicTest` from the listing in Task 3.

Run: `python3 -B -m unittest discover -s system/athanor-style/calmo/tests -v`
Expected: `OK` (37 tests). (The generator already exists; to see `test_inputs_are_the_five_builder_keys_per_mode` bite, delete one entry of `COSMIC_INPUTS`, run, restore.)

- [ ] **Step 2: Write the tool's manifest**

Create `forge/tools/calmo-cosmic-theme/Cargo.toml`:

```toml
[package]
name = "calmo-cosmic-theme"
version = "1.0.0"
edition = "2021"
publish = false
description = "Builds COSMIC's system defaults for the Calmo identity with COSMIC's own ThemeBuilder"

# Standalone on purpose: cosmic-theme is not on crates.io, and the Athanor workspace
# allows no git source. The revision is the one cosmic-settings epoch-1.8.0 locks, so
# the derived theme is the one the shipped Settings would compute from the same inputs.
[workspace]

[dependencies]
cosmic-theme = { git = "https://github.com/pop-os/libcosmic", rev = "2a73fbc0edfe1525381bf999e241d73def79b222" }
cosmic-config = { git = "https://github.com/pop-os/libcosmic", rev = "2a73fbc0edfe1525381bf999e241d73def79b222" }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
sha2 = "0.10"
hex = "0.4"
anyhow = "1"
```

In the root `Cargo.toml`, extend the exclusion list so that cargo does not claim the tool for the workspace:

```toml
exclude = [
    "tests/fuzz",
    "forge/tools/calmo-cosmic-theme"
]
```

- [ ] **Step 3: Write the tool**

Create `forge/tools/calmo-cosmic-theme/src/main.rs`:

```rust
//! calmo-cosmic-theme <cosmic-inputs.json> <out-dir>
//!
//! Reads the five Builder inputs the Calmo tokens set for each mode, applies them to
//! COSMIC's stock builders, derives the themes with `ThemeBuilder::build()` and writes
//! complete cosmic-config directories under `<out-dir>/cosmic/`, ready to be served as
//! system defaults from a directory placed first in `XDG_DATA_DIRS`.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use cosmic_config::{Config, CosmicConfigEntry};
use cosmic_theme::palette::{Srgb, Srgba};
use cosmic_theme::{Theme, ThemeBuilder, ThemeMode, DARK_THEME_BUILDER_ID, DARK_THEME_ID, LIGHT_THEME_BUILDER_ID, LIGHT_THEME_ID, THEME_MODE_ID};
use serde::Deserialize;
use sha2::{Digest, Sha256};

#[derive(Deserialize)]
struct Inputs {
    light: Mode,
    dark: Mode,
}

#[derive(Deserialize)]
struct Mode {
    accent: [f32; 3],
    bg_color: [f32; 3],
    primary_container_bg: [f32; 3],
    /// Optional: leaving a tint out keeps COSMIC's neutral steps.
    #[serde(default)]
    neutral_tint: Option<[f32; 3]>,
    #[serde(default)]
    text_tint: Option<[f32; 3]>,
}

fn rgb(c: [f32; 3]) -> Srgb {
    Srgb::new(c[0], c[1], c[2])
}

fn rgba(c: [f32; 3]) -> Srgba {
    Srgba::new(c[0], c[1], c[2], 1.0)
}

fn write<T: CosmicConfigEntry>(entry: &T, id: &str, out: &Path) -> Result<()> {
    let config = Config::with_custom_path(id, T::VERSION, out.to_path_buf())
        .map_err(|e| anyhow::anyhow!("{id}: {e}"))?;
    entry.write_entry(&config).map_err(|e| anyhow::anyhow!("{id}: {e}"))
}

fn write_mode(stock: ThemeBuilder, mode: &Mode, builder_id: &str, theme_id: &str, out: &Path) -> Result<()> {
    let mut builder = stock
        .accent(rgb(mode.accent))
        .bg_color(rgba(mode.bg_color))
        .primary_container_bg(rgba(mode.primary_container_bg));
    if let Some(tint) = mode.neutral_tint {
        builder = builder.neutral_tint(rgb(tint));
    }
    if let Some(tint) = mode.text_tint {
        builder = builder.text_tint(rgb(tint));
    }
    write(&builder, builder_id, out)?;
    let theme: Theme = builder.build();
    write(&theme, theme_id, out)
}

/// cosmic-config creates the directory of the previous schema version as a side effect.
/// An empty `v1` served from the overlay would shadow COSMIC's own `v1` defaults.
fn remove_empty_dirs(dir: &Path) -> Result<()> {
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            remove_empty_dirs(&path)?;
            if std::fs::read_dir(&path)?.next().is_none() {
                std::fs::remove_dir(&path)?;
            }
        }
    }
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let [_, inputs_path, out] = args.as_slice() else {
        bail!("usage: calmo-cosmic-theme <cosmic-inputs.json> <out-dir>");
    };
    let out = PathBuf::from(out);
    let raw = std::fs::read(inputs_path).with_context(|| format!("reading {inputs_path}"))?;
    let inputs: Inputs = serde_json::from_slice(&raw).context("parsing the inputs")?;

    if out.join("cosmic").exists() {
        std::fs::remove_dir_all(out.join("cosmic"))?;
    }
    write_mode(ThemeBuilder::light(), &inputs.light, LIGHT_THEME_BUILDER_ID, LIGHT_THEME_ID, &out)?;
    write_mode(ThemeBuilder::dark(), &inputs.dark, DARK_THEME_BUILDER_ID, DARK_THEME_ID, &out)?;
    // Calmo is light by default (doc_shell.md, SH5); COSMIC's stock default is dark.
    write(&ThemeMode { is_dark: false, auto_switch: false }, THEME_MODE_ID, &out)?;
    remove_empty_dirs(&out.join("cosmic"))?;

    std::fs::write(out.join("STAMP"), format!("{}\n", hex::encode(Sha256::digest(&raw))))?;
    Ok(())
}
```

- [ ] **Step 4: Write `derive.sh`**

Create `forge/tools/calmo-cosmic-theme/derive.sh` (mode 0755):

```bash
#!/usr/bin/env bash
# derive.sh - regenerates system/athanor-style/calmo/generated/cosmic/ from
# generated/cosmic-inputs.json with COSMIC's own ThemeBuilder. Run it whenever
# `generate.py --check` says the derived theme is stale, and whenever the libcosmic
# revision in Cargo.toml follows a COSMIC bump. Needs the network: libcosmic is a git
# dependency, which is why this tool is not a member of the workspace.
set -euo pipefail

root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
image=${ATHANOR_RIG_BUILD_IMAGE:-localhost/athanor-shell-rig:build}
generated=$root/system/athanor-style/calmo/generated

python3 -B "$root/system/athanor-style/calmo/generate.py" cosmic
podman run --rm --memory 6g --security-opt label=disable \
    -v "$root/forge/tools/calmo-cosmic-theme:/tool" -v "$generated:/generated" \
    -v athanor-calmo-tool-cargo:/root/.cargo/registry -w /tool \
    "$image" cargo run --release --locked -- /generated/cosmic-inputs.json /generated/cosmic
python3 -B "$root/system/athanor-style/calmo/generate.py" --check
```

The first run has no `Cargo.lock` yet: run it once with `--locked` removed from the script's `cargo run` line, commit the lock file it writes, and put `--locked` back.

- [ ] **Step 5: Derive**

Run: `bash forge/tools/calmo-cosmic-theme/derive.sh`
Expected: cargo builds `calmo-cosmic-theme`, then `generated/ matches tokens.toml`, exit 0.

Run: `ls system/athanor-style/calmo/generated/cosmic/cosmic`
Expected: exactly five directories: `com.system76.CosmicTheme.Dark`, `com.system76.CosmicTheme.Dark.Builder`, `com.system76.CosmicTheme.Light`, `com.system76.CosmicTheme.Light.Builder`, `com.system76.CosmicTheme.Mode`.

Run: `find system/athanor-style/calmo/generated/cosmic -type d -empty`
Expected: no output (an empty `v1` would shadow COSMIC's own `v1` defaults).

Run: `cat system/athanor-style/calmo/generated/cosmic/cosmic/com.system76.CosmicTheme.Light.Builder/v2/accent`
Expected: `Some("#2E44C2FF")`.

- [ ] **Step 6: Check the key sets against the shipped COSMIC**

Add to `forge/test/shell/rig.sh`, before the `*)` arm:

```bash
cosmic-keys)
    # Every key file COSMIC ships must exist in our overlay: resolution is per directory,
    # so a key we do not carry falls back to a compiled-in default, not to COSMIC's file.
    in_rig "$(rig_image)" bash -c '
        status=0
        overlay=/repo/system/athanor-style/calmo/generated/cosmic/cosmic
        for dir in "$overlay"/*/v*; do
            stock=/usr/share/cosmic/${dir#"$overlay"/}
            [ -d "$stock" ] || { echo "not shipped by COSMIC: $stock"; status=1; continue; }
            for key in "$stock"/*; do
                [ -e "$dir/$(basename "$key")" ] || { echo "missing in the overlay: ${dir#"$overlay"/}/$(basename "$key")"; status=1; }
            done
        done
        exit $status'
    ;;
```

and the line `#   rig.sh cosmic-keys      every key COSMIC ships exists in our overlay` to the header comment.

Run: `bash forge/test/shell/rig.sh cosmic-keys`
Expected: no output, exit 0. A `not shipped by COSMIC` line means COSMIC moved to a new schema version: bump `rev` in the tool's `Cargo.toml` to the revision the new cosmic-settings tag locks (`Cargo.lock` of `pop-os/cosmic-settings` at that tag, entry `cosmic-theme`) and derive again.

- [ ] **Step 7: Look at COSMIC under the overlay (the mapping decision)**

Add to `forge/test/shell/rig.sh`, before the `*)` arm, and the matching header line `#   rig.sh cosmic-preview   capture cosmic-panel and Settings under the Calmo defaults`:

```bash
cosmic-preview)
    mkdir -p "$out/seed-dark/cosmic/com.system76.CosmicTheme.Mode/v1"
    printf 'true' > "$out/seed-dark/cosmic/com.system76.CosmicTheme.Mode/v1/is_dark"
    overlay=/repo/system/athanor-style/calmo/generated/cosmic
    in_rig "$(rig_image)" env RIG_PANEL=1 RIG_DATA_OVERLAY="$overlay" \
        dbus-run-session -- /repo/forge/test/shell/scene.sh 1920 1080 1.0 cosmic-preview-light -- cosmic-settings appearance
    in_rig "$(rig_image)" env RIG_PANEL=1 RIG_DATA_OVERLAY="$overlay" RIG_CONFIG_SEED=/out/seed-dark \
        dbus-run-session -- /repo/forge/test/shell/scene.sh 1920 1080 1.0 cosmic-preview-dark -- cosmic-settings appearance
    echo "look at $out/cosmic-preview-light.png and $out/cosmic-preview-dark.png"
    ;;
```

Run: `bash forge/test/shell/rig.sh cosmic-preview` and open the two PNGs beside the mockup's "Desktop" section in light and in dark.

- **Outcome A:** the panel is the near-white (`#fbfcfd`) or near-navy (`#1c2033`) bar of the mockup, Settings shows a side bar slightly darker than its content, the selected accent is indigo. Keep `COSMIC_INPUTS` as it is.
- **Outcome B:** the window background reads flat, side bar and content the same: in `generate.py` change `"bg_color": "surf2"` to `"bg_color": "bg1"`, run `derive.sh`, look again.
- **Outcome C:** buttons and dividers read muddy or blue: remove the `"neutral_tint"` entry from `COSMIC_INPUTS` (the tool treats an absent tint as COSMIC's neutral), update `test_inputs_are_the_five_builder_keys_per_mode` to the four remaining keys and rename it, run `derive.sh`, look again.

Record the outcome and the two captures' look in the commit message. Show the captures to the maintainer before Task 8 ships them: this is the first time Calmo is seen on COSMIC's widgets.

- [ ] **Step 8: Turn the drift check on in CI**

In the "Calmo design tokens" step of `.github/workflows/call-lint.yml`, append the line:

```yaml
          python3 -B system/athanor-style/calmo/generate.py --check
```

Run: `python3 -B system/athanor-style/calmo/generate.py --check && actionlint .github/workflows/call-lint.yml`
Expected: `generated/ matches tokens.toml`, no actionlint output.

- [ ] **Step 9: Commit**

```bash
git add Cargo.toml forge/tools/calmo-cosmic-theme system/athanor-style/calmo/generated/cosmic system/athanor-style/calmo/generated/cosmic-inputs.json system/athanor-style/calmo/generated/cosmic-bg system/athanor-style/calmo/tests/test_generate.py forge/test/shell/rig.sh .github/workflows/call-lint.yml
git commit -m "feat(calmo): derive COSMIC's default theme from the tokens with COSMIC's own builder"
```

### Task 8: Package `athanor-calmo`, the overlay wiring and `verify.py shipped`

**Files:**
- Create: `forge/specs/athanor-calmo/athanor-calmo.spec`
- Create: `forge/specs/athanor-calmo/SOURCES/usr/lib/environment.d/60-athanor-cosmic-defaults.conf`
- Modify: `forge/config/packages.json` (`custom_packages` and `custom_tier2` gain `"calmo"`)
- Modify: `forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-session`
- Modify: `forge/specs/athanor-system-config/athanor-system-config.spec` (`Requires: athanor-calmo`, `Release` +1, changelog)
- Modify: `scripts/verify.py` (function `cosmic_defaults_problems`, called from `check_shipped`)
- Test: `scripts/tests/test_verify_shipped.py`
- Modify: `.github/workflows/call-lint.yml` (the structural-checks step runs `shipped` as well)

**Interfaces:**
- Consumes: `generated/cosmic/cosmic/`, `generated/cosmic-bg/`, `generated/icons/`, `generate.py wallpaper`, `generate.py --check`.
- Produces:
  - Installed paths: `/usr/share/athanor/cosmic-defaults/cosmic/…`, `/usr/lib/environment.d/60-athanor-cosmic-defaults.conf`, `/usr/share/backgrounds/athanor/hearth-{light,dark}.png`, `/usr/share/icons/hicolor/scalable/status/athanor-*-symbolic.svg`.
  - `verify.cosmic_defaults_problems(root: Path) -> list[str]`.
  - The constant `OVERLAY = "/usr/share/athanor/cosmic-defaults"`, spelled identically in the `environment.d` file, in `athanor-session`, in the spec and in `verify.py`.

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_verify_shipped.py`:

```python
"""Unit tests of the COSMIC defaults wiring check in scripts/verify.py
(python3 -B -m unittest discover -s scripts/tests -v)."""

import importlib.util
import pathlib
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "verify.py"
spec = importlib.util.spec_from_file_location("verify", SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

OVERLAY = "/usr/share/athanor/cosmic-defaults"
ENV_FILE = "forge/specs/athanor-calmo/SOURCES/usr/lib/environment.d/60-athanor-cosmic-defaults.conf"
SESSION = "forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-session"
SPEC = "forge/specs/athanor-calmo/athanor-calmo.spec"
KEY = "system/athanor-style/calmo/generated/cosmic/cosmic/com.system76.CosmicTheme.Mode/v1/is_dark"


class CosmicDefaultsTest(unittest.TestCase):
    def tree(self, tmp, **overrides):
        files = {
            KEY: "false",
            ENV_FILE: f"XDG_DATA_DIRS={OVERLAY}:${{XDG_DATA_DIRS:-/usr/local/share:/usr/share}}\n",
            SESSION: f'export XDG_DATA_DIRS="{OVERLAY}:${{XDG_DATA_DIRS:-/usr/local/share:/usr/share}}"\n',
            SPEC: ("%install\ncp -a system/athanor-style/calmo/generated/cosmic/cosmic "
                   f"%{{buildroot}}{OVERLAY}/\n%files\n{OVERLAY}\n"
                   "/usr/lib/environment.d/60-athanor-cosmic-defaults.conf\n"),
        }
        files.update(overrides)
        root = pathlib.Path(tmp)
        for name, text in files.items():
            if text is not None:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text)
        return root

    def test_a_complete_wiring_has_no_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(verify.cosmic_defaults_problems(self.tree(tmp)), [])

    def test_no_generated_defaults_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = verify.cosmic_defaults_problems(self.tree(tmp, **{KEY: None}))
            self.assertEqual(len(problems), 1)
            self.assertIn("derive.sh", problems[0])

    def test_the_overlay_must_come_first_for_the_user_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            late = f"XDG_DATA_DIRS=/usr/share:{OVERLAY}\n"
            problems = verify.cosmic_defaults_problems(self.tree(tmp, **{ENV_FILE: late}))
            self.assertEqual(len(problems), 1)
            self.assertIn("environment.d", problems[0])

    def test_the_compositor_needs_the_export_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = verify.cosmic_defaults_problems(self.tree(tmp, **{SESSION: "exec cosmic-comp\n"}))
            self.assertEqual(len(problems), 1)
            self.assertIn("athanor-session", problems[0])

    def test_the_spec_must_ship_the_overlay_and_the_environment_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = verify.cosmic_defaults_problems(self.tree(tmp, **{SPEC: "%files\n"}))
            self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and see it fail**

Run: `python3 -B -m unittest discover -s scripts/tests -v`
Expected: `AttributeError: module 'verify' has no attribute 'cosmic_defaults_problems'`.

- [ ] **Step 3: Implement the check**

In `scripts/verify.py`, above `@check("shipped", …)`, add:

```python
COSMIC_OVERLAY = "/usr/share/athanor/cosmic-defaults"


def cosmic_defaults_problems(root):
    """How Calmo reaches COSMIC (doc_shell.md, SH5): a data directory of our own, first
    in XDG_DATA_DIRS. cosmic-config resolves system defaults through that variable, so
    the defaults are shipped only if the files exist, the package installs them, and the
    variable is set both for the user manager and for the compositor."""
    root = Path(root)
    problems = []
    generated = root / "system/athanor-style/calmo/generated/cosmic/cosmic"
    if not generated.is_dir() or not any(p.is_file() for p in generated.rglob("*")):
        problems.append("no generated COSMIC defaults: run forge/tools/calmo-cosmic-theme/derive.sh")

    env_file = root / "forge/specs/athanor-calmo/SOURCES/usr/lib/environment.d/60-athanor-cosmic-defaults.conf"
    env_text = read(env_file) if env_file.exists() else ""
    if not re.search(rf"^XDG_DATA_DIRS={re.escape(COSMIC_OVERLAY)}:", env_text, re.M):
        problems.append(f"environment.d: {COSMIC_OVERLAY} is not first in XDG_DATA_DIRS for the user manager")

    session = root / "forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-session"
    session_text = read(session) if session.exists() else ""
    if not re.search(rf'^export XDG_DATA_DIRS="?{re.escape(COSMIC_OVERLAY)}:', session_text, re.M):
        problems.append(f"athanor-session does not export XDG_DATA_DIRS with {COSMIC_OVERLAY} first: "
                        f"cosmic-comp and its children are not started by the user manager")

    spec = root / "forge/specs/athanor-calmo/athanor-calmo.spec"
    files = read(spec).split("%files", 1)[-1] if spec.exists() else ""
    for shipped in (COSMIC_OVERLAY, "/usr/lib/environment.d/60-athanor-cosmic-defaults.conf"):
        if not re.search(rf"^{re.escape(shipped)}$", files, re.M):
            problems.append(f"athanor-calmo.spec: %files does not list {shipped}")
    return problems
```

and at the end of `check_shipped`, before `return r`:

```python
    for problem in cosmic_defaults_problems(ROOT):
        r.fail(problem)
```

- [ ] **Step 4: Run the unit tests (pass) and the check (fail, by design)**

Run: `python3 -B -m unittest discover -s scripts/tests -v`
Expected: `OK`.

Run: `python3 scripts/verify.py shipped`
Expected: `FAIL shipped` with four problems (`environment.d`, `athanor-session`, and two `%files` lines): the wiring does not exist yet. The next steps make it pass.

- [ ] **Step 5: The environment file**

Create `forge/specs/athanor-calmo/SOURCES/usr/lib/environment.d/60-athanor-cosmic-defaults.conf`:

```
# Athanor's defaults for COSMIC (theme, wallpaper) live in a data directory of our own,
# placed ahead of /usr/share: cosmic-config resolves a config's system defaults through
# XDG_DATA_DIRS, and the files under /usr/share/cosmic belong to COSMIC's RPMs. Read by
# the systemd user manager, which starts the panel, the applets, cosmic-bg and every
# D-Bus-activated application. athanor-session exports the same value for the compositor.
XDG_DATA_DIRS=/usr/share/athanor/cosmic-defaults:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}
```

- [ ] **Step 6: The compositor's environment**

In `forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-session`, after the line `export XDG_SESSION_TYPE=wayland`, add:

```sh

# Athanor's defaults for COSMIC come from a data directory ahead of /usr/share (see
# /usr/lib/environment.d/60-athanor-cosmic-defaults.conf, which covers the user
# manager). cosmic-comp, and the locker and idle daemon athanor-desktop starts, are
# children of this script, not of the user manager, so they need it from here.
export XDG_DATA_DIRS="/usr/share/athanor/cosmic-defaults:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
```

In `forge/specs/athanor-system-config/athanor-system-config.spec`: add `Requires: athanor-calmo` next to `Requires: athanor-shell-rs` (Task 11 later replaces that one with `athanor-greeter-ui`), in `Release`, change the fallback `41.fc43` to `42.fc43`, and add at the top of `%changelog` (keep the spec's date and author format, with `42` in place of `N`):

```
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-N
- athanor-session puts /usr/share/athanor/cosmic-defaults first in XDG_DATA_DIRS, so
  that cosmic-comp and the session components it parents read Athanor's default theme
  and wallpaper; the user manager gets the same value from athanor-calmo's
  environment.d file. Require athanor-calmo.
```

- [ ] **Step 7: The spec**

Create `forge/specs/athanor-calmo/athanor-calmo.spec`. It has no `Source`, so the forge builds it in place from the repository root, like `athanor-shell-rs`:

```spec
%global debug_package %{nil}
Name:           athanor-calmo
Version:        1.0.0
Release:        1%{?dist}
Summary:        The Calmo identity: COSMIC defaults, hearth wallpaper and seal icons
License:        MIT
URL:            https://github.com/hr-mes/athanor-forge
BuildArch:      noarch

BuildRequires:  python3
Requires:       rsms-inter-fonts
Requires:       hicolor-icon-theme

%description
Athanor's design system as data. COSMIC's default theme and wallpaper, derived from the
Calmo tokens and served from a data directory placed ahead of /usr/share in
XDG_DATA_DIRS; the hearth wallpaper, light and dark; the symbolic icons of the trust
seal. Inter is the interface font family.

%prep

%build
# The committed output must be the tokens' output: a stale file fails the build.
python3 -B system/athanor-style/calmo/generate.py --check
mkdir -p calmo-build
python3 -B system/athanor-style/calmo/generate.py wallpaper light 3840 2160 calmo-build/hearth-light.png
python3 -B system/athanor-style/calmo/generate.py wallpaper dark 3840 2160 calmo-build/hearth-dark.png

%install
mkdir -p %{buildroot}/usr/share/athanor/cosmic-defaults/cosmic
cp -a system/athanor-style/calmo/generated/cosmic/cosmic/. %{buildroot}/usr/share/athanor/cosmic-defaults/cosmic/
cp -a system/athanor-style/calmo/generated/cosmic-bg/. %{buildroot}/usr/share/athanor/cosmic-defaults/cosmic/
install -D -m 0644 forge/specs/athanor-calmo/SOURCES/usr/lib/environment.d/60-athanor-cosmic-defaults.conf %{buildroot}/usr/lib/environment.d/60-athanor-cosmic-defaults.conf
install -D -m 0644 calmo-build/hearth-light.png %{buildroot}/usr/share/backgrounds/athanor/hearth-light.png
install -D -m 0644 calmo-build/hearth-dark.png %{buildroot}/usr/share/backgrounds/athanor/hearth-dark.png
mkdir -p %{buildroot}/usr/share/icons/hicolor/scalable/status
install -m 0644 system/athanor-style/calmo/generated/icons/*.svg %{buildroot}/usr/share/icons/hicolor/scalable/status/
rm -rf calmo-build

%check
# Resolution is per directory: an empty version directory would shadow COSMIC's own.
test -z "$(find %{buildroot}/usr/share/athanor/cosmic-defaults -type d -empty)"
test -s %{buildroot}/usr/share/athanor/cosmic-defaults/cosmic/com.system76.CosmicTheme.Light/v2/accent
test -s %{buildroot}/usr/share/athanor/cosmic-defaults/cosmic/com.system76.CosmicBackground/v1/all

%transfiletriggerin -- /usr/share/icons/hicolor
gtk4-update-icon-cache -q -t -f /usr/share/icons/hicolor

%files
/usr/share/athanor/cosmic-defaults
/usr/lib/environment.d/60-athanor-cosmic-defaults.conf
/usr/share/backgrounds/athanor
/usr/share/icons/hicolor/scalable/status/athanor-mark-symbolic.svg
/usr/share/icons/hicolor/scalable/status/athanor-seal-verified-symbolic.svg
/usr/share/icons/hicolor/scalable/status/athanor-seal-attention-symbolic.svg
/usr/share/icons/hicolor/scalable/status/athanor-seal-blocked-symbolic.svg

%changelog
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- First package of the Calmo identity (doc_shell.md, SH5): COSMIC's default theme and
  wallpaper served from /usr/share/athanor/cosmic-defaults, the hearth wallpaper in
  light and dark, the seal icons. cosmic-bg cannot follow the theme mode, so the
  default is the light image and the dark one is a choice in Settings.
```

`%transfiletriggerin` is dropped if the image build already refreshes the icon cache; check with `grep -rn "update-icon-cache" system/Containerfile forge/specs/*/*.spec` and, when a system-wide refresh exists, delete the two trigger lines rather than doing the work twice.

- [ ] **Step 8: Put the package in the image**

In `forge/config/packages.json` add `"calmo"` to `custom_packages` (after `"bibata"`) and to `custom_tier2` (after `"bibata"`).

Run: `python3 scripts/verify.py shipped specs`
Expected: both `PASS`.

- [ ] **Step 9: Build the RPM and read its file list**

Run (the forge's in-place build, in the rig's build image, which has `rpm-build` only if added: install it for this one command):

```bash
podman run --rm --security-opt label=disable -v "$PWD:/workspace" -w /workspace localhost/athanor-shell-rig:build \
  bash -c 'dnf5 -y -q install rpm-build && rpmbuild -bb --nodeps --build-in-place --define "_rpmdir /workspace/.scratch/rpms" forge/specs/athanor-calmo/athanor-calmo.spec && rpm -qlp .scratch/rpms/noarch/athanor-calmo-*.rpm | head -20'
```

Expected: the build passes `%check`; the listing starts with `/usr/lib/environment.d/60-athanor-cosmic-defaults.conf` and contains `/usr/share/athanor/cosmic-defaults/cosmic/com.system76.CosmicBackground/v1/all`, the five theme directories, the two PNGs and the four icons.

- [ ] **Step 10: Run `shipped` in CI**

In `.github/workflows/call-lint.yml` change the structural-checks step to:

```yaml
      - name: Structural checks (scripts/verify.py workflows, kickstart, shipped)
        run: python3 scripts/verify.py workflows kickstart shipped
```

First run `python3 scripts/verify.py shipped` locally. If it reports problems that predate this plan, do **not** add it to the step: list them in the commit message and leave the step unchanged; the unit tests of this task still guard the new assertions.

- [ ] **Step 11: Commit (three commits, one problem each, in the order that keeps `verify.py shipped` green)**

```bash
git add forge/specs/athanor-calmo forge/config/packages.json
git commit -m "feat(calmo): package the COSMIC defaults, the hearth wallpaper and the seal icons"
git add forge/specs/athanor-system-config
git commit -m "feat(session): serve Athanor's COSMIC defaults to the compositor and its children"
git add scripts/verify.py scripts/tests/test_verify_shipped.py .github/workflows/call-lint.yml
git commit -m "feat(verify): assert that the COSMIC defaults overlay is shipped and wired"
```

The check lands last, so no commit in between has a red `shipped`.

# Part B: one crate per program

All cargo commands of Parts B and C run in the rig's build image, because the host has no `gtk4-devel`. Define this once per shell session and use it wherever a step says `cargo-in-rig`:

```bash
cargo-in-rig() {
    podman run --rm --memory 8g --security-opt label=disable \
        -v "$PWD:/repo" -v athanor-cargo-registry:/root/.cargo/registry \
        -e CARGO_TARGET_DIR=/repo/target -w /repo localhost/athanor-shell-rig:build cargo "$@"
}
```

`cargo-in-rig check --workspace` also needs `systemd-devel` (`libudev-sys`, unrelated to GTK): add it to the `build` stage's package list in `forge/test/shell/Containerfile` with Task 9's commit and rebuild the image.

### Task 9: Workspace membership and the frozen workspace of the old shell

> **Confirmed by the maintainer on 2026-09-19:** `athanor-shell-rs`, `athanor-dock`, `athanor-settings-rs`, `athanor-store-rs`, `athanor-daemon-rs` and `athanor-oobe` leave `[workspace.members]`; their files stay.

| Crate | Ships today | After this task |
|---|---|---|
| `forge/specs/athanor-shell-rs/athanor-shell-rs-1.0.0` | **yes**: the portal runs its `--file-chooser` and `--privacy-prompt` | frozen at GTK 0.7 in a workspace of its own; still built and shipped; mined until empty |
| `forge/specs/athanor-dock/athanor-dock-1.0.0` | as a library inside the old shell | member of the frozen workspace |
| `forge/specs/athanor-settings-rs/…`, `athanor-store-rs/…`, `athanor-daemon-rs/…`, `system/athanor-oobe` | no | excluded; built by nothing |
| `system/athanor-greeter` (PAM/TPM daemon) | no (`EXEMPT`) | stays a member; its dead `gtk` feature is deleted |
| `system/athanor-style`, `athanor-recovery` | yes | stay; bumped in Task 10 |

**Files:**
- Modify: `Cargo.toml` (`members`, `exclude`)
- Create: `forge/specs/athanor-shell-rs/Cargo.toml`, `forge/specs/athanor-shell-rs/Cargo.lock`
- Create: `forge/specs/athanor-shell-rs/athanor-style-0.7/{Cargo.toml,src/*}` (copy of `system/athanor-style` as it is today)
- Delete: `forge/specs/athanor-shell-rs/athanor-shell-rs-1.0.0/Cargo.lock` (a member has no lock file of its own)
- Modify: `forge/specs/athanor-shell-rs/athanor-shell-rs-1.0.0/Cargo.toml`, `forge/specs/athanor-dock/athanor-dock-1.0.0/Cargo.toml`
- Modify: `forge/specs/athanor-shell-rs/athanor-shell-rs.spec`
- Modify: `system/athanor-greeter/Cargo.toml`, `experimental/EXEMPT`, `forge/test/shell/Containerfile`

**Interfaces:**
- Consumes: nothing.
- Produces: a main workspace whose GTK consumers are exactly `athanor-style` and `athanor-recovery`; the frozen workspace `forge/specs/athanor-shell-rs/` with the build command `cargo build --release --locked --manifest-path forge/specs/athanor-shell-rs/Cargo.toml -p athanor-shell-rs` and the binary at `forge/specs/athanor-shell-rs/target/release/athanor-shell-rs`.

This construction was built on a scratch copy of `6f4fdeda` while revising the plan: the frozen workspace checks in 45 s at gtk4 0.7.3 with 274 locked packages, beside a main workspace at 0.11.4.

- [ ] **Step 1: Record the baseline**

Run: `cargo-in-rig metadata --no-deps --format-version 1 | python3 -c "import json,sys; print(len(json.load(sys.stdin)['packages']))"`
Expected: `34` (33 listed members and the implicit member `athanor-style`).

- [ ] **Step 2: Freeze a copy of `athanor-style` for the old shell**

```bash
mkdir -p forge/specs/athanor-shell-rs/athanor-style-0.7
cp -a system/athanor-style/Cargo.toml system/athanor-style/src forge/specs/athanor-shell-rs/athanor-style-0.7/
```

Only `Cargo.toml` and `src/`: the `calmo/` directory is the live design system and is not part of the frozen crate. Put this comment at the top of the copied `Cargo.toml`:

```toml
# Frozen copy of system/athanor-style as of 2026-09-19, at GTK 0.7, for the old shell
# and dock only (doc_shell.md, SH4). The live crate moves to GTK 0.11, and one dependency
# graph links one gtk4-sys. Do not develop here: this directory is deleted with the shell.
```

- [ ] **Step 3: The frozen workspace root**

Generate `forge/specs/athanor-shell-rs/Cargo.toml` from the root manifest as it is **before** the bump, so that every `{ workspace = true }` of the frozen members keeps resolving to today's version:

```bash
python3 - <<'EOF'
import re
from pathlib import Path
root = Path("Cargo.toml").read_text()
deps = re.search(r"\[workspace\.dependencies\]\n(.*?)\n\[profile\.dev\]", root, re.S).group(1)
profiles = root[root.index("[profile.dev]"):]
Path("forge/specs/athanor-shell-rs/Cargo.toml").write_text(
    "# The frozen workspace of the old shell (doc_shell.md, SH4; decision of 2026-09-19).\n"
    "# athanor-shell-rs is not ported to GTK 0.11: it stays here at GTK 0.7 with its own lock\n"
    "# file and is mined for the code worth keeping until it is empty, then deleted. It still\n"
    "# ships, because xdg-desktop-portal-athanor runs its file chooser and privacy prompt.\n"
    "# The dependency table is the root's as of the freeze. Do not bump it.\n"
    "[workspace]\n"
    "members = [\n"
    '    "athanor-shell-rs-1.0.0",\n'
    '    "athanor-style-0.7",\n'
    '    "../athanor-dock/athanor-dock-1.0.0"\n'
    "]\n"
    'resolver = "2"\n\n'
    "[workspace.dependencies]\n" + deps + "\n" + profiles)
EOF
```

Then three manifest edits:

- `forge/specs/athanor-shell-rs/athanor-shell-rs-1.0.0/Cargo.toml`: `athanor-style = { path = "../athanor-style-0.7" }`. The dependency on `athanor-niri-ipc` keeps its path: that crate stays in the main workspace and has no GTK.
- `forge/specs/athanor-dock/athanor-dock-1.0.0/Cargo.toml`: under `[package]` add `workspace = "../../athanor-shell-rs"` (the crate lives outside the frozen root's directory, so it names its root), and `athanor-style = { path = "../../athanor-shell-rs/athanor-style-0.7" }`.
- `git rm forge/specs/athanor-shell-rs/athanor-shell-rs-1.0.0/Cargo.lock`.

- [ ] **Step 4: The main workspace**

In the root `Cargo.toml`, delete from `members`:

```toml
    "forge/specs/athanor-daemon-rs/athanor-daemon-rs-0.2.1",
    "forge/specs/athanor-dock/athanor-dock-1.0.0",
    "forge/specs/athanor-settings-rs/athanor-settings-rs-1.0.0",
    "forge/specs/athanor-shell-rs/athanor-shell-rs-1.0.0",
    "forge/specs/athanor-store-rs/athanor-store-rs-1.0.0",
    "system/athanor-oobe",
```

and make the exclusion list (already extended in Task 7):

```toml
# Out of this workspace since 2026-09-19 (doc_shell.md, SH4): gtk4-sys declares
# links = "gtk-4", so every GTK crate of one workspace moves together. The old shell and
# its dock are frozen at GTK 0.7 in forge/specs/athanor-shell-rs/, a workspace of their
# own; the other four ship nothing and are built by nothing until they are redesigned.
exclude = [
    "tests/fuzz",
    "forge/tools/calmo-cosmic-theme",
    "forge/specs/athanor-shell-rs",
    "forge/specs/athanor-dock/athanor-dock-1.0.0",
    "forge/specs/athanor-daemon-rs/athanor-daemon-rs-0.2.1",
    "forge/specs/athanor-settings-rs/athanor-settings-rs-1.0.0",
    "forge/specs/athanor-store-rs/athanor-store-rs-1.0.0",
    "system/athanor-oobe"
]
```

- [ ] **Step 5: The frozen lock file**

```bash
cp Cargo.lock forge/specs/athanor-shell-rs/Cargo.lock
cargo-in-rig metadata --manifest-path forge/specs/athanor-shell-rs/Cargo.toml --format-version 1 > /dev/null
```

cargo prunes the copied lock to the frozen graph and changes no version. `git diff --stat Cargo.lock` must be empty at this point.

Run: `grep -A1 '^name = "gtk4"$' forge/specs/athanor-shell-rs/Cargo.lock`
Expected: `version = "0.7.3"`.

- [ ] **Step 6: Remove the dead feature of `system/athanor-greeter`**

Run: `grep -rn 'feature = "gtk"' system/athanor-greeter`
Expected: no output. Then delete from `system/athanor-greeter/Cargo.toml` the three optional dependencies (`gtk4`, `gtk4-layer-shell`, `glib`, lines 20 to 22) and the line `gtk = ["dep:gtk4", "dep:gtk4-layer-shell", "dep:glib"]`.

- [ ] **Step 7: Build the old shell from its new home**

In `forge/specs/athanor-shell-rs/athanor-shell-rs.spec`:

```spec
%build
%set_build_flags
# The old shell is frozen at GTK 0.7 in a workspace of its own (doc_shell.md, SH4).
cargo build --release --locked --manifest-path forge/specs/athanor-shell-rs/Cargo.toml -p %{name}

%install
mkdir -p %{buildroot}/usr/bin
install -m 0755 forge/specs/athanor-shell-rs/target/release/athanor-shell-rs %{buildroot}/usr/bin/athanor-shell-rs
```

`Release: 35`, and at the top of `%changelog`:

```
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-35
- Frozen at GTK 0.7 in a workspace of its own, forge/specs/athanor-shell-rs/, with its
  own lock file (doc_shell.md, SH4: one crate per program). The package stays in the
  image for xdg-desktop-portal-athanor, which runs its file chooser and privacy prompt.
```

- [ ] **Step 8: `experimental/EXEMPT`**

Remove the entries `athanor-store-rs`, `athanor-settings-rs`, `athanor-daemon-rs` and `athanor-dock`, keep their comment blocks, and start each block with "Out of the workspace since 2026-09-19, and". `verify.py shipped` reads members only, so an excluded crate needs no exemption.

- [ ] **Step 9: Verify both workspaces**

Run: `cargo-in-rig metadata --no-deps --format-version 1 | python3 -c "import json,sys; print(len(json.load(sys.stdin)['packages']))"`
Expected: `28`.

Run: `cargo-in-rig check --workspace`
Expected: `Finished`; GTK is still 0.7.3 here. If cargo rewrites `Cargo.lock`, it only deletes the entries of the crates that left: commit that diff.

Run: `cargo-in-rig build --release --locked --manifest-path forge/specs/athanor-shell-rs/Cargo.toml -p athanor-shell-rs && cargo-in-rig test --manifest-path forge/specs/athanor-shell-rs/Cargo.toml -p athanor-shell-rs`
Expected: `Finished`, 24 tests pass.

Run: `python3 scripts/verify.py shipped specs && just lint`
Expected: green. If `just lint` runs cargo from a directory that no longer holds a member, point that recipe at the root workspace; do not add the frozen workspace to lint.

- [ ] **Step 10: Commit**

One commit: a crate cannot be a member of two workspaces, so there is no buildable state in between.

```bash
git add Cargo.toml Cargo.lock forge/specs/athanor-shell-rs forge/specs/athanor-dock/athanor-dock-1.0.0/Cargo.toml system/athanor-greeter/Cargo.toml experimental/EXEMPT forge/test/shell/Containerfile
git commit -m "build(workspace): freeze the old shell at GTK 0.7 in a workspace of its own"
```

### Task 10: Bump the workspace: `athanor-style` and `athanor-recovery`

Measured on a scratch copy of `6f4fdeda` with Task 9 applied, in the P2 image, versions as below: `athanor-style` fails on one line; with that line fixed **`athanor-recovery` compiles with 0 errors** at relm4 0.11.0. The lock resolves to gtk4 0.11.4, glib 0.22.9, relm4 0.11.0.

**Files:**
- Modify: `Cargo.toml` (`[workspace.dependencies]`), `Cargo.lock`
- Modify: `system/athanor-style/src/appearance_engine.rs:291`
- Modify: `forge/specs/athanor-recovery/athanor-recovery.spec` (`Release: 5`, changelog)

**Interfaces:**
- Consumes: the workspace of Task 9.
- Produces: `gtk4 0.11.4` with the feature `v4_18`, `gtk4-layer-shell 0.8.1`, `glib 0.22.9`, `relm4 0.11.0` as workspace dependencies.

- [ ] **Step 1: Bump**

In the root `Cargo.toml`:

```toml
gtk4 = { version = "0.11.4", features = ["v4_18"] }
gtk4-layer-shell = "0.8.1"
glib = "0.22.9"
relm4 = "0.11.0"
```

`v4_18` exposes `gdk::Device::layout_names()`, which the greeter's keyboard chip reads in Task 16; Fedora 43 ships GTK 4.20.

- [ ] **Step 2: See the one expected failure**

Run: `cargo-in-rig check -p athanor-style --message-format=short`
Expected: exactly one error, at `appearance_engine.rs:291`.

- [ ] **Step 3: Fix it**

```rust
// before
        *w.borrow_mut() = Some(glib::ObjectExt::downgrade(win));
// after
        *w.borrow_mut() = Some(win.downgrade());
```

- [ ] **Step 4: The gate**

Run: `cargo-in-rig check --workspace && cargo-in-rig test -p athanor-style -p athanor-recovery`
Expected: `Finished`; tests pass. **If `athanor-recovery` reports an error after all** (the measurement enabled no extra feature and used the default target), list them with `cargo-in-rig check -p athanor-recovery --message-format=short 2>&1 | grep "^forge.*error"`; every kind spike P2 met is mechanical: a layer-shell setter takes `Some(...)`, `glib::clone!(@weak x => move |..| ..)` becomes `glib::clone!(#[weak] x, move |..| ..)`, `connect_command_line` returns `glib::ExitCode::SUCCESS`.

Run: `grep -A1 '^name = "gtk4"$' Cargo.lock forge/specs/athanor-shell-rs/Cargo.lock`
Expected: `0.11.4` in the first, `0.7.3` in the second.

- [ ] **Step 5: Look at recovery once**

The recovery kiosk has no rig case (it is not a 1a surface), so compile success is not proof that it still draws. Run it in the rig's scene and look at the capture:

```bash
cargo-in-rig build --release -p athanor-recovery
podman run --rm --memory 6g --security-opt label=disable -v "$PWD:/repo:ro" -v "$PWD/.scratch/shell-rig:/out" \
  localhost/athanor-shell-rig:rig dbus-run-session -- /repo/forge/test/shell/scene.sh 1280 800 1.0 recovery-after-bump -- /repo/target/release/athanor-recovery-ui
```

Expected: `.scratch/shell-rig/recovery-after-bump.png` shows the recovery card with its buttons. Attach it to the pull request.

- [ ] **Step 6: Release, changelog, commit**

`forge/specs/athanor-recovery/athanor-recovery.spec`, `Release: 5`:

```
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-5
- Build against gtk4 0.11 and relm4 0.11 (doc_shell.md, SH4). No source change was needed.
```

```bash
git add Cargo.toml Cargo.lock system/athanor-style/src/appearance_engine.rs forge/specs/athanor-recovery/athanor-recovery.spec
git commit -m "build(gtk): move the workspace to gtk4 0.11 and relm4 0.11"
```

### Task 11: Extract the greeter into `athanor-greeter-ui`

A move, reviewed as a move: the greeter keeps its look and its strings until Task 16. What is new is only what a program of its own needs (`main.rs`, `power.rs`, the manifest, the spec) and what the move makes possible (a smaller Landlock write set, no theme code, no forced renderer).

**Files:**
- Create: `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/Cargo.toml`, `src/main.rs`, `src/power.rs`
- Move: `…/athanor-shell-rs-1.0.0/src/ui/greeter/greeter.rs` → `…/athanor-greeter-ui-1.0.0/src/ui.rs`; `…/src/sys/auth.rs` → `src/auth.rs`
- Copy: `…/src/sys/sandbox.rs` → `src/sandbox.rs` (the old shell keeps its own)
- Create: `forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec`
- Modify: `Cargo.toml` (member; `greetd_ipc`, `landlock` as workspace dependencies), `Cargo.lock`
- Modify: `forge/config/packages.json` (`custom_packages`, `custom_tier3` gain `"greeter-ui"`)
- Modify: `forge/specs/athanor-system-config/SOURCES/usr/libexec/athanor-greeter-client`, `athanor-system-config.spec`
- Modify: `forge/test/iso/console.py` (the greeter-alive probe)
- Modify (mining): `…/athanor-shell-rs-1.0.0/src/main.rs`, `src/ui/mod.rs`, `src/sys/mod.rs`, `Cargo.toml`; Delete: `src/ui/greeter/`; `forge/specs/athanor-shell-rs/Cargo.lock`, `athanor-shell-rs.spec`

**Interfaces:**
- Consumes: the bumped workspace (Task 10), the frozen workspace (Task 9).
- Produces:
  - crate and binary `athanor-greeter-ui`; `/usr/bin/athanor-greeter-ui`, no arguments; application id `os.athanor.Greeter`
  - `crate::auth::{UserInfo, discover_target_user, authenticate, authenticate_interactive, session_command, session_badge, SESSION_TYPE}` (unchanged signatures)
  - `crate::sandbox::{ensure_single_threaded, apply_landlock_sandbox}`
  - `crate::power::LogindProxy` with `suspend(bool)`, `reboot(bool)`, `power_off(bool)`
  - `crate::ui::build_ui(app: &gtk4::Application)`
  - the gate `cargo clippy -p athanor-greeter-ui -- -D warnings`, green from this commit on.

- [ ] **Step 1: The manifest**

In the root `Cargo.toml`: add `"forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0",` to `members` (alphabetical place, after `athanor-gatekeeper-rs`), and under `[workspace.dependencies]`, in the "System Utilities" block:

```toml
greetd_ipc = "0.10.3"
landlock = "0.4"
```

Both are the versions `athanor-shell-rs` pins today; they are not new to the project.

Create `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/Cargo.toml`:

```toml
[package]
name = "athanor-greeter-ui"
version = "1.0.0"
edition = "2021"
authors = ["Athanor Forge <forge@athanor.os>"]
license = "MIT"
description = "The Athanor greeter: one surface, one binary, the process that reads the password"

[dependencies]
gtk4 = { workspace = true }
gtk4-layer-shell = { workspace = true }
glib = { workspace = true }
zbus = { workspace = true }
tokio = { workspace = true, features = ["rt-multi-thread", "time"] }
greetd_ipc = { workspace = true }
landlock = { workspace = true }
serde_json = { workspace = true }
chrono = "0.4"
tracing = { workspace = true }
tracing-subscriber = { workspace = true, features = ["env-filter"] }
```

`chrono` is what the moved date code uses; Task 16 replaces it with `glib::DateTime` and deletes the line. Against the old shell's 24 dependencies this is 11: no relm4, no clap, no mimalloc, no notify, no meval (and with it no `nom 1.2.4`), no `athanor-dock`, no `athanor-niri-ipc`.

- [ ] **Step 2: Move the code**

```bash
new=forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/src
old=forge/specs/athanor-shell-rs/athanor-shell-rs-1.0.0/src
mkdir -p "$new"
git mv "$old/ui/greeter/greeter.rs" "$new/ui.rs"
git mv "$old/sys/auth.rs" "$new/auth.rs"
cp "$old/sys/sandbox.rs" "$new/sandbox.rs"
git rm "$old/ui/greeter/mod.rs"
```

Edits to the moved files, and no others in this task:

- `ui.rs`: `use crate::sys::auth::*;` → `use crate::auth::*;`; the three `crate::ipc::power::LogindProxy` → `crate::power::LogindProxy`; `window.set_namespace("greeter");` → `window.set_namespace(Some("greeter"));` (the one error spike P2 found in the greeter); `provider.load_from_data(GREETER_CSS);` → `provider.load_from_string(GREETER_CSS);` (`load_from_data` is deprecated in gtk4 0.11 and the lint gate has no exceptions).
- `sandbox.rs`: the greeter writes no configuration and no state. Replace `writable_paths` and its test, and the unit-centred paragraph of the doc comment of `apply_landlock_sandbox`:

```rust
/// Confines the process's writes with Landlock.
///
/// The greeter runs inside the sandbox athanor-greeter-client builds, where $HOME and
/// the runtime directory are private tmpfs mounts. This ruleset restates in-process what
/// the greeter needs to write, so that the confinement survives a wrapper that lost a
/// line: /tmp, the runtime directory, and the DRM nodes. It writes no configuration and
/// no state. Reads are left alone: fonts, icons and catalogs come from /usr.
///
/// The ruleset is a hard requirement: a kernel without Landlock, or one that cannot
/// enforce every requested right, is an error rather than a best-effort no-op, so the
/// caller can refuse to run unconfined. Call it before any other thread exists (see
/// [`ensure_single_threaded`]).
```

```rust
/// The directories the greeter writes to.
fn writable_paths() -> Vec<PathBuf> {
    let mut paths = vec![PathBuf::from("/tmp")];
    if let Some(dir) = env::var_os("XDG_RUNTIME_DIR").filter(|dir| !dir.is_empty()) {
        paths.push(PathBuf::from(dir));
    }
    paths.retain(|path| Path::new(path).is_absolute());
    paths
}
```

```rust
    #[test]
    fn writable_set_is_tmp_and_the_runtime_directory() {
        // Environment variables are process-wide; keep the test to a single thread of use.
        env::set_var("HOME", "/var/home/tester");
        env::set_var("XDG_CONFIG_HOME", "/var/home/tester/.config");
        env::set_var("XDG_RUNTIME_DIR", "/run/user/1000");
        assert_eq!(writable_paths(), vec![PathBuf::from("/tmp"), PathBuf::from("/run/user/1000")]);
    }
```

- [ ] **Step 3: `power.rs`**

```rust
//! The three logind calls behind the greeter's power buttons. They are also the only
//! three methods athanor-greeter-client's D-Bus filter lets through.

use zbus::proxy;

#[proxy(
    interface = "org.freedesktop.login1.Manager",
    default_service = "org.freedesktop.login1",
    default_path = "/org/freedesktop/login1"
)]
pub trait Logind {
    fn power_off(&self, interactive: bool) -> zbus::Result<()>;
    fn reboot(&self, interactive: bool) -> zbus::Result<()>;
    fn suspend(&self, interactive: bool) -> zbus::Result<()>;
}
```

- [ ] **Step 4: `main.rs`**

```rust
//! athanor-greeter-ui: the Athanor greeter, a program of its own (doc_shell.md, SH4).
//!
//! greetd starts cosmic-comp, cosmic-comp starts athanor-greeter-client, and that wrapper
//! execs this binary inside a bubblewrap sandbox. It takes no arguments.

mod auth;
mod power;
mod sandbox;
mod ui;

use gtk4::prelude::*;
use gtk4::Application;

const APP_ID: &str = "os.athanor.Greeter";

fn main() -> glib::ExitCode {
    // Confinement comes first, while this is the only thread in the process. Landlock
    // restricts the calling thread and the threads it creates from then on; a thread
    // that already exists -- a Tokio worker, a GLib worker -- would keep running
    // unconfined. Nothing before this line may start a thread, and the check fails
    // closed if something did. Logging is not set up yet, so errors go to stderr.
    if let Err(err) = sandbox::ensure_single_threaded().and_then(|()| sandbox::apply_landlock_sandbox()) {
        eprintln!("athanor-greeter-ui: cannot apply the Landlock policy, refusing to run unconfined: {err}");
        return glib::ExitCode::FAILURE;
    }

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    // The workspace builds zbus on Tokio, and the greetd conversation sleeps on a Tokio
    // timer: both need a runtime that is current on this thread, or they abort with
    // "there is no reactor running" (acceptance run 34384585109). One worker is enough
    // for three logind calls.
    let runtime = match tokio::runtime::Builder::new_multi_thread().worker_threads(1).enable_all().build() {
        Ok(runtime) => runtime,
        Err(err) => {
            tracing::error!(error = %err, "cannot create the Tokio runtime");
            return glib::ExitCode::FAILURE;
        }
    };
    let _tokio = runtime.enter();

    let app = Application::builder().application_id(APP_ID).build();
    app.connect_activate(ui::build_ui);
    app.run_with_args(&Vec::<String>::new())
}
```

In `ui.rs`, the first statement of the old `connect_activate` closure, `crate::theme::init_css()`, has no counterpart: the inline sheet in `build_ui` is the greeter's whole style.

- [ ] **Step 5: Build under the gate**

Run: `cargo-in-rig clippy -p athanor-greeter-ui --all-targets -- -D warnings`
Expected: findings in the moved code are possible, because it lived under `#![allow(clippy::all, warnings)]` (rustc itself had none: measured). Fix each at its root, in a **second commit** of this task, so that the move stays a move; no `#[allow]`.

Run: `cargo-in-rig test -p athanor-greeter-ui`
Expected: the tests of `auth.rs` and `sandbox.rs` pass (the Landlock tests need a kernel with Landlock, which the container inherits).

- [ ] **Step 6: Mine the old shell**

In `forge/specs/athanor-shell-rs/athanor-shell-rs-1.0.0`: delete the field `greeter: bool` of `Args` and the whole `if args.greeter { … }` block of `src/main.rs`; delete `pub mod greeter;` from `src/ui/mod.rs` and `pub mod auth;` from `src/sys/mod.rs`; delete `greetd_ipc = "0.10.3"` from `Cargo.toml`.

Run: `cargo-in-rig check --manifest-path forge/specs/athanor-shell-rs/Cargo.toml -p athanor-shell-rs && grep -c '^name = "greetd_ipc"' forge/specs/athanor-shell-rs/Cargo.lock`
Expected: `Finished`, then `0` (cargo drops the entry from the frozen lock; commit it).

`athanor-shell-rs.spec`: `Release: 36`, changelog "The greeter left for a program of its own, athanor-greeter-ui; the --greeter mode and the greetd client are removed."

- [ ] **Step 7: The spec**

Create `forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec` (no `Source`: built in place from the repository root):

```spec
%global debug_package %{nil}
Name:           athanor-greeter-ui
Version:        1.0.0
Release:        1%{?dist}
Summary:        The Athanor greeter
License:        MIT

BuildRequires:  rust cargo gcc pkgconf-pkg-config gtk4-devel glib2-devel gtk4-layer-shell-devel
Requires:       gtk4 gtk4-layer-shell greetd

%description
The greeter of Athanor OS: one GTK4 layer-shell surface that talks to greetd. A program
of its own, because it is the process that reads the password. It is started by
/usr/libexec/athanor-greeter-client inside a bubblewrap sandbox and confines its own
writes with Landlock before anything else.

%prep

%build
%set_build_flags
cargo build --release --locked -p %{name}

%install
install -D -m 0755 target/release/athanor-greeter-ui %{buildroot}/usr/bin/athanor-greeter-ui

%files
/usr/bin/athanor-greeter-ui

%changelog
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- The greeter as a program of its own (doc_shell.md, SH4: one crate per program), moved
  out of athanor-shell-rs unchanged in look and behaviour, on gtk4 0.11. Its Landlock
  write set is /tmp, the runtime directory and the DRM nodes; it loads no theme file,
  forces no renderer and no GDK_SCALE.
```

In `forge/config/packages.json` add `"greeter-ui"` to `custom_packages` and to `custom_tier3`, next to `"shell-rs"`.

- [ ] **Step 8: Switch the image to it**

`forge/specs/athanor-system-config/SOURCES/usr/libexec/athanor-greeter-client`:

- the last line: `    -- /usr/bin/athanor-shell-rs --greeter` → `    -- /usr/bin/athanor-greeter-ui`
- delete the bind `--ro-bind-try /var/lib/athanor/theme.css /var/lib/athanor/theme.css \` and the two-line bind `--ro-bind-try "${XDG_CONFIG_HOME:-$HOME/.config}/athanor/theme.css" \` / `"${XDG_CONFIG_HOME:-$HOME/.config}/athanor/theme.css" \`
- in the comment above `exec bwrap`, end the sentence at "… the avatar and font cache directories." and delete the two sentences about `theme.css`
- in the header comment, "Everything else the shell's shared start-up code asks of the system bus is refused, and the shell treats those services as absent." → "Nothing else is asked of the system bus."

`athanor-system-config.spec`: `Requires: athanor-shell-rs` → `Requires: athanor-greeter-ui`; in `Release`, `42.fc43` → `43.fc43` (Task 8 made it 42); changelog: "The greeter is athanor-greeter-ui: athanor-greeter-client execs /usr/bin/athanor-greeter-ui and no longer binds theme.css, which that program does not read."

`forge/test/iso/console.py`, in `GREETER_PROBE`: `grep -q athanor-shell;` → `grep -q athanor-greeter-ui;`.

Run: `shellcheck -s sh forge/specs/athanor-system-config/SOURCES/usr/libexec/athanor-greeter-client && python3 -B forge/test/iso/test_verdict.py && python3 scripts/verify.py shipped specs`
Expected: no findings; the ISO suite passes (it drives a fake guest; if a fixture echoes the old process name, change it to `athanor-greeter-ui` there too); `shipped` finds `athanor-greeter-ui` packaged.

- [ ] **Step 9: Commit (three commits)**

```bash
git add Cargo.toml Cargo.lock forge/specs/athanor-greeter-ui forge/specs/athanor-shell-rs forge/config/packages.json
git commit -m "refactor(greeter): move the greeter out of athanor-shell-rs into a program of its own"
# only if Step 5 found something:
git add forge/specs/athanor-greeter-ui
git commit -m "fix(greeter): clear the clippy findings the old crate-level allow was hiding"
git add forge/specs/athanor-system-config forge/test/iso/console.py
git commit -m "feat(session): start athanor-greeter-ui as the greeter"
```

The acceptance of this task on real hardware is the ISO acceptance workflow's `greeter-alive` and login: it runs on the next image build.
### Task 12: Shim guards

**Files:**
- Create: `forge/scripts/check_shim_link_order.py`
- Test: `forge/scripts/tests/test_check_shim_link_order.py`
- Modify: `forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec` (`%check`, `BuildRequires: binutils python3`)
- Create: `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/src/layer_guard.rs`
- Modify: `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/src/main.rs` (`mod layer_guard;`), `src/ui.rs`
- Modify: `forge/test/shell/rig.sh` (sub-commands `build-greeter`, `layer-guard`), `.github/workflows/shell-surfaces.yml`, `.github/workflows/call-lint.yml`

**Interfaces:**
- Consumes: the crate `athanor-greeter-ui` (Task 11); `in_rig`, `scene.sh` (Task 4).
- Produces:
  - `check_shim_link_order.problems(needed: list[str]) -> list[str]`; command `check_shim_link_order.py <elf>`, exit 1 on a problem.
  - `crate::layer_guard::require_layer_surface(window: &gtk4::ApplicationWindow) -> Result<(), String>`.
  - `rig.sh build-greeter` → `$ATHANOR_RIG_OUT/bin/athanor-greeter-ui` (release build made in the `build` stage); `rig.sh layer-guard`.
  - Exit status 1 and the journal line `athanor-greeter-ui: not a layer surface` when the shim did not load first.

- [ ] **Step 1: Write the failing test of the link-order check**

Create `forge/scripts/tests/test_check_shim_link_order.py`:

```python
"""Unit tests of forge/scripts/check_shim_link_order.py
(python3 -B -m unittest discover -s forge/scripts/tests -v)."""

import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "check_shim_link_order.py"
spec = importlib.util.spec_from_file_location("check_shim_link_order", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

GOOD = ["libgtk4-layer-shell.so.0", "libpango-1.0.so.0", "libgtk-4.so.1", "libc.so.6"]


class LinkOrderTest(unittest.TestCase):
    def test_the_measured_order_passes(self):
        self.assertEqual(check.problems(GOOD), [])

    def test_the_shim_after_gtk_is_a_problem(self):
        self.assertEqual(len(check.problems(["libgtk-4.so.1", "libgtk4-layer-shell.so.0"])), 1)

    def test_the_shim_after_libwayland_is_a_problem(self):
        needed = ["libwayland-client.so.0", "libgtk4-layer-shell.so.0", "libgtk-4.so.1"]
        self.assertEqual(len(check.problems(needed)), 1)

    def test_a_binary_without_the_shim_is_a_problem(self):
        self.assertEqual(len(check.problems(["libgtk-4.so.1"])), 1)

    def test_readelf_output_is_parsed(self):
        text = (" 0x0000000000000001 (NEEDED)             Shared library: [libgtk4-layer-shell.so.0]\n"
                " 0x0000000000000001 (NEEDED)             Shared library: [libgtk-4.so.1]\n"
                " 0x000000000000000e (SONAME)             Library soname: [x]\n")
        self.assertEqual(check.needed(text), ["libgtk4-layer-shell.so.0", "libgtk-4.so.1"])


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -B -m unittest discover -s forge/scripts/tests -v`
Expected: `FileNotFoundError` for `check_shim_link_order.py`.

- [ ] **Step 2: Write the check**

Create `forge/scripts/check_shim_link_order.py` (mode 0755):

```python
#!/usr/bin/env python3
"""check_shim_link_order.py <elf>

gtk4-layer-shell works by interposing libwayland-client's symbols, so the dynamic linker
must load it before libwayland-client, and upstream asks for "before GTK as well". When
it does not, nothing fails: the surface silently becomes an ordinary window with a title
bar. The order of DT_NEEDED is the load order, and today it is right only by the accident
of how cargo orders its -l flags (spike P2). This check turns the accident into a
contract: it runs in %check and fails the package.
"""
import re
import subprocess
import sys

SHIM = "libgtk4-layer-shell.so"
AFTER = ("libgtk-4.so", "libwayland-client.so")


def needed(readelf_output):
    return re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", readelf_output)


def problems(libraries):
    names = [name for name in libraries if name.startswith(SHIM)]
    if not names:
        return [f"{SHIM} is not a direct dependency: the surface cannot be a layer surface"]
    shim = libraries.index(names[0])
    return [f"{name} is loaded before {names[0]}: the shim would not interpose libwayland"
            for name in libraries[:shim] if name.startswith(AFTER)]


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    output = subprocess.run(["readelf", "-d", argv[0]], check=True, capture_output=True, text=True).stdout
    found = problems(needed(output))
    for line in found:
        print(f"{argv[0]}: {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Run: `python3 -B -m unittest discover -s forge/scripts/tests -v`
Expected: `Ran 5 tests` … `OK`.

Add to `.github/workflows/call-lint.yml`, after the Calmo step:

```yaml
      - name: Forge scripts (unit tests)
        run: |
          set -euo pipefail
          python3 -B -m unittest discover -s forge/scripts/tests -v
```

- [ ] **Step 3: Call it from `%check`**

In `forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec`, append `binutils python3` to `BuildRequires`, and add between `%install` and `%files`:

```spec
%check
# doc_shell.md, SH4: the layer-shell shim must load before libwayland-client and GTK.
python3 -B forge/scripts/check_shim_link_order.py target/release/athanor-greeter-ui
```

The forge runs `rpmbuild --nodeps`, so `BuildRequires` documents the need and does not install it. Verify the builder has `readelf`: `grep -n "binutils" flake.nix`. **Outcome A:** present (directly or through the C toolchain): nothing to do. **Outcome B:** absent: add `binutils` to the `build-tools` list in `flake.nix` in the same commit, because a `%check` that cannot run `readelf` fails every build.

- [ ] **Step 4: Build the greeter in the rig and run the check on the real binary**

Add to `forge/test/shell/rig.sh`, before the `*)` arm, with the header line `#   rig.sh build-greeter     release build of athanor-greeter-ui into <out>/bin`:

```bash
build-greeter)
    mkdir -p "$out/bin" "$out/target"
    podman run --rm --memory 8g --security-opt label=disable \
        -v "$root:/repo:ro" -v "$out:/out" -v athanor-cargo-registry:/root/.cargo/registry \
        -e CARGO_TARGET_DIR=/out/target -w /repo "$local_image:build" \
        bash -c 'cargo build --release --locked -p athanor-greeter-ui \
                 && install -m 0755 /out/target/release/athanor-greeter-ui /out/bin/ \
                 && python3 -B forge/scripts/check_shim_link_order.py /out/bin/athanor-greeter-ui'
    ;;
```

Run: `bash forge/test/shell/rig.sh build-greeter`
Expected: `Finished release`, and no output from the check.

- **Outcome A:** exit 0. The accident still holds at 0.8.1; the contract now guards it.
- **Outcome B:** `libgtk-4.so.1 is loaded before libgtk4-layer-shell.so.0`. Add `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/build.rs`:

  ```rust
  // The layer-shell shim interposes libwayland-client and must precede GTK in DT_NEEDED
  // (doc_shell.md, SH4). cargo orders -l flags by the dependency graph, which put GTK
  // first once gtk4-layer-shell-sys moved to 0.8; naming the library here puts it at the
  // front of this binary's own link line.
  fn main() {
      println!("cargo:rustc-link-lib=dylib:+verbatim=libgtk4-layer-shell.so.0");
  }
  ```

  Rebuild and re-run the check. If the order is still wrong, stop and report to the maintainer with the `readelf -d` output: the remaining route is `LD_PRELOAD` in `athanor-greeter-client`, which changes the confinement wrapper and is the maintainer's call.

- [ ] **Step 5: The start-up assertion**

Create `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/src/layer_guard.rs`:

```rust
//! The start-up assertion doc_shell.md SH4 requires of every layer-shell surface.
//!
//! gtk4-layer-shell interposes libwayland-client. When it is not loaded first it cannot,
//! and the library then degrades in silence: the window maps as an ordinary toplevel
//! with a title bar. For the greeter that means a login screen other windows can cover.
//! A surface that is not a layer surface is an error, and the process says so and exits.

use gtk4_layer_shell::LayerShell;

/// Call after `init_layer_shell()`. `Err` carries the line to log before exiting.
pub fn require_layer_surface(window: &gtk4::ApplicationWindow) -> Result<(), String> {
    if !gtk4_layer_shell::is_supported() {
        return Err("the compositor does not offer zwlr_layer_shell_v1, or the layer-shell shim was loaded \
                    after libwayland-client"
            .to_string());
    }
    if !window.is_layer_window() {
        return Err("init_layer_shell() did not produce a layer surface".to_string());
    }
    Ok(())
}
```

Declare it in `src/main.rs` with `mod layer_guard;`.

In `src/ui.rs`, directly after `window.init_layer_shell();`:

```rust
    if let Err(reason) = crate::layer_guard::require_layer_surface(&window) {
        // No tracing subscriber may be listening this early in a failing start; stderr
        // reaches the journal through the compositor's systemd-cat.
        eprintln!("athanor-greeter-ui: not a layer surface: {reason}");
        std::process::exit(1);
    }
```

`std::process::exit` rather than a panic: under `panic = "abort"` a panic is a core dump, and this is a diagnosed configuration error with a message. greetd then reports that the greeter failed, which is the fail-closed behaviour the wrapper already has.

- [ ] **Step 6: Test the assertion where it can fail: in the rig**

Add to `forge/test/shell/rig.sh`, with the header line `#   rig.sh layer-guard       the greeter must refuse to run when the shim loads late`:

```bash
layer-guard)
    rm -f "$out/layer-guard.status"
    # Preloading libwayland-client reproduces the wrong load order on purpose.
    in_rig "$(rig_image)" env RIG_SETTLE=6 ATHANOR_LOGIN_USER=ermete \
        dbus-run-session -- /repo/forge/test/shell/scene.sh 1280 800 1.0 layer-guard -- \
        bash -c 'LD_PRELOAD=/usr/lib64/libwayland-client.so.0 /out/bin/athanor-greeter-ui; echo $? > /out/layer-guard.status; sleep 60'
    status=$(cat "$out/layer-guard.status")
    if [ "$status" != 1 ] || ! grep -q "not a layer surface" "$out/layer-guard-client.log"; then
        echo "layer-guard: expected exit status 1 and the guard's message, got status '$status'" >&2
        exit 1
    fi
    echo "layer-guard: the greeter refused to run as an ordinary window"
    ;;
```

Run: `bash forge/test/shell/rig.sh layer-guard`
Expected: `layer-guard: the greeter refused to run as an ordinary window`. To see the test bite, comment the `std::process::exit(1)` line out, rebuild with `build-greeter`, run again: the sub-command fails with `got status ''` (the greeter keeps running as a titled window); restore the line.

- [ ] **Step 7: Add the job**

In `.github/workflows/shell-surfaces.yml`, add after `css-parse`:

```yaml
  greeter:
    name: Greeter build, link order and layer-surface guard
    needs: lint
    runs-on: ubuntu-24.04
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - name: Rig image
        run: bash forge/test/shell/rig.sh build-image
      - name: Build the greeter and check the DT_NEEDED order
        run: bash forge/test/shell/rig.sh build-greeter
      - name: Layer-surface guard
        run: bash forge/test/shell/rig.sh layer-guard
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: shell-rig-greeter
          path: .scratch/shell-rig/*.log
```

Run: `actionlint .github/workflows/shell-surfaces.yml .github/workflows/call-lint.yml && python3 scripts/verify.py workflows specs && shellcheck forge/test/shell/rig.sh`
Expected: no findings.

- [ ] **Step 8: Commit (two commits)**

```bash
git add forge/scripts/check_shim_link_order.py forge/scripts/tests forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec .github/workflows/call-lint.yml
git commit -m "build(shell): assert in %check that the layer-shell shim is linked before GTK"
git add forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/src forge/test/shell/rig.sh .github/workflows/shell-surfaces.yml
git commit -m "fix(greeter): refuse to run when the window is not a layer surface"
```

### Task 13: Lint gate

SH4: "`#![allow(clippy::all, warnings)]` is removed from any crate a stage touches." After the extraction this is nearly free: `athanor-greeter-ui` never had the attribute and has been clean under `clippy -D warnings` since Task 11. What is left is to make the gate permanent in CI and to bring the other crate 1a touches, `athanor-style`, under it. The frozen shell keeps its crate-level allow: nobody edits it except to take code out.

**Files:**
- Modify: `system/athanor-style/src/lib.rs`, `system/athanor-style/Cargo.toml`
- Modify: `forge/test/shell/rig.sh` (`build-greeter` runs clippy first)

**Interfaces:**
- Consumes: `rig.sh build-greeter` (Task 12).
- Produces: the CI gate `cargo clippy --locked -p athanor-greeter-ui -p athanor-style --all-targets -- -D warnings`.

- [ ] **Step 1: Scope `athanor-style`'s legacy modules**

`accent_engine`, `appearance_engine` and `glass` are the old glass theme. Only `athanor-recovery` still calls into them (`load_glass_theme`), they have never been built as a lint target, and they leave with recovery's re-skin. `system/athanor-style/src/lib.rs` becomes:

```rust
//! Athanor's style crate. `calmo` (added by the design-system work) is the identity;
//! the three modules below are the pre-Calmo glass theme, kept only because
//! athanor-recovery still loads it. They predate the lint gate and keep their warnings
//! silenced until recovery is re-skinned and they are deleted (doc_shell.md, SH4).

#[allow(clippy::all, warnings)]
pub mod accent_engine;
#[allow(clippy::all, warnings)]
pub mod appearance_engine;
#[allow(clippy::all, warnings)]
pub mod glass;

pub use accent_engine::*;
pub use appearance_engine::*;
pub use glass::*;
```

Delete the dead `[profile.release]` table from `system/athanor-style/Cargo.toml`: cargo ignores a member's profile and says so at every build.

- [ ] **Step 2: See the gate green locally**

Run: `cargo-in-rig clippy --locked -p athanor-greeter-ui -p athanor-style --all-targets -- -D warnings`
Expected: `Finished`, no warning. A finding in `lib.rs` itself (for example an ambiguous glob re-export) is fixed, not allowed.

- [ ] **Step 3: Put it in the rig**

In the `build-greeter` arm of `forge/test/shell/rig.sh`, make the command:

```bash
        bash -c 'cargo clippy --locked -p athanor-greeter-ui -p athanor-style --all-targets -- -D warnings \
                 && cargo test --locked -p athanor-greeter-ui -p athanor-style \
                 && cargo build --release --locked -p athanor-greeter-ui \
                 && install -m 0755 /out/target/release/athanor-greeter-ui /out/bin/ \
                 && python3 -B forge/scripts/check_shim_link_order.py /out/bin/athanor-greeter-ui'
```

Run: `bash forge/test/shell/rig.sh build-greeter`
Expected: green. To see the gate bite: add `let unused = 1;` to `main()` of the greeter, run, see `error: unused variable`, remove it.

- [ ] **Step 4: Commit**

```bash
git add system/athanor-style/src/lib.rs system/athanor-style/Cargo.toml forge/test/shell/rig.sh
git commit -m "ci(greeter): gate the greeter and athanor-style on clippy with warnings denied"
```

# Part C: the greeter on the tokens

### Task 14: `athanor_style::calmo`

**Files:**
- Create: `system/athanor-style/src/calmo.rs`
- Modify: `system/athanor-style/src/lib.rs` (`pub mod calmo;`, not glob re-exported)

**Interfaces:**
- Consumes: `system/athanor-style/calmo/generated/css/calmo-{light,dark,light-hc,dark-hc}.css` (Task 3).
- Produces:
  - `athanor_style::calmo::Variant { Light, Dark, LightHc, DarkHc }`, `Copy + Eq + Debug`
  - `Variant::from_name(name: &str) -> Option<Variant>`, `Variant::name(self) -> &'static str`
  - `Variant::is_dark(self) -> bool`, `Variant::is_high_contrast(self) -> bool`, `Variant::with_high_contrast(self, on: bool) -> Variant`
  - `Variant::css(self) -> &'static str`
  - `athanor_style::calmo::load(display: &gtk4::gdk::Display, variant: Variant)`: installs the variant's stylesheet, replacing the one a previous call installed, and aligns GTK's own dark preference.

- [ ] **Step 1: Write the failing tests**

Create `system/athanor-style/src/calmo.rs` with the tests only:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    const ALL: [Variant; 4] = [Variant::Light, Variant::Dark, Variant::LightHc, Variant::DarkHc];

    #[test]
    fn names_round_trip() {
        for variant in ALL {
            assert_eq!(Variant::from_name(variant.name()), Some(variant));
        }
        assert_eq!(Variant::from_name("sepia"), None);
    }

    #[test]
    fn high_contrast_keeps_the_mode() {
        assert_eq!(Variant::Light.with_high_contrast(true), Variant::LightHc);
        assert_eq!(Variant::DarkHc.with_high_contrast(false), Variant::Dark);
        assert!(Variant::DarkHc.is_dark() && Variant::DarkHc.is_high_contrast());
        assert!(!Variant::Light.is_dark() && !Variant::Light.is_high_contrast());
    }

    #[test]
    fn every_variant_embeds_its_own_generated_sheet() {
        for variant in ALL {
            let css = variant.css();
            assert!(css.contains(&format!("/* Variant: {} */", variant.name())), "{variant:?}");
            assert!(css.contains("window.athanor-greeter"));
        }
        assert!(Variant::Light.css().contains("@define-color ath_acc #2e44c2;"));
        assert!(Variant::Dark.css().contains("@define-color ath_acc #8898f7;"));
    }
}
```

and add `pub mod calmo;` to `system/athanor-style/src/lib.rs`.

Run: `cargo-in-rig test -p athanor-style calmo`
Expected: compile error, `cannot find type Variant in this scope`.

- [ ] **Step 2: Implement**

Put above the tests in `system/athanor-style/src/calmo.rs`:

```rust
//! Calmo, the Athanor identity, as GTK4 stylesheets.
//!
//! The four sheets are generated from `calmo/tokens.toml` by `calmo/generate.py` and
//! embedded here, so a surface cannot start without its stylesheet and no CSS file has
//! to be installed, found or readable inside a sandbox. Colours are named colours
//! (`@ath_acc`, ...): a surface that follows the user's COSMIC accent re-defines
//! `ath_acc` from a provider of higher priority; the greeter never does.

use std::cell::RefCell;

use gtk4::gdk;

/// One of the four variants the contrast gate validates.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Variant {
    Light,
    Dark,
    LightHc,
    DarkHc,
}

impl Variant {
    pub fn from_name(name: &str) -> Option<Self> {
        match name {
            "light" => Some(Self::Light),
            "dark" => Some(Self::Dark),
            "light-hc" => Some(Self::LightHc),
            "dark-hc" => Some(Self::DarkHc),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::Light => "light",
            Self::Dark => "dark",
            Self::LightHc => "light-hc",
            Self::DarkHc => "dark-hc",
        }
    }

    pub fn is_dark(self) -> bool {
        matches!(self, Self::Dark | Self::DarkHc)
    }

    pub fn is_high_contrast(self) -> bool {
        matches!(self, Self::LightHc | Self::DarkHc)
    }

    pub fn with_high_contrast(self, on: bool) -> Self {
        match (self.is_dark(), on) {
            (false, false) => Self::Light,
            (false, true) => Self::LightHc,
            (true, false) => Self::Dark,
            (true, true) => Self::DarkHc,
        }
    }

    pub fn css(self) -> &'static str {
        match self {
            Self::Light => include_str!("../calmo/generated/css/calmo-light.css"),
            Self::Dark => include_str!("../calmo/generated/css/calmo-dark.css"),
            Self::LightHc => include_str!("../calmo/generated/css/calmo-light-hc.css"),
            Self::DarkHc => include_str!("../calmo/generated/css/calmo-dark-hc.css"),
        }
    }
}

thread_local! {
    static PROVIDER: RefCell<Option<gtk4::CssProvider>> = const { RefCell::new(None) };
}

/// Installs `variant` on `display`, replacing the sheet a previous call installed. GTK
/// inherits nothing from COSMIC (spike P1), so its own dark preference is set here too:
/// whatever a widget draws that our rules do not reach then matches the variant.
pub fn load(display: &gdk::Display, variant: Variant) {
    let provider = gtk4::CssProvider::new();
    provider.load_from_string(variant.css());
    PROVIDER.with(|slot| {
        if let Some(previous) = slot.borrow_mut().replace(provider.clone()) {
            gtk4::style_context_remove_provider_for_display(display, &previous);
        }
    });
    gtk4::style_context_add_provider_for_display(display, &provider, gtk4::STYLE_PROVIDER_PRIORITY_APPLICATION);
    if let Some(settings) = gtk4::Settings::default() {
        settings.set_gtk_application_prefer_dark_theme(variant.is_dark());
    }
}
```

- [ ] **Step 3: Run the tests**

Run: `cargo-in-rig test -p athanor-style calmo`
Expected: `3 passed`.

Run: `cargo-in-rig clippy -p athanor-style -- -D warnings`
Expected: `Finished`.

- [ ] **Step 4: Commit**

```bash
git add system/athanor-style/src/calmo.rs system/athanor-style/src/lib.rs
git commit -m "feat(style): expose the generated Calmo stylesheets per variant"
```

### Task 15: `athanor-i18n`, catalogs, `.mo` packaging, the greeter's locale

Translations in gettext's format, read by our own code (D5). The crate below was written and tested while revising this plan: 291 lines, no dependency, 10 tests green against real `msgfmt` output in both byte orders.

**Files:**
- Create: `system/athanor-i18n/Cargo.toml`, `src/lib.rs`, `tests/catalog.rs`, `tests/fixtures/{it.po,ar.po,latin1.po,make.sh}` and the four generated, committed `tests/fixtures/*.mo`
- Modify: `Cargo.toml` (member `"system/athanor-i18n"`)
- Modify: `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/Cargo.toml` (`athanor-i18n = { path = "../../../../system/athanor-i18n" }`)
- Create: `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/src/i18n.rs`; Modify: `src/main.rs`
- Create: `…/po/POTFILES.in`, `po/update.sh`, `po/it.po`, `po/en.po`
- Modify: `forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec` (compile and ship the catalogs)
- Modify: `forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-greeter-session`, `athanor-system-config.spec`
- Modify: `experimental/EXEMPT` is **not** needed: `athanor-i18n` is a library, which `verify.py shipped` skips.

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, from `athanor_i18n`:
  - `Catalog::empty() -> Catalog`, `Catalog::parse(bytes: &[u8]) -> Result<Catalog, Error>`
  - `Catalog::find(locale_dir: &Path, domain: &str, languages: &[String]) -> Result<Catalog, (PathBuf, Error)>`
  - `Catalog::load(domain: &str) -> Result<Catalog, (PathBuf, Error)>`
  - `Catalog::tr(&self, msgid) -> &str`, `tr_n(&self, msgid, msgid_plural, n: u64) -> &str`, `tr_c(&self, context, msgid) -> &str`
  - `Catalog::language(&self) -> Option<&str>`, `Catalog::is_rtl(&self) -> bool`
  - `languages(env: impl Fn(&str) -> Option<String>, system_locale_conf: Option<&str>) -> Vec<String>`
  - `PluralRule::{One, NotOne, MoreThanOne, Arabic}`, `PluralRule::index(self, n: u64) -> usize`
  - `LOCALE_DIR = "/usr/share/locale"`, `OVERRIDE_VARIABLE = "ATHANOR_I18N_CATALOG"`
- Produces, in the greeter: `crate::i18n::DOMAIN = "athanor-greeter-ui"`, `crate::i18n::init()`, `crate::i18n::tr(msgid: &str) -> String`, `crate::i18n::tr_with(msgid: &str, key: &str, value: &str) -> String`, `crate::i18n::is_rtl() -> bool`; installed catalogs `/usr/share/locale/{it,en}/LC_MESSAGES/athanor-greeter-ui.mo`.

- [ ] **Step 1: The fixtures, from the real `msgfmt`**

Create `system/athanor-i18n/tests/fixtures/it.po`:

```po
msgid ""
msgstr ""
"Language: it\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

msgid "Shut down"
msgstr "Spegni"

msgid "Signing in…"
msgstr "Accesso in corso…"

msgid "{n} update"
msgid_plural "{n} updates"
msgstr[0] "{n} aggiornamento"
msgstr[1] "{n} aggiornamenti"

msgctxt "verb"
msgid "Restart"
msgstr "Riavvia"

msgid "Left untranslated"
msgstr ""
```

`ar.po`:

```po
msgid ""
msgstr ""
"Language: ar\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Plural-Forms: nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5);\n"

msgid "{n} update"
msgid_plural "{n} updates"
msgstr[0] "zero"
msgstr[1] "one"
msgstr[2] "two"
msgstr[3] "few"
msgstr[4] "many"
msgstr[5] "other"
```

`latin1.po`:

```po
msgid ""
msgstr ""
"Language: it\n"
"Content-Type: text/plain; charset=ISO-8859-1\n"

msgid "Shut down"
msgstr "Spegni"
```

`make.sh` (mode 0755):

```bash
#!/usr/bin/env bash
# make.sh - rebuilds the fixtures from their .po sources with the real msgfmt.
# The .mo files are committed: the tests must not need gettext installed.
set -euo pipefail
here=$(dirname "${BASH_SOURCE[0]}")
msgfmt --endianness=little -o "$here/it.mo" "$here/it.po"
msgfmt --endianness=big -o "$here/it-big-endian.mo" "$here/it.po"
msgfmt --endianness=little -o "$here/ar.mo" "$here/ar.po"
# msgfmt converts to UTF-8 unless told not to; this fixture must stay Latin-1.
msgfmt --no-convert --endianness=little -o "$here/latin1.mo" "$here/latin1.po"
```

Run: `bash system/athanor-i18n/tests/fixtures/make.sh && ls -l system/athanor-i18n/tests/fixtures/*.mo`
Expected: `ar.mo` (325 bytes), `it.mo` and `it-big-endian.mo` (431 bytes each), `latin1.mo` (176 bytes). They are committed: the tests must not need gettext installed.

- [ ] **Step 2: The failing tests**

Create `system/athanor-i18n/Cargo.toml`:

```toml
[package]
name = "athanor-i18n"
version = "1.0.0"
edition = "2021"
license = "MIT"
description = "Reads gettext .mo catalogs in pure Rust: no C, no process-global locale state"

[dependencies]
```

an empty `system/athanor-i18n/src/lib.rs`, the member line `"system/athanor-i18n",` in the root `Cargo.toml` (after `"system/athanor-hypervisor-daemon"`), and `system/athanor-i18n/tests/catalog.rs`:

```rust
//! The fixtures are real `msgfmt` output (tests/fixtures/make.sh).

use athanor_i18n::{languages, Catalog, Error, PluralRule};

const IT: &[u8] = include_bytes!("fixtures/it.mo");
const IT_BIG_ENDIAN: &[u8] = include_bytes!("fixtures/it-big-endian.mo");
const AR: &[u8] = include_bytes!("fixtures/ar.mo");
const LATIN1: &[u8] = include_bytes!("fixtures/latin1.mo");

#[test]
fn translates_and_falls_back_to_the_message_id() {
    let it = Catalog::parse(IT).expect("fixture");
    assert_eq!(it.tr("Shut down"), "Spegni");
    assert_eq!(it.tr("Signing in…"), "Accesso in corso…");
    assert_eq!(it.tr("Not in the catalog"), "Not in the catalog");
    assert_eq!(it.tr("Left untranslated"), "Left untranslated");
    assert_eq!(it.language(), Some("it"));
    assert!(!it.is_rtl());
}

#[test]
fn both_byte_orders_read_the_same() {
    let big = Catalog::parse(IT_BIG_ENDIAN).expect("fixture");
    assert_eq!(big.tr("Shut down"), "Spegni");
}

#[test]
fn plurals_follow_the_catalogs_rule() {
    let it = Catalog::parse(IT).expect("fixture");
    assert_eq!(it.tr_n("{n} update", "{n} updates", 1), "{n} aggiornamento");
    assert_eq!(it.tr_n("{n} update", "{n} updates", 0), "{n} aggiornamenti");
    let ar = Catalog::parse(AR).expect("fixture");
    let forms: Vec<&str> = [0, 1, 2, 5, 11, 100].iter().map(|&n| ar.tr_n("{n} update", "{n} updates", n)).collect();
    assert_eq!(forms, ["zero", "one", "two", "few", "many", "other"]);
    assert!(ar.is_rtl());
}

#[test]
fn an_empty_catalog_is_english_with_english_plurals() {
    let english = Catalog::empty();
    assert_eq!(english.tr_n("{n} update", "{n} updates", 1), "{n} update");
    assert_eq!(english.tr_n("{n} update", "{n} updates", 2), "{n} updates");
    assert_eq!(english.language(), None);
}

#[test]
fn context_separates_two_meanings_of_one_word() {
    let it = Catalog::parse(IT).expect("fixture");
    assert_eq!(it.tr_c("verb", "Restart"), "Riavvia");
    assert_eq!(it.tr_c("noun", "Restart"), "Restart");
    assert_eq!(it.tr("Restart"), "Restart");
}

#[test]
fn a_catalog_that_is_not_utf8_is_refused() {
    assert_eq!(Catalog::parse(LATIN1).err(), Some(Error::NotUtf8));
}

#[test]
fn hostile_input_is_an_error_and_never_a_panic() {
    assert!(matches!(Catalog::parse(b""), Err(Error::Malformed(_))));
    assert!(matches!(Catalog::parse(b"not a catalog at all"), Err(Error::Malformed(_))));
    // Every truncation of a real catalog, and every single corrupted offset byte.
    for length in 0..IT.len() {
        let _ = Catalog::parse(&IT[..length]);
    }
    for position in 4..28.min(IT.len()) {
        let mut corrupt = IT.to_vec();
        corrupt[position] = 0xff;
        let _ = Catalog::parse(&corrupt);
    }
}

#[test]
fn an_unknown_plural_rule_is_named_in_the_error() {
    assert!(PluralRule::Arabic.index(103) == 3 && PluralRule::One.index(7) == 0 && PluralRule::MoreThanOne.index(1) == 0);
    let mut catalog = IT.to_vec();
    let needle = b"(n != 1)";
    let at = catalog.windows(needle.len()).position(|window| window == needle).expect("rule in the fixture");
    catalog[at..at + needle.len()].copy_from_slice(b"(n >= 9)");
    assert!(matches!(Catalog::parse(&catalog), Err(Error::UnknownPluralRule(_))));
}

#[test]
fn language_selection() {
    let env = |pairs: &'static [(&'static str, &'static str)]| move |name: &str| pairs.iter().find(|(key, _)| *key == name).map(|(_, value)| value.to_string());
    assert_eq!(languages(env(&[("LANG", "it_IT.UTF-8")]), None), ["it_IT", "it"]);
    assert_eq!(languages(env(&[("LANG", "en_US.UTF-8"), ("LC_ALL", "de_DE.UTF-8@euro")]), None), ["de_DE", "de"]);
    assert_eq!(languages(env(&[("LANG", "en_US.UTF-8"), ("LC_MESSAGES", "ar")]), None), ["ar"]);
    assert_eq!(languages(env(&[("LANG", "")]), Some("# comment\nLANG=\"it_IT.UTF-8\"\n")), ["it_IT", "it"]);
    assert!(languages(env(&[("LANG", "C.UTF-8")]), Some("LANG=it_IT.UTF-8")).is_empty());
    assert!(languages(env(&[]), None).is_empty());
}

#[test]
fn find_prefers_the_specific_directory_and_reports_a_broken_catalog() {
    let root = std::env::temp_dir().join(format!("athanor-i18n-{}", std::process::id()));
    let dir = root.join("it/LC_MESSAGES");
    std::fs::create_dir_all(&dir).expect("create");
    std::fs::write(dir.join("demo.mo"), IT).expect("write");
    let found = Catalog::find(&root, "demo", &["it_IT".to_string(), "it".to_string()]).expect("readable");
    assert_eq!(found.tr("Shut down"), "Spegni");
    assert_eq!(Catalog::find(&root, "demo", &["fr".to_string()]).expect("none is fine").language(), None);
    std::fs::write(dir.join("demo.mo"), b"broken").expect("write");
    assert!(Catalog::find(&root, "demo", &["it".to_string()]).is_err());
    std::fs::remove_dir_all(root).expect("cleanup");
}
```

Run: `cargo-in-rig test -p athanor-i18n`
Expected: compile errors, `unresolved imports athanor_i18n::languages, athanor_i18n::Catalog, …`.

- [ ] **Step 3: The reader**

`system/athanor-i18n/src/lib.rs`:

```rust
//! Translations for Athanor's own programs.
//!
//! The format is gettext's: translators work on `.po` files with the tools they know,
//! and packages ship `.mo` catalogs under `/usr/share/locale`. The *reader* is ours, in
//! safe Rust with no dependency, for three reasons (doc_shell.md, SH13; decision of
//! 2026-09-19):
//!
//! - the greeter handles the password: no C FFI and no process-global
//!   `setlocale`/`textdomain` state in that process;
//! - glibc's gettext translates only when the system locale is installed, so it is
//!   silently English inside a sandbox or a test container that lacks the locale;
//! - it is toolkit-agnostic logic (SH4), usable by a surface and by a notifier alike.
//!
//! GTK's own strings keep going through the system's gettext, untouched.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Where packages install catalogs.
pub const LOCALE_DIR: &str = "/usr/share/locale";
/// A catalog file to load instead of looking one up. For the test rig, where German and
/// the right-to-left pseudo-language are catalogs of the test, not of the product.
pub const OVERRIDE_VARIABLE: &str = "ATHANOR_I18N_CATALOG";

const SYSTEM_LOCALE_FILE: &str = "/etc/locale.conf";
const MAGIC: u32 = 0x9504_12de;
const CONTEXT_SEPARATOR: char = '\u{4}';
/// Languages written right to left. The direction comes from the language of the
/// catalog in use, never from a process-wide locale.
const RTL_LANGUAGES: [&str; 4] = ["ar", "he", "fa", "ur"];

#[derive(Debug, PartialEq, Eq)]
pub enum Error {
    /// Not a `.mo` file, or one cut short.
    Malformed(&'static str),
    /// A revision whose major number is not 0.
    UnsupportedRevision(u32),
    /// Only UTF-8 catalogs are read; `msgfmt` is told to write nothing else.
    NotUtf8,
    /// A `Plural-Forms` rule that is not in [`PluralRule`]'s table.
    UnknownPluralRule(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Malformed(what) => write!(f, "malformed catalog: {what}"),
            Self::UnsupportedRevision(revision) => write!(f, "unsupported catalog revision {revision:#x}"),
            Self::NotUtf8 => write!(f, "the catalog is not UTF-8"),
            Self::UnknownPluralRule(rule) => write!(f, "unknown plural rule: {rule}"),
        }
    }
}

impl std::error::Error for Error {}

/// The plural rules of the languages Athanor ships or tests, by their canonical
/// `Plural-Forms` expression. A table, not an expression evaluator: a catalog is data
/// read in the process that handles the password, and an evaluator is a parser and an
/// interpreter to get wrong there. A new language adds one line and one test.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PluralRule {
    /// `nplurals=1; plural=0` (Japanese, Chinese, ...).
    One,
    /// `nplurals=2; plural=(n != 1)` (English, Italian, German, Spanish, ...).
    NotOne,
    /// `nplurals=2; plural=(n > 1)` (French, Brazilian Portuguese).
    MoreThanOne,
    /// Arabic's six forms.
    Arabic,
}

impl PluralRule {
    fn parse(header: &str) -> Result<Self, Error> {
        let compact: String = header.chars().filter(|c| !c.is_whitespace()).collect();
        let compact = compact.trim_end_matches(';');
        Ok(match compact {
            "nplurals=1;plural=0" => Self::One,
            "nplurals=2;plural=(n!=1)" | "nplurals=2;plural=n!=1" => Self::NotOne,
            "nplurals=2;plural=(n>1)" | "nplurals=2;plural=n>1" => Self::MoreThanOne,
            "nplurals=6;plural=(n==0?0:n==1?1:n==2?2:n%100>=3&&n%100<=10?3:n%100>=11?4:5)"
            | "nplurals=6;plural=n==0?0:n==1?1:n==2?2:n%100>=3&&n%100<=10?3:n%100>=11?4:5" => Self::Arabic,
            other => return Err(Error::UnknownPluralRule(other.to_string())),
        })
    }

    /// The index of the form for `n`.
    pub fn index(self, n: u64) -> usize {
        match self {
            Self::One => 0,
            Self::NotOne => usize::from(n != 1),
            Self::MoreThanOne => usize::from(n > 1),
            Self::Arabic => match (n, n % 100) {
                (0, _) => 0,
                (1, _) => 1,
                (2, _) => 2,
                (_, 3..=10) => 3,
                (_, 11..) => 4,
                _ => 5,
            },
        }
    }
}

/// One language's translations. An empty catalog returns every message id unchanged,
/// which is English.
#[derive(Debug)]
pub struct Catalog {
    /// Key: `msgid`, or `msgctxt` + EOT + `msgid`. Value: the plural forms, one for a
    /// message without a plural.
    messages: HashMap<String, Vec<String>>,
    plural: PluralRule,
    language: Option<String>,
}

impl Default for Catalog {
    fn default() -> Self {
        Self::empty()
    }
}

impl Catalog {
    pub fn empty() -> Self {
        Self { messages: HashMap::new(), plural: PluralRule::NotOne, language: None }
    }

    /// Parses a `.mo` file of either byte order. Every offset is bounds-checked: a
    /// truncated or hostile file is an error, never a panic.
    pub fn parse(bytes: &[u8]) -> Result<Self, Error> {
        let word_at = |offset: usize, big_endian: bool| -> Result<u32, Error> {
            let raw: [u8; 4] = bytes
                .get(offset..offset.checked_add(4).ok_or(Error::Malformed("offset overflow"))?)
                .and_then(|slice| slice.try_into().ok())
                .ok_or(Error::Malformed("truncated"))?;
            Ok(if big_endian { u32::from_be_bytes(raw) } else { u32::from_le_bytes(raw) })
        };
        let big_endian = match (word_at(0, false)?, word_at(0, true)?) {
            (MAGIC, _) => false,
            (_, MAGIC) => true,
            _ => return Err(Error::Malformed("not a .mo file")),
        };
        let word = |offset: usize| word_at(offset, big_endian).map(|value| value as usize);

        let revision = word_at(4, big_endian)?;
        if revision >> 16 != 0 {
            return Err(Error::UnsupportedRevision(revision));
        }
        let (count, originals, translations) = (word(8)?, word(12)?, word(16)?);

        let text = |table: usize, index: usize| -> Result<&str, Error> {
            let entry = index
                .checked_mul(8)
                .and_then(|offset| offset.checked_add(table))
                .ok_or(Error::Malformed("table overflow"))?;
            let (length, start) = (word(entry)?, word(entry + 4)?);
            let end = start.checked_add(length).ok_or(Error::Malformed("string overflow"))?;
            let raw = bytes.get(start..end).ok_or(Error::Malformed("string out of bounds"))?;
            std::str::from_utf8(raw).map_err(|_| Error::NotUtf8)
        };

        let mut catalog = Self::empty();
        for index in 0..count {
            let original = text(originals, index)?;
            let translation = text(translations, index)?;
            if original.is_empty() {
                catalog.read_header(translation)?;
                continue;
            }
            // A plural entry stores "msgid NUL msgid_plural"; the key is the singular.
            let key = original.split('\0').next().unwrap_or(original);
            catalog.messages.insert(key.to_string(), translation.split('\0').map(str::to_string).collect());
        }
        Ok(catalog)
    }

    fn read_header(&mut self, header: &str) -> Result<(), Error> {
        for line in header.lines() {
            let Some((name, value)) = line.split_once(':') else { continue };
            let value = value.trim();
            match name.trim().to_ascii_lowercase().as_str() {
                "content-type" => {
                    let charset = value.rsplit("charset=").next().unwrap_or("");
                    if !charset.eq_ignore_ascii_case("utf-8") {
                        return Err(Error::NotUtf8);
                    }
                }
                "plural-forms" => self.plural = PluralRule::parse(value)?,
                "language" if !value.is_empty() => self.language = Some(value.to_string()),
                _ => {}
            }
        }
        Ok(())
    }

    /// The catalog of `domain` for the first language of `languages` that has one under
    /// `locale_dir`. A catalog that exists and cannot be read is an error, not a reason
    /// to fall through silently to the next language.
    pub fn find(locale_dir: &Path, domain: &str, languages: &[String]) -> Result<Self, (PathBuf, Error)> {
        for language in languages {
            let path = locale_dir.join(language).join("LC_MESSAGES").join(format!("{domain}.mo"));
            if let Ok(bytes) = std::fs::read(&path) {
                let mut catalog = Self::parse(&bytes).map_err(|error| (path, error))?;
                catalog.language.get_or_insert_with(|| language.clone());
                return Ok(catalog);
            }
        }
        Ok(Self::empty())
    }

    /// What a program calls at start: the override file when [`OVERRIDE_VARIABLE`] names
    /// one, otherwise the catalog for the language of the environment, of
    /// `/etc/locale.conf`, or none. The error says which file was unreadable; the caller
    /// logs it and carries on in English with [`Catalog::empty`].
    pub fn load(domain: &str) -> Result<Self, (PathBuf, Error)> {
        if let Some(path) = std::env::var_os(OVERRIDE_VARIABLE).filter(|value| !value.is_empty()) {
            let path = PathBuf::from(path);
            let bytes = std::fs::read(&path).map_err(|_| (path.clone(), Error::Malformed("unreadable override file")))?;
            return Self::parse(&bytes).map_err(|error| (path, error));
        }
        let system = std::fs::read_to_string(SYSTEM_LOCALE_FILE).ok();
        let languages = languages(|name| std::env::var(name).ok(), system.as_deref());
        Self::find(Path::new(LOCALE_DIR), domain, &languages)
    }

    pub fn tr<'a>(&'a self, msgid: &'a str) -> &'a str {
        self.form(msgid, 0).unwrap_or(msgid)
    }

    pub fn tr_n<'a>(&'a self, msgid: &'a str, msgid_plural: &'a str, n: u64) -> &'a str {
        match self.form(msgid, self.plural.index(n)) {
            Some(translated) => translated,
            None if n == 1 => msgid,
            None => msgid_plural,
        }
    }

    /// A message with a context (`msgctxt`), for a word that translates differently in
    /// two places.
    pub fn tr_c<'a>(&'a self, context: &str, msgid: &'a str) -> &'a str {
        let key = format!("{context}{CONTEXT_SEPARATOR}{msgid}");
        // The borrow of `key` ends here; the result borrows from `self` or `msgid`.
        match self.messages.get(&key).and_then(|forms| forms.first()) {
            Some(translated) if !translated.is_empty() => translated,
            _ => msgid,
        }
    }

    fn form(&self, msgid: &str, index: usize) -> Option<&str> {
        let forms = self.messages.get(msgid)?;
        forms.get(index).map(String::as_str).filter(|text| !text.is_empty())
    }

    /// The language of the catalog in use; `None` for the untranslated English.
    pub fn language(&self) -> Option<&str> {
        self.language.as_deref()
    }

    /// Whether the language in use is written right to left.
    pub fn is_rtl(&self) -> bool {
        self.language().map(primary_language).is_some_and(|language| RTL_LANGUAGES.contains(&language))
    }
}

fn primary_language(locale: &str) -> &str {
    locale.split(['_', '.', '@']).next().unwrap_or(locale)
}

/// The catalog directories to try, most specific first: `it_IT.UTF-8@euro` gives
/// `["it_IT", "it"]`. The locale is the first non-empty of `LC_ALL`, `LC_MESSAGES`,
/// `LANG` in the environment, else `LANG` of `/etc/locale.conf`. `C` and `POSIX` mean
/// untranslated.
pub fn languages(env: impl Fn(&str) -> Option<String>, system_locale_conf: Option<&str>) -> Vec<String> {
    let from_env = ["LC_ALL", "LC_MESSAGES", "LANG"].into_iter().find_map(|name| env(name).filter(|value| !value.is_empty()));
    let from_system = || {
        system_locale_conf?.lines().find_map(|line| {
            let value = line.trim().strip_prefix("LANG=")?;
            Some(value.trim_matches('"').to_string())
        })
    };
    let Some(locale) = from_env.or_else(from_system) else { return Vec::new() };
    let base = locale.split(['.', '@']).next().unwrap_or("");
    if base.is_empty() || base == "C" || base == "POSIX" {
        return Vec::new();
    }
    let mut found = vec![base.to_string()];
    let primary = primary_language(base);
    if primary != base {
        found.push(primary.to_string());
    }
    found
}
```

Run: `cargo-in-rig test -p athanor-i18n && cargo-in-rig clippy -p athanor-i18n --all-targets -- -D warnings`
Expected: `10 passed`; clippy clean. (The `expect` calls are in tests only.)

- [ ] **Step 4: The greeter's side**

Create `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/src/i18n.rs`:

```rust
//! The greeter's translations: one catalog for the life of the process, read by
//! athanor-i18n. No setlocale(), no textdomain(): nothing process-global changes in the
//! process that reads the password (doc_shell.md, SH13; decision of 2026-09-19).

use std::sync::OnceLock;

use athanor_i18n::Catalog;

pub const DOMAIN: &str = "athanor-greeter-ui";

static CATALOG: OnceLock<Catalog> = OnceLock::new();

/// Loads the catalog for the language of the environment, or of /etc/locale.conf. A
/// catalog that cannot be read is logged and the greeter speaks English: a greeter in
/// the wrong language still lets the user in.
pub fn init() {
    let catalog = Catalog::load(DOMAIN).unwrap_or_else(|(path, err)| {
        tracing::error!(path = %path.display(), error = %err, "translations are unavailable");
        Catalog::empty()
    });
    tracing::info!(language = catalog.language().unwrap_or("en (message ids)"), "translations loaded");
    // A second call keeps the first catalog; there is none in this program.
    let _already_set = CATALOG.set(catalog);
}

fn catalog() -> &'static Catalog {
    CATALOG.get_or_init(Catalog::empty)
}

/// The translation of `msgid`.
pub fn tr(msgid: &str) -> String {
    catalog().tr(msgid).to_string()
}

/// The translation of `msgid` with `{key}` replaced by `value`. Translators move the
/// placeholder freely; a value is never part of a message id.
pub fn tr_with(msgid: &str, key: &str, value: &str) -> String {
    catalog().tr(msgid).replace(&format!("{{{key}}}"), value)
}

/// Whether the language in use is written right to left.
pub fn is_rtl() -> bool {
    catalog().is_rtl()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn without_a_catalog_the_message_id_is_the_text() {
        assert_eq!(tr("Shut down"), "Shut down");
        assert!(!is_rtl());
    }

    #[test]
    fn the_placeholder_is_replaced_and_nothing_else() {
        assert_eq!(tr_with("Password for {name}", "name", "Ada {x}"), "Password for Ada {x}");
    }
}
```

In `src/main.rs` add `mod i18n;` and, directly after the tracing subscriber is initialised, `i18n::init();`. Add the path dependency to the crate's `Cargo.toml`.

Run: `cargo-in-rig test -p athanor-greeter-ui i18n`
Expected: `2 passed`. (`tr`, `tr_with` and `is_rtl` have no caller until Task 16; to keep the `-D warnings` gate green in between, this task's commit and Task 16's are pushed together, or the three functions carry `#[allow(dead_code)]` with the comment "used from Task 16 of the 1a plan" that Task 16 removes. Prefer pushing together.)

- [ ] **Step 5: The extraction script and the catalogs**

Create `po/POTFILES.in`:

```
src/ui.rs
src/auth.rs
```

Create `po/update.sh` (mode 0755):

```bash
#!/usr/bin/env bash
# update.sh - regenerates the template from the sources and merges it into every
# catalog. Needs GNU gettext 0.24 or later (xgettext --language=Rust); the rig's build
# image has 0.25. Run after adding or changing a tr()/tr_with() call.
set -euo pipefail
here=$(dirname "${BASH_SOURCE[0]}")
crate=$here/..
xgettext --language=Rust --keyword=tr --keyword=tr_with --from-code=UTF-8 --add-comments=TRANSLATORS \
    --package-name=athanor-greeter-ui --msgid-bugs-address=forge@athanor.os --no-wrap --sort-by-file \
    --directory="$crate" --files-from="$here/POTFILES.in" --output="$here/athanor-greeter-ui.pot"
# The creation date would make every run a diff.
sed -i '/^"POT-Creation-Date:/d' "$here/athanor-greeter-ui.pot"
for catalog in "$here"/*.po; do
    msgmerge --update --backup=none --no-wrap "$catalog" "$here/athanor-greeter-ui.pot"
done
```

Create `po/it.po` (the header, then one entry per message id of Task 16; `update.sh` fills in the source references). The `Plural-Forms` line must be one of the spellings `athanor_i18n::PluralRule` knows:

```po
msgid ""
msgstr ""
"Project-Id-Version: athanor-greeter-ui\n"
"Report-Msgid-Bugs-To: forge@athanor.os\n"
"Language: it\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

msgid "Not verified"
msgstr "Non verificato"

msgid "The system image has not been verified yet."
msgstr "L'immagine di sistema non è ancora stata verificata."

msgid "Password"
msgstr "Password"

msgid "Password for {name}"
msgstr "Password di {name}"

msgid "Sign in"
msgstr "Accedi"

msgid "Signing in…"
msgstr "Accesso in corso…"

msgid "Sign-in failed: {reason}"
msgstr "Accesso non riuscito: {reason}"

msgid "The login service cannot be reached."
msgstr "Il servizio di accesso non è raggiungibile."

msgid "Checking your credentials…"
msgstr "Verifica delle credenziali…"

msgid "The login service gave an unexpected answer."
msgstr "Il servizio di accesso ha dato una risposta inattesa."

msgid "Too many authentication steps."
msgstr "Troppi passaggi di autenticazione."

msgid "High contrast"
msgstr "Contrasto elevato"

msgid "Keyboard layout: {layout}"
msgstr "Disposizione della tastiera: {layout}"

msgid "Suspend"
msgstr "Sospendi"

msgid "Restart"
msgstr "Riavvia"

msgid "Shut down"
msgstr "Spegni"

#. TRANSLATORS: the date under the clock, in g_date_time_format() syntax:
#. %A weekday, %-d day of the month, %B month.
msgid "%A %-d %B"
msgstr "%A %-d %B"
```

Create `po/en.po` with the same header (`"Language: en\n"`) and every `msgstr` equal to its `msgid`. English ships as a catalog, not only as message ids, so that English copy can be corrected without touching a message id and invalidating the other catalogs.

`po/athanor-greeter-ui.pot` is produced in Task 16, Step 6, when the calls exist.

- [ ] **Step 6: Ship the catalogs**

In `forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec`: append `gettext` to `BuildRequires`; at the end of `%build`:

```spec
for catalog in forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/po/*.po; do
    lang=$(basename "$catalog" .po)
    mkdir -p "locale-build/$lang/LC_MESSAGES"
    msgfmt --check --output-file="locale-build/$lang/LC_MESSAGES/athanor-greeter-ui.mo" "$catalog"
done
```

at the end of `%install`:

```spec
mkdir -p %{buildroot}/usr/share/locale
cp -a locale-build/. %{buildroot}/usr/share/locale/
rm -rf locale-build
```

and in `%files`:

```spec
%lang(it) /usr/share/locale/it/LC_MESSAGES/athanor-greeter-ui.mo
%lang(en) /usr/share/locale/en/LC_MESSAGES/athanor-greeter-ui.mo
```

`msgfmt --check` fails the build on a catalog whose placeholders or format directives disagree with the message id, and writes UTF-8, the only charset the reader accepts. The builder has `gettext` (`flake.nix`, build-tools). The catalogs are readable in the greeter's sandbox because the wrapper binds `/usr` read-only. Add `Requires: athanor-calmo cosmic-icon-theme` as well: the greeter uses the seal icons and names its other icons from the Cosmic theme (Task 16). `Release: 2`, changelog "Italian and English catalogs, read by athanor-i18n."

- [ ] **Step 7: Give the greeter the system's locale**

Our own strings no longer need it: `athanor-i18n` reads `/etc/locale.conf` itself. GTK's own strings (the Caps Lock warning of the password field) and the weekday and month names of `g_date_time_format` still come from glibc, and greetd passes a session only what PAM builds, which does not include `/etc/locale.conf`. In `forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-greeter-session`, after the `XDG_RUNTIME_DIR` block, add:

```sh

# The greeter speaks the system's language. Its own strings find /etc/locale.conf by
# themselves (athanor-i18n); GTK's strings and the date's weekday and month names come
# from glibc, which needs the variables. systemd applies locale.conf to services, but
# greetd hands a session only PAM's environment. The file is systemd's KEY=value format,
# which sh can read; only the locale variables are taken from it.
if [ -r /etc/locale.conf ]; then
    # shellcheck disable=SC1091
    . /etc/locale.conf
    for variable in LANG LANGUAGE LC_MESSAGES LC_TIME; do
        eval "value=\${$variable:-}"
        if [ -n "$value" ]; then
            export "$variable=$value"
        fi
    done
fi
```

`athanor-greeter-client` passes the environment through bubblewrap unchanged (it uses no `--clearenv`). In `athanor-system-config.spec`, `43.fc43` → `44.fc43` with the changelog entry "The greeter session exports the locale of /etc/locale.conf: greetd passes only PAM's environment, which left GTK and the date in the C locale."

Run: `shellcheck -s sh forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-greeter-session && python3 scripts/verify.py specs`
Expected: no findings.

- [ ] **Step 8: Commit (three commits)**

```bash
git add Cargo.toml Cargo.lock system/athanor-i18n
git commit -m "feat(i18n): read gettext .mo catalogs in safe Rust, without glibc's process-global state"
git add forge/specs/athanor-greeter-ui
git commit -m "feat(greeter): add Italian and English catalogs, shipped as .mo files"
git add forge/specs/athanor-system-config
git commit -m "fix(greeter): run the greeter session in the system's locale"
```

### Task 16: Greeter re-skin

**Files:**
- Modify: `forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/src/ui.rs` (rewritten: 585 → about 340 lines)
- Modify: `src/auth.rs` (delete `session_badge` and its two tests; four Italian literals become `tr()` calls)
- Modify: `Cargo.toml` of the crate (`chrono` leaves; `athanor-style` arrives)
- Create: `po/athanor-greeter-ui.pot` (generated)
- Modify: `forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec` (`Release`, changelog), `forge/test/shell/rig.sh` (`greeter-preview`)

**Interfaces:**
- Consumes: `athanor_style::calmo::{Variant, load}` (Task 14); `crate::i18n::{tr, tr_with, is_rtl}` (Task 15); `crate::layer_guard::require_layer_surface` (Task 12); the icon `athanor-seal-attention-symbolic` (Task 5); the CSS classes of Task 3; from the moved code: `crate::auth::{discover_target_user, authenticate_interactive, UserInfo}`, `crate::power::LogindProxy` (`suspend(bool)`, `reboot(bool)`, `power_off(bool)`).
- Produces: `crate::ui::build_ui(app: &gtk4::Application)`; the environment variable `ATHANOR_GREETER_VARIANT` (`light` | `dark` | `light-hc` | `dark-hc`, default `light`); widget names (`set_widget_name`) the AT-SPI check and later packages rely on: `greeter-seal`, `greeter-password`, `greeter-submit`, `greeter-contrast`, `greeter-layout`, `greeter-suspend`, `greeter-restart`, `greeter-shutdown`.

What changes for the user, against the greeter Task 11 moved:

| Was | Becomes | Why |
|---|---|---|
| 190 lines of inline CSS, dark glass | the Calmo sheet of the variant | SH5: tokens are the single source |
| "ATHANOR OS" letter-spaced | "Athanor" wordmark | mockup |
| "🎨 Theme" button connected to nothing | removed | SH1: no facades |
| `Entry`, a reveal button with a Nerd Font glyph, a Caps Lock pill with a Nerd Font glyph, a key controller | `gtk4::PasswordEntry` with its peek icon and its own Caps Lock warning | native widget, correct accessible role, no tofu |
| badge "WAYLAND • ATHANOR-SESSION" | removed | the UX analysis, section 1.15: "Nobody needs this" |
| Italian literals, a hand-written Italian date | gettext, `g_date_time_format` in the locale | SH13 |
| three text pills, white on near-white | three icon chips with accessible names, bottom right | mockup; contrast gate |
| nothing | the seal, top right: exclamation badge, "Not verified" | SH12; constant until 1b-shield |
| nothing | keyboard layout chip from `gdk::Device`, high-contrast toggle | mockup; SH5 |

One departure from the mockup, on purpose: the mockup shows a single power button, which implies a menu. The rig has no input (SH13), so a menu could never be captured or checked there, and a popover on a layer surface is one more thing that can fail on the one surface that must not. Three labelled chips do the same job with nothing to open.

- [ ] **Step 1: The manifest**

In the crate's `Cargo.toml`: delete `chrono = "0.4"` (the date is `glib::DateTime` now, which formats in the locale) and add `athanor-style = { path = "../../../../system/athanor-style" }`.

- [ ] **Step 2: `auth.rs`: no badge, and no Italian literal**

Delete `pub fn session_badge` with its doc comment and the two tests that call it. Keep `SESSION_TYPE`: the session request uses it.

The file carries four user-visible Italian literals, which reach the screen through the error and status labels. Add `use crate::i18n::tr;` and replace:

| Literal | Becomes |
|---|---|
| `"Autenticazione fallita: demone auth irraggiungibile".to_string()` | `tr("The login service cannot be reached.")` |
| `status_cb("Verifica credenziali in corso...")` | `status_cb(&tr("Checking your credentials…"))` |
| `"Risposta inattesa dal comando StartSession".to_string()` | `tr("The login service gave an unexpected answer.")` |
| `"Timeout conversazione PAM (troppi passaggi di autenticazione)".to_string()` | `tr("Too many authentication steps.")` |

Messages that come from PAM through greetd (`auth_message`, `description`) are shown as received: PAM translates them itself.

Run after Step 3: `grep -n "session_badge\|Autenticazione\|Verifica cred\|Risposta inattesa\|Timeout conv" forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/src`
Expected: no output.

- [ ] **Step 3: Rewrite `src/ui.rs`**

```rust
//! The greeter: the first Athanor surface drawn on the Calmo tokens.
//!
//! It reads nothing from COSMIC: the accent is the factory accent, and the variant comes
//! from ATHANOR_GREETER_VARIANT and from the high-contrast toggle (doc_shell.md, SH5).
//! Every interactive widget carries an accessible name and every string goes through
//! gettext (SH13).

use std::rc::Rc;

use athanor_style::calmo::{self, Variant};
use gtk4::accessible::Property;
use gtk4::prelude::*;
use gtk4::{gdk, Align, Application, ApplicationWindow, Box, Button, Image, Label, Orientation, PasswordEntry, ToggleButton};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};

use crate::auth::{authenticate_interactive, discover_target_user, UserInfo};
use crate::i18n::{tr, tr_with};

/// The seal's state. The greeter has no verifier to ask yet: package 1b-shield binds the
/// root-owned trust state file into the sandbox and replaces this constant with what
/// that file says. Until then the only claim the greeter can back is "not verified", so
/// it shows the exclamation badge and never the check (doc_shell.md, SH1 "no facades",
/// SH12 "the shield reports only what a verifier backs").
const SEAL_ICON: &str = "athanor-seal-attention-symbolic";

/// The icons come from the theme the image ships (doc_shell.md, SH5: cosmic-icon-theme
/// stays in stage 1); the seal is ours, installed into hicolor, which every theme inherits.
const ICON_THEME: &str = "Cosmic";

fn initial_variant() -> Variant {
    std::env::var("ATHANOR_GREETER_VARIANT")
        .ok()
        .and_then(|name| Variant::from_name(&name))
        .unwrap_or(Variant::Light)
}

fn named<W: IsA<gtk4::Widget> + IsA<gtk4::Accessible>>(widget: &W, id: &str, label: &str) {
    widget.set_widget_name(id);
    widget.update_property(&[Property::Label(label)]);
}

fn icon_chip(id: &str, icon: &str, label: &str) -> Button {
    let button = Button::builder().icon_name(icon).css_classes(["greeter-chip"]).tooltip_text(label).build();
    named(&button, id, label);
    button
}

fn now_text(format: &str) -> String {
    glib::DateTime::now_local()
        .and_then(|now| now.format(format))
        .map(|text| text.to_string())
        .unwrap_or_default()
}

/// The avatar: the account's picture when there is one, the initial on the accent otherwise.
fn avatar(user: &UserInfo) -> gtk4::Widget {
    if let Some(path) = &user.avatar_path {
        let picture = gtk4::Picture::for_filename(path);
        picture.set_size_request(60, 60);
        picture.set_content_fit(gtk4::ContentFit::Cover);
        picture.set_overflow(gtk4::Overflow::Hidden);
        picture.add_css_class("greeter-avatar");
        picture.set_halign(Align::Center);
        picture.update_property(&[Property::Label(&user.real_name)]);
        return picture.upcast();
    }
    let initial: String = user.real_name.chars().next().map(|c| c.to_uppercase().collect()).unwrap_or_default();
    Label::builder().label(initial).css_classes(["greeter-avatar"]).halign(Align::Center).build().upcast()
}

/// The keyboard layout, read from the seat. Hidden when the seat names none: the chip
/// never shows a constant.
fn layout_chip(display: &gdk::Display) -> Label {
    let chip = Label::builder().css_classes(["greeter-chip"]).visible(false).build();
    chip.set_widget_name("greeter-layout");
    let Some(keyboard) = display.default_seat().and_then(|seat| seat.keyboard()) else {
        return chip;
    };
    let refresh = {
        let chip = chip.clone();
        move |keyboard: &gdk::Device| {
            let names = keyboard.layout_names();
            let active = usize::try_from(keyboard.active_layout_index()).ok().and_then(|index| names.get(index));
            match active {
                Some(name) => {
                    chip.set_label(name);
                    chip.update_property(&[Property::Label(&tr_with("Keyboard layout: {layout}", "layout", name))]);
                    chip.set_visible(true);
                }
                None => chip.set_visible(false),
            }
        }
    };
    refresh(&keyboard);
    keyboard.connect_active_layout_index_notify(refresh.clone());
    keyboard.connect_layout_names_notify(refresh);
    chip
}

fn power_chip(id: &str, icon: &str, label: &str, action: fn(&crate::power::LogindProxy<'static>) -> PowerCall) -> Button {
    let button = icon_chip(id, icon, label);
    button.connect_clicked(move |_| {
        glib::MainContext::default().spawn_local(async move {
            let result = async {
                let connection = zbus::Connection::system().await?;
                let proxy = crate::power::LogindProxy::new(&connection).await?;
                action(&proxy).await
            }
            .await;
            if let Err(err) = result {
                tracing::error!(error = %err, "logind refused the power request");
            }
        });
    });
    button
}

type PowerCall = std::pin::Pin<std::boxed::Box<dyn std::future::Future<Output = zbus::Result<()>>>>;

pub fn build_ui(app: &Application) {
    // The direction comes from the language of the catalog in use, not from a process
    // locale, and has to be set before the first widget exists.
    if crate::i18n::is_rtl() {
        gtk4::Widget::set_default_direction(gtk4::TextDirection::Rtl);
    }

    let window = ApplicationWindow::builder().application(app).title("Athanor").build();
    window.add_css_class("athanor-surface");
    window.add_css_class("athanor-greeter");

    window.init_layer_shell();
    if let Err(reason) = crate::layer_guard::require_layer_surface(&window) {
        // No tracing subscriber may be listening this early in a failing start; stderr
        // reaches the journal through the compositor's systemd-cat.
        eprintln!("athanor-greeter-ui: not a layer surface: {reason}");
        std::process::exit(1);
    }
    window.set_layer(Layer::Overlay);
    window.set_keyboard_mode(KeyboardMode::Exclusive);
    window.set_namespace(Some("greeter"));
    for edge in [Edge::Top, Edge::Bottom, Edge::Left, Edge::Right] {
        window.set_anchor(edge, true);
    }

    let display = gtk4::prelude::WidgetExt::display(&window);
    if let Some(settings) = gtk4::Settings::default() {
        settings.set_gtk_icon_theme_name(Some(ICON_THEME));
    }
    let variant = initial_variant();
    calmo::load(&display, variant);

    // Top: the wordmark on the left, the seal on the right.
    let wordmark = Label::builder().label("Athanor").css_classes(["greeter-wordmark"]).build();
    let seal = Box::builder().orientation(Orientation::Horizontal).spacing(8).css_classes(["greeter-chip"]).build();
    seal.set_widget_name("greeter-seal");
    seal.set_tooltip_text(Some(&tr("The system image has not been verified yet.")));
    let seal_icon = Image::builder().icon_name(SEAL_ICON).css_classes(["athanor-seal"]).build();
    seal_icon.update_property(&[Property::Label(&tr("Not verified"))]);
    seal.append(&seal_icon);
    seal.append(&Label::new(Some(&tr("Not verified"))));
    let top = gtk4::CenterBox::builder().margin_top(12).margin_start(20).margin_end(16).build();
    top.set_start_widget(Some(&wordmark));
    top.set_end_widget(Some(&seal));

    // Centre: the clock, the date, the card.
    let clock = Label::builder().css_classes(["greeter-clock"]).build();
    let date = Label::builder().css_classes(["greeter-date"]).margin_top(8).margin_bottom(34).build();
    let tick = {
        let (clock, date) = (clock.clone(), date.clone());
        move || {
            clock.set_label(&now_text("%H:%M"));
            date.set_label(&now_text(&tr("%A %-d %B")));
        }
    };
    tick();
    glib::timeout_add_seconds_local(1, move || {
        tick();
        glib::ControlFlow::Continue
    });

    let user = discover_target_user();
    let name = Label::builder().label(&user.real_name).css_classes(["greeter-name"]).margin_top(10).margin_bottom(14).build();

    let password = PasswordEntry::builder()
        .placeholder_text(tr("Password"))
        .show_peek_icon(true)
        .hexpand(true)
        .css_classes(["greeter-field"])
        .build();
    let password_label = tr_with("Password for {name}", "name", &user.real_name);
    named(&password, "greeter-password", &password_label);
    if let Some(delegate) = password.delegate() {
        // The text widget inside the entry is the node a screen reader lands on.
        delegate.update_property(&[Property::Label(&password_label)]);
    }
    let submit = Button::builder().icon_name("go-next-symbolic").css_classes(["greeter-submit"]).valign(Align::Center).build();
    named(&submit, "greeter-submit", &tr("Sign in"));
    let field_row = Box::builder().orientation(Orientation::Horizontal).spacing(6).build();
    field_row.append(&password);
    field_row.append(&submit);

    let status = Label::builder().css_classes(["greeter-status"]).margin_top(12).wrap(true).visible(false).build();
    let error = Label::builder().css_classes(["greeter-error"]).margin_top(12).wrap(true).visible(false).build();
    // A failed sign-in is announced, not only painted.
    error.set_accessible_role(gtk4::AccessibleRole::Alert);

    {
        let (status, error) = (status.clone(), error.clone());
        password.connect_changed(move |_| {
            status.set_visible(false);
            error.set_visible(false);
        });
    }

    let sign_in = Rc::new({
        let (app, password, submit, status, error) = (app.clone(), password.clone(), submit.clone(), status.clone(), error.clone());
        move || {
            let secret = password.text().to_string();
            password.set_sensitive(false);
            submit.set_sensitive(false);
            error.set_visible(false);
            status.set_label(&tr("Signing in…"));
            status.set_visible(true);
            let (app, password, submit, status, error) = (app.clone(), password.clone(), submit.clone(), status.clone(), error.clone());
            glib::MainContext::default().spawn_local(async move {
                // PAM's own prompts (a fingerprint reader asking for a touch) are shown as
                // they arrive.
                let progress = status.clone();
                match authenticate_interactive(&secret, &move |message: &str| progress.set_label(message)).await {
                    Ok(()) => app.quit(),
                    Err(reason) => {
                        status.set_visible(false);
                        error.set_label(&tr_with("Sign-in failed: {reason}", "reason", &reason));
                        error.set_visible(true);
                        password.set_text("");
                        password.set_sensitive(true);
                        submit.set_sensitive(true);
                        password.grab_focus();
                    }
                }
            });
        }
    });
    {
        let sign_in = sign_in.clone();
        password.connect_activate(move |_| sign_in());
    }
    submit.connect_clicked(move |_| sign_in());

    let card = Box::builder().orientation(Orientation::Vertical).halign(Align::Center).css_classes(["greeter-card"]).build();
    card.append(&avatar(&user));
    card.append(&name);
    card.append(&field_row);
    card.append(&status);
    card.append(&error);

    let centre = Box::builder().orientation(Orientation::Vertical).halign(Align::Center).valign(Align::Center).vexpand(true).build();
    centre.append(&clock);
    centre.append(&date);
    centre.append(&card);

    // Bottom right: keyboard layout, accessibility, power.
    let contrast = ToggleButton::builder()
        .icon_name("preferences-desktop-accessibility-symbolic")
        .css_classes(["greeter-chip"])
        .active(variant.is_high_contrast())
        .build();
    named(&contrast, "greeter-contrast", &tr("High contrast"));
    contrast.set_tooltip_text(Some(&tr("High contrast")));
    {
        let display = display.clone();
        contrast.connect_toggled(move |toggle| calmo::load(&display, variant.with_high_contrast(toggle.is_active())));
    }

    let bottom = Box::builder().orientation(Orientation::Horizontal).spacing(6).halign(Align::End).margin_bottom(14).margin_end(16).build();
    bottom.append(&layout_chip(&display));
    bottom.append(&contrast);
    bottom.append(&power_chip("greeter-suspend", "system-suspend-symbolic", &tr("Suspend"), |p| std::boxed::Box::pin(p.suspend(true))));
    bottom.append(&power_chip("greeter-restart", "system-reboot-symbolic", &tr("Restart"), |p| std::boxed::Box::pin(p.reboot(true))));
    bottom.append(&power_chip("greeter-shutdown", "system-shutdown-symbolic", &tr("Shut down"), |p| std::boxed::Box::pin(p.power_off(true))));

    let root = Box::builder().orientation(Orientation::Vertical).hexpand(true).vexpand(true).build();
    root.append(&top);
    root.append(&centre);
    root.append(&bottom);
    window.set_child(Some(&root));

    // The first key pressed is the first character of the password.
    password.grab_focus();
    window.present();
}
```

Two places where the compiler has the last word, with what to do for each:

- `power_chip` borrows the proxy inside a boxed future. If the borrow checker rejects `action(&proxy)` because the future outlives the borrow, replace the function pointer with an enum and a match, which needs no boxing:

  ```rust
  #[derive(Clone, Copy)]
  enum Power { Suspend, Restart, ShutDown }
  // inside the spawned future:
  let proxy = crate::power::LogindProxy::new(&connection).await?;
  match which {
      Power::Suspend => proxy.suspend(true).await,
      Power::Restart => proxy.reboot(true).await,
      Power::ShutDown => proxy.power_off(true).await,
  }
  ```

  and drop the `PowerCall` alias.
- `gdk::Device::layout_names` and `connect_layout_names_notify` exist from gtk4 0.9 with the feature `v4_18` (set in Task 10). If the generated binding returns `Option<Vec<GString>>` in 0.11.4, flatten it with `.unwrap_or_default()`.

All icon names used here exist in `/usr/share/icons/Cosmic` of `cosmic-icon-theme` 1.8 (checked on the maintainer's machine): `go-next-symbolic`, `preferences-desktop-accessibility-symbolic`, `system-suspend-symbolic`, `system-reboot-symbolic`, `system-shutdown-symbolic`. The peek and Caps Lock icons of `PasswordEntry` are built into GTK.

- [ ] **Step 4: Build under the lint gate**

Run: `bash forge/test/shell/rig.sh build-greeter`
Expected: clippy clean, tests pass, release build, link-order check silent.

- [ ] **Step 5: Look at it**

Add to `forge/test/shell/rig.sh`, with the header line `#   rig.sh greeter-preview   one capture of the greeter per variant, for the eye`:

```bash
greeter-preview)
    for variant in light dark light-hc dark-hc; do
        in_rig "$(rig_image)" env ATHANOR_GREETER_VARIANT="$variant" ATHANOR_LOGIN_USER=ermete RIG_LOCALE=en_US.UTF-8 \
            dbus-run-session -- /repo/forge/test/shell/scene.sh 1920 1080 1.0 "greeter-preview-$variant" -- \
            /out/bin/athanor-greeter-ui
    done
    echo "look at $out/greeter-preview-*.png"
    ;;
```

Run: `bash forge/test/shell/rig.sh greeter-preview`
Expected: four PNGs. Compare `greeter-preview-light.png` with the mockup's "Accesso" section: hearth discs from the bottom right, "Athanor" top left, the seal chip with an amber exclamation badge and "Not verified" top right, a 74 px light clock reading 10:00, "Friday 18 September", the card with an indigo disc bearing "E", "Ermete", the field with an indigo border and the arrow button, four chips bottom right (no keyboard chip: the rig's seat has no keyboard). No title bar anywhere: a title bar means the layer guard was bypassed. 

- [ ] **Step 5b: Show the maintainer, the high-contrast variants above all**

This is a gate, not a courtesy. `greeter-preview-light-hc.png` and `greeter-preview-dark-hc.png` show a variant **nobody has approved**: high contrast is required by SH5 and absent from the mockup, and this plan derived it by one rule in `tokens.toml` (secondary inks one step stronger, hairlines at 3:1, the accent further from the surface). Send the maintainer the four captures, the two high-contrast ones side by side with their normal variants, and ask specifically whether the derived high-contrast look is accepted. Do not start Task 18 before the answer: a change to the rule changes `tokens.toml`, every generated sheet and therefore every golden. If the maintainer changes the rule, edit the `[variant.*-hc.color]` tables, run `generate.py all`, the Calmo tests and `contrast.py` (the monotonic test keeps the variant honest), rebuild, and show again.

- [ ] **Step 6: Generate the template and check the catalogs**

Run: `podman run --rm --security-opt label=disable -v "$PWD:/repo" -w /repo localhost/athanor-shell-rig:build bash forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/po/update.sh`
Expected: `po/athanor-greeter-ui.pot` with 17 message ids; `it.po` and `en.po` gain source references and lose nothing.

Run: `podman run --rm --security-opt label=disable -v "$PWD:/repo:ro" -w /repo localhost/athanor-shell-rig:build bash -c 'for c in forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/po/*.po; do msgfmt --check --statistics -o /dev/null "$c"; done'`
Expected: twice `17 translated messages.`, no fuzzy, no untranslated.

- [ ] **Step 7: Release and changelog**

In `forge/specs/athanor-greeter-ui/athanor-greeter-ui.spec`, `Release: 3`, and at the top of `%changelog`:

```
* Sat Sep 19 2026 Athanor Forge <forge@athanor.os> - 1.0.0-3
- The greeter is drawn on the Calmo tokens (doc_shell.md, SH5): the generated GTK4
  stylesheet of the variant replaces the inline sheet, in light, dark and their
  high-contrast forms, chosen by ATHANOR_GREETER_VARIANT and by a high-contrast toggle.
  It reads nothing from COSMIC.
- Every interactive widget has an accessible name, a failed sign-in is an alert, every
  string is translated through athanor-i18n, and the layout mirrors for a right-to-left
  language.
- The seal is shown top right with the exclamation badge and "Not verified". This is a
  constant on purpose: the greeter has no verifier to ask until the shield package
  binds the trust state file into its sandbox, and it never shows the check meanwhile.
- The password field is GtkPasswordEntry: its peek icon and Caps Lock warning replace
  the hand-made ones, which drew Nerd Font glyphs no shipped font has.
- Removed: the "Theme" button, which was connected to nothing, and the session badge
  under the user name.
- The keyboard layout chip shows what the seat reports and is hidden when it reports none.
```

- [ ] **Step 8: Commit**

```bash
git add forge/specs/athanor-greeter-ui forge/test/shell/rig.sh
git commit -m "feat(greeter): draw the greeter on the Calmo tokens with accessible names and gettext"
```

### Task 17: AT-SPI check in the rig

**Files:**
- Create: `forge/test/shell/atspi_check.py`
- Test: `forge/test/shell/tests/test_atspi_check.py`
- Modify: `forge/test/shell/rig.sh` (sub-command `atspi`), `.github/workflows/shell-surfaces.yml`, `.github/workflows/call-lint.yml`

**Interfaces:**
- Consumes: `/out/bin/athanor-greeter-ui` (Task 12), the widget names of Task 16, `scene.sh` with `RIG_HOLD`.
- Produces:
  - `atspi_check.problems(nodes: list[Node], expected: int) -> list[str]` with `Node = (role: str, name: str, showing: bool)`; pure, unit-tested.
  - command `atspi_check.py <application-name> <minimum-interactive>`, exit 1 on a problem, tree dump on stdout.
  - `rig.sh atspi greeter`.

- [ ] **Step 1: Write the failing test**

Create `forge/test/shell/tests/test_atspi_check.py`:

```python
"""Unit tests of the pure part of forge/test/shell/atspi_check.py
(python3 -B -m unittest discover -s forge/test/shell/tests -v)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atspi_check as check

NAMED = [("push button", "Sign in", True), ("password text", "Password for Ermete", True),
         ("toggle button", "High contrast", True), ("label", "", True)]


class ProblemsTest(unittest.TestCase):
    def test_named_controls_pass(self):
        self.assertEqual(check.problems(NAMED, 3), [])

    def test_an_unnamed_control_is_reported_with_its_role(self):
        found = check.problems(NAMED + [("push button", " ", True)], 3)
        self.assertEqual(len(found), 1)
        self.assertIn("push button", found[0])

    def test_a_hidden_control_is_not_required_to_have_a_name(self):
        self.assertEqual(check.problems(NAMED + [("push button", "", False)], 3), [])

    def test_too_few_controls_means_the_tree_was_not_there(self):
        found = check.problems([("label", "x", True)], 6)
        self.assertEqual(len(found), 1)
        self.assertIn("0 interactive", found[0])


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -B -m unittest discover -s forge/test/shell/tests -v`
Expected: `ModuleNotFoundError: No module named 'atspi_check'`.

- [ ] **Step 2: Write the check**

Create `forge/test/shell/atspi_check.py` (mode 0755):

```python
#!/usr/bin/python3
"""atspi_check.py <application-name> <minimum-interactive>

doc_shell.md, SH13: "every interactive widget exposes a role and a name in the AT-SPI
tree". Walks the tree of one application on the accessibility bus and fails when a
showing interactive widget has no name, or when fewer interactive widgets than expected
are found, which is what an empty or missing tree looks like.
"""
import sys
import time

INTERACTIVE = {"push button", "toggle button", "check box", "radio button", "password text", "entry",
               "text", "combo box", "slider", "spin button", "link", "menu item", "switch"}


def problems(nodes, expected):
    """nodes: [(role, name, showing)]."""
    found = []
    interactive = [(role, name) for role, name, showing in nodes if showing and role in INTERACTIVE]
    for role, name in interactive:
        if not name.strip():
            found.append(f"a showing '{role}' has no accessible name")
    if len(interactive) < expected:
        found.append(f"{len(interactive)} interactive widget(s) in the tree, expected at least {expected}: "
                     f"the accessibility tree is missing or incomplete")
    return found


def walk(accessible, Atspi, depth=0, out=None):
    out = [] if out is None else out
    states = accessible.get_state_set()
    out.append((accessible.get_role_name(), accessible.get_name() or "", states.contains(Atspi.StateType.SHOWING), depth))
    for index in range(accessible.get_child_count()):
        child = accessible.get_child_at_index(index)
        if child is not None:
            walk(child, Atspi, depth + 1, out)
    return out


def find_application(Atspi, name, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        desktop = Atspi.get_desktop(0)
        for index in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(index)
            if app is not None and app.get_name() == name:
                return app
        time.sleep(0.5)
    return None


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    app = find_application(Atspi, argv[0])
    if app is None:
        print(f"no application named {argv[0]!r} on the accessibility bus", file=sys.stderr)
        return 1
    tree = walk(app, Atspi)
    for role, name, showing, depth in tree:
        print(f"{'  ' * depth}{role}: {name!r}{'' if showing else ' (hidden)'}")
    found = problems([(role, name, showing) for role, name, showing, _ in tree], int(argv[1]))
    for line in found:
        print(f"FAIL {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Run: `python3 -B -m unittest discover -s forge/test/shell/tests -v`
Expected: `Ran 4 tests` … `OK`. Add the discovery line to the "Forge scripts (unit tests)" step of `call-lint.yml`:

```yaml
          python3 -B -m unittest discover -s forge/test/shell/tests -v
```

- [ ] **Step 3: Run it against the greeter**

Add to `forge/test/shell/rig.sh`, with the header line `#   rig.sh atspi greeter      every interactive widget has a role and a name`:

```bash
atspi)
    [ "${2:-}" = greeter ] || { echo "rig.sh atspi: unknown surface '${2:-}'" >&2; exit 2; }
    # A screen reader announces itself by setting IsEnabled; GTK exports its tree then.
    # The greeter has 6 interactive widgets: password, sign in, contrast, three power chips.
    in_rig "$(rig_image)" env GTK_A11Y=atspi ATHANOR_LOGIN_USER=ermete RIG_LOCALE=en_US.UTF-8 RIG_SETTLE=6 \
        RIG_HOLD="python3 /repo/forge/test/shell/atspi_check.py athanor-greeter-ui 6" \
        dbus-run-session -- /repo/forge/test/shell/scene.sh 1280 800 1.0 atspi-greeter -- \
        bash -c 'busctl --user set-property org.a11y.Bus /org/a11y/bus org.a11y.Status IsEnabled b true \
                 && exec /out/bin/athanor-greeter-ui'
    ;;
```

Run: `bash forge/test/shell/rig.sh atspi greeter`
Expected: the tree, with `password text: 'Password for Ermete'`, `push button: 'Sign in'`, `toggle button: 'High contrast'`, `push button: 'Suspend'`, `'Restart'`, `'Shut down'`, and exit 0.

- **Outcome B, `no application named 'athanor-greeter-ui'`:** print the names the bus has (`python3 -c` with the loop of `find_application`, printing `app.get_name()`), and use the one GTK registered (it derives it from `g_get_prgname()`); change the argument in `rig.sh`, not the check.
- **Outcome C, an unnamed `password text` or `text`:** the node is `PasswordEntry`'s inner text widget; Task 16 already labels `password.delegate()`. If GTK 4.20 exposes yet another inner node, give the `PasswordEntry` the role's label through `Property::Label` on that node as well and say in the comment which GTK version needed it.

To see the check bite: remove the `named(&submit, …)` line in `ui.rs`, rebuild, run: `FAIL a showing 'push button' has no accessible name`. Restore it.

- [ ] **Step 4: Add it to the workflow's `greeter` job, after "Layer-surface guard"**

```yaml
      - name: Accessibility tree of the greeter
        run: bash forge/test/shell/rig.sh atspi greeter
```

Run: `actionlint .github/workflows/shell-surfaces.yml .github/workflows/call-lint.yml && python3 scripts/verify.py workflows && shellcheck forge/test/shell/rig.sh`
Expected: no findings.

- [ ] **Step 5: Commit**

```bash
git add forge/test/shell/atspi_check.py forge/test/shell/tests forge/test/shell/rig.sh .github/workflows
git commit -m "test(greeter): require a role and a name for every control in the AT-SPI tree"
```

### Task 18: The 12 surface cases, goldens and the workflow

**Files:**
- Create: `forge/test/shell/cases.py`, `forge/test/shell/compare.py`
- Test: `forge/test/shell/tests/test_cases.py`, `forge/test/shell/tests/test_compare.py`
- Create: `forge/test/shell/locale/de.po`, `forge/test/shell/locale/make_pseudo_rtl.py`
- Create: `forge/test/shell/rig-image.digest`, `forge/test/shell/golden/greeter/*.png` (12 files)
- Modify: `forge/test/shell/rig.sh` (`surface`, `update-goldens`), `.github/workflows/shell-surfaces.yml`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `cases.surface_cases(surface: str) -> list[Case]`, `Case = (tag, variant, scale, locale, catalog)`; command `cases.py greeter` prints one case per line, tab-separated. `locale` is the case's `LC_ALL` (the date, GTK's own strings); `catalog` is the file the case hands to `ATHANOR_I18N_CATALOG`, `-` for none.
  - `compare.TOLERANCE = 64`, `compare.parse_ae(text: str) -> int`, `compare.verdict(differing: int) -> bool`; command `compare.py <golden-dir> <actual-dir> <tag>…`, exit 1 when a case differs by more than the tolerance or a golden is missing; writes `<actual-dir>/<tag>-diff.png` for a failing case.
  - `rig.sh surface greeter`, `rig.sh update-goldens greeter`.

- [ ] **Step 1: Failing tests of the matrix and of the comparison**

Create `forge/test/shell/tests/test_cases.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cases


class CasesTest(unittest.TestCase):
    def test_the_greeter_has_the_twelve_cases_of_sh13(self):
        found = cases.surface_cases("greeter")
        self.assertEqual(len(found), 12)
        self.assertEqual(len({c.tag for c in found}), 12)
        self.assertEqual({c.scale for c in found}, {"1.0", "1.5"})
        self.assertEqual({c.variant for c in found}, {"light", "dark"})
        self.assertEqual({c.locale for c in found}, {"en_US.UTF-8", "de_DE.UTF-8", "ar_EG.UTF-8"})
        self.assertEqual({c.catalog for c in found}, {"-", "de.mo", "rtl.mo"})

    def test_tags_are_file_names(self):
        for case in cases.surface_cases("greeter"):
            self.assertRegex(case.tag, r"^greeter-(light|dark)-(1\.0|1\.5)-(en|de|rtl)$")

    def test_an_unknown_surface_is_an_error(self):
        with self.assertRaises(KeyError):
            cases.surface_cases("launcher")


if __name__ == "__main__":
    unittest.main()
```

Create `forge/test/shell/tests/test_compare.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import compare


class CompareTest(unittest.TestCase):
    def test_imagemagick_prints_the_count_in_several_shapes(self):
        self.assertEqual(compare.parse_ae("0"), 0)
        self.assertEqual(compare.parse_ae("17 (0.000259)"), 17)
        self.assertEqual(compare.parse_ae("1.15975e+09 (1.15975e+09)"), 1159750000)

    def test_garbage_is_an_error_not_a_pass(self):
        with self.assertRaises(ValueError):
            compare.parse_ae("compare: unable to open image")

    def test_the_tolerance_is_sixty_four_pixels(self):
        self.assertEqual(compare.TOLERANCE, 64)
        self.assertTrue(compare.verdict(64))
        self.assertFalse(compare.verdict(65))


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -B -m unittest discover -s forge/test/shell/tests -v`
Expected: `ModuleNotFoundError` for `cases` and for `compare`.

- [ ] **Step 2: Implement both**

Create `forge/test/shell/cases.py`:

```python
#!/usr/bin/python3
"""The surface cases of doc_shell.md, SH13: scale {1.0, 1.5} x theme {light, dark} x
text {English, German for length, a right-to-left pseudo-locale}.

    cases.py <surface>      one case per line: tag, variant, scale, locale, catalog (tab-separated)
"""
import sys
from collections import namedtuple
from itertools import product

Case = namedtuple("Case", "tag variant scale locale catalog")

# short name -> (LC_ALL, catalog handed to ATHANOR_I18N_CATALOG). Our own strings come
# from the catalog file, read by athanor-i18n, whatever the process locale is; LC_ALL
# gives the case its date and GTK's own strings. English is the message ids: no catalog.
# German and the right-to-left pseudo-language are catalogs of the test; the product
# ships it and en. The pseudo-language declares "Language: ar", which is what makes the
# greeter mirror.
LOCALES = {"en": ("en_US.UTF-8", "-"), "de": ("de_DE.UTF-8", "de.mo"), "rtl": ("ar_EG.UTF-8", "rtl.mo")}
SURFACES = {"greeter": {"variants": ("light", "dark"), "scales": ("1.0", "1.5")}}


def surface_cases(surface):
    spec = SURFACES[surface]
    return [Case(f"{surface}-{variant}-{scale}-{short}", variant, scale, locale, catalog)
            for variant, scale, (short, (locale, catalog)) in product(spec["variants"], spec["scales"], LOCALES.items())]


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SURFACES:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    for case in surface_cases(sys.argv[1]):
        print("\t".join(case))
```

Create `forge/test/shell/compare.py`:

```python
#!/usr/bin/python3
"""compare.py <golden-dir> <actual-dir> <tag>...

A case passes when at most TOLERANCE pixels differ from its golden image
(`magick compare -metric AE -fuzz 2%`). Spike P3 measured 0 between runs on one
machine; llvmpipe chooses its code path from the host CPU, so 64 pixels, 0.003 % of a
1920x1080 frame, is allowed between runner generations. The smallest thing that can move
on a surface, a 12 px badge, is 113 pixels.
"""
import re
import subprocess
import sys
from pathlib import Path

TOLERANCE = 64


def parse_ae(text):
    match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?)", text)
    if not match:
        raise ValueError(f"not an absolute-error count: {text!r}")
    return int(float(match.group(1)))


def verdict(differing):
    return differing <= TOLERANCE


def differing_pixels(golden, actual, diff):
    # compare exits 1 when the images differ: that is an answer, not a failure.
    result = subprocess.run(["magick", "compare", "-metric", "AE", "-fuzz", "2%", str(golden), str(actual), str(diff)],
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip())
    return parse_ae(result.stderr)


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    golden_dir, actual_dir, tags = Path(argv[0]), Path(argv[1]), argv[2:]
    failed = 0
    for tag in tags:
        golden, actual = golden_dir / f"{tag}.png", actual_dir / f"{tag}.png"
        if not golden.exists():
            print(f"FAIL {tag}: no golden image; run rig.sh update-goldens and review it")
            failed += 1
            continue
        differing = differing_pixels(golden, actual, actual_dir / f"{tag}-diff.png")
        ok = verdict(differing)
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {tag}: {differing} pixel(s) differ (tolerance {TOLERANCE})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Run: `python3 -B -m unittest discover -s forge/test/shell/tests -v`
Expected: `OK` (10 tests with Task 17's).

- [ ] **Step 3: The test catalogs**

Create `forge/test/shell/locale/de.po`: the header of `it.po` with `"Language: de\n"`, and:

```po
msgid "Not verified"
msgstr "Nicht verifiziert"

msgid "The system image has not been verified yet."
msgstr "Das Systemabbild wurde noch nicht verifiziert."

msgid "Password"
msgstr "Passwort"

msgid "Password for {name}"
msgstr "Passwort für {name}"

msgid "Sign in"
msgstr "Anmelden"

msgid "Signing in…"
msgstr "Anmeldung läuft…"

msgid "Sign-in failed: {reason}"
msgstr "Anmeldung fehlgeschlagen: {reason}"

msgid "The login service cannot be reached."
msgstr "Der Anmeldedienst ist nicht erreichbar."

msgid "Checking your credentials…"
msgstr "Anmeldedaten werden geprüft…"

msgid "The login service gave an unexpected answer."
msgstr "Der Anmeldedienst hat unerwartet geantwortet."

msgid "Too many authentication steps."
msgstr "Zu viele Authentifizierungsschritte."

msgid "High contrast"
msgstr "Hoher Kontrast"

msgid "Keyboard layout: {layout}"
msgstr "Tastaturbelegung: {layout}"

msgid "Suspend"
msgstr "Bereitschaft"

msgid "Restart"
msgstr "Neu starten"

msgid "Shut down"
msgstr "Herunterfahren"

msgid "%A %-d %B"
msgstr "%A, %-d. %B"
```

Create `forge/test/shell/locale/make_pseudo_rtl.py`:

```python
#!/usr/bin/python3
"""make_pseudo_rtl.py <template.pot> <out.po>

A right-to-left pseudo-catalog: every message is its id between RIGHT-TO-LEFT OVERRIDE
and POP DIRECTIONAL FORMATTING, so the copy stays readable to whoever reviews a golden
while the text runs, and the layout mirrors, the way Arabic or Hebrew would.
"""
import re
import sys

RLO, PDF = "‮", "‬"
HEADER = ('msgid ""\nmsgstr ""\n"Language: ar\\n"\n"MIME-Version: 1.0\\n"\n'
          '"Content-Type: text/plain; charset=UTF-8\\n"\n"Content-Transfer-Encoding: 8bit\\n"\n\n')


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    template = open(argv[0], encoding="utf-8").read()
    ids = [m for m in re.findall(r'^msgid "(.+)"$', template, re.M)]
    with open(argv[1], "w", encoding="utf-8") as out:
        out.write(HEADER)
        for msgid in ids:
            out.write(f'msgid "{msgid}"\nmsgstr "{RLO}{msgid}{PDF}"\n\n')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: `surface` and `update-goldens`**

Add to `forge/test/shell/rig.sh`, with the header lines `#   rig.sh surface <name>          capture every case of a surface and compare with the goldens` and `#   rig.sh update-goldens <name>   replace the goldens with a fresh capture, deliberately`:

```bash
surface | update-goldens)
    surface=${2:?usage: rig.sh $1 <surface>}
    golden=$rig/golden/$surface
    if [ "$1" = update-goldens ] && [ -n "$(git -C "$root" status --porcelain -- "$golden")" ]; then
        echo "rig.sh: $golden has uncommitted changes; commit or discard them first" >&2
        exit 1
    fi
    # Test-only catalogs: German for length, the pseudo-language for right-to-left.
    in_rig "$(rig_image)" bash -c '
        set -euo pipefail
        mkdir -p /out/locale
        msgfmt --check -o /out/locale/de.mo /repo/forge/test/shell/locale/de.po
        python3 /repo/forge/test/shell/locale/make_pseudo_rtl.py \
            /repo/forge/specs/athanor-greeter-ui/athanor-greeter-ui-1.0.0/po/athanor-greeter-ui.pot /out/pseudo-rtl.po
        msgfmt -o /out/locale/rtl.mo /out/pseudo-rtl.po'
    tags=()
    while IFS=$'\t' read -r tag variant scale locale catalog; do
        tags+=("$tag")
        override=()
        if [ "$catalog" != - ]; then
            override=(ATHANOR_I18N_CATALOG="/out/locale/$catalog")
        fi
        in_rig "$(rig_image)" env ATHANOR_GREETER_VARIANT="$variant" ATHANOR_LOGIN_USER=ermete RIG_LOCALE="$locale" \
            "${override[@]}" \
            dbus-run-session -- /repo/forge/test/shell/scene.sh 1920 1080 "$scale" "$tag" -- \
            /out/bin/athanor-greeter-ui
    done < <(python3 -B "$rig/cases.py" "$surface")
    if [ "$1" = update-goldens ]; then
        mkdir -p "$golden"
        for tag in "${tags[@]}"; do
            cp "$out/$tag.png" "$golden/$tag.png"
            echo "golden replaced: forge/test/shell/golden/$surface/$tag.png"
        done
        echo "review every image above before committing; say in the commit why they changed"
    else
        in_rig "$(rig_image)" python3 -B /repo/forge/test/shell/compare.py \
            "/repo/forge/test/shell/golden/$surface" /out "${tags[@]}"
    fi
    ;;
```

- [ ] **Step 5: Pin the image, then capture the goldens**

The goldens are only as stable as the image they were captured in, so the image is published and pinned first. This step needs a registry login with push rights (`podman login ghcr.io`), which the maintainer performs.

Run: `bash forge/test/shell/rig.sh publish-image`
Expected: `published ghcr.io/hr-mes/athanor-shell-rig@sha256:…`.

Run: `cp .scratch/shell-rig/rig-image.digest forge/test/shell/rig-image.digest`

From now on `rig_image` resolves to the pinned image, and the workflow's "Rig image" step in the jobs that do not build Rust can be dropped in favour of the pull `podman run` performs. Keep `build-image` in the `greeter` job: it needs the `build` stage.

Run: `bash forge/test/shell/rig.sh build-greeter && bash forge/test/shell/rig.sh update-goldens greeter`
Expected: twelve `golden replaced:` lines, about two minutes. Look at all twelve:

- `-de`: no label is cut and no chip overflows; "Nicht verifiziert" fits the seal chip.
- `-rtl`: the greeter mirrors because its catalog says `Language: ar` (Task 16 sets GTK's default direction from `i18n::is_rtl()`), not because of the process locale. The wordmark is top **right**, the seal top **left**, the chips bottom **left**, the arrow button left of the field; text runs right to left. (The hearth does not mirror: it is a background image, like the wallpaper.) The seal's place under RTL is an open point of SH12 ("decided with our own panel"); the greeter follows GTK's mirroring until then. Tell the maintainer this is what the golden shows.
- `-1.5`: everything is 1.5× and sharp, not a blurred upscale.
- No title bar in any of them.

Run: `bash forge/test/shell/rig.sh surface greeter`
Expected: twelve `ok` lines with `0 pixel(s) differ`, exit 0. Run it a second time: identical.

To see the gate bite: change `card = 18` to `card = 4` in `tokens.toml`, run `generate.py css`, `build-greeter`, `surface greeter`: all twelve cases fail with several thousand differing pixels and a `-diff.png` each. Restore with `git checkout system/athanor-style/calmo` and rebuild.

- [ ] **Step 6: The workflow job**

In `.github/workflows/shell-surfaces.yml`, at the end of the `greeter` job's steps, before the upload:

```yaml
      - name: Greeter surface cases (12) against the goldens
        run: bash forge/test/shell/rig.sh surface greeter
```

and widen the upload so a failing case can be looked at:

```yaml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: shell-rig-greeter
          path: |
            .scratch/shell-rig/*.log
            .scratch/shell-rig/greeter-*.png
```

Run: `actionlint .github/workflows/shell-surfaces.yml && python3 scripts/verify.py workflows && shellcheck forge/test/shell/rig.sh`
Expected: no findings.

The first run on the hosted runner is the measurement spike P3 could not make (llvmpipe on another CPU). **Outcome A:** at most 64 pixels per case: done. **Outcome B:** more, on text edges only: capture the goldens on the hosted runner instead (run the workflow manually with `update-goldens`, download the artifact, review, commit), so that the reference machine is the one that gates; do not raise the tolerance without the maintainer, because 64 is the number this plan states for SH13.

- [ ] **Step 7: Commit (two commits)**

```bash
git add forge/test/shell/cases.py forge/test/shell/compare.py forge/test/shell/tests forge/test/shell/locale forge/test/shell/rig.sh forge/test/shell/rig-image.digest .github/workflows/shell-surfaces.yml
git commit -m "test(greeter): capture the 12 surface cases of SH13 and compare them by pixel count"
git add forge/test/shell/golden/greeter
git commit -m "test(greeter): add the first goldens of the Calmo greeter"
```

---

## Acceptance of package 1a against the spec

| Spec item | Where it is proven |
|---|---|
| Acceptance 1: "generated CSS loads with zero GTK parse warnings, and the contrast gate passes in the four variants" | `rig.sh css-parse` (Task 4), `contrast.py` in lint (Task 2) |
| Acceptance 2, as far as it is 1a's: one identity on a fresh install in light and in dark; on the upgraded desktop the existing theme is untouched | overlay by construction (D2), `verify.py shipped` (Task 8), `rig.sh cosmic-preview` and `cosmic-keys` (Task 7); on the dev VM: install the image, log in as a new user, open Settings → Appearance: indigo accent, light mode; on the upgraded desktop `~/.config/cosmic/com.system76.CosmicTheme.*` is byte-identical before and after |
| Acceptance 3, greeter part: role and name for every control; Italian and English | `rig.sh atspi greeter` (Task 17); `it.po`, `en.po`, `msgfmt --check` in `%build` (Task 15) |
| Acceptance 11, greeter part: 12 surface cases in CI | `rig.sh surface greeter` (Task 18) |
| SH4 one crate per program | Tasks 9 and 11 |
| SH4 shim guards | `%check` and `rig.sh layer-guard` (Task 12) |
| SH4 lint | Tasks 11 and 13 |
| SH5 assets | Inter: `Requires` in `athanor-calmo` and the rig image; wallpaper and icons: Tasks 5, 6, 8 |
| SH12 look of the seal | Task 5 (three shapes, three fixed colours), Task 16 (constant "not verified") |
| SH13 gettext from the first commit | Task 15 (`athanor-i18n`), Task 16 (every string) |
| Section 5, doubt 8 (Inter at fractional scale on real hardware) | not closable in a container: look at the greeter on the dev VM at 150 % after the image carrying `athanor-greeter-ui` 1.0.0-3 is built, and report to the maintainer |

Not covered by 1a, by design: the sentence of acceptance 2 about the accent in COSMIC Settings changing our surfaces. 1a's only surface reads nothing from COSMIC (SH5); that sentence is accepted with 1b-shield and 1c, which re-define `ath_acc` over the sheet this package generates.

## Spec findings

1. **Corrected in the spec on 2026-09-19:** the factory accent is `#2e44c2` on light and `#8898f7` on dark; the earlier `#3f56d8` was the mockup's picker swatch.
2. **Two mockup colours fail AA where the mockup uses them.** `ink2` for the date on the light wallpaper is 4.38:1 where three discs overlap (the plan uses `ink`); `ink3` for placeholder text is 3.06 to 3.32:1 on the light surfaces (the plan restricts `ink3` to icons and uses `ink2` for the placeholder). `warn` (`#a36a00`) on `surf` is 4.48:1: fine for the badge, not for text, which matters to 1b-shield's rows.
3. **High contrast is required by SH5 and absent from the mockup.** The plan derives it by one written rule and gates it (AA, and never below the normal variant's ratio). Task 16, Step 5b, stops until the maintainer has seen it.
4. **cosmic-bg cannot follow the theme mode.** SH5's "two images, light and dark" is shipped, but `filter_by_theme` is an unimplemented TODO upstream and the 1.8.0 binary never reads `CosmicTheme.Mode`. A user who switches to dark keeps the light wallpaper until they pick the dark one in Settings. Closing this needs either an upstream change or a small watcher of our own, which is not in 1a's row.
5. **cosmic-config resolves system defaults per directory, not per key.** SH5's overlay works (proven on the shipped 1.8 binaries), but an overlay must carry the complete key set of every config it shadows, and an empty version directory in it would shadow COSMIC's. The plan enforces both (`cosmic-keys`, the spec's `%check`).
6. **COSMIC 1.8 reads schema `v2` of the theme configs**; `v1` still ships beside it. A COSMIC bump that moves to `v3` is caught by `cosmic-keys`.
7. **The old shell cannot leave the image with the greeter.** SH4 says it "is mined … until it is empty, then deleted"; today the shipped `xdg-desktop-portal-athanor` still runs `athanor-shell-rs --file-chooser` and `--privacy-prompt`, and denies by default without it. Until those two prompts are programs of their own (or the portal hands FileChooser to COSMIC's), a 15,000-line GTK 0.7 binary stays in the image, built from a frozen workspace with a frozen copy of `athanor-style`. SH4's sentence "two ship today, `athanor-shell-rs` and `athanor-recovery`" should say why the first still does.
8. **The rig needs `--security-opt label=disable` on SELinux hosts**, which P3 did not meet because its client drew no icons: GTK 4.20 decodes SVG through glycin in bubblewrap, and when that fails every icon is blank with no error. SH13's list of what makes a golden reproducible should gain "the nested sandbox works".
9. **greetd gives the greeter no locale.** Our own strings no longer depend on it (`athanor-i18n` reads `/etc/locale.conf`), but GTK's strings and the date's weekday and month names do; Task 15 makes `athanor-greeter-session` export it. Nothing in the spec mentions it.
10. **`auth.rs` carried four user-visible Italian literals** (and would have shipped them to every locale); they are translated in Task 16. The UX analysis' "no i18n" finding applied to the one file the spec calls worth keeping as well.

## Self-review

- **Spec coverage.** Row 1a: tokens (Task 1), generator (3), CI parse gate (4) and contrast gate (2), default `CosmicTheme` (7, 8), font (8, rig image in 4), hearth wallpaper (6, 8), seal icons (5, 8), greeter re-skinned on the tokens (14, 16) with roles (16, 17) and gettext (15). SH4: one crate per program (9, 11), the bump that remains (10), `%check` and start-up assertion (12), lint (11, 13); the Cairo renderer applies to panel-resident surfaces, none in 1a. SH13: 12 greeter cases, tolerance stated (64 pixels), reproducibility list implemented in `scene.sh`, AT-SPI check, gettext from the first commit. Gaps, stated rather than hidden: Inter on real hardware (dev VM), two-output cases (layout cases, package 1c), the portal's two prompts still inside the old shell (finding 7).
- **Placeholder scan.** No "TBD", no "similar to Task N" standing in for code. Steps whose content depends on a measurement the plan could not make give the exact command, the outcomes, and what each changes: `probe-sandbox` on the hosted runner (Task 4), the COSMIC mapping by capture (Task 7), clippy on the moved greeter code (Task 11, Step 5; rustc warnings were measured at 0, clippy was not available in the measuring image), the link order at gtk4-layer-shell 0.8.1 (Task 12), the first golden comparison on the hosted runner (Task 18).
- **Name consistency.** Crate, binary, RPM and text domain `athanor-greeter-ui`, short name `greeter-ui`, application id `os.athanor.Greeter` (wrapper filter, `main.rs`); modules `crate::{auth, sandbox, power, ui, layer_guard, i18n}` (Tasks 11, 12, 15, 16 agree); `athanor_i18n::{Catalog, PluralRule, languages, LOCALE_DIR, OVERRIDE_VARIABLE}` and `ATHANOR_I18N_CATALOG` (Task 15, `rig.sh surface` in Task 18); colour tokens `ath_<name>`; `Variant::{Light, Dark, LightHc, DarkHc}` and the names `light`, `dark`, `light-hc`, `dark-hc` (tokens, generator file names, `ATHANOR_GREETER_VARIANT`, `cases.py`); overlay path `/usr/share/athanor/cosmic-defaults`; frozen workspace `forge/specs/athanor-shell-rs/Cargo.toml` with `athanor-style-0.7`; `rig.sh` sub-commands as listed in each task's header comment; icon names `athanor-seal-{verified,attention,blocked}-symbolic`.
- **New crates of this plan:** `athanor-greeter-ui` (binary, workspace member, shipped), `athanor-i18n` (library, workspace member, no dependency), `calmo-cosmic-theme` (standalone developer tool, excluded from the workspace, not shipped), and `athanor-style-0.7` (a frozen copy, member of the frozen workspace only, no new code). No third-party crate is new to the project: `greetd_ipc` and `landlock` move from a crate manifest into `[workspace.dependencies]`; `async-channel` and `gettext-rs`, which the first version of this plan added, are gone.
- **Code that was run while writing or revising the plan:** the Python toolchain and its 37 tests; the generated CSS through GTK 4.20.4's parser (0 reports); the seal icons through `Gtk.Image` with `-gtk-icon-palette` in the headless rig; the 4K wallpaper (2.4 s); `calmo-cosmic-theme` against libcosmic `2a73fbc0`; the `XDG_DATA_DIRS` overlay against the shipped cosmic-panel; Task 9's frozen workspace on a scratch copy (`cargo check -p athanor-shell-rs`: 45 s, gtk4 0.7.3, 274 locked packages); Task 10's bump on the same copy (`athanor-style` 1 error, `athanor-recovery` 0); `athanor-i18n` (10 tests green against real `msgfmt` output). **Not compiled:** the greeter's Rust of Tasks 11, 12, 15 (its `i18n.rs`) and 16, and `calmo.rs` of Task 14; Task 16 names the two places where the compiler may disagree and what to write instead.

# Athanor shell: direction, layout model, stage 1

Status: **draft, awaiting maintainer review.** The decisions below were taken with the maintainer on 2026-09-18, after two critical analyses of the old shell, an adversarial review of the layout model and a check of the toolkit facts against upstream. Section 5 lists what is still unverified. No code is written before this document is approved.

The document replaces `doc_shell_ui.md` and amends `doc_platform_experience.md`, section 3. Section 6 lists the changes those documents take.

## 1. Context

Since 2026-09-11 the desktop is Fedora's COSMIC 1.8 on cosmic-comp: panel, dock, launcher, settings, notifications. `athanor-shell-rs` survives only as the greeter. The maintainer wants a proprietary shell back, evolved rather than restored, because the graphical environment is what an average user judges the system by.

What the analyses found in the old shell:

- It was a niri satellite. Workspaces, dock and overview are dead on cosmic-comp.
- Its visual identity never rendered: 50 GTK4 CSS parse errors, `backdrop-filter` is web-only, 34 of 185 classes defined.
- It had facades: a constant RAM reading, a wallpaper palette computed from compressed bytes.
- It had no accessibility roles, no i18n, no tray, no multi-monitor, `GDK_SCALE=1`, and `#![allow(clippy::all, warnings)]`.
- About 2,000 lines are worth keeping: the greeter with `sys/auth.rs`, the notification server, the D-Bus proxies, the spring integrator.

What the platform gives us today:

- cosmic-comp 1.8 advertises every protocol a shell needs. Privilege depends on which Wayland socket a client holds; the sandbox engine string `com.system76.CosmicPanel` is not authenticated.
- libcosmic is not applicable to our surfaces: not on crates.io, no releases, a hard fork of iced, and its text inputs emit no accessibility nodes (pop-os/libcosmic#1429).
- cosmic-panel is a nested compositor, so an applet is a plain xdg toplevel in any toolkit. It spawns every `X-CosmicApplet=true` desktop file in `XDG_DATA_DIRS`, `~/.local/share` included.
- `org.kde.StatusNotifierWatcher` is owned by `cosmic-applet-status-area`. Removing cosmic-panel removes the tray.
- The client does not verify image signatures: `/etc/containers/policy.json` is `insecureAcceptAnything`.
- Background updates do not run: the preset enables `bootc-fetch-apply.timer`, which does not exist, and the override of `bootc-fetch-apply-updates.service` calls `bootc upgrade --stage`, a flag bootc 1.16 does not have.

## 2. Decisions

**SH1. Staged path.** COSMIC stays underneath and its surfaces are replaced one at a time.

- **Stage 1:** a real design system, the update experience and the trust shield, on top of COSMIC. Section 3 scopes it.
- **Later stages:** one surface per stage, in this order unless a stage's own spec argues otherwise: session lock, notifications, panel with tray, launcher, overview.
- **The rule for replacing a surface:** ours is usable by an average user and better than COSMIC's at the moment of the switch. Tray, fractional scaling, screen-reader roles and i18n are requirements of every surface, not extras.
- **No facades.** A control that does nothing, or a reading with no source, is a defect.

**SH2. cosmic-comp stays; the dependency has an exit.** We do not write a compositor.

- A Rust compositor is 2.6–3.3 MB of Rust on top of Smithay's 4.4 MB, and its cost is the hardware matrix, not the first version. A compositor of our own on Smithay would still depend on the maintainer of cosmic-comp, through the library.
- cosmic-comp is GPL-3 and Smithay is MIT. A fork is always possible, and we only run cosmic-comp as a separate process.
- **Containment:** the `cosmic-*` protocols are used from one module of the shell and nowhere else. Where a standard protocol exists (`ext-workspace-v1`, `ext-foreign-toplevel-list-v1`, `ext-image-copy-capture-v1`, `ext-session-lock-v1`), the shell uses the standard one.
- **Security features only a compositor can give** (authenticated privileged clients, a trusted path for credential prompts, compositor-drawn trust decorations) are proposed upstream first. If upstream declines, they become a small isolated patch set built in the forge and rebased per release.
- **A fork is reconsidered only when** System76 abandons or relicenses cosmic-comp, or a security requirement we cannot drop is declined and the patch set stops being maintainable, or the project has more maintainers. A fork starts from cosmic-comp, never from zero.

**SH3. COSMIC's headless daemons stay by choice.** The shell owns pixels, not plumbing.

| Component | Role | Fate |
|---|---|---|
| cosmic-settings-daemon | configuration bus, media keys | stays |
| cosmic-settings, cosmic-randr | Settings application | stays; `athanor-settings-rs` is not revived |
| cosmic-osd | OSD and the session's only polkit agent | stays; replacing it means writing a polkit agent |
| cosmic-idle | `org.freedesktop.ScreenSaver`, idle policy | stays |
| cosmic-greeter as locker | session lock | first surface to be replaced |
| cosmic-notifications | notification daemon, coupled to the panel by an inherited socket pair | leaves with the panel; our notification server returns |
| cosmic-panel, cosmic-applets, cosmic-launcher, cosmic-app-library | panel, dock, launcher | leave when our panel provides the StatusNotifier watcher and host, and the network, Bluetooth, audio, battery, power and input-source modules |
| cosmic-workspaces, cosmic-bg | overview, wallpaper | stay until replaced |

COSMIC applications (`cosmic-files`, `cosmic-term`, `cosmic-edit`, `cosmic-store`) are content, not dependencies. They read `CosmicTheme`, so the design system writes it (SH5).

**SH4. GTK4, with the shim kept replaceable.**

- Our surfaces use GTK4 through plain `gtk4-rs`. AT-SPI, IME and RTL work today.
- `relm4` 0.7 is four majors behind. Spike P2 decides between upgrading it and dropping it; it is not kept at 0.7.
- `gtk4-layer-shell` is a one-maintainer symbol-interposition shim that GTK does not support. Therefore: one process per surface, all logic in toolkit-agnostic crates, and the shim called from one place per surface. If the shim fails, only the panel moves to a direct `wayland-rs` client. Qt is not a fallback.
- `#![allow(clippy::all, warnings)]` is removed from any crate a stage touches.

**SH5. Identity: "Calmo".** Light and neutral by default, with a dark variant of equal standing.

- **Tokens are the single source.** One tokens file generates the GTK4 CSS of our surfaces and the vendor `CosmicTheme` (light and dark). CI parses the generated CSS with GTK's own parser; a parse warning fails the build.
- **Factory accent:** indigo, hue 231 and saturation 62 % in the HSL tokens (`#3f56d8` on light). The user changes the accent; trust colours (verified, not verified, blocked) are fixed and never derived from the accent.
- **Stage 1 has one accent control, COSMIC's.** Our surfaces follow the `CosmicTheme` accent and compute the on-accent text colour against WCAG AA at run time. The greeter uses the factory accent. A curated palette arrives with a Settings surface of our own, not before.
- **Contrast is validated:** every text/background pair of the tokens meets WCAG AA, checked in CI.
- **The identity lives in form, not in colour,** because the colour is the user's. Two signatures carry it:
  - **The mark is the seal.** The Athanor mark is reserved for the trust shield (SH12) and appears nowhere else in the shell; the launcher uses a neutral glyph.
  - **The hearth wallpaper.** The default wallpaper is a set of concentric discs rising from a corner. Stage 1 ships it as two images, light and dark, in the factory accent. It follows the user's accent only when the accent comes from a curated palette, because each hue is then an image built ahead of time; a free colour picker cannot be followed without a run-time generator, which stage 1 does not have.
- **Shipped assets:** Inter (`rsms-inter-fonts`) as the only interface family, with tabular figures for clocks, to be confirmed on the dev VM; `cosmic-icon-theme` stays in stage 1; our own symbolic icons only for the seal and its states.
- **Depth is reserved for what floats:** windows, popovers and notifications carry a marked shadow; panels and docks carry a hairline and a faint one.
- Nothing in the identity relies on an effect GTK4 cannot draw.

**SH6. The layout is a document with our own schema.**

- Per output from the first version, even while one layout applies to all outputs.
- Versioned: `schema = <integer>`.
- Layered, lowest to highest: vendor (`/usr/share/athanor/layout/`, replaced on update) < policy (`/etc/athanor/layout/`, an administrator may mark a key mandatory) < user (`~/.config/athanor/layout.toml`).
- The document names a preset and the knobs of SH7, nothing else. It is the serialisation of what the interface offers, never a superset.

**SH7. Presets are data.** Version 1 ships three presets and three knobs.

- **Isola:** floating top panel, floating centred dock. COSMIC's shipped defaults; zero code.
- **Barra:** one bottom bar with launcher, running applications, tray and clock. In stage 1 it is an icon taskbar: no COSMIC applet renders window titles. Titles wait for our panel and for a decision on who may read them.
- **Essenziale:** thin top bar, no dock. Subject to cosmic-panel#560 being absent on 1.8.
- **Isole** (three top islands, vertical dock) needs our own panel and is not in version 1.
- **Knobs:** panel position (top, bottom); dock (visible, auto-hide, none); accent (SH5).
- **A knob exists only where it means something.** Barra holds the applications in the bar, so it has no dock knob and the schema rejects one. That leaves 2 × 3 layouts for Isola, 2 for Barra and 2 × 3 for Essenziale: 14 in version 1.
- **Dock placement is derived, not chosen:** the dock sits on the bottom edge, and on the left edge when the panel is at the bottom. A vertical dock carries icons only (SH9.3).
- In stage 1 a translator turns the document into cosmic-panel configuration. It writes `entries` last, because that configuration is live and not atomic. It runs when the effective document changes, not at every login.

**SH8. The schema is the ratchet.** Everything the schema can express is supported and tested; nothing else is expressible.

- An unknown key, a newer `schema`, or a malformed file rejects the whole user document. The shell then applies the nearest preset it knows, logs at error priority, and **never rewrites the user's file**. A rollback to an older `/usr` therefore degrades and a later upgrade restores.
- Crash-loop protection reuses the policy of `athanor-cosmic-panel`: bounded failures in a `CLOCK_BOOTTIME` window, then the vendor layout. The shell is never lost.

**SH9. Invariants, never configurable.**

1. The trust shield is always present, in the same place within a preset.
2. No third-party code runs in the shell: modules are a closed, in-image set. A third-party module mechanism may exist only inside a compartment with a declared capability manifest.
3. Elements that carry text are horizontal.

**SH10. The default preset is chosen once,** at first boot, from the logical resolution and the chassis type (`hostnamectl chassis`), and written as the user document. It is never re-evaluated.

**SH11. Updates are never forced.**

- A system timer stages updates in the background with `bootc upgrade` (no `--apply`), and not on a metered connection. Staging never reboots.
- `bootc status` needs root, so the system side publishes the state as a world-readable file, `/run/athanor/update/state.json`: booted, staged and rollback deployments (image, digest, version, timestamp), verification result, last check, last error.
- A user service watches that file and sends **one** notification per staged digest: the update applies at the next restart; actions "Restart now" and "Later". No countdown, no repeat.
- After the first boot into a new deployment, one notification says what changed and offers the way back.
- **Rollback** is `bootc rollback` behind a polkit action (`auth_admin`) in a small helper that checks the caller as the subject through `athanor_bus_api::polkit`. The helper is new code in a security path: the `auditor` agent reviews it and the maintainer consents before it is written.
- The backend sits behind one interface, so `systemd-sysupdate` with A/B `/usr` (`doc_kernel_profile.md`) later replaces bootc without changing the experience.

**SH12. The shield reports only what a verifier backs.**

- A state is shown as verified only when the system performed the verification. Everything else is "not verified", never green.
- Stage 1 sources: the booted image and digest (`bootc status`); whether that image passed signature verification at pull time; Secure Boot state; staged update and available rollback.
- Image verification has no verifier today (section 1). Stage 1 ships a sigstore policy for the project's registry and public key in `/etc/containers/policy.json`. Until it is shipped and proven on the dev VM, the shield shows the image as "not verified".
- **The shield is the Athanor mark with a state badge.** Verified is a check, not verified an exclamation mark, blocked a cross; each state differs in shape and in colour, so it reads without colour vision. There is no permanent text in the panel: the words are in the popover and in the accessible name.
- **Its place is fixed:** the trailing end of the panel in every layout, and the same corner of the greeter.
- In stage 1 the shield is a GTK4 applet inside cosmic-panel (spike P1). Its popover carries one row per source above, "Restart to update" and "Go back to the previous version".

**SH13. Tests.**

- Screenshot cases are generated from the schema. The three presets at their factory knobs run the full matrix: outputs {1, 2} × scale {1.0, 2.0} × direction {LTR, RTL} × locale {en, de} = 48 cases. The other 11 layouts of SH7 run once each at the baseline (one output, scale 1.0, LTR, en): 59 cases in all. German is in the matrix for string length; Italian and English are the shipped locales.
- Each surface has an accessibility check: every interactive widget exposes a role and a name.
- All strings go through gettext from the first commit.

## 3. Stage 1

Three work packages, each with its own implementation plan, in this order.

| Package | Delivers | Gated by |
|---|---|---|
| **1a. Design system** | tokens, generator, CI parse and contrast gates, vendor `CosmicTheme` light and dark, font, the greeter re-skinned on the tokens with roles and gettext | P2, P3 |
| **1b. Updates and shield** | staging timer (replaces the broken preset line and override), state file, notifier, rollback helper, sigstore policy, shield applet | P1; maintainer consent for the helper and the policy |
| **1c. Layout** | schema, layered loader with degradation, translator to cosmic-panel, first-boot default, three presets, a small chooser window, the 59 cases | P3 |

Spikes, run before the plan they gate; each produces an answer, not code we keep:

| # | Spike | Settles |
|---|---|---|
| P1 | A GTK4 applet inside cosmic-panel: sizing, popover, scale, theme, memory | whether the shield can ship in stage 1 |
| P2 | Bump gtk4 0.7→0.11 and gtk4-layer-shell on the greeter path only, with and without relm4; count errors | upgrade relm4 or drop it |
| P3 | cosmic-comp under llvmpipe in a container, one layer-shell client, one captured frame | whether screenshot tests run on a hosted runner or on the KVM runner |

Two more spikes gate stage 2, not stage 1: the security-context privilege model on 1.8, and a side-connection client for toplevels, workspaces and capture.

Out of stage 1: our own panel, dock, launcher, notifications, lock and Settings; the Isole preset; window titles in Barra; a curated accent palette; any compositor patch.

## 4. Risks

- **The shim.** GTK 4.16 broke `gtk4-layer-shell` once. SH4 bounds the damage to one call site per surface; the greeter is the exposed surface in stage 1.
- **A wrong signature policy blocks updates,** not boot. It is proven on the dev VM against a signed and an unsigned image before it reaches the image, and rollback stays available.
- **Two editors of the panel configuration.** COSMIC Settings keeps its Panel and Dock pages. A user's edit there lasts until the next layout change, when the translator rewrites the configuration. Accepted for stage 1; it ends with our own panel.
- **cosmic-panel moves fast.** The translator targets a configuration format we do not own. The 59 cases run against every COSMIC bump.
- **Scope.** Each later stage re-solves something COSMIC already solved. SH1's replacement rule is the brake.

## 5. Open doubts

1. **Applet injection against SH9.2.** cosmic-panel starts applets found under `~/.local/share`, inside a security context. In stage 1 the invariant holds for our surfaces only. Whether the panel unit can run with a restricted `XDG_DATA_DIRS` without breaking the application list is not verified.
2. **How the project's images are signed** (key or keyless) decides the form of the sigstore policy. To be read from `sign_attest.sh` when 1b is planned.
3. **The metered-connection check** relies on NetworkManager's metered state, which many networks leave as "unknown".
4. **P1 may fail.** Then the shield waits for our panel, and stage 1 carries the trust states in the update notifications only.
5. **Hiding COSMIC Settings pages** that configure a panel we later remove may need a patch. Not a stage 1 problem.
6. **The greeter holds the real Wayland socket,** with capture and clipboard privilege. Per-surface confinement needs the compositor work of SH2.
7. **Inter** is a proposal from the mockups, not yet seen on real hardware at fractional scale.
8. **The seal at panel size** is an 18-pixel mark with a 12-pixel badge. Whether the three badges stay distinguishable at scale 1.0 on a low-density screen is checked in P1.

## 6. Changes to other documents

- `doc_shell_ui.md` describes niri, relm4 and `athanor-settings-rs`. It is replaced by this document and deleted when this one is approved.
- `doc_platform_experience.md`, section 3, names "the native GTK4/Relm4 panel and the horizontal strip of `Niri`". It takes a pointer to this document.
- `NEXT.md` takes stage 1 as a block with the gate of section 7.
- `CLAUDE.md`, "Desktop GTK4/Wayland": unchanged.

## 7. Acceptance of stage 1

On a fresh install in the dev VM and on the maintainer's desktop:

1. The generated CSS loads with zero GTK parse warnings, and the contrast gate passes for light and dark.
2. The greeter, COSMIC's surfaces and COSMIC applications show one identity in light and in dark; changing the accent in COSMIC Settings changes our surfaces, and the trust colours do not move.
3. Orca reads every control of the greeter and of the shield; both run in Italian and in English.
4. With a newer image published, the update is staged with no user action, one notification appears, nothing reboots, and "Later" is never asked again for that digest.
5. After the restart the new deployment is booted; "Go back to the previous version" asks for administrator authentication and returns to the old digest.
6. An unsigned image is refused at pull time, and the shield never showed it as verified.
7. The three presets apply from the chooser without a restart of the session; a user document with an unknown key degrades to a preset and the file is byte-identical afterwards.
8. The 59 screenshot cases pass in CI.

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

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
    gtk4::style_context_add_provider_for_display(
        display,
        &provider,
        gtk4::STYLE_PROVIDER_PRIORITY_APPLICATION,
    );
    if let Some(settings) = gtk4::Settings::default() {
        settings.set_gtk_application_prefer_dark_theme(variant.is_dark());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const ALL: [Variant; 4] = [
        Variant::Light,
        Variant::Dark,
        Variant::LightHc,
        Variant::DarkHc,
    ];

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
            assert!(
                css.contains(&format!("/* Variant: {} */", variant.name())),
                "{variant:?}"
            );
            assert!(css.contains("window.athanor-greeter"));
        }
        assert!(Variant::Light
            .css()
            .contains("@define-color ath_acc #2e44c2;"));
        assert!(Variant::Dark
            .css()
            .contains("@define-color ath_acc #8898f7;"));
    }
}

use gtk4::gdk;
use gtk4::gio;
use gtk4::prelude::*;
use std::path::PathBuf;

pub fn get_config_dir() -> PathBuf {
    if let Ok(xdg) = std::env::var("XDG_CONFIG_HOME") {
        PathBuf::from(xdg).join("athanor")
    } else if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home).join(".config").join("athanor")
    } else {
        PathBuf::from("/var/lib/athanor")
    }
}

pub fn load_glass_theme() {
    let css_provider = gtk4::CssProvider::new();
    let css = include_str!("style.css");
    css_provider.load_from_data(css);

    if let Some(display) = gdk::Display::default() {
        gtk4::style_context_add_provider_for_display(
            &display,
            &css_provider,
            gtk4::STYLE_PROVIDER_PRIORITY_APPLICATION,
        );

        // Load dynamic accent.css if present
        let accent_path = get_config_dir().join("accent.css");
        if accent_path.exists() {
            let accent_provider = gtk4::CssProvider::new();
            accent_provider.load_from_path(&accent_path);
            gtk4::style_context_add_provider_for_display(
                &display,
                &accent_provider,
                gtk4::STYLE_PROVIDER_PRIORITY_USER + 100,
            );
            setup_css_monitor(accent_provider, accent_path, display.clone());
        }

        // Load dynamic theme.css if present
        let theme_path = get_config_dir().join("theme.css");
        if theme_path.exists() {
            let theme_provider = gtk4::CssProvider::new();
            theme_provider.load_from_path(&theme_path);
            gtk4::style_context_add_provider_for_display(
                &display,
                &theme_provider,
                gtk4::STYLE_PROVIDER_PRIORITY_USER,
            );
            setup_css_monitor(theme_provider, theme_path, display);
        }
    }
}

fn setup_css_monitor(provider: gtk4::CssProvider, path: PathBuf, display: gdk::Display) {
    let file = gio::File::for_path(&path);
    if let Ok(monitor) = file.monitor_file(gio::FileMonitorFlags::NONE, gio::Cancellable::NONE) {
        let path_clone = path.clone();
        monitor.connect_changed(move |_, _, _, event_type| {
            if (event_type == gio::FileMonitorEvent::ChangesDoneHint || event_type == gio::FileMonitorEvent::Changed)
                && path_clone.exists() {
                    provider.load_from_path(&path_clone);
                    gtk4::style_context_add_provider_for_display(
                        &display,
                        &provider,
                        gtk4::STYLE_PROVIDER_PRIORITY_USER + 100,
                    );
                }
        });
        std::mem::forget(monitor);
    }
}

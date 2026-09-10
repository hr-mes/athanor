use gtk4::prelude::*;
use gtk4::{Application, ApplicationWindow, Box, Button, Entry, Label, Orientation, Align};
use gtk4_layer_shell::{Edge, Layer, LayerShell};
use crate::sys::auth::*;

const GREETER_CSS: &str = r#"
window.background {
    background-color: transparent;
}

.greeter-backdrop {
    background-color: rgba(10, 12, 18, 0.45);
}

.greeter-topbar-title {
    font-family: 'Inter', 'SF Pro Display', sans-serif;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 4px;
    color: rgba(255, 255, 255, 0.90);
    text-shadow: 0 2px 8px rgba(0,0,0,0.5);
}

.greeter-status-pill {
    font-family: 'Inter', 'SF Pro Text', sans-serif;
    font-size: 13px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.95);
    background-color: rgba(255, 255, 255, 0.15);
    padding: 8px 16px;
    border-radius: 999px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    transition: background-color 0.3s ease;
}

.greeter-status-pill:hover {
    background-color: rgba(255, 255, 255, 0.25);
}

.greeter-clock-time {
    font-family: 'Inter', 'SF Pro Display', sans-serif;
    font-size: 84px;
    font-weight: 300;
    color: #ffffff;
    letter-spacing: -3px;
    text-shadow: 0 8px 24px rgba(0,0,0,0.4);
    margin-bottom: -10px;
}

.greeter-clock-date {
    font-family: 'Inter', 'SF Pro Text', sans-serif;
    font-size: 20px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.90);
    margin-bottom: 24px;
    text-shadow: 0 4px 12px rgba(0,0,0,0.4);
}

.greeter-card {
    background-color: rgba(24, 27, 36, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.25);
    border-radius: 36px;
    padding: 42px 52px;
    min-width: 400px;
    box-shadow: 0 32px 84px rgba(0, 0, 0, 0.8), inset 0 1px 1px rgba(255, 255, 255, 0.15);
    transition: all 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

.greeter-avatar-frame {
    border: 2px solid rgba(255, 255, 255, 0.4);
    border-radius: 999px;
    min-width: 96px;
    min-height: 96px;
    background-color: rgba(255, 255, 255, 0.15);
    font-size: 40px;
    color: #ffffff;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.6);
    transition: all 0.3s ease;
}

.greeter-user-name {
    font-family: 'Inter', 'SF Pro Display', sans-serif;
    font-size: 26px;
    font-weight: 700;
    color: #ffffff;
    margin-top: 18px;
    text-shadow: 0 4px 16px rgba(0,0,0,0.5);
}

.greeter-badge {
    font-family: 'Inter', 'SF Pro Text', sans-serif;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 2px;
    color: rgba(255, 255, 255, 0.70);
    margin-top: 6px;
    margin-bottom: 22px;
}

.greeter-caps-pill, .greeter-biometric-pill {
    font-family: 'Inter', 'SF Pro Text', sans-serif;
    font-size: 12px;
    font-weight: 700;
    border-radius: 999px;
    padding: 6px 14px;
    margin-bottom: 12px;
    letter-spacing: 1px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    transition: all 0.3s ease;
}

.greeter-caps-pill {
    color: #ffd166;
    background-color: rgba(255, 209, 102, 0.20);
    border: 1px solid rgba(255, 209, 102, 0.40);
}

.greeter-biometric-pill {
    color: #38bdf8;
    background-color: rgba(56, 189, 248, 0.20);
    border: 1px solid rgba(56, 189, 248, 0.40);
}

.greeter-entry-box {
    background-color: rgba(0, 0, 0, 0.25);
    border: 1px solid rgba(255, 255, 255, 0.25);
    border-radius: 20px;
    padding: 6px 10px;
    box-shadow: inset 0 2px 8px rgba(0,0,0,0.3);
    transition: all 0.3s ease;
}

.greeter-entry-box:focus-within {
    border-color: rgba(255, 255, 255, 0.6);
    background-color: rgba(0, 0, 0, 0.35);
    box-shadow: inset 0 2px 8px rgba(0,0,0,0.4), 0 0 12px rgba(255,255,255,0.2);
}

.greeter-entry {
    background: transparent;
    border: none;
    color: #ffffff;
    caret-color: #6ea8fe;
    font-family: 'Inter', 'SF Pro Text', sans-serif;
    font-size: 16px;
    min-height: 44px;
    box-shadow: none;
}

.greeter-icon-btn {
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.75);
    font-size: 18px;
    padding: 8px 12px;
    border-radius: 12px;
    transition: all 0.2s ease;
    box-shadow: none;
}

.greeter-icon-btn:hover {
    background-color: rgba(255, 255, 255, 0.15);
    color: #ffffff;
}

.greeter-error {
    color: #ff6b6b;
    font-family: 'Inter', 'SF Pro Text', sans-serif;
    font-size: 14px;
    font-weight: 600;
    margin-top: 12px;
    transition: opacity 0.3s ease;
}

.greeter-status-msg {
    color: #6ea8fe;
    font-family: 'Inter', 'SF Pro Text', sans-serif;
    font-size: 14px;
    font-weight: 600;
    margin-top: 12px;
    transition: opacity 0.3s ease;
}

.greeter-power-btn {
    background-color: rgba(255, 255, 255, 0.15);
    border: 1px solid rgba(255, 255, 255, 0.25);
    border-radius: 999px;
    color: #ffffff;
    font-family: 'Inter', 'SF Pro Text', sans-serif;
    font-size: 14px;
    font-weight: 600;
    padding: 12px 24px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    transition: all 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

.greeter-power-btn:hover {
    background-color: rgba(255, 255, 255, 0.25);
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(0,0,0,0.4);
}
"#;

fn format_italian_date(now: &chrono::DateTime<chrono::Local>) -> String {
    use chrono::Datelike;
    let weekday = match now.weekday() {
        chrono::Weekday::Mon => "Lunedì",
        chrono::Weekday::Tue => "Martedì",
        chrono::Weekday::Wed => "Mercoledì",
        chrono::Weekday::Thu => "Giovedì",
        chrono::Weekday::Fri => "Venerdì",
        chrono::Weekday::Sat => "Sabato",
        chrono::Weekday::Sun => "Domenica",
    };
    let month = match now.month() {
        1 => "gennaio",
        2 => "febbraio",
        3 => "marzo",
        4 => "aprile",
        5 => "maggio",
        6 => "giugno",
        7 => "luglio",
        8 => "agosto",
        9 => "settembre",
        10 => "ottobre",
        11 => "novembre",
        12 => "dicembre",
        _ => "",
    };
    format!("{}, {} {}", weekday, now.day(), month)
}

pub fn build_ui(app: &Application, is_lockscreen: bool) {
    let title = if is_lockscreen { "Athanor Lockscreen" } else { "Athanor Greeter" };
    let window = ApplicationWindow::builder()
        .application(app)
        .title(title)
        .build();

    window.init_layer_shell();
    window.set_layer(Layer::Overlay);
    window.set_keyboard_mode(gtk4_layer_shell::KeyboardMode::Exclusive);
    window.set_namespace(if is_lockscreen { "lockscreen" } else { "greeter" });

    window.set_anchor(Edge::Top, true);
    window.set_anchor(Edge::Bottom, true);
    window.set_anchor(Edge::Left, true);
    window.set_anchor(Edge::Right, true);

    if let Some(display) = gtk4::gdk::Display::default() {
        let provider = gtk4::CssProvider::new();
        provider.load_from_data(GREETER_CSS);
        gtk4::style_context_add_provider_for_display(&display, &provider, gtk4::STYLE_PROVIDER_PRIORITY_APPLICATION);
    }
    let root_vbox = Box::builder()
        .orientation(Orientation::Vertical)
        .css_classes(["greeter-backdrop"])
        .hexpand(true)
        .vexpand(true)
        .build();

    // Zone 1: Top Bar
    let topbar = Box::builder()
        .orientation(Orientation::Horizontal)
        .margin_top(20)
        .margin_start(28)
        .margin_end(28)
        .build();

    let os_title = Label::builder()
        .label("ATHANOR OS")
        .css_classes(["greeter-topbar-title"])
        .build();

    let spacer = Box::builder()
        .orientation(Orientation::Horizontal)
        .hexpand(true)
        .build();

    let theme_toggle = Button::builder()
        .label("🎨 Theme")
        .css_classes(["greeter-status-pill"])
        .build();

    let status_pill = Label::builder()
        .label("󰤨   󰁹   IT")
        .css_classes(["greeter-status-pill"])
        .build();

    let right_box = Box::builder()
        .orientation(Orientation::Horizontal)
        .spacing(8)
        .build();
    right_box.append(&theme_toggle);
    right_box.append(&status_pill);

    topbar.append(&os_title);
    topbar.append(&spacer);
    topbar.append(&right_box);

    // Zone 2: Center Clock + Card
    let center_box = Box::builder()
        .orientation(Orientation::Vertical)
        .valign(Align::Center)
        .halign(Align::Center)
        .hexpand(true)
        .vexpand(true)
        .spacing(24)
        .build();

    let clock_box = Box::builder()
        .orientation(Orientation::Vertical)
        .halign(Align::Center)
        .spacing(4)
        .build();

    let time_label = Label::builder()
        .css_classes(["greeter-clock-time"])
        .build();

    let date_label = Label::builder()
        .css_classes(["greeter-clock-date"])
        .build();

    let now = chrono::Local::now();
    time_label.set_text(&now.format("%H:%M").to_string());
    date_label.set_text(&format_italian_date(&now));

    let time_label_clone = time_label.clone();
    let date_label_clone = date_label.clone();
    glib::timeout_add_seconds_local(1, move || {
        let now = chrono::Local::now();
        time_label_clone.set_text(&now.format("%H:%M").to_string());
        date_label_clone.set_text(&format_italian_date(&now));
        glib::ControlFlow::Continue
    });

    clock_box.append(&time_label);
    clock_box.append(&date_label);

    let card_box = Box::builder()
        .orientation(Orientation::Vertical)
        .halign(Align::Center)
        .css_classes(["greeter-card"])
        .build();

    let user_info = discover_target_user();

    // Avatar rendering
    let avatar_widget: gtk4::Widget = if let Some(path) = &user_info.avatar_path {
        let picture = gtk4::Picture::for_filename(path);
        picture.set_can_shrink(true);
        picture.set_size_request(88, 88);
        picture.add_css_class("greeter-avatar-frame");
        picture.upcast()
    } else {
        let lbl = Label::builder()
            .label("")
            .css_classes(["greeter-avatar-frame"])
            .halign(Align::Center)
            .build();
        lbl.upcast()
    };
    avatar_widget.set_halign(Align::Center);

    let user_label = Label::builder()
        .label(&user_info.real_name)
        .halign(Align::Center)
        .css_classes(["greeter-user-name"])
        .build();

    let badge_text = if is_lockscreen { "BLOCCO SCHERMO • WAYLAND" } else { "WAYLAND • NIRI" };
    let badge_label = Label::builder()
        .label(badge_text)
        .halign(Align::Center)
        .css_classes(["greeter-badge"])
        .build();

    let biometric_pill = Label::builder()
        .label("󰈆 BIOMETRIA (TPM 2.0 / FPRINTD) & KEYRING UNLOCK ATTIVI")
        .halign(Align::Center)
        .css_classes(["greeter-biometric-pill"])
        .visible(std::path::Path::new("/var/run/dbus/system_bus_socket").exists())
        .build();

    let caps_label = Label::builder()
        .label("󰪛 MAIUSC ATTIVO")
        .halign(Align::Center)
        .css_classes(["greeter-caps-pill"])
        .visible(false)
        .build();

    // Password Entry Row
    let entry_row = Box::builder()
        .orientation(Orientation::Horizontal)
        .css_classes(["greeter-entry-box"])
        .hexpand(true)
        .build();

    let password_entry = Entry::builder()
        .placeholder_text("Password di accesso...")
        .visibility(false)
        .hexpand(true)
        .css_classes(["greeter-entry"])
        .build();

    let reveal_btn = Button::builder()
        .label("󰈈")
        .css_classes(["greeter-icon-btn"])
        .build();

    let entry_reveal_clone = password_entry.clone();
    let reveal_btn_clone = reveal_btn.clone();
    reveal_btn.connect_clicked(move |_| {
        let vis = gtk4::prelude::EntryExt::is_visible(&entry_reveal_clone);
        entry_reveal_clone.set_visibility(!vis);
        reveal_btn_clone.set_label(if !vis { "󰈉" } else { "󰈈" });
    });

    let submit_btn = Button::builder()
        .label("➔")
        .css_classes(["greeter-icon-btn"])
        .build();

    entry_row.append(&password_entry);
    entry_row.append(&reveal_btn);
    entry_row.append(&submit_btn);

    // Caps Lock detection on key presses
    let key_ctrl = gtk4::EventControllerKey::new();
    let caps_clone = caps_label.clone();
    key_ctrl.connect_key_pressed(move |_, _keyval, _keycode, state| {
        let is_caps = state.contains(gtk4::gdk::ModifierType::LOCK_MASK);
        caps_clone.set_visible(is_caps);
        glib::Propagation::Proceed
    });
    password_entry.add_controller(key_ctrl);

    let error_label = Label::builder()
        .label("")
        .css_classes(["greeter-error"])
        .visible(false)
        .wrap(true)
        .build();

    let status_label = Label::builder()
        .label("")
        .css_classes(["greeter-status-msg"])
        .visible(false)
        .wrap(true)
        .build();

    let err_clear = error_label.clone();
    let status_clear = status_label.clone();
    password_entry.connect_changed(move |_| {
        err_clear.set_visible(false);
        status_clear.set_visible(false);
    });

    let app_ref = app.clone();
    let submit_login = std::rc::Rc::new({
        let entry = password_entry.clone();
        let err_label = error_label.clone();
        let status_label = status_label.clone();
        let submit_btn = submit_btn.clone();
        move || {
            let password = entry.text().to_string();
            entry.set_sensitive(false);
            submit_btn.set_sensitive(false);
            err_label.set_visible(false);
            status_label.set_text("Accesso in corso...");
            status_label.set_visible(true);

            let entry_clone = entry.clone();
            let err_clone = err_label.clone();
            let status_clone = status_label.clone();
            let submit_clone = submit_btn.clone();
            let app_quit = app_ref.clone();

            glib::MainContext::default().spawn_local(async move {
                let res = authenticate(&password, is_lockscreen).await;
                match res {
                    Ok(_) => {
                        app_quit.quit();
                    }
                    Err(e) => {
                        status_clone.set_visible(false);
                        err_clone.set_text(&format!("Accesso non riuscito: {}", e));
                        err_clone.set_visible(true);
                        entry_clone.set_text("");
                        entry_clone.set_sensitive(true);
                        submit_clone.set_sensitive(true);
                        entry_clone.grab_focus();
                    }
                }
            });
        }
    });

    let sl_clone = submit_login.clone();
    password_entry.connect_activate(move |_| sl_clone());
    submit_btn.connect_clicked(move |_| submit_login());

    card_box.append(&avatar_widget);
    card_box.append(&user_label);
    card_box.append(&badge_label);
    card_box.append(&biometric_pill);
    card_box.append(&caps_label);
    card_box.append(&entry_row);
    card_box.append(&error_label);
    card_box.append(&status_label);

    center_box.append(&clock_box);
    center_box.append(&card_box);

    // Zone 3: Bottom Power Buttons
    let bottom_bar = Box::builder()
        .orientation(Orientation::Horizontal)
        .halign(Align::Center)
        .margin_bottom(32)
        .spacing(16)
        .build();

    let suspend_btn = Button::builder()
        .label("Sospendi")
        .css_classes(["greeter-power-btn"])
        .build();
    suspend_btn.connect_clicked(|_| {
        glib::MainContext::default().spawn_local(async move {
            if let Ok(conn) = zbus::Connection::system().await {
                if let Ok(proxy) = crate::ipc::power::LogindProxy::new(&conn).await {
                    if let Err(e) = proxy.suspend(true).await {
                        tracing::error!("Failed login1 suspend: {}", e);
                    }
                }
            }
        });
    });

    let reboot_btn = Button::builder()
        .label("Riavvia")
        .css_classes(["greeter-power-btn"])
        .build();
    reboot_btn.connect_clicked(|_| {
        glib::MainContext::default().spawn_local(async move {
            if let Ok(conn) = zbus::Connection::system().await {
                if let Ok(proxy) = crate::ipc::power::LogindProxy::new(&conn).await {
                    if let Err(e) = proxy.reboot(true).await {
                        tracing::error!("Failed login1 reboot: {}", e);
                    }
                }
            }
        });
    });

    let poweroff_btn = Button::builder()
        .label("Spegni")
        .css_classes(["greeter-power-btn"])
        .build();
    poweroff_btn.connect_clicked(|_| {
        glib::MainContext::default().spawn_local(async move {
            if let Ok(conn) = zbus::Connection::system().await {
                if let Ok(proxy) = crate::ipc::power::LogindProxy::new(&conn).await {
                    if let Err(e) = proxy.power_off(true).await {
                        tracing::error!("Failed login1 poweroff: {}", e);
                    }
                }
            }
        });
    });

    bottom_bar.append(&suspend_btn);
    bottom_bar.append(&reboot_btn);
    bottom_bar.append(&poweroff_btn);

    root_vbox.append(&topbar);
    root_vbox.append(&center_box);
    root_vbox.append(&bottom_bar);

    window.set_child(Some(&root_vbox));
    // Keyboard focus starts on the password entry: the first key pressed is the first
    // character of the password, nothing has to be clicked first. GTK moves focus to
    // the first focusable widget otherwise, which is whatever the layout puts first.
    password_entry.grab_focus();
    window.present();
}

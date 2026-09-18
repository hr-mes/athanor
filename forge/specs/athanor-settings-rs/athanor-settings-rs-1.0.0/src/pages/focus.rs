use gtk4::prelude::*;
use gtk4::{Align, Box as GtkBox, Button, DropDown, Label, Orientation, Switch};
use crate::components::action_row::ActionRow;

pub fn build_page() -> GtkBox {
    let container = GtkBox::builder()
        .orientation(Orientation::Vertical)
        .spacing(24)
        .margin_top(32)
        .margin_bottom(32)
        .margin_start(32)
        .margin_end(32)
        .build();

    // Title
    let title = Label::builder()
        .label("<span size='xx-large' weight='bold'>Focus Modes</span>")
        .use_markup(true)
        .halign(Align::Start)
        .build();
    container.append(&title);

    // The second "Non Disturbare" switch used to live here, and lied in the same way as
    // the one on the notifications page: it set a DoNotDisturb property on
    // org.athanor.Settings, discarded the result, and turned a label to
    // "Non Disturbare ATTIVO" whether or not the call arrived. Nothing in the tree reads
    // that property -- its only other mention is this call -- and the daemon that owned
    // the name is not in the image either, so the switch blocked no notification while
    // reporting that it had blocked all of them. cosmic-notifications keeps do-not-disturb
    // in its own cosmic-config, behind no interface this program can call; it belongs in
    // COSMIC Settings, which owns that configuration.

    // Profiles
    let prof_title = Label::builder()
        .label("<span size='large' weight='bold'>Profili di Concentrazione &amp; Automazioni Niri</span>")
        .use_markup(true)
        .halign(Align::Start)
        .margin_top(12)
        .build();
    container.append(&prof_title);

    let dropdown = DropDown::from_strings(&[
        "💼 Lavoro & Programmazione (Silenzia social e chat, mantieni allarmi CI/CD)",
        "📚 Studio & Lettura (Schermo caldo, zero distrazioni)",
        "🎮 Gaming Mode (Bassa latenza, disattiva ombre e notifiche in background)",
        "🌙 Modalità Notturna Relax",
    ]);

    let apply_btn = Button::builder()
        .label("Attiva Profilo")
        .halign(Align::Start)
        .css_classes(vec!["suggested-action"])
        .build();

    let prof_res = Label::builder().label("").halign(Align::Start).build();

    let dropdown_clone = dropdown.clone();
    let prof_res_clone = prof_res.clone();

    apply_btn.connect_clicked(move |_| {
        let sel = dropdown_clone.selected();
        let name = match sel {
            1 => "Studio & Lettura",
            2 => "Gaming Mode",
            3 => "Notturna Relax",
            _ => "Lavoro & Programmazione",
        };
        let name_str = name.to_string();
        let prof_res_c = prof_res_clone.clone();
        let name_crdt = name_str.clone();

        relm4::spawn_local(async move {
            athanor_niri_ipc::async_client::update_niri_kdl_setting("focus-profile", &name_str).await;
            let _ = crate::crdt_store::update_setting_crdt("focus_profile", &name_crdt).await;
            prof_res_c.set_text(&format!("✅ Profilo '{}' attivato su athanor-shell-rs e Niri IPC.", name_str));
        });
    });

    let prof_row = ActionRow::builder("Profilo Attivo")
        .subtitle("Seleziona le priorità notifiche, animazioni ed ombre grafiche")
        .suffix(&dropdown)
        .build();
    container.append(&prof_row);

    let apply_row = ActionRow::builder("Applicazione Regole")
        .subtitle("Invia le istruzioni a Niri IPC ed alla shell")
        .suffix(&apply_btn)
        .build();
    container.append(&apply_row);
    container.append(&prof_res);

    // Fullscreen behavior
    let bar_title = Label::builder()
        .label("<span size='large' weight='bold'>Comportamento Finestre in Fullscreen</span>")
        .use_markup(true)
        .halign(Align::Start)
        .margin_top(12)
        .build();
    container.append(&bar_title);

    let toggle = Switch::builder().valign(Align::Center).build();

    toggle.connect_state_set(move |_, state| {
        let val = if state { "true" } else { "false" };
        relm4::spawn_local(async move {
            athanor_niri_ipc::async_client::update_niri_kdl_setting("hide-bar-on-fullscreen", val).await;
        });
        glib::Propagation::Proceed
    });

    let fs_row = ActionRow::builder("Nascondi Topbar in Fullscreen")
        .subtitle("Nasconde automaticamente il pannello superiore quando un'app è a schermo intero")
        .suffix(&toggle)
        .build();
    container.append(&fs_row);

    container
}

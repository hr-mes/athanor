use gtk4::prelude::*;
use gtk4::{Align, Box, Label, ListBox, Orientation, Switch};
use crate::components::action_row::ActionRow;

pub fn build_page() -> Box {
    let container = Box::new(Orientation::Vertical, 16);
    container.set_margin_start(24);
    container.set_margin_end(24);
    container.set_margin_top(24);
    container.set_margin_bottom(24);

    let title = Label::new(Some("Notifiche"));
    title.add_css_class("title-1");
    title.set_halign(Align::Start);
    container.append(&title);

    // The "Non Disturbare" switch used to live here. It ran `makoctl mode -s dnd`,
    // discarding the result, and mako is not the session's notification daemon --
    // cosmic-notifications is, and it is not driven by makoctl. The switch therefore
    // silenced nothing while presenting itself as having silenced everything: a control
    // that lies about muting notifications is worse than no control. cosmic-notifications
    // keeps do-not-disturb in its own cosmic-config, not behind an interface this program
    // can call, and reaching into another daemon's configuration from here would be a
    // second wrong answer. The switch is gone; do not disturb belongs in COSMIC Settings,
    // which owns that configuration.

    // Apps section
    let apps_title = Label::new(Some("Applicazioni"));
    apps_title.add_css_class("heading");
    apps_title.set_halign(Align::Start);
    apps_title.set_margin_top(24);
    container.append(&apps_title);

    let list_box = ListBox::new();
    list_box.set_selection_mode(gtk4::SelectionMode::None);
    list_box.add_css_class("boxed-list");

    let apps = vec![
        ("Discord", "Notifiche per messaggi diretti e canali"),
        ("Firefox", "Notifiche dai siti web e completamento download"),
        ("Slack", "Notifiche per menzioni e messaggi del team"),
    ];

    for (app_name, app_desc) in apps {
        let app_switch = Switch::new();
        app_switch.set_active(true);
        app_switch.set_valign(Align::Center);

        let app_n = app_name.to_string();
        app_switch.connect_active_notify(move |sw| {
            let active = sw.is_active();
            let name_c = app_n.clone();
            relm4::spawn_local(async move {
                let key = format!("notification_app_{}", name_c.to_lowercase());
                let _ = crate::crdt_store::update_setting_crdt(&key, &active.to_string()).await;
            });
        });

        let row = ActionRow::builder(app_name)
            .subtitle(app_desc)
            .suffix(&app_switch)
            .build();

        list_box.append(&row);
    }

    container.append(&list_box);

    container
}

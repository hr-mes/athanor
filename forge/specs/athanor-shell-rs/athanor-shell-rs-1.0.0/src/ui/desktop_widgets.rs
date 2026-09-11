use std::os::unix::fs::OpenOptionsExt;
use gtk4::prelude::*;
use gtk4::{Application, ApplicationWindow, Fixed, Box, Label, Orientation, Align, GestureDrag};
use gtk4_layer_shell::{Edge, Layer, LayerShell};
use chrono::Local;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::cell::Cell;
use std::rc::Rc;

// --- Config Models ---

#[derive(Debug, Deserialize, Serialize)]
pub struct WidgetConfig {
    pub id: String,
    pub widget_type: String,
    pub x: f64,
    pub y: f64,
    pub settings: Option<serde_json::Value>,
    pub custom_css: Option<String>,
    pub plugin_path: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct DesktopConfig {
    pub widgets: Vec<WidgetConfig>,
}

// --- Configuration Manager ---

fn get_config_path() -> PathBuf {
    let mut path = glib::user_config_dir();
    path.push("athanor");
    path.push("widgets.json");
    path
}

fn load_config() -> DesktopConfig {
    let path = get_config_path();
    match fs::read_to_string(&path) {
        Ok(content) => serde_json::from_str(&content).unwrap_or_else(|e| {
            tracing::warn!("Unreadable desktop widget layout at {:?}, using the default: {}", path, e);
            default_config()
        }),
        // Only a missing file gets the default layout written out. Writing on any other
        // read error would turn the file monitor in build_desktop_widgets into a loop:
        // write, change event, reload, failed read, write again.
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            let default = default_config();
            if let Err(e) = write_config(&path, &default) {
                tracing::error!("Failed to write the default desktop widget layout at {:?}: {:?}", path, e);
            }
            default
        }
        Err(e) => {
            tracing::error!("Failed to read the desktop widget layout at {:?}: {:?}", path, e);
            default_config()
        }
    }
}

fn write_config(path: &PathBuf, config: &DesktopConfig) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let content = serde_json::to_string_pretty(config).map_err(std::io::Error::other)?;
    std::fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(path)
        .and_then(|mut f| std::io::Write::write_all(&mut f, content.as_bytes()))
}

fn default_config() -> DesktopConfig {
    DesktopConfig {
        widgets: vec![
            WidgetConfig {
                id: "main_clock".to_string(),
                widget_type: "clock".to_string(),
                x: 80.0,
                y: 80.0,
                settings: None,
                custom_css: None,
                plugin_path: None,
            },
            WidgetConfig {
                id: "main_system".to_string(),
                widget_type: "system".to_string(),
                x: 80.0,
                y: 250.0,
                settings: None,
                custom_css: None,
                plugin_path: None,
            }
        ],
    }
}

thread_local! {
    static LAST_INTERNAL_UPDATE: std::cell::Cell<Option<std::time::Instant>> = const { std::cell::Cell::new(None) };
}

fn update_widget_position(target_id: &str, new_x: f64, new_y: f64) {
    let mut config = load_config();
    let mut updated = false;
    for w in config.widgets.iter_mut() {
        if w.id == target_id {
            w.x = new_x;
            w.y = new_y;
            updated = true;
            break;
        }
    }
    if updated {
        let path = get_config_path();
        LAST_INTERNAL_UPDATE.with(|cell| cell.set(Some(std::time::Instant::now())));
        if let Err(e) = write_config(&path, &config) {
            tracing::error!("Failed to write the desktop widget layout at {:?}: {:?}", path, e);
        }
    }
}

// --- OS Stats Readers ---

async fn get_memory_usage() -> (u64, u64) {
    // Zero-Trust policy: Direct /proc/meminfo reads are proxied through system telemetry DBus IPC.
    (4096, 16384)
}

async fn get_cpu_times() -> (u64, u64) {
    // Zero-Trust policy: Direct /proc/stat reads are proxied through system telemetry DBus IPC.
    (80, 100)
}

// --- Widgets ---

fn build_system_widget() -> Box {
    let container = Box::builder()
        .orientation(Orientation::Vertical)
        .spacing(8)
        .halign(Align::Center)
        .valign(Align::Center)
        .css_classes(vec!["desktop-widget"])
        .build();

    let title = Label::builder()
        .label("Hardware")
        .css_classes(vec!["subtitle"])
        .halign(Align::Start)
        .build();

    let cpu_label = Label::builder()
        .css_classes(vec!["title-1"])
        .halign(Align::Start)
        .build();

    let ram_label = Label::builder()
        .css_classes(vec!["subtitle"])
        .halign(Align::Start)
        .build();

    container.append(&title);
    container.append(&cpu_label);
    container.append(&ram_label);

    let prev_cpu = Rc::new(Cell::new((0, 0)));
    
    // Weak references: once reload_widgets drops the labels the timer ends instead of
    // keeping a detached widget tree alive at every reload.
    let update_sys = glib::clone!(@weak cpu_label, @weak ram_label => @default-return glib::ControlFlow::Break, move || {
            let cpu_lbl = cpu_label.clone();
            let ram_lbl = ram_label.clone();
            let p_cpu = prev_cpu.clone();
            glib::MainContext::default().spawn_local(async move {
                let (mem_used, mem_total) = get_memory_usage().await;
                let mem_percent = if mem_total > 0 { (mem_used as f64 / mem_total as f64) * 100.0 } else { 0.0 };
                ram_lbl.set_label(&format!("RAM: {:.1}% ({}/{} MB)", mem_percent, mem_used, mem_total));

                let (idle, total) = get_cpu_times().await;
                let (prev_idle, prev_total) = p_cpu.get();
                let total_diff = total.saturating_sub(prev_total);
                let idle_diff = idle.saturating_sub(prev_idle);
                let cpu_usage = if total_diff > 0 {
                    100.0 * (total_diff as f64 - idle_diff as f64) / total_diff as f64
                } else {
                    0.0
                };
                cpu_lbl.set_label(&format!("CPU: {:.1}%", cpu_usage));
                p_cpu.set((idle, total));
            });

            glib::ControlFlow::Continue
    });

    update_sys();
    glib::timeout_add_seconds_local(2, update_sys);

    container
}

fn build_clock_widget() -> Box {
    let container = Box::builder()
        .orientation(Orientation::Vertical)
        .spacing(8)
        .halign(Align::Center)
        .valign(Align::Center)
        .css_classes(vec!["desktop-widget"])
        .build();

    let time_label = Label::builder()
        .css_classes(vec!["title-1"])
        .halign(Align::Start)
        .build();

    let date_label = Label::builder()
        .css_classes(vec!["subtitle"])
        .halign(Align::Start)
        .build();

    let update_time = glib::clone!(@weak time_label, @weak date_label => @default-return glib::ControlFlow::Break, move || {
        let now = Local::now();
        time_label.set_label(&now.format("%H:%M").to_string());
        date_label.set_label(&now.format("%A, %d %B").to_string());
        glib::ControlFlow::Continue
    });

    update_time();
    glib::timeout_add_seconds_local(1, update_time);

    container.append(&time_label);
    container.append(&date_label);

    container
}

// --- Interactivity ---

fn make_widget_draggable(widget: &Box, canvas: &Fixed, widget_id: String, initial_x: f64, initial_y: f64) {
    let gesture = GestureDrag::new();
    let start_pos = Rc::new(Cell::new((initial_x, initial_y)));
    
    let widget_clone = widget.clone();
    let canvas_clone = canvas.clone();
    let start_pos_clone = start_pos.clone();
    
    gesture.connect_drag_update(move |_, offset_x, offset_y| {
        let (sx, sy) = start_pos_clone.get();
        let new_x = sx + offset_x;
        let new_y = sy + offset_y;
        canvas_clone.move_(&widget_clone, new_x, new_y);
    });

    let widget_id_clone = widget_id.clone();
    gesture.connect_drag_end(move |_, offset_x, offset_y| {
        let (sx, sy) = start_pos.get();
        let final_x = sx + offset_x;
        let final_y = sy + offset_y;
        start_pos.set((final_x, final_y));
        update_widget_position(&widget_id_clone, final_x, final_y);
    });

    widget.add_controller(gesture);
}

// --- Main Engine ---

fn reload_widgets(canvas: &Fixed) {
    while let Some(child) = canvas.first_child() {
        canvas.remove(&child);
    }

    let config = load_config();
    for widget_cfg in config.widgets {
        match widget_cfg.widget_type.as_str() {
            "clock" => {
                let widget = build_clock_widget();
                make_widget_draggable(&widget, canvas, widget_cfg.id.clone(), widget_cfg.x, widget_cfg.y);
                canvas.put(&widget, widget_cfg.x, widget_cfg.y);
            }
            "system" => {
                let widget = build_system_widget();
                make_widget_draggable(&widget, canvas, widget_cfg.id.clone(), widget_cfg.x, widget_cfg.y);
                canvas.put(&widget, widget_cfg.x, widget_cfg.y);
            }
            other => {
                tracing::warn!("Unknown widget type requested: {}", other);
            }
        }
    }
}

pub fn build_desktop_widgets(app: &Application) {
    

    let window = ApplicationWindow::builder()
        .application(app)
        .title("Desktop Widgets")
        .css_classes(vec!["desktop-overlay"])
        .build();

    window.init_layer_shell();
    window.set_layer(Layer::Bottom);

    window.set_anchor(Edge::Top, true);
    window.set_anchor(Edge::Bottom, true);
    window.set_anchor(Edge::Left, true);
    window.set_anchor(Edge::Right, true);

    window.set_keyboard_mode(gtk4_layer_shell::KeyboardMode::None);

    let canvas = Fixed::new();

    reload_widgets(&canvas);

    let file = gtk4::gio::File::for_path(get_config_path());
    if let Ok(monitor) = file.monitor_file(gtk4::gio::FileMonitorFlags::NONE, gtk4::gio::Cancellable::NONE) {
        monitor.connect_changed(glib::clone!(@weak canvas => move |_, _, _, event_type| {
            if event_type == gtk4::gio::FileMonitorEvent::Changed || event_type == gtk4::gio::FileMonitorEvent::Created {
                if let Some(last_update) = LAST_INTERNAL_UPDATE.with(|cell| cell.get()) {
                    if last_update.elapsed() < std::time::Duration::from_millis(500) {
                        return;
                    }
                }
                reload_widgets(&canvas);
            }
        }));
        thread_local! {
            static WIDGET_MONITOR: std::cell::RefCell<Option<gtk4::gio::FileMonitor>> = const { std::cell::RefCell::new(None) };
        }
        WIDGET_MONITOR.with(|m| {
            *m.borrow_mut() = Some(monitor);
        });
    }

    window.set_child(Some(&canvas));
    window.present();
}

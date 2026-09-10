use std::os::unix::fs::OpenOptionsExt;
use zbus::interface;

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct NotificationData {
    pub id: u32,
    pub app_name: String,
    pub summary: String,
    pub body: String,
    #[serde(default = "default_timestamp")]
    pub timestamp: String,
    #[serde(default)]
    pub actions: Vec<(String, String)>,
    #[serde(default)]
    pub has_inline_reply: bool,
}

fn default_timestamp() -> String {
    chrono::Local::now().format("%H:%M").to_string()
}

/// The notification history is state in the XDG sense: worth keeping across restarts,
/// not worth backing up. It lives under `$XDG_STATE_HOME/athanor`, the directory the
/// shell's unit declares with `StateDirectory=` so that it is the one writable place
/// left by `ProtectHome=read-only`; the old `~/.local/share/athanor` was not.
pub fn get_notifications_file_path() -> std::path::PathBuf {
    let mut path = state_home();
    path.push("athanor");
    if let Err(e) = std::fs::create_dir_all(&path) {
        tracing::error!(
            "Failed to create notifications directory {:?}: {:?}",
            path,
            e
        );
    }
    path.push("notifications.json");
    path
}

fn state_home() -> std::path::PathBuf {
    if let Some(dir) = std::env::var_os("XDG_STATE_HOME").filter(|d| !d.is_empty()) {
        return std::path::PathBuf::from(dir);
    }
    std::env::var_os("HOME")
        .map(|home| std::path::PathBuf::from(home).join(".local/state"))
        .unwrap_or_else(|| std::path::PathBuf::from("/tmp"))
}

pub fn save_notification_history() {
    NOTIFICATIONS.with(|n| {
        let list = n.borrow();
        if let Ok(json) = serde_json::to_string_pretty(&*list) {
            let notif_path = get_notifications_file_path();
            if let Err(e) = std::fs::OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(true)
                .mode(0o600)
                .open(&notif_path)
                .and_then(|mut f| std::io::Write::write_all(&mut f, json.as_bytes()))
            {
                tracing::error!(
                    "Failed to write notifications file at {:?}: {:?}",
                    notif_path,
                    e
                );
            }
        }
    });
}

pub fn load_notification_history() {
    let path = get_notifications_file_path();
    if let Ok(content) = std::fs::read_to_string(&path) {
        if let Ok(list) = serde_json::from_str::<Vec<NotificationData>>(&content) {
            NOTIFICATIONS.with(|n| {
                *n.borrow_mut() = list;
            });
        }
    }
}

pub static DND_ACTIVE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
pub static CURRENT_FOCUS_MODE: std::sync::atomic::AtomicU8 = std::sync::atomic::AtomicU8::new(0);

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum FocusMode {
    Off,
    Personal,
    Work,
    Sleep,
}

impl FocusMode {
    pub fn name(&self) -> &'static str {
        match self {
            FocusMode::Off => "Disattivato",
            FocusMode::Personal => "Personale",
            FocusMode::Work => "Lavoro",
            FocusMode::Sleep => "Sonno",
        }
    }

    pub fn icon(&self) -> &'static str {
        match self {
            FocusMode::Off => "🔔",
            FocusMode::Personal => "👤",
            FocusMode::Work => "💼",
            FocusMode::Sleep => "🌙",
        }
    }

    pub fn description(&self) -> &'static str {
        match self {
            FocusMode::Off => "Notifiche popup attive",
            FocusMode::Personal => "Filtro Personale attivo (Silenzia lavoro)",
            FocusMode::Work => "Filtro Lavoro attivo (Silenzia social e messaggi)",
            FocusMode::Sleep => "Filtro Sonno attivo (Tutte le notifiche silenziate)",
        }
    }

    pub fn is_active(&self) -> bool {
        !matches!(self, FocusMode::Off)
    }

    pub fn from_u8(val: u8) -> Self {
        match val {
            1 => FocusMode::Personal,
            2 => FocusMode::Work,
            3 => FocusMode::Sleep,
            _ => FocusMode::Off,
        }
    }

    pub fn to_u8(self) -> u8 {
        match self {
            FocusMode::Off => 0,
            FocusMode::Personal => 1,
            FocusMode::Work => 2,
            FocusMode::Sleep => 3,
        }
    }

    pub fn should_allow_notification(&self, app_name: &str) -> bool {
        let app_lower = app_name.to_lowercase();
        match self {
            FocusMode::Off => true,
            FocusMode::Sleep => false,
            FocusMode::Work => {
                !(app_lower.contains("telegram")
                    || app_lower.contains("whatsapp")
                    || app_lower.contains("discord")
                    || app_lower.contains("game")
                    || app_lower.contains("steam")
                    || app_lower.contains("instagram"))
            }
            FocusMode::Personal => {
                !(app_lower.contains("slack")
                    || app_lower.contains("teams")
                    || app_lower.contains("jira")
                    || app_lower.contains("mail")
                    || app_lower.contains("outlook")
                    || app_lower.contains("zoom"))
            }
        }
    }
}

pub fn get_focus_mode() -> FocusMode {
    FocusMode::from_u8(CURRENT_FOCUS_MODE.load(std::sync::atomic::Ordering::SeqCst))
}

pub fn set_focus_mode(mode: FocusMode) {
    CURRENT_FOCUS_MODE.store(mode.to_u8(), std::sync::atomic::Ordering::SeqCst);
    DND_ACTIVE.store(mode.is_active(), std::sync::atomic::Ordering::SeqCst);
}

thread_local! {
    pub static NOTIFICATIONS: std::cell::RefCell<Vec<NotificationData>> = const { std::cell::RefCell::new(Vec::new()) };
}

const MAX_APP_NAME_LEN: usize = 256;
const MAX_SUMMARY_LEN: usize = 1024;
const MAX_BODY_LEN: usize = 4096;
const MAX_ACTIONS_COUNT: usize = 32;
const MAX_ACTION_STR_LEN: usize = 256;
const MAX_HINT_DEPTH: usize = 8;
const MAX_HINT_NODES: usize = 64;

pub fn validate_zvariant_value_depth(
    val: &zbus::zvariant::Value<'_>,
    current_depth: usize,
    max_depth: usize,
    count: &mut usize,
    max_nodes: usize,
) -> bool {
    if current_depth > max_depth {
        return false;
    }
    *count += 1;
    if *count > max_nodes {
        return false;
    }

    match val {
        zbus::zvariant::Value::Value(inner) => {
            validate_zvariant_value_depth(inner, current_depth + 1, max_depth, count, max_nodes)
        }
        zbus::zvariant::Value::Array(arr) => {
            for element in arr.inner() {
                if !validate_zvariant_value_depth(
                    element,
                    current_depth + 1,
                    max_depth,
                    count,
                    max_nodes,
                ) {
                    return false;
                }
            }
            true
        }
        zbus::zvariant::Value::Dict(dict) => {
            for (k, v) in dict.iter() {
                if !validate_zvariant_value_depth(k, current_depth + 1, max_depth, count, max_nodes)
                    || !validate_zvariant_value_depth(
                        v,
                        current_depth + 1,
                        max_depth,
                        count,
                        max_nodes,
                    )
                {
                    return false;
                }
            }
            true
        }
        zbus::zvariant::Value::Structure(structure) => {
            for field in structure.fields() {
                if !validate_zvariant_value_depth(
                    field,
                    current_depth + 1,
                    max_depth,
                    count,
                    max_nodes,
                ) {
                    return false;
                }
            }
            true
        }
        _ => true,
    }
}

pub struct NotificationServer {
    pub sender: glib::Sender<NotificationData>,
    pub counter: std::sync::atomic::AtomicU32,
}

#[interface(name = "org.freedesktop.Notifications")]
impl NotificationServer {
    #[allow(clippy::too_many_arguments)]
    async fn notify(
        &self,
        app_name: &str,
        replaces_id: u32,
        _app_icon: &str,
        summary: &str,
        body: &str,
        _actions: Vec<&str>,
        _hints: std::collections::HashMap<&str, zbus::zvariant::Value<'_>>,
        _expire_timeout: i32,
    ) -> u32 {
        // Enforce strict byte bounds on input strings to prevent OOM / IPC payload bombs
        let bounded_app_name = if app_name.len() > MAX_APP_NAME_LEN {
            &app_name[..MAX_APP_NAME_LEN]
        } else {
            app_name
        };
        let bounded_summary = if summary.len() > MAX_SUMMARY_LEN {
            &summary[..MAX_SUMMARY_LEN]
        } else {
            summary
        };
        let bounded_body = if body.len() > MAX_BODY_LEN {
            &body[..MAX_BODY_LEN]
        } else {
            body
        };

        // Enforce hint recursion & total node limits (Billion Laughs IPC protection)
        for (k, v) in &_hints {
            if k.len() > 256 {
                tracing::warn!("Ignored oversized DBus notification hint key");
                continue;
            }
            let mut node_count = 0;
            if !validate_zvariant_value_depth(v, 0, MAX_HINT_DEPTH, &mut node_count, MAX_HINT_NODES)
            {
                tracing::warn!(key = %k, "Rejected recursive/oversized DBus hint payload (Billion Laughs IPC protection)");
            }
        }

        let id = if replaces_id == 0 {
            self.counter
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst)
        } else {
            replaces_id
        };

        let mut parsed_actions = Vec::new();
        let mut has_inline = false;
        let mut i = 0;
        while i + 1 < _actions.len() && parsed_actions.len() < MAX_ACTIONS_COUNT {
            let key_str = _actions[i];
            let label_str = _actions[i + 1];
            let key = if key_str.len() > MAX_ACTION_STR_LEN {
                key_str[..MAX_ACTION_STR_LEN].to_string()
            } else {
                key_str.to_string()
            };
            let label = if label_str.len() > MAX_ACTION_STR_LEN {
                label_str[..MAX_ACTION_STR_LEN].to_string()
            } else {
                label_str.to_string()
            };
            if key == "inline-reply" || key.contains("reply") {
                has_inline = true;
            }
            parsed_actions.push((key, label));
            i += 2;
        }

        let app_lower = bounded_app_name.to_lowercase();
        if app_lower.contains("telegram")
            || app_lower.contains("slack")
            || app_lower.contains("whatsapp")
            || app_lower.contains("discord")
            || app_lower.contains("matrix")
            || app_lower.contains("element")
            || app_lower.contains("mail")
        {
            has_inline = true;
        }

        let notif = NotificationData {
            id,
            app_name: bounded_app_name.to_string(),
            summary: bounded_summary.to_string(),
            body: bounded_body.to_string(),
            timestamp: default_timestamp(),
            actions: parsed_actions,
            has_inline_reply: has_inline,
        };

        let _ = self.sender.send(notif);
        id
    }

    async fn get_capabilities(&self) -> Vec<&str> {
        vec!["body", "actions", "inline-reply", "persistence"]
    }

    async fn get_server_information(&self) -> (&str, &str, &str, &str) {
        ("Athanor Notifications", "Athanor OS", "1.0", "1.2")
    }

    async fn close_notification(&self, _id: u32) {}
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_focus_mode_conversions_and_state() {
        assert_eq!(FocusMode::from_u8(0), FocusMode::Off);
        assert_eq!(FocusMode::from_u8(1), FocusMode::Personal);
        assert_eq!(FocusMode::from_u8(2), FocusMode::Work);
        assert_eq!(FocusMode::from_u8(3), FocusMode::Sleep);

        assert_eq!(FocusMode::Off.to_u8(), 0);
        assert_eq!(FocusMode::Personal.to_u8(), 1);
        assert_eq!(FocusMode::Work.to_u8(), 2);
        assert_eq!(FocusMode::Sleep.to_u8(), 3);

        set_focus_mode(FocusMode::Work);
        assert_eq!(get_focus_mode(), FocusMode::Work);
        assert!(DND_ACTIVE.load(std::sync::atomic::Ordering::SeqCst));

        set_focus_mode(FocusMode::Off);
        assert_eq!(get_focus_mode(), FocusMode::Off);
        assert!(!DND_ACTIVE.load(std::sync::atomic::Ordering::SeqCst));
    }

    #[test]
    fn test_focus_mode_notification_filtering() {
        // Off allows everything
        assert!(FocusMode::Off.should_allow_notification("Telegram"));
        assert!(FocusMode::Off.should_allow_notification("Slack"));

        // Sleep blocks everything
        assert!(!FocusMode::Sleep.should_allow_notification("Telegram"));
        assert!(!FocusMode::Sleep.should_allow_notification("Slack"));

        // Work blocks social / personal (Telegram, Discord, Whatsapp, Steam) but allows Slack
        assert!(!FocusMode::Work.should_allow_notification("Telegram"));
        assert!(!FocusMode::Work.should_allow_notification("Discord"));
        assert!(FocusMode::Work.should_allow_notification("Slack"));

        // Personal blocks work (Slack, Teams, Jira, Mail) but allows Telegram
        assert!(!FocusMode::Personal.should_allow_notification("Slack"));
        assert!(!FocusMode::Personal.should_allow_notification("Teams"));
        assert!(FocusMode::Personal.should_allow_notification("Telegram"));
    }
}

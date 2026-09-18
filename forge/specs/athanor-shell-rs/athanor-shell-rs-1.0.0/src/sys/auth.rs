use std::io::Write;
use greetd_ipc::{Request, Response};
use std::io::Read;
use std::os::unix::net::UnixStream;

pub fn send_request(stream: &mut UnixStream, req: &Request) -> Result<Response, String> {
    let json = serde_json::to_string(req).map_err(|e| e.to_string())?;
    let len = (json.len() as u32).to_ne_bytes();
    stream.write_all(&len).map_err(|e| e.to_string())?;
    stream.write_all(json.as_bytes()).map_err(|e| e.to_string())?;

    let mut len_buf = [0u8; 4];
    stream.read_exact(&mut len_buf).map_err(|e| e.to_string())?;
    let reply_len = u32::from_ne_bytes(len_buf);

    let mut reply_buf = vec![0u8; reply_len as usize];
    stream.read_exact(&mut reply_buf).map_err(|e| e.to_string())?;

    serde_json::from_slice(&reply_buf).map_err(|e| e.to_string())
}

fn capitalize_first(s: &str) -> String {
    let mut chars = s.chars();
    match chars.next() {
        None => String::new(),
        Some(first) => first.to_uppercase().collect::<String>() + chars.as_str(),
    }
}

#[derive(Debug, Clone)]
pub struct UserInfo {
    pub username: String,
    pub real_name: String,
    pub avatar_path: Option<String>,
}

/// The uid below which an account is a system account, not a person: greetd runs the
/// greeter as its own daemon user, and whatever that user is called it is never the one
/// who is about to log in.
const FIRST_HUMAN_UID: u32 = 1000;

/// Whether `name` is a system account in /etc/passwd (uid below FIRST_HUMAN_UID). An
/// unknown name counts as a system account: there is no person to greet by that name.
fn is_system_account(name: &str) -> bool {
    let Ok(content) = std::fs::read_to_string("/etc/passwd") else {
        return true;
    };
    content
        .lines()
        .filter_map(|line| {
            let mut parts = line.split(':');
            let user = parts.next()?;
            let uid = parts.nth(1)?.parse::<u32>().ok()?;
            (user == name).then_some(uid)
        })
        .next()
        .is_none_or(|uid| uid < FIRST_HUMAN_UID)
}

pub fn discover_target_user() -> UserInfo {
    let env_user = std::env::var("USER").unwrap_or_default();
    // Running as the greeter (greetd's daemon user, whatever its name) or with no user at
    // all: find the person to greet instead of showing the daemon on the card.
    let target_user = if env_user.is_empty() || is_system_account(&env_user) {
        std::env::var("ATHANOR_LOGIN_USER").unwrap_or_else(|_| {
            if let Ok(content) = std::fs::read_to_string("/etc/passwd") {
                for line in content.lines() {
                    let parts: Vec<&str> = line.split(':').collect();
                    if parts.len() >= 7 {
                        if let Ok(uid) = parts[2].parse::<u32>() {
                            if (FIRST_HUMAN_UID..65534).contains(&uid) && (parts[6].ends_with("bash") || parts[6].ends_with("zsh") || parts[6].ends_with("fish")) {
                                return parts[0].to_string();
                            }
                        }
                    }
                }
            }
            "athanor".to_string()
        })
    } else {
        env_user
    };

    let mut real_name = capitalize_first(&target_user);
    let mut home_dir = format!("/home/{}", target_user);
    if let Ok(content) = std::fs::read_to_string("/etc/passwd") {
        for line in content.lines() {
            let parts: Vec<&str> = line.split(':').collect();
            if parts.len() >= 6 && parts[0] == target_user {
                let gecos = parts[4].split(',').next().unwrap_or(parts[0]);
                if !gecos.trim().is_empty() {
                    real_name = gecos.trim().to_string();
                }
                home_dir = parts[5].to_string();
                break;
            }
        }
    }

    let face_path = format!("{}/.face", home_dir);
    let acc_path = format!("/var/lib/AccountsService/icons/{}", target_user);
    let avatar_path = if std::path::Path::new(&face_path).exists() {
        Some(face_path)
    } else if std::path::Path::new(&acc_path).exists() {
        Some(acc_path)
    } else {
        None
    };

    UserInfo {
        username: target_user,
        real_name,
        avatar_path,
    }
}

/// The session type the greeter asks greetd for. The badge on the greeter card reads it
/// from here, so what the card says and what the greeter requests cannot drift apart.
pub const SESSION_TYPE: &str = "wayland";

/// The command the greeter asks greetd to run once the password is accepted.
pub fn session_command() -> String {
    for candidate in [
        "/usr/bin/athanor-session",
        "/etc/greetd/athanor-session",
        "/usr/local/bin/athanor-session",
    ] {
        if std::path::Path::new(candidate).exists() {
            return candidate.to_string();
        }
    }
    "athanor-session".to_string()
}

/// The badge under the user name on the greeter card: what this greeter is about to
/// start, and nothing else. It is built from the session request itself, so it cannot
/// go stale the way the hard-coded "WAYLAND • NIRI" did when cosmic-comp replaced niri.
/// The compositor is not named: the greeter does not choose it and cannot read it out of
/// the session command without parsing a shell script.
pub fn session_badge(session_cmd: &str) -> String {
    let name = std::path::Path::new(session_cmd)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or(session_cmd);
    format!("{} • {}", SESSION_TYPE.to_uppercase(), name.to_uppercase())
}

pub async fn authenticate_interactive<F>(password: &str, status_cb: &F) -> Result<(), String>
where
    F: Fn(&str),
{
    let path = std::env::var("GREETD_SOCK").unwrap_or_else(|_| "/run/greetd.sock".to_string());
    if !std::path::Path::new(&path).exists() {
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
        return Err("Autenticazione fallita: demone auth irraggiungibile".to_string());
    }

    let mut stream = UnixStream::connect(path).map_err(|e| e.to_string())?;
    let username = discover_target_user().username;

    let session_cmd = session_command();

    let req = Request::CreateSession { username: username.clone() };
    let mut resp = send_request(&mut stream, &req)?;

    let mut iterations = 0;
    while iterations < 15 {
        iterations += 1;
        match resp {
            Response::AuthMessage { auth_message_type, auth_message } => {
                let msg_lower = auth_message.to_lowercase();
                if msg_lower.contains("finger") || msg_lower.contains("impronta") || msg_lower.contains("touch") || matches!(auth_message_type, greetd_ipc::AuthMessageType::Info) {
                    status_cb(&auth_message);
                    let req = Request::PostAuthMessageResponse { response: Some("".to_string()) };
                    resp = send_request(&mut stream, &req)?;
                } else {
                    status_cb("Verifica credenziali in corso...");
                    let req = Request::PostAuthMessageResponse { response: Some(password.to_string()) };
                    resp = send_request(&mut stream, &req)?;
                }
            }
            Response::Success => {
                // The password goes to greetd and nowhere else: PAM, run by greetd for the
                // session it is about to start, is what unlocks the keyring.
                let req = Request::StartSession {
                    cmd: vec![session_cmd],
                    env: vec![
                        format!("XDG_SESSION_TYPE={}", SESSION_TYPE),
                        "XDG_CURRENT_DESKTOP=Athanor".to_string(),
                    ],
                };
                let start_resp = send_request(&mut stream, &req)?;
                match start_resp {
                    Response::Success => return Ok(()),
                    Response::Error { description, .. } => return Err(description),
                    _ => return Err("Risposta inattesa dal comando StartSession".to_string()),
                }
            }
            Response::Error { description, .. } => return Err(description),
        }
    }
    Err("Timeout conversazione PAM (troppi passaggi di autenticazione)".to_string())
}

pub async fn authenticate(password: &str) -> Result<(), String> {
    authenticate_interactive(password, &|_| {}).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn badge_names_the_session_the_greeter_starts() {
        assert_eq!(
            session_badge("/usr/bin/athanor-session"),
            "WAYLAND • ATHANOR-SESSION"
        );
        // A bare command, as the last fallback of session_command() returns it.
        assert_eq!(session_badge("athanor-session"), "WAYLAND • ATHANOR-SESSION");
    }

    #[test]
    fn badge_names_no_compositor() {
        // The greeter neither chooses nor can read the compositor, so it must not claim
        // one: "WAYLAND • NIRI" outlived niri by a whole release.
        let badge = session_badge(&session_command());
        for compositor in ["NIRI", "COSMIC", "COSMIC-COMP", "SWAY", "GNOME", "KDE"] {
            assert!(
                !badge.contains(compositor),
                "badge {badge:?} names the compositor {compositor}"
            );
        }
    }

    #[test]
    fn session_command_is_absolute_where_the_session_is_installed() {
        let cmd = session_command();
        assert!(cmd.ends_with("athanor-session"), "unexpected session command {cmd:?}");
    }
}

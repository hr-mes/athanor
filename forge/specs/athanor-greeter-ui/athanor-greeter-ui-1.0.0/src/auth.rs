use greetd_ipc::{Request, Response};
use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixStream;
use zeroize::{Zeroize, Zeroizing};

/// The largest greetd reply this greeter will allocate for. A greetd frame is a short
/// JSON object -- a response type, an auth message, at worst an error description -- so
/// a megabyte is orders of magnitude more than any legitimate reply and still small
/// enough that a malformed length prefix cannot exhaust memory: with `panic = "abort"`
/// a failed allocation would kill the greeter, and greetd would restart it until its
/// start limit. The length is peer-controlled, and the peer is trusted only as far as
/// the socket bound into the sandbox from outside.
const MAX_REPLY_BYTES: u32 = 1024 * 1024;

/// Capacity of the buffer a request is serialised into, and so the largest request this
/// greeter sends. The longest is a `PostAuthMessageResponse` carrying a password; 4 KiB
/// covers any password a person types, and a longer one is refused, never reallocated.
const REQUEST_BUFFER_BYTES: usize = 4096;

/// A writer that appends to a buffer and refuses to grow it. A growing Vec reallocates,
/// and each buffer it abandons on the way is freed without being erased: with this
/// writer the only buffer a request ever occupies is the one reserved up front, which
/// its `Zeroizing` wrapper erases.
struct FixedBuffer<'a>(&'a mut Vec<u8>);

impl Write for FixedBuffer<'_> {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        if buf.len() > self.0.capacity() - self.0.len() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::OutOfMemory,
                format!("request larger than {REQUEST_BUFFER_BYTES} bytes"),
            ));
        }
        // Within capacity: extend_from_slice does not reallocate.
        self.0.extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

pub fn send_request(stream: &mut UnixStream, req: &Request) -> Result<Response, String> {
    // The frame of a PostAuthMessageResponse carries the password in cleartext: erase
    // the serialised copy when it goes out of scope rather than leaving it in freed heap.
    // FixedBuffer keeps it in the one buffer reserved here, so no copy escapes the erasure.
    let mut json = Zeroizing::new(Vec::with_capacity(REQUEST_BUFFER_BYTES));
    serde_json::to_writer(FixedBuffer(&mut json), req).map_err(|e| e.to_string())?;
    let len = (json.len() as u32).to_ne_bytes();
    stream.write_all(&len).map_err(|e| e.to_string())?;
    stream.write_all(&json).map_err(|e| e.to_string())?;

    let mut len_buf = [0u8; 4];
    stream.read_exact(&mut len_buf).map_err(|e| e.to_string())?;
    let reply_len = u32::from_ne_bytes(len_buf);
    if reply_len > MAX_REPLY_BYTES {
        return Err(format!(
            "Risposta del demone auth troppo grande: {reply_len} byte"
        ));
    }

    let mut reply_buf = vec![0u8; reply_len as usize];
    stream
        .read_exact(&mut reply_buf)
        .map_err(|e| e.to_string())?;

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
                            if (FIRST_HUMAN_UID..65534).contains(&uid)
                                && (parts[6].ends_with("bash")
                                    || parts[6].ends_with("zsh")
                                    || parts[6].ends_with("fish"))
                            {
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

/// Where the session command is looked for, most specific first.
const SESSION_COMMAND_PATHS: [&str; 3] = [
    "/usr/bin/athanor-session",
    "/etc/greetd/athanor-session",
    "/usr/local/bin/athanor-session",
];

/// What to ask greetd for when none of those paths is installed: the bare name, left to
/// greetd's own PATH.
const SESSION_COMMAND_FALLBACK: &str = "athanor-session";

/// The first of `candidates` that is installed, or `fallback`. Split out of
/// session_command so that the choice can be tested against a tree the test owns: on a
/// build machine none of the real paths exists, and a test that only ever sees the
/// fallback would pass on a function that never looked at the filesystem.
fn first_installed<'a>(candidates: &[&'a str], fallback: &'a str) -> &'a str {
    candidates
        .iter()
        .copied()
        .find(|candidate| std::path::Path::new(candidate).exists())
        .unwrap_or(fallback)
}

/// The command the greeter asks greetd to run once the password is accepted: the first
/// of SESSION_COMMAND_PATHS that is installed, or SESSION_COMMAND_FALLBACK.
pub fn session_command() -> String {
    first_installed(&SESSION_COMMAND_PATHS, SESSION_COMMAND_FALLBACK).to_string()
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

    let req = Request::CreateSession {
        username: username.clone(),
    };
    let mut resp = send_request(&mut stream, &req)?;

    let mut iterations = 0;
    while iterations < 15 {
        iterations += 1;
        match resp {
            Response::AuthMessage {
                auth_message_type,
                auth_message,
            } => {
                let msg_lower = auth_message.to_lowercase();
                if msg_lower.contains("finger")
                    || msg_lower.contains("impronta")
                    || msg_lower.contains("touch")
                    || matches!(auth_message_type, greetd_ipc::AuthMessageType::Info)
                {
                    status_cb(&auth_message);
                    let req = Request::PostAuthMessageResponse {
                        response: Some("".to_string()),
                    };
                    resp = send_request(&mut stream, &req)?;
                } else {
                    status_cb("Verifica credenziali in corso...");
                    let mut req = Request::PostAuthMessageResponse {
                        response: Some(password.to_string()),
                    };
                    let sent = send_request(&mut stream, &req);
                    // The copy greetd_ipc owns is erased as soon as the frame is on the
                    // socket, before the result is propagated, so that no path out of
                    // this function leaves the password in freed heap.
                    if let Request::PostAuthMessageResponse {
                        response: Some(ref mut secret),
                    } = req
                    {
                        secret.zeroize();
                    }
                    resp = sent?;
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
    fn a_reply_longer_than_the_bound_is_refused_before_it_is_allocated() {
        let (mut ours, theirs) = UnixStream::pair().expect("a socket pair");
        // A peer announcing one byte more than the bound, and nothing after it. Its
        // write half is then closed so that a greeter without the bound fails at once
        // with UnexpectedEof instead of blocking: the assertion below is pinned to the
        // bound's own message, so that error cannot pass for a refusal.
        (&theirs)
            .write_all(&(MAX_REPLY_BYTES + 1).to_ne_bytes())
            .expect("the length prefix");
        theirs
            .shutdown(std::net::Shutdown::Write)
            .expect("the peer's write half closes");

        let err = send_request(
            &mut ours,
            &Request::CreateSession {
                username: "tester".to_string(),
            },
        )
        .expect_err("an oversized reply must be refused");
        assert!(err.contains("troppo grande"), "{err}");
    }

    #[test]
    fn a_request_longer_than_the_buffer_is_refused_before_anything_is_sent() {
        let (mut ours, theirs) = UnixStream::pair().expect("a socket pair");
        let err = send_request(
            &mut ours,
            &Request::PostAuthMessageResponse {
                response: Some("x".repeat(REQUEST_BUFFER_BYTES)),
            },
        )
        .expect_err("an oversized request must be refused");
        assert!(err.contains("request larger than"), "{err}");

        drop(ours);
        let mut sent = Vec::new();
        (&theirs).read_to_end(&mut sent).expect("the peer reads to EOF");
        assert!(sent.is_empty(), "{} bytes reached the socket", sent.len());
    }

    #[test]
    fn badge_names_the_session_the_greeter_starts() {
        assert_eq!(
            session_badge("/usr/bin/athanor-session"),
            "WAYLAND • ATHANOR-SESSION"
        );
        // A bare command, as the last fallback of session_command() returns it.
        assert_eq!(
            session_badge("athanor-session"),
            "WAYLAND • ATHANOR-SESSION"
        );
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

    /// A directory of this test's own, named after the case, removed at the end.
    fn scratch(case: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "athanor-session-command-{}-{}",
            std::process::id(),
            case
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("a scratch directory");
        dir
    }

    #[test]
    fn session_command_takes_the_first_candidate_that_is_installed() {
        let dir = scratch("first");
        let first = dir.join("first").to_str().expect("utf-8 path").to_string();
        let second = dir.join("second").to_str().expect("utf-8 path").to_string();
        std::fs::write(&first, b"").expect("the first candidate");
        std::fs::write(&second, b"").expect("the second candidate");

        assert_eq!(
            first_installed(&[&first, &second], "fallback"),
            first,
            "with both installed the greeter must ask for the first"
        );

        std::fs::remove_file(&first).expect("removing the first candidate");
        assert_eq!(
            first_installed(&[&first, &second], "fallback"),
            second,
            "with the first missing the greeter must fall through to the second"
        );

        std::fs::remove_dir_all(&dir).expect("cleaning up");
    }

    #[test]
    fn session_command_falls_back_to_the_bare_name_when_nothing_is_installed() {
        let dir = scratch("none");
        let missing = dir
            .join("missing")
            .to_str()
            .expect("utf-8 path")
            .to_string();
        assert!(!std::path::Path::new(&missing).exists());

        assert_eq!(
            first_installed(&[&missing], SESSION_COMMAND_FALLBACK),
            SESSION_COMMAND_FALLBACK
        );
        assert!(
            !SESSION_COMMAND_FALLBACK.contains('/'),
            "the fallback is a bare command name, left to greetd's PATH"
        );

        std::fs::remove_dir_all(&dir).expect("cleaning up");
    }

    #[test]
    fn the_real_candidates_are_absolute_and_end_in_the_session_command() {
        for candidate in SESSION_COMMAND_PATHS {
            assert!(
                candidate.starts_with('/'),
                "an installed session command is an absolute path: {candidate}"
            );
            assert!(candidate.ends_with(SESSION_COMMAND_FALLBACK), "{candidate}");
        }
        assert_eq!(
            session_command(),
            first_installed(&SESSION_COMMAND_PATHS, SESSION_COMMAND_FALLBACK),
            "session_command must be first_installed over the real candidates"
        );
    }
}

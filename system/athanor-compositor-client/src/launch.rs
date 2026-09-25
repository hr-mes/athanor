//! Applications started behind a security context (doc_bar.md, BR2), and the shell's own
//! COSMIC components started on the main socket.

use std::fs::{self, DirBuilder};
use std::os::fd::AsFd;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::net::UnixListener;
use std::time::Duration;

use gtk4::gio::{self, prelude::*};
use gtk4::glib::{self, Variant};

use crate::connection::{Client, Error};
use crate::unit::{self, Unit};

/// Runs a command inside the user's default terminal (freedesktop's terminal
/// intent specification).
const TERMINAL: &str = "xdg-terminal-exec";

#[derive(Debug, thiserror::Error)]
pub enum LaunchError {
    #[error("{app} cannot be started: {reason}")]
    Entry { app: String, reason: String },
    #[error("{0} is not installed")]
    Missing(String),
    #[error(transparent)]
    Compositor(#[from] Error),
    #[error("the socket of the application could not be prepared: {0}")]
    Socket(#[from] std::io::Error),
    #[error("the session bus refused the request: {0}")]
    Bus(#[from] glib::Error),
    #[error("{0} did not appear on the session bus")]
    NoAnswer(&'static str),
}

/// What the field codes of an `Exec` line expand to. No file or URL is ever passed.
pub(crate) struct Fields<'a> {
    pub(crate) name: &'a str,
    pub(crate) icon: Option<&'a str>,
    pub(crate) location: Option<&'a str>,
}

/// The arguments of an `Exec` line, with its field codes expanded (Desktop Entry
/// Specification, "The Exec key"), quoted as GLib's own launcher parses it.
pub(crate) fn expand(exec: &str, fields: &Fields<'_>) -> Result<Vec<String>, String> {
    let words = glib::shell_parse_argv(exec).map_err(|err| err.to_string())?;
    let mut argv = Vec::new();
    for word in words {
        let word = word
            .into_string()
            .map_err(|_| "an argument is not UTF-8".to_owned())?;
        match word.as_str() {
            // Files and URLs: none. %d %D %n %N %v %m: deprecated, removed.
            "%f" | "%F" | "%u" | "%U" | "%d" | "%D" | "%n" | "%N" | "%v" | "%m" => {}
            "%i" => {
                if let Some(icon) = fields.icon {
                    argv.extend(["--icon".to_owned(), icon.to_owned()]);
                }
            }
            _ => argv.push(expand_word(&word, fields)?),
        }
    }
    if argv.is_empty() {
        return Err("the Exec line names no program".to_owned());
    }
    Ok(argv)
}

fn expand_word(word: &str, fields: &Fields<'_>) -> Result<String, String> {
    let mut out = String::with_capacity(word.len());
    let mut chars = word.chars();
    while let Some(c) = chars.next() {
        if c != '%' {
            out.push(c);
            continue;
        }
        match chars.next() {
            Some('%') => out.push('%'),
            Some('c') => out.push_str(fields.name),
            Some('k') => out.push_str(fields.location.unwrap_or_default()),
            Some('f' | 'F' | 'u' | 'U' | 'd' | 'D' | 'n' | 'N' | 'v' | 'm') => {}
            Some(code) => return Err(format!("the field code %{code} is not valid here")),
            None => return Err("the Exec line ends with a lone %".to_owned()),
        }
    }
    Ok(out)
}

/// An absolute path for `program`, searched in the shell's `PATH`.
fn resolve(program: &str) -> Result<String, LaunchError> {
    glib::find_program_in_path(program)
        .and_then(|path| path.into_os_string().into_string().ok())
        .ok_or_else(|| LaunchError::Missing(program.to_owned()))
}

impl Client {
    /// Starts `app` in a transient service of the user manager, on a socket of its own
    /// behind a security context, and returns the unit's name. When the context cannot be
    /// created the application does not start (BR2.6).
    pub async fn launch(&self, app: &gio_unix::DesktopAppInfo) -> Result<String, LaunchError> {
        let entry = |reason: &str| LaunchError::Entry {
            app: app.name().to_string(),
            reason: reason.to_owned(),
        };
        let id = app.id().ok_or_else(|| entry("it has no desktop id"))?;
        // DBusActivatable is ignored on purpose: bus activation would start the
        // application with the user manager's environment, on the main socket (BR2.5).
        let exec = app
            .string("Exec")
            .ok_or_else(|| entry("it has no Exec line"))?;
        let icon = app.string("Icon");
        let location = app
            .filename()
            .and_then(|path| path.into_os_string().into_string().ok());
        let name = app.name();
        let fields = Fields {
            name: &name,
            icon: icon.as_deref(),
            location: location.as_deref(),
        };
        let mut argv = expand(&exec, &fields).map_err(|reason| entry(&reason))?;
        if app.boolean("Terminal") {
            argv.insert(0, TERMINAL.to_owned());
        }
        argv[0] = resolve(&argv[0])?;

        let random = unit::random();
        let unit_name =
            unit::app_unit_name(&id, &random).ok_or_else(|| entry("its desktop id is too long"))?;
        let runtime_directory = format!("athanor/{random}");
        let dir = glib::user_runtime_dir().join(&runtime_directory);
        DirBuilder::new().recursive(true).mode(0o700).create(&dir)?;
        let result = self
            .start_in_context(app, &id, argv, unit_name, runtime_directory, &dir)
            .await;
        if result.is_err() {
            if let Err(err) = fs::remove_dir_all(&dir) {
                tracing::warn!(dir = %dir.display(), "the socket directory was not removed: {err}");
            }
        }
        result
    }

    async fn start_in_context(
        &self,
        app: &gio_unix::DesktopAppInfo,
        id: &str,
        argv: Vec<String>,
        unit_name: String,
        runtime_directory: String,
        dir: &std::path::Path,
    ) -> Result<String, LaunchError> {
        let socket = dir.join("wayland");
        let listener = UnixListener::bind(&socket)?;
        let (close_read, close_write) = std::io::pipe()?;
        // The compositor keeps its own copies; ours close when this function returns. The
        // context lasts until every copy of the write end is closed: the user manager
        // holds one for as long as the unit runs.
        self.create_context(listener.as_fd(), close_read.as_fd(), id, &unit_name)?;

        let mut environment = vec![format!("WAYLAND_DISPLAY={}", socket.display())];
        if let Some(token) = self.activation_token(Some(app.upcast_ref())) {
            environment.push(format!("XDG_ACTIVATION_TOKEN={token}"));
            environment.push(format!("DESKTOP_STARTUP_ID={token}"));
        }
        let working_directory = app
            .string("Path")
            .filter(|path| path.starts_with('/'))
            .map_or_else(|| "~".to_owned(), |path| path.to_string());
        let unit = Unit {
            name: unit_name,
            description: app.name().to_string(),
            argv,
            environment,
            working_directory,
            runtime_directory: Some(runtime_directory),
        };
        unit.start(Some(close_write.into())).await?;
        Ok(unit.name)
    }
}

/// The COSMIC components the shell opens until its own replace them (doc_bar.md, BR3).
/// They are part of the shell and keep the main socket.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Opener {
    Launcher,
    AppLibrary,
    Workspaces,
}

impl Opener {
    /// The well-known name of libcosmic's single instance: the app id.
    fn app_id(self) -> &'static str {
        match self {
            Opener::Launcher => "com.system76.CosmicLauncher",
            Opener::AppLibrary => "com.system76.CosmicAppLibrary",
            Opener::Workspaces => "com.system76.CosmicWorkspaces",
        }
    }

    fn program(self) -> &'static str {
        match self {
            Opener::Launcher => "cosmic-launcher",
            Opener::AppLibrary => "cosmic-app-library",
            Opener::Workspaces => "cosmic-workspaces",
        }
    }

    /// The object libcosmic exports its activation interface on.
    fn path(self) -> String {
        format!("/{}", self.app_id().replace('.', "/"))
    }
}

/// How long a component has to take its name after it was started.
const APPEAR: Duration = Duration::from_secs(5);
const POLL: Duration = Duration::from_millis(50);

impl Client {
    /// Shows the component, starting it first when it does not run. A component started
    /// cold only takes its name, so it is always shown through the bus (spike P4).
    pub async fn open(&self, opener: Opener) -> Result<(), LaunchError> {
        let bus = gio::bus_get_future(gio::BusType::Session).await?;
        let name = opener.app_id();
        if !has_owner(&bus, name).await? {
            self.start_component(opener).await?;
            let mut waited = Duration::ZERO;
            while !has_owner(&bus, name).await? {
                if waited >= APPEAR {
                    return Err(LaunchError::NoAnswer(name));
                }
                glib::timeout_future(POLL).await;
                waited += POLL;
            }
        }
        let mut platform_data = std::collections::HashMap::<&str, Variant>::new();
        if let Some(token) = self.activation_token(None) {
            platform_data.insert("activation-token", token.to_variant());
            platform_data.insert("desktop-startup-id", token.to_variant());
        }
        bus.call_future(
            Some(name),
            &opener.path(),
            "org.freedesktop.DbusActivation",
            "Activate",
            Some(&(platform_data,).to_variant()),
            None,
            gio::DBusCallFlags::NONE,
            -1,
        )
        .await?;
        Ok(())
    }

    async fn start_component(&self, opener: Opener) -> Result<(), LaunchError> {
        let mut environment = Vec::new();
        if let Some(display) = std::env::var_os("WAYLAND_DISPLAY") {
            environment.push(format!("WAYLAND_DISPLAY={}", display.to_string_lossy()));
        }
        let random = unit::random();
        let unit = Unit {
            name: unit::app_unit_name(opener.app_id(), &random).ok_or_else(|| {
                LaunchError::Entry {
                    app: opener.program().to_owned(),
                    reason: "its desktop id is too long".to_owned(),
                }
            })?,
            description: opener.program().to_owned(),
            argv: vec![resolve(opener.program())?],
            environment,
            working_directory: "~".to_owned(),
            runtime_directory: None,
        };
        unit.start(None).await?;
        Ok(())
    }
}

async fn has_owner(bus: &gio::DBusConnection, name: &str) -> Result<bool, glib::Error> {
    let reply = bus
        .call_future(
            Some("org.freedesktop.DBus"),
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            Some(&(name,).to_variant()),
            None,
            gio::DBusCallFlags::NONE,
            -1,
        )
        .await?;
    Ok(reply.get::<(bool,)>().is_some_and(|(owned,)| owned))
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIELDS: Fields<'static> = Fields {
        name: "Text Editor",
        icon: Some("org.gnome.TextEditor"),
        location: Some("/usr/share/applications/org.gnome.TextEditor.desktop"),
    };

    fn run(exec: &str) -> Result<Vec<String>, String> {
        expand(exec, &FIELDS)
    }

    #[test]
    fn file_and_url_codes_disappear_and_the_rest_expand() {
        assert_eq!(run("gnome-text-editor %U").unwrap(), ["gnome-text-editor"]);
        assert_eq!(
            run("app %i --title=%c %k 100%% %f").unwrap(),
            [
                "app",
                "--icon",
                "org.gnome.TextEditor",
                "--title=Text Editor",
                "/usr/share/applications/org.gnome.TextEditor.desktop",
                "100%"
            ]
        );
        let no_icon = Fields {
            icon: None,
            ..FIELDS
        };
        assert_eq!(expand("app %i", &no_icon).unwrap(), ["app"]);
    }

    #[test]
    fn quoting_follows_the_specification() {
        assert_eq!(
            run(r#""/opt/My App/bin/app" --arg "a \"b\" c" --x=%u"#).unwrap(),
            ["/opt/My App/bin/app", "--arg", "a \"b\" c", "--x="]
        );
    }

    #[test]
    fn malformed_lines_are_refused() {
        for exec in [
            "",
            "   ",
            "%f",
            "app %z",
            "app 50%",
            "app \"unterminated",
            "app --icon=%i",
        ] {
            assert!(run(exec).is_err(), "{exec:?} was accepted");
        }
    }

    #[test]
    fn openers_address_libcosmic_single_instances() {
        assert_eq!(Opener::Launcher.path(), "/com/system76/CosmicLauncher");
        assert_eq!(Opener::AppLibrary.app_id(), "com.system76.CosmicAppLibrary");
        assert_eq!(Opener::Workspaces.program(), "cosmic-workspaces");
    }
}

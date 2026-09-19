//! athanor-greeter-ui: the Athanor greeter, a program of its own (doc_shell.md, SH4).
//!
//! greetd starts cosmic-comp, cosmic-comp starts athanor-greeter-client, and that wrapper
//! execs this binary inside a bubblewrap sandbox. It takes no arguments.

mod auth;
mod power;
mod sandbox;
mod ui;

use gtk4::prelude::*;
use gtk4::Application;

const APP_ID: &str = "os.athanor.Greeter";

fn main() -> glib::ExitCode {
    // Confinement comes first, while this is the only thread in the process. Landlock
    // restricts the calling thread and the threads it creates from then on; a thread
    // that already exists -- a Tokio worker, a GLib worker -- would keep running
    // unconfined. Nothing before this line may start a thread, and the check fails
    // closed if something did. Logging is not set up yet, so errors go to stderr.
    if let Err(err) =
        sandbox::ensure_single_threaded().and_then(|()| sandbox::apply_landlock_sandbox())
    {
        eprintln!("athanor-greeter-ui: cannot apply the Landlock policy, refusing to run unconfined: {err}");
        return glib::ExitCode::FAILURE;
    }

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    // The workspace builds zbus on Tokio, and the greetd conversation sleeps on a Tokio
    // timer: both need a runtime that is current on this thread, or they abort with
    // "there is no reactor running" (acceptance run 34384585109). One worker is enough
    // for three logind calls.
    let runtime = match tokio::runtime::Builder::new_multi_thread()
        .worker_threads(1)
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(err) => {
            tracing::error!(error = %err, "cannot create the Tokio runtime");
            return glib::ExitCode::FAILURE;
        }
    };
    let _tokio = runtime.enter();

    let app = Application::builder().application_id(APP_ID).build();
    app.connect_activate(ui::build_ui);
    app.run_with_args(&Vec::<String>::new())
}

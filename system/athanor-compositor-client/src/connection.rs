//! The connection: GTK's own `wl_display` (doc_shell.md, P4), a private event queue on it,
//! and the protocol events turned into our own types.
//!
//! The queue is read from the GLib main loop through a watch on the display's file
//! descriptor. GDK reads the same socket in the `check` phase of its own source, before any
//! source is dispatched, so what it reads for our queue is dispatched in the same iteration.

use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::fs::File;
use std::io::ErrorKind;
use std::ops::RangeInclusive;
use std::os::fd::{AsRawFd, OwnedFd};
use std::os::unix::fs::FileExt;
use std::rc::Rc;
use std::sync::atomic::{AtomicU64, Ordering};

use gdk4_wayland::prelude::*;
use gtk4::{gdk, glib};
use wayland_client::backend::{ObjectId, WaylandError};
use wayland_client::globals::{registry_queue_init, GlobalList, GlobalListContents};
use wayland_client::protocol::{wl_keyboard, wl_output, wl_registry, wl_seat};
use wayland_client::{
    event_created_child, Connection, Dispatch, EventQueue, Proxy, QueueHandle, WEnum,
};
use wayland_protocols::ext::foreign_toplevel_list::v1::client::{
    ext_foreign_toplevel_handle_v1::{self, ExtForeignToplevelHandleV1},
    ext_foreign_toplevel_list_v1::{self, ExtForeignToplevelListV1},
};
use wayland_protocols::ext::workspace::v1::client::{
    ext_workspace_group_handle_v1::{self, ExtWorkspaceGroupHandleV1},
    ext_workspace_handle_v1::{self, ExtWorkspaceHandleV1},
    ext_workspace_manager_v1::{self, ExtWorkspaceManagerV1},
};

use crate::keymap::{self, MAX_KEYMAP};
use crate::model::{
    Accessibility, Change, Event, ScreenFilter, Table, Tiling, Window, WindowId, WindowState,
    Workspace, WorkspaceId,
};
use crate::protocols::a11y::client::cosmic_a11y_manager_v1::{
    self, ActiveState, CosmicA11yManagerV1, Filter,
};
use crate::protocols::keyboard_layout::client::{
    zcosmic_keyboard_layout_manager_v1::ZcosmicKeyboardLayoutManagerV1,
    zcosmic_keyboard_layout_v1::{self, ZcosmicKeyboardLayoutV1},
};
use crate::protocols::toplevel_info::client::{
    zcosmic_toplevel_handle_v1::{self, ZcosmicToplevelHandleV1},
    zcosmic_toplevel_info_v1::{self, ZcosmicToplevelInfoV1},
};
use crate::protocols::toplevel_management::client::zcosmic_toplevel_manager_v1::ZcosmicToplevelManagerV1;
use crate::protocols::workspace_v2::client::{
    zcosmic_workspace_handle_v2::{self, TilingState, ZcosmicWorkspaceHandleV2},
    zcosmic_workspace_manager_v2::ZcosmicWorkspaceManagerV2,
};

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("the display is not a Wayland display")]
    NotWayland,
    #[error("the Wayland connection failed: {0}")]
    Connection(String),
    #[error("the compositor does not offer {0}")]
    Unavailable(&'static str),
    #[error("no such window")]
    NoWindow,
    #[error("no such workspace")]
    NoWorkspace,
    #[error("invalid argument: {0}")]
    InvalidArgument(&'static str),
}

/// Ids are handed out in creation order across every client of the process, so an id is
/// never reused. The protocol's object ids are, which is why they are not ours.
fn fresh() -> u64 {
    static NEXT: AtomicU64 = AtomicU64::new(1);
    NEXT.fetch_add(1, Ordering::Relaxed)
}

/// The shell's view of the compositor. Every call happens on the GTK main thread.
pub struct Client {
    inner: Rc<Inner>,
}

type Handler = Box<dyn FnMut(&Client, &Event)>;

struct Inner {
    connection: Connection,
    queue: RefCell<EventQueue<State>>,
    state: RefCell<State>,
    handler: RefCell<Option<Handler>>,
    delivering: Cell<bool>,
    source: RefCell<Option<glib::SourceId>>,
}

impl Drop for Inner {
    fn drop(&mut self) {
        if let Some(source) = self.source.take() {
            source.remove();
        }
    }
}

impl Client {
    /// Binds what the compositor offers and reads the initial state. A global the
    /// compositor does not offer is not an error: its part of the API stays empty, and its
    /// actions return [`Error::Unavailable`].
    pub fn connect(display: &gdk::Display) -> Result<Client, Error> {
        let wayland = display
            .downcast_ref::<gdk4_wayland::WaylandDisplay>()
            .ok_or(Error::NotWayland)?;
        let wl_display = wayland.wl_display().ok_or(Error::NotWayland)?;
        let backend = wl_display
            .backend()
            .upgrade()
            .ok_or_else(|| Error::Connection("the display has no live backend".into()))?;
        let connection = Connection::from_backend(backend);
        let (globals, mut queue) = registry_queue_init::<State>(&connection)
            .map_err(|err| Error::Connection(err.to_string()))?;
        let qh = queue.handle();
        let mut state = State::bind(&globals, &qh);
        // The first roundtrip announces the objects, the second their initial state.
        for _ in 0..2 {
            queue
                .roundtrip(&mut state)
                .map_err(|err| Error::Connection(err.to_string()))?;
        }
        state.events.clear();

        let inner = Rc::new(Inner {
            connection,
            queue: RefCell::new(queue),
            state: RefCell::new(state),
            handler: RefCell::new(None),
            delivering: Cell::new(false),
            source: RefCell::new(None),
        });
        let fd = inner.connection.backend().poll_fd().as_raw_fd();
        let weak = Rc::downgrade(&inner);
        let source = glib_unix::unix_fd_add_local(fd, glib::IOCondition::IN, move |_, _| {
            let Some(inner) = weak.upgrade() else {
                return glib::ControlFlow::Break;
            };
            if let Err(err) = inner.pump() {
                tracing::error!("reading from the compositor failed, no further events: {err}");
                // glib removes the source on Break; forget its id so Drop does not.
                inner.source.take();
                return glib::ControlFlow::Break;
            }
            glib::ControlFlow::Continue
        });
        inner.source.replace(Some(source));
        Ok(Client { inner })
    }

    /// The handler receives every change after the compositor finished describing it. It
    /// may call any method of the client, actions included. Connecting again replaces it.
    pub fn connect_events(&self, handler: impl FnMut(&Client, &Event) + 'static) {
        self.inner.handler.replace(Some(Box::new(handler)));
    }

    pub fn windows(&self) -> Vec<Window> {
        self.inner
            .state
            .borrow()
            .windows
            .values()
            .cloned()
            .collect()
    }

    pub fn workspaces(&self) -> Vec<Workspace> {
        self.inner
            .state
            .borrow()
            .workspaces
            .values()
            .cloned()
            .collect()
    }

    /// The configured layouts in group order; empty when the compositor sends no XKB keymap.
    pub fn keyboard_layouts(&self) -> Vec<String> {
        self.inner.state.borrow().keyboard_layouts.clone()
    }

    pub fn keyboard_group(&self) -> u32 {
        self.inner.state.borrow().keyboard_group
    }

    /// `None` when the compositor offers no accessibility protocol.
    pub fn accessibility(&self) -> Option<Accessibility> {
        let state = self.inner.state.borrow();
        state.globals.a11y.as_ref().map(|_| state.accessibility)
    }

    pub fn activate(&self, window: WindowId) -> Result<(), Error> {
        let state = self.inner.state.borrow();
        let manager = state.toplevel_manager()?;
        let seat = state
            .globals
            .seat
            .as_ref()
            .ok_or(Error::Unavailable("wl_seat"))?;
        manager.activate(state.cosmic_toplevel(window)?, seat);
        drop(state);
        self.flush()
    }

    pub fn minimize(&self, window: WindowId) -> Result<(), Error> {
        self.toplevel_request(window, ZcosmicToplevelManagerV1::set_minimized)
    }

    pub fn unminimize(&self, window: WindowId) -> Result<(), Error> {
        self.toplevel_request(window, ZcosmicToplevelManagerV1::unset_minimized)
    }

    pub fn close(&self, window: WindowId) -> Result<(), Error> {
        self.toplevel_request(window, ZcosmicToplevelManagerV1::close)
    }

    pub fn set_tiling(&self, workspace: WorkspaceId, tiling: Tiling) -> Result<(), Error> {
        let state = self.inner.state.borrow();
        let manager = state
            .globals
            .workspace_manager
            .as_ref()
            .ok_or(Error::Unavailable("ext_workspace_manager_v1"))?;
        let handles = state
            .workspace_handles
            .get(&workspace)
            .ok_or(Error::NoWorkspace)?;
        let cosmic = handles
            .cosmic
            .as_ref()
            .ok_or(Error::Unavailable("zcosmic_workspace_manager_v2"))?;
        cosmic.set_tiling_state(match tiling {
            Tiling::Floating => TilingState::FloatingOnly,
            Tiling::Tiled => TilingState::TilingEnabled,
        });
        manager.commit();
        drop(state);
        self.flush()
    }

    /// The compositor ignores a group beyond the configured layouts.
    pub fn set_keyboard_group(&self, group: u32) -> Result<(), Error> {
        let state = self.inner.state.borrow();
        state
            .keyboard_layout
            .as_ref()
            .ok_or(Error::Unavailable("zcosmic_keyboard_layout_manager_v1"))?
            .set_group(group);
        drop(state);
        self.flush()
    }

    pub fn set_magnifier(&self, enabled: bool) -> Result<(), Error> {
        let state = self.inner.state.borrow();
        state.a11y()?.set_magnifier(active_state(enabled));
        drop(state);
        self.flush()
    }

    pub fn set_screen_filter(&self, inverted: bool, filter: ScreenFilter) -> Result<(), Error> {
        let filter = match filter {
            ScreenFilter::None => Filter::Disabled,
            ScreenFilter::Greyscale => Filter::Greyscale,
            ScreenFilter::Protanopia => Filter::DaltonizeProtanopia,
            ScreenFilter::Deuteranopia => Filter::DaltonizeDeuteranopia,
            ScreenFilter::Tritanopia => Filter::DaltonizeTritanopia,
            ScreenFilter::Unknown => {
                return Err(Error::InvalidArgument(
                    "an unknown screen filter cannot be set",
                ))
            }
        };
        let state = self.inner.state.borrow();
        state
            .a11y()?
            .set_screen_filter(active_state(inverted), filter);
        drop(state);
        self.flush()
    }

    fn toplevel_request(
        &self,
        window: WindowId,
        request: impl FnOnce(&ZcosmicToplevelManagerV1, &ZcosmicToplevelHandleV1),
    ) -> Result<(), Error> {
        let state = self.inner.state.borrow();
        request(state.toplevel_manager()?, state.cosmic_toplevel(window)?);
        drop(state);
        self.flush()
    }

    fn flush(&self) -> Result<(), Error> {
        self.inner
            .connection
            .flush()
            .map_err(|err| Error::Connection(err.to_string()))
    }
}

impl Inner {
    fn pump(self: &Rc<Self>) -> Result<(), Error> {
        {
            let mut queue = self.queue.borrow_mut();
            let mut state = self.state.borrow_mut();
            let failed = |err: &dyn std::fmt::Display| Error::Connection(err.to_string());
            queue
                .dispatch_pending(&mut state)
                .map_err(|err| failed(&err))?;
            if let Some(guard) = queue.prepare_read() {
                match guard.read() {
                    Ok(_) => {}
                    Err(WaylandError::Io(err)) if err.kind() == ErrorKind::WouldBlock => {}
                    Err(err) => return Err(failed(&err)),
                }
            }
            queue
                .dispatch_pending(&mut state)
                .map_err(|err| failed(&err))?;
            self.connection.flush().map_err(|err| failed(&err))?;
        }
        self.deliver();
        Ok(())
    }

    /// Hands the collected events to the handler with no borrow held, so the handler may
    /// call back into the client. Events a nested call collects are delivered by the
    /// outermost call, in order.
    fn deliver(self: &Rc<Self>) {
        if self.delivering.get() {
            return;
        }
        let Some(mut handler) = self.handler.take() else {
            self.state.borrow_mut().events.clear();
            return;
        };
        self.delivering.set(true);
        let client = Client {
            inner: Rc::clone(self),
        };
        loop {
            let events = std::mem::take(&mut self.state.borrow_mut().events);
            if events.is_empty() {
                break;
            }
            for event in &events {
                handler(&client, event);
            }
        }
        self.delivering.set(false);
        // A handler that connected a new handler keeps the new one.
        let mut slot = self.handler.borrow_mut();
        if slot.is_none() {
            *slot = Some(handler);
        }
    }
}

fn active_state(enabled: bool) -> ActiveState {
    if enabled {
        ActiveState::Enabled
    } else {
        ActiveState::Disabled
    }
}

#[derive(Default)]
struct Globals {
    toplevel_info: Option<ZcosmicToplevelInfoV1>,
    toplevel_manager: Option<ZcosmicToplevelManagerV1>,
    workspace_manager: Option<ExtWorkspaceManagerV1>,
    cosmic_workspaces: Option<ZcosmicWorkspaceManagerV2>,
    seat: Option<wl_seat::WlSeat>,
    keyboard_layouts: Option<ZcosmicKeyboardLayoutManagerV1>,
    a11y: Option<CosmicA11yManagerV1>,
}

struct Toplevel {
    ext: ExtForeignToplevelHandleV1,
    cosmic: Option<ZcosmicToplevelHandleV1>,
}

struct WorkspaceHandles {
    ext: ExtWorkspaceHandleV1,
    cosmic: Option<ZcosmicWorkspaceHandleV2>,
}

#[derive(Default)]
pub(crate) struct State {
    globals: Globals,
    windows: Table<WindowId, Window>,
    toplevels: HashMap<WindowId, Toplevel>,
    workspaces: Table<WorkspaceId, Workspace>,
    workspace_handles: HashMap<WorkspaceId, WorkspaceHandles>,
    /// Each group's outputs, in the order they entered, GDK's objects included.
    groups: HashMap<ObjectId, Vec<ObjectId>>,
    group_of: HashMap<WorkspaceId, ObjectId>,
    /// Output globals by registry name, and their connector names.
    outputs: HashMap<u32, wl_output::WlOutput>,
    output_names: HashMap<ObjectId, String>,
    keyboard: Option<wl_keyboard::WlKeyboard>,
    keyboard_layout: Option<ZcosmicKeyboardLayoutV1>,
    keyboard_layouts: Vec<String>,
    keyboard_group: u32,
    accessibility: Accessibility,
    events: Vec<Event>,
}

fn bind<I>(
    globals: &GlobalList,
    qh: &QueueHandle<State>,
    versions: RangeInclusive<u32>,
) -> Option<I>
where
    I: Proxy + 'static,
    State: Dispatch<I, ()>,
{
    match globals.bind(qh, versions, ()) {
        Ok(proxy) => Some(proxy),
        Err(err) => {
            tracing::info!(interface = I::interface().name, "not bound: {err}");
            None
        }
    }
}

impl State {
    fn bind(globals: &GlobalList, qh: &QueueHandle<State>) -> State {
        let mut state = State::default();
        // Outputs first: the workspace manager announces a group's outputs only through
        // the `wl_output` objects the client holds when it binds the manager.
        for global in globals.contents().clone_list() {
            if global.interface == wl_output::WlOutput::interface().name {
                state.bind_output(globals.registry(), qh, global.name, global.version);
            }
        }
        state.globals = Globals {
            toplevel_info: bind(globals, qh, 2..=3),
            toplevel_manager: bind(globals, qh, 1..=4),
            cosmic_workspaces: bind(globals, qh, 2..=2),
            keyboard_layouts: bind(globals, qh, 1..=1),
            // Version 3 deprecates the screen filter events of version 2.
            a11y: bind(globals, qh, 2..=2),
            seat: bind(globals, qh, 1..=7),
            workspace_manager: bind(globals, qh, 1..=1),
        };
        // Only its events are needed; the proxy stays alive without a handle.
        bind::<ExtForeignToplevelListV1>(globals, qh, 1..=1);
        state
    }

    fn bind_output(
        &mut self,
        registry: &wl_registry::WlRegistry,
        qh: &QueueHandle<State>,
        name: u32,
        version: u32,
    ) {
        let output = registry.bind::<wl_output::WlOutput, _, _>(name, version.min(4), qh, ());
        self.outputs.insert(name, output);
    }

    fn toplevel_manager(&self) -> Result<&ZcosmicToplevelManagerV1, Error> {
        self.globals
            .toplevel_manager
            .as_ref()
            .ok_or(Error::Unavailable("zcosmic_toplevel_manager_v1"))
    }

    fn cosmic_toplevel(&self, window: WindowId) -> Result<&ZcosmicToplevelHandleV1, Error> {
        self.toplevels
            .get(&window)
            .ok_or(Error::NoWindow)?
            .cosmic
            .as_ref()
            .ok_or(Error::Unavailable("zcosmic_toplevel_info_v1"))
    }

    fn a11y(&self) -> Result<&CosmicA11yManagerV1, Error> {
        self.globals
            .a11y
            .as_ref()
            .ok_or(Error::Unavailable("cosmic_a11y_manager_v1"))
    }

    fn push_window(&mut self, change: Change<Window>) {
        self.events.push(match change {
            Change::Added(window) => Event::WindowAdded(window),
            Change::Changed(window) => Event::WindowChanged(window),
        });
    }

    fn commit_workspaces(&mut self) {
        for workspace in self.workspaces.pending_values() {
            workspace.output = self
                .group_of
                .get(&workspace.id)
                .and_then(|group| self.groups.get(group))
                // The group enters every `wl_output` of this connection, GDK's too; only
                // ours carry a name this client has read.
                .and_then(|outputs| {
                    outputs
                        .iter()
                        .find_map(|output| self.output_names.get(output))
                })
                .cloned();
        }
        for change in self.workspaces.commit_all() {
            self.events.push(match change {
                Change::Added(workspace) => Event::WorkspaceAdded(workspace),
                Change::Changed(workspace) => Event::WorkspaceChanged(workspace),
            });
        }
    }

    fn set_accessibility(&mut self, next: Accessibility) {
        if next != self.accessibility {
            self.accessibility = next;
            self.events.push(Event::Accessibility(next));
        }
    }
}

impl Dispatch<wl_registry::WlRegistry, GlobalListContents> for State {
    fn event(
        state: &mut Self,
        registry: &wl_registry::WlRegistry,
        event: wl_registry::Event,
        _: &GlobalListContents,
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        match event {
            wl_registry::Event::Global {
                name,
                interface,
                version,
            } if interface == wl_output::WlOutput::interface().name => {
                state.bind_output(registry, qh, name, version);
            }
            wl_registry::Event::GlobalRemove { name } => {
                if let Some(output) = state.outputs.remove(&name) {
                    state.output_names.remove(&output.id());
                    if output.version() >= 3 {
                        output.release();
                    }
                }
            }
            _ => {}
        }
    }
}

impl Dispatch<wl_output::WlOutput, ()> for State {
    fn event(
        state: &mut Self,
        output: &wl_output::WlOutput,
        event: wl_output::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let wl_output::Event::Name { name } = event {
            state.output_names.insert(output.id(), name);
        }
    }
}

impl Dispatch<wl_seat::WlSeat, ()> for State {
    fn event(
        state: &mut Self,
        seat: &wl_seat::WlSeat,
        event: wl_seat::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        let wl_seat::Event::Capabilities {
            capabilities: WEnum::Value(capabilities),
        } = event
        else {
            return;
        };
        if capabilities.contains(wl_seat::Capability::Keyboard) && state.keyboard.is_none() {
            let keyboard = seat.get_keyboard(qh, ());
            if let Some(manager) = &state.globals.keyboard_layouts {
                state.keyboard_layout = Some(manager.get_keyboard_layout(&keyboard, qh, ()));
            }
            state.keyboard = Some(keyboard);
        }
    }
}

fn read_keymap(fd: OwnedFd, size: u32) -> std::io::Result<String> {
    if size > MAX_KEYMAP {
        return Err(std::io::Error::new(
            ErrorKind::InvalidData,
            format!("a keymap of {size} bytes is beyond the limit of {MAX_KEYMAP}"),
        ));
    }
    let mut bytes = vec![0; size as usize];
    File::from(fd).read_exact_at(&mut bytes, 0)?;
    let text = bytes.split(|byte| *byte == 0).next().unwrap_or_default();
    Ok(String::from_utf8_lossy(text).into_owned())
}

impl Dispatch<wl_keyboard::WlKeyboard, ()> for State {
    fn event(
        state: &mut Self,
        _: &wl_keyboard::WlKeyboard,
        event: wl_keyboard::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        let wl_keyboard::Event::Keymap { format, fd, size } = event else {
            return;
        };
        if format != WEnum::Value(wl_keyboard::KeymapFormat::XkbV1) {
            return;
        }
        match read_keymap(fd, size) {
            Ok(text) => {
                let layouts = keymap::layout_names(&text);
                if layouts != state.keyboard_layouts {
                    state.keyboard_layouts = layouts.clone();
                    state.events.push(Event::KeyboardLayouts(layouts));
                }
            }
            Err(err) => tracing::warn!("the keymap could not be read: {err}"),
        }
    }
}

impl Dispatch<ZcosmicKeyboardLayoutV1, ()> for State {
    fn event(
        state: &mut Self,
        _: &ZcosmicKeyboardLayoutV1,
        event: zcosmic_keyboard_layout_v1::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        let zcosmic_keyboard_layout_v1::Event::Group { group } = event;
        if group != state.keyboard_group {
            state.keyboard_group = group;
            state.events.push(Event::KeyboardGroup(group));
        }
    }
}

impl Dispatch<CosmicA11yManagerV1, ()> for State {
    fn event(
        state: &mut Self,
        _: &CosmicA11yManagerV1,
        event: cosmic_a11y_manager_v1::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        let enabled = |value: WEnum<ActiveState>| value == WEnum::Value(ActiveState::Enabled);
        let mut next = state.accessibility;
        match event {
            cosmic_a11y_manager_v1::Event::Magnifier { active } => next.magnifier = enabled(active),
            cosmic_a11y_manager_v1::Event::ScreenFilter { inverted, filter } => {
                next.inverted = enabled(inverted);
                next.filter = match filter {
                    WEnum::Value(Filter::Disabled) => ScreenFilter::None,
                    WEnum::Value(Filter::Greyscale) => ScreenFilter::Greyscale,
                    WEnum::Value(Filter::DaltonizeProtanopia) => ScreenFilter::Protanopia,
                    WEnum::Value(Filter::DaltonizeDeuteranopia) => ScreenFilter::Deuteranopia,
                    WEnum::Value(Filter::DaltonizeTritanopia) => ScreenFilter::Tritanopia,
                    WEnum::Value(Filter::Unknown) | WEnum::Unknown(_) => ScreenFilter::Unknown,
                };
            }
            // Version 3 only; this client binds version 2.
            cosmic_a11y_manager_v1::Event::ScreenFilter2 { .. } => {}
        }
        state.set_accessibility(next);
    }
}

impl Dispatch<ExtForeignToplevelListV1, ()> for State {
    fn event(
        state: &mut Self,
        _: &ExtForeignToplevelListV1,
        event: ext_foreign_toplevel_list_v1::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        let ext_foreign_toplevel_list_v1::Event::Toplevel { toplevel } = event else {
            return;
        };
        let Some(&id) = toplevel.data::<WindowId>() else {
            return;
        };
        let cosmic = state
            .globals
            .toplevel_info
            .as_ref()
            .map(|info| info.get_cosmic_toplevel(&toplevel, qh, id));
        state.windows.insert(
            id,
            Window {
                id,
                app_id: String::new(),
                title: String::new(),
                state: WindowState::default(),
            },
        );
        state.toplevels.insert(
            id,
            Toplevel {
                ext: toplevel,
                cosmic,
            },
        );
    }

    event_created_child!(State, ExtForeignToplevelListV1, [
        ext_foreign_toplevel_list_v1::EVT_TOPLEVEL_OPCODE => (ExtForeignToplevelHandleV1, WindowId(fresh()))
    ]);
}

impl Dispatch<ExtForeignToplevelHandleV1, WindowId> for State {
    fn event(
        state: &mut Self,
        _: &ExtForeignToplevelHandleV1,
        event: ext_foreign_toplevel_handle_v1::Event,
        id: &WindowId,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        match event {
            ext_foreign_toplevel_handle_v1::Event::Title { title } => {
                if let Some(window) = state.windows.pending(id) {
                    window.title = title;
                }
            }
            ext_foreign_toplevel_handle_v1::Event::AppId { app_id } => {
                if let Some(window) = state.windows.pending(id) {
                    window.app_id = app_id;
                }
            }
            ext_foreign_toplevel_handle_v1::Event::Done => {
                if let Some(change) = state.windows.commit(id) {
                    state.push_window(change);
                }
            }
            ext_foreign_toplevel_handle_v1::Event::Closed => {
                if let Some(toplevel) = state.toplevels.remove(id) {
                    if let Some(cosmic) = toplevel.cosmic {
                        cosmic.destroy();
                    }
                    toplevel.ext.destroy();
                }
                if state.windows.remove(id) {
                    state.events.push(Event::WindowRemoved(*id));
                }
            }
            _ => {}
        }
    }
}

impl Dispatch<ZcosmicToplevelInfoV1, ()> for State {
    fn event(
        state: &mut Self,
        _: &ZcosmicToplevelInfoV1,
        event: zcosmic_toplevel_info_v1::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let zcosmic_toplevel_info_v1::Event::Done = event {
            for change in state.windows.commit_all() {
                state.push_window(change);
            }
        }
    }

    // Version 1 announced toplevels itself; a client binding version 2 never receives it.
    event_created_child!(State, ZcosmicToplevelInfoV1, [
        zcosmic_toplevel_info_v1::EVT_TOPLEVEL_OPCODE => (ZcosmicToplevelHandleV1, WindowId(fresh()))
    ]);
}

impl Dispatch<ZcosmicToplevelHandleV1, WindowId> for State {
    fn event(
        state: &mut Self,
        _: &ZcosmicToplevelHandleV1,
        event: zcosmic_toplevel_handle_v1::Event,
        id: &WindowId,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let zcosmic_toplevel_handle_v1::Event::State { state: array } = event {
            if let Some(window) = state.windows.pending(id) {
                window.state = WindowState::from_cosmic(&array);
            }
        }
    }
}

impl Dispatch<ExtWorkspaceManagerV1, ()> for State {
    fn event(
        state: &mut Self,
        _: &ExtWorkspaceManagerV1,
        event: ext_workspace_manager_v1::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        match event {
            ext_workspace_manager_v1::Event::WorkspaceGroup { workspace_group } => {
                state.groups.insert(workspace_group.id(), Vec::new());
            }
            ext_workspace_manager_v1::Event::Workspace { workspace } => {
                let Some(&id) = workspace.data::<WorkspaceId>() else {
                    return;
                };
                let cosmic = state
                    .globals
                    .cosmic_workspaces
                    .as_ref()
                    .map(|manager| manager.get_cosmic_workspace(&workspace, qh, id));
                state.workspaces.insert(
                    id,
                    Workspace {
                        id,
                        name: String::new(),
                        active: false,
                        tiling: None,
                        output: None,
                    },
                );
                state.workspace_handles.insert(
                    id,
                    WorkspaceHandles {
                        ext: workspace,
                        cosmic,
                    },
                );
            }
            ext_workspace_manager_v1::Event::Done => state.commit_workspaces(),
            _ => {}
        }
    }

    event_created_child!(State, ExtWorkspaceManagerV1, [
        ext_workspace_manager_v1::EVT_WORKSPACE_GROUP_OPCODE => (ExtWorkspaceGroupHandleV1, ()),
        ext_workspace_manager_v1::EVT_WORKSPACE_OPCODE => (ExtWorkspaceHandleV1, WorkspaceId(fresh()))
    ]);
}

impl Dispatch<ExtWorkspaceGroupHandleV1, ()> for State {
    fn event(
        state: &mut Self,
        group: &ExtWorkspaceGroupHandleV1,
        event: ext_workspace_group_handle_v1::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        match event {
            ext_workspace_group_handle_v1::Event::OutputEnter { output } => {
                if let Some(outputs) = state.groups.get_mut(&group.id()) {
                    outputs.push(output.id());
                }
            }
            ext_workspace_group_handle_v1::Event::OutputLeave { output } => {
                if let Some(outputs) = state.groups.get_mut(&group.id()) {
                    outputs.retain(|entered| *entered != output.id());
                }
            }
            ext_workspace_group_handle_v1::Event::WorkspaceEnter { workspace } => {
                if let Some(&id) = workspace.data::<WorkspaceId>() {
                    state.group_of.insert(id, group.id());
                }
            }
            ext_workspace_group_handle_v1::Event::WorkspaceLeave { workspace } => {
                if let Some(id) = workspace.data::<WorkspaceId>() {
                    if state.group_of.get(id) == Some(&group.id()) {
                        state.group_of.remove(id);
                    }
                }
            }
            ext_workspace_group_handle_v1::Event::Removed => {
                state.groups.remove(&group.id());
                group.destroy();
            }
            _ => {}
        }
    }
}

impl Dispatch<ExtWorkspaceHandleV1, WorkspaceId> for State {
    fn event(
        state: &mut Self,
        _: &ExtWorkspaceHandleV1,
        event: ext_workspace_handle_v1::Event,
        id: &WorkspaceId,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        match event {
            ext_workspace_handle_v1::Event::Name { name } => {
                if let Some(workspace) = state.workspaces.pending(id) {
                    workspace.name = name;
                }
            }
            ext_workspace_handle_v1::Event::State { state: bits } => {
                if let Some(workspace) = state.workspaces.pending(id) {
                    workspace.active =
                        u32::from(bits) & ext_workspace_handle_v1::State::Active.bits() != 0;
                }
            }
            ext_workspace_handle_v1::Event::Removed => {
                if let Some(handles) = state.workspace_handles.remove(id) {
                    if let Some(cosmic) = handles.cosmic {
                        cosmic.destroy();
                    }
                    handles.ext.destroy();
                }
                state.group_of.remove(id);
                if state.workspaces.remove(id) {
                    state.events.push(Event::WorkspaceRemoved(*id));
                }
            }
            _ => {}
        }
    }
}

impl Dispatch<ZcosmicWorkspaceHandleV2, WorkspaceId> for State {
    fn event(
        state: &mut Self,
        _: &ZcosmicWorkspaceHandleV2,
        event: zcosmic_workspace_handle_v2::Event,
        id: &WorkspaceId,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let zcosmic_workspace_handle_v2::Event::TilingState { state: tiling } = event {
            if let Some(workspace) = state.workspaces.pending(id) {
                workspace.tiling = match tiling {
                    WEnum::Value(TilingState::FloatingOnly) => Some(Tiling::Floating),
                    WEnum::Value(TilingState::TilingEnabled) => Some(Tiling::Tiled),
                    WEnum::Unknown(_) => None,
                };
            }
        }
    }
}

/// Globals and objects whose events this client does not read.
macro_rules! ignore_events {
    ($($proxy:ty),* $(,)?) => {$(
        impl Dispatch<$proxy, ()> for State {
            fn event(
                _: &mut Self,
                _: &$proxy,
                _: <$proxy as Proxy>::Event,
                _: &(),
                _: &Connection,
                _: &QueueHandle<Self>,
            ) {
            }
        }
    )*};
}

ignore_events!(
    ZcosmicToplevelManagerV1,
    ZcosmicWorkspaceManagerV2,
    ZcosmicKeyboardLayoutManagerV1,
);

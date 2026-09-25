//! org.kde.StatusNotifierWatcher (doc_bar.md BR5). An item registers with a bus name, or with
//! an object path (the form of the Ayatana libraries); it leaves when the owner of its bus name
//! disappears. The host is the bar. XEmbed is out of scope.

use futures_util::StreamExt;
use zbus::fdo::{self, DBusProxy};
use zbus::message::Header;
use zbus::names::BusName;
use zbus::object_server::SignalEmitter;
use zbus::{interface, Connection};
use zvariant::ObjectPath;

use crate::server::WATCHER_PATH;

pub const MAX_ITEMS: usize = 64;
/// Only the bar is expected to host; the cap bounds a hostile client.
pub const MAX_HOSTS: usize = 4;

#[derive(Debug, Default)]
pub struct Registry {
    /// (item id as announced, the bus name whose owner keeps it registered)
    items: Vec<(String, String)>,
    hosts: Vec<String>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Added {
    New,
    Known,
    Full,
}

#[derive(Debug, Default, PartialEq, Eq)]
pub struct Lost {
    pub items: Vec<String>,
    pub last_host_gone: bool,
}

impl Registry {
    pub fn add_item(&mut self, id: String, name: String) -> Added {
        if self.items.iter().any(|(known, _)| *known == id) {
            return Added::Known;
        }
        if self.items.len() >= MAX_ITEMS {
            return Added::Full;
        }
        self.items.push((id, name));
        Added::New
    }

    /// Registers a host, up to `MAX_HOSTS`; a known one succeeds without growing the list.
    pub fn add_host(&mut self, name: String) -> Added {
        if self.hosts.contains(&name) {
            return Added::Known;
        }
        if self.hosts.len() >= MAX_HOSTS {
            return Added::Full;
        }
        self.hosts.push(name);
        Added::New
    }

    #[must_use]
    pub fn items(&self) -> Vec<String> {
        self.items.iter().map(|(id, _)| id.clone()).collect()
    }

    #[must_use]
    pub fn has_host(&self) -> bool {
        !self.hosts.is_empty()
    }

    /// Everything `name` held: the items it kept alive, and whether the last host left with it.
    pub fn name_lost(&mut self, name: &str) -> Lost {
        let mut items = Vec::new();
        self.items.retain(|(id, owner)| {
            let gone = owner == name;
            if gone {
                items.push(id.clone());
            }
            !gone
        });
        let had_host = self.has_host();
        self.hosts.retain(|host| host != name);
        Lost {
            items,
            last_host_gone: had_host && !self.has_host(),
        }
    }
}

/// The item `service` names, and the bus name whose owner keeps it alive.
#[must_use]
pub fn item(service: &str, sender: &str) -> Option<(String, String)> {
    if service.starts_with('/') {
        ObjectPath::try_from(service).ok()?;
        Some((format!("{sender}{service}"), sender.to_owned()))
    } else {
        BusName::try_from(service).ok()?;
        Some((format!("{service}/StatusNotifierItem"), service.to_owned()))
    }
}

#[derive(Default)]
pub struct Watcher {
    registry: Registry,
}

/// Refuses a caller that names a bus name it does not own: a well-known name it does not
/// currently hold, or another connection's unique name. A unique name is trusted only against
/// the sender itself, since a connection cannot claim one that is not its own; a well-known
/// name is resolved through the bus. Without this, any client could attribute an item or a
/// host to a long-lived name it does not own and hold a slot forever, since that name's real
/// owner never leaves.
async fn owned_by(conn: &Connection, service: &str, sender: &str) -> fdo::Result<()> {
    let name =
        BusName::try_from(service).map_err(|err| fdo::Error::InvalidArgs(err.to_string()))?;
    let owner = if service.starts_with(':') {
        service.to_owned()
    } else {
        DBusProxy::new(conn)
            .await?
            .get_name_owner(name)
            .await
            .map_err(|err| fdo::Error::AccessDenied(format!("{service} has no owner: {err}")))?
            .to_string()
    };
    if owner == sender {
        Ok(())
    } else {
        Err(fdo::Error::AccessDenied(format!(
            "{service} is not owned by its caller"
        )))
    }
}

#[interface(name = "org.kde.StatusNotifierWatcher")]
impl Watcher {
    async fn register_status_notifier_item(
        &mut self,
        service: &str,
        #[zbus(header)] header: Header<'_>,
        #[zbus(connection)] conn: &Connection,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
    ) -> fdo::Result<()> {
        let sender = header
            .sender()
            .ok_or_else(|| fdo::Error::InvalidArgs("a call with no sender".into()))?;
        let (id, name) = item(service, sender.as_str()).ok_or_else(|| {
            fdo::Error::InvalidArgs(format!(
                "{service:?} is neither a bus name nor an object path"
            ))
        })?;
        if !service.starts_with('/') {
            owned_by(conn, service, sender.as_str()).await?;
        }
        match self.registry.add_item(id.clone(), name) {
            Added::New => {
                Self::status_notifier_item_registered(&emitter, &id).await?;
                self.registered_status_notifier_items_changed(&emitter)
                    .await?;
                Ok(())
            }
            Added::Known => Ok(()),
            Added::Full => Err(fdo::Error::LimitsExceeded(format!(
                "{MAX_ITEMS} items are registered"
            ))),
        }
    }

    async fn register_status_notifier_host(
        &mut self,
        service: &str,
        #[zbus(header)] header: Header<'_>,
        #[zbus(connection)] conn: &Connection,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
    ) -> fdo::Result<()> {
        let sender = header
            .sender()
            .ok_or_else(|| fdo::Error::InvalidArgs("a call with no sender".into()))?;
        owned_by(conn, service, sender.as_str()).await?;
        let had_host = self.registry.has_host();
        match self.registry.add_host(service.to_owned()) {
            Added::New => {
                if !had_host {
                    Self::status_notifier_host_registered(&emitter).await?;
                    self.is_status_notifier_host_registered_changed(&emitter)
                        .await?;
                }
                Ok(())
            }
            Added::Known => Ok(()),
            Added::Full => Err(fdo::Error::LimitsExceeded(format!(
                "{MAX_HOSTS} hosts are registered"
            ))),
        }
    }

    #[zbus(property)]
    fn registered_status_notifier_items(&self) -> Vec<String> {
        self.registry.items()
    }

    #[zbus(property)]
    fn is_status_notifier_host_registered(&self) -> bool {
        self.registry.has_host()
    }

    #[zbus(property)]
    fn protocol_version(&self) -> i32 {
        0
    }

    #[zbus(signal)]
    async fn status_notifier_item_registered(
        emitter: &SignalEmitter<'_>,
        service: &str,
    ) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn status_notifier_item_unregistered(
        emitter: &SignalEmitter<'_>,
        service: &str,
    ) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn status_notifier_host_registered(emitter: &SignalEmitter<'_>) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn status_notifier_host_unregistered(emitter: &SignalEmitter<'_>) -> zbus::Result<()>;
}

/// Subscribes to NameOwnerChanged, then follows it for the life of the connection: a name
/// that loses its owner takes its items and its host with it. Call before requesting the
/// watcher's name, so no registration can come before the subscription.
pub async fn follow_owners(conn: &Connection) -> zbus::Result<()> {
    let mut changes = DBusProxy::new(conn)
        .await?
        .receive_name_owner_changed()
        .await?;
    let conn = conn.clone();
    tokio::spawn(async move {
        while let Some(change) = changes.next().await {
            let Ok(args) = change.args() else {
                tracing::warn!("cannot parse a NameOwnerChanged signal");
                continue;
            };
            if args.new_owner().is_none() {
                if let Err(err) = name_lost(&conn, args.name().as_str()).await {
                    tracing::warn!(name = %args.name(), error = %err, "cannot unregister what a vanished name held");
                }
            }
        }
    });
    Ok(())
}

async fn name_lost(conn: &Connection, name: &str) -> zbus::Result<()> {
    let watcher = conn
        .object_server()
        .interface::<_, Watcher>(WATCHER_PATH)
        .await?;
    let emitter = watcher.signal_emitter();
    let mut guard = watcher.get_mut().await;
    let lost = guard.registry.name_lost(name);
    for id in &lost.items {
        Watcher::status_notifier_item_unregistered(emitter, id).await?;
    }
    if !lost.items.is_empty() {
        guard
            .registered_status_notifier_items_changed(emitter)
            .await?;
    }
    if lost.last_host_gone {
        Watcher::status_notifier_host_unregistered(emitter).await?;
        guard
            .is_status_notifier_host_registered_changed(emitter)
            .await?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn both_registration_forms_name_the_item_as_the_specification_announces_it() {
        assert_eq!(
            item("org.kde.StatusNotifierItem-5-1", ":1.9"),
            Some((
                "org.kde.StatusNotifierItem-5-1/StatusNotifierItem".into(),
                "org.kde.StatusNotifierItem-5-1".into()
            ))
        );
        assert_eq!(
            item("/org/ayatana/NotificationItem/nm", ":1.9"),
            Some((":1.9/org/ayatana/NotificationItem/nm".into(), ":1.9".into()))
        );
        assert_eq!(item("not a name", ":1.9"), None);
        assert_eq!(item("/bad//path", ":1.9"), None);
    }

    #[test]
    fn duplicates_are_known_the_cap_holds_and_owners_take_their_items() {
        let mut registry = Registry::default();
        assert_eq!(
            registry.add_item("a/StatusNotifierItem".into(), "a".into()),
            Added::New
        );
        assert_eq!(
            registry.add_item("a/StatusNotifierItem".into(), "a".into()),
            Added::Known
        );
        for n in 1..MAX_ITEMS {
            assert_eq!(
                registry.add_item(format!(":1.9/i{n}"), ":1.9".into()),
                Added::New
            );
        }
        assert_eq!(
            registry.add_item(":1.9/one-too-many".into(), ":1.9".into()),
            Added::Full
        );
        let lost = registry.name_lost(":1.9");
        assert_eq!(lost.items.len(), MAX_ITEMS - 1);
        assert_eq!(registry.items(), ["a/StatusNotifierItem"]);
    }

    #[test]
    fn the_last_host_leaving_is_reported_once() {
        let mut registry = Registry::default();
        assert_eq!(registry.add_host("h1".into()), Added::New);
        assert_eq!(registry.add_host("h2".into()), Added::New);
        assert!(!registry.name_lost("h1").last_host_gone);
        assert!(registry.name_lost("h2").last_host_gone);
        assert!(!registry.name_lost("h2").last_host_gone);
    }

    #[test]
    fn a_host_beyond_the_cap_is_refused_and_a_known_one_does_not_grow_the_list() {
        let mut registry = Registry::default();
        for n in 0..MAX_HOSTS {
            assert_eq!(registry.add_host(format!("h{n}")), Added::New);
        }
        assert_eq!(registry.add_host("h0".into()), Added::Known);
        assert_eq!(registry.add_host("one-too-many".into()), Added::Full);
    }
}

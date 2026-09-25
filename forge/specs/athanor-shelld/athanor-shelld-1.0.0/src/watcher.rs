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

    /// True when this is the first host.
    pub fn add_host(&mut self, name: String) -> bool {
        let first = self.hosts.is_empty();
        if !self.hosts.contains(&name) {
            self.hosts.push(name);
        }
        first && !self.hosts.is_empty()
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

async fn has_owner(conn: &Connection, name: &str) -> fdo::Result<bool> {
    let name = BusName::try_from(name).map_err(|err| fdo::Error::InvalidArgs(err.to_string()))?;
    DBusProxy::new(conn).await?.name_has_owner(name).await
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
        if !has_owner(conn, &name).await? {
            return Err(fdo::Error::InvalidArgs(format!(
                "{name} has no owner on the bus"
            )));
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
        #[zbus(connection)] conn: &Connection,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
    ) -> fdo::Result<()> {
        if !has_owner(conn, service).await? {
            return Err(fdo::Error::InvalidArgs(format!(
                "{service} has no owner on the bus"
            )));
        }
        if self.registry.add_host(service.to_owned()) {
            Self::status_notifier_host_registered(&emitter).await?;
            self.is_status_notifier_host_registered_changed(&emitter)
                .await?;
        }
        Ok(())
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
        assert!(registry.add_host("h1".into()));
        assert!(!registry.add_host("h2".into()));
        assert!(!registry.name_lost("h1").last_host_gone);
        assert!(registry.name_lost("h2").last_host_gone);
        assert!(!registry.name_lost("h2").last_host_gone);
    }
}

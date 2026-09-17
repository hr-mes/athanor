use zbus::proxy;
use zbus::Connection;

use std::collections::HashMap;

#[proxy(
    interface = "org.freedesktop.NetworkManager",
    default_service = "org.freedesktop.NetworkManager",
    default_path = "/org/freedesktop/NetworkManager"
)]
pub trait NetworkManager {
    #[zbus(property)]
    fn wireless_enabled(&self) -> zbus::Result<bool>;
    #[zbus(property)]
    fn set_wireless_enabled(&self, val: bool) -> zbus::Result<()>;
    fn get_devices(&self) -> zbus::Result<Vec<zbus::zvariant::OwnedObjectPath>>;
    #[zbus(property)]
    fn active_connections(&self) -> zbus::Result<Vec<zbus::zvariant::OwnedObjectPath>>;
    fn activate_connection(
        &self,
        connection: &zbus::zvariant::ObjectPath<'_>,
        device: &zbus::zvariant::ObjectPath<'_>,
        specific_object: &zbus::zvariant::ObjectPath<'_>,
    ) -> zbus::Result<zbus::zvariant::OwnedObjectPath>;
    fn deactivate_connection(&self, active_connection: &zbus::zvariant::ObjectPath<'_>) -> zbus::Result<()>;
}

#[proxy(
    interface = "org.freedesktop.NetworkManager.Settings",
    default_service = "org.freedesktop.NetworkManager",
    default_path = "/org/freedesktop/NetworkManager/Settings"
)]
pub trait NmSettings {
    fn list_connections(&self) -> zbus::Result<Vec<zbus::zvariant::OwnedObjectPath>>;
    fn get_connection_by_uuid(&self, uuid: &str) -> zbus::Result<zbus::zvariant::OwnedObjectPath>;
}

#[proxy(
    interface = "org.freedesktop.NetworkManager.Settings.Connection",
    default_service = "org.freedesktop.NetworkManager"
)]
pub trait NmSettingsConnection {
    fn get_settings(&self) -> zbus::Result<HashMap<String, HashMap<String, zbus::zvariant::OwnedValue>>>;
    fn delete(&self) -> zbus::Result<()>;
}

#[proxy(
    interface = "org.freedesktop.NetworkManager.Connection.Active",
    default_service = "org.freedesktop.NetworkManager"
)]
pub trait NmActiveConnection {
    #[zbus(property)]
    fn id(&self) -> zbus::Result<String>;
    #[zbus(property)]
    fn connection(&self) -> zbus::Result<zbus::zvariant::OwnedObjectPath>;
    #[zbus(property)]
    fn ip4_config(&self) -> zbus::Result<zbus::zvariant::OwnedObjectPath>;
}

#[proxy(
    interface = "org.freedesktop.NetworkManager.IP4Config",
    default_service = "org.freedesktop.NetworkManager"
)]
pub trait NmIP4Config {
    #[zbus(property)]
    fn gateway(&self) -> zbus::Result<String>;
    #[zbus(property)]
    fn nameservers(&self) -> zbus::Result<Vec<u32>>;
    #[zbus(property)]
    fn address_data(&self) -> zbus::Result<Vec<HashMap<String, zbus::zvariant::OwnedValue>>>;
}

#[proxy(
    interface = "org.freedesktop.NetworkManager.Device",
    default_service = "org.freedesktop.NetworkManager"
)]
pub trait NmDevice {
    #[zbus(property)]
    fn device_type(&self) -> zbus::Result<u32>;
}

#[proxy(
    interface = "org.freedesktop.NetworkManager.Device.Wireless",
    default_service = "org.freedesktop.NetworkManager"
)]
pub trait NmWireless {
    fn get_access_points(&self) -> zbus::Result<Vec<zbus::zvariant::OwnedObjectPath>>;
    fn request_scan(&self, options: HashMap<&str, zbus::zvariant::Value<'_>>) -> zbus::Result<()>;
}

#[proxy(
    interface = "org.freedesktop.NetworkManager.AccessPoint",
    default_service = "org.freedesktop.NetworkManager"
)]
pub trait NmAccessPoint {
    #[zbus(property)]
    fn ssid(&self) -> zbus::Result<Vec<u8>>;
    #[zbus(property)]
    fn strength(&self) -> zbus::Result<u8>;
}

#[proxy(
    interface = "os.athanor.Bedrock",
    default_service = "os.athanor.Bedrock",
    default_path = "/os/athanor/Bedrock"
)]
pub trait BedrockAudio {
    #[zbus(property, name = "Volume")]
    fn volume(&self) -> zbus::Result<f64>;
    #[zbus(property, name = "Volume")]
    fn set_volume(&self, val: f64) -> zbus::Result<()>;
    #[zbus(property, name = "Muted")]
    fn muted(&self) -> zbus::Result<bool>;
    #[zbus(property, name = "Muted")]
    fn set_muted(&self, val: bool) -> zbus::Result<()>;
    #[zbus(property, name = "SourceMuted")]
    fn source_muted(&self) -> zbus::Result<bool>;
    #[zbus(property, name = "SourceMuted")]
    fn set_source_muted(&self, val: bool) -> zbus::Result<()>;
    #[zbus(property, name = "SourceVolume")]
    fn source_volume(&self) -> zbus::Result<f64>;
    #[zbus(property, name = "SourceVolume")]
    fn set_source_volume(&self, val: f64) -> zbus::Result<()>;
}

#[derive(Debug, Clone, PartialEq)]
pub struct WifiNetworkInfo {
    pub ssid: String,
    pub signal: i32,
    pub active: bool,
    pub saved: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BluetoothDeviceInfo {
    pub name: String,
    pub connected: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MprisState {
    pub title: String,
    pub artist: String,
    pub status: String,
}



#[derive(Clone, Debug)]
pub enum IpcBackend {
    Dbus {
        session: Connection,
        system: Connection,
    },
    Disconnected,
}


#[derive(Debug, Clone)]
pub enum AudioEvent {
    VolumeChanged(f64),
    MuteToggled(bool),
}

#[derive(Clone)]
pub struct AudioBus { sender: tokio::sync::broadcast::Sender<AudioEvent> }
impl Default for AudioBus { fn default() -> Self { Self::new() } }
impl AudioBus {
    pub fn new() -> Self { let (sender, _) = tokio::sync::broadcast::channel(128); Self { sender } }
    pub fn subscribe(&self) -> tokio::sync::broadcast::Receiver<AudioEvent> { self.sender.subscribe() }
    pub fn emit(&self, event: AudioEvent) { let _ = self.sender.send(event); }
}

#[derive(Debug, Clone)]
pub enum NetEvent {
    WifiToggled(bool),
    BluetoothToggled(bool),
    NetworkUpdated(String),
}

#[derive(Clone)]
pub struct NetBus { sender: tokio::sync::broadcast::Sender<NetEvent> }
impl Default for NetBus { fn default() -> Self { Self::new() } }
impl NetBus {
    pub fn new() -> Self { let (sender, _) = tokio::sync::broadcast::channel(128); Self { sender } }
    pub fn subscribe(&self) -> tokio::sync::broadcast::Receiver<NetEvent> { self.sender.subscribe() }
    pub fn emit(&self, event: NetEvent) { let _ = self.sender.send(event); }
}

#[derive(Debug, Clone)]
pub enum HardwareEvent {
    BrightnessChanged(f64),
    CapsLockToggled(bool),
}

#[derive(Clone)]
pub struct HardwareBus { sender: tokio::sync::broadcast::Sender<HardwareEvent> }
impl Default for HardwareBus { fn default() -> Self { Self::new() } }
impl HardwareBus {
    pub fn new() -> Self { let (sender, _) = tokio::sync::broadcast::channel(128); Self { sender } }
    pub fn subscribe(&self) -> tokio::sync::broadcast::Receiver<HardwareEvent> { self.sender.subscribe() }
    pub fn emit(&self, event: HardwareEvent) { let _ = self.sender.send(event); }
}

#[derive(Debug, Clone)]
pub enum MprisEvent {
    MprisUpdated(Option<MprisState>),
}

#[derive(Clone)]
pub struct MprisBus { sender: tokio::sync::broadcast::Sender<MprisEvent> }
impl Default for MprisBus { fn default() -> Self { Self::new() } }
impl MprisBus {
    pub fn new() -> Self { let (sender, _) = tokio::sync::broadcast::channel(128); Self { sender } }
    pub fn subscribe(&self) -> tokio::sync::broadcast::Receiver<MprisEvent> { self.sender.subscribe() }
    pub fn emit(&self, event: MprisEvent) { let _ = self.sender.send(event); }
}

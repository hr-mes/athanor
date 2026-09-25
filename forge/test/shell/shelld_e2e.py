#!/usr/bin/python3
"""shelld_e2e.py - package 2b.1 in the rig: the athanor-shelld binary on the session bus of
dbus-run-session, driven the way applications drive it. Checks its names, the public
notifications interface, the refusal of the private one to a process outside
athanor-bar.service, the cleaning of untrusted text and images, the tray watcher in both
registration forms, its restart, its log priorities and its memory at rest. Prints one line
per check and exits 1 if any fails.
"""

import os
import signal
import subprocess
import sys
import tempfile
import time

from gi.repository import Gio, GLib

DAEMON = "/out/bin/athanor-shelld"
LOG = "/out/shelld-e2e.log"
NOTIFY = (
    "org.freedesktop.Notifications",
    "/org/freedesktop/Notifications",
    "org.freedesktop.Notifications",
)
PRIVATE = (
    "org.freedesktop.Notifications",
    "/os/athanor/Notifications1",
    "os.athanor.Notifications1",
)
WATCHER = (
    "org.kde.StatusNotifierWatcher",
    "/StatusNotifierWatcher",
    "org.kde.StatusNotifierWatcher",
)
PSS_BUDGET_KB = 16 * 1024
failures = []


def check(name, ok, detail: object = ""):
    print(f"ok {name}" if ok else f"FAIL {name}: {detail}")
    if not ok:
        failures.append(name)


def call(bus, target, method, args=None, reply=None):
    name, path, iface = target
    return bus.call_sync(
        name,
        path,
        iface,
        method,
        args,
        GLib.VariantType(reply) if reply else None,
        Gio.DBusCallFlags.NONE,
        10000,
        None,
    )


def owned(bus, name):
    reply = bus.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameHasOwner",
        GLib.Variant("(s)", (name,)),
        GLib.VariantType("(b)"),
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    )
    return reply.unpack()[0]


def wait_for(predicate, seconds):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.iteration(False):
            pass
        if predicate():
            return True
        time.sleep(0.05)
    return False


def start(state):
    log = open(LOG, "a")
    env = dict(os.environ, XDG_STATE_HOME=state)
    return subprocess.Popen([DAEMON], env=env, stderr=log)


def notify(bus, summary, body, hints, actions=()):
    args = GLib.Variant(
        "(susssasa{sv}i)", ("e2e", 0, "", summary, body, list(actions), hints, -1)
    )
    return call(bus, NOTIFY, "Notify", args, "(u)").unpack()[0]


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    state = tempfile.mkdtemp(prefix="shelld-e2e-")
    daemon = start(state)
    names = ("org.freedesktop.Notifications", "org.kde.StatusNotifierWatcher")
    check(
        "names",
        wait_for(lambda: all(owned(bus, n) for n in names), 10),
        "names not owned in 10 s",
    )

    caps = call(bus, NOTIFY, "GetCapabilities", None, "(as)").unpack()[0]
    check(
        "capabilities", caps == ["actions", "body", "icon-static", "persistence"], caps
    )

    added = []
    bus.signal_subscribe(
        None,
        PRIVATE[2],
        "Added",
        PRIVATE[1],
        None,
        Gio.DBusSignalFlags.NONE,
        lambda *a: added.append(a[5].unpack()[0]),
    )
    notify(bus, "two\nlines", "<b>bold</b>\u202eevil\x07", {})
    wait_for(lambda: added, 5)
    n = added[-1] if added else None
    check(
        "plain text",
        n is not None and n[2] == "twolines" and n[3] == "<b>bold</b>evil",
        n and n[2:4],
    )

    try:
        call(bus, PRIVATE, "List", None, "(ba(usssa(ss)ybbsssuuayuu))")
        check(
            "private refused",
            False,
            "List answered a process outside athanor-bar.service",
        )
    except GLib.Error as err:
        check("private refused", "AccessDenied" in err.message, err.message)

    big = GLib.Variant("(iiibiiay)", (100000, 1, 400000, True, 8, 4, b"\0" * 16))
    good = GLib.Variant(
        "(iiibiiay)", (512, 256, 2048, True, 8, 4, b"\xff" * (512 * 256 * 4))
    )
    added.clear()
    notify(
        bus,
        "bad image",
        "",
        {"image-data": big, "image-path": GLib.Variant("s", "https://x/y.png")},
    )
    notify(bus, "good image", "", {"image-data": good})
    notify(
        bus, "huge hint", "", {"x-huge": GLib.Variant("ay", b"\0" * (8 * 1024 * 1024))}
    )
    wait_for(lambda: len(added) >= 3, 10)
    by_summary = {a[2]: a for a in added}
    bad, fine = by_summary.get("bad image"), by_summary.get("good image")
    check(
        "image refused",
        bad is not None and bad[11] == 0 and bad[10] == "" and bad[9] == "",
        bad and bad[9:13],
    )
    check(
        "image scaled",
        fine is not None and (fine[11], fine[12]) == (96, 48),
        fine and fine[11:13],
    )
    check("huge hint", "huge hint" in by_summary, sorted(by_summary))

    # The tray watcher, both forms, and an item leaving with its owner.
    address = os.environ["DBUS_SESSION_BUS_ADDRESS"]
    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    app = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
    app.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant("(su)", ("org.kde.StatusNotifierItem-e2e-1", 4)),
        None,
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    )
    call(
        app,
        WATCHER,
        "RegisterStatusNotifierItem",
        GLib.Variant("(s)", ("org.kde.StatusNotifierItem-e2e-1",)),
    )
    call(
        app,
        WATCHER,
        "RegisterStatusNotifierItem",
        GLib.Variant("(s)", ("/org/ayatana/NotificationItem/e2e",)),
    )

    def items():
        reply = bus.call_sync(
            WATCHER[0],
            WATCHER[1],
            "org.freedesktop.DBus.Properties",
            "Get",
            GLib.Variant("(ss)", (WATCHER[2], "RegisteredStatusNotifierItems")),
            GLib.VariantType("(v)"),
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
        return reply.unpack()[0]

    expected = {
        "org.kde.StatusNotifierItem-e2e-1/StatusNotifierItem",
        f"{app.get_unique_name()}/org/ayatana/NotificationItem/e2e",
    }
    check("tray items", set(items()) == expected, items())
    app.close_sync(None)
    check("tray owner gone", wait_for(lambda: items() == [], 5), items())

    lines = open(LOG).read().splitlines()
    check(
        "journal priorities",
        bool(lines) and all(line[:1] == "<" and line[2:3] == ">" for line in lines),
        lines[:3],
    )

    time.sleep(1)
    rollup = open(f"/proc/{daemon.pid}/smaps_rollup").read()
    pss = next(
        int(line.split()[1]) for line in rollup.splitlines() if line.startswith("Pss:")
    )
    check("memory", pss <= PSS_BUDGET_KB, f"{pss} kB PSS > {PSS_BUDGET_KB} kB")

    daemon.send_signal(signal.SIGKILL)
    daemon.wait()
    check(
        "names released",
        wait_for(lambda: not any(owned(bus, n) for n in names), 5),
        "still owned",
    )
    daemon = start(state)
    check(
        "names back",
        wait_for(lambda: all(owned(bus, n) for n in names), 10),
        "not owned after restart",
    )
    daemon.terminate()
    daemon.wait()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

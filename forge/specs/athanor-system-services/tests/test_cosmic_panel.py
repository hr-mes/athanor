"""Checks athanor-cosmic-panel: one socket pair, and the panel outliving the daemon.

Two defects this guards against, both silent.

The first is a pair that is not a pair. With the descriptor missing, or with the two
ends belonging to different sockets, both programs still start and the session still
owns org.freedesktop.Notifications; the only sign is a line in the journal, while the
notifications applet never appears. So the test does not look at the environment
variables alone: it makes two stand-in children exchange a byte over what they were
given and fails unless each reads what the other wrote.

The second is the panel dying with the daemon. The panel is the session's dock, launcher
and applets; a daemon that cannot start must cost notifications, never the panel. So the
test runs a daemon that exits the moment it starts and requires the wrapper to keep
going and to settle on running the panel alone.

Run it: python3 -B -m unittest discover -s forge/specs/athanor-system-services/tests
"""

import contextlib
import importlib.machinery
import importlib.util
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1] / "SOURCES/usr/bin/athanor-cosmic-panel"
)

# A stand-in for cosmic-notifications or cosmic-panel: pick the descriptor out of the
# variable the wrapper named, write that variable's name to the peer, read what the peer
# wrote, and leave it in a file for the test. The timeout is what turns a wrapper that
# hands out two unrelated sockets into a failed assertion instead of a hung suite; the
# lingering end is the daemon's, so that the panel is always the one to exit first and
# the wrapper returns instead of restarting the pair.
PEER = """#!{python}
import os, socket, time
peer = socket.socket(fileno=int(os.environ[{variable!r}]))
peer.settimeout(10)
peer.sendall({variable!r}.encode())
try:
    heard = peer.recv(64).decode()
except OSError as error:
    heard = "nothing: {{}}".format(error)
open({report!r}, "w").write(heard)
time.sleep({linger})
"""

# Exits at once, whatever it was given.
DIES = """#!{python}
import sys
sys.exit(3)
"""

# Stays up until it is told to go.
SURVIVES = """#!{python}
import signal, sys, time
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
time.sleep(3600)
"""


def load_script():
    """Import the wrapper, which is installed without a .py suffix."""
    loader = importlib.machinery.SourceFileLoader("athanor_cosmic_panel", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def scope_is_available():
    """Whether a user systemd manager is here to put the daemon in a scope of its own.

    A build container has none, and the wrapper's policy does not depend on the scope, so
    every other test runs without it and the one test that is about the scope skips.
    """
    try:
        return (
            subprocess.run(
                ["systemd-run", "--user", "--scope", "--quiet", "--", "true"],
                capture_output=True,
                timeout=30,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def said(journal):
    """What the wrapper has written to its stderr so far."""
    try:
        return pathlib.Path(journal).read_text().splitlines()
    except FileNotFoundError:
        return []


def write_stand_in(directory, name, source, **fields):
    path = pathlib.Path(directory, name)
    path.write_text(source.format(python=sys.executable, **fields))
    path.chmod(0o755)
    return str(path)


class CosmicPanelWrapper(unittest.TestCase):
    def setUp(self):
        self.module = load_script()
        # The transient scope is an environment property, not part of the policy under
        # test, and a build container has no user manager to make one. Only the test
        # that is about the scope puts it back.
        self.scope = self.module.DAEMON_SCOPE
        self.module.DAEMON_SCOPE = []

    def exchange(self, tmp):
        """Run the pair with stand-ins that report what each read from its descriptor."""
        reports = {}
        for role, variable, linger in (
            ("daemon", "DAEMON_NOTIFICATIONS_FD", 30),
            ("panel", "PANEL_NOTIFICATIONS_FD", 0),
        ):
            reports[role] = os.path.join(tmp, f"{role}.heard")
            path = write_stand_in(
                tmp, role, PEER, variable=variable, report=reports[role], linger=linger
            )
            setattr(self.module, role.upper(), path)

        self.module.main()

        self.assertEqual(
            pathlib.Path(reports["daemon"]).read_text(),
            "PANEL_NOTIFICATIONS_FD",
            "the daemon did not read what the panel wrote: the ends are not paired",
        )
        self.assertEqual(
            pathlib.Path(reports["panel"]).read_text(),
            "DAEMON_NOTIFICATIONS_FD",
            "the panel did not read what the daemon wrote: the ends are not paired",
        )

    def test_both_children_get_two_ends_of_the_same_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.exchange(tmp)

    @unittest.skipUnless(
        scope_is_available(), "no user systemd manager to make a transient scope in"
    )
    def test_the_descriptor_survives_the_transient_scope(self):
        """systemd-run --scope must hand the daemon its end of the pair.

        The daemon is started inside a scope of its own so that its memory cannot get the
        panel killed. That only works because systemd-run --scope execs the command in
        its own process instead of handing it to the manager, which is the kind of thing
        that is true until it is not, and losing it would cost notifications silently.
        """
        self.module.DAEMON_SCOPE = self.scope
        self.assertIn("--scope", self.scope)
        with tempfile.TemporaryDirectory() as tmp:
            self.exchange(tmp)

    def test_a_daemon_that_cannot_be_started_costs_only_the_notifications(self):
        """A daemon that will not exec must not cost the session its panel.

        The wrapper spawns the daemon before the panel. An exec error there -- a missing
        binary, an SELinux denial, a failing harden() -- used to leave main() with no
        panel started at all, and the unit would have restarted into the same wall until
        it failed for good. The panel has to come up anyway, without notifications, and
        the journal has to say so at err priority.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.module.DAEMON = os.path.join(tmp, "no-such-notification-daemon")
            self.module.PANEL = write_stand_in(tmp, "panel", SURVIVES)
            self.assertFalse(os.path.exists(self.module.DAEMON))

            finished = threading.Event()
            outcome = {}
            journal = os.path.join(tmp, "stderr")

            def run():
                try:
                    outcome["code"] = self.module.main()
                finally:
                    finished.set()

            with open(journal, "w") as stderr, contextlib.redirect_stderr(stderr):
                threading.Thread(target=run, daemon=True).start()

                for _ in range(200):
                    self.assertFalse(
                        finished.is_set(),
                        "the wrapper exited because the daemon could not be started: "
                        f"{said(journal)}",
                    )
                    if any("could not be started" in line for line in said(journal)):
                        break
                    finished.wait(0.05)
                else:
                    self.fail(f"the wrapper never reported the failure: {said(journal)}")
                written = said(journal)

            self.assertTrue(
                written[0].startswith(f"{self.module.ERR}athanor-cosmic-panel: "),
                f"the failure has to be an error in the journal: {written[0]!r}",
            )
            running = subprocess.run(
                ["pgrep", "-f", self.module.PANEL],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.split()
            self.assertEqual(
                len(running), 1, f"expected exactly one panel running, found {running}"
            )
            # No restart loop either: the panel is started once and kept.
            self.assertEqual(
                len([line for line in written if "could not be started" in line]),
                1,
                f"the pair should not be retried once the daemon cannot exec: {written}",
            )

            os.kill(int(running[0]), signal.SIGTERM)
            self.assertTrue(
                finished.wait(30), "the wrapper did not exit when the panel did"
            )
            self.assertEqual(outcome["code"], 0)

    def test_a_daemon_dying_just_slowly_enough_still_reaches_the_give_up(self):
        """A 61-second death cycle must not reset the count forever.

        The rule used to be "a run longer than 60 seconds clears the count", so a daemon
        that died every 61 seconds cleared it every time: the give-up was never reached
        and the panel was restarted once a minute for as long as the session lasted. The
        window is what fixes that, and it is a pure function of the exit times, so the
        cycle can be played out here without waiting five minutes for it.
        """
        window = self.module.FAILURE_WINDOW_SECONDS
        cycle = 61.0
        self.assertGreater(
            window,
            cycle * (self.module.GIVE_UP_AFTER - 1),
            "the window has to be wider than the cycle it is meant to catch",
        )

        failures = []
        for exit_number in range(1, self.module.GIVE_UP_AFTER + 1):
            failures = self.module.recent_failures(failures, exit_number * cycle)
            self.assertEqual(
                len(failures),
                exit_number,
                f"exit {exit_number} of a {cycle}s cycle was forgotten: {failures}",
            )
        self.assertGreaterEqual(
            len(failures),
            self.module.GIVE_UP_AFTER,
            "a daemon dying every 61 seconds never reaches the give-up",
        )

        # And the window really does forget: an exit older than it is dropped, so a
        # daemon that fails rarely keeps being restarted.
        self.assertEqual(
            self.module.recent_failures([0.0], window + 1.0),
            [window + 1.0],
        )

    def test_it_supervises_the_programs_the_image_installs(self):
        self.assertEqual(self.module.DAEMON, "/usr/bin/cosmic-notifications")
        self.assertEqual(self.module.PANEL, "/usr/bin/cosmic-panel")


if __name__ == "__main__":
    unittest.main()

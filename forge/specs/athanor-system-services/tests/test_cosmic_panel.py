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


def write_stand_in(directory, name, source, **fields):
    path = pathlib.Path(directory, name)
    path.write_text(source.format(python=sys.executable, **fields))
    path.chmod(0o755)
    return str(path)


class CosmicPanelWrapper(unittest.TestCase):
    def setUp(self):
        self.module = load_script()

    def test_both_children_get_two_ends_of_the_same_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = {}
            for role, variable, linger in (
                ("daemon", "DAEMON_NOTIFICATIONS_FD", 30),
                ("panel", "PANEL_NOTIFICATIONS_FD", 0),
            ):
                reports[role] = os.path.join(tmp, f"{role}.heard")
                path = write_stand_in(
                    tmp,
                    role,
                    PEER,
                    variable=variable,
                    report=reports[role],
                    linger=linger,
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

    def test_a_daemon_that_dies_at_once_does_not_end_the_wrapper(self):
        """The wrapper must outlive a hopeless daemon and keep a panel running.

        The daemon exits the moment it starts, every time. The wrapper is expected to
        restart the pair, back off, give up on the daemon after GIVE_UP_AFTER short runs
        and then run the panel alone -- still running, with one live panel, until the
        panel itself goes. The wrapper's own log is the record of the policy, so the
        test reads it instead of counting processes, which the restarts race with.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.module.DAEMON = write_stand_in(tmp, "daemon", DIES)
            self.module.PANEL = write_stand_in(tmp, "panel", SURVIVES)
            # The real delays are 1, 2, 4 ... seconds; what is under test is the
            # sequence and the give-up, not the wall clock.
            self.module.BACKOFF_CEILING_SECONDS = 0.01
            said = []
            self.module.log = said.append

            finished = threading.Event()
            outcome = {}

            def run():
                try:
                    outcome["code"] = self.module.main()
                finally:
                    finished.set()

            threading.Thread(target=run, daemon=True).start()

            for _ in range(600):
                self.assertFalse(
                    finished.is_set(),
                    f"the wrapper exited although only the daemon was failing: {said}",
                )
                if any("without it" in message for message in said):
                    break
                finished.wait(0.05)
            else:
                self.fail(f"the wrapper never gave up on the daemon: {said}")

            restarts = [message for message in said if "restarting it" in message]
            self.assertEqual(
                len(restarts),
                self.module.GIVE_UP_AFTER - 1,
                f"the pair should be restarted until the {self.module.GIVE_UP_AFTER}th "
                f"failure, then dropped: {said}",
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
            self.assertFalse(
                finished.is_set(), "the wrapper exited while the panel was still running"
            )

            # The panel going is the only thing that ends the wrapper.
            os.kill(int(running[0]), signal.SIGTERM)
            self.assertTrue(
                finished.wait(30), "the wrapper did not exit when the panel did"
            )
            self.assertEqual(outcome["code"], 0)

    def test_it_supervises_the_programs_the_image_installs(self):
        self.assertEqual(self.module.DAEMON, "/usr/bin/cosmic-notifications")
        self.assertEqual(self.module.PANEL, "/usr/bin/cosmic-panel")


if __name__ == "__main__":
    unittest.main()

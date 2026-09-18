"""Checks that athanor-cosmic-panel really hands the two programs one socket pair.

The defect this guards against is silent. With the descriptor missing, or with the two
ends belonging to different sockets, both programs still start and the session still
owns org.freedesktop.Notifications; the only sign is a line in the journal, while the
notifications applet never appears. So the test does not look at the environment
variables alone: it makes two stand-in children exchange a byte over what they were
given and fails unless each reads what the other wrote.

Run it: python3 -B -m unittest discover -s forge/specs/athanor-system-services/tests
"""

import importlib.machinery
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1] / "SOURCES/usr/bin/athanor-cosmic-panel"
)

# A stand-in for cosmic-notifications or cosmic-panel: pick the descriptor out of the
# variable the wrapper named, write that variable's name to the peer, read what the peer
# wrote, and leave it in a file for the test. The timeout is what turns a wrapper that
# hands out two unrelated sockets into a failed assertion instead of a hung suite.
PEER = """#!{python}
import os, socket
peer = socket.socket(fileno=int(os.environ[{variable!r}]))
peer.settimeout(10)
peer.sendall({variable!r}.encode())
try:
    heard = peer.recv(64).decode()
except OSError as error:
    heard = "nothing: {{}}".format(error)
open({report!r}, "w").write(heard)
"""


def load_script():
    """Import the wrapper, which is installed without a .py suffix."""
    loader = importlib.machinery.SourceFileLoader("athanor_cosmic_panel", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CosmicPanelWrapper(unittest.TestCase):
    def setUp(self):
        self.module = load_script()

    def test_both_children_get_two_ends_of_the_same_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = {}
            for role, variable in (
                ("daemon", "DAEMON_NOTIFICATIONS_FD"),
                ("panel", "PANEL_NOTIFICATIONS_FD"),
            ):
                reports[role] = os.path.join(tmp, f"{role}.heard")
                stand_in = pathlib.Path(tmp, role)
                stand_in.write_text(
                    PEER.format(
                        python=sys.executable, variable=variable, report=reports[role]
                    )
                )
                stand_in.chmod(0o755)

            self.module.DAEMON = os.path.join(tmp, "daemon")
            self.module.PANEL = os.path.join(tmp, "panel")
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

    def test_it_supervises_the_programs_the_image_installs(self):
        self.assertEqual(self.module.DAEMON, "/usr/bin/cosmic-notifications")
        self.assertEqual(self.module.PANEL, "/usr/bin/cosmic-panel")


if __name__ == "__main__":
    unittest.main()

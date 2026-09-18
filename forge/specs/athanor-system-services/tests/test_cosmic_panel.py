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
import time
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

# Stays up until it is told to go, and says when it is ready to be told. A panel that is
# running is not yet a panel that answers SIGTERM: until signal.signal() has run, the
# default action applies and the kernel kills it, which the wrapper reports -- correctly
# -- as a panel that died of a signal and an exit of 1. The file is written after the
# handler is installed, so a test that waits for it is testing the wrapper rather than
# the speed of an interpreter starting up.
SURVIVES = """#!{python}
import os, signal, sys, time
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
open({ready!r}, "w").write(str(os.getpid()))
time.sleep(3600)
"""


def load_script():
    """Import the wrapper, which is installed without a .py suffix."""
    loader = importlib.machinery.SourceFileLoader("athanor_cosmic_panel", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def panels(path):
    """The pids of the stand-in panels running from `path`."""
    return subprocess.run(
        ["pgrep", "-f", path], capture_output=True, text=True, check=False
    ).stdout.split()


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

    def assert_the_panel_survives_the_daemon(self, tmp):
        """Run the wrapper with a daemon that cannot start, and hold it to the contract.

        Whatever stopped the daemon, the panel has to come up and stay up, the journal
        has to say so once at err priority, and the pair must not be retried -- nothing
        about a binary that will not run changes in two seconds, and every retry would
        cost another panel. Returns what was written, for the caller to read further.
        """
        ready = os.path.join(tmp, "panel.ready")
        self.module.PANEL = write_stand_in(tmp, "panel", SURVIVES, ready=ready)
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

            # The failure is logged just before the panel is started, so the panel is
            # still on its way up here: wait for it to be running and able to answer
            # SIGTERM, rather than for however long an interpreter takes to start on the
            # machine the suite happens to run on.
            for _ in range(600):
                self.assertFalse(
                    finished.is_set(),
                    f"the wrapper exited before the panel was up: {said(journal)}",
                )
                if os.path.exists(ready):
                    break
                finished.wait(0.05)
            else:
                self.fail(f"the panel never came up: {said(journal)}")
            written = said(journal)

        self.assertTrue(
            written[0].startswith(f"{self.module.ERR}athanor-cosmic-panel: "),
            f"the failure has to be an error in the journal: {written[0]!r}",
        )
        running = panels(self.module.PANEL)
        self.assertEqual(
            len(running), 1, f"expected exactly one panel running, found {running}"
        )
        self.assertEqual(
            len([line for line in written if "could not be started" in line]),
            1,
            f"the pair should not be retried once the daemon cannot run: {written}",
        )

        os.kill(int(running[0]), signal.SIGTERM)
        self.assertTrue(finished.wait(30), "the wrapper did not exit when the panel did")
        self.assertEqual(outcome["code"], 0)
        return written

    def test_a_daemon_binary_that_is_not_there_costs_only_the_notifications(self):
        """The commonest way for the daemon not to start: it is not installed.

        Caught before the fork, so the journal says which file is missing rather than
        repeating an errno at the reader.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.module.DAEMON = os.path.join(tmp, "no-such-notification-daemon")
            self.assertFalse(os.path.exists(self.module.DAEMON))

            written = self.assert_the_panel_survives_the_daemon(tmp)

            self.assertIn(
                f"{self.module.DAEMON} is not there to be executed",
                written[0],
                "the check that happens before the fork is what makes this message; "
                f"without it the reader gets a raw errno: {written[0]!r}",
            )

    def test_a_daemon_binary_that_cannot_be_exec_d_costs_only_the_notifications(self):
        """The other way: the file is there and executable, and the kernel refuses it.

        A file with the executable bit and no program in it is the honest stand-in for
        everything that can only fail at the exec -- an SELinux denial, a failing
        harden(), a fork that does not happen. os.access() says yes; execve does not.
        """
        with tempfile.TemporaryDirectory() as tmp:
            daemon = pathlib.Path(tmp, "unrunnable")
            daemon.write_bytes(b"\x00 not a program, and not a script either\n")
            daemon.chmod(0o755)
            self.module.DAEMON = str(daemon)
            self.assertTrue(os.access(self.module.DAEMON, os.X_OK))

            self.assert_the_panel_survives_the_daemon(tmp)

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

    def test_the_failure_window_counts_a_suspend(self):
        """A suspend must age the window out, not be skipped over.

        time.monotonic() stops while the machine is suspended. Four exits, a laptop shut
        for the night, one more exit in the morning, and a window measured on
        CLOCK_MONOTONIC would call that five failures inside ten minutes and drop the
        daemon for a session that had been healthy all night. main() takes the clock as
        an argument so the eight hours can be played out here for nothing -- and so that
        a loop reading the wrong clock again fails this test rather than a laptop.
        """
        night = 8 * 60 * 60
        readings = []

        def slept_through_the_night():
            """1, 2, 3, 4 seconds -- then every reading is a night later."""
            readings.append(len(readings) + 1)
            if len(readings) < self.module.GIVE_UP_AFTER:
                return float(len(readings))
            return float(len(readings)) + (len(readings) - 4) * night

        with tempfile.TemporaryDirectory() as tmp:
            self.module.DAEMON = write_stand_in(tmp, "daemon", DIES)
            self.module.PANEL = write_stand_in(
                tmp, "panel", SURVIVES, ready=os.path.join(tmp, "panel.ready")
            )
            self.module.BACKOFF_START_SECONDS = 0.01
            self.module.BACKOFF_CEILING_SECONDS = 0.01

            finished = threading.Event()
            journal = os.path.join(tmp, "stderr")

            def run():
                try:
                    self.module.main(clock=slept_through_the_night)
                finally:
                    finished.set()

            with open(journal, "w") as stderr, contextlib.redirect_stderr(stderr):
                threading.Thread(target=run, daemon=True).start()

                # Well past the point a window that ignored the suspend would have given
                # up: every exit after the fourth is a night away from the last.
                wanted = self.module.GIVE_UP_AFTER + 3
                for _ in range(600):
                    if len(said(journal)) >= wanted:
                        break
                    finished.wait(0.05)
                else:
                    self.fail(f"the wrapper stopped restarting: {said(journal)}")
                written = said(journal)

                self.assertFalse(
                    any("without it" in line for line in written),
                    "a session healthy all night lost its notifications: the window is "
                    f"not counting the suspend: {written}",
                )
                self.assertFalse(finished.is_set())

                # The pair is being restarted the whole time, so there is a moment
                # between the old panel going and the new one arriving: wait for one
                # rather than sampling into the gap.
                for _ in range(600):
                    running = panels(self.module.PANEL)
                    if len(running) == 1:
                        break
                    finished.wait(0.05)
                else:
                    self.fail(f"no panel came back: {said(journal)}")
                os.kill(int(running[0]), signal.SIGTERM)
                self.assertTrue(finished.wait(30))

    def test_the_window_is_measured_on_a_clock_that_survives_suspend(self):
        """The default clock is CLOCK_BOOTTIME, which keeps counting while suspended."""
        self.assertAlmostEqual(
            self.module.boottime(),
            time.clock_gettime(time.CLOCK_BOOTTIME),
            delta=1.0,
        )
        self.assertGreaterEqual(
            time.clock_gettime(time.CLOCK_BOOTTIME),
            time.monotonic() - 1.0,
            "sanity: BOOTTIME never runs behind MONOTONIC",
        )

    def test_it_supervises_the_programs_the_image_installs(self):
        self.assertEqual(self.module.DAEMON, "/usr/bin/cosmic-notifications")
        self.assertEqual(self.module.PANEL, "/usr/bin/cosmic-panel")


if __name__ == "__main__":
    unittest.main()

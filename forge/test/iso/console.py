#!/usr/bin/env python3
"""Records the guest serial console and notes when each phase of the test ends.

Usage: console.py SOCKET LOGFILE PHASEFILE

QEMU serves the console on SOCKET as a unix server; this connects as the client. Every
byte read is appended to LOGFILE, so the whole run can be read afterwards even for
things nobody thought to look for in advance.

PHASEFILE gets one line per milestone, as "NAME EPOCH", and it is the file the verdict
reads. The milestones are written by the kickstarts themselves rather than guessed from
installer chatter, which is why they are exact strings: the ISO's own kickstart echoes
"Install finished", ours adds "Athanor kickstart finished", and the installed system
announces itself with a login prompt or with the greeter's own unit.

The GRUB menu on this ISO times out on its own, so nothing needs to answer it. A return
is sent anyway if the menu sits quiet, because a menu that stopped counting down would
otherwise burn the whole timeout in silence.
"""

import os
import socket
import sys
import time

# Marker -> phase name. Order matters only for reporting; each is written once.
MARKERS = (
    (b"Install finished", "installed"),
    (b"Athanor kickstart finished", "kickstart-done"),
    (b"Kernel panic", "panic"),
    (b"Entering emergency mode", "emergency"),
    (b"Failed to start", "unit-failed"),
    (b"login:", "login-prompt"),
    (b"athanor-greeter", "greeter-unit"),
    (b"Reached target Graphical Interface", "graphical-target"),
)

GRUB_MENU = b"GRUB version"
QUIET_BEFORE_GRUB_ANSWER = 20.0
MAX_GRUB_ANSWERS = 3
IDLE_GIVE_UP = 2400.0


def main() -> int:
    sock_path, log_path, phase_path = sys.argv[1], sys.argv[2], sys.argv[3]

    for _ in range(180):
        if os.path.exists(sock_path):
            break
        time.sleep(1)
    else:
        print("serial socket never appeared", flush=True)
        return 1

    s = socket.socket(socket.AF_UNIX)
    s.settimeout(10)
    s.connect(sock_path)

    log = open(log_path, "wb")
    phases = open(phase_path, "a", buffering=1)
    seen: set[str] = set()
    tail = b""
    grub_answers = 0
    last_data = time.time()

    def note(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        phases.write(f"{name} {time.time():.0f}\n")
        print(f"  console: {name} at {time.strftime('%H:%M:%S')}", flush=True)

    while True:
        try:
            chunk = s.recv(65536)
            if not chunk:
                note("console-closed")
                break
        except socket.timeout:
            chunk = b""
        except OSError as exc:
            print(f"  console: {exc}", flush=True)
            break

        if chunk:
            log.write(chunk)
            log.flush()
            # A bounded tail is enough to match markers and keeps memory flat over a run
            # that can produce megabytes of console output.
            tail = (tail + chunk)[-8000:]
            last_data = time.time()
            for needle, name in MARKERS:
                if needle in tail:
                    note(name)

        if (
            GRUB_MENU in tail
            and grub_answers < MAX_GRUB_ANSWERS
            and time.time() - last_data > QUIET_BEFORE_GRUB_ANSWER
        ):
            s.sendall(b"\r")
            grub_answers += 1
            print(f"  console: nudged GRUB ({grub_answers})", flush=True)
            time.sleep(5)

        if time.time() - last_data > IDLE_GIVE_UP:
            note("idle-timeout")
            break

    log.close()
    phases.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Drives the guest through GRUB, records its serial console, and notes each milestone.

Usage: console.py SOCKET LOGFILE PHASEFILE

QEMU serves the console on SOCKET as a unix server; this connects as the client. Every
byte read is appended to LOGFILE, so the whole run can be read afterwards even for things
nobody thought to look for in advance.

PHASEFILE gets one line per milestone, as "NAME EPOCH", and it is the file the verdict
reads. The milestones are written by the kickstarts themselves rather than guessed from
installer chatter, which is why they are exact strings: the ISO's own kickstart echoes
"Install finished", ours adds "Athanor kickstart finished", and the installed system
announces itself with a login prompt or a graphical target.

This also does the one thing that makes the test unattended at all. The ISO's menu entry
boots the installer with the kickstart that ships inside it, and that one is attended by
design: it draws a summary screen and waits for a person, forever. Rather than rewriting
the ISO, which would mean testing something other than what ships, the boot commands are
typed into GRUB's own command line, with our kickstart named on the kernel line. What
runs is the ISO's kernel, initrd and stage 2; only the answers come from us.

Why the command line and not the menu editor. Editing the highlighted entry means moving
the cursor onto the `linux` line, and GRUB's editor is a full-screen editor whose line
wrapping depends on the width of the terminal it is drawing to: on a 160-column serial
console the entry's own lines wrap differently than on 80, so counting Ctrl-N presses put
the text on a blank line and GRUB then booted "a command list" instead of the entry. The
command line takes whole commands and does not care how anything is drawn. Verified by
booting it and reading what the kernel reported as its command line.
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
    (b"login:", "login-prompt"),
    (b"Reached target Graphical Interface", "graphical-target"),
    (b"Started Greeter daemon", "greeter-unit"),
)

GRUB_MENU = b"GRUB version"
# What the UEFI firmware prints when it hands control to the ISO. The installed system is
# announced the same way but from a disk, as `starting Boot0004 "Athanor OS" from HD(...)`,
# which is how the two are told apart after an install.
BOOTED_FROM_CD = b'starting Boot0001 "UEFI QEMU QEMU CD-ROM'

# The boot commands, in the order GRUB wants them. They restate what the ISO's own menu
# entry does, with two additions: our kickstart, and a serial console so the installed
# system can be watched over the same line. The stage 2 label is the ISO's, set by the
# image builder; the kickstart label is the one mkfs gave the small disk the test creates.
# Both are labels and not device names because the firmware hands the disks over in
# whatever order it likes, and a test that depends on that order fails for the wrong
# reason.
BOOT_COMMANDS = (
    b"search --no-floppy --set=root -l 'Container-Installer-x86_64'",
    b"linux /images/pxeboot/vmlinuz inst.stage2=hd:LABEL=Container-Installer-x86_64"
    b" inst.ks=hd:LABEL=ATHANORKS:/collaudo.ks console=ttyS0",
    b"initrd /images/pxeboot/initrd.img",
    b"boot",
)

# Let the menu finish drawing before typing into it. It counts down from 60s, so there is
# room, and typing into a half-drawn screen is how this kind of automation goes wrong.
GRUB_SETTLE = 3.0
BETWEEN_COMMANDS = 2.0
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
    grub_done = False
    last_data = time.time()

    def note(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        phases.write(f"{name} {time.time():.0f}\n")
        print(f"  console: {name} at {time.strftime('%H:%M:%S')}", flush=True)

    def boot_with_our_kickstart() -> None:
        time.sleep(GRUB_SETTLE)
        s.sendall(b"c")  # leave the menu for GRUB's command line
        time.sleep(BETWEEN_COMMANDS)
        for command in BOOT_COMMANDS:
            s.sendall(command + b"\n")
            time.sleep(BETWEEN_COMMANDS)
        note("grub-booted")

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

        # The menu is answered once, on the way in. After the install the machine restarts
        # into GRUB again, and that second menu must be left alone: the entry it offers is
        # the installed system, which is exactly what the test wants booted, and it times
        # out on its own.
        if GRUB_MENU in tail and not grub_done:
            grub_done = True
            boot_with_our_kickstart()
            tail = b""

        # Booting the CD again after an install means the machine ignored the disk it just
        # wrote and will keep reinstalling until the run is killed. Say so and stop rather
        # than spending the rest of the budget on it.
        #
        # The test is what the firmware announces it is starting, not the presence of a
        # GRUB menu: the installed system has a GRUB of its own and shows it on the way
        # up, so treating any second menu as a loop ends the run at the exact moment it
        # was about to succeed. That is what an earlier version of this check did.
        if "installed" in seen and BOOTED_FROM_CD in tail:
            note("reinstall-loop")
            break

        if time.time() - last_data > IDLE_GIVE_UP:
            note("idle-timeout")
            break

    log.close()
    phases.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

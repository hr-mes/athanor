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
# Milestones that settle the run: once one of these is seen there is nothing left to wait
# for, so the watcher stops and the machine is shut down. A greeter is the answer the test
# wants; the rest are answers too, just unwelcome ones.
# A text login prompt is deliberately NOT here. The serial getty appears on the way to
# graphical.target, not instead of it, so stopping at it ends the run before the greeter
# has had a chance to start and reports a pass on a boot that never showed one. That is
# exactly what run 34259567237 did. It stays in MARKERS, because knowing the system got
# as far as a getty is useful when no greeter follows, but it no longer settles anything.
DECIDED = frozenset({"greeter-unit", "graphical-target", "panic", "emergency"})

# How long the guest may say nothing before the run is called over. A first boot that has
# to relabel the filesystem is the slowest legitimate silence there is, and it does not
# take anywhere near this long; anything quieter than this has stopped for good.
IDLE_GIVE_UP = 600.0

# When the installed system offers a login and no greeter has appeared, ask it what it is
# doing rather than inferring it from what the console stopped saying. Two readings fit a
# log that ends at getty.target -- a boot stalled before graphical.target, or a boot that
# simply stopped writing to the serial once the getty owned it -- and they call for
# opposite fixes. Deduction picked wrong twice (runs 34262503262 and 34269959759); the
# machine can answer directly. The account is the one collaudo.ks creates, it exists only
# inside this VM, and the whole exchange is recorded in the console log.
DIAGNOSTIC_USER = b"collaudo"
DIAGNOSTIC_PASSWORD = b"collaudo"
DIAGNOSTICS = (
    b"systemctl is-system-running",
    b"systemctl get-default",
    b"systemctl list-jobs --no-pager",
    b"systemctl status greetd.service --no-pager -l | head -20",
    b"systemctl list-units --failed --no-pager",
    # Where the default target actually comes from. /etc wins over /usr, so if the
    # installer wrote one there it decides the boot, and the image's own
    # /usr/lib/systemd/system/default.target -> graphical.target never gets a say.
    # Fedora Silverblue ships exactly what we ship, so the difference is made at
    # install time rather than in the image.
    b"ls -l /etc/systemd/system/default.target /usr/lib/systemd/system/default.target",
    # What greetd itself said before giving up. `systemctl status` shows the unit's fate
    # but only the last few lines of its output, and in run 34288274184 it exited
    # 0/SUCCESS after 2.3s with nothing on the console: a daemon that decided there was
    # no work to do rather than one that crashed. Its own log lines say why.
    b"journalctl -u greetd.service -b --no-pager | tail -40",
    # cage's own complaint. greetd reports only that the greeter "exited without creating
    # a session", because the session command sends its stderr nowhere greetd keeps, so
    # the compositor's reason for giving up never reaches the journal. Running the same
    # command by hand and letting it speak is the shortest way to that reason. It is run
    # as the greetd user, since a compositor started as root would answer a different
    # question than the one that fails.
    b"ls -l /dev/dri/ 2>&1 | head",
    # Whether logind has a seat with a graphics device attached at all. wlroots asks
    # logind for the DRM node, so a session-less, seat-less system is one where a
    # compositor cannot start no matter which groups the user is in.
    b"loginctl list-seats; loginctl seat-status seat0 2>&1 | head -20",
    # sudo -S reads the password from stdin: collaudo is in wheel, so sudo works, but it
    # asks, and in run 34293193136 the prompt swallowed the whole diagnostic. timeout,
    # because a compositor that does start would hold the console open and the run would
    # end with the rest unread.
    b"printf 'collaudo\\n' | sudo -S -u greetd timeout 10 sh -c"
    b" 'export XDG_RUNTIME_DIR=/run/user/966;"
    b" mkdir -p -m 0700 $XDG_RUNTIME_DIR; export WLR_NO_HARDWARE_CURSORS=1;"
    b" cage -s -m extend -- /usr/bin/athanor-shell-rs --greeter' 2>&1 | tail -25",
)
# Let each answer arrive before asking the next. Most are cheap queries on an idle guest;
# the last one runs a compositor under a 10s timeout, so its wait has to outlast that or
# the shell would still be busy when the watcher stops reading.
DIAGNOSTIC_PAUSE = 3.0
DIAGNOSTIC_LAST_PAUSE = 14.0


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

    def ask_the_guest_what_it_is_doing() -> None:
        """Log in over the serial and record what systemd says about itself."""
        s.sendall(DIAGNOSTIC_USER + b"\n")
        time.sleep(DIAGNOSTIC_PAUSE)
        s.sendall(DIAGNOSTIC_PASSWORD + b"\n")
        time.sleep(DIAGNOSTIC_PAUSE)
        for index, command in enumerate(DIAGNOSTICS):
            # A leading space absorbs the first characters, which the serial line drops
            # after heavy output: run 34295559310 received `echo collaudo | sudo ...` as
            # `ho collaudo | sudo ...` and the diagnostic was lost to "command not found".
            # A space is also what keeps the line out of bash history, which is fitting
            # for one that carries a password.
            s.sendall(b"   " + command + b"\n")
            last = index == len(DIAGNOSTICS) - 1
            time.sleep(DIAGNOSTIC_LAST_PAUSE if last else DIAGNOSTIC_PAUSE)
        note("diagnostics-sent")

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

        # A login prompt on the installed system with no greeter in sight is the case
        # worth interrogating. Ask once, then keep reading: the answers arrive as ordinary
        # console output and land in the log like everything else.
        if (
            "installed" in seen
            and "login-prompt" in seen
            and "diagnostics-sent" not in seen
            and not (seen & DECIDED)
        ):
            ask_the_guest_what_it_is_doing()
            tail = b""

        # The run is over the moment there is an answer. Waiting past a greeter, a panic
        # or an emergency shell only spends the budget on a question already settled, and
        # this watcher ending is what shuts the machine down.
        if seen & DECIDED:
            break

        # Nothing has been said for a long time and nothing is expected: a guest that
        # stopped talking before reaching a session is not going to start again. The
        # window is generous enough to cover a first boot that relabels the filesystem.
        # Once the guest has answered the diagnostics there is nothing further to wait
        # for, so the generous window that covers a slow first boot no longer applies.
        window = 60.0 if "diagnostics-sent" in seen else IDLE_GIVE_UP
        if time.time() - last_data > window:
            note("idle-timeout")
            break

    log.close()
    phases.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

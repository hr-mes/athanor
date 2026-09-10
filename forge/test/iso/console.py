#!/usr/bin/env python3
"""Drives the guest through GRUB, records its serial console, and notes each milestone.

Usage: console.py SOCKET LOGFILE PHASEFILE MONITOR

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

MONITOR is QEMU's monitor socket, and it is the machine's keyboard: the greeter is drawn
on the seat, not on the serial line, so the password is typed into it through `sendkey`
once the guest has said over the serial that the greeter is up. The guest is then asked,
over the serial again, whether the desktop session came up and stayed. A screenshot is
taken through the same socket at that point, whichever way it answered.

Why the command line and not the menu editor. Editing the highlighted entry means moving
the cursor onto the `linux` line, and GRUB's editor is a full-screen editor whose line
wrapping depends on the width of the terminal it is drawing to: on a 160-column serial
console the entry's own lines wrap differently than on 80, so counting Ctrl-N presses put
the text on a blank line and GRUB then booted "a command list" instead of the entry. The
command line takes whole commands and does not care how anything is drawn. Verified by
booting it and reading what the kernel reported as its command line.
"""

import os
import pathlib
import re
import socket
import subprocess
import sys
import time

# Marker -> phase name. Order matters only for reporting; each is written once. Colour
# escapes are stripped before matching: systemd wraps unit names in them on the console,
# so "[  OK  ] Started greetd.service - Greeter daemon." arrives as
# "Started \x1b[0;1;39mgreetd.service\x1b[0m - Greeter daemon.", and a needle written
# across the name never matched anything. The last two systemd lines were dead that way
# until run 34384585109 showed the unit starting with no phase recorded for it.
MARKERS = (
    (b"Install finished", "installed"),
    (b"Athanor kickstart finished", "kickstart-done"),
    (b"Kernel panic", "panic"),
    (b"Entering emergency mode", "emergency"),
    (b"login:", "login-prompt"),
    (b"Reached target graphical.target", "graphical-target"),
    (b"Started greetd.service", "greeter-unit"),
    # The guest's own answer to GREETER_PROBE below: a greeter session that is still
    # there, with the shell inside it, after it has had time to die.
    (b"GREETER_ALIVE", "greeter-alive"),
    (b"GREETER_DEAD", "greeter-dead"),
    # And to SESSION_PROBE: the account's own desktop session, with the shell and the
    # dock in it, still up after logging in at the greeter.
    (b"SESSION_ALIVE", "session-alive"),
    (b"SESSION_DEAD", "session-dead"),
)
ANSI = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]")

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
# for, so the watcher stops and the machine is shut down. A desktop session is the answer
# the test wants; the rest are answers too, just unwelcome ones.
# A text login prompt is deliberately NOT here. The serial getty appears on the way to
# graphical.target, not instead of it, so stopping at it ends the run before the greeter
# has had a chance to start and reports a pass on a boot that never showed one. That is
# exactly what run 34259567237 did. It stays in MARKERS, because knowing the system got
# as far as a getty is useful when no greeter follows, but it no longer settles anything.
#
# Nor do the greeter unit and the graphical target. Run 34384585109 had both on the
# console while its greeter was dying: greetd started, the greeter it launched aborted
# three seconds later, three times, until the start limit. They say the system tried,
# not that it succeeded. Nor, any longer, does the greeter itself: a steady greeter is
# where the login is typed, and the run is settled by the guest's own report of a steady
# desktop session after it. A greeter or a session found dead is not final either: the
# diagnostics are asked for first, and the idle window then ends the run.
DECIDED = frozenset({"session-alive", "panic", "emergency"})

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
# inside this VM, and the whole exchange is recorded in the console log. The same account
# is the one that logs in at the greeter.
GUEST_USER = b"collaudo"
GUEST_PASSWORD = b"collaudo"
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
    # The DRM nodes, for context: run 34293193136 showed card1 carrying a POSIX ACL, which
    # is how logind grants the active session access, so device permissions are not the
    # obstacle even though the greetd user is in no video group.
    b"ls -l /dev/dri/ 2>&1 | head",
    # Whether logind has a seat with a graphics device attached at all. wlroots asks
    # logind for the DRM node, so a session-less, seat-less system is one where a
    # compositor cannot start no matter which groups the user is in.
    b"loginctl list-seats; loginctl seat-status seat0 2>&1 | head -20",
    # Whether logind ever registered a session for greetd. cage failed with "[libseat] No
    # backend was able to open a seat", and libseat's logind backend needs a session to
    # attach to. greetd's journal shows pam_unix opening one and never pam_systemd, and
    # the console carries no "New session" line, so this is the thing to confirm.
    b"loginctl list-sessions --no-pager",
    # And whether greetd's own session ends up with a seat. The steady-state listing above
    # only ever shows collaudo's sessions: greetd's lives about two seconds, so by the time
    # anything is asked it is gone and its seat has never actually been observed. A single
    # sleep is too narrow a window to catch it -- run 34356955543 caught nothing -- so this
    # polls twenty times a second across a restart and prints whatever it finds.
    b"printf 'collaudo\\n' | sudo -S systemctl restart greetd.service;"
    b" for i in $(seq 60); do"
    b' s=$(loginctl list-sessions --no-legend 2>/dev/null | awk \'$3=="greetd" && $6=="greeter"{print $1; exit}\');'
    b' if [ -n "$s" ]; then loginctl show-session $s -p Id -p Seat -p Type -p Class -p VTNr;'
    b' break; fi; sleep 0.05; done; echo "polled: ${s:-none}"',
    # Restart greetd and watch what logind and PAM say while it tries. This is the service
    # itself rather than a hand-run copy: the manual reproduction in run 34297060397 was
    # run under sudo, which creates no logind session of its own and so could not tell a
    # broken greeter from a broken reproduction.
    b"printf 'collaudo\\n' | sudo -S systemctl reset-failed greetd.service;"
    b" printf 'collaudo\\n' | sudo -S systemctl start greetd.service; sleep 6;"
    b" journalctl -b --no-pager -u greetd -u systemd-logind --since '-20s' | tail -30",
    # The compositor's own words, and the renderer probe's before them: the session
    # script runs both under systemd-cat. greetd is started again a second after the
    # greeter fails, so any snapshot cuts one attempt in flight -- run 34365841089 ended
    # on the EGL warning of an attempt begun that same second. A tail this wide holds at
    # least one complete attempt, and xkbcomp's keysym chatter is left out so the lines
    # that matter fit in it.
    b"journalctl -b --no-pager -t athanor-greeter-probe -t athanor-greeter --since '-120s'"
    b" | grep -v 'Could not resolve keysym' | tail -50",
)
# Let each answer arrive before asking the next. Most are cheap queries on an idle guest;
# the ones that restart greetd wait inside their own command line, and the last pause
# outlasts the greeter's retry so its journal is read settled rather than mid-attempt.
DIAGNOSTIC_PAUSE = 3.0
DIAGNOSTIC_LAST_PAUSE = 14.0

# Ask the guest whether its greeter is actually up, before anything else is touched. A
# greeter that fails is started again by greetd a second later, so a greeter session
# present at one instant means little; one that is still the same session, of class
# greeter, with the shell inside it, fifteen seconds on has outlived every failure seen
# so far (the shell's own abort took three seconds). The marker is assembled by printf so
# that the console's echo of what was typed cannot pass for the answer.
#
# The session is picked by class, not by user alone: greetd's user manager holds a
# session of its own, class manager-early and listed first, and run 34398712740 answered
# GREETER_DEAD for it while the greeter session beside it was on screen. CLASS is the
# sixth column of `loginctl list-sessions`.
GREETER_PROBE = (
    b"for i in $(seq 30); do"
    b' s=$(loginctl list-sessions --no-legend 2>/dev/null | awk \'$3=="greetd" && $6=="greeter"{print $1; exit}\');'
    b' [ -n "$s" ] && break; sleep 1; done; sleep 15;'
    b' if [ -n "$s" ] && [ "$(loginctl show-session "$s" -p Class --value 2>/dev/null)" = greeter ]'
    b' && loginctl session-status "$s" 2>/dev/null | grep -q athanor-shell;'
    b" then printf 'GREETER_%s %s\\n' ALIVE \"$s\"; else printf 'GREETER_%s %s\\n' DEAD \"${s:-none}\"; fi"
)
# Thirty seconds of looking plus fifteen of watching, and a margin for the shell.
GREETER_PROBE_WAIT = 50.0

# The password as QEMU's `sendkey` wants it, one key per command. QEMU names a letter key
# by the letter, and letters are all the password has.
GREETER_PASSWORD_KEYS = tuple(GUEST_PASSWORD.decode())

# Ask the guest whether the login at the greeter produced a desktop, the same way the
# greeter was asked about: the account's session on the seat -- the serial login is the
# same account with no seat -- of type wayland, with the session target and the units it
# gathers all still active fifteen seconds after the target came up. The units are asked
# about one by one: `systemctl is-active` given several names answers yes when any one
# of them is, and a desktop with the shell crashed out of it is exactly the failure this
# is for. The names that are down go into the answer, so a dead session says what died.
SESSION_UNITS = b"athanor-session.target athanor-shell.service athanor-dock.service"
SESSION_PROBE = (
    b"for i in $(seq 60); do"
    b' s=$(loginctl list-sessions --no-legend 2>/dev/null | awk \'$3=="collaudo" && $4=="seat0"{print $1; exit}\');'
    b' [ -n "$s" ] && systemctl --user -q is-active athanor-session.target && break; sleep 1; done; sleep 15;'
    b" down=; for u in " + SESSION_UNITS + b'; do systemctl --user -q is-active "$u" || down="$down $u"; done;'
    b' if [ -n "$s" ] && [ "$(loginctl show-session "$s" -p Type --value 2>/dev/null)" = wayland ] && [ -z "$down" ];'
    b" then printf 'SESSION_%s %s\\n' ALIVE \"$s\"; else printf 'SESSION_%s %s down:%s\\n' DEAD \"${s:-none}\" \"$down\"; fi"
)
# Sixty seconds of looking plus fifteen of watching, and a margin.
SESSION_PROBE_WAIT = 85.0

# What to ask when the session did not come up, from the account's own serial login: its
# user manager is the one the desktop runs in, so `systemctl --user` here sees the very
# units the greeter's login started.
SESSION_DIAGNOSTICS = (
    b"loginctl list-sessions --no-pager",
    b"systemctl --user list-units --failed --no-pager",
    b"systemctl --user status athanor-session.target athanor-desktop.service"
    b" athanor-shell.service athanor-dock.service --no-pager -l | head -60",
    # The compositor's own words, and the greeter's before them, under the tags the
    # session scripts log them with.
    b"journalctl -b --no-pager -t athanor-session -t athanor-greeter --since '-300s'"
    b" | grep -v 'Could not resolve keysym' | tail -50",
    # What the user manager did with the session: the readiness gate timing out, a unit
    # dying at start, the target never reached.
    b"journalctl --user -b --no-pager --since '-300s' | tail -60",
    # What greetd made of the login itself.
    b"printf 'collaudo\\n' | sudo -S journalctl -b --no-pager -u greetd --since '-300s' | tail -30",
)
# The tests drive a fake guest that answers at once and scale every wait in the login
# path down through this; the run itself leaves it at one.
PACE = float(os.environ.get("ATHANOR_CONSOLE_PACE", "1"))


def main() -> int:
    sock_path, log_path, phase_path, monitor_path = sys.argv[1:5]

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

    def ask(command: bytes, wait: float) -> None:
        """Type a command at the guest's serial shell and let its answer arrive."""
        # A leading space absorbs the first characters, which the serial line drops
        # after heavy output: run 34295559310 received `echo collaudo | sudo ...` as
        # `ho collaudo | sudo ...` and the diagnostic was lost to "command not found".
        # A space is also what keeps the line out of bash history, which is fitting
        # for one that carries a password.
        s.sendall(b"   " + command + b"\n")
        time.sleep(wait * PACE)

    def monitor(*commands: str) -> None:
        """Send commands to QEMU's monitor: the keyboard and the screen are there."""
        script = str(pathlib.Path(__file__).with_name("monitor.py"))
        subprocess.run([sys.executable, script, monitor_path, *commands], check=True)

    def ask_about_the_greeter() -> None:
        """Log in over the serial and ask whether the greeter is up."""
        s.sendall(GUEST_USER + b"\n")
        time.sleep(DIAGNOSTIC_PAUSE * PACE)
        s.sendall(GUEST_PASSWORD + b"\n")
        time.sleep(DIAGNOSTIC_PAUSE * PACE)
        ask(GREETER_PROBE, GREETER_PROBE_WAIT)
        note("greeter-asked")

    def log_in_at_the_greeter() -> None:
        """Type the password at the greeter, on the machine's keyboard, then ask the
        guest whether the desktop came up, and keep a picture of the screen as it is
        when it answers."""
        monitor(*(f"sendkey {key}" for key in GREETER_PASSWORD_KEYS), "sendkey ret")
        ask(SESSION_PROBE, SESSION_PROBE_WAIT)
        monitor(f"screendump {pathlib.Path(log_path).with_name('screen-session.ppm')}")
        note("login-sent")

    def collect(diagnostics: tuple[bytes, ...]) -> None:
        """Record what systemd says about itself."""
        for index, command in enumerate(diagnostics):
            last = index == len(diagnostics) - 1
            ask(command, DIAGNOSTIC_LAST_PAUSE if last else DIAGNOSTIC_PAUSE)
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
            clean = ANSI.sub(b"", tail)
            for needle, name in MARKERS:
                if needle in clean:
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

        # A login prompt on the installed system is where the questions start. Ask once,
        # then keep reading: the answers arrive as ordinary console output and land in
        # the log like everything else.
        if (
            "installed" in seen
            and "login-prompt" in seen
            and "greeter-asked" not in seen
            and not (seen & DECIDED)
        ):
            ask_about_the_greeter()
            tail = b""

        # A steady greeter is where the login happens. Once.
        if "greeter-alive" in seen and "login-sent" not in seen:
            log_in_at_the_greeter()
            tail = b""

        # Whichever of the two died is the one worth interrogating.
        if "diagnostics-sent" not in seen:
            if "greeter-dead" in seen:
                collect(DIAGNOSTICS)
                tail = b""
            elif "session-dead" in seen:
                collect(SESSION_DIAGNOSTICS)
                tail = b""

        # The run is over the moment there is an answer. Waiting past a session, a panic
        # or an emergency shell only spends the budget on a question already settled, and
        # this watcher ending is what shuts the machine down.
        if seen & DECIDED:
            break

        # Nothing has been said for a long time and nothing is expected: a guest that
        # stopped talking before reaching a session is not going to start again. The
        # window is generous enough to cover a first boot that relabels the filesystem.
        # Once the guest has answered the diagnostics there is nothing further to wait
        # for, so the generous window that covers a slow first boot no longer applies.
        window = 120.0 if "diagnostics-sent" in seen else IDLE_GIVE_UP
        if time.time() - last_data > window:
            note("idle-timeout")
            break

    log.close()
    phases.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

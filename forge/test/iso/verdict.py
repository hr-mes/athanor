#!/usr/bin/env python3
"""Turns what the run recorded into a pass or a fail, and into something readable.

Usage: verdict.py OUTPUT_DIR GREETER_WAIT QEMU_STATUS

Reads phases.txt, written by console.py, and the console log beside it. Prints a report
on stdout, writes the same report to OUTPUT_DIR/verdict.md for the job summary, and
exits non-zero when the run did not reach a greeter.

Three things have to be true for a pass, and they are checked separately so a failure
says which half broke:

  installed        the ISO's own kickstart finished, so ostreecontainer wrote the image
  kickstart-done   our additions ran too, so the disk has an account on it
  greeter          the installed system started and reached a session prompt

The greeter is recognised from the console rather than from a screenshot, because a
screenshot cannot tell a drawn greeter from a wallpaper. The screenshots are still kept
and published: an automated check says the session started, a person looking at the
picture says it started *correctly*, and the second question is not one this script can
answer.
"""

import pathlib
import sys

GREETER_SIGNALS = ("greeter-unit", "graphical-target", "login-prompt")
FAILURE_SIGNALS = ("panic", "emergency")


def main() -> int:
    out = pathlib.Path(sys.argv[1])
    greeter_wait = int(sys.argv[2])
    qemu_status = int(sys.argv[3])

    phase_file = out / "phases.txt"
    phases: dict[str, int] = {}
    if phase_file.exists():
        for line in phase_file.read_text().splitlines():
            name, _, epoch = line.partition(" ")
            if name and epoch.isdigit():
                phases.setdefault(name, int(epoch))

    log = out / "serial.log"
    log_bytes = log.stat().st_size if log.exists() else 0
    shots = sorted(out.glob("screen-*.ppm"))

    installed = "installed" in phases
    kickstart_done = "kickstart-done" in phases
    greeter = next((s for s in GREETER_SIGNALS if s in phases), None)
    failures = [s for s in FAILURE_SIGNALS if s in phases]

    lines = ["## ISO acceptance test", ""]
    lines.append(f"- installer finished: {'yes' if installed else 'NO'}")
    lines.append(
        f"- unattended kickstart finished: {'yes' if kickstart_done else 'NO'}"
    )
    lines.append(f"- greeter reached: {greeter if greeter else 'NO'}")
    if failures:
        lines.append(f"- guest failures seen: {', '.join(failures)}")
    lines.append(f"- console log: {log_bytes} bytes")
    lines.append(f"- screenshots: {len(shots)}")
    # A non-zero status from `timeout` is 124, which means the run outlived its budget
    # rather than that QEMU itself broke; both are worth naming.
    if qemu_status == 124:
        lines.append("- qemu: killed by the timeout, the run did not finish on its own")
    elif qemu_status != 0:
        lines.append(f"- qemu: exited {qemu_status}")

    if installed and phases.get("installed") and greeter:
        elapsed = phases[greeter] - phases["installed"]
        lines.append(f"- first boot to greeter: {elapsed}s (budget {greeter_wait}s)")

    ok = installed and kickstart_done and greeter is not None and not failures
    lines.insert(1, f"**{'PASS' if ok else 'FAIL'}**")
    report = "\n".join(lines) + "\n"

    (out / "verdict.md").write_text(report)
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

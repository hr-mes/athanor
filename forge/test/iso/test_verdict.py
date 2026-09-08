#!/usr/bin/env python3
"""Checks that the acceptance test reports what actually happened.

Run it directly: python3 forge/test/iso/test_verdict.py

Two parts of the ISO test can be wrong quietly. A VM that does not boot is loud; a verdict
that calls a broken run green is not, and neither is a console that types the wrong thing
at GRUB, which just leaves the installer waiting for a person until the timeout. So the
four cases that decide a pass or a fail are pinned here, together with the boot commands
console.py sends, the markers it recognises, and the PNG conversion, checked on the pixels
rather than on the file existing.
"""

import pathlib
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import zlib

HERE = pathlib.Path(__file__).resolve().parent


def verdict(tmp: pathlib.Path, phases, qemu_status=0):
    out = tmp / "run"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    (out / "phases.txt").write_text("".join(f"{n} {t}\n" for n, t in phases))
    (out / "serial.log").write_bytes(b"console output\n")
    proc = subprocess.run(
        [sys.executable, str(HERE / "verdict.py"), str(out), "900", str(qemu_status)],
        capture_output=True,
        text=True,
    )
    return proc.returncode, (out / "verdict.md").read_text()


def test_pass(tmp: pathlib.Path) -> None:
    code, report = verdict(
        tmp, [("installed", 100), ("kickstart-done", 110), ("greeter-unit", 400)]
    )
    assert code == 0, f"a complete run must pass, got {code}"
    assert "**PASS**" in report, report
    assert "first boot to greeter: 300s" in report, report


def test_installed_but_no_greeter(tmp: pathlib.Path) -> None:
    # The half that most needs to be told apart: the disk was written, nothing started.
    code, report = verdict(
        tmp, [("installed", 100), ("kickstart-done", 110)], qemu_status=124
    )
    assert code == 1, "a run that never reached a session must fail"
    assert "installer finished: yes" in report, report
    assert "greeter reached: NO" in report, report
    assert "killed by the timeout" in report, report


def test_panic_fails_despite_markers(tmp: pathlib.Path) -> None:
    # A login prompt after a panic is not a pass: the guest already broke.
    code, report = verdict(
        tmp,
        [("installed", 1), ("kickstart-done", 2), ("login-prompt", 3), ("panic", 4)],
    )
    assert code == 1, "a panic must fail the run"
    assert "guest failures seen: panic" in report, report


def test_reinstall_loop_fails(tmp: pathlib.Path) -> None:
    # The machine booted the ISO again instead of the disk it had just written. Every
    # install marker is present, several times over, and the run still proves nothing
    # about first boot, so it must fail and say which way.
    code, report = verdict(
        tmp,
        [("installed", 100), ("kickstart-done", 110), ("reinstall-loop", 700)],
        qemu_status=124,
    )
    assert code == 1, "a guest that reinstalls in a loop must fail"
    assert "guest failures seen: reinstall-loop" in report, report


def test_nothing_recorded(tmp: pathlib.Path) -> None:
    # No phases file at all: a verdict, not a traceback.
    out = tmp / "empty"
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(HERE / "verdict.py"), str(out), "900", "1"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "**FAIL**" in proc.stdout, proc.stdout


def test_screenshot_keeps_the_pixels(tmp: pathlib.Path) -> None:
    shots = tmp / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    width, height = 4, 3
    pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255] * height)
    ppm = shots / "screen-001.ppm"
    ppm.write_bytes(b"P6\n%d %d\n255\n" % (width, height) + pixels)

    subprocess.run(
        [sys.executable, str(HERE / "screenshots.py"), str(shots)], check=True
    )
    png = (shots / "screen-001.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    assert not ppm.exists(), "the PPM should be replaced, not kept"

    idat = png.index(b"IDAT") + 4
    length = struct.unpack(">I", png[idat - 8 : idat - 4])[0]
    raw = zlib.decompress(png[idat : idat + length])
    stride = width * 3
    # Drop the per-scanline filter byte and compare with what went in.
    back = b"".join(
        raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)] for y in range(height)
    )
    assert back == pixels, "the image changed on the way through"


def test_console_boots_our_kickstart(tmp: pathlib.Path) -> None:
    """console.py must name our kickstart at GRUB, in the order GRUB accepts."""
    if not hasattr(socket, "AF_UNIX"):
        # QEMU serves its console on a unix socket, so this check only means something
        # where the test itself runs. Skipping rather than failing keeps the suite usable
        # from a Windows workstation while it still runs in full on the job's runner.
        print("  skip test_console_boots_our_kickstart: no unix sockets here")
        return

    run = tmp / "console"
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    sock = str(run / "serial.sock")

    server = socket.socket(socket.AF_UNIX)
    server.bind(sock)
    server.listen(1)
    proc = subprocess.Popen(
        [
            sys.executable,
            str(HERE / "console.py"),
            sock,
            str(run / "serial.log"),
            str(run / "phases.txt"),
        ],
        stdout=subprocess.DEVNULL,
    )
    try:
        conn, _ = server.accept()
        conn.settimeout(2)
        conn.sendall(b"GRUB version 2.12\r\n")

        typed = b""
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                typed += conn.recv(65536)
            except socket.timeout:
                pass
            if typed.rstrip().endswith(b"boot"):
                break
        assert b"search --no-floppy" in typed, typed[:200]
        assert b"inst.ks=hd:LABEL=ATHANORKS:/collaudo.ks" in typed, typed[:400]
        assert b"initrd /images/pxeboot/initrd.img" in typed, (
            "the initrd was never named"
        )
        assert typed.rstrip().endswith(b"boot"), typed[-40:]

        # Markers split across reads, which is how a real console delivers them.
        conn.sendall(b"Install fin")
        time.sleep(0.4)
        conn.sendall(b"ished\r\n")
        time.sleep(0.4)
        conn.sendall(b"Athanor kickstart finished\r\n")
        time.sleep(0.4)
        conn.sendall(b"Started Greeter daemon.\r\n")
        time.sleep(0.8)
        conn.close()
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
        server.close()

    phases = dict(
        line.split() for line in (run / "phases.txt").read_text().splitlines()
    )
    for expected in ("grub-booted", "installed", "kickstart-done", "greeter-unit"):
        assert expected in phases, f"{expected} not recorded: {sorted(phases)}"


def main() -> int:
    with tempfile.TemporaryDirectory() as name:
        tmp = pathlib.Path(name)
        for test in (
            test_pass,
            test_installed_but_no_greeter,
            test_panic_fails_despite_markers,
            test_reinstall_loop_fails,
            test_nothing_recorded,
            test_screenshot_keeps_the_pixels,
            test_console_boots_our_kickstart,
        ):
            test(tmp)
            print(f"  ok  {test.__name__}")
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""install_console.py SOCKET LOGFILE KICKSTART: boots the installer with our kickstart.

Types the acceptance test's GRUB commands (forge/test/iso/console.py, reused rather than
copied) with the kickstart file name replaced, then records the serial console to LOGFILE
until QEMU closes it at the kickstart's poweroff.
"""

import os
import pathlib
import socket
import sys
import time

# This script is found by its position in the repository, two directories below the root:
# forge/test/iso is a sibling of scripts/devvm's parent. create.sh runs it in place with
# "$HERE/install_console.py", so this only breaks if scripts/devvm itself was copied or
# symlinked out of the repo tree -- but then it breaks silently: create.sh backgrounds
# this process and runs QEMU in the foreground, so a crash here at start-up leaves nobody
# to type at the GRUB menu, and QEMU just sits there with no further output. A plain
# ModuleNotFoundError from the failed import says as much, but only if someone happens to
# be watching the very first instant of a `create.sh` that otherwise looks like a normal,
# multi-minute install -- which is what "hangs silently" meant in practice.
_ISO_TEST_DIR = pathlib.Path(__file__).resolve().parents[2] / "forge" / "test" / "iso"
if not (_ISO_TEST_DIR / "console.py").is_file():
    sys.exit(
        f"install_console.py: expected {_ISO_TEST_DIR / 'console.py'} two directories "
        "above scripts/devvm, found nothing there. This script locates "
        "forge/test/iso/console.py by its position in the repository: run it from "
        "scripts/devvm inside a normal checkout of athanor, not from a copy or a "
        "symlink taken out of the repository layout."
    )
sys.path.insert(0, str(_ISO_TEST_DIR))
import console


def main() -> int:
    sock_path, log_path, kickstart = sys.argv[1:4]
    commands = [
        c.replace(b"collaudo.ks", kickstart.encode()) for c in console.BOOT_COMMANDS
    ]

    for _ in range(180):
        if os.path.exists(sock_path):
            break
        time.sleep(1)
    else:
        print("serial socket never appeared", file=sys.stderr)
        return 1

    s = socket.socket(socket.AF_UNIX)
    s.connect(sock_path)
    tail = b""
    typed = False
    with open(log_path, "wb") as log:
        while chunk := s.recv(65536):
            log.write(chunk)
            log.flush()
            tail = (tail + chunk)[-8000:]
            if not typed and console.GRUB_MENU in tail:
                time.sleep(console.GRUB_SETTLE)
                s.sendall(b"c")
                time.sleep(console.BETWEEN_COMMANDS)
                for command in commands:
                    s.sendall(command + b"\n")
                    time.sleep(console.BETWEEN_COMMANDS)
                typed = True
    return 0


if __name__ == "__main__":
    sys.exit(main())

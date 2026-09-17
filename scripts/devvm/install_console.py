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

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "forge" / "test" / "iso")
)
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

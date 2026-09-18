#!/usr/bin/env bash
# console.sh: attaches to the running guest's serial console (STATE/console.sock, opened
# by start.sh) for when SSH is unreachable -- a hung boot, a dead network, typing at a
# GRUB or systemd-boot menu. The guest's tty is on the other end, so this is a real,
# bidirectional terminal: type at it, Ctrl-] (the client's escape, printed on start)
# leaves without touching the guest. It only reads and writes a socket already made
# user-only by start.sh's umask; it needs no permission of its own.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
source "$HERE/devvm.env"

[[ -S $STATE/console.sock ]] || die "$STATE/console.sock missing: start.sh must be running"

if command -v socat > /dev/null; then
  echo "attached (socat); ^] to leave" >&2
  exec socat -,raw,echo=0,escape=0x1d "UNIX-CONNECT:$STATE/console.sock"
elif command -v python3 > /dev/null; then
  echo "attached (python3); ^] to leave" >&2
  exec python3 - "$STATE/console.sock" <<'PY'
import os
import select
import socket
import sys
import termios
import tty

ESCAPE = 0x1D  # Ctrl-], the same escape socat's raw mode uses above


def main() -> int:
    sock = socket.socket(socket.AF_UNIX)
    sock.connect(sys.argv[1])
    # This script is itself the heredoc handed to "python3 -", so its own stdin is that
    # heredoc, not the terminal console.sh is attached to: sys.stdin is already at EOF by
    # the time main() runs, and tcgetattr on it fails with ENOTTY. /dev/tty is the
    # controlling terminal regardless of what stdin was redirected to get the script here.
    tty_fd = os.open("/dev/tty", os.O_RDWR)
    old = termios.tcgetattr(tty_fd)
    tty.setraw(tty_fd)
    try:
        while True:
            readable, _, _ = select.select([sock, tty_fd], [], [])
            if sock in readable:
                data = sock.recv(65536)
                if not data:
                    return 0
                os.write(tty_fd, data)
            if tty_fd in readable:
                data = os.read(tty_fd, 4096)
                if not data or ESCAPE in data:
                    return 0
                sock.sendall(data)
    finally:
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, old)
        os.close(tty_fd)


if __name__ == "__main__":
    sys.exit(main())
PY
else
  die "neither socat nor python3 found on the host"
fi

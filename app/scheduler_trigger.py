"""Cron 시각에 scheduler manager로 작업 key를 전달하는 작은 client."""

import os
import socket
import sys

SOCKET_PATH = os.path.join("/run", "task-ticket-scheduler.sock")


def main() -> int:
    """Cron 항목의 작업 key를 실행 환경을 보유한 manager에 전달한다."""
    if len(sys.argv) != 3:
        return 2
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(SOCKET_PATH)
        connection.sendall(f"{sys.argv[1]} {sys.argv[2]}\n".encode("ascii"))
        return 0 if connection.recv(16) == b"accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())

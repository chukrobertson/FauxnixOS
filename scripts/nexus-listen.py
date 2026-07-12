#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import sys

SOCKET_DIR = "/run/nexus"


def listen_thread(thread_name: str) -> None:
    sock_path = os.path.join(SOCKET_DIR, f"{thread_name}.sock")

    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    os.chmod(sock_path, 0o666)
    server.listen(5)

    print(f"[nexus] listening on {sock_path}")
    print(f"[nexus] waiting for activity from '{thread_name}'...")
    print()

    try:
        while True:
            conn, addr = server.accept()
            try:
                data = conn.recv(4096)
                if data:
                    for line in data.decode().strip().split("\n"):
                        if line:
                            event = json.loads(line)
                            src = event.get("src", "?")
                            ts = event.get("ts", "")[-12:-5]
                            if src == "window":
                                d = event["data"]
                                print(f"  [{ts}] WINDOW  {d.get('app', '?')}: {d.get('title', '?')[:60]}")
                            elif src == "file":
                                d = event["data"]
                                print(f"  [{ts}] FILE    {d.get('action', '?')} {d.get('path', '?')[:60]}")
                            elif src == "git":
                                d = event["data"]
                                print(f"  [{ts}] GIT     {d.get('action', '?')} on {d.get('branch', '?')}: {d.get('msg', '?')[:50]}")
                            elif src == "terminal":
                                d = event["data"]
                                print(f"  [{ts}] SHELL   {d.get('cmd', '?')[:60]}")
                            elif src == "browser":
                                d = event["data"]
                                print(f"  [{ts}] WEB     {d.get('domain', '?')} - {d.get('title', '?')[:50]}")
                            elif src == "idle":
                                d = event["data"]
                                print(f"  [{ts}] IDLE    {d.get('state', '?')} ({d.get('seconds', 0)}s)")
                            elif src == "system":
                                d = event["data"]
                                print(f"  [{ts}] SYSTEM  cpu:{d.get('cpu', '?')}% mem:{d.get('mem', '?')}%")
                            else:
                                print(f"  [{ts}] {src:8} {json.dumps(event['data'])[:80]}")
            finally:
                conn.close()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass

    print("\n[nexus] stopped")


if __name__ == "__main__":
    thread = sys.argv[1] if len(sys.argv) > 1 else "test-thread"
    listen_thread(thread)

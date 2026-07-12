#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import sys

DISPATCH_SOCK = "/run/nexus/dispatch.sock"


def listen_dispatch() -> None:
    try:
        os.unlink(DISPATCH_SOCK)
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(DISPATCH_SOCK)
    os.chmod(DISPATCH_SOCK, 0o666)
    server.listen(16)

    print(f"[nexus-listen] dispatch socket on {DISPATCH_SOCK}")
    print(f"[nexus-listen] waiting for events...")

    try:
        while True:
            conn, _ = server.accept()
            try:
                conn.settimeout(2)
                buf = b""
                try:
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                except socket.timeout:
                    pass

                for line in buf.decode().strip().split("\n"):
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        thread = event.get("thread", "?")
                        src = event.get("src", "?")
                        ts = event.get("ts", "")[:19]
                        data = event.get("data", {})

                        if src == "window":
                            print(f"  [{ts}] {thread:12} WINDOW  {data.get('app', '?')}: {data.get('title', '?')[:50]}")
                        elif src == "file":
                            print(f"  [{ts}] {thread:12} FILE    {data.get('action', '?')} {data.get('path', '?')[:50]}")
                        elif src == "git":
                            print(f"  [{ts}] {thread:12} GIT     {data.get('action', '?')} on {data.get('branch', '?')}: {data.get('msg', '?')[:50]}")
                        elif src == "terminal":
                            print(f"  [{ts}] {thread:12} SHELL   {data.get('cmd', '?')[:60]}")
                        elif src == "browser":
                            print(f"  [{ts}] {thread:12} WEB     {data.get('domain', '?')} - {data.get('title', '?')[:50]}")
                        elif src == "idle":
                            print(f"  [{ts}] {thread:12} IDLE    {data.get('state', '?')} ({data.get('seconds', 0)}s)")
                        elif src == "system":
                            print(f"  [{ts}] {thread:12} SYSTEM  cpu:{data.get('cpu', '?')}% mem:{data.get('mem', '?')}%")
                        else:
                            print(f"  [{ts}] {thread:12} {src:8} {json.dumps(data)[:60]}")
                    except json.JSONDecodeError:
                        pass
            finally:
                conn.close()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        try:
            os.unlink(DISPATCH_SOCK)
        except FileNotFoundError:
            pass

    print("\n[nexus-listen] stopped")


if __name__ == "__main__":
    listen_dispatch()

#!/usr/bin/env python3
"""Tiny TCP proxy from the Tailscale IP to the localhost-only exam calendar.

This keeps the actual app bound to 127.0.0.1 while allowing tailnet devices
access through the VPS's private Tailscale address only.
"""

import asyncio
import os
import signal

BIND_HOST = os.environ.get("TAILSCALE_PROXY_BIND", "100.118.207.80")
BIND_PORT = int(os.environ.get("TAILSCALE_PROXY_PORT", "8765"))
TARGET_HOST = os.environ.get("TAILSCALE_PROXY_TARGET_HOST", "127.0.0.1")
TARGET_PORT = int(os.environ.get("TAILSCALE_PROXY_TARGET_PORT", "8765"))


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
    try:
        target_reader, target_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
    except Exception:
        client_writer.close()
        await client_writer.wait_closed()
        return

    await asyncio.gather(
        pipe(client_reader, target_writer),
        pipe(target_reader, client_writer),
        return_exceptions=True,
    )


async def main() -> None:
    server = await asyncio.start_server(handle_client, BIND_HOST, BIND_PORT)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"proxy listening on {sockets}, forwarding to {TARGET_HOST}:{TARGET_PORT}", flush=True)

    async with server:
        await stop.wait()
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())

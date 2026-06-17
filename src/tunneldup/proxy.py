"""Asyncio TCP forwarder used on the remote to satisfy pymobiledevice3's
hardcoded TUNNELD_DEFAULT_ADDRESS=('127.0.0.1', 49151)."""

import asyncio
import contextlib
import sys


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Forward bytes from reader to writer; on EOF, half-close (write_eof)
    so the peer's response side stays open for the other pump direction."""
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
        if writer.can_write_eof():
            with contextlib.suppress(OSError):
                writer.write_eof()
    except (ConnectionResetError, BrokenPipeError):
        pass


async def _handle(client_r, client_w, dst_host: str, dst_port: int) -> None:
    try:
        up_r, up_w = await asyncio.open_connection(dst_host, dst_port)
    except OSError as e:
        print(f"[proxy] upstream {dst_host}:{dst_port} unreachable: {e}", file=sys.stderr)
        client_w.close()
        return
    try:
        await asyncio.gather(_pump(client_r, up_w), _pump(up_r, client_w))
    finally:
        for w in (up_w, client_w):
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass


async def serve_forwarder(listen_host: str, listen_port: int, dst_host: str, dst_port: int) -> asyncio.AbstractServer:
    return await asyncio.start_server(
        lambda r, w: _handle(r, w, dst_host, dst_port),
        listen_host,
        listen_port,
    )

import asyncio

import pytest

from tunneldup.proxy import serve_forwarder


async def _echo_server(host: str, port: int) -> asyncio.AbstractServer:
    async def handle(r, w):
        data = await r.read(8192)
        w.write(b"ECHO:" + data)
        await w.drain()
        w.close()

    return await asyncio.start_server(handle, host, port)


@pytest.mark.asyncio
async def test_forwarder_relays_bytes():
    upstream = await _echo_server("127.0.0.1", 0)
    up_host, up_port = upstream.sockets[0].getsockname()[:2]

    fwd = await serve_forwarder("127.0.0.1", 0, up_host, up_port)
    fwd_host, fwd_port = fwd.sockets[0].getsockname()[:2]

    async def run_client():
        r, w = await asyncio.open_connection(fwd_host, fwd_port)
        w.write(b"hello")
        await w.drain()
        w.write_eof()
        data = await r.read(8192)
        w.close()
        return data

    received = await asyncio.wait_for(run_client(), timeout=3)
    assert received == b"ECHO:hello"

    fwd.close()
    await fwd.wait_closed()
    upstream.close()
    await upstream.wait_closed()


@pytest.mark.asyncio
async def test_forwarder_handles_upstream_unreachable():
    fwd = await serve_forwarder("127.0.0.1", 0, "127.0.0.1", 1)  # port 1 -> connection refused
    fwd_host, fwd_port = fwd.sockets[0].getsockname()[:2]
    r, w = await asyncio.open_connection(fwd_host, fwd_port)
    w.write(b"x")
    await w.drain()
    data = await r.read(1024)
    w.close()
    assert data == b""
    fwd.close()
    await fwd.wait_closed()

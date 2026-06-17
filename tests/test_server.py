import asyncio
import socket

import pytest

from tunneldup import server


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.asyncio
async def test_tunneld_bridge_forwards_to_loopback():
    """Simulate the host wiring: real tunneld bound on 127.0.0.1, bridge on
    another loopback port. Client hits the bridge port and gets the tunneld
    response."""
    upstream_port = _free_port()
    bridge_port = _free_port()

    async def fake_tunneld(reader, writer):
        await reader.read(4096)
        body = b'{"udid":"abc"}'
        writer.write(
            b"HTTP/1.0 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        await writer.drain()
        writer.close()

    upstream = await asyncio.start_server(fake_tunneld, "127.0.0.1", upstream_port)

    t = server.start_tunneld_bridge(
        listen_host="127.0.0.1",
        listen_port=bridge_port,
        dst_host="127.0.0.1",
        dst_port=upstream_port,
    )
    assert t.is_alive()
    await asyncio.sleep(0.2)

    r, w = await asyncio.open_connection("127.0.0.1", bridge_port)
    w.write(b"GET / HTTP/1.0\r\nHost: x\r\n\r\n")
    await w.drain()
    data = await asyncio.wait_for(r.read(4096), timeout=2)
    w.close()
    assert b"HTTP/1.0 200 OK" in data
    assert b'"udid":"abc"' in data

    upstream.close()
    await upstream.wait_closed()

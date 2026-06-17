"""Host-side orchestration: WG up + tunneld bridge.

tunneldup does NOT start tunneld itself. You run
`sudo pymobiledevice3 remote tunneld` separately (default bind 127.0.0.1:49151),
and tunneldup bridges 10.42.0.1:49151 -> 127.0.0.1:49151 so the remote can
query it over WireGuard without you re-binding tunneld.
"""

import asyncio
import threading
from pathlib import Path
from typing import Optional

from tunneldup import proxy, wg, wgconf
from tunneldup.paths import (
    CLIENT_CONF,
    SERVER_CONF,
    SERVER_TUNNELD_IP,
    TUNNELD_PORT,
)


def setup_host(endpoint: Optional[str] = None) -> Path:
    """Generate (or load) keys, write configs, bring up the WG server."""
    wg.require_tools()
    wg.require_root()
    keys = wgconf.load_or_init_keys()
    ep = endpoint or wg.detect_public_endpoint()
    wgconf.write_configs(keys, ep)
    wg.down(SERVER_CONF)
    wg.up(SERVER_CONF)
    return CLIENT_CONF


def start_tunneld_bridge(
    listen_host: str = SERVER_TUNNELD_IP,
    listen_port: int = TUNNELD_PORT,
    dst_host: str = "127.0.0.1",
    dst_port: int = TUNNELD_PORT,
    bind_timeout: float = 3.0,
) -> threading.Thread:
    """Forward listen_host:listen_port -> dst_host:dst_port in a daemon thread.
    Raises RuntimeError if the listener can't bind (e.g. WG not up, port busy)."""
    ready = threading.Event()
    bind_error: list[BaseException] = []

    def _run() -> None:
        async def _main() -> None:
            try:
                srv = await proxy.serve_forwarder(listen_host, listen_port, dst_host, dst_port)
            except OSError as e:
                bind_error.append(e)
                ready.set()
                return
            ready.set()
            async with srv:
                await srv.serve_forever()

        asyncio.run(_main())

    t = threading.Thread(
        target=_run,
        name=f"tunneld-bridge:{listen_host}:{listen_port}",
        daemon=True,
    )
    t.start()
    if not ready.wait(bind_timeout):
        raise RuntimeError(f"tunneld bridge did not start within {bind_timeout}s")
    if bind_error:
        raise RuntimeError(
            f"tunneld bridge failed to bind {listen_host}:{listen_port}: {bind_error[0]}; "
            "check that WireGuard is up and no other process is using the port"
        )
    return t


def teardown_host() -> None:
    wg.down(SERVER_CONF)

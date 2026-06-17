"""End-to-end: stand up a 'host' tunneld carrying a fake device, stand up
a 'local' tunneld, use tunneldup.client to register the host as upstream,
verify the device appears on the local listing, and that deregister removes it."""

import socket
import threading
import time

import pytest
import requests
from pymobiledevice3.tunneld.server import TunneldRunner


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _start(host: str, port: int) -> threading.Thread:
    t = threading.Thread(
        target=lambda: TunneldRunner.create(
            host=host,
            port=port,
            usb_monitor=False,
            wifi_monitor=False,
            usbmux_monitor=False,
            mobdev2_monitor=False,
        ),
        daemon=True,
    )
    t.start()
    deadline = time.time() + 4
    while time.time() < deadline:
        try:
            requests.get(f"http://{host}:{port}/hello", timeout=0.2)
            return t
        except requests.RequestException:
            time.sleep(0.1)
    raise RuntimeError("tunneld did not come up")


@pytest.fixture(scope="module")
def two_tunnelds():
    host_port = _free_port()
    local_port = _free_port()
    _start("127.0.0.1", host_port)
    _start("127.0.0.1", local_port)
    yield host_port, local_port


def test_register_then_device_appears_on_local(two_tunnelds, monkeypatch):
    host_port, local_port = two_tunnelds
    host_url = f"http://127.0.0.1:{host_port}"
    local_url = f"http://127.0.0.1:{local_port}"

    # Inject a fake device into the "host" tunneld by patching _fetch_upstream
    # when the LOCAL tunneld calls into the host. To do that, we pretend the
    # local tunneld has an upstream of `host_url`, and inject the device by
    # patching the host's GET / via a request-level mock.
    # Simpler: register an upstream URL pointing at a stub that returns devices.
    import pymobiledevice3.tunneld.server as srv

    fake_devices = {"FAKE-UDID": [{"tunnel-address": "fd99::1", "tunnel-port": 9999, "interface": "test"}]}

    real_fetch = srv._fetch_upstream

    def fake_fetch(url: str):
        if url == host_url:
            return fake_devices
        return real_fetch(url)

    monkeypatch.setattr(srv, "_fetch_upstream", fake_fetch)

    # tunneldup.client points at the LOCAL tunneld and registers host_url as upstream.
    from tunneldup import client as clientmod

    clientmod.register_upstream(upstream_url=host_url, local_url=local_url)
    try:
        body = requests.get(f"{local_url}/").json()
        assert "FAKE-UDID" in body, body
        assert body["FAKE-UDID"][0]["tunnel-address"] == "fd99::1"
    finally:
        clientmod.deregister_upstream(upstream_url=host_url, local_url=local_url)

    body = requests.get(f"{local_url}/").json()
    assert "FAKE-UDID" not in body


def test_wait_for_tunneld_times_out_quickly_when_absent():
    from tunneldup import client as clientmod

    t0 = time.monotonic()
    ok = clientmod._wait_for_tunneld(local_url="http://127.0.0.1:1", timeout=1.5)
    assert ok is False
    assert time.monotonic() - t0 < 3.0

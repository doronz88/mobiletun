"""End-to-end test of pymobiledevice3's new /upstream REST API:
register -> appears in GET / -> deregister -> gone."""

import threading
import time
from unittest.mock import patch

import pytest
import requests


def _start_tunneld(host: str, port: int) -> threading.Thread:
    from pymobiledevice3.tunneld.server import TunneldRunner

    def _run():
        TunneldRunner.create(
            host=host,
            port=port,
            usb_monitor=False,
            wifi_monitor=False,
            usbmux_monitor=False,
            mobdev2_monitor=False,
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    for _ in range(40):
        try:
            requests.get(f"http://{host}:{port}/hello", timeout=0.2)
            return t
        except requests.RequestException:
            time.sleep(0.1)
    raise RuntimeError("tunneld didn't come up")


def _free_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def tunneld():
    port = _free_port()
    _start_tunneld("127.0.0.1", port)
    yield ("127.0.0.1", port)


def test_upstream_register_deregister(tunneld):
    host, port = tunneld
    base = f"http://{host}:{port}"

    # initially empty
    assert requests.get(f"{base}/upstream").json() == []

    # register two upstreams
    r = requests.post(f"{base}/upstream", json={"url": "http://10.42.0.1:49151"})
    assert r.status_code == 200
    r = requests.post(f"{base}/upstream", json={"url": "http://other:8080"})
    assert r.status_code == 200

    listed = requests.get(f"{base}/upstream").json()
    assert "http://10.42.0.1:49151" in listed
    assert "http://other:8080" in listed
    assert len(listed) == 2

    # idempotent re-add
    requests.post(f"{base}/upstream", json={"url": "http://10.42.0.1:49151"})
    assert len(requests.get(f"{base}/upstream").json()) == 2

    # deregister
    r = requests.delete(f"{base}/upstream", json={"url": "http://other:8080"})
    assert r.status_code == 200
    listed = requests.get(f"{base}/upstream").json()
    assert listed == ["http://10.42.0.1:49151"]

    # cleanup
    requests.delete(f"{base}/upstream", json={"url": "http://10.42.0.1:49151"})


def test_root_merges_upstream_devices(tunneld):
    host, port = tunneld
    base = f"http://{host}:{port}"

    # ensure clean state
    for u in requests.get(f"{base}/upstream").json():
        requests.delete(f"{base}/upstream", json={"url": u})

    fake_remote_devices = {
        "DEADBEEF-1": [
            {
                "tunnel-address": "fd99::1",
                "tunnel-port": 1234,
                "interface": "usbmux-DEADBEEF-1-USB",
            }
        ],
    }
    with patch("pymobiledevice3.tunneld.server._fetch_upstream", return_value=fake_remote_devices):
        requests.post(f"{base}/upstream", json={"url": "http://fake-host:49151"})
        body = requests.get(f"{base}/").json()
        assert "DEADBEEF-1" in body
        assert body["DEADBEEF-1"][0]["tunnel-address"] == "fd99::1"
        requests.delete(f"{base}/upstream", json={"url": "http://fake-host:49151"})


def test_root_tolerates_dead_upstream(tunneld):
    host, port = tunneld
    base = f"http://{host}:{port}"

    # register an unreachable upstream
    requests.post(f"{base}/upstream", json={"url": "http://127.0.0.1:1"})  # nothing listens on port 1
    # GET / must still return 200 (just an empty dict for our case)
    r = requests.get(f"{base}/", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
    requests.delete(f"{base}/upstream", json={"url": "http://127.0.0.1:1"})

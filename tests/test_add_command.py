"""Tests for `tunneldup add A` (run on B).

The command: bring up WG (so B can route to A's iPhone tunnel ULAs) + POST
`http://A:9246/tunneld` as an upstream of B's local tunneld, then hold until
Ctrl-C with full cleanup on exit (DELETE /upstream + WG down).
"""

import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests
from pymobiledevice3.tunneld.server import TunneldRunner
from typer.testing import CliRunner


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _start_tunneld(port: int) -> None:
    threading.Thread(
        target=lambda: TunneldRunner.create(
            host="127.0.0.1",
            port=port,
            usb_monitor=False,
            wifi_monitor=False,
            usbmux_monitor=False,
            mobdev2_monitor=False,
        ),
        daemon=True,
    ).start()
    deadline = time.time() + 4
    while time.time() < deadline:
        try:
            requests.get(f"http://127.0.0.1:{port}/hello", timeout=0.2)
            return
        except requests.RequestException:
            time.sleep(0.1)
    raise RuntimeError("tunneld did not come up")


@pytest.fixture(scope="module")
def b_tunneld():
    """Tunneld running on B (the machine running `tunneldup add`)."""
    port = _free_port()
    _start_tunneld(port)
    yield port


def _start_fake_a_web(devices_flat, tunneld_dict, wg_config_text) -> int:
    """Stand up a fake tunneldup-web on A serving /devices, /tunneld, /config."""
    import json

    port = _free_port()

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def _json(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _text(self, body):
            data = body.encode()
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/devices":
                self._json(devices_flat)
            elif self.path == "/tunneld":
                self._json(tunneld_dict)
            elif self.path == "/config":
                self._text(wg_config_text)
            else:
                (self.send_response(404), self.end_headers())

    srv = HTTPServer(("127.0.0.1", port), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return port


def test_parse_host_arg_variants():
    from tunneldup.upstreams import parse_host_arg

    assert parse_host_arg("1.2.3.4") == "http://1.2.3.4:49151"
    assert parse_host_arg("1.2.3.4", default_port=9246) == "http://1.2.3.4:9246"
    assert parse_host_arg("1.2.3.4:5000", default_port=9246) == "http://1.2.3.4:5000"
    assert parse_host_arg("http://host.tld:9000/") == "http://host.tld:9000"


def test_upstreams_and_remove(b_tunneld, monkeypatch):
    b_url = f"http://127.0.0.1:{b_tunneld}"

    from tunneldup import upstreams as upstreams_mod

    monkeypatch.setattr(upstreams_mod, "LOCAL_TUNNELD_URL", b_url)

    from tunneldup.cli import app

    runner = CliRunner()

    upstreams_mod.register("http://A.test:9246/tunneld")
    try:
        r = runner.invoke(app, ["upstreams"])
        assert r.exit_code == 0
        assert "A.test" in r.output

        r = runner.invoke(app, ["remove", "http://A.test:9246/tunneld"])
        assert r.exit_code == 0
        assert "deregistered" in r.output
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            upstreams_mod.unregister("http://A.test:9246/tunneld")


def test_add_full_lifecycle(b_tunneld, monkeypatch, tmp_path):
    """B runs `tunneldup add A`: fetches A's WG config, brings up WG (mocked),
    registers A's tunneld as upstream of B's local tunneld, fetches devices,
    waits, then cleans up everything on exit."""
    b_port = b_tunneld
    b_url = f"http://127.0.0.1:{b_port}"

    a_devices = [
        {
            "udid": "AABBCCDD-EEFF1122334455667788",
            "tunnel_address": "fd99::1",
            "tunnel_port": 1234,
            "interface": "usbmux-A-USB",
        }
    ]
    a_tunneld = {
        "AABBCCDD-EEFF1122334455667788": [
            {
                "tunnel-address": "fd99::1",
                "tunnel-port": 1234,
                "interface": "usbmux-A-USB",
            }
        ]
    }
    wg_config = "[Interface]\nPrivateKey = stub\nAddress = 10.42.0.2/32\n[Peer]\nPublicKey = stub\nEndpoint = 127.0.0.1:51820\nAllowedIPs = 10.42.0.0/24, fd00::/8\n"
    a_port = _start_fake_a_web(a_devices, a_tunneld, wg_config)
    expected_upstream = f"http://127.0.0.1:{a_port}/tunneld"

    from tunneldup import paths
    from tunneldup import upstreams as upstreams_mod

    monkeypatch.setattr(upstreams_mod, "LOCAL_TUNNELD_URL", b_url)
    fake_conf = tmp_path / "client.conf"
    monkeypatch.setattr(paths, "CLIENT_CONF", fake_conf)
    monkeypatch.setattr(paths, "ensure_cfg_dir", lambda: tmp_path.mkdir(exist_ok=True))

    # Mock everything that touches the real OS (WG, sudo).
    from tunneldup import wg

    monkeypatch.setattr(wg, "require_tools", lambda: None)
    monkeypatch.setattr(wg, "require_root", lambda: None)
    monkeypatch.setattr(wg, "up", lambda p: None)
    monkeypatch.setattr(wg, "down", lambda p: None)
    monkeypatch.setattr("tunneldup.client._wait_for_tunneld", lambda *a, **kw: True)

    # Use B's real tunneld as the "local" for the federation lookup the
    # CLI does to populate the picker.
    monkeypatch.setattr("tunneldup.client.LOCAL_TUNNELD_URL", b_url)

    # Replace signal.pause with a checkpoint that asserts upstream IS registered.
    seen = {"upstreams": None, "conf_written": False}

    def _checkpoint_and_interrupt(*_):
        try:
            seen["upstreams"] = requests.get(f"{b_url}/upstream", timeout=2).json()
        except Exception as e:
            seen["upstreams"] = f"<error: {e}>"
        seen["conf_written"] = fake_conf.exists() and fake_conf.read_text().startswith("[Interface]")
        raise KeyboardInterrupt

    monkeypatch.setattr(signal, "pause", _checkpoint_and_interrupt)

    from tunneldup.cli import app

    runner = CliRunner()
    r = runner.invoke(app, ["add", f"127.0.0.1:{a_port}", "--no-prompt"])
    assert r.exit_code == 0, r.output

    # WG conf was fetched and written into our tmp path (not the real home).
    assert seen["conf_written"], "client.conf should have been written from /config"
    # Upstream was active DURING the lifecycle.
    assert expected_upstream in (seen["upstreams"] or []), seen
    # Upstream is cleaned up AFTER exit (no stale tunnels).
    after = requests.get(f"{b_url}/upstream", timeout=2).json()
    assert expected_upstream not in after
    assert "deregistered" in r.output


def test_add_fails_clear_when_remote_unreachable(b_tunneld, monkeypatch):
    from tunneldup import upstreams as upstreams_mod
    from tunneldup import wg

    monkeypatch.setattr(upstreams_mod, "LOCAL_TUNNELD_URL", f"http://127.0.0.1:{b_tunneld}")
    monkeypatch.setattr(wg, "require_tools", lambda: None)
    monkeypatch.setattr(wg, "require_root", lambda: None)
    from tunneldup.cli import app

    runner = CliRunner()
    r = runner.invoke(app, ["add", "127.0.0.1:1"])
    assert r.exit_code == 2, r.output
    assert "could not reach" in r.output.lower()

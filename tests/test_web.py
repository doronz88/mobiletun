from unittest.mock import patch

from fastapi.testclient import TestClient

from tunneldup.web import build_app


def test_index_html():
    client = TestClient(build_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "tunneldup" in r.text.lower()


def test_devices_endpoint_flattens_tunneld_response():
    fake_tunneld_payload = {
        "00008150-001074523440401C": [
            {
                "tunnel-address": "fd97:a812:1d5a::1",
                "tunnel-port": 54747,
                "interface": "usbmux-00008150-001074523440401C-USB",
            }
        ],
    }
    with patch("tunneldup.web._fetch_tunneld", return_value=(fake_tunneld_payload, None)):
        client = TestClient(build_app())
        r = client.get("/devices")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["udid"] == "00008150-001074523440401C"
        assert body[0]["tunnel_address"] == "fd97:a812:1d5a::1"
        assert body[0]["tunnel_port"] == 54747
        assert "usbmux" in body[0]["interface"]


def test_devices_endpoint_returns_503_when_tunneld_down():
    with patch("tunneldup.web._fetch_tunneld", return_value=(None, "ConnectionError: ...")):
        client = TestClient(build_app())
        r = client.get("/devices")
        assert r.status_code == 503
        assert "tunneld" in r.json()["_error"]


def test_config_endpoint_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("TUNNELDUP_DIR", str(tmp_path / "absent"))
    import importlib

    import tunneldup.paths
    import tunneldup.web

    importlib.reload(tunneldup.paths)
    importlib.reload(tunneldup.web)
    client = TestClient(tunneldup.web.build_app())
    r = client.get("/config")
    assert r.status_code == 404


def test_exec_endpoint_runs_pmd3():
    async def _to_thread(fn, *args, **kwargs):
        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    with patch("asyncio.to_thread", _to_thread):
        client = TestClient(build_app())
        r = client.post("/exec", json={"args": ["--help"]})
        assert r.status_code == 200
        body = r.json()
        assert body["cmd"][0] == "pymobiledevice3"
        assert body["returncode"] == 0

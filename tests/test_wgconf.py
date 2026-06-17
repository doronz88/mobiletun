import json
import os
import shutil
from pathlib import Path

import pytest

# Override config dir before importing the modules under test.
TMP_HOME = Path(__file__).parent / "_tmp_cfg"
os.environ["TUNNELDUP_DIR"] = str(TMP_HOME)


@pytest.fixture(autouse=True)
def _clean_cfg(tmp_path, monkeypatch):
    d = tmp_path / "mtcfg"
    monkeypatch.setenv("TUNNELDUP_DIR", str(d))
    # Reload modules so they pick up the new env.
    import importlib

    import tunneldup.paths as p

    importlib.reload(p)
    yield
    if TMP_HOME.exists():
        shutil.rmtree(TMP_HOME, ignore_errors=True)


def test_render_server_conf_contains_keys_and_addresses():
    from tunneldup.wgconf import KeyPair, Keys, render_server_conf

    keys = Keys(server=KeyPair("S_PRIV_KEY", "S_PUB_KEY"), client=KeyPair("C_PRIV_KEY", "C_PUB_KEY"))
    conf = render_server_conf(keys)
    assert "PrivateKey = S_PRIV_KEY" in conf
    assert "PublicKey  = C_PUB_KEY" in conf
    assert "10.42.0.1/24" in conf
    assert "fdaa:1234::1/64" in conf
    assert "ListenPort = 51820" in conf


def test_render_client_conf_includes_endpoint_and_routes():
    from tunneldup.wgconf import KeyPair, Keys, render_client_conf

    keys = Keys(server=KeyPair("S_PRIV", "S_PUB"), client=KeyPair("C_PRIV", "C_PUB"))
    conf = render_client_conf(keys, endpoint="example.org")
    assert "Endpoint   = example.org:51820" in conf
    assert "PublicKey  = S_PUB" in conf
    # AllowedIPs covers the WG net plus fd00::/8 so the remote can route
    # to the per-device iPhone tunnel ULAs that pymobile's tunneld allocates.
    assert "10.42.0.0/24" in conf
    assert "fdaa:1234::/64" in conf
    assert "fd00::/8" in conf
    assert "PersistentKeepalive" in conf


def test_load_or_init_keys_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("TUNNELDUP_DIR", str(tmp_path / "kp"))
    import importlib

    import tunneldup.paths

    importlib.reload(tunneldup.paths)
    import tunneldup.wgconf

    importlib.reload(tunneldup.wgconf)

    if shutil.which("wg") is None:
        pytest.skip("wg not installed; cannot generate real keys")

    k1 = tunneldup.wgconf.load_or_init_keys()
    k2 = tunneldup.wgconf.load_or_init_keys()
    assert k1.server.private == k2.server.private
    assert k1.client.public == k2.client.public
    meta = json.loads(tunneldup.paths.META.read_text())
    assert set(meta.keys()) >= {"server_priv", "server_pub", "client_priv", "client_pub"}

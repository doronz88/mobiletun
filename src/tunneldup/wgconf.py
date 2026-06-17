"""WireGuard keypair + config-file generation. No filesystem ops on import."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

from tunneldup.paths import (
    CLIENT_CONF,
    META,
    SERVER_CONF,
    WG_CLIENT4,
    WG_CLIENT6,
    WG_NET4,
    WG_NET6,
    WG_PORT,
    WG_SERVER4,
    WG_SERVER6,
    ensure_cfg_dir,
)


@dataclass(frozen=True)
class KeyPair:
    private: str
    public: str


@dataclass(frozen=True)
class Keys:
    server: KeyPair
    client: KeyPair


def _have_wg() -> bool:
    return shutil.which("wg") is not None


def _gen_keypair() -> KeyPair:
    priv = subprocess.run(["wg", "genkey"], check=True, capture_output=True, text=True).stdout.strip()
    pub = subprocess.run(["wg", "pubkey"], check=True, capture_output=True, text=True, input=priv).stdout.strip()
    return KeyPair(private=priv, public=pub)


def load_or_init_keys() -> Keys:
    ensure_cfg_dir()
    if META.exists():
        d = json.loads(META.read_text())
        return Keys(
            server=KeyPair(d["server_priv"], d["server_pub"]),
            client=KeyPair(d["client_priv"], d["client_pub"]),
        )
    if not _have_wg():
        raise RuntimeError("missing `wg` (wireguard-tools); install with: brew install wireguard-tools wireguard-go")
    s = _gen_keypair()
    c = _gen_keypair()
    META.write_text(
        json.dumps(
            {
                "server_priv": s.private,
                "server_pub": s.public,
                "client_priv": c.private,
                "client_pub": c.public,
            },
            indent=2,
        )
    )
    META.chmod(0o600)
    return Keys(server=s, client=c)


def render_server_conf(keys: Keys) -> str:
    return dedent(f"""\
        [Interface]
        PrivateKey = {keys.server.private}
        Address    = {WG_SERVER4}, {WG_SERVER6}
        ListenPort = {WG_PORT}

        [Peer]
        PublicKey  = {keys.client.public}
        AllowedIPs = {WG_CLIENT4}, {WG_CLIENT6}
    """)


def render_client_conf(keys: Keys, endpoint: str) -> str:
    # fd00::/8 covers the iPhone-tunnel ULA prefixes that pymobile's
    # tunneld allocates per device. Without this the remote can federate
    # the device LISTING but can't TCP-connect to the per-device tunnel
    # address, so pymobile commands fail.
    return dedent(f"""\
        [Interface]
        PrivateKey = {keys.client.private}
        Address    = {WG_CLIENT4}, {WG_CLIENT6}

        [Peer]
        PublicKey  = {keys.server.public}
        Endpoint   = {endpoint}:{WG_PORT}
        AllowedIPs = {WG_NET4}, {WG_NET6}, fd00::/8
        PersistentKeepalive = 25
    """)


def write_configs(keys: Keys, endpoint: str) -> tuple[Path, Path]:
    ensure_cfg_dir()
    SERVER_CONF.write_text(render_server_conf(keys))
    SERVER_CONF.chmod(0o600)
    CLIENT_CONF.write_text(render_client_conf(keys, endpoint))
    CLIENT_CONF.chmod(0o600)
    return SERVER_CONF, CLIENT_CONF

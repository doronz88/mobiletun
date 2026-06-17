import ipaddress
import os
from pathlib import Path

CFG_DIR = Path(os.environ.get("TUNNELDUP_DIR", Path.home() / ".config" / "tunneldup"))
META = CFG_DIR / "meta.json"
SERVER_CONF = CFG_DIR / "server.conf"
CLIENT_CONF = CFG_DIR / "client.conf"

WG_NET4 = ipaddress.ip_network("10.42.0.0/24")
WG_SERVER4 = "10.42.0.1/24"
WG_CLIENT4 = "10.42.0.2/32"
WG_NET6 = ipaddress.ip_network("fdaa:1234::/64")
WG_SERVER6 = "fdaa:1234::1/64"
WG_CLIENT6 = "fdaa:1234::2/128"
WG_PORT = 51820

TUNNELD_PORT = 49151
# Distinct port for tunneldup's web UI / control plane. Avoids the
# common 8000/8080 collisions with whatever else the user runs.
WEB_PORT = 9246

SERVER_TUNNELD_IP = str(ipaddress.ip_interface(WG_SERVER4).ip)
SERVER_WEB_IP = SERVER_TUNNELD_IP


def ensure_cfg_dir() -> None:
    CFG_DIR.mkdir(parents=True, exist_ok=True)

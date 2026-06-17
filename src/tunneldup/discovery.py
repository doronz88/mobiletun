"""Discover USB-connected iPhones via pymobiledevice3's bonjour module."""

import asyncio
from dataclasses import dataclass

from pymobiledevice3.bonjour import browse_remoted
from pymobiledevice3.exceptions import AccessDeniedError
from pymobiledevice3.remote.remote_service_discovery import RSD_PORT, RemoteServiceDiscoveryService
from pymobiledevice3.remote.utils import stop_remoted


class DiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class Device:
    udid: str
    address: str  # link-local IPv6 with %iface scope
    iface: str  # e.g. en10
    rsd_port: int
    product_type: str
    product_version: str


async def discover_async(timeout: float = 3.0) -> list[Device]:
    """Find iPhones reachable over USB-NCM. Mirrors tunneld's logic.
    On macOS, suspending the system `remoted` requires root."""
    results: list[Device] = []
    seen_udids: set[str] = set()
    try:
        with stop_remoted():
            answers = await browse_remoted(timeout=timeout)
            for answer in answers:
                for address in answer.addresses:
                    if not address.iface or address.iface.startswith("utun"):
                        continue
                    rsd = RemoteServiceDiscoveryService((address.full_ip, RSD_PORT))
                    try:
                        await rsd.connect()
                    except Exception:
                        continue
                    try:
                        if rsd.udid in seen_udids:
                            continue
                        seen_udids.add(rsd.udid)
                        results.append(
                            Device(
                                udid=rsd.udid,
                                address=address.full_ip,
                                iface=address.iface,
                                rsd_port=RSD_PORT,
                                product_type=getattr(rsd, "product_type", "") or "",
                                product_version=getattr(rsd, "product_version", "") or "",
                            )
                        )
                    finally:
                        await rsd.close()
    except AccessDeniedError as e:
        raise DiscoveryError(
            "discovery needs root on macOS (sudo) to suspend the system `remoted` bonjour browser"
        ) from e
    return results


def discover(timeout: float = 3.0) -> list[Device]:
    return asyncio.run(discover_async(timeout=timeout))

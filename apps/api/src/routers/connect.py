"""Phone access — QR code so ARIA opens on a phone without typing an IP.

The friction this removes: the PC's LAN address changes whenever the router
reassigns it, so any written-down URL goes stale. This endpoint discovers the
current address at request time and renders it as a scannable QR.

Public (no auth): it exposes only a private-network address, which anyone on
that network can already discover, and the login page still gates the app
when ARIA_PASSWORD is set.
"""

import io
import ipaddress
import socket

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter(prefix="/connect", tags=["connect"])

WEB_PORT = 3000


class ConnectInfo(BaseModel):
    lan_ip: str | None
    phone_url: str | None
    reason: str | None = None
    # Tailscale address, when this machine is on a tailnet. Unlike the LAN
    # address this one works from anywhere, so it is the more useful of the
    # two whenever it exists.
    tailscale_ip: str | None = None
    tailscale_url: str | None = None


def detect_lan_ip() -> str | None:
    """Best-effort private IPv4 address of this machine.

    Uses the "connect a UDP socket and read the local end" trick: no packets
    are sent, but the OS picks the interface it would actually route through
    — which correctly skips Docker/WSL virtual adapters that simple
    hostname lookups return.
    """
    candidates: list[str] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("10.255.255.255", 1))
            candidates.append(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except OSError:
        pass

    for addr in candidates:
        try:
            ip = ipaddress.IPv4Address(addr)
        except ipaddress.AddressValueError:
            continue
        if not ip.is_private or ip.is_loopback:
            continue
        # Skip Docker/WSL virtual ranges (172.16-31.x) — reachable from this
        # machine but not from a phone on the Wi-Fi.
        if addr.startswith("172."):
            continue
        return addr
    return None


def detect_tailscale_ip() -> str | None:
    """This machine's Tailscale address, if it is on a tailnet.

    Tailscale hands out addresses from 100.64.0.0/10 — the carrier-grade NAT
    block, which is deliberately NOT one of the RFC1918 private ranges. That
    is why it needs its own detection here and its own CORS entry in main.py.
    """
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            try:
                ip = ipaddress.IPv4Address(addr)
            except ipaddress.AddressValueError:
                continue
            if ip in ipaddress.IPv4Network("100.64.0.0/10"):
                return addr
    except OSError:
        pass
    return None


@router.get("", response_model=ConnectInfo)
def connect_info() -> ConnectInfo:
    tailscale = detect_tailscale_ip()
    ip = detect_lan_ip()

    if ip is None and tailscale is None:
        return ConnectInfo(
            lan_ip=None,
            phone_url=None,
            reason="No home-network address found — is this PC on Wi-Fi?",
        )
    return ConnectInfo(
        lan_ip=ip,
        phone_url=f"http://{ip}:{WEB_PORT}" if ip else None,
        tailscale_ip=tailscale,
        tailscale_url=f"http://{tailscale}:{WEB_PORT}" if tailscale else None,
    )


@router.get("/qr")
def connect_qr() -> Response:
    """SVG QR code of the phone URL. Rendered locally — the address is never
    sent to a third-party QR service."""
    ip = detect_lan_ip()
    if ip is None:
        raise HTTPException(503, "No home-network address found")

    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(f"http://{ip}:{WEB_PORT}")
    qr.make(fit=True)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)

    buffer = io.BytesIO()
    image.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},  # the IP can change
    )

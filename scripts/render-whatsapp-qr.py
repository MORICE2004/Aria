"""Show ARIA's WhatsApp pairing QR at a size a phone will actually scan.

`node sender.js` prints a QR in the terminal. On Windows that often will not
scan: the small renderer draws each module as a half-block character, and the
console font's aspect ratio squashes them just enough that a phone camera
refuses the code. The result looks like a broken pairing flow when the code
itself is fine.

This renders the same code as a real image, full size, in the browser.

    # terminal 1
    cd apps/wa-bridge && node sender.js

    # terminal 2, from the repo root
    apps/api/.venv/Scripts/python scripts/render-whatsapp-qr.py

WhatsApp rotates the pairing code roughly every 20 seconds, so this follows the
file the sender writes and re-renders when it changes; the page reloads itself.
Leave both running, scan when the page shows a code, and the sender prints
"Connected" the moment the phone accepts it.

No new dependency: `qrcode` is already installed in the API's environment,
where it renders the /connect page's QR — which is why this is a Python script
next to a Node bridge.

Nothing here talks to WhatsApp or to ARIA. It reads one local file and writes
one local HTML file.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

try:
    import qrcode
    import qrcode.image.svg
except ModuleNotFoundError:  # pragma: no cover - environment problem, not logic
    sys.exit(
        "qrcode is not importable. Run this with the API's interpreter:\n"
        "    apps/api/.venv/Scripts/python scripts/render-whatsapp-qr.py"
    )

# Written by apps/wa-bridge/sender.js each time WhatsApp issues a new code, and
# deleted when the device links.
QR_FILE = ROOT / "apps" / "wa-bridge" / "qr-current.txt"
PAGE = ROOT / "apps" / "wa-bridge" / "qr-current.html"

# How often the page reloads. Comfortably shorter than WhatsApp's ~20 s
# rotation, so what is on screen is the code that is currently valid.
RELOAD_SECONDS = 4

_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="{reload}">
<title>Link ARIA's WhatsApp sender</title>
<style>
  body {{
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    background: #0b0f14; color: #e4e4e7;
    font: 15px/1.5 system-ui, -apple-system, Segoe UI, sans-serif;
  }}
  main {{ text-align: center; padding: 24px; }}
  /* QR codes need a light background and a quiet margin to scan reliably. */
  .plate {{
    background: #fff; padding: 20px; border-radius: 12px;
    display: inline-block; line-height: 0;
  }}
  .plate svg {{ width: min(78vw, 380px); height: auto; }}
  h1 {{ font-size: 17px; font-weight: 600; margin: 0 0 4px; }}
  p {{ margin: 6px 0 0; color: #a1a1aa; font-size: 13px; }}
  .steps {{ margin-top: 18px; font-size: 13px; color: #d4d4d8; }}
  .waiting {{ color: #fbbf24; }}
  .done {{ color: #34d399; }}
</style>
</head>
<body>
<main>
  <h1>Link ARIA's WhatsApp sender</h1>
  <p>Use the demo number, not your main one.</p>
  {body}
  <p class="steps">
    WhatsApp &rarr; Settings &rarr; Linked Devices &rarr; Link a Device
  </p>
  <p>This page refreshes every {reload}s. The code rotates about every 20s.</p>
</main>
</body>
</html>
"""


def render_page(payload: str | None, *, linked: bool) -> str:
    if linked:
        body = (
            '<p class="done" style="font-size:15px;margin-top:20px">'
            "Linked. The sender is connected — you can close this page and the "
            "second terminal.</p>"
        )
    elif payload is None:
        body = (
            '<p class="waiting" style="margin-top:20px">Waiting for a code from '
            "<code>node sender.js</code>…</p>"
        )
    else:
        qr = qrcode.QRCode(border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        buffer = io.BytesIO()
        qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(buffer)
        svg = buffer.getvalue().decode("utf-8")
        # Strip the XML declaration: it is invalid partway through an HTML body.
        if svg.startswith("<?xml"):
            svg = svg.split("?>", 1)[1].lstrip()
        body = f'<div class="plate">{svg}</div>'

    return _PAGE_TEMPLATE.format(reload=RELOAD_SECONDS, body=body)


def read_payload() -> str | None:
    try:
        text = QR_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return text or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-open", action="store_true", help="write the page but do not open it"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="render once and exit instead of following the rotating code",
    )
    args = parser.parse_args()

    print(f"  watching {QR_FILE}")
    print(f"  page     {PAGE}")

    # Whether a code has EVER appeared. Distinguishes "the sender has not
    # started yet" from "the device linked, so the file went away" — which look
    # identical if you only check whether the file exists.
    seen_a_code = False
    last_payload: str | None = object()  # sentinel: force a first render
    opened = False

    while True:
        payload = read_payload()
        linked = seen_a_code and payload is None
        if payload is not None:
            seen_a_code = True

        if payload != last_payload:
            PAGE.write_text(render_page(payload, linked=linked), encoding="utf-8")
            last_payload = payload
            if payload is not None:
                print(f"  new code rendered ({time.strftime('%H:%M:%S')})")
            elif linked:
                print("  device linked — sending is live. Nothing left to scan.")
            else:
                print("  no code yet; start `node sender.js` in another terminal")

        if not opened and not args.no_open:
            webbrowser.open(PAGE.as_uri())
            opened = True

        if args.once or linked:
            return 0

        time.sleep(1.0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  stopped")

"""Teach ARIA a writing voice from WhatsApp chat exports.

WhatsApp's "Export chat" (without media) gives thousands of messages MORICE
really sent — far better evidence than waiting for the bridge to observe
enough conversation.

Only HIS side is imported. The other person's messages are their voice, and
learning from them would teach ARIA to write like whoever he talks to most.

Usage, from the repo root:

    apps/api/.venv/Scripts/python scripts/import-whatsapp-export.py \\
        --sender "Morice Magnus" \\
        --password "<your ARIA password>" \\
        "C:/path/WhatsApp Chat with X.zip" ...

    # See what would be imported, without changing anything:
    ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

# Windows consoles default to cp1252, which cannot encode the emoji WhatsApp
# puts in contact names — printing a filename would crash the import after the
# parsing had already succeeded. Replace rather than fail: a garbled character
# in a progress line must never cost the import.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # pragma: no cover - non-standard stream
        pass

from src.communication.whatsapp_export import (  # noqa: E402
    own_messages,
    parse_export,
    senders,
)

# Enough for maximum confidence with room to spare: the confidence curve
# reaches its 0.95 cap at ~152 samples. Importing thousands would not make
# ARIA more certain, only slower, and would bloat the stored sample.
DEFAULT_LIMIT_PER_CHAT = 150


def read_chat_files(path: Path) -> list[tuple[str, str]]:
    """Chat text from a .zip or .txt. Returns (label, contents) pairs."""
    if path.suffix.lower() == ".txt":
        return [(path.stem, path.read_text(encoding="utf-8", errors="replace"))]

    out: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".txt"):
                continue
            raw = archive.read(name)
            out.append((path.stem, raw.decode("utf-8", errors="replace")))
    return out


def post(url: str, payload: dict, token: str) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def login(api: str, password: str) -> str:
    if not password:
        return ""
    request = urllib.request.Request(
        f"{api}/auth/login",
        data=json.dumps({"password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())["token"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exports", nargs="+", help=".zip or .txt chat exports")
    parser.add_argument(
        "--sender",
        help="Your name exactly as it appears in the export. "
        "Omitted: the script lists the senders it found and stops.",
    )
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--password", default="", help="ARIA password if auth is on")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT_PER_CHAT)
    parser.add_argument(
        "--dry-run", action="store_true", help="report only, import nothing"
    )
    args = parser.parse_args()

    collected: dict[str, list[str]] = {}
    for raw_path in args.exports:
        path = Path(raw_path)
        if not path.exists():
            print(f"  !! not found: {path}")
            continue

        for label, text in read_chat_files(path):
            messages = parse_export(text)
            counts = senders(messages)

            if not args.sender:
                print(f"\n{label}: senders found")
                for name, count in list(counts.items())[:5]:
                    print(f"    {name!r}  x{count}")
                continue

            if args.sender not in counts:
                print(f"  !! {label}: no messages from {args.sender!r}")
                print(f"     found: {list(counts)[:4]}")
                continue

            mine = own_messages(messages, args.sender, limit=args.limit)
            collected[label] = mine
            print(f"  {label}: {counts[args.sender]} of yours -> {len(mine)} usable")

    if not args.sender:
        print("\nRe-run with --sender \"<your name>\" to import.")
        return 0

    total = sum(len(v) for v in collected.values())
    if total == 0:
        print("\nNothing to import.")
        return 1

    print(f"\n{total} messages ready.")
    if args.dry_run:
        print("Dry run - nothing sent. Sample of what would be learned:")
        for label, msgs in collected.items():
            for body in msgs[:2]:
                print(f"    [{label}] {body[:70]}")
        return 0

    token = login(args.api, args.password)

    result = None
    for label, msgs in collected.items():
        try:
            result = post(
                f"{args.api}/style/samples",
                {"text": "\n".join(msgs), "label": f"WhatsApp export: {label}"},
                token,
            )
            print(f"  imported {result['added']} from {label}")
        except urllib.error.HTTPError as exc:
            print(f"  !! {label}: HTTP {exc.code} {exc.read()[:200]!r}")
            return 1

    if result:
        print(f"\nARIA now has {result['total_samples']} samples of your writing.")
        print(f"Voice confidence: {result['confidence']}")
        print(f"Ready for autonomous replies: {result['ready_for_autonomy']}")
        print(result["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

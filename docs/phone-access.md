# Using ARIA on your phone

ARIA runs on your PC. Your phone reaches it over your home Wi-Fi — so the PC
must be on, the servers running, and the phone on the SAME Wi-Fi network.

## One-time setup

1. **Open the firewall** (once): Start menu → type "PowerShell" → right-click →
   *Run as administrator*, then:
   ```powershell
   cd C:\Users\MORICE\projects\aria
   .\allow-phone.ps1
   ```
2. **Add your Gemini key**: get a free key at https://aistudio.google.com
   (→ "Get API key"), then open `C:\Users\MORICE\projects\aria\.env` and set:
   ```
   GEMINI_API_KEY=your-key-here
   ```
   (`LLM_PROVIDER=gemini` is already set.)

## Every time you want ARIA

Double-click **`start-aria.ps1`** (in the project folder). It starts the
databases, the API, and the dashboard, then prints two links:

- On this PC: `http://localhost:3000`
- On your phone: `http://<PC-IP>:3000`  (e.g. `http://10.0.91.189:3000`)

Open the phone link in your phone's browser. For an app-like experience,
use the browser menu → **Add to Home Screen** — ARIA gets its own icon.

## If the phone can't connect

- Same Wi-Fi? Phone and PC must be on the same network (not mobile data).
- Firewall: did you run `allow-phone.ps1` as admin?
- PC IP changed? Routers reassign addresses. Re-run `start-aria.ps1` — it
  prints the current IP. (To pin it, set a DHCP reservation in your router.)
- Servers running? The two PowerShell windows `start-aria.ps1` opened must
  stay open.

## Security note

Right now `ARIA_PASSWORD` is empty, so no login is required — fine on a
trusted home network. If others share your Wi-Fi, set `ARIA_PASSWORD` and
`SECRET_KEY` in `.env` (a SECRET_KEY was already generated for you) to require
a password. Using ARIA from OUTSIDE your home (mobile data, anywhere) needs
cloud hosting or a tunnel — a separate, later step.

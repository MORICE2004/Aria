# Using ARIA from another PC, or your phone

ARIA runs on one machine — the PC where the databases, the API, the dashboard
and the WhatsApp bridge live. Nothing here deploys her anywhere else. What these
options change is *how another device reaches that machine*.

| | Works from | Needs |
|---|---|---|
| **Home Wi-Fi** | the same network only | firewall opened once |
| **Tailscale** | anywhere with internet | Tailscale on both devices, one account |

Either way the ARIA PC must be **on and running** (`.\aria.ps1 start`). She is
not in the cloud; a sleeping PC is an unreachable ARIA.

---

## From anywhere: Tailscale

This is the one to use if you want ARIA from a second PC, from the office, or
from mobile data.

```powershell
.\aria.ps1 remote
```

It installs Tailscale if missing, signs this machine in, opens the firewall to
your own devices only, and prints the address to use.

Then, on the other PC or phone, once:

1. Install Tailscale: <https://tailscale.com/download>
2. Sign in with the **same account**
3. Open the address the script printed (`http://100.x.y.z:3000`)

### Why not just forward a port

ARIA holds WhatsApp credentials that can send messages as you, a memory of your
personal life, and an API that acts on your behalf. A forwarded port or a public
tunnel puts that on the open internet, where the only thing between a stranger
and ARIA is one password.

A tailnet is a private network between your own devices. There is no public
address, nothing is published, and a machine not signed into your account cannot
see ARIA at all. The CORS rules in `apps/api/src/main.py` already allow the
Tailscale range (`100.64.0.0/10`) and MagicDNS names, and `/connect` reports the
tailnet address when there is one — the support was built in; this just turns it
on.

---

## On the same Wi-Fi

Simpler, but only at home.

```powershell
.\aria.ps1 phone
```

Run that once **as Administrator** (Start menu → PowerShell → right-click → Run
as administrator). It opens ports 3000 and 8000 on private networks only.

Then `.\aria.ps1 start` prints the address, or `.\aria.ps1 status` shows it any
time. On the phone, use the browser menu → **Add to Home Screen** and ARIA gets
her own icon.

---

## Security, honestly

**Set `ARIA_PASSWORD` in `.env` before using ARIA off this machine.** Without
it, anyone who reaches her can read your memory and act as you — and ARIA
refuses to send autonomously at all, by design, when no password is set.

The password is what makes remote access safe; Tailscale is what makes it
private. They solve different problems and you want both.

---

## If it will not connect

- **Is ARIA running?** `.\aria.ps1 status` says what is up and what is not.
- **Is the PC awake?** Sleep ends every connection.
- **Tailscale on both ends?** Both devices must be signed into the same
  account. `tailscale status` lists what it can see.
- **Same Wi-Fi** (Wi-Fi option only) — a phone on mobile data is not on your
  network. That is exactly the case Tailscale solves.
- **Address changed?** Routers reassign LAN addresses; the tailnet address does
  not change, which is the other reason to prefer it.

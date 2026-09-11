import asyncio
import json
import subprocess
import time
import httpx

BASE_URL = "http://127.0.0.1:8000"
SECRET = "aria_ingest_2cf9c2e4b1fe6f046a5676f6464481d35925f125bce64cb2"
HEADERS = {"X-ARIA-Ingest-Secret": SECRET}
HANDLE = "commissioning-pilot@s.whatsapp.net"

async def test():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # Step 1: Ensure autonomy state
        await client.patch("/whatsapp/autonomy", json={"emergency_stop": False, "paused": False, "autonomy_stopped": False})
        await client.patch("/whatsapp/autonomy", json={"mode": "full_autonomy"})
        
        # Step 2: Ensure contact trust & policy
        r = await client.get("/whatsapp/contacts")
        c = next(x for x in r.json() if x["handle"] == HANDLE)
        cid = c["id"]
        await client.patch(f"/whatsapp/contacts/{cid}", json={
            "trust_level": "high",
            "autonomy_enabled": True,
            "allowed_actions": ["greeting", "routine_reply"],
            "paused": False,
            "taken_over": False
        })
        
        # Step 3: Ingest greeting
        msg_id = f"auto-drill-{int(time.time()*1000)}"
        r = await client.post("/whatsapp/ingest", headers=HEADERS, json={
            "handle": HANDLE,
            "name": "Pilot Commissioning Partner",
            "body": "Habari Morice, mzima wewe?",
            "direction": "in",
            "message_id": msg_id,
            "timestamp": int(time.time())
        })
        print("Ingest:", r.json())
        
        # Step 4: Wait for queue worker processing
        for i in range(20):
            await asyncio.sleep(1.0)
            qs = (await client.get("/whatsapp/queue")).json()
            print(f"Waiting queue... pending={qs['pending']}, processing={qs['processing']}")
            if qs["pending"] == 0 and qs["processing"] == 0:
                break
        
        # Step 5: Check autonomous response
        r_auto = await client.get("/whatsapp/autonomous?limit=3")
        autos = [a for a in r_auto.json() if a["contact_id"] == cid]
        print("Auto responses for contact:", len(autos))
        if autos:
            print("Latest Auto Response:", json.dumps(autos[0], indent=2))
        
        # Step 6: Check outbound queue
        r_out = await client.get("/whatsapp/outbound?limit=5")
        outs = [o for o in r_out.json() if o["handle"] == HANDLE]
        print("Outbound messages for contact:", len(outs))
        if outs:
            print("Latest Outbound Message:", json.dumps(outs[0], indent=2))
        
        # Step 7: Run dry-run sender
        proc = subprocess.run(["node", "apps/wa-bridge/sender.js", "--dry-run"], capture_output=True, text=True)
        print("Sender Dry Run STDOUT:\n", proc.stdout)
        if proc.stderr:
            print("Sender Dry Run STDERR:\n", proc.stderr)

asyncio.run(test())

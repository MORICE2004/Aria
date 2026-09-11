import sqlite3
con = sqlite3.connect("aria.db")
cur = con.cursor()
cur.execute("UPDATE inbound_messages SET status='done' WHERE status='processing'")
con.commit()
print("Cleaned rows:", cur.rowcount)
con.close()

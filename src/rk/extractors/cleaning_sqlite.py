import sqlite3

con = sqlite3.connect("data/richmond.db")
cur = con.cursor()

deleted = cur.execute("DELETE FROM events").rowcount
con.commit()
con.close()

print(f"Deleted ALL events ({deleted} rows)")

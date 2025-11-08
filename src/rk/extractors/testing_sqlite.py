import sqlite3
import pandas as pd

DB_PATH = "data/richmond.db"
OUTFILE = "events_dump.xlsx"

con = sqlite3.connect(DB_PATH)

# Load full table into pandas
df = pd.read_sql_query("SELECT * FROM events", con)

# Write to Excel
df.to_excel(OUTFILE, index=False)

print(f"✅ Exported {len(df)} rows to {OUTFILE}")

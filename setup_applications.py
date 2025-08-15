import sqlite3

conn = sqlite3.connect("data.db")
cursor = conn.cursor()

# Create basic applications table if not exists
cursor.execute("""
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    purpose TEXT,
    ticket_number TEXT UNIQUE,
    status TEXT DEFAULT 'Submitted',
    submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Ensure file columns exist
def column_exists(table, col):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in cursor.fetchall())

if not column_exists('applications', 'file_name'):
    cursor.execute("ALTER TABLE applications ADD COLUMN file_name TEXT")
if not column_exists('applications', 'file_data'):
    cursor.execute("ALTER TABLE applications ADD COLUMN file_data BLOB")

conn.commit()
conn.close()
print("Applications table ensured with file_name and file_data columns!")

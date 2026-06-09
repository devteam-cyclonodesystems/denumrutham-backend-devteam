import sqlite3

def main():
    conn = sqlite3.connect("tms_local_sqlite.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print("Tables:", tables)

if __name__ == "__main__":
    main()

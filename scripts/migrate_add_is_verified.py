"""Migration: Add is_verified field to kols and raw_contents tables"""
import sqlite3
import os

def migrate():
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ainsight_new.db")
    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if kols table has is_verified column
    cursor.execute("PRAGMA table_info(kols)")
    kol_columns = [col[1] for col in cursor.fetchall()]

    if "is_verified" not in kol_columns:
        print("Adding kols.is_verified column...")
        cursor.execute("ALTER TABLE kols ADD COLUMN is_verified BOOLEAN DEFAULT 0")
        print("[OK] kols.is_verified added")
    else:
        print("[OK] kols.is_verified exists")

    # Check if raw_contents table has is_verified column
    cursor.execute("PRAGMA table_info(raw_contents)")
    rc_columns = [col[1] for col in cursor.fetchall()]

    if "is_verified" not in rc_columns:
        print("Adding raw_contents.is_verified column...")
        cursor.execute("ALTER TABLE raw_contents ADD COLUMN is_verified BOOLEAN DEFAULT 0")
        print("[OK] raw_contents.is_verified added")
    else:
        print("[OK] raw_contents.is_verified exists")

    # Check if raw_contents table has author info columns
    author_columns = ["author_name", "author_handle", "author_avatar"]
    for col in author_columns:
        if col not in rc_columns:
            print(f"Adding raw_contents.{col} column...")
            cursor.execute(f"ALTER TABLE raw_contents ADD COLUMN {col} VARCHAR(500)")
            print(f"[OK] raw_contents.{col} added")
        else:
            print(f"[OK] raw_contents.{col} exists")

    conn.commit()
    conn.close()
    print("\nMigration completed!")

if __name__ == "__main__":
    migrate()

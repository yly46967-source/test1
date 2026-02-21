"""数据库迁移脚本 - 添加 RawContent 作者字段"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def migrate():
    """添加 author_name, author_handle, author_avatar 字段到 raw_contents 表"""
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ainsight.db")

    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查字段是否已存在
    cursor.execute("PRAGMA table_info(raw_contents)")
    columns = [col[1] for col in cursor.fetchall()]

    migrations = []

    if "author_name" not in columns:
        migrations.append("ALTER TABLE raw_contents ADD COLUMN author_name VARCHAR(100)")

    if "author_handle" not in columns:
        migrations.append("ALTER TABLE raw_contents ADD COLUMN author_handle VARCHAR(100)")

    if "author_avatar" not in columns:
        migrations.append("ALTER TABLE raw_contents ADD COLUMN author_avatar VARCHAR(500)")

    if not migrations:
        print("所有字段已存在，无需迁移")
        conn.close()
        return

    print(f"执行 {len(migrations)} 个迁移...")

    for sql in migrations:
        print(f"  执行: {sql}")
        cursor.execute(sql)

    conn.commit()
    conn.close()

    print("迁移完成!")


if __name__ == "__main__":
    migrate()

import sqlite3
from datetime import datetime

def init_db():
    conn = sqlite3.connect('inspection.db')
    c = conn.cursor()
    
    # 物品表
    c.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        location TEXT,
        check_items TEXT  -- JSON 字符串，如 ["外观","电源"]
    )''')

    # 检查记录表
    c.execute('''CREATE TABLE IF NOT EXISTS inspections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER,
        checked_by TEXT,
        results TEXT,      -- JSON: {"外观": true, "电源": false}
        remarks TEXT,
        timestamp TEXT,
        FOREIGN KEY(item_id) REFERENCES items(id)
    )''')

    conn.commit()
    conn.close()

# 初始化数据库
if __name__ == '__main__':
    init_db()
    print("Database initialized.")
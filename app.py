import os
import json
import uuid
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

# --- 数据库配置 ---
# Render 会在后台提供 DATABASE_URL 环境变量
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '123')

def get_db_connection():
    # 如果有云端数据库 URL，用 Postgres
    if os.getenv('DATABASE_URL'):
        return psycopg2.connect(os.getenv('DATABASE_URL'), sslmode='require')
    # 否则在本地运行，自动切换到 SQLite (方便调试)
    else:
        import sqlite3
        conn = sqlite3.connect('local_test.db')
        conn.row_factory = sqlite3.Row
        return conn
# --- 数据库初始化 ---
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    is_pg = os.getenv('DATABASE_URL') is not None
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT,
            check_items TEXT NOT NULL
        )
    ''')
    
    # 根据数据库类型选择自增语法
    id_type = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    
    cur.execute(f'''
        CREATE TABLE IF NOT EXISTS inspections (
            id {id_type},
            item_id TEXT NOT NULL,
            check_results TEXT NOT NULL,
            signature TEXT,
            inspected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_item FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()
# 只有在配置了数据库 URL 的情况下才初始化（防止本地报错）
if DATABASE_URL:
    init_db()

# --- 核心查询函数 ---
def query_db(query, args=(), one=False):
    conn = get_db_connection()
    is_pg = isinstance(conn, psycopg2.extensions.connection)
    
    if is_pg:
        # PostgreSQL 逻辑
        cur = conn.cursor(cursor_factory=RealDictCursor)
        formatted_query = query.replace('?', '%s')
    else:
        # SQLite 逻辑
        cur = conn.cursor()
        formatted_query = query # SQLite 原生支持 ?
        
    cur.execute(formatted_query, args)
    
    # 获取结果
    if cur.description:
        rv = cur.fetchall()
        # 将结果统一转为字典列表
        if is_pg:
            results = [dict(r) for r in rv]
        else:
            results = [dict(r) for r in rv]
    else:
        results = []
        
    conn.commit()
    cur.close()
    conn.close()
    
    if results:
        return (results[0] if one else results)
    return None if one else []
# --- 路由接口 (逻辑保持不变，底层已自动适配) ---

@app.route('/')
def serve_root():
    return "🚀 巡检系统服务已启动。请访问 /admin.html"

@app.route('/api/items', methods=['POST'])
def create_item():
    data = request.json
    name = data.get('name')
    location = data.get('location')
    check_items = data.get('checkItems')
    if not name or not isinstance(check_items, list):
        return jsonify({"error": "缺少必要字段"}), 400

    item_id = f"item_{int(time.time())}_{uuid.uuid4().hex[:5]}"
    query_db('INSERT INTO items (id, name, location, check_items) VALUES (?, ?, ?, ?)',
             (item_id, name, location, json.dumps(check_items)))
    
    return jsonify({"id": item_id, "name": name})

@app.route('/api/items/<id>', methods=['GET'])
def get_item(id):
    row = query_db('SELECT * FROM items WHERE id = ?', (id,), one=True)
    if not row: return jsonify({"error": "未找到"}), 404
    item = dict(row)
    item['check_items'] = json.loads(item['check_items'])
    return jsonify(item)

@app.route('/api/inspections', methods=['POST'])
def submit_inspection():
    data = request.json
    query_db('INSERT INTO inspections (item_id, check_results, signature) VALUES (?, ?, ?)',
             (data.get('item_id'), json.dumps(data.get('check_results')), data.get('signature')))
    return jsonify({"success": True})

@app.route('/api/reports/monthly', methods=['GET'])
def get_monthly_report():
    if request.args.get('pwd') != ADMIN_PASSWORD:
        return jsonify({"error": "Unauthorized"}), 403
    rows = query_db('SELECT * FROM items ORDER BY name')
    return jsonify([dict(r) for r in rows])

@app.route('/api/inspections/all', methods=['GET'])
def get_all_inspections():
    rows = query_db('SELECT * FROM inspections ORDER BY inspected_at DESC')
    return jsonify([dict(r) for r in rows])

@app.route('/api/inspections/<id>', methods=['GET'])
def get_inspection_detail(id):
    if id == "null" or not id:
        return jsonify({"error": "ID不能为空"}), 400
        
    # 尝试转数字以兼容 SQLite
    search_id = id
    try:
        search_id = int(id)
    except:
        pass

    row = query_db('SELECT * FROM inspections WHERE id = ?', (search_id,), one=True)
    if not row: 
        return jsonify({"error": "记录未找到"}), 404
    
    res = dict(row)
    if isinstance(res['check_results'], str):
        res['check_results'] = json.loads(res['check_results'])
    return jsonify(res)

@app.route('/api/items/<id>', methods=['DELETE'])
def delete_item(id):
    query_db('DELETE FROM items WHERE id = ?', (id,))
    return jsonify({"success": True})

# if __name__ == '__main__':
#     # 本地开发测试时，你需要手动设置一个本地或远程的 DATABASE_URL
#     app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 3000)))
if __name__ == '__main__':
    init_db()
    print(f"当前系统设定的管理员密码是: {ADMIN_PASSWORD}")
    PORT = 3000
    print(f"\n" + "="*40)
    print(f"✅ 服务已启动：http://localhost:{PORT}")
    print(f"📱 扫码页面示例：http://localhost:{PORT}/index.html?id=item_123")
    print(f"💻 管理后台：http://localhost:{PORT}/admin.html")
    print("="*40 + "\n")
    
    # debug=True 可以在修改代码后自动重启1
    app.run(host='0.0.0.0', port=PORT, debug=True)
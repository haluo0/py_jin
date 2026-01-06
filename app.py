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

DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '123')

# 1. 增加超时设置，解决锁定竞争
def get_db_connection():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        import sqlite3
        # timeout=20 表示如果数据库锁定了，它会等待20秒再报错，而不是立刻报错
        conn = sqlite3.connect('fire_safety.db', timeout=20)
        conn.row_factory = sqlite3.Row
        return conn

# 2. 优化查询逻辑，确保连接必关闭
def query_db(query, args=(), one=False):
    conn = get_db_connection()
    is_pg = os.getenv('DATABASE_URL') is not None
    
    try:
        if is_pg:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            formatted_query = query.replace('?', '%s')
        else:
            cur = conn.cursor()
            formatted_query = query
            
        cur.execute(formatted_query, args)
        
        rv = None
        if cur.description:
            rv = cur.fetchall()
            
        conn.commit() # 确保提交
        
        if rv:
            res = [dict(r) for r in rv]
            return (res[0] if one else res)
        return None if one else []
        
    except Exception as e:
        conn.rollback() # 出错时回滚
        raise e
    finally:
        cur.close() # 显式关闭游标
        conn.close() # 显式关闭连接，释放锁
# --- 数据库初始化 ---
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    is_pg = DATABASE_URL is not None
    id_type = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"

    # 1. 站点表
    cur.execute('''CREATE TABLE IF NOT EXISTS stations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        location TEXT
    )''')

    # 2. 设备表 (灭火器)
    cur.execute(f'''CREATE TABLE IF NOT EXISTS devices (
        id TEXT PRIMARY KEY,
        station_id TEXT NOT NULL,
        name TEXT NOT NULL,
        location TEXT,
        specs TEXT,
        expiry_date TEXT,
        check_items TEXT,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE
    )''')

    # 3. 巡检记录表
    cur.execute(f'''CREATE TABLE IF NOT EXISTS inspections (
        id {id_type},
        device_id TEXT NOT NULL,
        month_str TEXT NOT NULL, -- 格式如 '2026-01'
        check_results TEXT,
        signature TEXT,
        inspected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()


@app.route('/')
def serve_root():
    return "🚀 巡检系统服务已启动。请访问 /manage_stations.html"
# --- 接口 A：获取站点列表 (供前端页面展示列表使用) ---
@app.route('/api/stations_all', methods=['GET']) # 注意这里是 GET
def get_stations():
    try:
        stations = query_db('SELECT * FROM stations ORDER BY id DESC')
        return jsonify(stations) # 必须返回 JSON 列表
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# [管理后台] 创建站点
@app.route('/api/stations', methods=['POST'])
def create_station():
    data = request.json
    s_id = f"st_{int(time.time())}_{uuid.uuid4().hex[:4]}"
    try:
        query_db('INSERT INTO stations (id, name, location) VALUES (?, ?, ?)',
                 (s_id, data['name'], data.get('location', '')))
        return jsonify({"id": s_id})
    except Exception as e:
        print(f"数据库写入失败: {e}")
        return jsonify({"error": str(e)}), 500

# [管理后台] 为站点添加设备
@app.route('/api/stations/<s_id>/devices', methods=['POST'])
def add_device(s_id):
    data = request.json
    d_id = f"dev_{uuid.uuid4().hex[:8]}"
    query_db('''INSERT INTO devices (id, station_id, name, location, specs, expiry_date, check_items) 
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
             (d_id, s_id, data['name'], data['location'], data.get('specs',''), 
              data.get('expiry_date',''), json.dumps(data['check_items'])))
    return jsonify({"id": d_id})


# [管理后台] 获取某站点下的所有设备（用于管理页面）
@app.route('/api/stations/<s_id>/devices_all', methods=['GET'])
def get_station_devices(s_id):
    try:
        devices = query_db('SELECT * FROM devices WHERE station_id = ?', (s_id,))
        # 解析 check_items 为对象（如果需要展示，但这里只展示基本信息）
        for d in devices:
            d['check_items'] = json.loads(d['check_items']) if d.get('check_items') else []
        return jsonify(devices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# [管理后台] 删除站点（级联删除设备和巡检记录）
@app.route('/api/stations/<s_id>', methods=['DELETE'])
def delete_station(s_id):
    try:
        # SQLite 和 PostgreSQL 都支持 ON DELETE CASCADE，所以只需删站点
        query_db('DELETE FROM stations WHERE id = ?', (s_id,))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# [管理后台] 删除单个设备
@app.route('/api/devices/<d_id>', methods=['DELETE'])
def delete_device(d_id):
    try:
        query_db('DELETE FROM devices WHERE id = ?', (d_id,))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# [页面A] 获取站点下所有设备及指定月份的状态
@app.route('/api/stations/<s_id>/status/<month>')
def get_station_status(s_id, month):
    # 获取站点信息
    station = query_db('SELECT * FROM stations WHERE id = ?', (s_id,), one=True)
    # 获取该站所有设备
    devices = query_db('SELECT * FROM devices WHERE station_id = ?', (s_id,))
    # 获取该站该月的所有巡检记录
    records = query_db('''SELECT device_id, check_results FROM inspections 
                          WHERE device_id IN (SELECT id FROM devices WHERE station_id = ?) 
                          AND month_str = ?''', (s_id, month))
    
    # 建立查找表
    record_map = {r['device_id']: json.loads(r['check_results']) for r in records}
    
    for d in devices:
        d['check_items'] = json.loads(d['check_items'])
        d['this_month_status'] = record_map.get(d['id'], None) # None 表示未检

    return jsonify({"station": station, "devices": devices})

# [页面B] 获取设备详情及年度巡检统计
@app.route('/api/devices/<d_id>/history/<year>')
def get_device_history(d_id, year):
    device = query_db('SELECT * FROM devices WHERE id = ?', (d_id,), one=True)
    if not device: return jsonify({"error": "Not Found"}), 404
    
    device['check_items'] = json.loads(device['check_items'])
    
    # 获取该年度的所有记录
    pattern = f"{year}-%"
    records = query_db('SELECT month_str, check_results FROM inspections WHERE device_id = ? AND month_str LIKE ?',
                       (d_id, pattern))
    
    return jsonify({"device": device, "history": records})

# [页面B] 提交巡检记录
@app.route('/api/inspections', methods=['POST'])
def submit_inspection():
    data = request.json
    # month_str 格式 '2026-01'
    query_db('INSERT INTO inspections (device_id, month_str, check_results, signature) VALUES (?, ?, ?, ?)',
             (data['device_id'], data['month_str'], json.dumps(data['check_results']), data.get('signature')))
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
    
    # debug=True 可以在修改代码后自动重启
    app.run(host='0.0.0.0', port=PORT, debug=True)
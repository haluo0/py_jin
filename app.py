from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
import qrcode
import io
import base64
import json
from models import db, Item, Inspection
from sqlalchemy import cast, String
from qrcode.image.pil import PilImage 
app = Flask(__name__)

# Render 提供 DATABASE_URL 环境变量
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    # 👇 强制添加 SSL 模式（Render PostgreSQL 要求）
    if "?sslmode=" not in DATABASE_URL:
        DATABASE_URL += "?sslmode=require"
else:
    DATABASE_URL = 'sqlite:///inspection.db'

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,      # 每次取连接前 ping 一下，避免坏连接
    "pool_recycle": 300,        # 5分钟重建连接，防止长时间 idle 导致 SSL 失效
}
db.init_app(app)
# @app.before_first_request
# def create_tables():
#     db.create_all()
#     print("✅ 数据库表已初始化")
# 动态生成 Base64 二维码
def generate_qr_base64(url):
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PilImage, fill_color='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")  # ✅ 现在 safe！
    img_str = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"

@app.route('/')
def index():
    return redirect('/admin')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        name = request.form['name']
        location = request.form['location']
        check_items_raw = request.form['check_item'].strip()
        check_items = [x.strip() for x in check_items_raw.split('\n') if x.strip()]
        
        item = Item(name=name, location=location, check_items=json.dumps(check_items))
        db.session.add(item)
        db.session.commit()

        return redirect('/admin')

    items = Item.query.all()
    # 为每个物品生成动态二维码 Base64
    items_with_qr = []
    for item in items:
        scan_url = f"{request.host_url}scan/{item.id}"
        qr_b64 = generate_qr_base64(scan_url)
        items_with_qr.append((item, qr_b64))
    return render_template('admin.html', items_with_qr=items_with_qr)

@app.route('/scan/<int:item_id>', methods=['GET', 'POST'])
def scan(item_id):
    item = Item.query.get_or_404(item_id)
    check_items = json.loads(item.check_items)

    if request.method == 'POST':
        checked_by = request.form['checked_by']
        remarks = request.form.get('remarks', '')
        results = {}
        for chk in check_items:
            results[chk] = 'on' in request.form.getlist(f"check_{chk}")

        inspection = Inspection(
            item_id=item_id,
            checked_by=checked_by,
            results=json.dumps(results),
            remarks=remarks
        )
        db.session.add(inspection)
        db.session.commit()
        return '''
        <div class="container mt-5 text-center">
            <h2>✅ 检查提交成功！</h2>
            <a href="/" class="btn btn-primary">返回首页</a>
        </div>
        '''

    return render_template('scan.html', item=item, check_items=check_items)

@app.route('/dashboard')
def dashboard():
    from datetime import datetime
    ym = request.args.get('ym', datetime.now().strftime("%Y-%m"))
    
    items = Item.query.all()
    inspected_ids = {
        ins.item_id for ins in Inspection.query.filter(
            cast(Inspection.timestamp, String).like(f"{ym}-%")
        ).all()
    }

    status_list = [
        {'item': item, 'inspected': item.id in inspected_ids}
        for item in items
    ]
    return render_template('dashboard.html', status_list=status_list, ym=ym)

with app.app_context():
    db.create_all()
    print("✅ 数据库表已在启动时创建")


# if __name__ == '__main__':
#     with app.app_context():
#         db.create_all()
#     # 本地开发用
#     app.run(debug=True)
# else:
#     # Render 生产环境
#     with app.app_context():
#         db.create_all()
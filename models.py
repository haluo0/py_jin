from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100))
    check_items = db.Column(db.Text)  # 存 JSON 字符串

class Inspection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    checked_by = db.Column(db.String(50))
    results = db.Column(db.Text)  # JSON
    remarks = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
from app import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ApiKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    store_name = db.Column(db.String(100), nullable=False)
    client_id = db.Column(db.String(200), nullable=False)
    client_secret = db.Column(db.String(200), nullable=False)

class MonitoredKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keyword = db.Column(db.String(200), nullable=False)
    search_volume = db.Column(db.String(50), default='0')
    rank_info = db.Column(db.String(50), default='A')
    link = db.Column(db.Text, default='-')
    isbn = db.Column(db.String(100), default='-')
    shipping_fee = db.Column(db.String(50), default='-')
    store_rank = db.Column(db.String(50), default='-')
    prev_store_rank = db.Column(db.String(50), default='-')
    stock_quantity = db.Column(db.String(50), default='-')
    sales_quantity = db.Column(db.String(50), default='-')
    registered_at = db.Column(db.String(50), default='-')
    sales_status = db.Column(db.String(50), default='-')
    publisher = db.Column(db.String(100), default='-')
    supply_rate = db.Column(db.String(50), default='-')
    price = db.Column(db.String(50), default='-')
    store_name = db.Column(db.String(100), default='-')
    book_title = db.Column(db.Text, default='-')
    product_link = db.Column(db.Text, default='-')
    # ✨ 새롭게 추가된 카페, 블로그 링크 칸
    cafe_link = db.Column(db.Text, default='-')
    blog_link = db.Column(db.Text, default='-')

class RunningmateKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keyword = db.Column(db.String(200), nullable=False)
    search_volume = db.Column(db.String(50), default='0')
    rank_info = db.Column(db.String(50), default='A')
    link = db.Column(db.Text, default='-')
    isbn = db.Column(db.String(100), default='-')
    shipping_fee = db.Column(db.String(50), default='-')
    store_rank = db.Column(db.String(50), default='-')
    prev_store_rank = db.Column(db.String(50), default='-')
    stock_quantity = db.Column(db.String(50), default='-')
    sales_quantity = db.Column(db.String(50), default='-')
    registered_at = db.Column(db.String(50), default='-')
    sales_status = db.Column(db.String(50), default='-')
    publisher = db.Column(db.String(100), default='-')
    supply_rate = db.Column(db.String(50), default='-')
    price = db.Column(db.String(50), default='-')
    store_name = db.Column(db.String(100), default='-')
    book_title = db.Column(db.Text, default='-')
    product_link = db.Column(db.Text, default='-')
    # ✨ 새롭게 추가된 카페, 블로그 링크 칸
    cafe_link = db.Column(db.Text, default='-')
    blog_link = db.Column(db.Text, default='-')

class DailylearningKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keyword = db.Column(db.String(200), nullable=False)
    search_volume = db.Column(db.String(50), default='0')
    rank_info = db.Column(db.String(50), default='A')
    link = db.Column(db.Text, default='-')
    isbn = db.Column(db.String(100), default='-')
    shipping_fee = db.Column(db.String(50), default='-')
    store_rank = db.Column(db.String(50), default='-')
    prev_store_rank = db.Column(db.String(50), default='-')
    stock_quantity = db.Column(db.String(50), default='-')
    sales_quantity = db.Column(db.String(50), default='-')
    registered_at = db.Column(db.String(50), default='-')
    sales_status = db.Column(db.String(50), default='-')
    publisher = db.Column(db.String(100), default='-')
    supply_rate = db.Column(db.String(50), default='-')
    price = db.Column(db.String(50), default='-')
    store_name = db.Column(db.String(100), default='-')
    book_title = db.Column(db.Text, default='-')
    product_link = db.Column(db.Text, default='-')
    # ✨ 새롭게 추가된 카페, 블로그 링크 칸
    cafe_link = db.Column(db.Text, default='-')
    blog_link = db.Column(db.Text, default='-')

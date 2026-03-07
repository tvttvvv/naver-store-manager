from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import User
from app import db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('store.index'))
        else:
            flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'danger')
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        new_username = request.form.get('new_username')
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')

        # 보안 확인: 현재 비밀번호가 맞는지 검증
        if not check_password_hash(current_user.password_hash, current_password):
            flash('현재 비밀번호가 일치하지 않습니다.', 'danger')
            return redirect(url_for('auth.profile'))

        # 아이디 변경 처리
        if new_username and new_username != current_user.username:
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user:
                flash('이미 사용 중인 아이디입니다.', 'warning')
                return redirect(url_for('auth.profile'))
            current_user.username = new_username

        # 새 비밀번호 변경 처리 (입력한 경우만)
        if new_password:
            current_user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')

        db.session.commit()
        flash('계정 정보가 성공적으로 변경되었습니다. 다음 로그인부터 적용됩니다.', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html')

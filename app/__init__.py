# ... (기존 상단 코드 생략) ...

    # 블루프린트 등록
    from app.views.auth import auth_bp
    from app.views.keys import keys_bp
    from app.views.store import store_bp
    from app.views.kyobo import kyobo_bp
    from app.views.studybox import studybox_bp  # ✨ 이 줄 추가!

    app.register_blueprint(auth_bp)
    app.register_blueprint(keys_bp)
    app.register_blueprint(store_bp)
    app.register_blueprint(kyobo_bp)
    app.register_blueprint(studybox_bp)         # ✨ 이 줄 추가!

    with app.app_context():
        db.create_all()

    return app

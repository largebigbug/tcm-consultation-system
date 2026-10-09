import os

from flask import Flask, jsonify, send_from_directory

import db
from config import settings
from utils.response import fail

FRONTEND_DIST = os.path.join(os.path.dirname(settings.BASE_DIR), "frontend", "dist")


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.get("app.secret_key", "secret")
    app.config["JSON_AS_ASCII"] = False

    db.init_db_path(settings.resolve_db_path())

    from ontology import registry
    registry.load_ontology()

    _init_db()

    _register_blueprints(app)
    _register_error_handlers(app)
    _register_cors(app)
    return app


def _init_db():
    conn = db.connect()
    try:
        schema_path = os.path.join(settings.BASE_DIR, "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        from seed import ensure_seed
        ensure_seed(conn)
        conn.commit()
    finally:
        conn.close()


def _register_blueprints(app):
    from api import (auth, flow, formula, herb, meta, patient, permissions,
                    resources, roles, syndrome, users, workbench)
    app.register_blueprint(auth.bp)
    app.register_blueprint(meta.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(roles.bp)
    app.register_blueprint(permissions.bp)
    app.register_blueprint(resources.bp)
    app.register_blueprint(flow.bp)
    app.register_blueprint(workbench.bp)
    # 业务模块（批次 1：基础数据）
    app.register_blueprint(patient.bp)
    app.register_blueprint(syndrome.bp)
    app.register_blueprint(formula.bp)
    app.register_blueprint(herb.bp)
    # 业务模块（批次 2：门诊业务流）—— 显式注册（批次 2 收口时替换过渡写法）
    from api import diagnosis, dispense, prescription, visit
    app.register_blueprint(visit.bp)
    app.register_blueprint(diagnosis.bp)
    app.register_blueprint(prescription.bp)
    app.register_blueprint(dispense.bp)
    # 业务模块（批次 3：统计报表）—— 过渡写法：模块到位即注册，收口时改显式注册
    # 目的：批次 3 并行开发期，前端子代理的开发服务器不会被尚未落盘的报表模块卡住启动。
    import importlib

    try:
        report = importlib.import_module("api.report")
        app.register_blueprint(report.bp)
    except ModuleNotFoundError:
        app.logger.warning("api.report 尚未就绪，跳过报表蓝图注册（批次 3 收口时须改为显式注册）")
    # 业务模块（批次 5：AI 对话）—— 显式注册
    from api import ai
    app.register_blueprint(ai.bp)


def _register_error_handlers(app):
    @app.errorhandler(ValueError)
    def handle_value_error(e):
        return fail(str(e), "BUSINESS_ERROR")

    @app.errorhandler(404)
    def handle_404(e):
        return fail("接口不存在", "NOT_FOUND", 404)

    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.exception("unhandled error")
        return fail("服务器内部错误", "INTERNAL_ERROR", 500)


def _register_cors(app):
    @app.after_request
    def cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return resp


app = create_app()


@app.route("/api/health")
def health():
    return jsonify({"success": True, "message": "ok", "data": {"name": settings.get("app.name")}})


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if not os.path.exists(FRONTEND_DIST):
        return jsonify({"success": False, "message": "前端未构建，请先执行 npm run build"}), 404
    target = os.path.join(FRONTEND_DIST, path) if path else None
    if path and os.path.isfile(target):
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")


if __name__ == "__main__":
    app.run(
        host=settings.get("app.host", "0.0.0.0"),
        port=int(settings.get("app.port", 5000)),
        debug=True,
    )

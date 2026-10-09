# -*- coding: utf-8 -*-
"""中医问诊系统 · 演示服务器（独立进程，无 reloader，供 demo 常驻）。

与 `app.py` 的区别：直接以模块级 app 起 werkzeug，`debug=False`（不启 reloader，
避免双进程 + 被杀后不自愈），并把启动就绪信息打到 stdout。

用法：
    code-app/backend/.venv/Scripts/python.exe code-app/backend/tools/serve_demo.py [port]
默认端口 5000，监听 0.0.0.0；数据库用 config.yaml 的默认值（data/app.db）。
"""
import os
import sys
import threading

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

from app import app as flask_app  # noqa: E402
from config import settings as app_settings  # noqa: E402
import db as db_module  # noqa: E402

db_path = app_settings.resolve_db_path()
assert os.path.abspath(db_module._db_path) == os.path.abspath(db_path), "数据库路径不一致"


def _warm():
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/" % PORT, timeout=20).read()
    except Exception:
        pass


if __name__ == "__main__":
    from werkzeug.serving import make_server
    srv = make_server("0.0.0.0", PORT, flask_app, threaded=True)
    print("[OK] 中医问诊系统已启动 http://localhost:%d" % PORT, flush=True)
    print("[OK] 数据库: %s" % db_path, flush=True)
    print("[OK] 演示账号: admin/admin123, yishi|yaoshi|daozhen|keshi|kufang / 123456", flush=True)
    threading.Thread(target=_warm, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

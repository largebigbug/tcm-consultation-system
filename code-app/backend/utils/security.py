import datetime
import functools

import jwt
from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from config.settings import get


def hash_password(raw):
    return generate_password_hash(raw)


def verify_password(raw, hashed):
    return check_password_hash(hashed, raw)


def generate_token(user_id, username):
    secret = get("auth.jwt_secret", "secret")
    hours = int(get("auth.jwt_expires_hours", 2))
    exp = datetime.datetime.utcnow() + datetime.timedelta(hours=hours)
    payload = {"sub": str(user_id), "username": username, "exp": exp}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token):
    secret = get("auth.jwt_secret", "secret")
    return jwt.decode(token, secret, algorithms=["HS256"])


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"success": False, "message": "未登录或登录已失效"}), 401
        token = auth[7:]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"success": False, "message": "登录已过期，请重新登录"}), 401
        except Exception:
            return jsonify({"success": False, "message": "无效的登录凭证"}), 401
        g.user_id = int(payload["sub"])
        g.username = payload.get("username")
        return f(*args, **kwargs)

    return wrapper


def require_permission(code):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            from services.auth_service import has_permission
            if not has_permission(getattr(g, "user_id", None), code):
                return jsonify({"success": False, "message": "无权限执行该操作"}), 403
            return f(*args, **kwargs)

        return wrapper

    return deco


def require_any_permission(*codes):
    """持有其中任一权限码即可通过（用于一屏/一接口被多条 M2 行为共用的场景）。

    典型：复诊随访登记屏（UI-11）的列表既服务 `FollowUp_Complete` 的登记作业，
    也服务 `FollowUp_QueryCompletion` 的查询导出（两条行为派生权限码不同）。
    """
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            from services.auth_service import has_permission
            uid = getattr(g, "user_id", None)
            if not any(has_permission(uid, c) for c in codes):
                return jsonify({"success": False, "message": "无权限执行该操作"}), 403
            return f(*args, **kwargs)

        return wrapper

    return deco


def has_current_permission(code):
    from flask import g
    from services.auth_service import has_permission
    return has_permission(getattr(g, "user_id", None), code)

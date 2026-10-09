# -*- coding: utf-8 -*-
"""认证 API（批次 1 底座 + 批次 6 改密）：`/api/auth`。

  POST /api/auth/login     登录（失败 → 400 + 中文，便于前端区分「凭证错误」与「登录态失效」401）
  POST /api/auth/logout    退出登录
  GET  /api/auth/info      当前用户信息
  POST /api/auth/password  修改本人密码（批次 6 契约 §5：oldPassword/newPassword）
"""
from flask import Blueprint, g, request

from services import auth_service
from utils.response import fail, ok
from utils.security import generate_token, login_required

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return fail("请输入用户名和密码", "AUTH_INVALID", 400)
    user, err = auth_service.login(username, password)
    if err:
        # 凭证错误 = 400（参数/凭据类错误）；401 保留给「未登录 / 登录已失效」（login_required）
        return fail(err, "AUTH_FAILED", 400)
    token = generate_token(user["id"], user["username"])
    payload = auth_service.build_login_payload(user)
    payload["token"] = token
    auth_service.write_audit(user["id"], user["username"], "LOGIN")
    return ok(payload, "登录成功")


@bp.post("/logout")
@login_required
def logout():
    auth_service.write_audit(g.user_id, g.username, "LOGOUT")
    return ok(None, "已退出登录")


@bp.get("/info")
@login_required
def info():
    user = auth_service.get_user(g.user_id)
    if not user or user["status"] != 1:
        return fail("账号不存在或已禁用", "AUTH_FAILED")
    return ok(auth_service.build_login_payload(user))


@bp.post("/password")
@login_required
def change_password():
    """修改本人密码：校验原密码 + 新密码规则；成功后旧密码立即失效（契约 §5）。"""
    data = request.get_json(silent=True) or {}
    old_password = data.get("oldPassword")
    new_password = data.get("newPassword")
    if not old_password or not new_password:
        return fail("请输入原密码与新密码", "INVALID_ARGUMENT", 400)
    try:
        auth_service.change_password(g.user_id, old_password, new_password)
    except ValueError as e:
        return fail(str(e), "INVALID_ARGUMENT", 400)
    return ok(None, "密码修改成功，请使用新密码重新登录")

"""证型字典维护 API（UI-12）：/api/syndrome。契约 §4.2。"""
from flask import Blueprint, request

from services import auth_service, syndrome_service
from utils.response import ok
from utils.security import login_required, require_permission

bp = Blueprint("syndrome", __name__, url_prefix="/api/syndrome")


@bp.get("")
@login_required
@require_permission("syndrome:save")
def list_syndromes():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 10))
    filters = {k: request.args.get(k) for k in
               ("syndrome_name", "syndrome_code", "diagnosis_method", "syndrome_status")}
    return ok(syndrome_service.list_syndromes(page, size, filters))


@bp.get("/<int:syndrome_id>")
@login_required
@require_permission("syndrome:save")
def get_syndrome(syndrome_id):
    return ok(syndrome_service.get_syndrome(syndrome_id))


@bp.post("")
@login_required
@require_permission("syndrome:save")
def create_syndrome():
    data = request.get_json(silent=True) or {}
    return ok(syndrome_service.create_syndrome(data, auth_service.current_user()), "保存成功")


@bp.put("/<int:syndrome_id>")
@login_required
@require_permission("syndrome:save")
def update_syndrome(syndrome_id):
    data = request.get_json(silent=True) or {}
    return ok(syndrome_service.update_syndrome(syndrome_id, data, auth_service.current_user()), "保存成功")


@bp.post("/<int:syndrome_id>/status")
@login_required
@require_permission("syndrome:change-status")
def change_status(syndrome_id):
    data = request.get_json(silent=True) or {}
    status = data.get("syndrome_status")
    row = syndrome_service.change_status(syndrome_id, status, auth_service.current_user())
    return ok(row, "已%s" % ("启用" if status == "ENABLED" else "停用"))

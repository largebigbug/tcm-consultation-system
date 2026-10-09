"""方剂模板维护 API（UI-13，主从表单）：/api/formula。契约 §4.3。"""
from flask import Blueprint, request

from services import auth_service, formula_service
from utils.response import ok
from utils.security import login_required, require_permission

bp = Blueprint("formula", __name__, url_prefix="/api/formula")


@bp.get("")
@login_required
@require_permission("formula:save")
def list_formulas():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 10))
    filters = {k: request.args.get(k) for k in
               ("formula_name", "formula_code", "formula_type", "formula_status")}
    return ok(formula_service.list_formulas(page, size, filters))


@bp.get("/<int:formula_id>")
@login_required
@require_permission("formula:save")
def get_formula(formula_id):
    return ok(formula_service.get_formula(formula_id))


@bp.post("")
@login_required
@require_permission("formula:save")
def create_formula():
    data = request.get_json(silent=True) or {}
    return ok(formula_service.create_formula(data, auth_service.current_user()), "保存成功")


@bp.put("/<int:formula_id>")
@login_required
@require_permission("formula:save")
def update_formula(formula_id):
    data = request.get_json(silent=True) or {}
    return ok(formula_service.update_formula(formula_id, data, auth_service.current_user()), "保存成功")


@bp.post("/<int:formula_id>/status")
@login_required
@require_permission("formula:change-status")
def change_status(formula_id):
    data = request.get_json(silent=True) or {}
    status = data.get("formula_status")
    row = formula_service.change_status(formula_id, status, auth_service.current_user())
    return ok(row, "已%s" % ("启用" if status == "ENABLED" else "停用"))

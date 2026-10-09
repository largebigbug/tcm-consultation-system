"""患者建档 API（UI-01）：/api/patient。契约 §4.1。

权限：列表/详情/新增/修改 → patient:save；停用启用 → patient:change-status。
业务异常由 app.py 的 ValueError 处理器转成统一响应。
"""
from flask import Blueprint, request

from services import auth_service, patient_service
from utils.response import ok
from utils.security import login_required, require_permission

bp = Blueprint("patient", __name__, url_prefix="/api/patient")


@bp.get("")
@login_required
@require_permission("patient:save")
def list_patients():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 10))
    filters = {k: request.args.get(k) for k in ("patient_no", "patient_name", "phone", "patient_status")}
    return ok(patient_service.list_patients(page, size, filters))


@bp.get("/<int:patient_id>")
@login_required
@require_permission("patient:save")
def get_patient(patient_id):
    return ok(patient_service.get_patient(patient_id))


@bp.post("")
@login_required
@require_permission("patient:save")
def create_patient():
    data = request.get_json(silent=True) or {}
    return ok(patient_service.create_patient(data, auth_service.current_user()), "保存成功")


@bp.put("/<int:patient_id>")
@login_required
@require_permission("patient:save")
def update_patient(patient_id):
    data = request.get_json(silent=True) or {}
    return ok(patient_service.update_patient(patient_id, data, auth_service.current_user()), "保存成功")


@bp.post("/<int:patient_id>/status")
@login_required
@require_permission("patient:change-status")
def change_status(patient_id):
    data = request.get_json(silent=True) or {}
    status = data.get("patient_status")
    row = patient_service.change_status(patient_id, status, auth_service.current_user())
    return ok(row, "已%s" % ("启用" if status == "ACTIVE" else "停用"))

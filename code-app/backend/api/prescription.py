"""处方 API（UI-06 开具处方 / UI-07 处方审核）：`/api/prescription`。契约 §4.3。

权限（M5 自动派生，勿硬编码新码）：
  `prescription:save` 列表/详情/新增/修改；`prescription:submit` 提交；`prescription:review` 待审列表与审核；
  `prescription:cancel` 作废；`dispense:confirm` 待调剂列表（契约 §4.3 末行）；
  详情同时允许 `prescription:review`（药师审核必须能看详情，契约 §5 接口级权限交叉说明）。
"""
import functools

from flask import Blueprint, jsonify, request

from services import auth_service, prescription_service
from utils.response import ok
from utils.security import has_current_permission, login_required, require_permission

bp = Blueprint("prescription", __name__, url_prefix="/api/prescription")


def require_any_permission(*codes):
    """任一权限码满足即可（用于「详情」等交叉权限接口）。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not any(has_current_permission(code) for code in codes):
                return jsonify({"success": False, "message": "无权限执行该操作"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------- 列表 / 详情

@bp.get("")
@login_required
@require_permission("prescription:save")
def list_prescriptions():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 10))
    filters = {k: request.args.get(k) for k in
               ("prescription_no", "visit_id", "patient_name", "prescription_status")}
    return ok(prescription_service.list_prescriptions(page, size, filters))


@bp.get("/pending-review")
@login_required
@require_permission("prescription:review")
def list_pending_review():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 10))
    filters = {k: request.args.get(k) for k in ("prescription_no", "patient_name")}
    return ok(prescription_service.list_pending_review(page, size, filters))


@bp.get("/pending-dispense")
@login_required
@require_permission("dispense:confirm")
def list_pending_dispense():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 10))
    filters = {k: request.args.get(k) for k in ("prescription_no", "patient_name")}
    return ok(prescription_service.list_pending_dispense(page, size, filters))


@bp.get("/<int:prescription_id>")
@login_required
@require_any_permission("prescription:save", "prescription:review")
def get_prescription(prescription_id):
    row = prescription_service.get_prescription(prescription_id)
    if not row:
        return ok(None, "处方不存在")
    return ok(row)


# ---------------------------------------------------------------- 开具 / 修改 / 提交

@bp.post("")
@login_required
@require_permission("prescription:save")
def create_prescription():
    data = request.get_json(silent=True) or {}
    return ok(prescription_service.create_prescription(data, auth_service.current_user()), "保存成功")


@bp.put("/<int:prescription_id>")
@login_required
@require_permission("prescription:save")
def update_prescription(prescription_id):
    data = request.get_json(silent=True) or {}
    return ok(prescription_service.update_prescription(prescription_id, data,
                                                       auth_service.current_user()), "保存成功")


@bp.post("/<int:prescription_id>/submit")
@login_required
@require_permission("prescription:submit")
def submit_prescription(prescription_id):
    return ok(prescription_service.submit_prescription(prescription_id, auth_service.current_user()),
              "提交送审成功")


# ---------------------------------------------------------------- 审核 / 作废

@bp.post("/<int:prescription_id>/review")
@login_required
@require_permission("prescription:review")
def review_prescription(prescription_id):
    data = request.get_json(silent=True) or {}
    result = prescription_service.review_prescription(prescription_id, data,
                                                      auth_service.current_user())
    message = "审核通过" if result["action"] == "APPROVE" else "已驳回"
    return ok(result, message)


@bp.post("/<int:prescription_id>/cancel")
@login_required
@require_permission("prescription:cancel")
def cancel_prescription(prescription_id):
    data = request.get_json(silent=True) or {}
    result = prescription_service.cancel_prescription(prescription_id, data,
                                                      auth_service.current_user())
    return ok(result, "处方已作废（%s）" % result["dispatch"])

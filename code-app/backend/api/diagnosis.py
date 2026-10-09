# -*- coding: utf-8 -*-
"""辨证结论 API（UI-05）：/api/diagnosis。契约 docs/批次2-实现契约.md §4.2。

权限：查询/保存/修改 → diagnosis:save；确认结论 → diagnosis:confirm。
（详情与列表允许 diagnosis:confirm 一并通过 `require_any_permission`，便于确认前复核。）
业务异常由 app.py 的 ValueError 处理器转成统一响应（success=false + 中文 message）。
"""
import functools

from flask import Blueprint, g, jsonify, request

from services import auth_service, diagnosis_service
from utils.response import ok
from utils.security import login_required, require_permission

bp = Blueprint("diagnosis", __name__, url_prefix="/api/diagnosis")


def require_any_permission(*codes):
    """任一权限码满足即放行（只读接口用；与 api/visit.py 同名同义）。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            owned = auth_service.get_permission_codes(getattr(g, "user_id", None))
            if "*" not in owned and not owned.intersection(codes):
                return jsonify({"success": False, "message": "无权限执行该操作"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return deco


@bp.get("")
@login_required
@require_permission("diagnosis:save")
def list_diagnoses():
    """该就诊全部辨证结论（visit_id 必填）。"""
    visit_id = request.args.get("visit_id")
    if visit_id in (None, ""):
        raise ValueError("就诊记录必填")
    try:
        visit_id = int(visit_id)
    except (TypeError, ValueError):
        raise ValueError("就诊记录标识非法")
    return ok(diagnosis_service.list_diagnoses(visit_id))


@bp.get("/<int:diagnosis_id>")
@login_required
@require_any_permission("diagnosis:save", "diagnosis:confirm")
def get_diagnosis(diagnosis_id):
    return ok(diagnosis_service.get_diagnosis(diagnosis_id))


@bp.post("")
@login_required
@require_permission("diagnosis:save")
def create_diagnosis():
    data = request.get_json(silent=True) or {}
    return ok(diagnosis_service.create_diagnosis(data, auth_service.current_user()), "保存成功")


@bp.put("/<int:diagnosis_id>")
@login_required
@require_permission("diagnosis:save")
def update_diagnosis(diagnosis_id):
    data = request.get_json(silent=True) or {}
    return ok(diagnosis_service.update_diagnosis(diagnosis_id, data, auth_service.current_user()),
              "保存成功")


@bp.post("/<int:diagnosis_id>/confirm")
@login_required
@require_permission("diagnosis:confirm")
def confirm_diagnosis(diagnosis_id):
    return ok(diagnosis_service.confirm_diagnosis(diagnosis_id, auth_service.current_user()),
              "结论已确认")

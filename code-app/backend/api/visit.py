# -*- coding: utf-8 -*-
"""门诊就诊 API（UI-02/03/04）：/api/visit。契约 docs/批次2-实现契约.md §4.1。

权限：列表/详情/跳选框/挂号 → visit:register；待接诊列表/接诊 → visit:receive；
      四诊录入与读取 → visit:save-four-diagnosis；撤销 → visit:cancel。
      详情接口按「接口级权限交叉」放宽为任一门诊侧权限可读（§5：中医师在接诊/四诊/辨证全流程
      都需要读取本人接诊的就诊详情，而 M5 未把 visit:register 授予 ROLE-02）。
业务异常由 app.py 的 ValueError 处理器转成统一响应（success=false + 中文 message）。
"""
import functools

from flask import Blueprint, g, jsonify, request

from services import auth_service, visit_service
from utils.response import ok
from utils.security import login_required, require_permission

bp = Blueprint("visit", __name__, url_prefix="/api/visit")

# 详情可读权限（契约 §5 接口级权限交叉说明；避免中医师全流程读不到就诊详情）
DETAIL_PERMISSIONS = (
    "visit:register",
    "visit:receive",
    "visit:save-four-diagnosis",
    "visit:cancel",
    "visit:complete",
    "diagnosis:save",
    "diagnosis:confirm",
    "prescription:save",
)


def require_any_permission(*codes):
    """任一权限码满足即放行（utils/security.require_permission 的「或」版本，只读接口用）。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            owned = auth_service.get_permission_codes(getattr(g, "user_id", None))
            if "*" not in owned and not owned.intersection(codes):
                return jsonify({"success": False, "message": "无权限执行该操作"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return deco


_LIST_FILTER_KEYS = ("visit_no", "patient_id", "patient_name", "visit_type", "visit_status",
                     "dept_code", "doctor_id", "date_from", "date_to")


def _int_arg(name, default):
    """分页入参取整：非法值转中文业务异常（不透出英文异常）。"""
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        raise ValueError("%s 必须为整数" % name)


@bp.get("")
@login_required
@require_permission("visit:register")
def list_visits():
    page = _int_arg("page", 1)
    size = _int_arg("size", 10)
    filters = {k: request.args.get(k) for k in _LIST_FILTER_KEYS}
    return ok(visit_service.list_visits(page, size, filters))


@bp.get("/pending")
@login_required
@require_permission("visit:receive")
def list_pending():
    """待接诊列表（visit_status=REGISTERED），UI-03 入口列表。"""
    page = _int_arg("page", 1)
    size = _int_arg("size", 10)
    filters = {k: request.args.get(k) for k in _LIST_FILTER_KEYS}
    return ok(visit_service.list_pending(page, size, filters))


@bp.get("/options")
@login_required
@require_permission("visit:register")
def options():
    """跳选框数据源：复诊选上次就诊、随访选本次就诊。"""
    return ok(visit_service.options(request.args.get("patient_id"),
                                    request.args.get("keyword") or ""))


@bp.get("/<int:visit_id>")
@login_required
@require_any_permission(*DETAIL_PERMISSIONS)
def get_visit(visit_id):
    return ok(visit_service.get_visit_detail(visit_id))


@bp.post("")
@login_required
@require_permission("visit:register")
def register_visit():
    data = request.get_json(silent=True) or {}
    return ok(visit_service.register_visit(data, auth_service.current_user()), "挂号成功")


@bp.post("/<int:visit_id>/receive")
@login_required
@require_permission("visit:receive")
def receive_visit(visit_id):
    data = request.get_json(silent=True) or {}
    return ok(visit_service.receive_visit(visit_id, data, auth_service.current_user()), "接诊成功")


@bp.get("/<int:visit_id>/four-diagnosis")
@login_required
@require_permission("visit:save-four-diagnosis")
def get_four_diagnosis(visit_id):
    """四诊详情；不存在时 data 为 null。"""
    return ok(visit_service.get_four_diagnosis(visit_id))


@bp.post("/<int:visit_id>/four-diagnosis")
@login_required
@require_permission("visit:save-four-diagnosis")
def save_four_diagnosis(visit_id):
    data = request.get_json(silent=True) or {}
    row = visit_service.save_four_diagnosis(visit_id, data, auth_service.current_user())
    return ok(row, "四诊信息已保存")


@bp.post("/<int:visit_id>/cancel")
@login_required
@require_permission("visit:cancel")
def cancel_visit(visit_id):
    data = request.get_json(silent=True) or {}
    row = visit_service.cancel_visit(visit_id, data, auth_service.current_user())
    return ok(row, "就诊已撤销")

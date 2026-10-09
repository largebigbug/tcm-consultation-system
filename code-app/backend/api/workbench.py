# -*- coding: utf-8 -*-
"""工作台 API（批次 6 块①②④）：`/api/workbench`。

契约 `docs/批次6-实现契约.md` §6/§7：

  GET  /api/workbench/todo|done|requested   登录；新增筛选（flowName/activityName/dateFrom/dateTo/status），
                                            分页 page/size（size ≤ 100，越界 400）
  POST /api/workbench/todo/<id>/approve     登录 + M5 派生权限码（由任务 behavior_ref 派生）
  POST /api/workbench/todo/<id>/reject      同上（驳回原因必填）
  POST /api/workbench/todo/<id>/transfer    登录 + 任务归属（非平台权限码）
  POST /api/workbench/todo/<id>/urge        登录 + 任务归属
  POST /api/workbench/todo/<id>/return      底座能力，前端不暴露（契约 §0.2 / §9.2）

错误一律中文：参数类 400、越权 403、业务规则 `fail()`（沿用底座行为）。
"""
from flask import Blueprint, request

from services import auth_service, workbench_service
from utils.response import fail, ok
from utils.security import login_required

bp = Blueprint("workbench", __name__, url_prefix="/api/workbench")

MAX_PAGE_SIZE = 100
FILTER_KEYS = ("flowName", "activityName", "dateFrom", "dateTo", "status")


def _paging():
    """分页参数解析：非法 → (None, 400 响应)（契约 §7「参数类错误 400」）。"""
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        return None, fail("页码必须为正整数", "INVALID_ARGUMENT", 400)
    try:
        size = int(request.args.get("size", 10))
    except (TypeError, ValueError):
        return None, fail("每页条数必须为正整数", "INVALID_ARGUMENT", 400)
    if page < 1:
        return None, fail("页码必须为正整数", "INVALID_ARGUMENT", 400)
    if size < 1 or size > MAX_PAGE_SIZE:
        return None, fail("每页条数须在 1~%d 之间" % MAX_PAGE_SIZE, "INVALID_ARGUMENT", 400)
    return (page, size), None


def _filters():
    return {k: (request.args.get(k) or "").strip() or None for k in FILTER_KEYS}


def _list_response(fn):
    paging, error = _paging()
    if error:
        return error
    page, size = paging
    data = fn(auth_service.current_user()["id"], page, size, _filters())
    return ok(data)


@bp.get("/todo")
@login_required
def todo():
    return _list_response(workbench_service.todo)


@bp.get("/done")
@login_required
def done():
    return _list_response(workbench_service.done)


@bp.get("/requested")
@login_required
def requested():
    return _list_response(workbench_service.requested)


def _review(task_id, action, success_message):
    data = request.get_json(silent=True) or {}
    try:
        result = (workbench_service.approve if action == "APPROVE" else workbench_service.reject)(
            task_id, data.get("comment"), auth_service.current_user())
        return ok(result, success_message)
    except workbench_service.PermissionDenied as e:
        return fail(str(e), "FORBIDDEN", 403)
    except ValueError as e:
        return fail(str(e))


@bp.post("/todo/<int:task_id>/approve")
@login_required
def approve(task_id):
    return _review(task_id, "APPROVE", "审批通过")


@bp.post("/todo/<int:task_id>/reject")
@login_required
def reject(task_id):
    return _review(task_id, "REJECT", "已驳回")


@bp.post("/todo/<int:task_id>/transfer")
@login_required
def transfer(task_id):
    data = request.get_json(silent=True) or {}
    try:
        result = workbench_service.transfer(
            task_id, data.get("assigneeId", data.get("assignee_id")), auth_service.current_user())
        return ok(result, "转办成功（%s → %s）" % (result["from"], result["to"]))
    except ValueError as e:
        return fail(str(e))


@bp.post("/todo/<int:task_id>/urge")
@login_required
def urge(task_id):
    try:
        workbench_service.urge(task_id, auth_service.current_user())
        return ok(None, "催办成功")
    except ValueError as e:
        return fail(str(e))


@bp.post("/todo/<int:task_id>/return")
@login_required
def return_task(task_id):
    """退回（底座能力）：M6 Q02 `approvalOutcomes` 仅 APPROVE/REJECT，D-25 退回等同驳回 → 前端不暴露。"""
    data = request.get_json(silent=True) or {}
    try:
        workbench_service.return_task(task_id, data.get("target_activity_id"), data.get("comment"),
                                      auth_service.current_user())
        return ok(None, "已退回")
    except ValueError as e:
        return fail(str(e))

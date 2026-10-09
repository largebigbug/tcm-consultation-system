"""调剂发药 API（UI-08 调剂发药）与随访 API（本批无界面，供验收与批次 3 使用）。

契约 §4.4 `/api/dispense`：
  `GET  /api/dispense/{id}`               权限 `dispense:confirm`
  `GET  /api/dispense/{id}/stock-check`   权限 `dispense:confirm`（R-02 逐味结果）
  `POST /api/dispense/{id}/confirm`       权限 `dispense:confirm`
  `POST /api/dispense/{id}/issue`         权限 `dispense:issue`
契约 §4.5 `/api/followup`：
  `GET  /api/followup`                    权限 `follow_up:complete`
  `POST /api/followup/{id}/complete`      权限 `follow_up:complete`（R-05 日期顺序）
  `POST /api/followup/{id}/mark-lost`     权限 `follow_up:mark-lost`
说明：随访接口按契约路径 `/api/followup` 落地，与本模块同一蓝图（`app.py` 只注册 `bp`），
      故蓝图不带 url_prefix，路径在每个路由上写全；这样不新增第 7 个文件也满足契约路径与权限码。
"""
from flask import Blueprint, request

from services import auth_service, dispense_service, followup_service
from utils.response import ok
from utils.security import login_required, require_any_permission, require_permission

bp = Blueprint("dispense", __name__)


# ---------------------------------------------------------------- 调剂发药（UI-08）

@bp.get("/api/dispense/<int:record_id>")
@login_required
@require_permission("dispense:confirm")
def get_dispense(record_id):
    row = dispense_service.get_dispense(record_id)
    if not row:
        return ok(None, "调剂发药记录不存在")
    return ok(row)


@bp.get("/api/dispense/<int:record_id>/stock-check")
@login_required
@require_permission("dispense:confirm")
def stock_check(record_id):
    """`grdStockCheck` 只读数据源：逐味需求用量 / 当前库存 / 是否充足（R-02）。"""
    return ok(dispense_service.stock_check(record_id))


@bp.post("/api/dispense/<int:record_id>/confirm")
@login_required
@require_permission("dispense:confirm")
def confirm_dispense(record_id):
    data = request.get_json(silent=True) or {}
    return ok(dispense_service.confirm_dispense(record_id, data, auth_service.current_user()),
              "调剂确认成功，库存已扣减")


@bp.post("/api/dispense/<int:record_id>/issue")
@login_required
@require_permission("dispense:issue")
def issue_dispense(record_id):
    data = request.get_json(silent=True) or {}
    return ok(dispense_service.issue_dispense(record_id, data, auth_service.current_user()),
              "发药确认成功")


# ---------------------------------------------------------------- 随访（契约 §4.5）

@bp.get("/api/followup")
@login_required
@require_any_permission("follow_up:complete", "follow_up:query-completion")
def list_followups():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 10))
    filters = {k: request.args.get(k) for k in
               ("patient_name", "record_status", "scheduled_from", "scheduled_to")}
    return ok(followup_service.list_followups(page, size, filters))


@bp.get("/api/followup/<int:followup_id>")
@login_required
@require_any_permission("follow_up:complete", "follow_up:query-completion")
def get_followup(followup_id):
    """随访详情（契约未列，批次 3 随访登记屏需要；同一权限码）。"""
    row = followup_service.get_followup(followup_id)
    if not row:
        return ok(None, "随访记录不存在")
    return ok(row)


@bp.post("/api/followup/<int:followup_id>/complete")
@login_required
@require_permission("follow_up:complete")
def complete_followup(followup_id):
    data = request.get_json(silent=True) or {}
    return ok(followup_service.complete_followup(followup_id, data, auth_service.current_user()),
              "随访登记完成")


@bp.post("/api/followup/<int:followup_id>/mark-lost")
@login_required
@require_permission("follow_up:mark-lost")
def mark_lost(followup_id):
    data = request.get_json(silent=True) or {}
    return ok(followup_service.mark_lost(followup_id, data, auth_service.current_user()),
              "已标记失访")

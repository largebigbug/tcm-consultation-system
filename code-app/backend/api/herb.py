"""饮片建档与入库 / 饮片库存与预警 API（UI-09 / UI-10）：/api/herb。契约 §4.4。

权限：建档维护 herb:save；状态 herb:change-status；入库 herb:inbound；盘点 herb:stocktake；
      库存查询与预警、导出 CSV、对账 herb:query-stock-and-alert；跳选框 options 登录即可。
"""
import csv
import io
from urllib.parse import quote

from flask import Blueprint, Response, request

from services import auth_service, herb_service
from utils.response import ok
from utils.security import login_required, require_permission

bp = Blueprint("herb", __name__, url_prefix="/api/herb")

_STOCK_FILTER_KEYS = ("herb_name", "herb_code", "herb_category", "toxicity_level", "herb_status",
                      "alert_only", "stock_from", "stock_to")


# ---------------------------------------------------------------- 跳选框

@bp.get("/options")
@login_required
def options():
    return ok(herb_service.options(request.args.get("keyword") or ""))


# ---------------------------------------------------------------- 库存查询与预警

@bp.get("/stock")
@login_required
@require_permission("herb:query-stock-and-alert")
def list_stock():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 20))
    filters = {k: request.args.get(k) for k in _STOCK_FILTER_KEYS}
    return ok(herb_service.list_stock(page, size, filters))


@bp.get("/stock/export")
@login_required
@require_permission("herb:query-stock-and-alert")
def export_stock():
    filters = {k: request.args.get(k) for k in _STOCK_FILTER_KEYS}
    rows = herb_service.stock_rows(filters)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["饮片编码", "饮片名称", "别名", "药材类别", "毒性分级", "规格", "产地",
                     "库存数量(g)", "低库存预警值(g)", "预警状态", "预警差额(g)",
                     "常用最小量(g)", "常用最大量(g)", "最近入库日期", "最近出库日期"])
    for r in rows:
        writer.writerow([
            r.get("herb_code"), r.get("herb_name"), r.get("alias_name"), r.get("herb_category"),
            r.get("toxicity_level"), r.get("spec"), r.get("origin"), r.get("stock_quantity"),
            r.get("low_stock_threshold"), r.get("alert_status"), r.get("alert_gap"),
            r.get("min_common_dose"), r.get("max_common_dose"),
            r.get("latest_inbound_date"), r.get("latest_outbound_date"),
        ])
    # UTF-8 BOM：保证 Excel 正确识别中文
    content = "\ufeff" + buf.getvalue()
    filename = quote("饮片库存与预警.csv")
    return Response(content, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % filename})


# ---------------------------------------------------------------- 建档维护

@bp.get("")
@login_required
@require_permission("herb:save")
def list_herbs():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 10))
    filters = {k: request.args.get(k) for k in ("herb_name", "herb_code", "herb_category", "herb_status")}
    return ok(herb_service.list_herbs(page, size, filters))


@bp.get("/<int:herb_id>")
@login_required
@require_permission("herb:save")
def get_herb(herb_id):
    return ok(herb_service.get_herb(herb_id))


@bp.post("")
@login_required
@require_permission("herb:save")
def create_herb():
    data = request.get_json(silent=True) or {}
    return ok(herb_service.create_herb(data, auth_service.current_user()), "保存成功")


@bp.put("/<int:herb_id>")
@login_required
@require_permission("herb:save")
def update_herb(herb_id):
    data = request.get_json(silent=True) or {}
    return ok(herb_service.update_herb(herb_id, data, auth_service.current_user()), "保存成功")


@bp.post("/<int:herb_id>/status")
@login_required
@require_permission("herb:change-status")
def change_status(herb_id):
    data = request.get_json(silent=True) or {}
    status = data.get("herb_status")
    row = herb_service.change_status(herb_id, status, auth_service.current_user())
    return ok(row, "已%s" % ("启用" if status == "ENABLED" else "停用"))


@bp.post("/<int:herb_id>/inbound")
@login_required
@require_permission("herb:inbound")
def inbound(herb_id):
    data = request.get_json(silent=True) or {}
    return ok(herb_service.inbound(herb_id, data, auth_service.current_user()), "入库登记成功")


@bp.post("/<int:herb_id>/stocktake")
@login_required
@require_permission("herb:stocktake")
def stocktake(herb_id):
    data = request.get_json(silent=True) or {}
    row = herb_service.stocktake(herb_id, data, auth_service.current_user())
    adjust = row["stocktake"]["adjust_quantity"]
    return ok(row, "盘点完成，已生成盘点调整流水（差异 %.3f g）" % adjust)


@bp.get("/<int:herb_id>/reconcile")
@login_required
@require_permission("herb:save")
def reconcile(herb_id):
    """UI-09 btnReconcile：按 RULE-HERB-STOCK-RECONCILE 输出账实差异（无独立行为）。"""
    return ok(herb_service.reconcile(herb_id))

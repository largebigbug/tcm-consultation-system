# -*- coding: utf-8 -*-
"""报表 API（批次 3）：/api/report。

契约 docs/批次3-实现契约.md §3.4 / §3.5：
  GET /api/report/<reportCode>             分页查询
  GET /api/report/<reportCode>/export      导出（?format=xlsx|csv）
权限：每张报表用其 M7 behaviorRef 派生权限码（查询与导出同一权限，需求 D-31）。
未知报表码 → 404 中文提示；分页/格式等非法取值 → 400 中文提示；其余业务校验失败按全局约定
（utils/response.fail，中文 message）。
"""
from urllib.parse import quote

from flask import Blueprint, Response, g, request

from services import auth_service, report_service
from utils.response import fail, ok
from utils.security import login_required, require_any_permission

bp = Blueprint("report", __name__, url_prefix="/api/report")


def _with_any_report_permission(view):
    """蓝图级「任一报表权限」放行；精确到该报表的权限码在视图内二次校验。"""
    codes = report_service.all_report_permission_codes()
    return require_any_permission(*codes)(view) if codes else view


def _query():
    """查询参数 → {参数名: [值, …]}（支持重复参数，服务层负责逗号拆分与默认值）。"""
    return {key: request.args.getlist(key) for key in request.args.keys()}


def _check_permission(report_code):
    """返回 (report, 拒绝响应)。权限码由 M7 behaviorRef 派生（与 seed 同一规则）。"""
    report = report_service.get_report(report_code)
    code = report_service.permission_code_for_report(report)
    if code and not auth_service.has_permission(getattr(g, "user_id", None), code):
        return report, fail("无权限执行该操作", "FORBIDDEN", 403)
    return report, None


@bp.get("/<report_code>")
@login_required
@_with_any_report_permission
def query_report(report_code):
    try:
        _report, denied = _check_permission(report_code)
        if denied:
            return denied
        return ok(report_service.list_report(report_code, _query()))
    except report_service.ReportError as e:
        return fail(e.message, "REPORT_ERROR", e.status)


@bp.get("/<report_code>/export")
@login_required
@_with_any_report_permission
def export_report(report_code):
    try:
        _report, denied = _check_permission(report_code)
        if denied:
            return denied
        fmt = request.args.get("format") or "xlsx"
        payload, filename, mimetype = report_service.export_report(report_code, _query(), fmt)
    except report_service.ReportError as e:
        return fail(e.message, "REPORT_ERROR", e.status)
    resp = Response(payload, mimetype=mimetype)
    resp.headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(filename)
    return resp

from flask import Blueprint

from ontology.registry import get_dictionary_items, registry
from utils.response import fail, ok
from utils.security import login_required

bp = Blueprint("meta", __name__, url_prefix="/api/meta")


@bp.get("/dictionaries")
@login_required
def dictionaries():
    """返回全部业务字典，键形如 `DICT-PATIENT.GENDER`（字典 id + 类型码）。"""
    data = {}
    for dic in registry["data_dictionaries"].values():
        for t in dic.get("types", []) or []:
            key = "%s.%s" % (dic.get("id"), t.get("typeCode"))
            data[key] = [
                {"code": it["code"], "label": it["label"]}
                for it in t.get("items", []) or []
                if it.get("enabled", True)
            ]
    return ok(data)


@bp.get("/dictionary/<dict_id>/<type_code>")
@login_required
def dictionary(dict_id, type_code):
    items = get_dictionary_items(dict_id, type_code)
    if not items:
        return fail("字典不存在或该类型无字典项")
    return ok(items)


@bp.get("/rules")
@login_required
def rules():
    return ok([
        {
            "id": r["id"],
            "name": r.get("name", r["id"]),
            "description": r.get("description"),
            "expression": (r.get("expression") or "").strip(),
            "rule_type": r.get("ruleType"),
            "input_params": r.get("inputParams", []),
        }
        for r in registry["rules"].values()
    ])


@bp.get("/ontology")
@login_required
def ontology_summary():
    """模型装载自检：确认七模型均已注册（供联调排错用）。"""
    return ok({
        "aggregates": len(registry["aggregates"]),
        "entities": len(registry["entities"]),
        "dictionaries": len(registry["data_dictionaries"]),
        "behaviors": len(registry["behaviors"]),
        "rules": len(registry["rules"]),
        "roles": len(registry["roles"]),
        "permissions": len(registry["permissions"]),
        "flows": len(registry["flows"]),
        "query_reports": len(registry["query_reports"]),
        "screens": len(registry["screens"]),
        "menus": len(registry["menus"]),
    })

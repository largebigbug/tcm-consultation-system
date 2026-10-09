import db
from utils.security import hash_password, verify_password


def get_user_by_username(username, conn=None):
    return db.query_one("SELECT * FROM sys_user WHERE username = ?", (username,), conn)


def get_user(user_id, conn=None):
    return db.query_one("SELECT * FROM sys_user WHERE id = ?", (user_id,), conn)


def login(username, password):
    user = get_user_by_username(username)
    if not user or not verify_password(password, user["password"]):
        return None, "用户名或密码错误"
    if user["status"] != 1:
        return None, "账号已被禁用"
    return user, None


def get_user_roles(user_id, conn=None):
    roles = db.query(
        """
        SELECT r.* FROM sys_role r
        JOIN sys_user_role ur ON ur.role_id = r.id
        WHERE ur.user_id = ? AND r.status = 1
        """,
        (user_id,),
        conn,
    )
    result = []
    seen = set()
    stack = list(roles)
    while stack:
        role = stack.pop()
        if role["id"] in seen:
            continue
        seen.add(role["id"])
        result.append(role)
        if role["parent_id"] and role["parent_id"] != 0:
            parent = db.query_one("SELECT * FROM sys_role WHERE id = ?", (role["parent_id"],), conn)
            if parent and parent["status"] == 1:
                stack.append(parent)
    return result


def get_permission_codes(user_id, conn=None):
    roles = get_user_roles(user_id, conn)
    codes = set()
    for r in roles:
        if r["code"] in ("admin", "ROLE-ADMIN"):
            codes.add("*")
        perms = db.query(
            """
            SELECT p.code FROM sys_permission p
            JOIN sys_role_permission rp ON rp.permission_id = p.id
            WHERE rp.role_id = ? AND p.status = 1
            """,
            (r["id"],),
            conn,
        )
        for p in perms:
            codes.add(p["code"])
    return codes


def has_permission(user_id, code):
    if user_id is None:
        return False
    codes = get_permission_codes(user_id)
    return "*" in codes or code in codes


def get_menus(user_id):
    codes = get_permission_codes(user_id)
    resources = db.query(
        "SELECT * FROM sys_resource WHERE status = 1 AND type IN ('DIRECTORY','MENU') ORDER BY sort_order, id"
    )
    allowed_ids = set()
    for r in resources:
        if r["type"] == "MENU":
            pc = r["permission_code"]
            if not pc or "*" in codes or pc in codes:
                allowed_ids.add(r["id"])
    menu_list = []
    for r in resources:
        if r["type"] == "DIRECTORY":
            children = [c for c in resources if c["parent_id"] == r["id"] and c["id"] in allowed_ids]
            if children:
                menu_list.append({
                    "id": r["id"],
                    "name": r["name"],
                    "code": r["code"],
                    "icon": r["icon"],
                    "path": r["path"],
                    "children": [{
                        "id": c["id"],
                        "name": c["name"],
                        "code": c["code"],
                        "icon": c["icon"],
                        "path": c["path"],
                        "permission_code": c["permission_code"],
                    } for c in children],
                })
    return menu_list


def build_login_payload(user):
    user_id = user["id"]
    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "real_name": user["real_name"] or user["username"],
            "actor_type": user["actor_type"],
            "roles": [r["code"] for r in get_user_roles(user_id)],
        },
        "permissions": sorted(get_permission_codes(user_id)),
        "menus": get_menus(user_id),
    }


def current_user():
    from flask import g
    user = get_user(getattr(g, "user_id", None))
    if not user:
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "real_name": user["real_name"] or user["username"],
    }


def write_audit(user_id, username, action, detail=""):
    db.execute(
        "INSERT INTO audit_logs (user_id, username, action, detail) VALUES (?, ?, ?, ?)",
        (user_id, username, action, detail),
    )


#: 新密码最小长度（契约 §5：≥6 位）
MIN_PASSWORD_LENGTH = 6


def change_password(user_id, old_password, new_password):
    """修改本人密码（批次 6 契约 §5）：校验原密码 → 新密码 ≥6 位且 ≠ 用户名/原密码 →
    落库 `hash_password` → 写 `audit_logs(action='CHANGE_PASSWORD')`。失败抛中文 `ValueError`。
    """
    user = get_user(user_id)
    if not user or user["status"] != 1:
        raise ValueError("账号不存在或已禁用")
    if not old_password:
        raise ValueError("请输入原密码")
    if not new_password:
        raise ValueError("请输入新密码")
    if not verify_password(old_password, user["password"]):
        raise ValueError("原密码不正确")
    new_password = str(new_password).strip()
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise ValueError("新密码长度不得少于 %d 位" % MIN_PASSWORD_LENGTH)
    if new_password == user["username"]:
        raise ValueError("新密码不能与用户名相同")
    if verify_password(new_password, user["password"]):
        raise ValueError("新密码不能与原密码相同")
    db.execute(
        "UPDATE sys_user SET password = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (hash_password(new_password), user_id),
    )
    write_audit(user_id, user["username"], "CHANGE_PASSWORD", "用户自助修改密码")
    return True

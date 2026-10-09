# -*- coding: utf-8 -*-
"""AGG-VISIT-001 就诊记录（含从表 FourDiagnosis 四诊信息）。

行为：Visit_Register / Visit_Receive / Visit_SaveFourDiagnosis / Visit_Cancel /
      Visit_Complete（系统行为，供处方提交链调用）。
契约：docs/批次2-实现契约.md §2 全局约定、§3 数据库契约、§4.1 API、§8.6 就诊与辨证规则。
规则：REF-05 接诊时间不得早于挂号时间、主诉 ≤200 字、复诊必选上次就诊、
      每就诊至多一份四诊（ux_four_diagnosis_visit，更新语义）、脉象必填、
      撤销就诊前置「该就诊下不存在任何处方」。

状态码：M1 字典 DICT-VISIT.VISIT_STATUS 的 code（模型为唯一语义来源）
      （REGISTERED 已挂号 / IN_PROGRESS 接诊中 / COMPLETED 已完成 / CANCELLED 已取消）。
      入参/筛选兼容历史字面量 IN_CONSULT（_STATUS_ALIAS），落库与对外返回一律用 M1 code。
      目录：字典码取自 registry.get_dictionary_items；字典之外的取值一律拒绝（不静默落库）。
字典码取自 registry.get_dictionary_items（不硬编码字面量）。
"""
import datetime
import sqlite3

import db
from ontology.registry import get_dictionary_items
from utils.codegen import generate_code, next_code

TABLE = "visit"
FOUR_TABLE = "four_diagnosis"
PRESCRIPTION_TABLE = "prescription"

# ---- 就诊状态（DICT-VISIT.VISIT_STATUS） ----
STATUS_REGISTERED = "REGISTERED"
STATUS_IN_CONSULT = "IN_PROGRESS"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"
# 入参兼容别名 → M1 字典 code（落库口径唯一：IN_PROGRESS）
_STATUS_ALIAS = {"IN_CONSULT": STATUS_IN_CONSULT, "IN_PROGRESS": STATUS_IN_CONSULT}

# ---- 就诊类型（DICT-VISIT.VISIT_TYPE） ----
TYPE_FIRST = "FIRST"
TYPE_FOLLOW_UP = "FOLLOW_UP"
# 就诊类型一律以 M1 字典 DICT-VISIT.VISIT_TYPE 为准（code 或 label）；
# 不接受字典外的自造字面量（FIRST_VISIT/INITIAL 之类），避免脏值落库。
_TYPE_CODES = (TYPE_FIRST, TYPE_FOLLOW_UP)

# 四诊字段（除 pulse_code 必填外，其余选填；值为 (列名, 标签, 最大长度)）
_FOUR_FIELDS = (
    ("inquiry_cold_heat", "问诊-寒热", 500),
    ("inquiry_sweat", "问诊-汗出", 500),
    ("inquiry_head_body", "问诊-头身", 500),
    ("inquiry_diet", "问诊-饮食口味", 500),
    ("inquiry_sleep", "问诊-睡眠", 500),
    ("inquiry_excretion", "问诊-二便", 500),
    ("inquiry_emotion", "问诊-情志与妇科", 500),
    ("inspection_face", "望诊-面色", 200),
    ("inspection_shape", "望诊-形态", 200),
    ("tongue_body", "舌质", 30),
    ("tongue_coating", "舌苔", 30),
    ("auscultation_voice", "闻诊-声音气息", 200),
    ("auscultation_smell", "闻诊-气味", 200),
    ("pulse_detail", "脉象补充说明", 200),
    ("four_diagnosis_summary", "四诊摘要", 500),
)
_FOUR_TONGUE_BODY = ("tongue_body", "DICT-TCM-SIGN", "TONGUE_BODY")
_FOUR_TONGUE_COATING = ("tongue_coating", "DICT-TCM-SIGN", "TONGUE_COATING")


# ------------------------------------------------------------------ 基础工具


def _dict_items(dict_id, type_code):
    return get_dictionary_items(dict_id, type_code)


def _codes(dict_id, type_code):
    return {i["code"] for i in _dict_items(dict_id, type_code)}


def _labels(dict_id, type_code, aliases=None):
    out = {}
    for i in _dict_items(dict_id, type_code):
        out[i["code"]] = i["label"]
    for code, label in (aliases or {}).items():
        out.setdefault(code, label)
    return out


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value)


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_dt(value, label, default=None):
    """入参时间归一化为 `YYYY-MM-DD HH:MM:SS`；缺省取 default（未给则当前时间）。"""
    text = _text(value)
    if not text:
        return default if default is not None else _now()
    raw = text.replace("T", " ").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError("%s格式应为 yyyy-MM-dd HH:mm:ss" % label)


def _as_dt(value):
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text.replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _clip(value, label, max_len):
    text = _text(value)
    if len(text) > max_len:
        raise ValueError("%s不能超过 %d 字" % (label, max_len))
    return text


def status_label(code):
    code = _STATUS_ALIAS.get(_text(code).upper(), _text(code))
    labels = _labels("DICT-VISIT", "VISIT_STATUS", {STATUS_IN_CONSULT: "接诊中"})
    return labels.get(code, code)


def type_label(code):
    labels = _labels("DICT-VISIT", "VISIT_TYPE")
    return labels.get(_text(code), _text(code))


def default_dept_code():
    """M1：科室默认取当前门诊科室（单机构字典 → 取字典首项）。"""
    for i in _dict_items("DICT-VISIT", "DEPT"):
        return i["code"]
    return ""


def _norm_status_filter(value):
    text = _text(value).upper()
    if not text:
        return ""
    return _STATUS_ALIAS.get(text, text)


def _norm_visit_type(value):
    """就诊类型归一：字典 code / 字典 label → 字典 code；其余一律拒绝。"""
    text = _text(value).upper()
    if text in _codes("DICT-VISIT", "VISIT_TYPE"):
        return text
    labels = {_text(i.get("label")).upper(): i["code"] for i in _dict_items("DICT-VISIT", "VISIT_TYPE")}
    if text in labels:
        return labels[text]
    raise ValueError("就诊类型取值不在字典范围内：%s" % _text(value))


def _norm_dept_code(value):
    """科室归一：字典 code / 字典 label → 字典 code；空值取默认科室；其余拒绝。"""
    text = _text(value)
    if not text:
        return default_dept_code()
    if text in _codes("DICT-VISIT", "DEPT"):
        return text
    labels = {_text(i.get("label")): i["code"] for i in _dict_items("DICT-VISIT", "DEPT")}
    if text in labels:
        return labels[text]
    raise ValueError("科室取值不在字典范围内：%s" % text)


# ------------------------------------------------------------------ 查询

_SELECT = """
SELECT v.*, p.patient_no, p.patient_name, p.gender, p.age, p.phone,
       pv.visit_no AS previous_visit_no, u.real_name AS doctor_name
FROM visit v
LEFT JOIN patient p ON p.id = v.patient_id
LEFT JOIN visit pv ON pv.id = v.previous_visit_id
LEFT JOIN sys_user u ON CAST(v.doctor_id AS INTEGER) = u.id
"""


def _decorate(row):
    if not row:
        return row
    row["visit_status_label"] = status_label(row.get("visit_status"))
    row["visit_type_label"] = type_label(row.get("visit_type"))
    dept = {i["code"]: i["label"] for i in _dict_items("DICT-VISIT", "DEPT")}
    row["dept_code_label"] = dept.get(row.get("dept_code"), row.get("dept_code"))
    return row


def get_visit(visit_id, conn=None):
    """按 id 取就诊记录（含患者姓名等展示字段与状态 label）；不存在返回 None。

    供药房模块（处方链路）调用：只读，不改变任何状态。
    """
    try:
        visit_id = int(visit_id)
    except (TypeError, ValueError):
        return None
    row = db.query_one(_SELECT + " WHERE v.id = ? AND v.flag = 1", (visit_id,), conn)
    return _decorate(row)


def get_visit_detail(visit_id, conn=None):
    """GET /api/visit/{id} 详情：就诊 + 四诊 + 辨证结论摘要 + 处方摘要。"""
    row = get_visit(visit_id, conn)
    if not row:
        return None

    four = get_four_diagnosis(visit_id, conn)
    row["four_diagnosis"] = four
    row["four_diagnosis_id"] = four.get("four_diagnosis_id") if four else None

    diagnoses = db.query(
        """
        SELECT d.*, s.syndrome_code, s.syndrome_name
        FROM syndrome_diagnosis d
        LEFT JOIN syndrome_type s ON s.id = d.syndrome_id
        WHERE d.visit_id = ? AND d.flag = 1 ORDER BY d.id
        """,
        (row["id"],),
        conn,
    )
    status_labels = _labels("DICT-SYNDROME", "CONCLUSION_STATUS")
    nature_labels = _labels("DICT-SYNDROME", "SYNDROME_NATURE")
    for d in diagnoses:
        d["conclusion_status_label"] = status_labels.get(d["conclusion_status"], d["conclusion_status"])
        d["syndrome_nature_label"] = nature_labels.get(d["syndrome_nature"], d["syndrome_nature"])
    row["syndrome_diagnoses"] = diagnoses

    prescriptions = db.query(
        "SELECT id, prescription_no, prescription_type, doses, doctor_id, prescribe_time, "
        "prescription_status FROM prescription WHERE visit_id = ? AND flag = 1 ORDER BY id",
        (row["id"],),
        conn,
    )
    p_labels = _labels("DICT-PRESCRIPTION", "PRESCRIPTION_STATUS")
    for rx in prescriptions:
        rx["prescription_status_label"] = p_labels.get(rx["prescription_status"], rx["prescription_status"])
    row["prescriptions"] = prescriptions
    row["prescription_count"] = len(prescriptions)
    row["has_four_diagnosis"] = bool(four)
    return row


def list_visits(page=1, size=10, filters=None, forced_status=None):
    filters = dict(filters or {})
    if forced_status:
        filters["visit_status"] = forced_status
    where = "WHERE v.flag = 1"
    params = []
    if filters.get("visit_no"):
        where += " AND v.visit_no LIKE ?"
        params.append("%%%s%%" % filters["visit_no"])
    if filters.get("patient_id") not in (None, ""):
        try:
            pid = int(filters["patient_id"])
        except (TypeError, ValueError):
            raise ValueError("患者标识非法")
        where += " AND v.patient_id = ?"
        params.append(pid)
    if filters.get("patient_name"):
        where += " AND p.patient_name LIKE ?"
        params.append("%%%s%%" % filters["patient_name"])
    if filters.get("visit_type"):
        where += " AND v.visit_type = ?"
        params.append(_norm_visit_type(filters["visit_type"]))
    if filters.get("visit_status"):
        where += " AND v.visit_status = ?"
        params.append(_norm_status_filter(filters["visit_status"]))
    if filters.get("dept_code"):
        where += " AND v.dept_code = ?"
        params.append(filters["dept_code"])
    if filters.get("doctor_id"):
        where += " AND v.doctor_id = ?"
        params.append(_text(filters["doctor_id"]))
    if filters.get("date_from"):
        where += " AND date(v.register_time) >= date(?)"
        params.append(filters["date_from"])
    if filters.get("date_to"):
        where += " AND date(v.register_time) <= date(?)"
        params.append(filters["date_to"])

    total = db.query_one(
        "SELECT COUNT(*) AS c FROM visit v LEFT JOIN patient p ON p.id = v.patient_id " + where, params
    )["c"]
    rows = db.query(
        _SELECT + where + " ORDER BY v.register_time DESC, v.id DESC LIMIT ? OFFSET ?",
        params + [int(size), (int(page) - 1) * int(size)],
    )
    return {"list": [_decorate(r) for r in rows], "total": total, "page": int(page), "size": int(size)}


def list_pending(page=1, size=10, filters=None):
    """待接诊列表：visit_status = REGISTERED（UI-03 入口）。"""
    return list_visits(page, size, filters, forced_status=STATUS_REGISTERED)


def options(patient_id=None, keyword="", limit=100):
    """跳选框数据源（复诊选上次就诊 / 随访选本次就诊）：visit/pending 之外的精简列表。"""
    where = "WHERE v.flag = 1"
    params = []
    if patient_id not in (None, ""):
        try:
            patient_id = int(patient_id)
        except (TypeError, ValueError):
            raise ValueError("患者标识非法")
        where += " AND v.patient_id = ?"
        params.append(patient_id)
    if _text(keyword):
        where += " AND (v.visit_no LIKE ? OR p.patient_name LIKE ?)"
        params += ["%%%s%%" % keyword, "%%%s%%" % keyword]
    rows = db.query(
        _SELECT + where + " ORDER BY v.register_time DESC, v.id DESC LIMIT ?", params + [int(limit)]
    )
    return [
        {
            "id": r["id"],
            "visit_no": r["visit_no"],
            "register_time": r["register_time"],
            "doctor_id": r["doctor_id"],
            "visit_status": r["visit_status"],
            "visit_status_label": status_label(r["visit_status"]),
            "patient_id": r["patient_id"],
            "patient_name": r.get("patient_name"),
        }
        for r in rows
    ]


def get_four_diagnosis(visit_id, conn=None):
    row = db.query_one(
        "SELECT * FROM four_diagnosis WHERE visit_id = ? AND flag = 1", (int(visit_id),), conn
    )
    return _decorate_four(row)


def _decorate_four(row):
    if not row:
        return None
    tb = {i["code"]: i["label"] for i in _dict_items(*_FOUR_TONGUE_BODY[1:])}
    tc = {i["code"]: i["label"] for i in _dict_items(*_FOUR_TONGUE_COATING[1:])}
    pulse = {i["code"]: i["label"] for i in _dict_items("DICT-TCM-SIGN", "PULSE")}
    row["tongue_body_label"] = tb.get(row.get("tongue_body"), row.get("tongue_body"))
    row["tongue_coating_label"] = tc.get(row.get("tongue_coating"), row.get("tongue_coating"))
    row["pulse_code_label"] = pulse.get(row.get("pulse_code"), row.get("pulse_code"))
    return row


def _norm_dict_value(value, dict_id, type_code):
    """字典字段归一：字典 code / 字典 label → 字典 code；命中不了则拒绝（不静默落库）。

    模型是唯一语义来源（M1 属性的数据结构为字典引用），故字典外的取值必须报错，
    否则脏值会顺着四诊/辨证一路写进库并被报表按字典统计漏掉。
    """
    text = _text(value)
    if not text:
        return None
    items = _dict_items(dict_id, type_code)
    for i in items:
        if text == i["code"]:
            return i["code"]
    for i in items:
        if text == i["label"]:
            return i["code"]
    raise ValueError("取值不在字典 %s.%s 范围内：%s" % (dict_id, type_code, text))


# ------------------------------------------------------------------ Visit_Register


def _resolve_patient(patient_id):
    if patient_id in (None, ""):
        raise ValueError("患者必填")
    try:
        patient_id = int(patient_id)
    except (TypeError, ValueError):
        raise ValueError("患者标识非法")
    patient = db.query_one("SELECT * FROM patient WHERE id = ? AND flag = 1", (patient_id,))
    if not patient:
        raise ValueError("患者不存在或已删除")
    if patient["patient_status"] != "ACTIVE":
        raise ValueError("患者已停用，不可挂号")
    return patient


def register_visit(data, user):
    """Visit_Register：生成 visit_no（ZC+6）、visit_status=REGISTERED（§8.6）。"""
    patient = _resolve_patient(data.get("patient_id"))
    visit_type = _norm_visit_type(data.get("visit_type"))
    if not visit_type:
        raise ValueError("就诊类型必填")

    previous_visit_id = data.get("previous_visit_id")
    if previous_visit_id in (None, ""):
        previous_visit_id = None
    else:
        try:
            previous_visit_id = int(previous_visit_id)
        except (TypeError, ValueError):
            raise ValueError("上次就诊标识非法")
        prev = db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (previous_visit_id,))
        if not prev:
            raise ValueError("上次就诊记录不存在或已删除")
        if prev["patient_id"] != patient["id"]:
            raise ValueError("上次就诊记录不属于该患者")
    if visit_type == TYPE_FOLLOW_UP and previous_visit_id is None:
        raise ValueError("就诊类型为复诊时必须选择上次就诊记录")  # §8.6

    # M1 v1.5：主诉由接诊环节录入并必填（挂号屏 MU 无该元素），此处仅做长度约束
    chief = _clip(data.get("chief_complaint"), "主诉", 200) or None

    dept_code = _norm_dept_code(data.get("dept_code"))
    register_time = _norm_dt(data.get("register_time"), "挂号时间")
    doctor_id = _text(data.get("doctor_id")) or (str(user["id"]) if user else "")
    if not doctor_id:
        raise ValueError("接诊医师必填")
    fields = {
        "patient_id": patient["id"],
        "visit_type": visit_type,
        "previous_visit_id": previous_visit_id,
        "register_time": register_time,
        "doctor_id": doctor_id,
        "dept_code": dept_code,
        "chief_complaint": chief,
        "present_illness": _clip(data.get("present_illness"), "现病史", 1000) or None,
        "past_history": _clip(data.get("past_history"), "既往史", 1000) or None,
        "vital_signs": _clip(data.get("vital_signs"), "生命体征", 200) or None,
        "remark": _clip(data.get("remark"), "备注", 500) or None,
    }

    def _do(conn):
        no = next_code("visit", TABLE, "visit_no", conn)
        return db.execute(
            """
            INSERT INTO visit (visit_no, patient_id, visit_type, previous_visit_id, register_time,
                doctor_id, dept_code, chief_complaint, present_illness, past_history, vital_signs,
                visit_status, remark, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (no, fields["patient_id"], fields["visit_type"], fields["previous_visit_id"],
             fields["register_time"], fields["doctor_id"], fields["dept_code"],
             fields["chief_complaint"], fields["present_illness"], fields["past_history"],
             fields["vital_signs"], STATUS_REGISTERED, fields["remark"],
             user["id"] if user else None, user["id"] if user else None),
            conn,
        )[0]

    visit_id = db.transaction(_do)
    return get_visit_detail(visit_id)


# ------------------------------------------------------------------ Visit_Receive


def receive_visit(visit_id, data, user):
    """Visit_Receive：仅 REGISTERED 可接诊 → IN_CONSULT；医师置为当前登录用户。"""
    visit = db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (int(visit_id),))
    if not visit:
        raise ValueError("就诊记录不存在或已删除")
    if visit["visit_status"] != STATUS_REGISTERED:
        raise ValueError("仅「已挂号」状态的就诊可接诊（当前状态：%s）" % status_label(visit["visit_status"]))

    receive_time = _norm_dt(data.get("receive_time"), "接诊时间")
    register_dt = _as_dt(visit["register_time"])
    receive_dt = _as_dt(receive_time)
    # REF-05（M1 不变性）：receiveTime >= registerTime，严格按时刻比较
    if register_dt and receive_dt and receive_dt < register_dt:
        raise ValueError("接诊时间不得早于挂号时间")

    chief = _clip(data.get("chief_complaint"), "主诉", 200) or visit["chief_complaint"]
    if not chief:
        raise ValueError("主诉必填")

    doctor_id = str(user["id"]) if user else visit["doctor_id"]  # M2 后置条件：接诊医师=当前用户
    new = {
        "receive_time": receive_time,
        "doctor_id": doctor_id,
        "dept_code": _norm_dept_code(data.get("dept_code") or visit["dept_code"]),
        "chief_complaint": chief,
        "present_illness": _clip(data.get("present_illness"), "现病史", 1000) or visit["present_illness"],
        "past_history": _clip(data.get("past_history"), "既往史", 1000) or visit["past_history"],
        "vital_signs": _clip(data.get("vital_signs"), "生命体征", 200) or visit["vital_signs"],
        "remark": _clip(data.get("remark"), "备注", 500) or visit["remark"],
    }
    db.execute(
        """
        UPDATE visit SET receive_time = ?, doctor_id = ?, dept_code = ?, chief_complaint = ?,
            present_illness = ?, past_history = ?, vital_signs = ?, remark = ?,
            visit_status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND flag = 1 AND visit_status = ?
        """,
        (new["receive_time"], new["doctor_id"], new["dept_code"], new["chief_complaint"],
         new["present_illness"], new["past_history"], new["vital_signs"], new["remark"],
         STATUS_IN_CONSULT, user["id"] if user else None, int(visit_id), STATUS_REGISTERED),
    )
    return get_visit_detail(visit_id)


# ------------------------------------------------------------------ Visit_SaveFourDiagnosis


def save_four_diagnosis(visit_id, data, user):
    """Visit_SaveFourDiagnosis：仅 IN_CONSULT 可录；pulse_code 必填；同就诊唯一一份（更新语义）。"""
    visit = db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (int(visit_id),))
    if not visit:
        raise ValueError("就诊记录不存在或已删除")
    if visit["visit_status"] != STATUS_IN_CONSULT:
        raise ValueError("仅「接诊中」状态的就诊可录入四诊信息（当前状态：%s）"
                         % status_label(visit["visit_status"]))

    pulse_code = _norm_dict_value(data.get("pulse_code"), "DICT-TCM-SIGN", "PULSE")
    if not pulse_code:
        raise ValueError("脉象必填")
    if len(pulse_code) > 30:
        raise ValueError("脉象取值过长")

    values = {}
    for col, label, max_len in _FOUR_FIELDS:
        value = data.get(col)
        if col in (_FOUR_TONGUE_BODY[0], _FOUR_TONGUE_COATING[0]):
            value = _norm_dict_value(value, "DICT-TCM-SIGN",
                                     "TONGUE_BODY" if col == _FOUR_TONGUE_BODY[0] else "TONGUE_COATING")
            if value and len(value) > max_len:
                raise ValueError("%s取值过长" % label)
            values[col] = value or None
        else:
            values[col] = _clip(value, label, max_len) or None
    values["pulse_code"] = pulse_code

    cols = [c for c, _, _ in _FOUR_FIELDS] + ["pulse_code"]
    existing = db.query_one("SELECT id FROM four_diagnosis WHERE visit_id = ? AND flag = 1", (int(visit_id),))

    def _do(conn):
        if existing:
            db.execute(
                "UPDATE four_diagnosis SET %s, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND flag = 1" % ", ".join("%s = ?" % c for c in cols),
                [values[c] for c in cols] + [user["id"] if user else None, existing["id"]],
                conn,
            )
            return existing["id"]
        four_no = generate_code("FD", FOUR_TABLE, "four_diagnosis_id", conn, 6)
        return db.execute(
            "INSERT INTO four_diagnosis (visit_id, four_diagnosis_id, %s, created_by, updated_by) "
            "VALUES (?, ?, %s, ?, ?)" % (", ".join(cols), ", ".join("?" for _ in cols)),
            [int(visit_id), four_no] + [values[c] for c in cols] + [user["id"] if user else None,
                                                                   user["id"] if user else None],
            conn,
        )[0]

    try:
        db.transaction(_do)
    except sqlite3.IntegrityError:
        # ux_four_diagnosis_visit：并发下同就诊重复插入 → 转中文提示（不透出英文异常）
        raise ValueError("该就诊已存在四诊信息，请刷新后重新保存")
    return get_four_diagnosis(visit_id)


# ------------------------------------------------------------------ Visit_Cancel


def cancel_visit(visit_id, data, user):
    """Visit_Cancel：仅 REGISTERED/IN_CONSULT；该就诊无任何处方；撤销原因必填并追加到 remark。"""
    visit = db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (int(visit_id),))
    if not visit:
        raise ValueError("就诊记录不存在或已删除")
    if visit["visit_status"] not in (STATUS_REGISTERED, STATUS_IN_CONSULT):
        raise ValueError("仅「已挂号」或「接诊中」状态的就诊可撤销（当前状态：%s）"
                         % status_label(visit["visit_status"]))

    reason = _text(data.get("cancel_reason"))
    if not reason:
        raise ValueError("撤销原因必填")
    if len(reason) > 200:
        raise ValueError("撤销原因不能超过 200 字")

    used = db.query_one(
        "SELECT COUNT(*) AS c FROM %s WHERE visit_id = ? AND flag = 1" % PRESCRIPTION_TABLE,
        (int(visit_id),),
    )["c"]
    if used:
        raise ValueError("该就诊下已存在处方，不可撤销就诊")

    remark = (visit["remark"] + "\n" if visit["remark"] else "") + "撤销原因：" + reason
    if len(remark) > 500:
        remark = remark[:500]
    db.execute(
        "UPDATE visit SET visit_status = ?, remark = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND flag = 1 AND visit_status IN (?, ?)",
        (STATUS_CANCELLED, remark, user["id"] if user else None, int(visit_id),
         STATUS_REGISTERED, STATUS_IN_CONSULT),
    )
    return get_visit_detail(visit_id)


# ------------------------------------------------------------------ Visit_Complete（系统行为）


def complete_visit(visit_id, conn, allow_idempotent=False):
    """系统行为 Visit_Complete：就诊置 COMPLETED（处方提交链 §8.3 步骤 3 调用）。

    :param visit_id: 就诊主键
    :param conn: **必须**传入调用方事务连接，与调用方同事务提交/回滚
    :param allow_idempotent: True 时若已是 COMPLETED 直接返回（不报错）；默认 False 严格按契约抛错
    :return: 更新后的就诊记录 dict（含 visit_status_label）
    :raises ValueError: 就诊不存在，或当前状态不为 IN_CONSULT（且未开幂等）
    """
    if conn is None:
        raise ValueError("complete_visit 必须在调用方事务内执行（需传入 conn）")
    row = db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (int(visit_id),), conn)
    if not row:
        raise ValueError("就诊记录不存在或已删除")
    if row["visit_status"] == STATUS_COMPLETED:
        if allow_idempotent:
            return get_visit(visit_id, conn)
        raise ValueError("就诊已完成，不可重复完成")
    if row["visit_status"] != STATUS_IN_CONSULT:
        raise ValueError("仅「接诊中」状态的就诊可完成为「已完成」（当前状态：%s）"
                         % status_label(row["visit_status"]))
    db.execute(
        "UPDATE visit SET visit_status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1",
        (STATUS_COMPLETED, int(visit_id)),
        conn,
    )
    return get_visit(visit_id, conn)

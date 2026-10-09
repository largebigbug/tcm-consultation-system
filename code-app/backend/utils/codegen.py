"""业务编号生成（《本体模型业务功能开发指导书》§3.1）。

本项目按需求文档口径给出逐对象规则（见 docs/批次1-实现契约.md §2.2）：
    Patient 患者       PA + 6 位流水   PA000001
    Visit 就诊        ZC + 6 位流水   ZC000001
    SyndromeDiagnosis 辨证 BZ + 6 位流水  BZ000001
    Prescription 处方  CF + 6 位流水   CF000001
    DispenseRecord     FY + 6 位流水   FY000001
    FollowUp 随访      SF + 4 位流水   SF0001
    HerbStockFlow 流水 LS + 6 位流水   LS000001
    SyndromeType 证型  Z  + 3 位流水   Z001
    FormulaTemplate 方剂 F + 3 位流水  F001
    Herb 饮片          Y  + 4 位流水   Y0001
必须在业务事务内调用（传入 conn），避免并发重号。
"""
import re

import db

# 对象键 → (前缀, 流水位数)
NUMBERING = {
    # 批次 1
    "patient": ("PA", 6),            # 需求：两位前缀 + 六位流水
    "syndrome": ("Z", 3),            # 需求：Z + 三位流水
    "formula": ("F", 3),             # 需求：F + 三位流水
    "herb": ("Y", 4),                # 需求：Y + 四位流水
    "herb_stock_flow": ("LS", 6),    # 需求附录 D UI-09 原型：LS000128
    # 批次 2（需求附录 D UI 原型：ZC000001 / CF000001 / FY000001 / SF0001）
    "visit": ("ZC", 6),
    "syndrome_diagnosis": ("BZ", 6),  # 需求未给示例，按同类口径落地补充
    "prescription": ("CF", 6),
    "dispense_record": ("FY", 6),
    "follow_up": ("SF", 4),
}


def prefix_of(alias: str) -> str:
    """按英文别名派生前缀（无显式规则时的兜底：大写取前 3 位）。"""
    return re.sub(r"[^A-Za-z]", "", alias).upper()[:3]


def next_code(obj_key: str, table: str, column: str, conn=None) -> str:
    """按 NUMBERING 表生成编号；obj_key 形如 patient / syndrome / formula / herb / herb_stock_flow。"""
    if obj_key not in NUMBERING:
        prefix, digits = prefix_of(obj_key), 4
    else:
        prefix, digits = NUMBERING[obj_key]
    return generate_code(prefix, table, column, conn, digits)


def generate_code(prefix: str, table: str, column: str, conn=None, digits: int = 4) -> str:
    """生成业务编号：前缀 + 定长流水号，如 ('PA', 'patient', 'patient_no', conn, 6) -> PA000001。"""
    row = db.query_one(
        f"SELECT MAX({column}) AS mx FROM {table} WHERE {column} LIKE ?",
        (f"{prefix}%",),
        conn,
    )
    cur = 0
    if row and row["mx"]:
        m = re.match(rf"^{re.escape(prefix)}(\d+)$", row["mx"])
        if m:
            cur = int(m.group(1))
    return f"{prefix}{cur + 1:0{digits}d}"

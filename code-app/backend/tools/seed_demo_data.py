# -*- coding: utf-8 -*-
"""批次 1 演示数据：真实中医内容，全部经 service 层写入（编号、规则、事务与界面一致）。

用法（后端 venv 解释器）：
  D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe tools/seed_demo_data.py
已有业务数据时自动跳过；加 --force 可强制再灌一份。
"""
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import db  # noqa: E402
from config import settings  # noqa: E402
from ontology import registry as registry_module  # noqa: E402
from services import formula_service, herb_service, patient_service, syndrome_service  # noqa: E402

db.init_db_path(settings.resolve_db_path())
registry_module.load_ontology()  # 字典/规则校验依赖注册表

KUFANG = {"id": 5, "username": "kufang", "real_name": "孙库管"}   # ROLE-04 库房管理员
DAOTHEN = {"id": 2, "username": "daozhen", "real_name": "王导诊"}  # ROLE-01 导诊员
KESHI = {"id": 6, "username": "keshi", "real_name": "周科长"}      # ROLE-05 科室管理员

PATIENTS = [
    {"patient_name": "张伟", "gender": "MALE", "birth_date": "1980-05-06", "phone": "13801234567",
     "occupation": "教师", "address": "北京市朝阳区建国路88号", "allergy_history": "青霉素过敏"},
    {"patient_name": "李静", "gender": "FEMALE", "birth_date": "1992-11-20", "phone": "13902345678",
     "occupation": "会计", "address": "上海市静安区南京西路100号"},
    {"patient_name": "王秀英", "gender": "FEMALE", "birth_date": "1957-03-15", "phone": "13703456789",
     "occupation": "退休", "address": "广州市越秀区中山五路30号", "allergy_history": "无"},
]

SYNDROMES = [
    {"syndrome_name": "肝气郁结证", "diagnosis_method": "ZANGFU", "syndrome_description": "情志抑郁，胸胁胀痛，善太息",
     "common_symptoms": "胸闷、胁痛、善太息、月经不调", "corresponding_treatment": "疏肝解郁"},
    {"syndrome_name": "气血两虚证", "diagnosis_method": "QI_BLOOD_FLUID", "syndrome_description": "面色苍白，气短乏力，心悸失眠",
     "common_symptoms": "乏力、心悸、头晕、面色少华", "corresponding_treatment": "益气养血"},
    {"syndrome_name": "脾胃湿热证", "diagnosis_method": "ZANGFU", "syndrome_description": "脘腹胀满，口苦口黏，大便黏滞不爽",
     "common_symptoms": "脘痞、口苦、便溏黏、舌苔黄腻", "corresponding_treatment": "清热化湿、健脾和胃"},
    {"syndrome_name": "风寒感冒证", "diagnosis_method": "WEIQI_YINGXUE", "syndrome_description": "恶寒重，发热轻，无汗，鼻塞流清涕",
     "common_symptoms": "恶寒、无汗、鼻塞、头痛身痛", "corresponding_treatment": "辛温解表"},
    {"syndrome_name": "肾阳虚证", "diagnosis_method": "ZANGFU", "syndrome_description": "腰膝酸软，畏寒肢冷，夜尿频多",
     "common_symptoms": "腰酸、畏寒、夜尿多、精神不振", "corresponding_treatment": "温补肾阳"},
    {"syndrome_name": "痰湿内蕴证", "diagnosis_method": "EIGHT_PRINCIPLES", "syndrome_description": "形体肥胖，胸闷痰多，舌苔白腻",
     "common_symptoms": "胸闷、痰多、头重、苔白腻", "corresponding_treatment": "燥湿化痰"},
]

# (饮片名, 类别, 最小量, 最大量, 毒性, 别名, 性味归经, 功效, 产地, 预警值, 入库量, 特殊管理)
HERBS = [
    ("当归", "TONIFYING", 6, 12, "NONE", "干归", "甘辛温，归肝心脾经", "补血活血、调经止痛", "甘肃岷县", 500, 3000, False),
    ("白芍", "TONIFYING", 6, 15, "NONE", "白芍药", "苦酸微寒，归肝脾经", "养血敛阴、柔肝止痛", "安徽亳州", 500, 2500, False),
    ("柴胡", "RELIEVING_EXTERIOR", 3, 10, "NONE", "北柴胡", "辛苦微寒，归肝胆经", "和解退热、疏肝升阳", "河北安国", 300, 1500, False),
    ("茯苓", "DIURETIC", 9, 15, "NONE", "云苓", "甘淡平，归心肺脾肾经", "利水渗湿、健脾宁心", "云南丽江", 500, 4000, False),
    ("白术", "TONIFYING", 6, 12, "NONE", "于术", "苦甘温，归脾胃经", "健脾益气、燥湿利水", "浙江磐安", 400, 2000, False),
    ("甘草", "TONIFYING", 2, 10, "NONE", "国老", "甘平，归心肺脾胃经", "补脾益气、调和诸药", "内蒙古杭锦旗", 600, 5000, False),
    ("黄芪", "TONIFYING", 9, 30, "NONE", "绵黄芪", "甘微温，归脾肺经", "补气升阳、固表止汗", "山西浑源", 800, 4000, False),
    ("党参", "TONIFYING", 9, 30, "NONE", "潞党参", "甘平，归脾肺经", "补中益气、健脾益肺", "甘肃定西", 600, 3000, False),
    ("陈皮", "REGULATING_QI", 3, 10, "NONE", "橘皮", "辛苦温，归脾肺经", "理气健脾、燥湿化痰", "广东新会", 400, 2000, False),
    ("半夏", "STOPPING_COUGH", 3, 9, "SLIGHT", "三叶半夏", "辛温有毒，归脾胃肺经", "燥湿化痰、降逆止呕", "四川南充", 300, 200, True),
]

FORMULAS = [
    {"formula_name": "逍遥散", "formula_type": "CLASSIC", "source": "《太平惠民和剂局方》",
     "function": "疏肝解郁、健脾养血", "indication": "肝气郁结证，两胁作痛、神疲食少", "default_doses": 7,
     "items": [("当归", 10), ("白芍", 12), ("柴胡", 6), ("茯苓", 12), ("白术", 10), ("甘草", 3)]},
    {"formula_name": "四君子汤", "formula_type": "CLASSIC", "source": "《太平惠民和剂局方》",
     "function": "益气健脾", "indication": "脾胃气虚证，面色萎白、食少便溏", "default_doses": 7,
     "items": [("党参", 12), ("白术", 10), ("茯苓", 12), ("甘草", 3)]},
]


def main():
    force = "--force" in sys.argv
    conn = db.connect()
    try:
        n = db.query_one("SELECT COUNT(*) AS c FROM patient", (), conn)["c"]
        if n and not force:
            print("已有 %d 条患者数据，跳过（如需重灌加 --force）" % n)
            return 0
    finally:
        conn.close()

    print("=== 患者（3） ===")
    for p in PATIENTS:
        row = patient_service.create_patient(dict(p), DAOTHEN)
        print("  %s %s（年龄 %s）" % (row["patient_no"], row["patient_name"], row["age"]))

    print("=== 证型字典（6） ===")
    for s in SYNDROMES:
        row = syndrome_service.create_syndrome(dict(s), KESHI)
        print("  %s %s（%s）" % (row["syndrome_code"], row["syndrome_name"], row["diagnosis_method"]))

    print("=== 饮片建档与入库（10） ===")
    name2id = {}
    for idx, (name, cat, lo, hi, tox, alias, nature, eff, origin, warn, qty, special) in enumerate(HERBS, start=1):
        row = herb_service.create_herb({
            "herb_name": name, "alias_name": alias, "herb_category": cat,
            "nature_meridian": nature, "efficacy": eff, "origin": origin,
            "min_common_dose": lo, "max_common_dose": hi, "toxicity_level": tox,
            "special_managed": special, "low_stock_threshold": warn, "spec": "统货",
        }, KUFANG)
        name2id[name] = row["id"]
        herb_service.inbound(row["id"], {
            "quantity": qty, "biz_date": "2026-09-30 09:%02d:00" % idx,
            "inbound_no": "RK20260930%03d" % idx, "remark": "首批验收入库",
        }, KUFANG)
        after = herb_service.get_herb(row["id"])
        print("  %s %s 入库 %sg → 库存 %sg%s" % (
            row["herb_code"], name, qty, after["stock_quantity"],
            "（低于预警值，界面应显示预警）" if float(after["stock_quantity"]) < warn else ""))

    print("=== 方剂模板（2） ===")
    for f in FORMULAS:
        items = [{"seq_no": i, "herb_id": name2id[hn], "common_dose": dose, "decoction_method": "NONE"}
                 for i, (hn, dose) in enumerate(f["items"], start=1)]
        payload = {k: v for k, v in f.items() if k != "items"}
        payload["items"] = items
        row = formula_service.create_formula(payload, KESHI)
        print("  %s %s（%d 味）" % (row["formula_code"], row["formula_name"], len(items)))

    print("\n演示数据写入完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

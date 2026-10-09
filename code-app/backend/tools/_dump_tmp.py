
import json, yaml, sys
sys.path.insert(0, r"D:/hermes/workspace/中医问诊系统/code-app/backend")
from ontology.registry import load_ontology
reg = load_ontology()
print("WHITELIST KEYS:", sorted(reg["db_whitelist"].keys()))
m7 = yaml.safe_load(open(r"D:/hermes/workspace/中医问诊系统/code-app/models/m7-report-model.yaml", encoding="utf-8"))
# print raw yaml text keys for one report
rep = [r for r in m7["query_reports"] if r["id"]=="RPT-HERB-USAGE-001"][0]
print(json.dumps(rep, ensure_ascii=False, indent=1))

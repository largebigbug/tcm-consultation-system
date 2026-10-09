# -*- coding: utf-8 -*-
"""mock provider：确定性离线实现（契约 §4 末「必须能驱动完整链路」）。

不联网、不用随机数：同一条输入永远产出同一串 Chunk，便于验收脚本断言
`message_start → delta → tool_call → tool_result → render_payload → message_end` 全序列。

意图路由（按最后一条用户消息的关键词，首个命中生效）：
  含「sql/SQL」        → `sql_readonly`（白名单内的样例查询）
  含「图/chart/图表」  → `chart`
  含「建档/新增患者」  → `action_Patient_Save`
  含「挂号」           → `action_Visit_Register`
  含「库存/预警」      → `query_Herb_QueryStockAndAlert`
  含「随访」           → `query_FollowUp_QueryCompletion`
  含「打开/跳转/页面」 → 可用的第一个 `nav_*`
  其它                 → `report_RPT-VISIT-STATS-001`

验收专用指令（仅 mock 生效，用于强制指定工具，含**强行调用未授权工具**的负例）：
  `#tool=<工具名>`  指定要调用的工具（可不在当前 schema 内）
  `#args={json}`    指定该工具的入参（缺省用意图默认值）
"""
import json
import re

from ai.providers.base import BaseProvider, Chunk

DIRECTIVE_TOOL_RE = re.compile(r"#tool=([A-Za-z0-9_.\-]+)")
DIRECTIVE_ARGS_RE = re.compile(r"#args=(\{.*\})", re.S)

SQL_SAMPLE = ("SELECT visit_no, register_time, visit_status, doctor_id "
              "FROM visit ORDER BY id DESC LIMIT 5")
CHART_ROWS = [
    {"statDate": "2026-09-01", "visitCount": 12},
    {"statDate": "2026-09-02", "visitCount": 15},
    {"statDate": "2026-09-03", "visitCount": 9},
]

#: (关键词组, 工具名, 默认入参) —— 顺序即优先级
INTENTS = (
    (("SQL", "sql"), "sql_readonly", {"sql": SQL_SAMPLE}),
    (("图表", "图", "chart"), "chart",
     {"chartType": "bar", "xField": "statDate", "yField": "visitCount", "rows": CHART_ROWS}),
    (("建档", "新增患者"), "action_Patient_Save", {}),
    (("挂号",), "action_Visit_Register", {}),
    (("库存", "预警"), "query_Herb_QueryStockAndAlert", {}),
    (("随访",), "query_FollowUp_QueryCompletion", {}),
    (("打开", "跳转", "页面", "去"), "nav___first__", {}),
    ((), "report_RPT-VISIT-STATS-001", {"granularity": "MONTH"}),
)


class MockProvider(BaseProvider):
    """确定性离线 provider（验收用）。"""

    name = "mock"
    supports_tool_round = False

    def __init__(self, model="mock-deterministic", **kwargs):
        BaseProvider.__init__(self, model=model or "mock-deterministic", **kwargs)

    # ------------------------------------------------------------ 意图路由

    @staticmethod
    def _names(tools):
        out = []
        for t in tools or []:
            fn = (t or {}).get("function") or {}
            if fn.get("name"):
                out.append(fn["name"])
        return out

    def _route(self, message, names):
        """返回 (工具名, 入参) —— 指令优先，其次关键词，最后兜底报表。"""
        m = DIRECTIVE_TOOL_RE.search(message or "")
        if m:
            args = {}
            am = DIRECTIVE_ARGS_RE.search(message or "")
            if am:
                try:
                    args = json.loads(am.group(1))
                except ValueError:
                    args = {}
            else:
                for _keys, name, defaults in INTENTS:
                    if name == m.group(1):
                        args = dict(defaults)
                        break
            return m.group(1), args

        lowered = (message or "")
        for keys, name, defaults in INTENTS:
            if not keys:
                continue
            if not any(k in lowered for k in keys):
                continue
            if name == "nav___first__":
                nav = [n for n in names if n.startswith("nav_")]
                if not nav:
                    continue
                return nav[0], dict(defaults)
            if name in names:
                return name, dict(defaults)
        return "report_RPT-VISIT-STATS-001", {"granularity": "MONTH"}

    # ------------------------------------------------------------ 主流程

    def chat(self, messages, tools=None):
        message = ""
        for item in reversed(messages or []):
            if (item or {}).get("role") == "user":
                message = item.get("content") or ""
                break
        names = self._names(tools)
        name, arguments = self._route(message, names)
        yield Chunk.delta("好的，正在为你处理：「%s」。\n" % (message or "")[:40])
        yield Chunk.tool_call(name, arguments, tool_call_id="call_mock_1")

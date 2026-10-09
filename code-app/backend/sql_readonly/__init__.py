# -*- coding: utf-8 -*-
"""批次 5 只读 SQL 工具（契约 §7）：守卫 + 受限执行。

对外只需 `sql_readonly.guard_sql`（校验）与 `sql_readonly.execute_readonly`（校验+受限执行）。
"""


class SqlRejected(ValueError):
    """SQL 被只读边界拒绝（中文原因 + rule 标记，供审计 recorded）。"""

    def __init__(self, message, rule="REJECTED"):
        ValueError.__init__(self, message)
        self.message = message
        self.rule = rule


class SqlTimeout(RuntimeError):
    """只读查询超过 timeout_seconds，被 progress handler 中断。"""


class SqlFailed(RuntimeError):
    """SQL 本身合法但执行失败（语法/字段不存在、列不存在等）。"""


from sql_readonly.guard import (  # noqa: E402  （放在异常定义之后，避免循环导入）
    execute_readonly,
    guard_sql,
    whitelist,
    whitelist_summary,
)

__all__ = ["SqlRejected", "SqlTimeout", "SqlFailed",
           "execute_readonly", "guard_sql", "whitelist", "whitelist_summary"]

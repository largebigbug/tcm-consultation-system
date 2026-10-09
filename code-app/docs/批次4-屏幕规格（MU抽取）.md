# 批次 4 · 屏幕规格（从 MU 机械抽取，禁手改）

> 来源：`yaml/mu-ui-model.yaml`（v1.0）｜屏幕 `frmHerbStock`（饮片库存与预警（含盘点））｜由 `tools/gen_batch4_spec.py` 生成。

## 1. 屏幕定义

| 字段 | 值 |
|---|---|
| `screenId` | `frmHerbStock` |
| `name` | 饮片库存与预警（含盘点） |
| `screenType` | QUERY_LIST |

## 2. 控件元素（25 个，控件 id 原样落地）

| # | 控件 id | 类型 | 标签 | io | dataBinding |
|---|---|---|---|---|---|
| 1 | `txtQryHerbName` | TEXTBOX | 饮片名称 | I | Herb.herbName |
| 2 | `cboQryHerbCategory` | COMBO | 药材类别 | I | Herb.herbCategory |
| 3 | `cboQryToxicityLevel` | COMBO | 毒性分级 | I | Herb.toxicityLevel |
| 4 | `cboQryAlertStatus` | COMBO | 预警状态 | I | — |
| 5 | `numQryStockFrom` | NUMBER | 库存数量从 | I | Herb.stockQuantity |
| 6 | `numQryStockTo` | NUMBER | 库存数量到 | I | Herb.stockQuantity |
| 7 | `chkOnlyAlert` | CHECKBOX | 仅看预警项 | I | — |
| 8 | `grdResult` | GRID | 库存与预警列表 | O | — |
| 9 | `lblPaging` | LABEL | 分页信息 | O | — |
| 10 | `cboPageSize` | COMBO | 每页条数 | I | — |
| 11 | `btnPrev` | BUTTON | 上一页 | — | — |
| 12 | `btnNext` | BUTTON | 下一页 | — | — |
| 13 | `btnQuery` | BUTTON | 查询 | — | — |
| 14 | `btnReset` | BUTTON | 重置 | — | — |
| 15 | `btnExport` | BUTTON | 导出 | — | — |
| 16 | `txtStocktakeHerbName` | TEXTBOX | 饮片 | O | Herb.herbName |
| 17 | `numStocktakeBookQty` | NUMBER | 账面库存 | O | Herb.stockQuantity |
| 18 | `numStocktakeQty` | NUMBER | 实盘数量 | I | — |
| 19 | `numAdjustQuantity` | NUMBER | 调整数量 | I | Herb.HerbStockFlow.quantity |
| 20 | `cboFlowBizType` | COMBO | 业务类型 | I | Herb.HerbStockFlow.bizType |
| 21 | `dtpBizDate` | DATEPICKER | 业务日期 | I | Herb.HerbStockFlow.bizDate |
| 22 | `txtOperatorId` | TEXTBOX | 操作人 | I | Herb.HerbStockFlow.operatorId |
| 23 | `txaStocktakeRemark` | TEXTAREA | 盘点/报损原因 | I | Herb.HerbStockFlow.remark |
| 24 | `btnStocktake` | BUTTON | 盘点 | — | — |
| 25 | `btnStocktakeCancel` | BUTTON | 取消 | — | — |

## 3. 功能点/动作（3 个）

| # | actionId | 名称 | 类型 | behaviorRef | permissionRef |
|---|---|---|---|---|---|
| 1 | `actQuery` | 查询 | BUTTON | `Herb_QueryStockAndAlert` | `PERM-QUERY-HERB-STOCK` |
| 2 | `actExport` | 导出 | BUTTON | `Herb_QueryStockAndAlert` | `PERM-QUERY-HERB-STOCK` |
| 3 | `actStocktake` | 盘点 | BUTTON | `Herb_Stocktake` | `PERM-HERB-STOCKTAKE` |

## 4. 布局原样（ASCII 原型）

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 库存管理 / 饮片库存与预警                                  │
├──────────────────────────────────────────────────────────────────────────┤
│          饮片名称: [txtQryHerbName]  药材类别: (cboQryHerbCategory)  毒性分级: (cboQryToxicityLevel) │
│          预警状态: (cboQryAlertStatus) 库存数量: [numQryStockFrom] ~ [numQryStockTo]  [chkOnlyAlert 仅看预警项] │
│          [btnQuery 查询] [btnReset 重置] [btnExport 导出]                 │
├──────────────────────────────────────────────────────────────────────────┤
│ @grdResult                                                                │
│  饮片编码 | 饮片名称 | 类别 | 毒性 | 库存（g） | 预警值（g） | 预警状态 | 最近入库 | 操作 │
│ 分页: [lblPaging 共N条] [cboPageSize 每页20条] [btnPrev 上一页] [btnNext 下一页] │
│ 行操作「盘点」打开下方弹窗（FUNC-12）                                      │
└──────────────────────────────────────────────────────────────────────────┘

（行操作「盘点」弹出对话框，页面本身不展示以下表单）
┌──────────────────────────────────────────────────────────────────────────┐
│ 库存盘点 / 报损                                                          │
│          饮片: [txtStocktakeHerbName 只读]    账面库存: [numStocktakeBookQty 只读] │
│          实盘数量: [numStocktakeQty]          调整数量: [numAdjustQuantity] │
│          业务类型: (cboFlowBizType)           业务日期: {dtpBizDate}       │
│          操作人: [txtOperatorId]                                          │
│          盘点/报损原因: [txaStocktakeRemark]                              │
│                                             [btnStocktake 盘点] [btnStocktakeCancel 取消] │
└──────────────────────────────────────────────────────────────────────────┘

```

## 5. 权限码（由 M5 permissionId 的 targetRef 机械派生）

| 权限 id | 派生权限码 | 说明 |
|---|---|---|
| `PERM-QUERY-HERB-STOCK` | `herb:query-stock-and-alert` | 查询 |
| `PERM-QUERY-HERB-STOCK` | `herb:query-stock-and-alert` | 导出 |
| `PERM-HERB-STOCKTAKE` | `herb:stocktake` | 盘点 |

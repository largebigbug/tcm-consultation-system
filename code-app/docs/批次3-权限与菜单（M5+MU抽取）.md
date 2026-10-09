# 批次 3 · 权限与菜单（由 M5+MU 机械抽取）

> 与 `批次3-实现契约.md` 同等效力；由 `tools/gen_batch3_spec.py` 生成，**不得手改**。
> 权限码由 M5 `targetRef`（= M2 行为 id）按 `seed.py::permission_code` 同一规则派生（`{对象}:{动作-kebab}`）。

## 一、批次 3 行为 → 权限码

| 行为 | 权限项 | 权限码 | 出现屏幕 |
|---|---|---|---|
| `FollowUp_QueryCompletion` | PERM-QUERY-FOLLOWUP | **`follow_up:query-completion`** | frmFollowUp, frmFollowUpAnalysis |
| `FollowUp_Complete` | PERM-FOLLOWUP-COMPLETE | **`follow_up:complete`** | frmFollowUp |
| `FollowUp_MarkLost` | PERM-FOLLOWUP-LOST | **`follow_up:mark-lost`** | frmFollowUp |
| `Visit_QueryStats` | PERM-QUERY-VISIT-STATS | **`visit:query-stats`** | frmVisitStats |
| `Diagnosis_QuerySyndromeDistribution` | PERM-QUERY-SYNDROME-DIST | **`diagnosis:query-syndrome-distribution`** | frmSyndromeDist |
| `Prescription_QueryHerbUsage` | PERM-QUERY-HERB-USAGE | **`prescription:query-herb-usage`** | frmHerbUsageStats |
| `Visit_QueryVisitAndPrescription` | PERM-QUERY-VISIT-PRESCRIPTION | **`visit:query-visit-and-prescription`** | frmVisitPrescriptionQuery |
| `Prescription_Cancel` | PERM-PRESCRIPTION-CANCEL | **`prescription:cancel`** | frmVisitPrescriptionQuery |
| `Prescription_QueryOverdoseReview` | PERM-QUERY-OVERDOSE-REVIEW | **`prescription:query-overdose-review`** | frmOverdoseLedger |

## 二、角色授权（M5）

| 角色 | 名称 | 是否持有本批权限 | 本批权限码 |
|---|---|---|---|
| ROLE-01 | 导诊员 | 是 | follow_up:complete, follow_up:mark-lost, follow_up:query-completion, visit:query-visit-and-prescription |
| ROLE-02 | 中医师 | 是 | diagnosis:query-syndrome-distribution, follow_up:complete, follow_up:mark-lost, follow_up:query-completion, prescription:cancel, visit:query-stats, visit:query-visit-and-prescription |
| ROLE-03 | 中药师 | 是 | prescription:query-overdose-review, visit:query-visit-and-prescription |
| ROLE-04 | 库房管理员 | 否 | —— |
| ROLE-05 | 科室管理员 | 是 | diagnosis:query-syndrome-distribution, follow_up:query-completion, prescription:cancel, prescription:query-herb-usage, prescription:query-overdose-review, visit:query-stats, visit:query-visit-and-prescription |
| ROLE-06 | 系统管理员 | 否 | —— |
| ROLE-07 | 系统自动执行主体 | 否 | —— |

## 三、菜单树（需求文档附录 D.3：一级菜单 7 个，仅二级关联界面）

| 一级菜单 | 二级菜单 | 界面 | screenId | 屏幕类型 |
|---|---|---|---|---|
| 门诊管理 | 患者建档 |  | frmPatientCreate | SINGLE_FORM |
| 门诊管理 | 门诊挂号（含撤销就诊） |  | frmVisitRegister | SINGLE_FORM |
| 门诊管理 | 接诊开单 |  | frmVisitReceive | SINGLE_FORM |
| 门诊管理 | 四诊录入 |  | frmFourDiagnosis | SINGLE_FORM |
| 门诊管理 | 辨证判定 |  | frmDiagnosisJudge | MASTER_DETAIL_FORM |
| 门诊管理 | 开具处方 |  | frmPrescription | MASTER_DETAIL_FORM |
| 药房管理 | 处方审核 |  | frmPrescriptionReview | SINGLE_FORM |
| 药房管理 | 调剂发药 |  | frmDispense | MASTER_DETAIL_FORM |
| 库存管理 | 饮片建档与入库 |  | frmHerbMaintain | MASTER_DETAIL_FORM |
| 库存管理 | 饮片库存与预警（含盘点） |  | frmHerbStock | QUERY_LIST |
| 随访管理 | 复诊随访登记 |  | frmFollowUp | LIST_MAINTENANCE |
| 统计报表 | 门诊量统计 |  | frmVisitStats | QUERY_LIST |
| 统计报表 | 证型分布统计 |  | frmSyndromeDist | QUERY_LIST |
| 统计报表 | 方剂与饮片使用统计 |  | frmHerbUsageStats | QUERY_LIST |
| 统计报表 | 就诊与处方记录查询 |  | frmVisitPrescriptionQuery | QUERY_LIST |
| 统计报表 | 超量·毒性处方审核台账 |  | frmOverdoseLedger | QUERY_LIST |
| 统计报表 | 随访完成与失访分析 |  | frmFollowUpAnalysis | QUERY_LIST |
| 基础数据 | 证型字典维护 |  | frmSyndromeMaintain | LIST_MAINTENANCE |
| 基础数据 | 方剂模板维护 |  | frmFormulaMaintain | MASTER_DETAIL_FORM |
| 系统管理 | 用户管理 |  |  |  |
| 系统管理 | 角色与权限配置 |  |  |  |
| 系统管理 | 菜单管理 |  |  |  |

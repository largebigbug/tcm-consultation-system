# 批次 3 · 屏幕规格（由 MU 机械抽取）

> 与 `批次3-实现契约.md` 同等效力；由 `tools/gen_batch3_spec.py` 从 `yaml/mu-ui-model.yaml` 生成，**不得手改**。
> 元素 `dataBinding` 的 `对象.属性` 需按下划线的 snake_case 落到表单/查询条件字段；`type` 与 MU 一致。


---

## frmFollowUp　复诊随访登记（LIST_MAINTENANCE）

### 动作（4 个）

| 动作 | 名称 | 类型 | 绑定行为 | 权限 | 权限码 |
|---|---|---|---|---|---|
| `actQuery` | 查询 | BUTTON | `FollowUp_QueryCompletion` | PERM-QUERY-FOLLOWUP | follow_up:query-completion（PERM-QUERY-FOLLOWUP） |
| `actExport` | 导出 | BUTTON | `FollowUp_QueryCompletion` | PERM-QUERY-FOLLOWUP | follow_up:query-completion（PERM-QUERY-FOLLOWUP） |
| `actSave` | 评价 | BUTTON | `FollowUp_Complete` | PERM-FOLLOWUP-COMPLETE | follow_up:complete（PERM-FOLLOWUP-COMPLETE） |
| `actMarkLost` | 标记失访 | BUTTON | `FollowUp_MarkLost` | PERM-FOLLOWUP-LOST | follow_up:mark-lost（PERM-FOLLOWUP-LOST） |

### 元素（25 个）

| 序号 | 元素 id | 类型 | 标签 | io | dataBinding | 其它 |
|---|---|---|---|---|---|---|
| 1 | `txtQryPatientName` | TEXTBOX | 患者姓名 | I | `Patient.patientName` |  |
| 2 | `dtpQryPlannedFrom` | DATEPICKER | 计划随访日期从 | I | `FollowUp.plannedFollowUpDate` |  |
| 3 | `dtpQryPlannedTo` | DATEPICKER | 计划随访日期到 | I | `FollowUp.plannedFollowUpDate` |  |
| 4 | `cboQryRecordStatus` | COMBO | 随访状态 | I | `FollowUp.recordStatus` |  |
| 5 | `grdFollowUpList` | GRID | 随访登记列表 | O | `` |  |
| 6 | `lblPaging` | LABEL | 分页信息 | O | `` |  |
| 7 | `cboPageSize` | COMBO | 每页条数 | I | `` |  |
| 8 | `btnPrev` | BUTTON | 上一页 | None | `` |  |
| 9 | `btnNext` | BUTTON | 下一页 | None | `` |  |
| 10 | `txtFollowUpNo` | TEXTBOX | 随访号 | O | `FollowUp.followUpNo` | {"required": true} |
| 11 | `lblPatientName` | TEXTBOX | 患者 | O | `Patient.patientName` |  |
| 12 | `pslSourceVisitId` | POPUP_SELECT | 上次就诊 | O | `FollowUp.sourceVisitId` | {"required": true} |
| 13 | `dtpPlannedFollowUpDate` | DATEPICKER | 计划随访日期 | O | `FollowUp.plannedFollowUpDate` | {"required": true} |
| 14 | `dtpActualFollowUpDate` | DATEPICKER | 实际随访日期 | I | `FollowUp.actualFollowUpDate` |  |
| 15 | `pslActualVisitId` | POPUP_SELECT | 本次就诊 | I | `FollowUp.actualVisitId` |  |
| 16 | `cboEfficacyLevel` | COMBO | 疗效评价 | I | `FollowUp.efficacyLevel` |  |
| 17 | `cboFollowUpStatus` | COMBO | 随访状态 | O | `FollowUp.recordStatus` | {"required": true} |
| 18 | `txaSymptomChange` | TEXTAREA | 症状变化 | I | `FollowUp.symptomChange` |  |
| 19 | `chkContinueMedication` | CHECKBOX | 是否继续用药 | I | `FollowUp.continueMedication` |  |
| 20 | `txaRemark` | TEXTAREA | 备注/失访原因 | I | `FollowUp.remark` |  |
| 21 | `btnQuery` | BUTTON | 查询 | None | `` |  |
| 22 | `btnExport` | BUTTON | 导出 | None | `` |  |
| 23 | `btnSave` | BUTTON | 评价 | None | `` |  |
| 24 | `btnMarkLost` | BUTTON | 标记失访 | None | `` |  |
| 25 | `btnCancel` | BUTTON | 取消 | None | `` |  |

### 布局（MU ASCII 原型）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 随访管理 / 复诊随访登记                                    │
├──────────────────────────────────────────────────────────────────────────┤
│          患者姓名: [txtQryPatientName]   计划随访日期: {dtpQryPlannedFrom} ~ {dtpQryPlannedTo} │
│          随访状态: (cboQryRecordStatus)                                   │
│          [btnQuery 查询] [btnExport 导出]                                  │
├──────────────────────────────────────────────────────────────────────────┤
│ @grdFollowUpList                                                          │
│  序号 | 随访号 | 患者 | 上次就诊 | 计划随访 | 实际随访 | 疗效 | 状态 | [评价/失访] │
│ 分页: [lblPaging 共N条] [cboPageSize 每页20条] [btnPrev 上一页] [btnNext 下一页] │
└──────────────────────────────────────────────────────────────────────────┘

（行操作「评价/失访」弹出对话框，页面本身不展示以下表单）
┌──────────────────────────────────────────────────────────────────────────┐
│ 随访评价登记 / 标记失访                                                   │
│          随访号: [txtFollowUpNo 只读]          患者    : [lblPatientName 只读] │
│          上次就诊: [pslSourceVisitId 只读]     计划随访日期: {dtpPlannedFollowUpDate 只读} │
│          实际随访日期: {dtpActualFollowUpDate} 本次就诊: [pslActualVisitId…]  │
│          疗效评价: (cboEfficacyLevel)          随访状态: (cboFollowUpStatus 只读) │
│          症状变化: [txaSymptomChange]                                      │
│          是否继续用药: [chkContinueMedication] 备注/失访原因: [txaRemark]   │
│                                [btnSave 评价] [btnMarkLost 标记失访] [btnCancel 取消] │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## frmVisitStats　门诊量统计（QUERY_LIST）

### 动作（2 个）

| 动作 | 名称 | 类型 | 绑定行为 | 权限 | 权限码 |
|---|---|---|---|---|---|
| `actQuery` | 查询 | BUTTON | `Visit_QueryStats` | PERM-QUERY-VISIT-STATS | visit:query-stats（PERM-QUERY-VISIT-STATS） |
| `actExport` | 导出 | BUTTON | `Visit_QueryStats` | PERM-QUERY-VISIT-STATS | visit:query-stats（PERM-QUERY-VISIT-STATS） |

### 元素（15 个）

| 序号 | 元素 id | 类型 | 标签 | io | dataBinding | 其它 |
|---|---|---|---|---|---|---|
| 1 | `dtpQryDateFrom` | DATEPICKER | 挂号日期从 | I | `Visit.registerTime` |  |
| 2 | `dtpQryDateTo` | DATEPICKER | 挂号日期到 | I | `Visit.registerTime` |  |
| 3 | `cboDateGranularity` | COMBO | 日期粒度 | I | `` |  |
| 4 | `cboQryDeptCode` | COMBO | 科室 | I | `Visit.deptCode` |  |
| 5 | `txtQryDoctorId` | TEXTBOX | 接诊医师 | I | `Visit.doctorId` |  |
| 6 | `cboQryVisitType` | COMBO | 就诊类型 | I | `Visit.visitType` |  |
| 7 | `cboQryVisitStatus` | COMBO | 就诊状态 | I | `Visit.visitStatus` |  |
| 8 | `grdResult` | GRID | 门诊量统计结果 | O | `` | {"dataSource": "RPT-VISIT-STATS-001"} |
| 9 | `lblPaging` | LABEL | 分页信息 | O | `` |  |
| 10 | `cboPageSize` | COMBO | 每页条数 | I | `` |  |
| 11 | `btnPrev` | BUTTON | 上一页 | None | `` |  |
| 12 | `btnNext` | BUTTON | 下一页 | None | `` |  |
| 13 | `btnQuery` | BUTTON | 查询 | None | `` |  |
| 14 | `btnReset` | BUTTON | 重置 | None | `` |  |
| 15 | `btnExport` | BUTTON | 导出 | None | `` |  |

### 布局（MU ASCII 原型）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 统计报表 / 门诊量统计                                      │
├──────────────────────────────────────────────────────────────────────────┤
│          挂号日期: {dtpQryDateFrom} ~ {dtpQryDateTo}   日期粒度: (cboDateGranularity) │
│          科室: (cboQryDeptCode)   接诊医师: [txtQryDoctorId]   就诊类型: (cboQryVisitType) │
│          就诊状态: (cboQryVisitStatus)                                     │
│          [btnQuery 查询] [btnReset 重置] [btnExport 导出]                  │
├──────────────────────────────────────────────────────────────────────────┤
│ @grdResult                                                                │
│  统计日期 | 科室 | 接诊医师 | 就诊类型 | 就诊人数 | 就诊人次 | 初诊 | 复诊 | 已完成 | 已取消 │
│ 分页: [lblPaging 共N条] [cboPageSize 每页20条] [btnPrev 上一页] [btnNext 下一页] │
│ 口径提示：就诊人数=不重复患者数、就诊人次=记录条数（Q-01 / REP-01）          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## frmSyndromeDist　证型分布统计（QUERY_LIST）

### 动作（2 个）

| 动作 | 名称 | 类型 | 绑定行为 | 权限 | 权限码 |
|---|---|---|---|---|---|
| `actQuery` | 查询 | BUTTON | `Diagnosis_QuerySyndromeDistribution` | PERM-QUERY-SYNDROME-DIST | diagnosis:query-syndrome-distribution（PERM-QUERY-SYNDROME-DIST） |
| `actExport` | 导出 | BUTTON | `Diagnosis_QuerySyndromeDistribution` | PERM-QUERY-SYNDROME-DIST | diagnosis:query-syndrome-distribution（PERM-QUERY-SYNDROME-DIST） |

### 元素（16 个）

| 序号 | 元素 id | 类型 | 标签 | io | dataBinding | 其它 |
|---|---|---|---|---|---|---|
| 1 | `dtpQryDateFrom` | DATEPICKER | 就诊日期从 | I | `Visit.registerTime` |  |
| 2 | `dtpQryDateTo` | DATEPICKER | 就诊日期到 | I | `Visit.registerTime` |  |
| 3 | `cboQryDiagnosisMethod` | COMBO | 辨证体系 | I | `SyndromeType.diagnosisMethod` |  |
| 4 | `cboQrySyndromeNature` | COMBO | 证型性质 | I | `SyndromeDiagnosis.syndromeNature` |  |
| 5 | `pslQrySyndromeId` | POPUP_SELECT | 证型 | I | `SyndromeDiagnosis.syndromeId` |  |
| 6 | `cboSummaryDimension` | COMBO | 汇总维度 | I | `` |  |
| 7 | `cboQryDeptCode` | COMBO | 科室 | I | `Visit.deptCode` |  |
| 8 | `txtQryDoctorId` | TEXTBOX | 接诊医师 | I | `Visit.doctorId` |  |
| 9 | `grdResult` | GRID | 证型分布统计结果 | O | `` | {"dataSource": "RPT-SYNDROME-DIST-001"} |
| 10 | `lblPaging` | LABEL | 分页信息 | O | `` |  |
| 11 | `cboPageSize` | COMBO | 每页条数 | I | `` |  |
| 12 | `btnPrev` | BUTTON | 上一页 | None | `` |  |
| 13 | `btnNext` | BUTTON | 下一页 | None | `` |  |
| 14 | `btnQuery` | BUTTON | 查询 | None | `` |  |
| 15 | `btnReset` | BUTTON | 重置 | None | `` |  |
| 16 | `btnExport` | BUTTON | 导出 | None | `` |  |

### 布局（MU ASCII 原型）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 统计报表 / 证型分布统计                                    │
├──────────────────────────────────────────────────────────────────────────┤
│          就诊日期: {dtpQryDateFrom} ~ {dtpQryDateTo}   辨证体系: (cboQryDiagnosisMethod) │
│          证型性质: (cboQrySyndromeNature)  证型: [pslQrySyndromeId…]   汇总维度: (cboSummaryDimension) │
│          科室: (cboQryDeptCode)   接诊医师: [txtQryDoctorId]               │
│          [btnQuery 查询] [btnReset 重置] [btnExport 导出]                  │
├──────────────────────────────────────────────────────────────────────────┤
│ @grdResult                                                                │
│  证型编码 | 证型名称 | 所属辨证体系 | 证型性质 | 辨证例数 | 占比             │
│ 分页: [lblPaging 共N条] [cboPageSize 每页20条] [btnPrev 上一页] [btnNext 下一页] │
│ 口径提示：占比分子分母使用相同筛选条件（Q-02 / REP-02）                      │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## frmHerbUsageStats　方剂与饮片使用统计（QUERY_LIST）

### 动作（2 个）

| 动作 | 名称 | 类型 | 绑定行为 | 权限 | 权限码 |
|---|---|---|---|---|---|
| `actQuery` | 查询 | BUTTON | `Prescription_QueryHerbUsage` | PERM-QUERY-HERB-USAGE | prescription:query-herb-usage（PERM-QUERY-HERB-USAGE） |
| `actExport` | 导出 | BUTTON | `Prescription_QueryHerbUsage` | PERM-QUERY-HERB-USAGE | prescription:query-herb-usage（PERM-QUERY-HERB-USAGE） |

### 元素（15 个）

| 序号 | 元素 id | 类型 | 标签 | io | dataBinding | 其它 |
|---|---|---|---|---|---|---|
| 1 | `dtpQryDateFrom` | DATEPICKER | 开方日期从 | I | `Prescription.prescribeTime` |  |
| 2 | `dtpQryDateTo` | DATEPICKER | 开方日期到 | I | `Prescription.prescribeTime` |  |
| 3 | `cboStatDimension` | COMBO | 统计维度 | I | `` |  |
| 4 | `cboQryHerbCategory` | COMBO | 饮片类别 | I | `Herb.herbCategory` |  |
| 5 | `pslQryHerbId` | POPUP_SELECT | 饮片 | I | `Prescription.PrescriptionItem.herbId` |  |
| 6 | `pslQryFormulaTemplateId` | POPUP_SELECT | 方剂模板 | I | `Prescription.formulaTemplateId` |  |
| 7 | `cboQryPrescriptionType` | COMBO | 处方类型 | I | `Prescription.prescriptionType` |  |
| 8 | `grdResult` | GRID | 方剂与饮片使用统计结果 | O | `` | {"dataSource": "RPT-HERB-USAGE-001"} |
| 9 | `lblPaging` | LABEL | 分页信息 | O | `` |  |
| 10 | `cboPageSize` | COMBO | 每页条数 | I | `` |  |
| 11 | `btnPrev` | BUTTON | 上一页 | None | `` |  |
| 12 | `btnNext` | BUTTON | 下一页 | None | `` |  |
| 13 | `btnQuery` | BUTTON | 查询 | None | `` |  |
| 14 | `btnReset` | BUTTON | 重置 | None | `` |  |
| 15 | `btnExport` | BUTTON | 导出 | None | `` |  |

### 布局（MU ASCII 原型）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 统计报表 / 方剂与饮片使用统计                              │
├──────────────────────────────────────────────────────────────────────────┤
│          开方日期: {dtpQryDateFrom} ~ {dtpQryDateTo}   统计维度: (cboStatDimension) │
│          饮片类别: (cboQryHerbCategory)  饮片: [pslQryHerbId…]  方剂模板: [pslQryFormulaTemplateId…] │
│          处方类型: (cboQryPrescriptionType)                                │
│          [btnQuery 查询] [btnReset 重置] [btnExport 导出]                  │
├──────────────────────────────────────────────────────────────────────────┤
│ @grdResult                                                                │
│  饮片编码 | 饮片名称 | 类别 | 毒性 | 使用剂数 | 累计用量（g） | 单剂均值（g） | 处方张数 | 患者数 │
│ 分页: [lblPaging 共N条] [cboPageSize 每页20条] [btnPrev 上一页] [btnNext 下一页] │
│ 口径提示：按饮片与按方剂模板两个维度分别查询，避免重复统计（Q-03 / REP-03）    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## frmVisitPrescriptionQuery　就诊与处方记录查询（QUERY_LIST）

### 动作（3 个）

| 动作 | 名称 | 类型 | 绑定行为 | 权限 | 权限码 |
|---|---|---|---|---|---|
| `actQuery` | 查询 | BUTTON | `Visit_QueryVisitAndPrescription` | PERM-QUERY-VISIT-PRESCRIPTION | visit:query-visit-and-prescription（PERM-QUERY-VISIT-PRESCRIPTION） |
| `actExport` | 导出 | BUTTON | `Visit_QueryVisitAndPrescription` | PERM-QUERY-VISIT-PRESCRIPTION | visit:query-visit-and-prescription（PERM-QUERY-VISIT-PRESCRIPTION） |
| `actVoid` | 作废 | BUTTON | `Prescription_Cancel` | PERM-PRESCRIPTION-CANCEL | prescription:cancel（PERM-PRESCRIPTION-CANCEL） |

### 元素（22 个）

| 序号 | 元素 id | 类型 | 标签 | io | dataBinding | 其它 |
|---|---|---|---|---|---|---|
| 1 | `txtQryPatientName` | TEXTBOX | 患者姓名 | I | `Patient.patientName` |  |
| 2 | `txtQryVisitNo` | TEXTBOX | 就诊号 | I | `Visit.visitNo` |  |
| 3 | `txtQryPrescriptionNo` | TEXTBOX | 处方号 | I | `Prescription.prescriptionNo` |  |
| 4 | `dtpQryDateFrom` | DATEPICKER | 挂号日期从 | I | `Visit.registerTime` |  |
| 5 | `dtpQryDateTo` | DATEPICKER | 挂号日期到 | I | `Visit.registerTime` |  |
| 6 | `cboQryVisitStatus` | COMBO | 就诊状态 | I | `Visit.visitStatus` |  |
| 7 | `cboQryPrescriptionStatus` | COMBO | 处方状态 | I | `Prescription.prescriptionStatus` |  |
| 8 | `txtQryDoctorId` | TEXTBOX | 接诊医师 | I | `Visit.doctorId` |  |
| 9 | `txtQryReviewerId` | TEXTBOX | 审核药师 | I | `Prescription.reviewerId` |  |
| 10 | `grdVisitResult` | GRID | 就诊记录（主表） | O | `` | {"dataSource": "QR-VISIT-PRESCRIPTION-001"} |
| 11 | `grdPrescriptionResult` | GRID | 处方记录（从表） | O | `` | {"dataSource": "QR-VISIT-PRESCRIPTION-001"} |
| 12 | `lblPaging` | LABEL | 分页信息 | O | `` |  |
| 13 | `cboPageSize` | COMBO | 每页条数 | I | `` |  |
| 14 | `btnPrev` | BUTTON | 上一页 | None | `` |  |
| 15 | `btnNext` | BUTTON | 下一页 | None | `` |  |
| 16 | `txtVoidPrescriptionNo` | TEXTBOX | 处方号 | O | `Prescription.prescriptionNo` | {"required": true} |
| 17 | `txaVoidReason` | TEXTAREA | 作废原因 | I | `Prescription.cancelReason` |  |
| 18 | `btnVoid` | BUTTON | 作废 | None | `` |  |
| 19 | `btnVoidCancel` | BUTTON | 取消 | None | `` |  |
| 20 | `btnQuery` | BUTTON | 查询 | None | `` |  |
| 21 | `btnReset` | BUTTON | 重置 | None | `` |  |
| 22 | `btnExport` | BUTTON | 导出 | None | `` |  |

### 布局（MU ASCII 原型）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 统计报表 / 就诊与处方记录查询                              │
├──────────────────────────────────────────────────────────────────────────┤
│          患者姓名: [txtQryPatientName]  就诊号: [txtQryVisitNo]  处方号: [txtQryPrescriptionNo] │
│          挂号日期: {dtpQryDateFrom} ~ {dtpQryDateTo}   就诊状态: (cboQryVisitStatus) │
│          处方状态: (cboQryPrescriptionStatus)  接诊医师: [txtQryDoctorId]  审核药师: [txtQryReviewerId] │
│          [btnQuery 查询] [btnReset 重置] [btnExport 导出]                  │
├──────────────────────────────────────────────────────────────────────────┤
│ 主表：就诊记录                                                            │
│ @grdVisitResult                                                           │
│  就诊号 | 患者 | 性别 | 年龄 | 就诊类型 | 挂号时间 | 接诊医师 | 就诊状态 | [展开] │
│   └ 从表：处方（行「展开」后呈现）                                          │
│ @grdPrescriptionResult                                                    │
│     处方号 | 处方状态 | 剂数 | 用法 | 开方时间 | 审核人 | [作废]            │
│ 分页: [lblPaging 共N条] [cboPageSize 每页20条] [btnPrev 上一页] [btnNext 下一页] │
│ 行操作「作废」打开下方弹窗（FUNC-09；已发药由 R-04 阻断）                    │
└──────────────────────────────────────────────────────────────────────────┘

（行操作「作废」弹出对话框，页面本身不展示以下表单）
┌──────────────────────────────────────────────────────────────────────────┐
│ 处方作废                                                                  │
│          处方号: [txtVoidPrescriptionNo 只读]                              │
│          作废原因: [txaVoidReason]                                        │
│                                             [btnVoid 作废] [btnVoidCancel 取消] │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## frmOverdoseLedger　超量·毒性处方审核台账（QUERY_LIST）

### 动作（2 个）

| 动作 | 名称 | 类型 | 绑定行为 | 权限 | 权限码 |
|---|---|---|---|---|---|
| `actQuery` | 查询 | BUTTON | `Prescription_QueryOverdoseReview` | PERM-QUERY-OVERDOSE-REVIEW | prescription:query-overdose-review（PERM-QUERY-OVERDOSE-REVIEW） |
| `actExport` | 导出 | BUTTON | `Prescription_QueryOverdoseReview` | PERM-QUERY-OVERDOSE-REVIEW | prescription:query-overdose-review（PERM-QUERY-OVERDOSE-REVIEW） |

### 元素（14 个）

| 序号 | 元素 id | 类型 | 标签 | io | dataBinding | 其它 |
|---|---|---|---|---|---|---|
| 1 | `dtpQryDateFrom` | DATEPICKER | 开方日期从 | I | `Prescription.prescribeTime` |  |
| 2 | `dtpQryDateTo` | DATEPICKER | 开方日期到 | I | `Prescription.prescribeTime` |  |
| 3 | `cboQryTriggerType` | COMBO | 触发类型 | I | `` |  |
| 4 | `cboQryPrescriptionStatus` | COMBO | 处方状态 | I | `Prescription.prescriptionStatus` |  |
| 5 | `txtQryReviewerId` | TEXTBOX | 审核药师 | I | `Prescription.reviewerId` |  |
| 6 | `cboQryHandleResult` | COMBO | 处理结果 | I | `` |  |
| 7 | `grdResult` | GRID | 超量·毒性处方审核台账 | O | `` | {"dataSource": "QR-PRESCRIPTION-OVERDOSE-001"} |
| 8 | `lblPaging` | LABEL | 分页信息 | O | `` |  |
| 9 | `cboPageSize` | COMBO | 每页条数 | I | `` |  |
| 10 | `btnPrev` | BUTTON | 上一页 | None | `` |  |
| 11 | `btnNext` | BUTTON | 下一页 | None | `` |  |
| 12 | `btnQuery` | BUTTON | 查询 | None | `` |  |
| 13 | `btnReset` | BUTTON | 重置 | None | `` |  |
| 14 | `btnExport` | BUTTON | 导出 | None | `` |  |

### 布局（MU ASCII 原型）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 统计报表 / 超量·毒性处方审核台账                            │
├──────────────────────────────────────────────────────────────────────────┤
│          开方日期: {dtpQryDateFrom} ~ {dtpQryDateTo}   触发类型: (cboQryTriggerType) │
│          处方状态: (cboQryPrescriptionStatus)  审核药师: [txtQryReviewerId]  处理结果: (cboQryHandleResult) │
│          [btnQuery 查询] [btnReset 重置] [btnExport 导出]                  │
├──────────────────────────────────────────────────────────────────────────┤
│ @grdResult                                                                │
│  处方号 | 患者 | 开方日期 | 开方医师 | 超量/毒性药味 | 剂量 | 上限 | 超出倍数 | 毒性 | 超量理由 | 处方状态 | 审核人 │
│ 分页: [lblPaging 共N条] [cboPageSize 每页20条] [btnPrev 上一页] [btnNext 下一页] │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## frmFollowUpAnalysis　随访完成与失访分析（QUERY_LIST）

### 动作（2 个）

| 动作 | 名称 | 类型 | 绑定行为 | 权限 | 权限码 |
|---|---|---|---|---|---|
| `actQuery` | 查询 | BUTTON | `FollowUp_QueryCompletion` | PERM-QUERY-FOLLOWUP | follow_up:query-completion（PERM-QUERY-FOLLOWUP） |
| `actExport` | 导出 | BUTTON | `FollowUp_QueryCompletion` | PERM-QUERY-FOLLOWUP | follow_up:query-completion（PERM-QUERY-FOLLOWUP） |

### 元素（14 个）

| 序号 | 元素 id | 类型 | 标签 | io | dataBinding | 其它 |
|---|---|---|---|---|---|---|
| 1 | `dtpQryPlannedFrom` | DATEPICKER | 计划随访日期从 | I | `FollowUp.plannedFollowUpDate` |  |
| 2 | `dtpQryPlannedTo` | DATEPICKER | 计划随访日期到 | I | `FollowUp.plannedFollowUpDate` |  |
| 3 | `cboQryDeptCode` | COMBO | 科室 | I | `Visit.deptCode` |  |
| 4 | `txtQryDoctorId` | TEXTBOX | 接诊医师 | I | `Visit.doctorId` |  |
| 5 | `cboQryRecordStatus` | COMBO | 随访状态 | I | `FollowUp.recordStatus` |  |
| 6 | `cboQryEfficacyLevel` | COMBO | 疗效评价 | I | `FollowUp.efficacyLevel` |  |
| 7 | `grdResult` | GRID | 随访完成与失访分析结果 | O | `` | {"dataSource": "RPT-FOLLOWUP-COMPLETION-001"} |
| 8 | `lblPaging` | LABEL | 分页信息 | O | `` |  |
| 9 | `cboPageSize` | COMBO | 每页条数 | I | `` |  |
| 10 | `btnPrev` | BUTTON | 上一页 | None | `` |  |
| 11 | `btnNext` | BUTTON | 下一页 | None | `` |  |
| 12 | `btnQuery` | BUTTON | 查询 | None | `` |  |
| 13 | `btnReset` | BUTTON | 重置 | None | `` |  |
| 14 | `btnExport` | BUTTON | 导出 | None | `` |  |

### 布局（MU ASCII 原型）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 统计报表 / 随访完成与失访分析                              │
├──────────────────────────────────────────────────────────────────────────┤
│          计划随访日期: {dtpQryPlannedFrom} ~ {dtpQryPlannedTo}   科室: (cboQryDeptCode) │
│          接诊医师: [txtQryDoctorId]   随访状态: (cboQryRecordStatus)   疗效评价: (cboQryEfficacyLevel) │
│          [btnQuery 查询] [btnReset 重置] [btnExport 导出]                  │
├──────────────────────────────────────────────────────────────────────────┤
│ @grdResult                                                                │
│  统计期间 | 科室 | 接诊医师 | 计划随访 | 已完成 | 已失访 | 完成率 | 失访率 | 痊愈 | 显效 | 有效 | 无效 | 加重 │
│ 分页: [lblPaging 共N条] [cboPageSize 每页20条] [btnPrev 上一页] [btnNext 下一页] │
└──────────────────────────────────────────────────────────────────────────┘
```

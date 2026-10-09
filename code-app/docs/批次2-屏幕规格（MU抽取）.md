### frmVisitRegister 门诊挂号（含撤销就诊）（SINGLE_FORM）

| 元素 id | 类型 | io | 字典/来源 | dataBinding | 标签 |
|---|---|---|---|---|---|
| `txtVisitNo` | TEXTBOX | O |  | `Visit.visitNo` | 就诊号 |
| `pslPatient` | POPUP_SELECT | I |  | `Visit.patientId` | 患者 |
| `cboVisitType` | COMBO | I |  | `Visit.visitType` | 就诊类型 |
| `pslPreviousVisit` | POPUP_SELECT | I |  | `Visit.previousVisitId` | 上次就诊 |
| `dtpRegisterTime` | DATEPICKER | I |  | `Visit.registerTime` | 挂号时间 |
| `cboDeptCode` | COMBO | I |  | `Visit.deptCode` | 科室 |
| `txtDoctorId` | TEXTBOX | I |  | `Visit.doctorId` | 接诊医师 |
| `cboVisitStatus` | COMBO | O |  | `Visit.visitStatus` | 就诊状态 |
| `txaRemark` | TEXTAREA | I |  | `Visit.remark` | 备注 |
| `btnSave` | BUTTON | None |  | `` | 保存 |
| `btnCancelVisit` | BUTTON | None |  | `` | 撤销就诊 |
| `btnClear` | BUTTON | None |  | `` | 清空 |

动作：
- `actSave` BUTTON → 行为 `Visit_Register` 权限 `['PERM-VISIT-REGISTER']`
- `actCancelVisit` BUTTON → 行为 `Visit_Cancel` 权限 `['PERM-VISIT-CANCEL']`

布局（ASCII）：
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 门诊管理 / 门诊挂号                                        │
├──────────────────────────────────────────────────────────────────────────┤
│          就诊号  : [txtVisitNo 只读]          患者    : [pslPatient…]      │
│          就诊类型: (cboVisitType)             上次就诊: [pslPreviousVisit…] │
│          挂号时间: {dtpRegisterTime}          科室    : (cboDeptCode)      │
│          接诊医师: [txtDoctorId]              就诊状态: (cboVisitStatus 只读) │
│          备注    : [txaRemark]                                            │
├──────────────────────────────────────────────────────────────────────────┤
│ [btnSave 保存] [btnCancelVisit 撤销就诊] [btnClear 清空]                    │
│ 撤销就诊：仅就诊状态=已挂号/接诊中且该就诊无处方时可用，需填写作废原因        │
└──────────────────────────────────────────────────────────────────────────┘
```

### frmVisitReceive 接诊开单（SINGLE_FORM）

| 元素 id | 类型 | io | 字典/来源 | dataBinding | 标签 |
|---|---|---|---|---|---|
| `txtVisitNo` | TEXTBOX | O |  | `Visit.visitNo` | 就诊号 |
| `lblPatientInfo` | TEXTBOX | O |  | `Patient.patientName` | 患者 |
| `dtpRegisterTime` | DATEPICKER | O |  | `Visit.registerTime` | 挂号时间 |
| `dtpReceiveTime` | DATEPICKER | I |  | `Visit.receiveTime` | 接诊时间 |
| `txtDoctorId` | TEXTBOX | I |  | `Visit.doctorId` | 接诊医师 |
| `cboDeptCode` | COMBO | I |  | `Visit.deptCode` | 科室 |
| `txtVitalSigns` | TEXTBOX | I |  | `Visit.vitalSigns` | 生命体征 |
| `txaChiefComplaint` | TEXTAREA | I |  | `Visit.chiefComplaint` | 主诉 |
| `txaPresentIllness` | TEXTAREA | I |  | `Visit.presentIllness` | 现病史 |
| `txaPastHistory` | TEXTAREA | I |  | `Visit.pastHistory` | 既往史 |
| `txaRemark` | TEXTAREA | I |  | `Visit.remark` | 备注 |
| `btnSave` | BUTTON | None |  | `` | 保存 |
| `btnBack` | BUTTON | None |  | `` | 返回待诊列表 |

动作：
- `actSave` BUTTON → 行为 `Visit_Receive` 权限 `['PERM-VISIT-RECEIVE']`

布局（ASCII）：
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 门诊管理 / 接诊开单                                        │
├──────────────────────────────────────────────────────────────────────────┤
│          就诊号  : [txtVisitNo 只读]          患者    : [lblPatientInfo 只读] │
│          挂号时间: {dtpRegisterTime 只读}     接诊时间: {dtpReceiveTime}    │
│          接诊医师: [txtDoctorId]              科室    : (cboDeptCode)      │
│          生命体征: [txtVitalSigns]                                        │
│          主诉    : [txaChiefComplaint]                                    │
│          现病史  : [txaPresentIllness]                                    │
│          既往史  : [txaPastHistory]                                       │
│          备注    : [txaRemark]                                            │
├──────────────────────────────────────────────────────────────────────────┤
│ [btnSave 保存] [btnBack 返回待诊列表]                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

### frmFourDiagnosis 四诊录入（SINGLE_FORM）

| 元素 id | 类型 | io | 字典/来源 | dataBinding | 标签 |
|---|---|---|---|---|---|
| `txtVisitNo` | TEXTBOX | O |  | `Visit.visitNo` | 就诊号 |
| `lblPatientName` | TEXTBOX | O |  | `Patient.patientName` | 患者 |
| `txtInquiryColdHeat` | TEXTBOX | I |  | `Visit.FourDiagnosis.inquiryColdHeat` | 问诊-寒热 |
| `txtInquirySweat` | TEXTBOX | I |  | `Visit.FourDiagnosis.inquirySweat` | 问诊-汗出 |
| `txtInquiryHeadBody` | TEXTBOX | I |  | `Visit.FourDiagnosis.inquiryHeadBody` | 问诊-头身 |
| `txtInquiryDiet` | TEXTBOX | I |  | `Visit.FourDiagnosis.inquiryDiet` | 问诊-饮食口味 |
| `txtInquirySleep` | TEXTBOX | I |  | `Visit.FourDiagnosis.inquirySleep` | 问诊-睡眠 |
| `txtInquiryExcretion` | TEXTBOX | I |  | `Visit.FourDiagnosis.inquiryExcretion` | 问诊-二便 |
| `txaInquiryEmotion` | TEXTAREA | I |  | `Visit.FourDiagnosis.inquiryEmotion` | 问诊-情志与妇科 |
| `txtInspectionFace` | TEXTBOX | I |  | `Visit.FourDiagnosis.inspectionFace` | 望诊-面色 |
| `txtInspectionShape` | TEXTBOX | I |  | `Visit.FourDiagnosis.inspectionShape` | 望诊-形态 |
| `cboTongueBody` | COMBO | I |  | `Visit.FourDiagnosis.tongueBody` | 舌质 |
| `cboTongueCoating` | COMBO | I |  | `Visit.FourDiagnosis.tongueCoating` | 舌苔 |
| `txtAuscultationVoice` | TEXTBOX | I |  | `Visit.FourDiagnosis.auscultationVoice` | 闻诊-声音气息 |
| `txtAuscultationSmell` | TEXTBOX | I |  | `Visit.FourDiagnosis.auscultationSmell` | 闻诊-气味 |
| `cboPulseCode` | COMBO | I |  | `Visit.FourDiagnosis.pulseCode` | 脉象 |
| `txtPulseDetail` | TEXTBOX | I |  | `Visit.FourDiagnosis.pulseDetail` | 脉象文本补充 |
| `txaFourDiagnosisSummary` | TEXTAREA | I |  | `Visit.FourDiagnosis.fourDiagnosisSummary` | 四诊摘要 |
| `btnSave` | BUTTON | None |  | `` | 保存 |
| `btnSummary` | BUTTON | None |  | `` | 四诊摘要 |

动作：
- `actSave` BUTTON → 行为 `Visit_SaveFourDiagnosis` 权限 `['PERM-VISIT-FOURDIAGNOSIS']`

布局（ASCII）：
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 门诊管理 / 四诊录入                                        │
├──────────────────────────────────────────────────────────────────────────┤
│          就诊号  : [txtVisitNo 只读]          患者    : [lblPatientName 只读] │
│          问诊-寒热: [txtInquiryColdHeat]      问诊-汗出: [txtInquirySweat]   │
│          问诊-头身: [txtInquiryHeadBody]      问诊-饮食: [txtInquiryDiet]    │
│          问诊-睡眠: [txtInquirySleep]         问诊-二便: [txtInquiryExcretion]│
│          问诊-情志与妇科: [txaInquiryEmotion]                              │
│          望诊-面色: [txtInspectionFace]       望诊-形态: [txtInspectionShape]│
│          舌质    : (cboTongueBody)            舌苔    : (cboTongueCoating)  │
│          闻诊-声音气息: [txtAuscultationVoice] 闻诊-气味: [txtAuscultationSmell]│
│          脉象    : (cboPulseCode)             脉象文本补充: [txtPulseDetail] │
│          四诊摘要: [txaFourDiagnosisSummary]                              │
├──────────────────────────────────────────────────────────────────────────┤
│ [btnSave 保存] [btnSummary 四诊摘要]                                       │
│ 脉象为必填项；舌质/舌苔/脉象为数据字典下拉（DICT-TCM-SIGN）                  │
└──────────────────────────────────────────────────────────────────────────┘
```

### frmDiagnosisJudge 辨证判定（MASTER_DETAIL_FORM）

| 元素 id | 类型 | io | 字典/来源 | dataBinding | 标签 |
|---|---|---|---|---|---|
| `txtVisitNo` | TEXTBOX | O |  | `Visit.visitNo` | 就诊号 |
| `lblPatientName` | TEXTBOX | O |  | `Patient.patientName` | 患者 |
| `txtDoctorId` | TEXTBOX | O |  | `Visit.doctorId` | 接诊医师 |
| `txaFourDiagnosisSummary` | TEXTAREA | O |  | `Visit.FourDiagnosis.fourDiagnosisSummary` | 四诊摘要 |
| `grdDiagnosis` | GRID | I_O |  | `` | 辨证结论 |
| `btnAddDiagnosisRow` | BUTTON | None |  | `` | 添加辨证结论 |
| `btnSave` | BUTTON | None |  | `` | 保存 |
| `btnConfirm` | BUTTON | None |  | `` | 确认结论 |
| `btnBack` | BUTTON | None |  | `` | 返回 |

动作：
- `actSave` BUTTON → 行为 `Diagnosis_Save` 权限 `['PERM-DIAGNOSIS-SAVE']`
- `actConfirm` BUTTON → 行为 `Diagnosis_Confirm` 权限 `['PERM-DIAGNOSIS-CONFIRM']`

布局（ASCII）：
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 门诊管理 / 辨证判定                                        │
├──────────────────────────────────────────────────────────────────────────┤
│ 主表：就诊摘要（只读）                                                    │
│       就诊号: [txtVisitNo 只读]   患者: [lblPatientName 只读]   接诊医师: [txtDoctorId 只读] │
│       四诊摘要: [txaFourDiagnosisSummary 只读]                            │
├──────────────────────────────────────────────────────────────────────────┤
│ 从表：辨证结论（AGG-DIAGNOSIS-001，表格内动态维护）                        │
│ @grdDiagnosis                                                             │
│  序号 | 辨证方法(下拉) | 证型(跳选框) | 性质(下拉) | 辨证依据 | 治法 | 删除  │
│  [btnAddDiagnosisRow 添加辨证结论]                                        │
│ 规则提示：主证性质在同一就诊下唯一（INV-02，从表内「主证」只能一行）         │
├──────────────────────────────────────────────────────────────────────────┤
│ [btnSave 保存] [btnConfirm 确认结论] [btnBack 返回]                        │
└──────────────────────────────────────────────────────────────────────────┘
```

### frmPrescription 开具处方（MASTER_DETAIL_FORM）

| 元素 id | 类型 | io | 字典/来源 | dataBinding | 标签 |
|---|---|---|---|---|---|
| `txtPrescriptionNo` | TEXTBOX | O |  | `Prescription.prescriptionNo` | 处方号 |
| `txtVisitNo` | TEXTBOX | O |  | `Visit.visitNo` | 就诊号 |
| `lblPatientName` | TEXTBOX | O |  | `Patient.patientName` | 患者 |
| `cboPrescriptionType` | COMBO | I |  | `Prescription.prescriptionType` | 处方类型 |
| `pslFormulaTemplate` | POPUP_SELECT | I |  | `Prescription.formulaTemplateId` | 引用方剂 |
| `numDoses` | NUMBER | I |  | `Prescription.doses` | 剂数 |
| `cboUsageMethod` | COMBO | I |  | `Prescription.usageMethod` | 用法 |
| `txtDecoctionInstruction` | TEXTBOX | I |  | `Prescription.decoctionInstruction` | 煎服说明 |
| `txaMedicalAdvice` | TEXTAREA | I |  | `Prescription.medicalAdvice` | 医嘱嘱托 |
| `grdPrescriptionItems` | GRID | I_O |  | `Prescription.PrescriptionItem` | 处方明细 |
| `btnAddHerbRow` | BUTTON | None |  | `` | 添加药味 |
| `btnRecheckDose` | BUTTON | None |  | `` | 检查剂量 |
| `btnSaveDraft` | BUTTON | None |  | `` | 保存草稿 |
| `btnSubmit` | BUTTON | None |  | `` | 提交 |
| `btnBack` | BUTTON | None |  | `` | 返回 |

动作：
- `actSaveDraft` DRAFT → 行为 `Prescription_Save` 权限 `['PERM-PRESCRIPTION-SAVE']`
- `actSubmit` SUBMIT → 行为 `Prescription_Submit` 权限 `['PERM-PRESCRIPTION-SUBMIT']`

布局（ASCII）：
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 门诊管理 / 开具处方                                        │
├──────────────────────────────────────────────────────────────────────────┤
│ 主表：处方（AGG-PRESCRIPTION-001）                                        │
│       处方号: [txtPrescriptionNo 只读]  就诊号: [txtVisitNo 只读]   患者: [lblPatientName 只读] │
│       处方类型: (cboPrescriptionType)  引用方剂: [pslFormulaTemplate…]  剂数: [numDoses] │
│       用法: (cboUsageMethod)            煎服说明: [txtDecoctionInstruction] │
│       医嘱嘱托: [txaMedicalAdvice]                                        │
├──────────────────────────────────────────────────────────────────────────┤
│ 从表：处方明细（AGG-PRESCRIPTION-001 子实体 PrescriptionItem，表格内动态维护） │
│ @grdPrescriptionItems                                                     │
│  序号 | 饮片(跳选框) | 单剂剂量（g） | 常用量区间 | 特殊煎法(下拉) | 超量理由 | 删除 │
│  [btnAddHerbRow 添加药味] [btnRecheckDose 检查剂量]                        │
│ 规则提示：R-01 超量需填写超量理由并强制审核、超常用上限 2 倍阻断；             │
│           R-03 毒性饮片总量超上限阻断提交                                  │
├──────────────────────────────────────────────────────────────────────────┤
│ [btnSaveDraft 保存草稿] [btnSubmit 提交] [btnBack 返回]                    │
└──────────────────────────────────────────────────────────────────────────┘
```

### frmPrescriptionReview 处方审核（SINGLE_FORM）

| 元素 id | 类型 | io | 字典/来源 | dataBinding | 标签 |
|---|---|---|---|---|---|
| `txtPrescriptionNo` | TEXTBOX | O |  | `Prescription.prescriptionNo` | 处方号 |
| `lblPatientName` | TEXTBOX | O |  | `Patient.patientName` | 患者 |
| `txtDoctorId` | TEXTBOX | O |  | `Prescription.doctorId` | 开方医师 |
| `numDoses` | NUMBER | O |  | `Prescription.doses` | 剂数 |
| `cboUsageMethod` | COMBO | O |  | `Prescription.usageMethod` | 用法 |
| `dtpSubmitTime` | DATEPICKER | O |  | `Prescription.submitTime` | 提交时间 |
| `txaDiagnosisSummary` | TEXTAREA | O |  | `` | 辨证结论 |
| `grdPrescriptionItems` | GRID | O |  | `Prescription.PrescriptionItem` | 处方明细 |
| `txaRejectReason` | TEXTAREA | I |  | `Prescription.rejectReason` | 驳回原因 |
| `btnApprove` | BUTTON | None |  | `` | 通过 |
| `btnReject` | BUTTON | None |  | `` | 驳回 |
| `btnBack` | BUTTON | None |  | `` | 返回待审队列 |

动作：
- `actApprove` APPROVE → 行为 `Prescription_Review` 权限 `['PERM-PRESCRIPTION-REVIEW']`
- `actReject` REJECT → 行为 `Prescription_Review` 权限 `['PERM-PRESCRIPTION-REVIEW']`

布局（ASCII）：
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 药房管理 / 处方审核                                        │
├──────────────────────────────────────────────────────────────────────────┤
│          处方号  : [txtPrescriptionNo 只读]   患者    : [lblPatientName 只读] │
│          开方医师: [txtDoctorId 只读]         剂数    : [numDoses 只读]     │
│          用法    : (cboUsageMethod 只读)      提交时间: {dtpSubmitTime 只读}│
│          辨证结论: [txaDiagnosisSummary 只读]                              │
├──────────────────────────────────────────────────────────────────────────┤
│ 处方明细（只读）                                                          │
│ @grdPrescriptionItems                                                     │
│  序号 | 饮片 | 单剂剂量 | 常用量区间 | 特殊煎法 | 超量/毒性标记             │
├──────────────────────────────────────────────────────────────────────────┤
│          审核意见：驳回原因 [txaRejectReason]（驳回时必填）                 │
├──────────────────────────────────────────────────────────────────────────┤
│ [btnApprove 通过] [btnReject 驳回] [btnBack 返回待审队列]                   │
└──────────────────────────────────────────────────────────────────────────┘
```

### frmDispense 调剂发药（MASTER_DETAIL_FORM）

| 元素 id | 类型 | io | 字典/来源 | dataBinding | 标签 |
|---|---|---|---|---|---|
| `txtDispenseNo` | TEXTBOX | O |  | `DispenseRecord.dispenseNo` | 发药单号 |
| `txtPrescriptionNo` | TEXTBOX | O |  | `Prescription.prescriptionNo` | 处方号 |
| `lblPatientName` | TEXTBOX | O |  | `Patient.patientName` | 患者 |
| `txtDispenserId` | TEXTBOX | I |  | `DispenseRecord.dispenserId` | 调剂人 |
| `txtCheckerId` | TEXTBOX | I |  | `DispenseRecord.checkerId` | 复核人 |
| `cboRecordStatus` | COMBO | O |  | `DispenseRecord.recordStatus` | 记录状态 |
| `dtpDispenseTime` | DATEPICKER | I |  | `DispenseRecord.dispenseTime` | 调剂时间 |
| `dtpIssueTime` | DATEPICKER | I |  | `DispenseRecord.issueTime` | 发药时间 |
| `txaRemark` | TEXTAREA | I |  | `DispenseRecord.remark` | 备注 |
| `grdStockCheck` | GRID | O |  | `Prescription.PrescriptionItem` | 处方明细核对 |
| `btnConfirmDispense` | BUTTON | None |  | `` | 确认调剂 |
| `btnIssue` | BUTTON | None |  | `` | 发药确认 |
| `btnBack` | BUTTON | None |  | `` | 返回队列 |

动作：
- `actConfirmDispense` BUTTON → 行为 `Dispense_Confirm` 权限 `['PERM-DISPENSE-CONFIRM']`
- `actIssue` BUTTON → 行为 `Dispense_Issue` 权限 `['PERM-DISPENSE-ISSUE']`

布局（ASCII）：
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 中医问诊系统 / 药房管理 / 调剂发药                                        │
├──────────────────────────────────────────────────────────────────────────┤
│ 主表：调剂发药记录（AGG-DISPENSE-001）                                    │
│       发药单号: [txtDispenseNo 只读]  处方号: [txtPrescriptionNo 只读]  患者: [lblPatientName 只读] │
│       调剂人: [txtDispenserId]        复核人: [txtCheckerId]   记录状态: (cboRecordStatus 只读) │
│       调剂时间: {dtpDispenseTime}     发药时间: {dtpIssueTime}             │
│       备注: [txaRemark]                                                   │
├──────────────────────────────────────────────────────────────────────────┤
│ 从表：处方明细核对（实时库存，只读 + 核对勾选）                             │
│ @grdStockCheck                                                            │
│  序号 | 饮片 | 需求用量（g） | 当前库存（g） | 是否充足 | 核对 | 备注           │
│ 规则提示：R-02 库存不足阻断调剂，不允许先调剂后补库                          │
├──────────────────────────────────────────────────────────────────────────┤
│ [btnConfirmDispense 确认调剂] [btnIssue 发药确认] [btnBack 返回队列]        │
└──────────────────────────────────────────────────────────────────────────┘
```

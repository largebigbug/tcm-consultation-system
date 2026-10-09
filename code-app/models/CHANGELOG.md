# 本体模型变更记录（CHANGELOG）

记录**跨模型的破坏性变更**（实体删除、行为签名变更、编号新增或迁移等）。同文件内的小修订只改各 yaml 的 `version`，不在此登记。

## v2.1（2026-09-30，阶段三批次 4 开工修订 M7：条件组开关显式化）

### 新增

- **约定 13：非 BASE 条件组必须显式声明机读开关**。组内条件一律声明 `switchParameterRef`（同组取值一致），该参数必须存在于本报表 `parameters` 且 `required=false`。开关语义两种：① 显式给 `switchActivateValue`（如 `onlyAlert` 的 `true`）→「相等即参与」，未传取参数 `defaultValue`；② 未给 `switchActivateValue`（Enum 开关，如 `triggerType`）→ `BOTH` 整组参与、其它取值仅 `triggerKind` 匹配的成员参与。

### 修复（实质缺陷）

- **`QR-HERB-STOCK-001` 的 `ALERT_FILTER` 组补 `switchParameterRef: onlyAlert` + `switchActivateValue: true`**。此前该组的开关只写在注释里，注册表解析 yaml 后注释丢失 → 引擎无法定位开关 → 静默按「整组恒参与」容错 → **该报表忽略 `onlyAlert`、恒只返回预警项**（实测修复前 10 条饮片恒返回 1 行；修复后：未传 10 行、`onlyAlert=true` 1 行、`onlyAlert=false` 10 行、非法值 400 中文提示）。
- **`QR-PRESCRIPTION-OVERDOSE-001` 的 `TRIGGER` 组补 `switchParameterRef: triggerType`**（显式化，语义与 v1.7 一致，不再依赖「默认值 ∈ [BOTH]+triggerKind」的启发式推断）。

### 门禁

- `tools/validate_ontology.py` 新增约定 13 检查：非 BASE 组缺 `switchParameterRef`、开关参数不在 `parameters` 中或为必填、`switchActivateValue` 与参数类型/枚举不符 → **校验阻断**（此前只由引擎静默容错）。负例已实测：删除 `switchParameterRef` 即被拦下。
- `report_service.validate_metadata()` 同步新增条件组开关自检（问题清单此前实测为 0 条、不反映该缺陷）。

## v1.9（2026-09-30，阶段三批次 3 收口时修正 M7 + 运行时模型副本同步）

### 新增（模型可机读性）

- **Enum 型参数新增 `enumValues` 字段**（`granularity=[DAY, MONTH]`、`statsDimension=[HERB, FORMULA_TEMPLATE]`、`triggerType=[OVERDOSE, TOXIC, BOTH]`），并据此重写约定 10：合法取值＝该字段（原约定 10 只写在注释里，而注册表解析 yaml 后注释丢失、实现无法机读 → 实现只能自造取值，实测接受了 `granularity=YEAR`、拒绝了模型内的 `statsDimension=FORMULA_TEMPLATE`）。
- **新增约定 11**：维度开关参数的取值按「最长前缀」映射到维度别名（`HERB`→`herb`、`FORMULA_TEMPLATE`→`formula`），实现可额外接受同义别名（`FORMULA`）作容错，但不得拒绝 `enumValues` 取值。
- **新增约定 12**：预聚合（`preAggregation`）来源**不得作主来源**——主来源即 `FROM` 表，必须为普通表；预聚合来源须在 CTE 中先汇总再 `LEFT JOIN` 接入。

### 修正

- **`RPT-HERB-USAGE-001` 主来源回退为 `prescription`**：v1.8 曾按「需求 5.4 来源对象首列 OBJ-09 处方明细」把主来源改为 `itemAgg`，实测触发引擎对「预聚合来源作主来源」支持不完善的缺陷（生成 SQL 引用错误别名 → `no such column: prescription.prescribe_time`，接口 500），故回退并立为约定 12。「无明细的处方」改按**数据质量问题**处理（正常流程下已审核/已发药处方必有明细），不由报表口径兜底；验收固定数据集已同步修正（复制处方时一并复制明细并挂方剂模板）。

### 说明

- **运行时模型副本 `code-app/models/` 已重新同步**：该目录是阶段三开工时（14:06）自 `yaml/` 拷贝的运行时副本，此前已落后于 `yaml/`（缺批次 2 的 M1 `toxicDoseLimit`、主诉必填裁决，以及批次 3 的 M7 Join 修正 / `triggerKind` / 约定），运行时一直加载的是过期快照（旧副本已备份为 `code-app/models.bak-20260930-1600`）。已整体重新同步，md5 一致。**后续每次改模型必须同步该目录**（登记为阶段三纪律）。
- `tools/validate_ontology.py yaml` 十类门禁复跑通过；抽取文档 `code-app/docs/批次3-报表规格（M7抽取）.md` 已重新生成。

## v1.8（2026-09-30，阶段三批次 3 收口时修正 M7）

### 修正（模型自相矛盾 + 契约越权定义取值域）

- **M7 文件头约定编号去重重排为 1～10**：原文件同时存在两个「约定 5」「约定 6」「约定 7」（同一编号指向不同语义：预聚合 / SUBTOTAL 各占一个「约定 5」；fixedValue+可选条件组 / DATE_TRUNC 各占一个「约定 6」；SUBTOTAL 实现 / 医师科室取数各占一个「约定 7」），作为门禁自检依据不可歧义。语义全部保留，仅重排编号。
- **新增约定 10：Enum 型参数的合法取值 = 该参数 `defaultValue` 行注释列出的取值集合**。原因：`code-app/docs/批次3-实现契约.md` 自造了 `statsDimension=HERB|FORMULA`、`granularity=DAY/MONTH/YEAR`，而模型注释写明 `statsDimension=HERB/FORMULA_TEMPLATE`、`granularity=DAY/MONTH` → 实现接受了模型外取值（`granularity=YEAR`）、拒绝了模型内取值（`statsDimension=FORMULA_TEMPLATE` 报 400）。
- **`RPT-HERB-USAGE-001` 主来源由 `prescription` 改为 `itemAgg`（处方明细）**：需求 5.4 该报表的来源对象首列即 OBJ-09 处方明细；原主来源为处方时，LEFT JOIN 明细会为「无明细的处方」生成一行空饮片维度数据，使饮片行数与累计用量虚增（实测：饮片行 8 → 9、合计剂数 84 → 91）。改动后两个维度均以处方明细为行单位，方剂维度经明细关联处方后按 `formula.*` 分组。

### 说明

- **`version` 行同步校正为 1.8**：v1.7 的变更此前只登记在本 CHANGELOG 与文件头约定中，`version:` 行仍停留在 `1.6`，本次一并校正。
- 本次不新增/删除对象、参数、列、条件；`tools/validate_ontology.py yaml` 十类门禁复跑通过；`code-app/docs/批次3-报表规格（M7抽取）.md` 已随 `tools/gen_batch3_spec.py` 重新生成。

## v1.7（2026-09-30，阶段三批次 3 契约冻结时补全）

### 新增（模型语法显式化，避免实现方猜测）

- **M7 条件新增 `triggerKind` 字段**：超量·毒性处方审核台账（QR-PRESCRIPTION-OVERDOSE-001）的 TRIGGER 组两个条件补 `triggerKind`：C03（`prescriptionItem.singleDose GT herb.maxCommonDose`）＝`OVERDOSE`、C04（`herb.toxicityLevel NE NONE`）＝`TOXIC`。原因：「触发类型」参数 `triggerType`（`BOTH`/`OVERDOSE`/`TOXIC`）与 TRIGGER 组内成员的对应关系在原模型里没有显式表达，实现方只能靠条件文本猜测。现约定：`BOTH`＝TRIGGER 组成员按组内连接符（OR）全部参与；`OVERDOSE`/`TOXIC`＝仅保留对应 `triggerKind` 的成员。
- **M7 文件头约定补齐两条**：约定 6（`fixedValue` 常量条件的语义 + 非 BASE 可选条件组的参与规则）、约定 7（`SUBTOTAL(x)` 表示跨全部分组总计，实现为窗口聚合 `SUM(x) OVER ()`）。

### 说明

- 本次为**新增可选字段 + 文件头约定**，不改变任何已有的对象、参数、列、条件表达式与 Join；`tools/validate_ontology.py` 十类检查复跑全过。
- `fixedValue` 并非新增：RPT-HERB-USAGE-001 C03（`[APPROVED, DISPENSING, ISSUED]`，与需求 5.4「处方状态∈{审核通过,已调剂,已发药}」一致）、QR-PRESCRIPTION-OVERDOSE-001 C03/C04、QR-HERB-STOCK-001 C08（批次 1 已实现）自阶段二即存在；本批在抽取文档中补印该列，避免实现方遗漏。
- `SUBTOTAL` 自阶段二即用于 RPT-SYNDROME-DIST-001 `caseRatio` 与 RPT-HERB-USAGE-001 `formulaRefRatio`（需求 5.3/5.4 的占比口径：分子分母使用同一筛选条件），本批首次明确其实现形式。

## v1.6（2026-09-30，阶段三批次 3 侦察时修订）

### 修正（模型与物理结构不一致，属阶段二建模偏差）

- **M7 全部 18 条 Join 的 `conditionExpression` 修正**：原写法把**数值外键**与**对方业务编号**相比（例：`visit.patientId == patient.patientNo`、`prescription.visitId == visit.visitNo`、`itemAgg.herbId == herb.herbCode`），与 `code-app/backend/schema.sql` 的实际结构不符——业务表关联一律为 `INTEGER` 外键（`patient_id`/`visit_id`/`prescription_id`/`herb_id`）指向**对方主键 `id`**。照字面实现会得到空结果或错关联。已全部改为 `X.foreignKey == Y.id`。
  - 涉及报表：RPT-VISIT-STATS-001（1）、RPT-SYNDROME-DIST-001（2）、RPT-HERB-USAGE-001（4）、QR-VISIT-PRESCRIPTION-001（5）、QR-HERB-STOCK-001（1）、QR-PRESCRIPTION-OVERDOSE-001（3）、RPT-FOLLOWUP-COMPLETION-001（2）。
  - `preAggregation` 产生的别名（`itemAgg`/`visitPrescriptionAgg`/`flowAgg`）其 `groupBy` 键即外键本身，Join 时同样按主键 `id` 关联。

### 说明

- 本次修正**不新增/删除对象、字段、参数、列**，只修正 Join 表达式的关联口径；`tools/validate_ontology.py` 十类检查复跑全过。
- 已同步重新生成 `code-app/docs/批次3-报表规格（M7抽取）.md`（该抽取文件不得手改，须由 `tools/gen_batch3_spec.py` 重跑）。

## v1.5（2026-09-30，阶段三批次 2 收口时修订）

### 修正（模型与需求/MU 口径不一致，均为阶段二建模偏差）

- **M1 `Visit.chiefComplaint` 必填口径修正**：`required: true` → `false`，并补 description。理由：需求文档 §挂号步骤（FUNC-02：选择患者 → 确认就诊类型 → 写挂号时间 → 生成就诊号）与 MU `frmVisitRegister`（UI-02，12 个元素）**均无主诉元素**，主诉元素位于 `frmVisitReceive`（UI-03，`txaChiefComplaint`）。原建型把「接诊环节必填」误记为「挂号环节必填」，会导致挂号行为无法落地。
- **M2 `Visit_Register` 前置条件删除「主诉已填写，长度不超过 200 字」**：同步上条，主诉不由挂号环节录入。
- **M2 `Visit_Receive` 前置条件新增「主诉已填写，长度不超过 200 字」**：主诉的录入与必填归属接诊环节（该屏有对应元素）。
- **M2 `Prescription_Save` 前置条件放宽**：由「`visit.visitStatus == '接诊中'`」改为「接诊中；或处方状态为『已驳回』时允许修改后重新提交」。理由：`Prescription_Submit` 的 `syncTriggers` 会把就诊收尾为「已完成」，原前置使 M6 Q04「驳回 → 修改 → 重新提交」闭环不可达（需求文档 FUNC-09 明确支持退回修改）。
- **M2 `Prescription_Cancel` 前置条件纳入「已调剂」**：`IN ['草稿','待审核','审核通过']` → `IN ['草稿','待审核','审核通过','已调剂']`。理由：R-04 明确存在「已调剂 → 作废并回冲库存」分支（M2 自身描述亦写明），原前置使该分支不可达，属 M2 内部自相矛盾。已发药/已作废仍不可作废（由 R-04 BLOCK 保证）。

### 说明

- 以上修正**不改变任何编号规则、字段名、行为签名**，仅修正前置条件与必填口径；`tools/validate_ontology.py` 十类检查复跑全过。
- 状态码以 M1 字典为唯一来源（`VISIT_STATUS.IN_PROGRESS`、`PRESCRIPTION_STATUS.PENDING_REVIEW/DISPENSING`）；实施文档中出现的 `IN_CONSULT`/`SUBMITTED`/`DISPENSED` 为阶段三契约笔误，已按模型更正。


## v1.3 — 2026-09-30

### 新增

- **M1 处方聚合（`AGG-PRESCRIPTION-001`）新增属性 `cancelReason`（作废原因）**：需求文档 FUNC-09 要求作废时填写原因，但 OBJ-08 属性表缺该字段（需求侧真空）。已同步在需求文档 OBJ-08 属性表补「作废原因」并升版 v1.3。
- **`Prescription_Cancel` 后置条件字段修正**：`prescription.remark` → `prescription.cancelReason`（原字段在 M1 不存在，M1/M2 字段级不一致，已消除）。
- **MU `frmVisitPrescriptionQuery`（UI-17）的 `txaVoidReason` 绑定 `Prescription.cancelReason`**（原因 M1 缺字段而暂不绑定，缺口已关闭，边界说明 6.e 同步更新）。

### 变更

- **M2 字段路径前缀统一为 M1 聚合别名**（校验器新增「M2 后置条件字段 ⊆ M1」门禁）：`formula.`→`formulaTemplate.`、`syndrome.`→`syndromeType.`、`diagnosis.`→`syndromeDiagnosis.`；子实体集合统一写「聚合别名.子实体别名」：`prescription.items`→`prescription.PrescriptionItem`、`herb.stockFlows`→`herb.HerbStockFlow`、`visit.fourDiagnosis`→`visit.FourDiagnosis`、`formula.items`→`formulaTemplate.FormulaItem`。M2 文件头已补写字段路径约定。

### 门禁

- 校验器新增第 10 类检查（M2 后置条件字段可解析到 M1）；全部检查通过，阻断 0 条、提示 0 条。

## v1.1 — 2026-09-30

阶段二本体建模初版交付，与《中医问诊系统-需求规格说明书-V9.md》v1.2 对齐。

### 新增

- **M2 新增系统自动行为**
  - `Dispense_CreatePending`（B-05 创建待调剂记录）：由审批流 `FLOW-PRESCRIPTION-APPROVAL-001` 的 `approvalOutcome=APPROVE` 分支调用，权限 `PERM-AUTO-DISPENSE-CREATE`（授予 ROLE-07 系统自动主体）。
  - `Dispense_CancelPending`（B-06 取消待调剂记录）：由 `Prescription_Cancel` 经 `RULE-PRESCRIPTION-VOID-DISPATCH` 的 `syncTriggers` 调用，权限 `PERM-AUTO-DISPENSE-CANCEL`（授予 ROLE-07）。
  - 原因：3.12 定义了调剂发药记录「待调剂」初态与 R-04「无记录/待调剂」分支，但原缺创建与取消行为，导致「待调剂」不可达且 R-04 分支无落点。同步新增至需求文档 v1.2。
- **M5 新增权限**：`PERM-AUTO-DISPENSE-CREATE`、`PERM-AUTO-DISPENSE-CANCEL`（M5 权限计数 35 → 37）。
- **M6 新增流程**：`FLOW-PRESCRIPTION-APPROVAL-001`（PROC-APP-01 中药处方审核流，APPROVAL），触发行为 `Prescription_Submit`。

### 变更（需下游注意）

- **M6 审批流边界收敛**：`FLOW-PRESCRIPTION-APPROVAL-001` 只覆盖「提交 → 单节点审批 → 通过/驳回 → 通过后创建待调剂记录」；调剂与发药活动归属协同流 `FLOW-VISIT-001` / `FLOW-FOLLOWUP-001`。需求文档 4.4.1 的原流程图曾把调剂画在同一张图内，已在文档 v1.2 注明流程边界。
- **M2 行为签名**：`Dispense_CreatePending.requiredPermissions` 由空改为 `[PERM-AUTO-DISPENSE-CREATE]`。

### 未变更

- M1 对象模型（9 聚合 / 4 子实体 / 11 字典 / 11 关联）自首次落盘后未做结构性修改。
- M3 规则模型 R-01～R-06 未新增、未删除。
- M7 / MU 为首次落盘。

## v1.4（2026-09-30，阶段三批次 2 实施时补漏）

| 变更 | 模型 | 原因 | 影响面 |
|---|---|---|---|
| `Herb` 新增属性 `toxicDoseLimit`（毒性单张处方总量上限，Decimal，非必填） | M1 | 需求文档 OBJ-07 属性表 v1.1 已定义该字段（R-03 判定输入 `toxicDoseLimit`），但 M1 未落地 → R-03 无法实现 | `code-app/backend/schema.sql` 增列；`herb_service` 与 UI-09 表单增控件；R-03 判定取该字段（为空表示不单独设限） |
| `frmHerbMaintain` 新增元素 `numToxicDoseLimit`（NUMBER / io=I / `Herb.toxicDoseLimit`），布局同步 | MU | 同上（库房管理员需可维护该值，否则 R-03 永远无上限可用） | 前端 UI-09 表单增一个数字输入 |

> 同步说明：`tools/validate_ontology.py` 十类门禁在本次变更后已复跑通过（无阻断、无提示）。

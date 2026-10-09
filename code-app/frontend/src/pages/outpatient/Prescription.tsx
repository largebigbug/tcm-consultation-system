import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, CheckCheck, Plus, Save, Search, Send, Trash2 } from 'lucide-react'
import { herbApi, type Herb } from '../../api/herb'
import { formulaApi } from '../../api/formula'
import {
  prescriptionApi,
  type Prescription as PrescriptionModel,
  type PrescriptionItem,
  type PrescriptionPayload,
} from '../../api/prescription'
import { visitApi, type Visit } from '../../api/visit'
import { dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import Modal from '../../components/Modal'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/** 批次 2 字典键（api/meta.ts 属他人文件不改动，按契约 §7.3 直接使用字典键） */
const DICT_PRESCRIPTION_TYPE = 'DICT-PRESCRIPTION.PRESCRIPTION_TYPE'
const DICT_USAGE_METHOD = 'DICT-PRESCRIPTION.USAGE_METHOD'
const DICT_DECOCTION_METHOD = 'DICT-PRESCRIPTION.DECOCTION_METHOD'
const DICT_PRESCRIPTION_STATUS = 'DICT-PRESCRIPTION.PRESCRIPTION_STATUS'
const DICT_TOXICITY_LEVEL = 'DICT-HERB.TOXICITY_LEVEL'
const DICT_VISIT_STATUS = 'DICT-VISIT.VISIT_STATUS'

/** 就诊状态机码值（兼容 M1 字典 IN_PROGRESS 与契约 IN_CONSULT 两种口径） */
const IN_CONSULT_STATUS = ['IN_CONSULT', 'IN_PROGRESS', 'RECEIVING']
const isInConsult = (status?: string | null) => IN_CONSULT_STATUS.includes(String(status || ''))

/** 处方可编辑状态（草稿 / 已驳回） */
const EDITABLE_STATUS = ['DRAFT', 'REJECTED']

type Verdict = 'PASS' | 'NEED_REASON' | 'BLOCK' | 'UNKNOWN'

interface DoseResult {
  verdict: Verdict
  message: string
  max: number | null
}

interface ItemRow {
  item_id?: string | number
  seq_no: number
  herb_id: number | ''
  single_dose: string
  decoction_method: string
  over_dose_reason: string
  remark: string
  /** 后端详情回显的常用量信息（本地 R-01 判定兜底） */
  herb_name?: string | null
  min_common_dose?: number | null
  max_common_dose?: number | null
  toxicity_level?: string | null
  toxic_dose_limit?: number | null
}

interface MasterState {
  prescription_no: string
  visit_no: string
  patient_name: string
  prescription_type: string
  formula_template_id: number | ''
  formula_label: string
  doses: string
  usage_method: string
  decoction_instruction: string
  medical_advice: string
  prescription_status: string
}

const emptyMaster = (): MasterState => ({
  prescription_no: '',
  visit_no: '',
  patient_name: '',
  prescription_type: '',
  formula_template_id: '',
  formula_label: '',
  doses: '',
  usage_method: '',
  decoction_instruction: '',
  medical_advice: '',
  prescription_status: 'DRAFT',
})

const newItem = (seq: number): ItemRow => ({
  seq_no: seq,
  herb_id: '',
  single_dose: '',
  decoction_method: '',
  over_dose_reason: '',
  remark: '',
})

const num = (v: any): number | null => {
  if (v === null || v === undefined || String(v).trim() === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

interface PopupOption {
  value: number
  label: string
  sub?: string
}

/** 跳选框（POPUP_SELECT）：只读输入框 + 「…」弹窗列表选择 */
function PopupSelect({
  elementId,
  title,
  display,
  placeholder,
  loader,
  onSelect,
}: {
  elementId: string
  title: string
  display: string
  placeholder?: string
  loader: (keyword: string) => Promise<PopupOption[]>
  onSelect: (opt: PopupOption) => void
}) {
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [rows, setRows] = useState<PopupOption[]>([])
  const [loading, setLoading] = useState(false)

  const search = (kw: string) => {
    setLoading(true)
    loader(kw)
      .then((list) => setRows(list))
      .catch((e: any) => {
        toast(e.message, 'error')
        setRows([])
      })
      .finally(() => setLoading(false))
  }

  return (
    <div className="field-control" style={{ display: 'flex', gap: 6 }}>
      <input id={elementId} readOnly value={display} placeholder={placeholder || '点击「…」选择'} />
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => {
          setKeyword('')
          setOpen(true)
          search('')
        }}
      >
        …
      </button>
      <Modal
        title={title}
        open={open}
        onClose={() => setOpen(false)}
        width={660}
        footer={
          <button className="btn btn-secondary" onClick={() => setOpen(false)}>
            关闭
          </button>
        }
      >
        <div className="toolbar" style={{ marginBottom: 12 }}>
          <div className="form-item" style={{ flex: 1 }}>
            <label className="field-label">关键字</label>
            <div className="field-control">
              <input
                value={keyword}
                placeholder="输入方剂名称后回车查询"
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') search(keyword)
                }}
              />
            </div>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => search(keyword)}>
            <Search size={14} /> 查询
          </button>
        </div>
        <div className="table-container" style={{ maxHeight: 320 }}>
          <table>
            <thead>
              <tr>
                <th style={{ width: 70 }}>选择</th>
                <th>方剂模板</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={String(r.value)}>
                  <td>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => {
                        onSelect(r)
                        setOpen(false)
                      }}
                    >
                      选择
                    </button>
                  </td>
                  <td>
                    {r.label}
                    {r.sub && <span className="text-secondary"> · {r.sub}</span>}
                  </td>
                </tr>
              ))}
              {loading && (
                <tr>
                  <td colSpan={2} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    加载中…
                  </td>
                </tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={2} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    无匹配方剂模板
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Modal>
    </div>
  )
}

export default function Prescription() {
  const navigate = useNavigate()
  const { hasPerm } = useAuth()
  const canSave = hasPerm('prescription:save')
  const canSubmit = hasPerm('prescription:submit')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [visits, setVisits] = useState<Visit[]>([])
  const [visitId, setVisitId] = useState<number | null>(null)
  const [master, setMaster] = useState<MasterState>(emptyMaster)
  const [items, setItems] = useState<ItemRow[]>([])
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [herbs, setHerbs] = useState<Herb[]>([])
  const [checked, setChecked] = useState(false)
  const [checkDetail, setCheckDetail] = useState('')
  const [busy, setBusy] = useState(false)

  const loadVisits = () => {
    visitApi
      .list({ page: 1, size: 100 })
      .then((res) => setVisits((res.list || []).filter((v) => isInConsult(v.visit_status))))
      .catch(() => setVisits([]))
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
    herbApi
      .list({ page: 1, size: 200 })
      .then((res) => setHerbs(res.list || []))
      .catch(() => setHerbs([]))
    loadVisits()
  }, [])

  /** 后端对外统一返回 IN_CONSULT（M1 字典 code 为 IN_PROGRESS），显示时做口径别名归一 */
  const visitStatusLabel = (code?: string | null) => dictLabel(dicts, DICT_VISIT_STATUS, code === 'IN_CONSULT' ? 'IN_PROGRESS' : code)

  const typeOptions = dicts[DICT_PRESCRIPTION_TYPE] || []
  const usageOptions = dicts[DICT_USAGE_METHOD] || []
  const decoctionOptions = dicts[DICT_DECOCTION_METHOD] || []

  const setMasterField = (key: keyof MasterState, value: any) => setMaster((m) => ({ ...m, [key]: value }))

  const herbOf = (row: ItemRow): Herb | undefined =>
    row.herb_id === '' ? undefined : herbs.find((h) => h.id === Number(row.herb_id))

  const herbNameOf = (row: ItemRow): string => {
    const h = herbOf(row)
    if (h) return h.herb_name
    if (row.herb_name) return String(row.herb_name)
    return row.herb_id === '' ? '' : `饮片 #${row.herb_id}`
  }

  const rangeOf = (row: ItemRow): { min: number | null; max: number | null } => {
    const h = herbOf(row)
    const min = h ? num(h.min_common_dose) : num(row.min_common_dose)
    const max = h ? num(h.max_common_dose) : num(row.max_common_dose)
    return { min, max }
  }

  const toxicityOf = (row: ItemRow): string => {
    const h = herbOf(row)
    return String((h ? h.toxicity_level : row.toxicity_level) || 'NONE')
  }

  /** R-01 逐味判定（PASS / NEED_REASON / BLOCK） */
  const judge = (row: ItemRow): DoseResult => {
    const name = herbNameOf(row) || `第 ${row.seq_no} 行`
    const dose = num(row.single_dose)
    if (dose === null || dose <= 0) {
      return { verdict: 'BLOCK', message: `${name} 单剂剂量须大于 0`, max: null }
    }
    const { max } = rangeOf(row)
    if (max === null) {
      return { verdict: 'UNKNOWN', message: `${name} 未取到常用量上限，无法本地判定（以后端校验为准）`, max: null }
    }
    if (dose <= max) return { verdict: 'PASS', message: '', max }
    if (dose > max * 2) {
      return { verdict: 'BLOCK', message: `${name} 单剂剂量 ${dose}g 超过常用最大量 ${max}g 的 2 倍，禁止开具`, max }
    }
    return { verdict: 'NEED_REASON', message: `${name} 单剂剂量 ${dose}g 超过常用最大量 ${max}g，请填写超量理由`, max }
  }

  const results = useMemo(() => items.map(judge), [items, herbs])
  const passCount = results.filter((r) => r.verdict === 'PASS').length
  const needReasonCount = results.filter((r) => r.verdict === 'NEED_REASON').length
  const blockCount = results.filter((r) => r.verdict === 'BLOCK').length
  const unknownCount = results.filter((r) => r.verdict === 'UNKNOWN').length
  const missingReasonCount = items.filter((row, i) => results[i].verdict === 'NEED_REASON' && !row.over_dose_reason.trim()).length
  const hasBlock = blockCount > 0

  /** R-03 毒性饮片总量（单张处方 SUM(single_dose)）本地提示 */
  const toxicIssues = useMemo(() => {
    const issues: string[] = []
    const seen = new Set<number>()
    items.forEach((row) => {
      const id = row.herb_id === '' ? null : Number(row.herb_id)
      if (id === null || seen.has(id)) return
      seen.add(id)
      const h = herbOf(row)
      const toxicity = toxicityOf(row)
      const limit = h ? num((h as any).toxic_dose_limit) : num(row.toxic_dose_limit)
      if (toxicity === 'NONE' || limit === null) return
      const total = items
        .filter((r) => Number(r.herb_id) === id)
        .reduce((sum, r) => sum + (num(r.single_dose) || 0), 0)
      if (total > limit) {
        issues.push(`毒性饮片 ${herbNameOf(row)} 单张处方总量 ${total}g 超过上限 ${limit}g`)
      }
    })
    return issues
  }, [items, herbs])

  const setItemField = (idx: number, patch: Partial<ItemRow>) =>
    setItems((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)))

  const applyDetail = (p: PrescriptionModel) => {
    setCurrentId(p.id)
    setMaster({
      prescription_no: p.prescription_no || '',
      visit_no: master.visit_no,
      patient_name: p.patient_name || master.patient_name,
      prescription_type: p.prescription_type || '',
      formula_template_id: p.formula_template_id ?? '',
      formula_label: p.formula_name ? String(p.formula_name) : p.formula_template_id ? `方剂 #${p.formula_template_id}` : '',
      doses: p.doses === null || p.doses === undefined ? '' : String(p.doses),
      usage_method: p.usage_method || '',
      decoction_instruction: p.decoction_instruction || '',
      medical_advice: p.medical_advice || '',
      prescription_status: p.prescription_status || 'DRAFT',
    })
    setItems(
      (p.items || []).map((it: PrescriptionItem, i) => ({
        item_id: it.item_id,
        seq_no: it.seq_no || i + 1,
        herb_id: it.herb_id ?? '',
        single_dose: it.single_dose === null || it.single_dose === undefined ? '' : String(it.single_dose),
        decoction_method: it.decoction_method || '',
        over_dose_reason: it.over_dose_reason || '',
        remark: it.remark || '',
        herb_name: it.herb_name ?? null,
        min_common_dose: num(it.min_common_dose),
        max_common_dose: num(it.max_common_dose),
        toxicity_level: it.toxicity_level ?? null,
        toxic_dose_limit: num(it.toxic_dose_limit),
      })),
    )
    setChecked(false)
    if (p.formula_template_id && !p.formula_name) {
      formulaApi
        .get(p.formula_template_id)
        .then((tpl) => setMaster((m) => ({ ...m, formula_label: `${tpl.formula_code} ${tpl.formula_name}` })))
        .catch(() => undefined)
    }
  }

  const onLoadVisit = async (id: number) => {
    if (!id) return
    setVisitId(id)
    setCurrentId(null)
    setMaster(emptyMaster())
    setItems([])
    setChecked(false)
    try {
      const v = await visitApi.get(id)
      setMaster((m) => ({ ...m, visit_no: v.visit_no || '', patient_name: v.patient_name || '' }))
      // 若该就诊已有草稿 / 已驳回处方，载入继续编辑
      const res = await prescriptionApi.list({ page: 1, size: 50, visit_id: id }).catch(() => null)
      const editable = (res?.list || []).find((p) => EDITABLE_STATUS.includes(String(p.prescription_status)))
      if (editable) {
        const detail = await prescriptionApi.get(editable.id)
        applyDetail({ ...detail, visit_id: id })
        toast(`已载入${String(detail.prescription_status) === 'REJECTED' ? '已驳回' : '草稿'}处方 ${detail.prescription_no}`)
      }
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  const onFormulaSelect = async (opt: PopupOption) => {
    setMasterField('formula_template_id', opt.value)
    setMasterField('formula_label', opt.label)
    try {
      const tpl = await formulaApi.get(opt.value)
      const tplItems: ItemRow[] = (tpl.items || []).map((it, i) => ({
        seq_no: i + 1,
        herb_id: it.herb_id ?? '',
        single_dose: it.common_dose === null || it.common_dose === undefined ? '' : String(it.common_dose),
        decoction_method: it.decoction_method || '',
        over_dose_reason: '',
        remark: '',
      }))
      if (tplItems.length) setItems(tplItems)
      if (!master.doses && tpl.default_doses) setMasterField('doses', String(tpl.default_doses))
      toast('已带出方剂组成，可加减调整')
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  const addHerbRow = () => setItems((rows) => [...rows, newItem(rows.length + 1)])

  const removeItem = (idx: number) =>
    setItems((rows) => rows.filter((_, i) => i !== idx).map((r, i) => ({ ...r, seq_no: i + 1 })))

  const onRecheckDose = () => {
    setChecked(true)
    if (items.length === 0) {
      toast('请先添加药味', 'error')
      return
    }
    const parts = [`正常 ${passCount} 味`, `超量需理由 ${needReasonCount} 味`, `超 2 倍阻断 ${blockCount} 味`]
    if (unknownCount) parts.push(`无法判定 ${unknownCount} 味`)
    const head = `剂量校验（R-01）：${parts.join(' / ')}`
    const detailMsgs = results.filter((r) => r.verdict !== 'PASS' && r.message).map((r) => r.message)
    const toxicMsgs = toxicIssues.map((t) => `[R-03] ${t}`)
    const all = [head, ...detailMsgs, ...toxicMsgs].join('\n')
    if (blockCount > 0 || toxicIssues.length > 0) {
      toast(`剂量校验未通过：${blockCount + toxicIssues.length} 项阻断，详见校验提示`, 'error')
    } else if (needReasonCount > 0) {
      toast(`剂量校验：${needReasonCount} 味超量需填写超量理由`, 'error')
    } else {
      toast('剂量校验通过：全部药味单剂剂量在常用量上限内')
    }
    setCheckDetail(all)
  }

  const validate = (needReason: boolean): string | null => {
    if (!visitId) return '请先选择接诊中的就诊记录'
    if (!master.prescription_type) return '处方类型不能为空'
    const doses = num(master.doses)
    if (doses === null || doses < 1 || doses > 30) return '剂数须为 1～30'
    if (!master.usage_method) return '用法不能为空'
    if (items.length === 0) return '处方明细至少 1 味饮片'
    const used = new Set<number>()
    for (let i = 0; i < items.length; i++) {
      const row = items[i]
      if (row.herb_id === '') return `第 ${i + 1} 行未选择饮片`
      const id = Number(row.herb_id)
      if (used.has(id)) return '同一处方内饮片不得重复'
      used.add(id)
      const dose = num(row.single_dose)
      if (dose === null || dose <= 0) return `第 ${i + 1} 行单剂剂量须大于 0`
    }
    const blocked = results.find((r) => r.verdict === 'BLOCK')
    if (blocked) return blocked.message
    if (toxicIssues.length > 0) return toxicIssues[0]
    if (needReason) {
      const missing = items.find((row, i) => results[i].verdict === 'NEED_REASON' && !row.over_dose_reason.trim())
      if (missing) return `${herbNameOf(missing)} 超量需填写超量理由`
    }
    return null
  }

  const buildPayload = (): PrescriptionPayload => ({
    visit_id: Number(visitId),
    prescription_type: master.prescription_type,
    formula_template_id: master.formula_template_id === '' ? null : Number(master.formula_template_id),
    doses: Number(master.doses),
    usage_method: master.usage_method,
    decoction_instruction: master.decoction_instruction || null,
    medical_advice: master.medical_advice || null,
    items: items.map((r, i) => ({
      seq_no: i + 1,
      herb_id: Number(r.herb_id),
      single_dose: Number(r.single_dose),
      decoction_method: r.decoction_method || null,
      remark: r.remark || null,
      over_dose_reason: r.over_dose_reason.trim() || null,
    })),
  })

  const persist = async (): Promise<PrescriptionModel> => {
    const payload = buildPayload()
    const saved = currentId ? await prescriptionApi.update(currentId, payload) : await prescriptionApi.create(payload)
    applyDetail(saved)
    return saved
  }

  const onSaveDraft = async () => {
    const err = validate(false)
    if (err) {
      toast(err, 'error')
      return
    }
    setBusy(true)
    try {
      await persist()
      toast('已保存为草稿')
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const onSubmit = async () => {
    const err = validate(true)
    if (err) {
      toast(err, 'error')
      return
    }
    setBusy(true)
    try {
      const saved = await persist()
      const submitted = await prescriptionApi.submit(saved.id)
      applyDetail(submitted)
      toast('已提交送审（状态：待审核）')
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {/* 入口列表：接诊中就诊（MU 表单无列表元素，此栏仅作载入入口） */}
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">接诊中就诊</label>
            <div className="field-control">
              <select value={visitId ?? ''} onChange={(e) => onLoadVisit(Number(e.target.value))}>
                <option value="">请选择接诊中的就诊记录…</option>
                {visits.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.visit_no} {v.patient_name || ''} · {visitStatusLabel(v.visit_status)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <span className="text-secondary">
            前置：就诊「接诊中」且已有已确认的辨证结论；一次就诊可开多张处方
            {master.prescription_status ? ` · 当前处方状态：${dictLabel(dicts, DICT_PRESCRIPTION_STATUS, master.prescription_status)}` : ''}
          </span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>主表：处方（AGG-PRESCRIPTION-001）</h3>
        </div>
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">处方号</label>
            <div className="field-control">
              <input id="txtPrescriptionNo" value={master.prescription_no} disabled placeholder="保存后由系统生成" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">就诊号</label>
            <div className="field-control">
              <input id="txtVisitNo" value={master.visit_no} disabled placeholder="载入就诊后回显" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">患者</label>
            <div className="field-control">
              <input id="lblPatientName" value={master.patient_name} disabled placeholder="载入就诊后回显" />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">处方类型</label>
            <div className="field-control">
              <select
                id="cboPrescriptionType"
                value={master.prescription_type}
                onChange={(e) => setMasterField('prescription_type', e.target.value)}
              >
                <option value="">请选择</option>
                {typeOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">引用方剂</label>
            <PopupSelect
              elementId="pslFormulaTemplate"
              title="选择方剂模板（选方后带出组成）"
              display={master.formula_label}
              placeholder="点击「…」选择方剂模板"
              loader={(kw) =>
                formulaApi
                  .list({ page: 1, size: 50, formula_name: kw || undefined, formula_status: 'ENABLED' })
                  .then((res) =>
                    (res.list || []).map((f) => ({
                      value: f.id,
                      label: `${f.formula_code} ${f.formula_name}`,
                      sub: `默认剂数 ${f.default_doses ?? '—'}`,
                    })),
                  )
              }
              onSelect={onFormulaSelect}
            />
          </div>
          <div className="form-item">
            <label className="field-label required">剂数</label>
            <div className="field-control">
              <input
                id="numDoses"
                type="number"
                min={1}
                max={30}
                value={master.doses}
                onChange={(e) => setMasterField('doses', e.target.value)}
                placeholder="1～30"
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">用法</label>
            <div className="field-control">
              <select id="cboUsageMethod" value={master.usage_method} onChange={(e) => setMasterField('usage_method', e.target.value)}>
                <option value="">请选择</option>
                {usageOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">煎服说明</label>
            <div className="field-control">
              <input
                id="txtDecoctionInstruction"
                value={master.decoction_instruction}
                onChange={(e) => setMasterField('decoction_instruction', e.target.value)}
                placeholder="代煎、特殊煎法汇总说明"
              />
            </div>
          </div>
          <div className="form-item span-3">
            <label className="field-label">医嘱嘱托</label>
            <div className="field-control">
              <textarea
                id="txaMedicalAdvice"
                rows={2}
                value={master.medical_advice}
                onChange={(e) => setMasterField('medical_advice', e.target.value)}
                placeholder="饮食起居禁忌等"
              />
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>从表：处方明细（PrescriptionItem）</h3>
          <span className="text-secondary">
            规则提示：R-01 超量需填写超量理由并强制审核、超常用上限 2 倍阻断；R-03 毒性饮片总量超上限阻断提交
          </span>
        </div>
        {checked && checkDetail && (
          <div
            style={{
              whiteSpace: 'pre-wrap',
              padding: '8px 12px',
              marginBottom: 12,
              borderRadius: 8,
              background: hasBlock || toxicIssues.length > 0 ? '#fef2f2' : needReasonCount > 0 ? '#fff7ed' : '#f0fdf4',
              color: hasBlock || toxicIssues.length > 0 ? '#991b1b' : needReasonCount > 0 ? '#854d0e' : '#166534',
            }}
          >
            {checkDetail}
          </div>
        )}
        <div className="table-container" id="grdPrescriptionItems">
          <table>
            <thead>
              <tr>
                <th style={{ width: 60 }}>序号</th>
                <th style={{ width: 220 }}>饮片</th>
                <th style={{ width: 130 }}>单剂剂量（g）</th>
                <th style={{ width: 130 }}>常用量区间</th>
                <th style={{ width: 150 }}>特殊煎法</th>
                <th style={{ width: 220 }}>超量理由</th>
                <th style={{ width: 90 }}>删除</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row, idx) => {
                const res = results[idx] || { verdict: 'PASS' as Verdict, message: '', max: null }
                const range = rangeOf(row)
                const over = res.verdict === 'NEED_REASON' || res.verdict === 'BLOCK'
                const bg = res.verdict === 'BLOCK' ? '#fef2f2' : res.verdict === 'NEED_REASON' ? '#fff7ed' : undefined
                return (
                  <tr key={idx} style={bg ? { background: bg } : undefined}>
                    <td>{idx + 1}</td>
                    <td>
                      <select
                        className="table-input"
                        value={row.herb_id}
                        onChange={(e) => setItemField(idx, { herb_id: e.target.value ? Number(e.target.value) : '' })}
                      >
                        <option value="">请选择饮片</option>
                        {herbs.map((h) => (
                          <option key={h.id} value={h.id}>
                            {h.herb_code} {h.herb_name}
                            {h.toxicity_level && h.toxicity_level !== 'NONE'
                              ? `（${dictLabel(dicts, DICT_TOXICITY_LEVEL, h.toxicity_level)}）`
                              : ''}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input
                        className="table-input"
                        type="number"
                        min={0}
                        step="0.1"
                        value={row.single_dose}
                        onChange={(e) => setItemField(idx, { single_dose: e.target.value })}
                      />
                      {checked && res.message && (
                        <div style={{ fontSize: '9pt', marginTop: 4, color: res.verdict === 'BLOCK' ? '#991b1b' : '#854d0e' }}>
                          {res.verdict === 'BLOCK' ? '超 2 倍阻断' : res.verdict === 'NEED_REASON' ? '超量需理由' : '无法判定'}：
                          {res.message}
                        </div>
                      )}
                    </td>
                    <td className="text-secondary">
                      {range.min === null && range.max === null ? '—' : `${range.min ?? '—'} ～ ${range.max ?? '—'} g`}
                    </td>
                    <td>
                      <select
                        className="table-input"
                        value={row.decoction_method}
                        onChange={(e) => setItemField(idx, { decoction_method: e.target.value })}
                      >
                        <option value="">用字典默认</option>
                        {decoctionOptions.map((it) => (
                          <option key={it.code} value={it.code}>
                            {it.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      {over ? (
                        <input
                          className="table-input"
                          value={row.over_dose_reason}
                          placeholder="超量理由（必填）"
                          onChange={(e) => setItemField(idx, { over_dose_reason: e.target.value })}
                        />
                      ) : (
                        <span className="text-secondary">—</span>
                      )}
                    </td>
                    <td>
                      <button className="btn btn-secondary btn-sm" onClick={() => removeItem(idx)}>
                        <Trash2 size={14} /> 删除
                      </button>
                    </td>
                  </tr>
                )
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无处方明细，请点击「添加药味」或先选择引用方剂
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="toolbar" style={{ marginTop: 12 }}>
          <button id="btnAddHerbRow" className="btn btn-secondary" onClick={addHerbRow}>
            <Plus size={14} /> 添加药味
          </button>
          <button id="btnRecheckDose" className="btn btn-secondary" onClick={onRecheckDose}>
            <AlertTriangle size={14} /> 检查剂量
          </button>
          {checked && (
            <span className="text-secondary">
              正常 {passCount} 味 · 超量需理由 {needReasonCount} 味{missingReasonCount ? `（未填理由 ${missingReasonCount} 味）` : ''} ·
              超 2 倍阻断 {blockCount} 味
            </span>
          )}
        </div>
        <div className="toolbar-right">
          {canSave && (
            <button id="btnSaveDraft" className="btn btn-primary" onClick={onSaveDraft} disabled={busy}>
              <Save size={14} /> {busy ? '处理中…' : '保存草稿'}
            </button>
          )}
          {canSubmit && (
            <button id="btnSubmit" className="btn btn-primary" onClick={onSubmit} disabled={busy || hasBlock}>
              <Send size={14} /> 提交
            </button>
          )}
          <button id="btnBack" className="btn btn-secondary" onClick={() => navigate(-1)}>
            <ArrowLeft size={14} /> 返回
          </button>
        </div>
        {hasBlock && (
          <div className="text-secondary mt-16" style={{ color: '#991b1b' }}>
            存在单剂剂量超过常用最大量 2 倍的药味，已阻断保存与提交（R-01）。
          </div>
        )}
        {missingReasonCount > 0 && !hasBlock && (
          <div className="text-secondary mt-16" style={{ color: '#854d0e' }}>
            <CheckCheck size={12} /> 有 {missingReasonCount} 味超量药味未填写超量理由，提交前须补齐（R-01）。
          </div>
        )}
      </div>
    </div>
  )
}

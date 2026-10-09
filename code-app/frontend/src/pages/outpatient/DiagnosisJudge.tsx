import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, Plus, Save, Search, Trash2 } from 'lucide-react'
import { diagnosisApi, type DiagnosisPayload, type SyndromeDiagnosis } from '../../api/diagnosis'
import { syndromeApi } from '../../api/syndrome'
import { visitApi, type Visit } from '../../api/visit'
import { dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import Modal from '../../components/Modal'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/** 批次 2 字典键（api/meta.ts 属他人文件不改动，按契约 §7.3 直接使用字典键） */
const DICT_DIAG_METHOD = 'DICT-SYNDROME.DIAG_METHOD'
const DICT_SYNDROME_NATURE = 'DICT-SYNDROME.SYNDROME_NATURE'
const DICT_CONCLUSION_STATUS = 'DICT-SYNDROME.CONCLUSION_STATUS'
const DICT_VISIT_STATUS = 'DICT-VISIT.VISIT_STATUS'

/** 就诊状态机码值（兼容 M1 字典 IN_PROGRESS 与契约 IN_CONSULT 两种口径） */
const IN_CONSULT_STATUS = ['IN_CONSULT', 'IN_PROGRESS', 'RECEIVING']
const isInConsult = (status?: string | null) => IN_CONSULT_STATUS.includes(String(status || ''))

interface DiagRow {
  id?: number
  diagnosis_no?: string
  conclusion_status?: string
  diagnosis_method: string
  syndrome_id: number | ''
  syndrome_label: string
  syndrome_nature: string
  diagnosis_basis: string
  treatment_principle: string
}

const newRow = (): DiagRow => ({
  diagnosis_method: '',
  syndrome_id: '',
  syndrome_label: '',
  syndrome_nature: '',
  diagnosis_basis: '',
  treatment_principle: '',
})

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
    <>
      <div className="field-control" style={{ display: 'flex', gap: 4 }}>
        <input
          id={`${elementId}-${title}`}
          className="table-input"
          readOnly
          value={display}
          placeholder={placeholder || '点击「…」选择'}
          style={{ flex: 1, minWidth: 90 }}
        />
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
      </div>
      <Modal
        title={title}
        open={open}
        onClose={() => setOpen(false)}
        width={640}
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
                placeholder="输入名称后回车查询"
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
                <th>证型</th>
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
                    无匹配证型
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Modal>
    </>
  )
}

export default function DiagnosisJudge() {
  const navigate = useNavigate()
  const { hasPerm } = useAuth()
  const canSave = hasPerm('diagnosis:save')
  const canConfirm = hasPerm('diagnosis:confirm')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [visits, setVisits] = useState<Visit[]>([])
  const [visitId, setVisitId] = useState<number | null>(null)
  const [visitNo, setVisitNo] = useState('')
  const [patientName, setPatientName] = useState('')
  const [doctorId, setDoctorId] = useState('')
  const [summary, setSummary] = useState('')
  const [rows, setRows] = useState<DiagRow[]>([])
  const [busy, setBusy] = useState(false)

  const loadVisits = () => {
    visitApi
      .list({ page: 1, size: 100 })
      .then((res) => setVisits((res.list || []).filter((v) => isInConsult(v.visit_status))))
      .catch(() => setVisits([]))
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
    loadVisits()
  }, [])

  /** 后端对外统一返回 IN_CONSULT（M1 字典 code 为 IN_PROGRESS），显示时做口径别名归一 */
  const visitStatusLabel = (code?: string | null) => dictLabel(dicts, DICT_VISIT_STATUS, code === 'IN_CONSULT' ? 'IN_PROGRESS' : code)

  const methodOptions = dicts[DICT_DIAG_METHOD] || []
  const natureOptions = dicts[DICT_SYNDROME_NATURE] || []

  const toRow = (d: SyndromeDiagnosis): DiagRow => ({
    id: d.id,
    diagnosis_no: d.diagnosis_no,
    conclusion_status: d.conclusion_status,
    diagnosis_method: d.diagnosis_method || '',
    syndrome_id: d.syndrome_id ?? '',
    syndrome_label: d.syndrome_name ? `${d.syndrome_code || ''} ${d.syndrome_name}`.trim() : String(d.syndrome_id ?? ''),
    syndrome_nature: d.syndrome_nature || '',
    diagnosis_basis: d.diagnosis_basis || '',
    treatment_principle: d.treatment_principle || '',
  })

  const loadDiagnoses = async (id: number) => {
    const list = await diagnosisApi.list(id)
    setRows((list || []).map(toRow))
  }

  const onLoad = async (id: number) => {
    if (!id) return
    try {
      const v = await visitApi.get(id)
      setVisitId(v.id)
      setVisitNo(v.visit_no || '')
      setPatientName(v.patient_name || '')
      setDoctorId(v.doctor_id || '')
      const fd = v.four_diagnosis || (v as any).fourDiagnosis || null
      setSummary(fd?.four_diagnosis_summary || '')
      if (!fd?.four_diagnosis_summary) {
        const detail = await visitApi.fourDiagnosis(v.id).catch(() => null)
        setSummary(detail?.four_diagnosis_summary || '')
      }
      await loadDiagnoses(v.id)
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  const patchRow = (idx: number, patch: Partial<DiagRow>) =>
    setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, ...patch } : r)))

  const addRow = () => setRows((rs) => [...rs, newRow()])

  const removeRow = (idx: number) => setRows((rs) => rs.filter((_, i) => i !== idx))

  const primaryCount = rows.filter((r) => r.syndrome_nature === 'PRIMARY').length
  const draftCount = rows.filter((r) => (r.conclusion_status || 'DRAFT') === 'DRAFT').length
  const confirmedCount = rows.filter((r) => r.conclusion_status === 'CONFIRMED').length

  const validate = (): string | null => {
    if (!visitId) return '请先选择接诊中的就诊记录'
    if (rows.length === 0) return '请至少添加一条辨证结论'
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i]
      if (!r.diagnosis_method) return `第 ${i + 1} 行：辨证方法不能为空`
      if (r.syndrome_id === '') return `第 ${i + 1} 行：证型不能为空`
      if (!r.syndrome_nature) return `第 ${i + 1} 行：证型性质不能为空`
      if (r.diagnosis_basis.trim().length < 10) return `第 ${i + 1} 行：辨证依据不少于 10 字`
      if (!r.treatment_principle.trim()) return `第 ${i + 1} 行：治法不能为空`
    }
    if (primaryCount > 1) return '主证性质在同一就诊下唯一（INV-02）'
    return null
  }

  /** 逐行保存（新增/修改），返回带 id 的行；失败返回 null */
  const persistRows = async (): Promise<DiagRow[] | null> => {
    if (!visitId) return null
    const saved: DiagRow[] = []
    for (const r of rows) {
      const payload: DiagnosisPayload = {
        visit_id: visitId,
        diagnosis_method: r.diagnosis_method,
        syndrome_id: Number(r.syndrome_id),
        syndrome_nature: r.syndrome_nature,
        diagnosis_basis: r.diagnosis_basis.trim(),
        treatment_principle: r.treatment_principle.trim(),
      }
      const res = r.id ? await diagnosisApi.update(r.id, payload) : await diagnosisApi.create(payload)
      saved.push({ ...r, ...toRow(res) })
    }
    setRows(saved)
    return saved
  }

  const onSave = async () => {
    const err = validate()
    if (err) {
      toast(err, 'error')
      return
    }
    setBusy(true)
    try {
      await persistRows()
      toast('辨证结论已保存（结论状态：草稿）')
      if (visitId) await loadDiagnoses(visitId)
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const onConfirm = async () => {
    const err = validate()
    if (err) {
      toast(err, 'error')
      return
    }
    setBusy(true)
    try {
      const saved = await persistRows()
      if (!saved) return
      const todo = saved.filter((r) => r.id && r.conclusion_status !== 'CONFIRMED')
      if (todo.length === 0) {
        toast('辨证结论均已确认，无需重复确认')
        return
      }
      for (const r of todo) {
        await diagnosisApi.confirm(r.id as number)
      }
      toast(`已确认 ${todo.length} 条辨证结论`)
      if (visitId) await loadDiagnoses(visitId)
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
              <select value={visitId ?? ''} onChange={(e) => onLoad(Number(e.target.value))}>
                <option value="">请选择接诊中的就诊记录…</option>
                {visits.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.visit_no} {v.patient_name || ''} · {visitStatusLabel(v.visit_status)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <span className="text-secondary">所属就诊必须已有四诊信息，方可保存辨证结论</span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>主表：就诊摘要（只读）</h3>
        </div>
        <div className="form-grid-2">
          <div className="form-item">
            <label className="field-label">就诊号</label>
            <div className="field-control">
              <input id="txtVisitNo" value={visitNo} disabled placeholder="载入就诊后回显" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">患者</label>
            <div className="field-control">
              <input id="lblPatientName" value={patientName} disabled placeholder="载入就诊后回显" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">接诊医师</label>
            <div className="field-control">
              <input id="txtDoctorId" value={doctorId} disabled />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">四诊摘要</label>
            <div className="field-control">
              <textarea id="txaFourDiagnosisSummary" rows={2} value={summary} disabled placeholder="引用四诊录入结果" />
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>从表：辨证结论（AGG-DIAGNOSIS-001）</h3>
          <span className="text-secondary">
            规则提示：主证性质在同一就诊下唯一（INV-02，从表内「主证」只能一行）；结论状态：草稿 {draftCount} 条 / 已确认{' '}
            {confirmedCount} 条
          </span>
        </div>
        <div className="table-container" id="grdDiagnosis">
          <table>
            <thead>
              <tr>
                <th style={{ width: 60 }}>序号</th>
                <th style={{ width: 150 }}>辨证方法</th>
                <th style={{ width: 210 }}>证型</th>
                <th style={{ width: 120 }}>性质</th>
                <th>辨证依据</th>
                <th style={{ width: 170 }}>治法</th>
                <th style={{ width: 90 }}>删除</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr key={idx}>
                  <td>{idx + 1}</td>
                  <td>
                    <select
                      className="table-input"
                      value={row.diagnosis_method}
                      onChange={(e) => patchRow(idx, { diagnosis_method: e.target.value })}
                    >
                      <option value="">请选择</option>
                      {methodOptions.map((it) => (
                        <option key={it.code} value={it.code}>
                          {it.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <PopupSelect
                      elementId={`pslSyndrome-${idx}`}
                      title={`选择证型（第 ${idx + 1} 行）`}
                      display={row.syndrome_label}
                      loader={(kw) =>
                        syndromeApi
                          .list({ page: 1, size: 50, syndrome_name: kw || undefined, syndrome_status: 'ENABLED' })
                          .then((res) =>
                            (res.list || []).map((s) => ({
                              value: s.id,
                              label: `${s.syndrome_code} ${s.syndrome_name}`,
                              sub: s.corresponding_treatment || undefined,
                            })),
                          )
                      }
                      onSelect={(opt) => patchRow(idx, { syndrome_id: opt.value, syndrome_label: opt.label })}
                    />
                  </td>
                  <td>
                    <select
                      className="table-input"
                      value={row.syndrome_nature}
                      onChange={(e) => patchRow(idx, { syndrome_nature: e.target.value })}
                    >
                      <option value="">请选择</option>
                      {natureOptions.map((it) => (
                        <option
                          key={it.code}
                          value={it.code}
                          disabled={it.code === 'PRIMARY' && row.syndrome_nature !== 'PRIMARY' && primaryCount > 0}
                        >
                          {it.label}
                          {it.code === 'PRIMARY' && primaryCount > 0 && row.syndrome_nature !== 'PRIMARY' ? '（已存在主证）' : ''}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      className="table-input"
                      value={row.diagnosis_basis}
                      placeholder="不少于 10 字"
                      onChange={(e) => patchRow(idx, { diagnosis_basis: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      className="table-input"
                      value={row.treatment_principle}
                      placeholder="如「疏肝理气」"
                      onChange={(e) => patchRow(idx, { treatment_principle: e.target.value })}
                    />
                  </td>
                  <td>
                    <button className="btn btn-secondary btn-sm" onClick={() => removeRow(idx)}>
                      <Trash2 size={14} /> 删除
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无辨证结论，请点击「添加辨证结论」
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="toolbar" style={{ marginTop: 12 }}>
          <button id="btnAddDiagnosisRow" className="btn btn-secondary" onClick={addRow}>
            <Plus size={14} /> 添加辨证结论
          </button>
          {rows.some((r) => r.conclusion_status === 'CONFIRMED') && (
            <span className="text-secondary">
              已有结论状态为「{dictLabel(dicts, DICT_CONCLUSION_STATUS, 'CONFIRMED')}」，草稿结论不可再修改
            </span>
          )}
        </div>
        <div className="toolbar-right">
          {canSave && (
            <button id="btnSave" className="btn btn-primary" onClick={onSave} disabled={busy}>
              <Save size={14} /> {busy ? '处理中…' : '保存'}
            </button>
          )}
          {canConfirm && (
            <button id="btnConfirm" className="btn btn-primary" onClick={onConfirm} disabled={busy}>
              <CheckCircle2 size={14} /> 确认结论
            </button>
          )}
          <button id="btnBack" className="btn btn-secondary" onClick={() => navigate(-1)}>
            <ArrowLeft size={14} /> 返回
          </button>
        </div>
      </div>
    </div>
  )
}

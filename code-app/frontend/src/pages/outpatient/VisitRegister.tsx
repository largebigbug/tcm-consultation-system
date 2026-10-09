import { useEffect, useState } from 'react'
import { Eraser, Save, Search, XCircle } from 'lucide-react'
import { patientApi } from '../../api/patient'
import { visitApi, type Visit, type VisitPayload } from '../../api/visit'
import { dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import Modal from '../../components/Modal'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/** 批次 2 字典键（api/meta.ts 的 DICT 常量属他人文件，不改动，故按契约 §7.3 直接使用字典键） */
const DICT_VISIT_TYPE = 'DICT-VISIT.VISIT_TYPE'
const DICT_VISIT_STATUS = 'DICT-VISIT.VISIT_STATUS'
const DICT_VISIT_DEPT = 'DICT-VISIT.DEPT'

interface FormState {
  visit_no: string
  patient_id: number | ''
  visit_type: string
  previous_visit_id: number | ''
  register_time: string
  dept_code: string
  doctor_id: string
  visit_status: string
  remark: string
}

const pad = (n: number) => String(n).padStart(2, '0')

/** Date → `YYYY-MM-DDTHH:mm`（datetime-local 取值格式） */
function nowLocal(): string {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 后端 datetime → datetime-local 显示值 */
function toLocalInput(v?: string | null): string {
  if (!v) return ''
  const s = String(v).replace(' ', 'T')
  return s.length >= 16 ? s.slice(0, 16) : s
}

/** datetime-local → 后端 datetime 入参（SQLite 友好） */
function fromLocalInput(v: string): string | null {
  if (!v) return null
  const s = v.replace('T', ' ')
  return s.length === 16 ? `${s}:00` : s
}

const emptyForm = (): FormState => ({
  visit_no: '',
  patient_id: '',
  visit_type: '',
  previous_visit_id: '',
  register_time: nowLocal(),
  dept_code: '',
  doctor_id: '',
  visit_status: 'REGISTERED',
  remark: '',
})

/** 就诊状态机码值（兼容 M1 字典 IN_PROGRESS 与契约 IN_CONSULT 两种口径） */
const CANCELLABLE_STATUS = ['REGISTERED', 'IN_PROGRESS', 'IN_CONSULT', 'RECEIVING']

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
  disabled,
  placeholder,
  loader,
  onSelect,
}: {
  elementId: string
  title: string
  display: string
  disabled?: boolean
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

  const openDialog = () => {
    setKeyword('')
    setOpen(true)
    search('')
  }

  return (
    <div className="field-control" style={{ display: 'flex', gap: 6 }}>
      <input id={elementId} readOnly value={display} placeholder={placeholder || '点击「…」选择'} disabled={disabled} />
      <button type="button" className="btn btn-secondary btn-sm" disabled={disabled} onClick={openDialog}>
        …
      </button>
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
                placeholder="输入名称 / 编号后回车查询"
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
                <th>记录</th>
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
                    无匹配记录
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

export default function VisitRegister() {
  const { hasPerm } = useAuth()
  const canRegister = hasPerm('visit:register')
  const canCancel = hasPerm('visit:cancel')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [form, setForm] = useState<FormState>(emptyForm)
  const [patientLabel, setPatientLabel] = useState('')
  const [previousLabel, setPreviousLabel] = useState('')
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [hasPrescription, setHasPrescription] = useState(false)
  const [visits, setVisits] = useState<Visit[]>([])
  const [saving, setSaving] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelReason, setCancelReason] = useState('')

  const loadVisits = () => {
    visitApi
      .list({ page: 1, size: 100 })
      .then((res) => setVisits(res.list || []))
      .catch(() => setVisits([]))
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
    loadVisits()
  }, [])

  const visitTypeOptions = dicts[DICT_VISIT_TYPE] || []
  const visitStatusOptions = dicts[DICT_VISIT_STATUS] || []
  const deptOptions = dicts[DICT_VISIT_DEPT] || []

  /** 后端对外统一返回 IN_CONSULT（M1 字典 code 为 IN_PROGRESS），显示时做口径别名归一 */
  const visitStatusLabel = (code?: string | null) => dictLabel(dicts, DICT_VISIT_STATUS, code === 'IN_CONSULT' ? 'IN_PROGRESS' : code)
  const statusOptions =
    !form.visit_status || visitStatusOptions.some((it) => it.code === form.visit_status)
      ? visitStatusOptions
      : [{ code: form.visit_status, label: visitStatusLabel(form.visit_status) }, ...visitStatusOptions]

  const setField = (key: keyof FormState, value: any) => setForm((f) => ({ ...f, [key]: value }))

  const onNew = () => {
    setCurrentId(null)
    setHasPrescription(false)
    setPatientLabel('')
    setPreviousLabel('')
    setForm(emptyForm())
    toast('已切换到新增挂号')
  }

  const fillFromDetail = (v: Visit) => {
    setCurrentId(v.id)
    setForm({
      visit_no: v.visit_no || '',
      patient_id: v.patient_id ?? '',
      visit_type: v.visit_type || '',
      previous_visit_id: v.previous_visit_id ?? '',
      register_time: toLocalInput(v.register_time),
      dept_code: v.dept_code || '',
      doctor_id: v.doctor_id || '',
      visit_status: v.visit_status || 'REGISTERED',
      remark: v.remark || '',
    })
    setPatientLabel(`${v.patient_no || ''} ${v.patient_name || ''}`.trim())
    setPreviousLabel(v.previous_visit_id ? `就诊 #${v.previous_visit_id}` : '')
    setHasPrescription((v.prescriptions || []).length > 0)
  }

  const onLoad = async (id: number) => {
    if (!id) return
    try {
      fillFromDetail(await visitApi.get(id))
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  const validate = (): string | null => {
    if (form.patient_id === '') return '患者不能为空'
    // M1 v1.5：主诉不在挂号环节（MU frmVisitRegister 无该元素），由接诊开单屏录入并必填
    if (!form.visit_type) return '就诊类型不能为空'
    if (form.visit_type === 'FOLLOW_UP' && form.previous_visit_id === '') return '复诊必须选择上次就诊'
    if (!form.register_time) return '挂号时间不能为空'
    if (!form.dept_code) return '科室不能为空'
    if (!form.doctor_id.trim()) return '接诊医师不能为空'
    return null
  }

  const onSave = async () => {
    if (currentId) {
      toast('当前已载入既有就诊（仅供撤销就诊使用）；如需新挂号请先点击「清空」', 'error')
      return
    }
    const err = validate()
    if (err) {
      toast(err, 'error')
      return
    }
    const payload: VisitPayload = {
      patient_id: Number(form.patient_id),
      visit_type: form.visit_type,
      previous_visit_id: form.previous_visit_id === '' ? null : Number(form.previous_visit_id),
      register_time: fromLocalInput(form.register_time),
      dept_code: form.dept_code,
      doctor_id: form.doctor_id.trim(),
      remark: form.remark || null,
      // M1 v1.5：主诉不由挂号环节录入（MU frmVisitRegister 无该元素），由接诊开单屏 txaChiefComplaint 录入并必填
    }
    setSaving(true)
    try {
      const saved = await visitApi.create(payload)
      toast('挂号成功')
      fillFromDetail(saved)
      loadVisits()
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const openCancel = () => {
    if (!currentId) {
      toast('请先载入需要撤销的就诊记录', 'error')
      return
    }
    if (!CANCELLABLE_STATUS.includes(form.visit_status)) {
      toast('仅「已挂号 / 接诊中」的就诊可撤销', 'error')
      return
    }
    if (hasPrescription) {
      toast('该就诊已存在处方，不可撤销', 'error')
      return
    }
    setCancelReason('')
    setCancelOpen(true)
  }

  const onCancelVisit = async () => {
    if (!currentId) return
    if (!cancelReason.trim()) {
      toast('撤销原因不能为空', 'error')
      return
    }
    try {
      const saved = await visitApi.cancel(currentId, cancelReason.trim())
      toast('已撤销就诊')
      setCancelOpen(false)
      fillFromDetail(saved)
      loadVisits()
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  return (
    <div>
      {/* 入口列表：载入既有就诊（MU 表单本身无列表元素，此栏仅用于载入后执行撤销就诊） */}
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">载入就诊</label>
            <div className="field-control">
              <select value={currentId ?? ''} onChange={(e) => onLoad(Number(e.target.value))}>
                <option value="">请选择已有就诊记录…</option>
                {visits.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.visit_no} {v.patient_name || ''} · {visitStatusLabel(v.visit_status)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {currentId && (
            <span className="text-secondary">
              当前就诊号：<strong style={{ color: '#2266e3' }}>{form.visit_no}</strong> · 状态：
              {visitStatusLabel(form.visit_status)}
            </span>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>门诊挂号</h3>
          <span className="text-secondary">就诊号由系统生成；复诊须选择上次就诊</span>
        </div>
        <div className="form-grid-2">
          <div className="form-item">
            <label className="field-label required">就诊号</label>
            <div className="field-control">
              <input id="txtVisitNo" value={form.visit_no} disabled placeholder="保存后由系统生成" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">患者</label>
            <PopupSelect
              elementId="pslPatient"
              title="选择患者（仅「在用」档案）"
              display={patientLabel}
              placeholder="点击「…」选择患者"
              loader={(kw) =>
                patientApi
                  .list({ page: 1, size: 50, patient_name: kw || undefined, patient_status: 'ACTIVE' })
                  .then((res) =>
                    (res.list || []).map((p) => ({
                      value: p.id,
                      label: `${p.patient_no} ${p.patient_name}`,
                      sub: p.phone,
                    })),
                  )
              }
              onSelect={(opt) => {
                setField('patient_id', opt.value)
                setPatientLabel(opt.label)
                setPreviousLabel('')
                setField('previous_visit_id', '')
              }}
            />
          </div>

          <div className="form-item">
            <label className="field-label required">就诊类型</label>
            <div className="field-control">
              <select id="cboVisitType" value={form.visit_type} onChange={(e) => setField('visit_type', e.target.value)}>
                <option value="">请选择</option>
                {visitTypeOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">上次就诊</label>
            <PopupSelect
              elementId="pslPreviousVisit"
              title="选择上次就诊（复诊必填）"
              display={previousLabel}
              placeholder="复诊时点击「…」选择"
              loader={(kw) =>
                visitApi.options({ patient_id: form.patient_id === '' ? undefined : Number(form.patient_id), keyword: kw || undefined }).then(
                  (list) =>
                    (list || []).map((o) => ({
                      value: o.id,
                      label: `${o.visit_no}`,
                      sub: `挂号时间 ${o.register_time || '—'} · 医师 ${o.doctor_id} · ${visitStatusLabel(o.visit_status)}`,
                    })),
                )
              }
              onSelect={(opt) => {
                setField('previous_visit_id', opt.value)
                setPreviousLabel(opt.label)
              }}
            />
          </div>

          <div className="form-item">
            <label className="field-label required">挂号时间</label>
            <div className="field-control">
              <input
                id="dtpRegisterTime"
                type="datetime-local"
                value={form.register_time}
                onChange={(e) => setField('register_time', e.target.value)}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">科室</label>
            <div className="field-control">
              <select id="cboDeptCode" value={form.dept_code} onChange={(e) => setField('dept_code', e.target.value)}>
                <option value="">请选择</option>
                {deptOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">接诊医师</label>
            <div className="field-control">
              <input
                id="txtDoctorId"
                value={form.doctor_id}
                onChange={(e) => setField('doctor_id', e.target.value)}
                placeholder="医师工号 / 姓名"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">就诊状态</label>
            <div className="field-control">
              <select id="cboVisitStatus" value={form.visit_status} disabled>
                {statusOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item span-2">
            <label className="field-label">备注</label>
            <div className="field-control">
              <textarea id="txaRemark" rows={2} value={form.remark} onChange={(e) => setField('remark', e.target.value)} />
            </div>
          </div>
        </div>

        <div className="toolbar-right">
          {canRegister && (
            <button id="btnSave" className="btn btn-primary" onClick={onSave} disabled={saving}>
              <Save size={14} /> {saving ? '保存中…' : '保存'}
            </button>
          )}
          {canCancel && (
            <button id="btnCancelVisit" className="btn btn-danger" onClick={openCancel}>
              <XCircle size={14} /> 撤销就诊
            </button>
          )}
          <button id="btnClear" className="btn btn-secondary" onClick={onNew}>
            <Eraser size={14} /> 清空
          </button>
        </div>
        <div className="text-secondary mt-16">
          撤销就诊：仅就诊状态=已挂号/接诊中且该就诊无处方时可用，需填写作废原因（追加到备注）。
        </div>
        <div className="text-secondary">
          接口口径说明：主诉由接诊开单屏（UI-03）录入并必填（M1 v1.5）；挂号仅写就诊类型、挂号时间、科室与备注。
        </div>
      </div>

      <Modal
        title="撤销就诊"
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        width={520}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setCancelOpen(false)}>
              取消
            </button>
            <button className="btn btn-danger" onClick={onCancelVisit}>
              确认撤销
            </button>
          </>
        }
      >
        <div className="form-item" style={{ alignItems: 'flex-start' }}>
          <label className="field-label required">作废原因</label>
          <div className="field-control">
            <textarea
              rows={3}
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              placeholder="必填，将追加到就诊备注"
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}

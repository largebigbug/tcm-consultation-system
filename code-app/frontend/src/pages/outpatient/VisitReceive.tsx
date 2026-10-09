import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Save } from 'lucide-react'
import { visitApi, type Visit, type VisitReceivePayload } from '../../api/visit'
import { dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/** 批次 2 字典键（api/meta.ts 属他人文件不改动，按契约 §7.3 直接使用字典键） */
const DICT_VISIT_STATUS = 'DICT-VISIT.VISIT_STATUS'
const DICT_VISIT_DEPT = 'DICT-VISIT.DEPT'
const DICT_VISIT_TYPE = 'DICT-VISIT.VISIT_TYPE'

const pad = (n: number) => String(n).padStart(2, '0')

function nowLocal(): string {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function toLocalInput(v?: string | null): string {
  if (!v) return ''
  const s = String(v).replace(' ', 'T')
  return s.length >= 16 ? s.slice(0, 16) : s
}

function fromLocalInput(v: string): string | null {
  if (!v) return null
  const s = v.replace('T', ' ')
  return s.length === 16 ? `${s}:00` : s
}

interface FormState {
  visit_no: string
  patient_name: string
  register_time: string
  receive_time: string
  doctor_id: string
  dept_code: string
  vital_signs: string
  chief_complaint: string
  present_illness: string
  past_history: string
  remark: string
}

const emptyForm = (): FormState => ({
  visit_no: '',
  patient_name: '',
  register_time: '',
  receive_time: nowLocal(),
  doctor_id: '',
  dept_code: '',
  vital_signs: '',
  chief_complaint: '',
  present_illness: '',
  past_history: '',
  remark: '',
})

export default function VisitReceive() {
  const navigate = useNavigate()
  const { user, hasPerm } = useAuth()
  const canSave = hasPerm('visit:receive')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [form, setForm] = useState<FormState>(emptyForm)
  const [pending, setPending] = useState<Visit[]>([])
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [currentStatus, setCurrentStatus] = useState('')
  const [currentType, setCurrentType] = useState('')
  const [saving, setSaving] = useState(false)

  const loadPending = () => {
    visitApi
      .pending({ page: 1, size: 100 })
      .then((res) => setPending(res.list || []))
      .catch(() => setPending([]))
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
    loadPending()
  }, [])

  const deptOptions = dicts[DICT_VISIT_DEPT] || []

  /** 后端对外统一返回 IN_CONSULT（M1 字典 code 为 IN_PROGRESS），显示时做口径别名归一 */
  const visitStatusLabel = (code?: string | null) => dictLabel(dicts, DICT_VISIT_STATUS, code === 'IN_CONSULT' ? 'IN_PROGRESS' : code)

  const setField = (key: keyof FormState, value: string) => setForm((f) => ({ ...f, [key]: value }))

  const onLoad = async (id: number) => {
    if (!id) return
    try {
      const v = await visitApi.get(id)
      setCurrentId(v.id)
      setCurrentStatus(v.visit_status || '')
      setCurrentType(v.visit_type || '')
      setForm({
        visit_no: v.visit_no || '',
        patient_name: v.patient_name || '',
        register_time: toLocalInput(v.register_time),
        receive_time: toLocalInput(v.receive_time) || nowLocal(),
        doctor_id: v.doctor_id || user?.real_name || '',
        dept_code: v.dept_code || '',
        vital_signs: v.vital_signs || '',
        chief_complaint: v.chief_complaint || '',
        present_illness: v.present_illness || '',
        past_history: v.past_history || '',
        remark: v.remark || '',
      })
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  const onSave = async () => {
    if (!currentId) {
      toast('请先从待接诊列表载入就诊记录', 'error')
      return
    }
    if (!form.receive_time) {
      toast('接诊时间不能为空', 'error')
      return
    }
    if (form.register_time && form.receive_time < form.register_time) {
      toast('接诊时间不得早于挂号时间', 'error')
      return
    }
    if (!form.doctor_id.trim()) {
      toast('接诊医师不能为空', 'error')
      return
    }
    if (!form.dept_code) {
      toast('科室不能为空', 'error')
      return
    }
    if (!form.chief_complaint.trim()) {
      toast('主诉不能为空', 'error')
      return
    }
    if (form.chief_complaint.length > 200) {
      toast('主诉不得超过 200 字', 'error')
      return
    }
    const payload: VisitReceivePayload = {
      receive_time: fromLocalInput(form.receive_time),
      doctor_id: form.doctor_id.trim(),
      dept_code: form.dept_code,
      vital_signs: form.vital_signs || null,
      chief_complaint: form.chief_complaint.trim(),
      present_illness: form.present_illness || null,
      past_history: form.past_history || null,
      remark: form.remark || null,
    }
    setSaving(true)
    try {
      const saved = await visitApi.receive(currentId, payload)
      toast('接诊成功')
      setCurrentStatus(saved.visit_status || 'IN_CONSULT')
      setForm((f) => ({
        ...f,
        visit_no: saved.visit_no || f.visit_no,
        receive_time: toLocalInput(saved.receive_time) || f.receive_time,
        doctor_id: saved.doctor_id || f.doctor_id,
      }))
      loadPending()
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      {/* 入口列表：待接诊列表（visit_status=REGISTERED） */}
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">待接诊患者</label>
            <div className="field-control">
              <select value={currentId ?? ''} onChange={(e) => onLoad(Number(e.target.value))}>
                <option value="">请选择待接诊就诊记录…</option>
                {pending.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.visit_no} {v.patient_name || ''} · 挂号 {v.register_time || '—'}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {currentId && (
            <span className="text-secondary">
              就诊状态：{visitStatusLabel(currentStatus)} · 就诊类型：
              {dictLabel(dicts, DICT_VISIT_TYPE, currentType)}
            </span>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>接诊开单</h3>
          <span className="text-secondary">仅「已挂号」就诊可接诊，接诊后状态置「接诊中」</span>
        </div>
        <div className="form-grid-2">
          <div className="form-item">
            <label className="field-label required">就诊号</label>
            <div className="field-control">
              <input id="txtVisitNo" value={form.visit_no} disabled placeholder="载入就诊后回显" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">患者</label>
            <div className="field-control">
              <input id="lblPatientInfo" value={form.patient_name} disabled placeholder="载入就诊后回显" />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">挂号时间</label>
            <div className="field-control">
              <input id="dtpRegisterTime" type="datetime-local" value={form.register_time} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">接诊时间</label>
            <div className="field-control">
              <input
                id="dtpReceiveTime"
                type="datetime-local"
                value={form.receive_time}
                onChange={(e) => setField('receive_time', e.target.value)}
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">接诊医师</label>
            <div className="field-control">
              <input id="txtDoctorId" value={form.doctor_id} onChange={(e) => setField('doctor_id', e.target.value)} />
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

          <div className="form-item span-2">
            <label className="field-label">生命体征</label>
            <div className="field-control">
              <input
                id="txtVitalSigns"
                value={form.vital_signs}
                onChange={(e) => setField('vital_signs', e.target.value)}
                placeholder="体温 / 血压 / 心率等"
              />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label required">主诉</label>
            <div className="field-control">
              <textarea
                id="txaChiefComplaint"
                rows={2}
                maxLength={200}
                value={form.chief_complaint}
                onChange={(e) => setField('chief_complaint', e.target.value)}
                placeholder="≤200 字"
              />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">现病史</label>
            <div className="field-control">
              <textarea
                id="txaPresentIllness"
                rows={2}
                value={form.present_illness}
                onChange={(e) => setField('present_illness', e.target.value)}
                placeholder="起病、演变与诊疗经过"
              />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">既往史</label>
            <div className="field-control">
              <textarea id="txaPastHistory" rows={2} value={form.past_history} onChange={(e) => setField('past_history', e.target.value)} />
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
          {canSave && (
            <button id="btnSave" className="btn btn-primary" onClick={onSave} disabled={saving}>
              <Save size={14} /> {saving ? '保存中…' : '保存'}
            </button>
          )}
          <button id="btnBack" className="btn btn-secondary" onClick={() => navigate(-1)}>
            <ArrowLeft size={14} /> 返回待诊列表
          </button>
        </div>
      </div>
    </div>
  )
}

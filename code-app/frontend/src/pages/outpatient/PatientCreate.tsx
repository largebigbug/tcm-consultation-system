import { useEffect, useMemo, useState } from 'react'
import { Power, RotateCcw, Save, UserPlus } from 'lucide-react'
import { patientApi, type Patient, type PatientPayload } from '../../api/patient'
import { DICT, dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

interface FormState {
  patient_no: string
  patient_name: string
  gender: string
  birth_date: string
  age: string
  id_type: string
  id_no: string
  phone: string
  occupation: string
  address: string
  allergy_history: string
  patient_status: string
  remark: string
}

const emptyForm = (): FormState => ({
  patient_no: '',
  patient_name: '',
  gender: '',
  birth_date: '',
  age: '',
  id_type: '',
  id_no: '',
  phone: '',
  occupation: '',
  address: '',
  allergy_history: '',
  patient_status: 'ACTIVE',
  remark: '',
})

function toForm(p: Patient): FormState {
  return {
    patient_no: p.patient_no || '',
    patient_name: p.patient_name || '',
    gender: p.gender || '',
    birth_date: p.birth_date ? String(p.birth_date).slice(0, 10) : '',
    age: p.age === null || p.age === undefined ? '' : String(p.age),
    id_type: p.id_type || '',
    id_no: p.id_no || '',
    phone: p.phone || '',
    occupation: p.occupation || '',
    address: p.address || '',
    allergy_history: p.allergy_history || '',
    patient_status: p.patient_status || 'ACTIVE',
    remark: p.remark || '',
  }
}

/** 出生日期 → 年龄（周岁） */
function calcAge(birth: string): number | null {
  if (!birth) return null
  const b = new Date(birth)
  if (Number.isNaN(b.getTime())) return null
  const now = new Date()
  let age = now.getFullYear() - b.getFullYear()
  const m = now.getMonth() - b.getMonth()
  if (m < 0 || (m === 0 && now.getDate() < b.getDate())) age -= 1
  return age < 0 ? 0 : age
}

const today = () => new Date().toISOString().slice(0, 10)

export default function PatientCreate() {
  const { hasPerm } = useAuth()
  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [form, setForm] = useState<FormState>(emptyForm)
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [patients, setPatients] = useState<Patient[]>([])
  const [saving, setSaving] = useState(false)

  const canSave = hasPerm('patient:save')
  const canChangeStatus = hasPerm('patient:change-status')

  const loadPatients = () => {
    patientApi
      .list({ page: 1, size: 100 })
      .then((res) => setPatients(res.list || []))
      .catch(() => setPatients([]))
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
    loadPatients()
  }, [])

  const genderOptions = dicts[DICT.PATIENT_GENDER] || []
  const idTypeOptions = dicts[DICT.PATIENT_ID_TYPE] || []
  const statusOptions = dicts[DICT.PATIENT_STATUS] || []

  const setField = (key: keyof FormState, value: any) => setForm((f) => ({ ...f, [key]: value }))

  const onBirthChange = (value: string) => {
    setForm((f) => {
      const next = { ...f, birth_date: value }
      // 出生日期改变时自动计算年龄（仅填空值）
      if (value && !f.age) {
        const age = calcAge(value)
        if (age !== null) next.age = String(age)
      }
      return next
    })
  }

  const onNew = () => {
    setCurrentId(null)
    setForm(emptyForm())
    toast('已切换到新增患者')
  }

  const onLoad = (id: number) => {
    if (!id) return
    patientApi
      .get(id)
      .then((p) => {
        setCurrentId(p.id)
        setForm(toForm(p))
      })
      .catch((err: any) => toast(err.message, 'error'))
  }

  const validate = (): string | null => {
    const name = form.patient_name.trim()
    if (!name) return '患者姓名不能为空'
    if (name.length < 2 || name.length > 20) return '患者姓名须为 2～20 字'
    if (!form.gender) return '性别不能为空'
    if (!form.phone.trim()) return '联系电话不能为空'
    if (form.birth_date && form.birth_date > today()) return '出生日期不得晚于今天'
    const ageText = String(form.age).trim()
    if (!form.birth_date && !ageText) return '出生日期与年龄至少填写一项'
    if (ageText) {
      const age = Number(ageText)
      if (!Number.isFinite(age) || age < 0 || age > 150) return '年龄须为 0～150 之间的整数'
    }
    if (form.address && form.address.length > 100) return '联系地址不得超过 100 字'
    if (form.remark && form.remark.length > 200) return '备注不得超过 200 字'
    return null
  }

  const onSave = async () => {
    const err = validate()
    if (err) {
      toast(err, 'error')
      return
    }
    const payload: PatientPayload = {
      patient_name: form.patient_name.trim(),
      gender: form.gender,
      birth_date: form.birth_date || null,
      age: String(form.age).trim() ? Number(form.age) : null,
      id_type: form.id_type || null,
      id_no: form.id_no.trim() || null,
      phone: form.phone.trim(),
      address: form.address || null,
      occupation: form.occupation || null,
      allergy_history: form.allergy_history || null,
      patient_status: form.patient_status || 'ACTIVE',
      remark: form.remark || null,
    }
    setSaving(true)
    try {
      const saved = currentId ? await patientApi.update(currentId, payload) : await patientApi.create(payload)
      toast('保存成功')
      setCurrentId(saved.id)
      setForm(toForm(saved))
      loadPatients()
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const statusLabel = useMemo(
    () => dictLabel(dicts, DICT.PATIENT_STATUS, form.patient_status) || '在用',
    [dicts, form.patient_status],
  )
  const isInactive = form.patient_status === 'INACTIVE'

  const onChangeStatus = async () => {
    if (!currentId) {
      toast('请先保存患者建档，再执行停用/启用', 'error')
      return
    }
    const next = isInactive ? 'ACTIVE' : 'INACTIVE'
    try {
      const saved = await patientApi.changeStatus(currentId, next)
      toast(next === 'INACTIVE' ? '已停用' : '已启用')
      setCurrentId(saved.id)
      setForm(toForm(saved))
      loadPatients()
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  return (
    <div>
      {/* 载入已有患者（患者建档为单表维护屏，此栏用于载入既有档案以执行停用/启用） */}
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">载入患者</label>
            <div className="field-control">
              <select
                value={currentId ?? ''}
                onChange={(e) => onLoad(Number(e.target.value))}
              >
                <option value="">请选择已有患者…</option>
                {patients.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.patient_no} {p.patient_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn btn-secondary" onClick={onNew}>
            <UserPlus size={14} /> 新增患者
          </button>
          {currentId && (
            <span className="text-secondary">
              当前患者编号：<strong>{form.patient_no}</strong> · 状态：{statusLabel}
            </span>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>患者建档</h3>
        </div>
        <div className="form-grid-2">
          <div className="form-item">
            <label className="field-label required">患者编号</label>
            <div className="field-control">
              <input value={form.patient_no} disabled placeholder="保存后由系统生成" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">患者状态</label>
            <div className="field-control">
              <select value={form.patient_status} disabled onChange={() => undefined}>
                {statusOptions.length === 0 && <option value={form.patient_status}>{statusLabel}</option>}
                {statusOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">患者姓名</label>
            <div className="field-control">
              <input
                value={form.patient_name}
                maxLength={20}
                onChange={(e) => setField('patient_name', e.target.value)}
                placeholder="2～20 字"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">性别</label>
            <div className="field-control">
              <select value={form.gender} onChange={(e) => setField('gender', e.target.value)}>
                <option value="">请选择</option>
                {genderOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">出生日期</label>
            <div className="field-control">
              <input type="date" value={form.birth_date} max={today()} onChange={(e) => onBirthChange(e.target.value)} />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">年龄</label>
            <div className="field-control">
              <input
                type="number"
                min={0}
                max={150}
                value={form.age}
                onChange={(e) => setField('age', e.target.value)}
                placeholder="0～150"
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">证件类型</label>
            <div className="field-control">
              <select value={form.id_type} onChange={(e) => setField('id_type', e.target.value)}>
                <option value="">请选择</option>
                {idTypeOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">证件号码</label>
            <div className="field-control">
              <input value={form.id_no} onChange={(e) => setField('id_no', e.target.value)} placeholder="身份证须 18 位" />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">联系电话</label>
            <div className="field-control">
              <input value={form.phone} onChange={(e) => setField('phone', e.target.value)} placeholder="11 位手机号或含区号固话" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">职业</label>
            <div className="field-control">
              <input value={form.occupation} onChange={(e) => setField('occupation', e.target.value)} />
            </div>
          </div>

          <div className="form-item span-2">
            <label className="field-label">联系地址</label>
            <div className="field-control">
              <textarea rows={2} maxLength={100} value={form.address} onChange={(e) => setField('address', e.target.value)} placeholder="≤100 字" />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">过敏史</label>
            <div className="field-control">
              <textarea rows={2} value={form.allergy_history} onChange={(e) => setField('allergy_history', e.target.value)} />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">备注</label>
            <div className="field-control">
              <textarea rows={2} maxLength={200} value={form.remark} onChange={(e) => setField('remark', e.target.value)} placeholder="≤200 字" />
            </div>
          </div>
        </div>

        <div className="toolbar-right">
          <button className="btn btn-secondary" onClick={onNew}>
            <RotateCcw size={14} /> 清空
          </button>
          {canSave && (
            <button className="btn btn-primary" onClick={onSave} disabled={saving}>
              <Save size={14} /> {saving ? '保存中…' : '保存'}
            </button>
          )}
          {canChangeStatus && (
            <button className="btn btn-primary" onClick={onChangeStatus} disabled={!currentId}>
              <Power size={14} /> {isInactive ? '启用患者' : '停用患者'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

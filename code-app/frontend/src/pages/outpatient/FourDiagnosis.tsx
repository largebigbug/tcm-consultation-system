import { useEffect, useState } from 'react'
import { FileText, Save } from 'lucide-react'
import { visitApi, type FourDiagnosis as FourDiagnosisModel, type Visit } from '../../api/visit'
import { dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/** 批次 2 字典键（api/meta.ts 属他人文件不改动，按契约 §7.3 直接使用字典键） */
const DICT_TONGUE_BODY = 'DICT-TCM-SIGN.TONGUE_BODY'
const DICT_TONGUE_COATING = 'DICT-TCM-SIGN.TONGUE_COATING'
const DICT_PULSE = 'DICT-TCM-SIGN.PULSE'
const DICT_VISIT_STATUS = 'DICT-VISIT.VISIT_STATUS'

/** 就诊状态机码值（兼容 M1 字典 IN_PROGRESS 与契约 IN_CONSULT 两种口径） */
const IN_CONSULT_STATUS = ['IN_CONSULT', 'IN_PROGRESS', 'RECEIVING']
const isInConsult = (status?: string | null) => IN_CONSULT_STATUS.includes(String(status || ''))

interface FormState {
  visit_no: string
  patient_name: string
  inquiry_cold_heat: string
  inquiry_sweat: string
  inquiry_head_body: string
  inquiry_diet: string
  inquiry_sleep: string
  inquiry_excretion: string
  inquiry_emotion: string
  inspection_face: string
  inspection_shape: string
  tongue_body: string
  tongue_coating: string
  auscultation_voice: string
  auscultation_smell: string
  pulse_code: string
  pulse_detail: string
  four_diagnosis_summary: string
}

const emptyForm = (): FormState => ({
  visit_no: '',
  patient_name: '',
  inquiry_cold_heat: '',
  inquiry_sweat: '',
  inquiry_head_body: '',
  inquiry_diet: '',
  inquiry_sleep: '',
  inquiry_excretion: '',
  inquiry_emotion: '',
  inspection_face: '',
  inspection_shape: '',
  tongue_body: '',
  tongue_coating: '',
  auscultation_voice: '',
  auscultation_smell: '',
  pulse_code: '',
  pulse_detail: '',
  four_diagnosis_summary: '',
})

/** 四诊摘要本地归纳（MU 中 btnSummary 未映射 M2 行为，仅界面整理为摘要文本） */
const SUMMARY_PARTS: { key: keyof FormState; label: string; dictKey?: string }[] = [
  { key: 'inquiry_cold_heat', label: '寒热' },
  { key: 'inquiry_sweat', label: '汗出' },
  { key: 'inquiry_head_body', label: '头身' },
  { key: 'inquiry_diet', label: '饮食口味' },
  { key: 'inquiry_sleep', label: '睡眠' },
  { key: 'inquiry_excretion', label: '二便' },
  { key: 'inquiry_emotion', label: '情志与妇科' },
  { key: 'inspection_face', label: '面色' },
  { key: 'inspection_shape', label: '形态' },
  { key: 'tongue_body', label: '舌质', dictKey: DICT_TONGUE_BODY },
  { key: 'tongue_coating', label: '舌苔', dictKey: DICT_TONGUE_COATING },
  { key: 'auscultation_voice', label: '声音气息' },
  { key: 'auscultation_smell', label: '气味' },
  { key: 'pulse_code', label: '脉象', dictKey: DICT_PULSE },
  { key: 'pulse_detail', label: '脉象补充' },
]

export default function FourDiagnosis() {
  const { hasPerm } = useAuth()
  const canSave = hasPerm('visit:save-four-diagnosis')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [form, setForm] = useState<FormState>(emptyForm)
  const [visits, setVisits] = useState<Visit[]>([])
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  /** 入口列表：当前接诊中的就诊（UI 无列表元素，仅作载入入口） */
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

  const tongueBodyOptions = dicts[DICT_TONGUE_BODY] || []
  const tongueCoatingOptions = dicts[DICT_TONGUE_COATING] || []
  const pulseOptions = dicts[DICT_PULSE] || []

  const setField = (key: keyof FormState, value: string) => setForm((f) => ({ ...f, [key]: value }))

  const onLoad = async (id: number) => {
    if (!id) return
    try {
      const v = await visitApi.get(id)
      setCurrentId(v.id)
      const fd = v.four_diagnosis || (v as any).fourDiagnosis || null
      setForm({
        ...emptyForm(),
        visit_no: v.visit_no || '',
        patient_name: v.patient_name || '',
        inquiry_cold_heat: fd?.inquiry_cold_heat || '',
        inquiry_sweat: fd?.inquiry_sweat || '',
        inquiry_head_body: fd?.inquiry_head_body || '',
        inquiry_diet: fd?.inquiry_diet || '',
        inquiry_sleep: fd?.inquiry_sleep || '',
        inquiry_excretion: fd?.inquiry_excretion || '',
        inquiry_emotion: fd?.inquiry_emotion || '',
        inspection_face: fd?.inspection_face || '',
        inspection_shape: fd?.inspection_shape || '',
        tongue_body: fd?.tongue_body || '',
        tongue_coating: fd?.tongue_coating || '',
        auscultation_voice: fd?.auscultation_voice || '',
        auscultation_smell: fd?.auscultation_smell || '',
        pulse_code: fd?.pulse_code || '',
        pulse_detail: fd?.pulse_detail || '',
        four_diagnosis_summary: fd?.four_diagnosis_summary || '',
      })
      // 就诊详情未带四诊时，单独取一次四诊详情
      if (!fd) {
        const detail = await visitApi.fourDiagnosis(v.id).catch(() => null)
        if (detail) {
          setForm((f) => ({
            ...f,
            inquiry_cold_heat: detail.inquiry_cold_heat || '',
            inquiry_sweat: detail.inquiry_sweat || '',
            inquiry_head_body: detail.inquiry_head_body || '',
            inquiry_diet: detail.inquiry_diet || '',
            inquiry_sleep: detail.inquiry_sleep || '',
            inquiry_excretion: detail.inquiry_excretion || '',
            inquiry_emotion: detail.inquiry_emotion || '',
            inspection_face: detail.inspection_face || '',
            inspection_shape: detail.inspection_shape || '',
            tongue_body: detail.tongue_body || '',
            tongue_coating: detail.tongue_coating || '',
            auscultation_voice: detail.auscultation_voice || '',
            auscultation_smell: detail.auscultation_smell || '',
            pulse_code: detail.pulse_code || '',
            pulse_detail: detail.pulse_detail || '',
            four_diagnosis_summary: detail.four_diagnosis_summary || '',
          }))
        }
      }
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  const onSummary = () => {
    const parts = SUMMARY_PARTS.map((p) => {
      const raw = String(form[p.key] || '').trim()
      if (!raw) return ''
      const text = p.dictKey ? dictLabel(dicts, p.dictKey, raw) : raw
      return `${p.label}：${text}`
    }).filter(Boolean)
    if (parts.length === 0) {
      toast('请先录入四诊内容，再生成摘要', 'error')
      return
    }
    setField('four_diagnosis_summary', parts.join('；'))
    toast('已按已录入四诊生成摘要，可继续编辑')
  }

  const onSave = async () => {
    if (!currentId) {
      toast('请先选择接诊中的就诊记录', 'error')
      return
    }
    if (!form.pulse_code) {
      toast('脉象不能为空', 'error')
      return
    }
    const payload: Partial<FourDiagnosisModel> = {
      inquiry_cold_heat: form.inquiry_cold_heat || null,
      inquiry_sweat: form.inquiry_sweat || null,
      inquiry_head_body: form.inquiry_head_body || null,
      inquiry_diet: form.inquiry_diet || null,
      inquiry_sleep: form.inquiry_sleep || null,
      inquiry_excretion: form.inquiry_excretion || null,
      inquiry_emotion: form.inquiry_emotion || null,
      inspection_face: form.inspection_face || null,
      inspection_shape: form.inspection_shape || null,
      tongue_body: form.tongue_body || null,
      tongue_coating: form.tongue_coating || null,
      auscultation_voice: form.auscultation_voice || null,
      auscultation_smell: form.auscultation_smell || null,
      pulse_code: form.pulse_code,
      pulse_detail: form.pulse_detail || null,
      four_diagnosis_summary: form.four_diagnosis_summary || null,
    }
    setSaving(true)
    try {
      await visitApi.saveFourDiagnosis(currentId, payload)
      toast('四诊保存成功')
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      {/* 入口列表：接诊中就诊 */}
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">接诊中就诊</label>
            <div className="field-control">
              <select value={currentId ?? ''} onChange={(e) => onLoad(Number(e.target.value))}>
                <option value="">请选择接诊中的就诊记录…</option>
                {visits.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.visit_no} {v.patient_name || ''} · {visitStatusLabel(v.visit_status)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <span className="text-secondary">仅「接诊中」的就诊可录入四诊（同就诊唯一一份，重复保存为更新）</span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>四诊录入</h3>
          <span className="text-secondary">脉象为必填项；舌质 / 舌苔 / 脉象为数据字典下拉（DICT-TCM-SIGN）</span>
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
              <input id="lblPatientName" value={form.patient_name} disabled placeholder="载入就诊后回显" />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">问诊-寒热</label>
            <div className="field-control">
              <input
                id="txtInquiryColdHeat"
                value={form.inquiry_cold_heat}
                onChange={(e) => setField('inquiry_cold_heat', e.target.value)}
                placeholder="恶寒发热、寒热往来等"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">问诊-汗出</label>
            <div className="field-control">
              <input
                id="txtInquirySweat"
                value={form.inquiry_sweat}
                onChange={(e) => setField('inquiry_sweat', e.target.value)}
                placeholder="有汗无汗、自汗盗汗"
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">问诊-头身</label>
            <div className="field-control">
              <input
                id="txtInquiryHeadBody"
                value={form.inquiry_head_body}
                onChange={(e) => setField('inquiry_head_body', e.target.value)}
                placeholder="头痛、眩晕、身重"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">问诊-饮食口味</label>
            <div className="field-control">
              <input
                id="txtInquiryDiet"
                value={form.inquiry_diet}
                onChange={(e) => setField('inquiry_diet', e.target.value)}
                placeholder="食欲、口渴、口味异常"
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">问诊-睡眠</label>
            <div className="field-control">
              <input
                id="txtInquirySleep"
                value={form.inquiry_sleep}
                onChange={(e) => setField('inquiry_sleep', e.target.value)}
                placeholder="失眠、多梦、嗜睡"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">问诊-二便</label>
            <div className="field-control">
              <input
                id="txtInquiryExcretion"
                value={form.inquiry_excretion}
                onChange={(e) => setField('inquiry_excretion', e.target.value)}
                placeholder="大便、小便情况"
              />
            </div>
          </div>

          <div className="form-item span-2">
            <label className="field-label">问诊-情志与妇科</label>
            <div className="field-control">
              <textarea
                id="txaInquiryEmotion"
                rows={2}
                value={form.inquiry_emotion}
                onChange={(e) => setField('inquiry_emotion', e.target.value)}
                placeholder="情志变化、月经带下等"
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">望诊-面色</label>
            <div className="field-control">
              <input
                id="txtInspectionFace"
                value={form.inspection_face}
                onChange={(e) => setField('inspection_face', e.target.value)}
                placeholder="面色、色泽"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">望诊-形态</label>
            <div className="field-control">
              <input
                id="txtInspectionShape"
                value={form.inspection_shape}
                onChange={(e) => setField('inspection_shape', e.target.value)}
                placeholder="形体、姿态"
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">舌质</label>
            <div className="field-control">
              <select id="cboTongueBody" value={form.tongue_body} onChange={(e) => setField('tongue_body', e.target.value)}>
                <option value="">请选择</option>
                {tongueBodyOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">舌苔</label>
            <div className="field-control">
              <select
                id="cboTongueCoating"
                value={form.tongue_coating}
                onChange={(e) => setField('tongue_coating', e.target.value)}
              >
                <option value="">请选择</option>
                {tongueCoatingOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">闻诊-声音气息</label>
            <div className="field-control">
              <input
                id="txtAuscultationVoice"
                value={form.auscultation_voice}
                onChange={(e) => setField('auscultation_voice', e.target.value)}
                placeholder="语声、气息、咳嗽"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">闻诊-气味</label>
            <div className="field-control">
              <input
                id="txtAuscultationSmell"
                value={form.auscultation_smell}
                onChange={(e) => setField('auscultation_smell', e.target.value)}
                placeholder="口气、体味"
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">脉象</label>
            <div className="field-control">
              <select id="cboPulseCode" value={form.pulse_code} onChange={(e) => setField('pulse_code', e.target.value)}>
                <option value="">请选择</option>
                {pulseOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">脉象文本补充</label>
            <div className="field-control">
              <input
                id="txtPulseDetail"
                value={form.pulse_detail}
                onChange={(e) => setField('pulse_detail', e.target.value)}
                placeholder="左右寸关尺六部分布记录"
              />
            </div>
          </div>

          <div className="form-item span-2">
            <label className="field-label">四诊摘要</label>
            <div className="field-control">
              <textarea
                id="txaFourDiagnosisSummary"
                rows={3}
                value={form.four_diagnosis_summary}
                onChange={(e) => setField('four_diagnosis_summary', e.target.value)}
                placeholder="可点击「四诊摘要」按已录入内容自动归纳"
              />
            </div>
          </div>
        </div>

        <div className="toolbar-right">
          {canSave && (
            <button id="btnSave" className="btn btn-primary" onClick={onSave} disabled={saving}>
              <Save size={14} /> {saving ? '保存中…' : '保存'}
            </button>
          )}
          <button id="btnSummary" className="btn btn-secondary" onClick={onSummary}>
            <FileText size={14} /> 四诊摘要
          </button>
        </div>
      </div>
    </div>
  )
}

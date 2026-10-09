import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Check, X } from 'lucide-react'
import {
  prescriptionApi,
  type DoseCheckRow,
  type Prescription as PrescriptionModel,
  type PrescriptionItem,
  type PrescriptionListRow,
} from '../../api/prescription'
import { dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/** 批次 2 字典键（api/meta.ts 属他人文件不改动，按契约 §7.3 直接使用字典键） */
const DICT_USAGE_METHOD = 'DICT-PRESCRIPTION.USAGE_METHOD'
const DICT_PRESCRIPTION_STATUS = 'DICT-PRESCRIPTION.PRESCRIPTION_STATUS'
const DICT_DECOCTION_METHOD = 'DICT-PRESCRIPTION.DECOCTION_METHOD'
const DICT_TOXICITY_LEVEL = 'DICT-HERB.TOXICITY_LEVEL'

const num = (v: any): number | null => {
  if (v === null || v === undefined || String(v).trim() === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function toLocalInput(v?: string | null): string {
  if (!v) return ''
  const s = String(v).replace(' ', 'T')
  return s.length >= 16 ? s.slice(0, 16) : s
}

export default function PrescriptionReview() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { hasPerm } = useAuth()
  const canReview = hasPerm('prescription:review')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [pending, setPending] = useState<PrescriptionListRow[]>([])
  const [detail, setDetail] = useState<PrescriptionModel | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [busy, setBusy] = useState(false)

  const loadPending = () => {
    prescriptionApi
      .pendingReview({ page: 1, size: 100 })
      .then((res) => setPending(res.list || []))
      .catch(() => setPending([]))
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
    loadPending()
  }, [])

  const onLoad = async (id: number) => {
    if (!id) return
    try {
      const p = await prescriptionApi.get(id)
      setDetail(p)
      setRejectReason(p.reject_reason || '')
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  // 批次 6：按 URL 参数定位单据（工作台业务单跳转 ?prescriptionId=<id>）
  useEffect(() => {
    const id = Number(searchParams.get('prescriptionId'))
    if (Number.isFinite(id) && id > 0) onLoad(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const doseCheckMap = useMemo(() => {
    const map: Record<number, DoseCheckRow> = {}
    const rows: DoseCheckRow[] = detail?.dose_check || detail?.doseCheck || []
    rows.forEach((r) => {
      if (r.herb_id !== undefined && r.herb_id !== null) map[Number(r.herb_id)] = r
    })
    return map
  }, [detail])

  const verdictOf = (item: PrescriptionItem): string => {
    const hit = doseCheckMap[Number(item.herb_id)]
    const raw = String(hit?.verdict || hit?.result || hit?.level || '').toUpperCase()
    if (raw.includes('BLOCK')) return 'BLOCK'
    if (raw.includes('NEED') || raw.includes('REASON') || raw.includes('OVER')) return 'NEED_REASON'
    if (raw.includes('PASS') || raw.includes('NORMAL') || raw.includes('OK')) return 'PASS'
    const max = num(item.max_common_dose)
    const dose = num(item.single_dose)
    if (dose !== null && max !== null && dose > max) return dose > max * 2 ? 'BLOCK' : 'NEED_REASON'
    return item.over_dose_reason ? 'NEED_REASON' : 'PASS'
  }

  const statusText = dictLabel(dicts, DICT_PRESCRIPTION_STATUS, detail?.prescription_status)

  const onApprove = async () => {
    if (!detail) {
      toast('请先载入待审核处方', 'error')
      return
    }
    setBusy(true)
    try {
      const saved = await prescriptionApi.review(detail.id, 'APPROVE')
      toast('审核通过，已生成待调剂记录')
      setDetail({ ...detail, ...saved })
      loadPending()
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const onReject = async () => {
    if (!detail) {
      toast('请先载入待审核处方', 'error')
      return
    }
    if (!rejectReason.trim()) {
      toast('驳回时驳回原因不能为空', 'error')
      return
    }
    setBusy(true)
    try {
      const saved = await prescriptionApi.review(detail.id, 'REJECT', rejectReason.trim())
      toast('已驳回该处方')
      setDetail({ ...detail, ...saved })
      loadPending()
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const items = detail?.items || []
  const diagnosisSummary = detail ? detail.diagnosis_summary || detail.diagnosisText || '' : ''

  return (
    <div>
      {/* 入口列表：待审核队列（SUBMITTED） */}
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">待审核处方</label>
            <div className="field-control">
              <select value={detail?.id ?? ''} onChange={(e) => onLoad(Number(e.target.value))}>
                <option value="">请选择待审核处方…</option>
                {pending.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.prescription_no} {p.patient_name || ''} · 医师 {p.doctor_id} · 剂数 {p.doses} · 提交 {p.submit_time || '—'}
                    {p.has_over_dose || p.over_dose_flag || p.overDoseFlag ? ` · 超量标记(${p.over_dose_item_count ?? '?'}味)` : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {detail && (
            <span className="text-secondary">
              处方状态：{statusText}
              {(detail.dispense_record || (detail as any).dispense_record_id) ? ' · 已生成调剂发药记录' : ''}
            </span>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>处方审核</h3>
          <span className="text-secondary">药师审核通过后自动生成待调剂记录；驳回须填写驳回原因</span>
        </div>
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">处方号</label>
            <div className="field-control">
              <input id="txtPrescriptionNo" value={detail?.prescription_no || ''} disabled placeholder="载入处方后回显" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">患者</label>
            <div className="field-control">
              <input id="lblPatientName" value={detail?.patient_name || ''} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">开方医师</label>
            <div className="field-control">
              <input id="txtDoctorId" value={detail?.doctor_id || ''} disabled />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">剂数</label>
            <div className="field-control">
              <input id="numDoses" type="number" value={detail?.doses ?? ''} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">用法</label>
            <div className="field-control">
              <select id="cboUsageMethod" value={detail?.usage_method || ''} disabled>
                <option value="">—</option>
                {(dicts[DICT_USAGE_METHOD] || []).map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">提交时间</label>
            <div className="field-control">
              <input id="dtpSubmitTime" type="datetime-local" value={toLocalInput(detail?.submit_time)} disabled />
            </div>
          </div>

          <div className="form-item span-3">
            <label className="field-label">辨证结论</label>
            <div className="field-control">
              <textarea id="txaDiagnosisSummary" rows={2} value={diagnosisSummary} disabled placeholder="引用已确认辨证结论" />
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>处方明细（只读）</h3>
          <span className="text-secondary">超量 / 毒性标记来自后端 R-01、R-03 判定结果</span>
        </div>
        <div className="table-container" id="grdPrescriptionItems">
          <table>
            <thead>
              <tr>
                <th style={{ width: 60 }}>序号</th>
                <th style={{ width: 200 }}>饮片</th>
                <th style={{ width: 110 }}>单剂剂量</th>
                <th style={{ width: 150 }}>常用量区间</th>
                <th style={{ width: 130 }}>特殊煎法</th>
                <th>超量 / 毒性标记</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, idx) => {
                const verdict = verdictOf(it)
                const max = num(it.max_common_dose)
                const min = num(it.min_common_dose)
                const toxic = String(it.toxicity_level || 'NONE') !== 'NONE'
                const checkMsg = String(doseCheckMap[Number(it.herb_id)]?.message || '')
                return (
                  <tr key={idx}>
                    <td>{it.seq_no || idx + 1}</td>
                    <td>{it.herb_name ? `${it.herb_code || ''} ${it.herb_name}`.trim() : `饮片 #${it.herb_id}`}</td>
                    <td>
                      {it.single_dose} g
                      {verdict === 'BLOCK' && <span className="badge badge-danger" style={{ marginLeft: 6 }}>超 2 倍</span>}
                    </td>
                    <td className="text-secondary">{min === null && max === null ? '—' : `${min ?? '—'} ～ ${max ?? '—'} g`}</td>
                    <td>{it.decoction_method ? dictLabel(dicts, DICT_DECOCTION_METHOD, it.decoction_method) : '—'}</td>
                    <td>
                      {verdict === 'NEED_REASON' && (
                        <span className="badge badge-warning" style={{ marginRight: 6 }}>
                          超量{it.over_dose_reason ? '（已填理由）' : '（缺理由）'}
                        </span>
                      )}
                      {verdict === 'BLOCK' && (
                        <span className="badge badge-danger" style={{ marginRight: 6 }}>
                          超量阻断
                        </span>
                      )}
                      {toxic && (
                        <span className="badge badge-danger" style={{ marginRight: 6 }}>
                          毒性：{dictLabel(dicts, DICT_TOXICITY_LEVEL, it.toxicity_level)}
                        </span>
                      )}
                      {verdict === 'PASS' && !toxic && <span className="text-secondary">正常</span>}
                      {checkMsg && (verdict !== 'PASS' || toxic) && (
                        <div className="text-secondary" style={{ fontSize: '9pt', marginTop: 4 }}>
                          {checkMsg}
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无处方明细
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>审核意见</h3>
        </div>
        <div className="form-item">
          <label className="field-label">驳回原因</label>
          <div className="field-control">
            <textarea
              id="txaRejectReason"
              rows={3}
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="驳回时必填；通过时留空"
            />
          </div>
        </div>
        <div className="toolbar-right">
          {canReview && (
            <button id="btnApprove" className="btn btn-primary" onClick={onApprove} disabled={busy || !detail}>
              <Check size={14} /> 通过
            </button>
          )}
          {canReview && (
            <button id="btnReject" className="btn btn-danger" onClick={onReject} disabled={busy || !detail}>
              <X size={14} /> 驳回
            </button>
          )}
          <button id="btnBack" className="btn btn-secondary" onClick={() => navigate(-1)}>
            <ArrowLeft size={14} /> 返回待审队列
          </button>
        </div>
      </div>
    </div>
  )
}

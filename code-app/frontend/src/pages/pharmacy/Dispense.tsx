import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, Send } from 'lucide-react'
import { dispenseApi, type DispenseRecord, type StockCheckRow } from '../../api/dispense'
import { prescriptionApi, type PrescriptionListRow } from '../../api/prescription'
import { dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/** 批次 2 字典键（api/meta.ts 属他人文件不改动，按契约 §7.3 直接使用字典键） */
const DICT_DISPENSE_STATUS = 'DICT-DISPENSE.DISPENSE_STATUS'

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

const toNum = (v: any): number => {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

/** 待调剂列表行 → 调剂发药记录 id（后端返回键名兼容多种写法） */
function resolveDispenseId(row: PrescriptionListRow): number | null {
  const candidates = [
    row.dispense_id,
    row.dispense_record_id,
    row.dispense_record?.id,
    (row as any).dispenseId,
    (row as any).dispenseRecordId,
  ]
  for (const c of candidates) {
    if (c !== undefined && c !== null && String(c) !== '') return Number(c)
  }
  // 兜底：列表行 id 即为调剂记录 id（后端若返回处方 id，取详情时会由后端报错提示）
  return row.id ? Number(row.id) : null
}

export default function Dispense() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { hasPerm } = useAuth()
  const canConfirm = hasPerm('dispense:confirm')
  const canIssue = hasPerm('dispense:issue')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [pending, setPending] = useState<PrescriptionListRow[]>([])
  const [record, setRecord] = useState<DispenseRecord | null>(null)
  const [stockRows, setStockRows] = useState<StockCheckRow[]>([])
  const [checks, setChecks] = useState<Record<string, boolean>>({})
  const [dispenserId, setDispenserId] = useState('')
  const [checkerId, setCheckerId] = useState('')
  const [dispenseTime, setDispenseTime] = useState('')
  const [issueTime, setIssueTime] = useState('')
  const [remark, setRemark] = useState('')
  const [busy, setBusy] = useState(false)

  const loadPending = () => {
    prescriptionApi
      .pendingDispense({ page: 1, size: 100 })
      .then((res) => setPending(res.list || []))
      .catch(() => setPending([]))
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
    loadPending()
  }, [])

  /** 处方明细备注（grdStockCheck 备注列来自处方明细） */
  const remarkMap = useMemo(() => {
    const map: Record<string, string> = {}
    const items = (record?.items || (record as any)?.prescription?.items || []) as any[]
    items.forEach((it) => {
      if (it?.herb_id !== undefined && it?.herb_id !== null && it.remark) map[String(it.herb_id)] = String(it.remark)
    })
    return map
  }, [record])

  const onLoad = async (id: number) => {
    if (!id) return
    setBusy(true)
    try {
      const rec = await dispenseApi.get(id)
      setRecord(rec)
      setDispenserId(rec.dispenser_id || '')
      setCheckerId(rec.checker_id || '')
      setRemark(rec.remark || '')
      const status = String(rec.record_status || '')
      setDispenseTime(toLocalInput(rec.dispense_time) || (status === 'PENDING' || !status ? nowLocal() : ''))
      setIssueTime(toLocalInput(rec.issue_time) || (status === 'DISPENSED' ? nowLocal() : ''))
      setChecks({})
      try {
        const rows = await dispenseApi.stockCheck(id)
        setStockRows(rows || [])
      } catch (e: any) {
        setStockRows([])
        toast(e.message, 'error')
      }
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  // 批次 6：按 URL 参数定位单据（?recordId=<调剂记录 id> 或 ?prescriptionId=<处方 id>）
  const paramHandled = useRef(false)
  useEffect(() => {
    if (paramHandled.current) return
    const recId = Number(searchParams.get('recordId'))
    if (Number.isFinite(recId) && recId > 0) {
      paramHandled.current = true
      onLoad(recId)
      return
    }
    const rxId = Number(searchParams.get('prescriptionId'))
    if (Number.isFinite(rxId) && rxId > 0 && pending.length > 0) {
      const hit = pending.find((p) => Number(p.id) === rxId || Number((p as any).prescription_id) === rxId)
      const did = hit ? resolveDispenseId(hit) : null
      if (did) {
        paramHandled.current = true
        onLoad(did)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, pending])

  const rows = stockRows
  const enoughOf = (row: StockCheckRow): boolean => {
    const v: any = row.enough
    if (v === true || v === 1) return true
    if (v === false || v === 0) return false
    if (typeof v === 'string') {
      const s = v.trim().toUpperCase()
      if (['TRUE', '1', 'Y', 'YES', 'ENOUGH', '充足'].includes(s)) return true
      if (['FALSE', '0', 'N', 'NO', '不足'].includes(s)) return false
    }
    return toNum(row.required_quantity) <= toNum(row.stock_quantity)
  }

  const shortRows = rows.filter((r) => !enoughOf(r))
  /** R-02 中文提示：优先用后端返回的 message，缺失时本地同口径拼接 */
  const shortMsg = (row: StockCheckRow) =>
    String(row.message || `${row.herb_name || row.herb_id} 需求 ${row.required_quantity}g 超过库存 ${row.stock_quantity}g，无法调剂`)
  const status = String(record?.record_status || '')
  const canConfirmNow = !!record && status === 'PENDING'
  const canIssueNow = !!record && status === 'DISPENSED'
  const allChecked = rows.length > 0 && rows.every((r) => checks[String(r.herb_id)])

  const onConfirmDispense = async () => {
    if (!record) {
      toast('请先载入待调剂记录', 'error')
      return
    }
    if (shortRows.length > 0) {
      toast(shortRows.map(shortMsg).join('；'), 'error')
      return
    }
    if (!dispenserId.trim()) {
      toast('调剂人不能为空', 'error')
      return
    }
    setBusy(true)
    try {
      const saved = await dispenseApi.confirm(record.id, {
        dispenser_id: dispenserId.trim(),
        checker_id: checkerId.trim() || null,
        dispense_time: fromLocalInput(dispenseTime) || null,
        remark: remark || null,
      })
      toast('已确认调剂，库存已扣减')
      setRecord(saved)
      setStockRows([])
      loadPending()
      await onLoad(saved.id)
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const onIssue = async () => {
    if (!record) {
      toast('请先载入待调剂记录', 'error')
      return
    }
    if (!canIssueNow) {
      toast('仅「已调剂」的记录可发药确认', 'error')
      return
    }
    setBusy(true)
    try {
      const saved = await dispenseApi.issue(record.id, {
        checker_id: checkerId.trim() || null,
        issue_time: fromLocalInput(issueTime) || null,
        remark: remark || null,
      })
      toast('已发药，处方状态置「已发药」')
      setRecord(saved)
      loadPending()
      await onLoad(saved.id)
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const prescriptionNo = record?.prescription_no || (record as any)?.prescription?.prescription_no || ''
  const patientName = record?.patient_name || (record as any)?.prescription?.patient_name || ''

  return (
    <div>
      {/* 入口列表：待调剂队列（APPROVED 且无记录或记录 PENDING） */}
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">待调剂处方</label>
            <div className="field-control">
              <select value={record?.id ?? ''} onChange={(e) => onLoad(Number(e.target.value))}>
                <option value="">请选择待调剂处方…</option>
                {pending.map((p) => {
                  const did = resolveDispenseId(p)
                  return (
                    <option key={`${p.id}-${did ?? 'x'}`} value={did ?? ''} disabled={did === null}>
                      {p.prescription_no} {p.patient_name || ''} · 剂数 {p.doses} · 发药单号 {did ?? '未生成'}
                    </option>
                  )
                })}
              </select>
            </div>
          </div>
          {record && (
            <span className="text-secondary">
              记录状态：{dictLabel(dicts, DICT_DISPENSE_STATUS, status)}
              {shortRows.length > 0 ? ` · 库存不足 ${shortRows.length} 味` : ' · 库存校验通过'}
            </span>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>主表：调剂发药记录（AGG-DISPENSE-001）</h3>
          <span className="text-secondary">R-02 库存不足阻断调剂，不允许先调剂后补库</span>
        </div>
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">发药单号</label>
            <div className="field-control">
              <input id="txtDispenseNo" value={record?.dispense_no || ''} disabled placeholder="载入记录后回显" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">处方号</label>
            <div className="field-control">
              <input id="txtPrescriptionNo" value={prescriptionNo} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">患者</label>
            <div className="field-control">
              <input id="lblPatientName" value={patientName} disabled />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">调剂人</label>
            <div className="field-control">
              <input id="txtDispenserId" value={dispenserId} onChange={(e) => setDispenserId(e.target.value)} />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">复核人</label>
            <div className="field-control">
              <input id="txtCheckerId" value={checkerId} onChange={(e) => setCheckerId(e.target.value)} />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">记录状态</label>
            <div className="field-control">
              <select id="cboRecordStatus" value={status} disabled>
                {((dicts[DICT_DISPENSE_STATUS] || []).length === 0) && <option value={status}>{status}</option>}
                {(dicts[DICT_DISPENSE_STATUS] || []).map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">调剂时间</label>
            <div className="field-control">
              <input
                id="dtpDispenseTime"
                type="datetime-local"
                value={dispenseTime}
                onChange={(e) => setDispenseTime(e.target.value)}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">发药时间</label>
            <div className="field-control">
              <input id="dtpIssueTime" type="datetime-local" value={issueTime} onChange={(e) => setIssueTime(e.target.value)} />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">备注</label>
            <div className="field-control">
              <input id="txaRemark" value={remark} onChange={(e) => setRemark(e.target.value)} />
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>从表：处方明细核对（实时库存）</h3>
          <span className="text-secondary">逐味比对「需求用量（= 单剂剂量 × 剂数）」与当前库存，不足的行标红并阻断调剂</span>
        </div>
        <div className="table-container" id="grdStockCheck">
          <table>
            <thead>
              <tr>
                <th style={{ width: 60 }}>序号</th>
                <th style={{ width: 200 }}>饮片</th>
                <th style={{ width: 120 }}>需求用量（g）</th>
                <th style={{ width: 130 }}>当前库存（g）</th>
                <th style={{ width: 210 }}>是否充足</th>
                <th style={{ width: 70 }}>核对</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => {
                const enough = enoughOf(row)
                const key = String(row.herb_id)
                return (
                  <tr key={`${key}-${idx}`} style={enough ? undefined : { background: '#fef2f2' }}>
                    <td>{idx + 1}</td>
                    <td>{row.herb_name || `饮片 #${row.herb_id}`}</td>
                    <td>{row.required_quantity} g</td>
                    <td>{row.stock_quantity} g</td>
                    <td>
                      {enough ? (
                        <span className="badge badge-success">充足</span>
                      ) : (
                        <span className="badge badge-danger">不足：{shortMsg(row)}</span>
                      )}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <input
                        type="checkbox"
                        checked={!!checks[key]}
                        onChange={(e) => setChecks((c) => ({ ...c, [key]: e.target.checked }))}
                      />
                    </td>
                    <td className="text-secondary">{remarkMap[key] || '—'}</td>
                  </tr>
                )
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    {record ? '暂无库存校验结果（载入记录后自动校验）' : '请先载入待调剂记录'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {shortRows.length > 0 && (
          <div className="mt-16" style={{ color: '#991b1b' }}>
            <strong>R-02 阻断：</strong>
            {shortRows.map(shortMsg).join('；')}
          </div>
        )}
        <div className="toolbar-right">
          {canConfirm && (
            <button
              id="btnConfirmDispense"
              className="btn btn-primary"
              onClick={onConfirmDispense}
              disabled={busy || !record || !canConfirmNow || shortRows.length > 0}
            >
              <CheckCircle2 size={14} /> 确认调剂
            </button>
          )}
          {canIssue && (
            <button id="btnIssue" className="btn btn-primary" onClick={onIssue} disabled={busy || !record || !canIssueNow}>
              <Send size={14} /> 发药确认
            </button>
          )}
          <button id="btnBack" className="btn btn-secondary" onClick={() => navigate(-1)}>
            <ArrowLeft size={14} /> 返回队列
          </button>
        </div>
        {rows.length > 0 && !allChecked && (
          <div className="text-secondary mt-16">
            提示：请逐味完成「核对」勾选后再确认调剂（{rows.filter((r) => checks[String(r.herb_id)]).length}/{rows.length} 已核对）。
          </div>
        )}
      </div>
    </div>
  )
}

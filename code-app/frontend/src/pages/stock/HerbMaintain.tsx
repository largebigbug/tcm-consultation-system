import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, CheckSquare, Plus, Power, Save } from 'lucide-react'
import { herbApi, type Herb, type HerbPayload, type HerbStockFlow } from '../../api/herb'
import { DICT, dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

interface FormState {
  herb_code: string
  herb_name: string
  alias_name: string
  herb_category: string
  nature_meridian: string
  efficacy: string
  min_common_dose: string
  max_common_dose: string
  toxicity_level: string
  special_managed: boolean
  stock_quantity: string
  low_stock_threshold: string
  toxic_dose_limit: string
  origin: string
  spec: string
  herb_status: string
}

interface InboundDraft {
  quantity: string
  biz_date: string
  inbound_no: string
  remark: string
}

const today = () => new Date().toISOString().slice(0, 10)

const emptyForm = (): FormState => ({
  herb_code: '',
  herb_name: '',
  alias_name: '',
  herb_category: '',
  nature_meridian: '',
  efficacy: '',
  min_common_dose: '',
  max_common_dose: '',
  toxicity_level: 'NONE',
  special_managed: false,
  stock_quantity: '0',
  low_stock_threshold: '',
  toxic_dose_limit: '',
  origin: '',
  spec: '',
  herb_status: 'ENABLED',
})

const numOrNull = (v: string) => (String(v).trim() ? Number(v) : null)

function toForm(h: Herb): FormState {
  return {
    herb_code: h.herb_code || '',
    herb_name: h.herb_name || '',
    alias_name: h.alias_name || '',
    herb_category: h.herb_category || '',
    nature_meridian: h.nature_meridian || '',
    efficacy: h.efficacy || '',
    min_common_dose: h.min_common_dose === null || h.min_common_dose === undefined ? '' : String(h.min_common_dose),
    max_common_dose: h.max_common_dose === null || h.max_common_dose === undefined ? '' : String(h.max_common_dose),
    toxicity_level: h.toxicity_level || 'NONE',
    special_managed: !!h.special_managed,
    stock_quantity: h.stock_quantity === null || h.stock_quantity === undefined ? '0' : String(h.stock_quantity),
    low_stock_threshold:
      h.low_stock_threshold === null || h.low_stock_threshold === undefined ? '' : String(h.low_stock_threshold),
    toxic_dose_limit:
      h.toxic_dose_limit === null || h.toxic_dose_limit === undefined ? '' : String(h.toxic_dose_limit),
    origin: h.origin || '',
    spec: h.spec || '',
    herb_status: h.herb_status || 'ENABLED',
  }
}

export default function HerbMaintain() {
  const navigate = useNavigate()
  const { hasPerm } = useAuth()
  const canSave = hasPerm('herb:save')
  const canInbound = hasPerm('herb:inbound')
  const canChangeStatus = hasPerm('herb:change-status')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [form, setForm] = useState<FormState>(emptyForm)
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [flows, setFlows] = useState<HerbStockFlow[]>([])
  const [herbs, setHerbs] = useState<Herb[]>([])
  const [draft, setDraft] = useState<InboundDraft | null>(null)
  const [saving, setSaving] = useState(false)

  const loadHerbs = () => {
    herbApi
      .list({ page: 1, size: 100 })
      .then((res) => setHerbs(res.list || []))
      .catch(() => setHerbs([]))
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
    loadHerbs()
  }, [])

  const categoryOptions = dicts[DICT.HERB_HERB_CATEGORY] || []
  const toxicityOptions = dicts[DICT.HERB_TOXICITY_LEVEL] || []
  const statusOptions = dicts[DICT.COMMON_USE_STATUS] || []
  const bizTypeOptions = dicts[DICT.STOCK_FLOW_FLOW_BIZ_TYPE] || []

  const setField = (key: keyof FormState, value: any) => setForm((f) => ({ ...f, [key]: value }))

  const loadDetail = async (id: number) => {
    const detail = await herbApi.get(id)
    setCurrentId(detail.id)
    setForm(toForm(detail))
    setFlows(detail.stock_flows || [])
  }

  const onNew = () => {
    setCurrentId(null)
    setForm(emptyForm())
    setFlows([])
    setDraft(null)
    toast('已切换到新增饮片')
  }

  const onLoad = async (id: number) => {
    if (!id) return
    try {
      await loadDetail(id)
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  const validate = (): string | null => {
    if (!form.herb_name.trim()) return '饮片名称不能为空'
    const min = Number(form.min_common_dose)
    const max = Number(form.max_common_dose)
    if (!String(form.min_common_dose).trim() || !Number.isFinite(min) || min <= 0) return '常用最小量须大于 0'
    if (!String(form.max_common_dose).trim() || !Number.isFinite(max)) return '常用最大量不能为空'
    if (max < min) return '常用最大量不得小于常用最小量'
    if (!form.toxicity_level) return '毒性分级不能为空'
    const threshold = String(form.low_stock_threshold).trim() ? Number(form.low_stock_threshold) : null
    if (threshold !== null && (!Number.isFinite(threshold) || threshold < 0)) return '低库存预警值不得小于 0'
    const toxicLimit = String(form.toxic_dose_limit).trim() ? Number(form.toxic_dose_limit) : null
    if (toxicLimit !== null && (!Number.isFinite(toxicLimit) || toxicLimit <= 0)) return '毒性单张处方总量上限须大于 0'
    if (form.toxicity_level === 'NONE' && toxicLimit !== null) return '毒性分级为「无毒」时无需填写毒性总量上限'
    return null
  }

  const onSave = async () => {
    const err = validate()
    if (err) {
      toast(err, 'error')
      return
    }
    const payload: HerbPayload = {
      herb_name: form.herb_name.trim(),
      alias_name: form.alias_name || null,
      herb_category: form.herb_category || null,
      nature_meridian: form.nature_meridian || null,
      efficacy: form.efficacy || null,
      min_common_dose: Number(form.min_common_dose),
      max_common_dose: Number(form.max_common_dose),
      toxicity_level: form.toxicity_level,
      special_managed: form.special_managed ? 1 : 0,
      low_stock_threshold: numOrNull(form.low_stock_threshold),
      toxic_dose_limit: numOrNull(form.toxic_dose_limit),
      origin: form.origin || null,
      spec: form.spec || null,
      herb_status: form.herb_status || 'ENABLED',
    }
    setSaving(true)
    try {
      const saved = currentId ? await herbApi.update(currentId, payload) : await herbApi.create(payload)
      toast('保存成功')
      loadHerbs()
      await loadDetail(saved.id)
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const onChangeStatus = async () => {
    if (!currentId) {
      toast('请先保存饮片建档，再执行停用/启用', 'error')
      return
    }
    const next = form.herb_status === 'ENABLED' ? 'DISABLED' : 'ENABLED'
    try {
      const saved = await herbApi.changeStatus(currentId, next)
      toast(next === 'ENABLED' ? '已启用' : '已停用')
      setForm((f) => ({ ...f, herb_status: saved.herb_status || next }))
      loadHerbs()
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  /** actAddFlow → Herb_Inbound：在从表新增一行入库，提交时写入流水并同步库存 */
  const onAddFlowRow = () => {
    if (!currentId) {
      toast('请先保存饮片建档，再登记入库', 'error')
      return
    }
    setDraft({ quantity: '', biz_date: today(), inbound_no: '', remark: '' })
  }

  const submitInbound = async () => {
    if (!currentId || !draft) return
    const qty = Number(draft.quantity)
    if (!String(draft.quantity).trim() || !Number.isFinite(qty) || qty <= 0) {
      toast('入库数量须大于 0', 'error')
      return
    }
    if (!draft.biz_date) {
      toast('业务日期不能为空', 'error')
      return
    }
    try {
      await herbApi.inbound(currentId, {
        quantity: qty,
        biz_date: draft.biz_date,
        inbound_no: draft.inbound_no || null,
        remark: draft.remark || null,
      })
      toast('入库成功')
      setDraft(null)
      await loadDetail(currentId)
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  /** btnReconcile：按 RULE-HERB-STOCK-RECONCILE 的求值口径 stockQuantity - flowNetQuantity 客户端核对 */
  const onReconcile = async () => {
    if (!currentId) {
      toast('请先保存饮片建档，再执行对账检查', 'error')
      return
    }
    try {
      const detail = await herbApi.get(currentId)
      const flows = detail.stock_flows || []
      const net = flows.reduce((sum, f) => sum + Number(f.quantity || 0), 0)
      const diff = Number(detail.stock_quantity || 0) - net
      setFlows(flows)
      setForm(toForm(detail))
      if (Math.abs(diff) < 1e-9) {
        toast(`账实相符，库存 ${Number(detail.stock_quantity || 0)} g 与流水净和一致`)
      } else {
        toast(`库存与流水净和不一致，差异 ${diff} g`, 'error')
      }
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  return (
    <div>
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">载入饮片</label>
            <div className="field-control">
              <select value={currentId ?? ''} onChange={(e) => onLoad(Number(e.target.value))}>
                <option value="">请选择已有饮片…</option>
                {herbs.map((h) => (
                  <option key={h.id} value={h.id}>
                    {h.herb_code} {h.herb_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn btn-secondary" onClick={onNew}>
            <Plus size={14} /> 新增饮片
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>饮片建档（主表）</h3>
        </div>
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label required">饮片编码</label>
            <div className="field-control">
              <input value={form.herb_code} disabled placeholder="保存后由系统生成" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">饮片名称</label>
            <div className="field-control">
              <input value={form.herb_name} onChange={(e) => setField('herb_name', e.target.value)} placeholder="如「当归」" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">别名</label>
            <div className="field-control">
              <input value={form.alias_name} onChange={(e) => setField('alias_name', e.target.value)} />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">药材类别</label>
            <div className="field-control">
              <select value={form.herb_category} onChange={(e) => setField('herb_category', e.target.value)}>
                <option value="">请选择</option>
                {categoryOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">性味归经</label>
            <div className="field-control">
              <input value={form.nature_meridian} onChange={(e) => setField('nature_meridian', e.target.value)} />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">功效</label>
            <div className="field-control">
              <input value={form.efficacy} onChange={(e) => setField('efficacy', e.target.value)} />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">常用最小量(g)</label>
            <div className="field-control">
              <input
                type="number"
                min={0}
                step="0.1"
                value={form.min_common_dose}
                onChange={(e) => setField('min_common_dose', e.target.value)}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">常用最大量(g)</label>
            <div className="field-control">
              <input
                type="number"
                min={0}
                step="0.1"
                value={form.max_common_dose}
                onChange={(e) => setField('max_common_dose', e.target.value)}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">毒性分级</label>
            <div className="field-control">
              <select value={form.toxicity_level} onChange={(e) => setField('toxicity_level', e.target.value)}>
                {toxicityOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label required">是否特殊管理</label>
            <div className="field-control">
              <input
                type="checkbox"
                style={{ width: 'auto' }}
                checked={form.special_managed}
                onChange={(e) => setField('special_managed', e.target.checked)}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">库存数量(g)</label>
            <div className="field-control">
              <input value={form.stock_quantity} disabled placeholder="由入库/盘点流水驱动" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">低库存预警值(g)</label>
            <div className="field-control">
              <input
                type="number"
                min={0}
                step="0.1"
                value={form.low_stock_threshold}
                onChange={(e) => setField('low_stock_threshold', e.target.value)}
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">毒性单张处方总量上限(g)</label>
            <div className="field-control">
              <input
                type="number"
                min={0}
                step="0.1"
                placeholder="毒性分级非「无毒」时填写，供 R-03 判定"
                value={form.toxic_dose_limit}
                onChange={(e) => setField('toxic_dose_limit', e.target.value)}
              />
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">规格</label>
            <div className="field-control">
              <input value={form.spec} onChange={(e) => setField('spec', e.target.value)} />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">产地</label>
            <div className="field-control">
              <input value={form.origin} onChange={(e) => setField('origin', e.target.value)} />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">状态</label>
            <div className="field-control">
              <select value={form.herb_status} onChange={(e) => setField('herb_status', e.target.value)}>
                {statusOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>出入库流水（从表，只追加）</h3>
          <span className="text-secondary">规则提示：R-06 账实差异核对 · 调整后库存不得为负</span>
        </div>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>流水号</th>
                <th>业务类型</th>
                <th>数量（g）</th>
                <th>业务日期</th>
                <th>入库单号</th>
                <th>操作人</th>
                <th>备注</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {flows.map((f, idx) => (
                <tr key={f.id ?? f.flow_no ?? idx}>
                  <td>{f.flow_no || '-'}</td>
                  <td>{dictLabel(dicts, DICT.STOCK_FLOW_FLOW_BIZ_TYPE, f.biz_type)}</td>
                  <td>{f.quantity}</td>
                  <td>{f.biz_date ? String(f.biz_date).slice(0, 19) : '-'}</td>
                  <td>{f.inbound_no || '-'}</td>
                  <td>{f.operator_name || f.operator_id || '-'}</td>
                  <td>{f.remark || '-'}</td>
                  <td className="text-secondary">已记账</td>
                </tr>
              ))}
              {draft && (
                <tr>
                  <td className="text-secondary">（待提交）</td>
                  <td>
                    <select className="table-input" value="INBOUND" disabled>
                      <option value="INBOUND">{dictLabel(dicts, DICT.STOCK_FLOW_FLOW_BIZ_TYPE, 'INBOUND') || '入库'}</option>
                    </select>
                  </td>
                  <td>
                    <input
                      className="table-input"
                      type="number"
                      min={0}
                      step="0.1"
                      value={draft.quantity}
                      onChange={(e) => setDraft({ ...draft, quantity: e.target.value })}
                      placeholder="入库数量"
                    />
                  </td>
                  <td>
                    <input
                      className="table-input"
                      type="date"
                      value={draft.biz_date}
                      onChange={(e) => setDraft({ ...draft, biz_date: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      className="table-input"
                      value={draft.inbound_no}
                      onChange={(e) => setDraft({ ...draft, inbound_no: e.target.value })}
                      placeholder="入库单号"
                    />
                  </td>
                  <td className="text-secondary">当前用户</td>
                  <td>
                    <input
                      className="table-input"
                      value={draft.remark}
                      onChange={(e) => setDraft({ ...draft, remark: e.target.value })}
                      placeholder="备注"
                    />
                  </td>
                  <td>
                    <button className="btn btn-primary btn-sm" onClick={submitInbound}>
                      提交入库
                    </button>
                    <button
                      className="btn btn-secondary btn-sm"
                      style={{ marginLeft: 6 }}
                      onClick={() => setDraft(null)}
                    >
                      取消
                    </button>
                  </td>
                </tr>
              )}
              {flows.length === 0 && !draft && (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无出入库流水
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="toolbar-right">
          {canInbound && (
            <button className="btn btn-secondary" onClick={onAddFlowRow}>
              <Plus size={14} /> 新增流水行
            </button>
          )}
          <button className="btn btn-secondary" onClick={onReconcile}>
            <CheckSquare size={14} /> 对账检查
          </button>
          <button className="btn btn-secondary" onClick={() => navigate(-1)}>
            <ArrowLeft size={14} /> 返回
          </button>
          {canSave && (
            <button className="btn btn-primary" onClick={onSave} disabled={saving}>
              <Save size={14} /> {saving ? '保存中…' : '保存'}
            </button>
          )}
          {canChangeStatus && (
            <button className="btn btn-primary" onClick={onChangeStatus} disabled={!currentId}>
              <Power size={14} /> {form.herb_status === 'ENABLED' ? '停用品目' : '启用'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

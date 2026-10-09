import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Plus, Power, Save, Trash2 } from 'lucide-react'
import { formulaApi, type FormulaPayload, type FormulaTemplate } from '../../api/formula'
import { herbApi, type HerbOption } from '../../api/herb'
import { DICT, dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

interface ItemRow {
  seq_no: number
  herb_id: number | ''
  common_dose: string
  decoction_method: string
}

interface FormState {
  formula_code: string
  formula_name: string
  formula_type: string
  source: string
  function: string
  indication: string
  default_doses: string
  formula_status: string
}

const emptyForm = (): FormState => ({
  formula_code: '',
  formula_name: '',
  formula_type: '',
  source: '',
  function: '',
  indication: '',
  default_doses: '',
  formula_status: 'ENABLED',
})

const newItem = (seq: number): ItemRow => ({ seq_no: seq, herb_id: '', common_dose: '', decoction_method: '' })

export default function FormulaMaintain() {
  const navigate = useNavigate()
  const { hasPerm } = useAuth()
  const canSave = hasPerm('formula:save')
  const canChangeStatus = hasPerm('formula:change-status')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [form, setForm] = useState<FormState>(emptyForm)
  const [items, setItems] = useState<ItemRow[]>([])
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [herbOptions, setHerbOptions] = useState<HerbOption[]>([])
  const [formulas, setFormulas] = useState<FormulaTemplate[]>([])
  const [saving, setSaving] = useState(false)

  const loadFormulas = () => {
    formulaApi
      .list({ page: 1, size: 100 })
      .then((res) => setFormulas(res.list || []))
      .catch(() => setFormulas([]))
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
    herbApi
      .options()
      .then((list) => setHerbOptions(list || []))
      .catch(() => setHerbOptions([]))
    loadFormulas()
  }, [])

  const typeOptions = dicts[DICT.FORMULA_FORMULA_TYPE] || []
  const statusOptions = dicts[DICT.COMMON_USE_STATUS] || []
  const decoctionOptions = dicts[DICT.PRESCRIPTION_DECOCTION_METHOD] || []

  const herbLabel = (id: number | '') => {
    if (id === '') return ''
    const hit = herbOptions.find((h) => h.id === id)
    return hit ? `${hit.herb_code} ${hit.herb_name}` : String(id)
  }

  const onNew = () => {
    setCurrentId(null)
    setForm(emptyForm())
    setItems([newItem(1)])
    toast('已切换到新增方剂')
  }

  const onLoad = async (id: number) => {
    if (!id) return
    try {
      const detail = await formulaApi.get(id)
      // 明细回显可能引用未在 /herb/options 中的饮片，补齐以确保下拉可显示
      const missing = (detail.items || []).filter(
        (it) => it.herb_id !== null && it.herb_id !== undefined && !herbOptions.some((h) => h.id === it.herb_id),
      )
      if (missing.length) {
        setHerbOptions((prev) => [
          ...prev,
          ...missing.map((it) => ({
            id: Number(it.herb_id),
            herb_code: it.herb_code || String(it.herb_id),
            herb_name: it.herb_name || '（已停用药味）',
          })),
        ])
      }
      setCurrentId(detail.id)
      setForm({
        formula_code: detail.formula_code || '',
        formula_name: detail.formula_name || '',
        formula_type: detail.formula_type || '',
        source: detail.source || '',
        function: detail.function || '',
        indication: detail.indication || '',
        default_doses: detail.default_doses === null || detail.default_doses === undefined ? '' : String(detail.default_doses),
        formula_status: detail.formula_status || 'ENABLED',
      })
      setItems(
        (detail.items || []).map((it, i) => ({
          seq_no: it.seq_no || i + 1,
          herb_id: it.herb_id === null || it.herb_id === undefined ? '' : it.herb_id,
          common_dose: it.common_dose === null || it.common_dose === undefined ? '' : String(it.common_dose),
          decoction_method: it.decoction_method || '',
        })),
      )
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  const setField = (key: keyof FormState, value: string) => setForm((f) => ({ ...f, [key]: value }))

  const addItem = () => setItems((rows) => [...rows, newItem(rows.length + 1)])

  const removeItem = (idx: number) =>
    setItems((rows) => rows.filter((_, i) => i !== idx).map((r, i) => ({ ...r, seq_no: i + 1 })))

  const patchItem = (idx: number, patch: Partial<ItemRow>) =>
    setItems((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)))

  const validate = (): string | null => {
    if (!form.formula_name.trim()) return '方剂名称不能为空'
    if (!form.formula_type) return '方剂类型不能为空'
    if (items.length === 0) return '组成明细至少 1 行'
    const used = new Set<number>()
    for (let i = 0; i < items.length; i++) {
      const it = items[i]
      if (it.herb_id === '') return `第 ${i + 1} 行未选择药味`
      if (used.has(Number(it.herb_id))) return '同一方剂模板内药味不得重复'
      used.add(Number(it.herb_id))
      const dose = Number(it.common_dose)
      if (!String(it.common_dose).trim() || !Number.isFinite(dose) || dose <= 0) {
        return `第 ${i + 1} 行常用剂量须大于 0`
      }
    }
    return null
  }

  const onSave = async () => {
    const err = validate()
    if (err) {
      toast(err, 'error')
      return
    }
    const payload: FormulaPayload = {
      formula_name: form.formula_name.trim(),
      formula_type: form.formula_type,
      formula_status: form.formula_status || 'ENABLED',
      source: form.source || null,
      function: form.function || null,
      indication: form.indication || null,
      default_doses: String(form.default_doses).trim() ? Number(form.default_doses) : null,
      items: items.map((it, i) => ({
        seq_no: i + 1,
        herb_id: Number(it.herb_id),
        common_dose: Number(it.common_dose),
        decoction_method: it.decoction_method || null,
      })),
    }
    setSaving(true)
    try {
      const saved = currentId ? await formulaApi.update(currentId, payload) : await formulaApi.create(payload)
      toast('保存成功')
      setCurrentId(saved.id)
      loadFormulas()
      await onLoad(saved.id)
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const onChangeStatus = async () => {
    if (!currentId) {
      toast('请先保存方剂模板，再执行停用/启用', 'error')
      return
    }
    const next = form.formula_status === 'ENABLED' ? 'DISABLED' : 'ENABLED'
    try {
      const saved = await formulaApi.changeStatus(currentId, next)
      toast(next === 'ENABLED' ? '已启用' : '已停用')
      setForm((f) => ({ ...f, formula_status: saved.formula_status || next }))
      loadFormulas()
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  return (
    <div>
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">载入方剂</label>
            <div className="field-control">
              <select value={currentId ?? ''} onChange={(e) => onLoad(Number(e.target.value))}>
                <option value="">请选择已有方剂模板…</option>
                {formulas.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.formula_code} {f.formula_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn btn-secondary" onClick={onNew}>
            <Plus size={14} /> 新增方剂
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>方剂模板维护（主表）</h3>
        </div>
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label required">方剂编码</label>
            <div className="field-control">
              <input value={form.formula_code} disabled placeholder="保存后由系统生成" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">方剂名称</label>
            <div className="field-control">
              <input
                value={form.formula_name}
                onChange={(e) => setField('formula_name', e.target.value)}
                placeholder="如「逍遥散」"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">方剂类型</label>
            <div className="field-control">
              <select value={form.formula_type} onChange={(e) => setField('formula_type', e.target.value)}>
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
            <label className="field-label">出处</label>
            <div className="field-control">
              <input value={form.source} onChange={(e) => setField('source', e.target.value)} />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">常用剂数</label>
            <div className="field-control">
              <input
                type="number"
                min={1}
                value={form.default_doses}
                onChange={(e) => setField('default_doses', e.target.value)}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">状态</label>
            <div className="field-control">
              <select value={form.formula_status} onChange={(e) => setField('formula_status', e.target.value)}>
                {statusOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item span-3">
            <label className="field-label">功用</label>
            <div className="field-control">
              <textarea rows={2} value={form.function} onChange={(e) => setField('function', e.target.value)} />
            </div>
          </div>
          <div className="form-item span-3">
            <label className="field-label">主治</label>
            <div className="field-control">
              <textarea rows={2} value={form.indication} onChange={(e) => setField('indication', e.target.value)} />
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>组成明细（从表）</h3>
          <span className="text-secondary">规则：至少一味药味且药味不得重复</span>
        </div>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th style={{ width: 70 }}>序号</th>
                <th style={{ width: 260 }}>药味</th>
                <th style={{ width: 160 }}>常用剂量（g）</th>
                <th style={{ width: 200 }}>特殊煎法</th>
                <th style={{ width: 100 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row, idx) => (
                <tr key={idx}>
                  <td>{row.seq_no}</td>
                  <td>
                    <select
                      className="table-input"
                      value={row.herb_id}
                      onChange={(e) => patchItem(idx, { herb_id: e.target.value ? Number(e.target.value) : '' })}
                    >
                      <option value="">请选择药味</option>
                      {herbOptions.map((h) => (
                        <option key={h.id} value={h.id}>
                          {h.herb_code} {h.herb_name}
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
                      value={row.common_dose}
                      onChange={(e) => patchItem(idx, { common_dose: e.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      className="table-input"
                      value={row.decoction_method}
                      onChange={(e) => patchItem(idx, { decoction_method: e.target.value })}
                    >
                      <option value="">无特殊煎法</option>
                      {decoctionOptions.map((it) => (
                        <option key={it.code} value={it.code}>
                          {it.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button className="btn btn-secondary btn-sm" onClick={() => removeItem(idx)}>
                      <Trash2 size={14} /> 删除
                    </button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无组成明细，请点击「添加药味」
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="toolbar-right">
          {canSave && (
            <button className="btn btn-secondary" onClick={addItem}>
              <Plus size={14} /> 添加药味
            </button>
          )}
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
              <Power size={14} /> {form.formula_status === 'ENABLED' ? '停用' : '启用'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

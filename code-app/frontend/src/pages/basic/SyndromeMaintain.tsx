import { useEffect, useState } from 'react'
import { Edit2, Plus, Power, Search } from 'lucide-react'
import { syndromeApi, type SyndromePayload, type SyndromeType } from '../../api/syndrome'
import { DICT, dictLabel, metaApi, type DictionaryMap } from '../../api/meta'
import Pagination from '../../components/Pagination'
import Modal from '../../components/Modal'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

interface FormState {
  syndrome_code: string
  syndrome_name: string
  diagnosis_method: string
  syndrome_status: string
  syndrome_description: string
  common_symptoms: string
  corresponding_treatment: string
}

const emptyForm = (): FormState => ({
  syndrome_code: '',
  syndrome_name: '',
  diagnosis_method: '',
  syndrome_status: 'ENABLED',
  syndrome_description: '',
  common_symptoms: '',
  corresponding_treatment: '',
})

const emptyQuery = { syndrome_name: '', diagnosis_method: '', syndrome_status: '' }

const PAGE_SIZES = [20, 50, 100]

export default function SyndromeMaintain() {
  const { hasPerm } = useAuth()
  const canSave = hasPerm('syndrome:save')
  const canChangeStatus = hasPerm('syndrome:change-status')

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [query, setQuery] = useState({ ...emptyQuery })
  const [applied, setApplied] = useState({ ...emptyQuery })
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [data, setData] = useState<SyndromeType[]>([])
  const [total, setTotal] = useState(0)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm)

  const load = async () => {
    try {
      const res = await syndromeApi.list({ page, size, ...applied })
      setData(res.list || [])
      setTotal(res.total || 0)
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
  }, [])

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, size, applied])

  const diagOptions = dicts[DICT.SYNDROME_DIAG_METHOD] || []
  const statusOptions = dicts[DICT.COMMON_USE_STATUS] || []

  const onQuery = () => {
    setPage(1)
    setApplied({ ...query })
  }

  const onReset = () => {
    setQuery({ ...emptyQuery })
    setApplied({ ...emptyQuery })
    setPage(1)
  }

  const openAdd = () => {
    setEditingId(null)
    setForm(emptyForm())
    setModalOpen(true)
  }

  const openEdit = (row: SyndromeType) => {
    setEditingId(row.id)
    setForm({
      syndrome_code: row.syndrome_code || '',
      syndrome_name: row.syndrome_name || '',
      diagnosis_method: row.diagnosis_method || '',
      syndrome_status: row.syndrome_status || 'ENABLED',
      syndrome_description: row.syndrome_description || '',
      common_symptoms: row.common_symptoms || '',
      corresponding_treatment: row.corresponding_treatment || '',
    })
    setModalOpen(true)
  }

  const onModalSave = async () => {
    if (!form.syndrome_name.trim()) {
      toast('证型名称不能为空', 'error')
      return
    }
    if (!form.diagnosis_method) {
      toast('所属辨证体系不能为空', 'error')
      return
    }
    const payload: SyndromePayload = {
      syndrome_name: form.syndrome_name.trim(),
      diagnosis_method: form.diagnosis_method,
      syndrome_status: form.syndrome_status || 'ENABLED',
      syndrome_description: form.syndrome_description || null,
      common_symptoms: form.common_symptoms || null,
      corresponding_treatment: form.corresponding_treatment || null,
    }
    try {
      if (editingId) await syndromeApi.update(editingId, payload)
      else await syndromeApi.create(payload)
      toast('保存成功')
      setModalOpen(false)
      load()
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  const onChangeStatus = async (row: SyndromeType) => {
    const next = row.syndrome_status === 'ENABLED' ? 'DISABLED' : 'ENABLED'
    const tip = next === 'ENABLED' ? `确认启用证型「${row.syndrome_name}」？` : `确认停用证型「${row.syndrome_name}」？`
    if (!window.confirm(tip)) return
    try {
      await syndromeApi.changeStatus(row.id, next)
      toast(next === 'ENABLED' ? '已启用' : '已停用')
      load()
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  return (
    <div>
      <div className="card">
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">证型名称</label>
            <div className="field-control">
              <input
                value={query.syndrome_name}
                onChange={(e) => setQuery({ ...query, syndrome_name: e.target.value })}
                placeholder="模糊匹配"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">所属辨证体系</label>
            <div className="field-control">
              <select
                value={query.diagnosis_method}
                onChange={(e) => setQuery({ ...query, diagnosis_method: e.target.value })}
              >
                <option value="">全部</option>
                {diagOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">状态</label>
            <div className="field-control">
              <select
                value={query.syndrome_status}
                onChange={(e) => setQuery({ ...query, syndrome_status: e.target.value })}
              >
                <option value="">全部</option>
                {statusOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        <div className="toolbar-right">
          <button className="btn btn-secondary" onClick={onReset}>
            重置
          </button>
          <button className="btn btn-primary" onClick={onQuery}>
            <Search size={14} /> 查询
          </button>
          {canSave && (
            <button className="btn btn-primary" onClick={openAdd}>
              <Plus size={14} /> 新增
            </button>
          )}
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>证型编码</th>
                <th>证型名称</th>
                <th>所属辨证体系</th>
                <th>对应治法</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.id}>
                  <td>{row.syndrome_code}</td>
                  <td>{row.syndrome_name}</td>
                  <td>{dictLabel(dicts, DICT.SYNDROME_DIAG_METHOD, row.diagnosis_method)}</td>
                  <td>{row.corresponding_treatment || '-'}</td>
                  <td>
                    <span className={`badge ${row.syndrome_status === 'ENABLED' ? 'badge-success' : 'badge-neutral'}`}>
                      {dictLabel(dicts, DICT.COMMON_USE_STATUS, row.syndrome_status)}
                    </span>
                  </td>
                  <td>
                    {canSave && (
                      <button className="btn btn-secondary btn-sm" onClick={() => openEdit(row)}>
                        <Edit2 size={14} /> 编辑
                      </button>
                    )}
                    {canChangeStatus && (
                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ marginLeft: 8 }}
                        onClick={() => onChangeStatus(row)}
                      >
                        <Power size={14} /> {row.syndrome_status === 'ENABLED' ? '停用' : '启用'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无证型数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div
          style={{
            padding: '14px 20px',
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            gap: 16,
          }}
        >
          <div className="toolbar">
            <span className="text-secondary">每页</span>
            <select
              style={{ width: 90 }}
              value={size}
              onChange={(e) => {
                setSize(Number(e.target.value))
                setPage(1)
              }}
            >
              {PAGE_SIZES.map((s) => (
                <option key={s} value={s}>
                  {s} 条
                </option>
              ))}
            </select>
          </div>
          <Pagination page={page} size={size} total={total} onChange={setPage} />
        </div>
      </div>

      <Modal
        title={editingId ? '编辑证型' : '新增证型'}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        width={640}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setModalOpen(false)}>
              取消
            </button>
            <button className="btn btn-primary" onClick={onModalSave}>
              保存
            </button>
          </>
        }
      >
        <div className="form-grid-2">
          <div className="form-item">
            <label className="field-label required">证型编码</label>
            <div className="field-control">
              <input value={form.syndrome_code} disabled placeholder="保存后由系统生成" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">证型名称</label>
            <div className="field-control">
              <input
                value={form.syndrome_name}
                onChange={(e) => setForm({ ...form, syndrome_name: e.target.value })}
                placeholder="如「肝气郁结证」"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">所属辨证体系</label>
            <div className="field-control">
              <select
                value={form.diagnosis_method}
                onChange={(e) => setForm({ ...form, diagnosis_method: e.target.value })}
              >
                <option value="">请选择</option>
                {diagOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">状态</label>
            <div className="field-control">
              <select
                value={form.syndrome_status}
                onChange={(e) => setForm({ ...form, syndrome_status: e.target.value })}
              >
                {statusOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">证候描述</label>
            <div className="field-control">
              <textarea
                rows={2}
                value={form.syndrome_description}
                onChange={(e) => setForm({ ...form, syndrome_description: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">常见症状</label>
            <div className="field-control">
              <textarea
                rows={2}
                value={form.common_symptoms}
                onChange={(e) => setForm({ ...form, common_symptoms: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">对应治法</label>
            <div className="field-control">
              <input
                value={form.corresponding_treatment}
                onChange={(e) => setForm({ ...form, corresponding_treatment: e.target.value })}
              />
            </div>
          </div>
        </div>
      </Modal>
    </div>
  )
}

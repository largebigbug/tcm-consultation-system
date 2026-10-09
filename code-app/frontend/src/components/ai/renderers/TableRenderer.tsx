/**
 * `table` 渲染（批次 5 契约 §3.4）。
 *
 * 复用「全局表格 CSS」：直接复用批次 3 的公共表格组件 `components/ReportTable.tsx`
 * （其根节点 `.table-container` + 全局 `table/th/td` 样式，`index.css` §表格），
 * 不新造表格样式、不修改该组件。
 * payload = `{columns:[{name,label}], rows:[...], total, truncated}`。
 */
import ReportTable from '../../ReportTable'
import type { ReportColumn } from '../../../api/report'
import type { AiTableRenderPayload } from '../../../api/ai'

export default function TableRenderer({ payload }: { payload: AiTableRenderPayload }) {
  const columns = Array.isArray(payload?.columns) ? payload.columns : []
  const rows = Array.isArray(payload?.rows) ? payload.rows : []
  if (columns.length === 0) return <div className="ai-render-empty">暂无可展示的表格数据</div>

  return (
    <div className="ai-table-render">
      <ReportTable
        columns={columns as ReportColumn[]}
        rows={rows}
        emptyText="暂无数据"
        rowKey="id"
      />
      <div className="ai-table-meta">
        共 {typeof payload.total === 'number' ? payload.total : rows.length} 行
        {payload.truncated ? '（结果已截断，仅展示部分）' : ''}
      </div>
    </div>
  )
}

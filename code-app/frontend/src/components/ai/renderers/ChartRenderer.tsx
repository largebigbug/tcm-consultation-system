/**
 * `chart` 渲染（批次 5 契约 §3.4）：`echarts-for-react`（已装 `echarts ^5.5.1`）。
 * option 构造在 `chartOption.ts`（纯函数），本文件只做组件包装与空态。
 */
import ReactECharts from 'echarts-for-react'
import { buildChartOption, isSupportedChartType } from './chartOption'
import type { AiChartRenderPayload } from '../../../api/ai'

export default function ChartRenderer({ payload }: { payload: AiChartRenderPayload }) {
  const rows = Array.isArray(payload?.rows) ? payload.rows : []
  if (rows.length === 0) return <div className="ai-render-empty">暂无可绘制的数据</div>
  if (!isSupportedChartType(payload?.chartType)) {
    return <div className="ai-render-empty">暂不支持的图表类型：{String(payload?.chartType)}</div>
  }
  return (
    <div className="ai-chart-render">
      <ReactECharts
        option={buildChartOption(payload)}
        style={{ height: 240, width: '100%' }}
        notMerge
        lazyUpdate
      />
    </div>
  )
}

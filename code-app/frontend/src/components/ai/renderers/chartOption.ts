/**
 * `chart` 渲染的 ECharts option 构造（纯函数，便于离线自测）。
 *
 * 口径（批次 5 契约 §3.4 `chart`）：payload = `{chartType:bar|line|pie, xField, yField, rows, title?}`，
 * 前端用已装 `echarts`（^5.5.1）+ `echarts-for-react`（^3.0.2）渲染；本批只做 bar/line/pie。
 */
import type { AiChartRenderPayload, AiChartType } from '../../../api/ai'

export const CHART_TYPES: AiChartType[] = ['bar', 'line', 'pie']

/** 是否为本批支持的图形类型 */
export function isSupportedChartType(t: any): t is AiChartType {
  return CHART_TYPES.includes(t)
}

/** 取数值列（非数值统一按 0，避免 ECharts 因 undefined 画不出图） */
function num(v: any): number {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

function str(v: any): string {
  return v === null || v === undefined ? '' : String(v)
}

/** 由 render_payload.chart 构造 ECharts option（含中文坐标轴/图例配置） */
export function buildChartOption(payload: AiChartRenderPayload): Record<string, any> {
  const rows = Array.isArray(payload?.rows) ? payload.rows : []
  const chartType: AiChartType = isSupportedChartType(payload?.chartType) ? payload.chartType : 'bar'
  const xField = payload?.xField
  const yField = payload?.yField

  const option: Record<string, any> = {}
  if (payload?.title) {
    option.title = { text: payload.title, left: 'center', textStyle: { fontSize: 12, fontWeight: 600 } }
  }
  const top = payload?.title ? 34 : 12
  const common = {
    grid: { left: 6, right: 14, top, bottom: 4, containLabel: true },
    tooltip: { trigger: chartType === 'pie' ? 'item' : 'axis' },
  }

  if (chartType === 'pie') {
    return {
      ...common,
      ...option,
      legend: { bottom: 0, type: 'scroll', textStyle: { fontSize: 10 } },
      series: [
        {
          type: 'pie',
          radius: ['38%', '64%'],
          center: ['50%', '52%'],
          avoidLabelOverlap: true,
          label: { fontSize: 10, formatter: '{b}\n{d}%' },
          data: rows.map((r) => ({ name: str(r[xField]), value: num(r[yField]) })),
        },
      ],
    }
  }

  return {
    ...common,
    ...option,
    xAxis: {
      type: 'category',
      data: rows.map((r) => str(r[xField])),
      axisLabel: { fontSize: 10, interval: 0, rotate: rows.length > 8 ? 30 : 0 },
    },
    yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
    series: [
      {
        type: chartType === 'line' ? 'line' : 'bar',
        data: rows.map((r) => num(r[yField])),
        smooth: chartType === 'line',
        barMaxWidth: 28,
        itemStyle: { color: '#2266e3' },
        lineStyle: { color: '#2266e3' },
      },
    ],
  }
}

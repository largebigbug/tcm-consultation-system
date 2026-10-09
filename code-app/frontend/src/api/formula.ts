import { http, type PageResult } from './request'

export interface FormulaItem {
  item_id?: string | number
  seq_no: number
  herb_id: number | null
  /** 列表/详情返回的显示名 */
  herb_name?: string | null
  herb_code?: string | null
  common_dose: number | string
  decoction_method?: string | null
}

export interface FormulaTemplate {
  id: number
  formula_code: string
  formula_name: string
  formula_type: string
  source: string | null
  function: string | null
  indication: string | null
  default_doses: number | null
  formula_status: string
  items?: FormulaItem[]
  created_at?: string
  updated_at?: string
}

/** 新增/修改入参：主表字段 + 从表 items（全量重建） */
export interface FormulaPayload {
  formula_name: string
  formula_type: string
  formula_status: string
  source?: string | null
  function?: string | null
  indication?: string | null
  default_doses?: number | null
  items: { seq_no: number; herb_id: number | null; common_dose: number | null; decoction_method?: string | null }[]
}

export interface FormulaQuery {
  page?: number
  size?: number
  formula_name?: string
  formula_type?: string
  formula_status?: string
}

export const formulaApi = {
  list(params: FormulaQuery) {
    return http.get<PageResult<FormulaTemplate>>('/formula', params)
  },
  /** 返回主表 + items[]（含 herb_name 显示名） */
  get(id: number) {
    return http.get<FormulaTemplate>(`/formula/${id}`)
  },
  create(data: FormulaPayload) {
    return http.post<FormulaTemplate>('/formula', data)
  },
  update(id: number, data: FormulaPayload) {
    return http.put<FormulaTemplate>(`/formula/${id}`, data)
  },
  /** Formula_ChangeStatus：停用 / 启用 */
  changeStatus(id: number, formula_status: string) {
    return http.post<FormulaTemplate>(`/formula/${id}/status`, { formula_status })
  },
}

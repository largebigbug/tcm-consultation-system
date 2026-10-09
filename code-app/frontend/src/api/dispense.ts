import { http } from './request'

/** R-02 逐味库存校验结果（GET /api/dispense/{id}/stock-check） */
export interface StockCheckRow {
  herb_id: number
  herb_name?: string | null
  /** 需求用量 = 单剂剂量 × 剂数 */
  required_quantity: number | string
  stock_quantity: number | string
  enough: boolean | number | string
  [key: string]: any
}

/** AGG-DISPENSE-001 调剂发药记录 */
export interface DispenseRecord {
  id: number
  dispense_no: string
  prescription_id: number
  prescription_no?: string | null
  patient_no?: string | null
  patient_name?: string | null
  dispenser_id: string
  checker_id?: string | null
  dispense_time: string | null
  issue_time?: string | null
  record_status: string
  remark?: string | null
  /** 处方明细（grdStockCheck 用） */
  items?: any[]
  stock_check?: StockCheckRow[]
  stockCheck?: StockCheckRow[]
  prescription?: any
}

export interface DispenseConfirmPayload {
  dispenser_id?: string | null
  checker_id?: string | null
  dispense_time?: string | null
  remark?: string | null
}

export interface DispenseIssuePayload {
  checker_id?: string | null
  issue_time?: string | null
  remark?: string | null
}

export const dispenseApi = {
  /** 详情 + 处方明细 + 逐味库存校验 */
  get(id: number) {
    return http.get<DispenseRecord>(`/dispense/${id}`)
  },
  /** R-02 逐味库存校验（不足的行需标红提示） */
  stockCheck(id: number) {
    return http.get<StockCheckRow[]>(`/dispense/${id}/stock-check`)
  },
  /** Dispense_Confirm（R-02 全部充足 + Herb_DeductStock） */
  confirm(id: number, data: DispenseConfirmPayload = {}) {
    return http.post<DispenseRecord>(`/dispense/${id}/confirm`, data)
  },
  /** Dispense_Issue（REF-14 发药时间不得早于调剂时间） */
  issue(id: number, data: DispenseIssuePayload = {}) {
    return http.post<DispenseRecord>(`/dispense/${id}/issue`, data)
  },
}

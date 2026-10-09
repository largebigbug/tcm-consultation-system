import { http, type PageResult } from './request'

/** 从表 Prescription.PrescriptionItem */
export interface PrescriptionItem {
  item_id?: string | number
  seq_no: number
  herb_id: number
  herb_code?: string | null
  herb_name?: string | null
  single_dose: number | string
  min_common_dose?: number | string | null
  max_common_dose?: number | string | null
  toxicity_level?: string | null
  toxic_dose_limit?: number | string | null
  decoction_method?: string | null
  remark?: string | null
  over_dose_reason?: string | null
}

/** R-01 逐味判定结果（GET /api/prescription/{id} 的 dose_check[]） */
export interface DoseCheckRow {
  herb_id?: number
  herb_name?: string | null
  single_dose?: number | string
  max_common_dose?: number | string | null
  /** PASS | NEED_REASON | BLOCK */
  verdict?: string | null
  result?: string | null
  level?: string | null
  message?: string | null
  [key: string]: any
}

/** AGG-PRESCRIPTION-001 处方 */
export interface Prescription {
  id: number
  prescription_no: string
  visit_id: number
  patient_id: number
  patient_no?: string | null
  patient_name?: string | null
  doctor_id: string
  prescription_type: string
  formula_template_id?: number | null
  formula_name?: string | null
  doses: number | string
  usage_method: string
  decoction_instruction?: string | null
  medical_advice?: string | null
  prescribe_time?: string | null
  submit_time?: string | null
  prescription_status: string
  reviewer_id?: string | null
  review_time?: string | null
  reject_reason?: string | null
  cancel_reason?: string | null
  /** 审核屏展示的辨证结论（后端可能返回 diagnosis_summary / diagnosisText） */
  diagnosis_summary?: string | null
  diagnosisText?: string | null
  items?: PrescriptionItem[]
  dose_check?: DoseCheckRow[]
  doseCheck?: DoseCheckRow[]
  dispense_record?: any
}

/** Prescription_Save 入参（主表 + items[] 全量重建） */
export interface PrescriptionPayload {
  visit_id: number
  prescription_type: string
  formula_template_id?: number | null
  doses: number
  usage_method: string
  decoction_instruction?: string | null
  medical_advice?: string | null
  items: {
    seq_no: number
    herb_id: number
    single_dose: number
    decoction_method?: string | null
    remark?: string | null
    over_dose_reason?: string | null
  }[]
}

export interface PrescriptionQuery {
  page?: number
  size?: number
  prescription_no?: string
  visit_id?: number
  patient_name?: string
  prescription_status?: string
}

/** 待审核/待调剂列表行（超量标记等附加字段） */
export interface PrescriptionListRow extends Partial<Prescription> {
  /** 后端 list_pending_review 的超量标记字段 */
  has_over_dose?: boolean | number | string | null
  over_dose_item_count?: number | null
  over_dose_flag?: boolean | number | string | null
  overDoseFlag?: boolean | number | string | null
  dispense_id?: number | null
  dispense_record_id?: number | null
  [key: string]: any
}

export const prescriptionApi = {
  list(params: PrescriptionQuery) {
    return http.get<PageResult<Prescription>>('/prescription', params as Record<string, any>)
  },
  /** UI-07 入口：待审核队列（SUBMITTED） */
  pendingReview(params: PrescriptionQuery = {}) {
    return http.get<PageResult<PrescriptionListRow>>('/prescription/pending-review', params as Record<string, any>)
  },
  /** UI-08 入口：待调剂队列（APPROVED 且无记录或记录 PENDING） */
  pendingDispense(params: PrescriptionQuery = {}) {
    return http.get<PageResult<PrescriptionListRow>>('/prescription/pending-dispense', params as Record<string, any>)
  },
  /** 详情 + items[] + dose_check[] + dispense_record */
  get(id: number) {
    return http.get<Prescription>(`/prescription/${id}`)
  },
  create(data: PrescriptionPayload) {
    return http.post<Prescription>('/prescription', data)
  },
  update(id: number, data: PrescriptionPayload) {
    return http.put<Prescription>(`/prescription/${id}`, data)
  },
  /** Prescription_Submit（触发审批流 + 就诊完成 + 随访计划） */
  submit(id: number) {
    return http.post<Prescription>(`/prescription/${id}/submit`)
  },
  /** Prescription_Review：action = APPROVE | REJECT */
  review(id: number, action: 'APPROVE' | 'REJECT', comment?: string) {
    return http.post<Prescription>(`/prescription/${id}/review`, { action, comment: comment || '' })
  },
  /** Prescription_Cancel（R-04 分派） */
  cancel(id: number, cancel_reason: string) {
    return http.post<Prescription>(`/prescription/${id}/cancel`, { cancel_reason })
  },
}

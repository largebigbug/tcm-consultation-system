import { http, type PageResult } from './request'

/** Visit.FourDiagnosis 从表（基数 ZERO_OR_ONE，每就诊至多一份） */
export interface FourDiagnosis {
  id?: number
  visit_id?: number
  four_diagnosis_id?: string | null
  inquiry_cold_heat?: string | null
  inquiry_sweat?: string | null
  inquiry_head_body?: string | null
  inquiry_diet?: string | null
  inquiry_sleep?: string | null
  inquiry_excretion?: string | null
  inquiry_emotion?: string | null
  inspection_face?: string | null
  inspection_shape?: string | null
  tongue_body?: string | null
  tongue_coating?: string | null
  auscultation_voice?: string | null
  auscultation_smell?: string | null
  /** 必填（DICT-TCM-SIGN.PULSE） */
  pulse_code: string
  pulse_detail?: string | null
  four_diagnosis_summary?: string | null
}

/** AGG-VISIT-001 就诊记录 */
export interface Visit {
  id: number
  visit_no: string
  patient_id: number
  patient_no?: string | null
  patient_name?: string | null
  gender?: string | null
  age?: number | string | null
  visit_type: string
  previous_visit_id?: number | null
  register_time: string | null
  receive_time?: string | null
  doctor_id: string
  dept_code: string
  chief_complaint?: string | null
  present_illness?: string | null
  past_history?: string | null
  vital_signs?: string | null
  visit_status: string
  remark?: string | null
  four_diagnosis?: FourDiagnosis | null
  syndrome_diagnoses?: any[]
  prescriptions?: any[]
}

export interface VisitQuery {
  page?: number
  size?: number
  visit_no?: string
  patient_name?: string
  visit_type?: string
  visit_status?: string
  dept_code?: string
  doctor_id?: string
  date_from?: string
  date_to?: string
}

/** Visit_Register 入参（visit_no / visit_status 由后端生成） */
export interface VisitPayload {
  patient_id: number
  visit_type: string
  previous_visit_id?: number | null
  register_time?: string | null
  dept_code: string
  doctor_id: string
  /** 契约 §8.6：挂号时主诉必填（UI-02 无主诉元素，以备注内容作为初值提交） */
  chief_complaint?: string | null
  remark?: string | null
}

/** Visit_Receive 入参 */
export interface VisitReceivePayload {
  receive_time?: string | null
  doctor_id?: string | null
  dept_code?: string | null
  vital_signs?: string | null
  chief_complaint?: string | null
  present_illness?: string | null
  past_history?: string | null
  remark?: string | null
}

/** 复诊选上次就诊用的选项（GET /api/visit/options） */
export interface VisitOption {
  id: number
  visit_no: string
  register_time: string | null
  doctor_id: string
  visit_status: string
}

export const visitApi = {
  list(params: VisitQuery = {}) {
    return http.get<PageResult<Visit>>('/visit', params as Record<string, any>)
  },
  /** 待接诊列表（visit_status=REGISTERED）—— UI-03 入口 */
  pending(params: VisitQuery = {}) {
    return http.get<PageResult<Visit>>('/visit/pending', params as Record<string, any>)
  },
  /** 复诊「上次就诊」跳选框数据源 */
  options(params: { patient_id?: number; keyword?: string } = {}) {
    return http.get<VisitOption[]>('/visit/options', params)
  },
  get(id: number) {
    return http.get<Visit>(`/visit/${id}`)
  },
  /** Visit_Register */
  create(data: VisitPayload) {
    return http.post<Visit>('/visit', data)
  },
  /** Visit_Receive */
  receive(id: number, data: VisitReceivePayload) {
    return http.post<Visit>(`/visit/${id}/receive`, data)
  },
  /** Visit_SaveFourDiagnosis（每就诊唯一一份，新增/更新语义） */
  saveFourDiagnosis(id: number, data: Partial<FourDiagnosis>) {
    return http.post<FourDiagnosis>(`/visit/${id}/four-diagnosis`, data)
  },
  /** 四诊详情（不存在时后端返回 null data） */
  fourDiagnosis(id: number) {
    return http.get<FourDiagnosis | null>(`/visit/${id}/four-diagnosis`)
  },
  /** Visit_Cancel（撤销原因必填，后端追加到 remark） */
  cancel(id: number, cancel_reason: string) {
    return http.post<Visit>(`/visit/${id}/cancel`, { cancel_reason })
  },
}

import { http } from './request'

/** AGG-DIAGNOSIS-001 辨证结论 */
export interface SyndromeDiagnosis {
  id: number
  diagnosis_no: string
  visit_id: number
  diagnosis_method: string
  syndrome_id: number
  syndrome_code?: string | null
  syndrome_name?: string | null
  syndrome_nature: string
  diagnosis_basis: string
  treatment_principle: string
  conclusion_status: string
}

/** Diagnosis_Save 入参 */
export interface DiagnosisPayload {
  visit_id: number
  diagnosis_method: string
  syndrome_id: number
  syndrome_nature: string
  diagnosis_basis: string
  treatment_principle: string
}

export const diagnosisApi = {
  /** 该就诊全部辨证结论（visit_id 必填） */
  list(visit_id: number) {
    return http.get<SyndromeDiagnosis[]>('/diagnosis', { visit_id })
  },
  get(id: number) {
    return http.get<SyndromeDiagnosis>(`/diagnosis/${id}`)
  },
  /** Diagnosis_Save（新增，conclusion_status=DRAFT） */
  create(data: DiagnosisPayload) {
    return http.post<SyndromeDiagnosis>('/diagnosis', data)
  },
  /** Diagnosis_Save（修改，仅 DRAFT 可改） */
  update(id: number, data: DiagnosisPayload) {
    return http.put<SyndromeDiagnosis>(`/diagnosis/${id}`, data)
  },
  /** Diagnosis_Confirm（INV-02 主证唯一、治法必填） */
  confirm(id: number) {
    return http.post<SyndromeDiagnosis>(`/diagnosis/${id}/confirm`)
  },
}

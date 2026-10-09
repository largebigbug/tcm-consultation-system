import { http, type PageResult } from './request'

/** AGG-FOLLOWUP-001 复诊随访记录（列表行） */
export interface FollowUp {
  id: number
  follow_up_no?: string | null
  patient_id: number
  patient_no?: string | null
  patient_name?: string | null
  source_visit_id?: number | null
  visit_no?: string | null
  planned_follow_up_date?: string | null
  actual_visit_id?: number | null
  actual_follow_up_date?: string | null
  record_status: string
  efficacy_level?: string | null
  symptom_change?: string | null
  continue_medication?: number | boolean | null
  remark?: string | null
  [key: string]: any
}

export interface FollowUpQuery {
  page?: number
  size?: number
  patient_name?: string
  patient_no?: string
  record_status?: string
  planned_from?: string
  planned_to?: string
  scheduled_from?: string
  scheduled_to?: string
  actual_from?: string
  actual_to?: string
}

export const followupApi = {
  /** 待随访/随访记录列表（Q-07 数据源；权限 follow_up:complete 或 follow_up:query-completion） */
  list(params?: FollowUpQuery) {
    return http.get<PageResult<FollowUp>>('/followup', params)
  },
  get(id: number | string) {
    return http.get<FollowUp>(`/followup/${id}`)
  },
  /** 复诊随访登记（FUNC-13）：实际随访日期 + 本次就诊 + 疗效评价 */
  complete(id: number | string, data: {
    actual_visit_id: number | string
    actual_follow_up_date: string
    efficacy_level?: string
    symptom_change?: string
    continue_medication?: number | boolean
    remark?: string
  }) {
    return http.post<FollowUp>(`/followup/${id}/complete`, data)
  },
  /** 标记失访（前置：计划随访日期已超期） */
  markLost(id: number | string, reason: string) {
    return http.post<FollowUp>(`/followup/${id}/mark-lost`, { remark: reason })
  },
}

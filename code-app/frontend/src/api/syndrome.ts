import { http, type PageResult } from './request'

export interface SyndromeType {
  id: number
  syndrome_code: string
  syndrome_name: string
  diagnosis_method: string
  syndrome_description: string | null
  common_symptoms: string | null
  corresponding_treatment: string | null
  syndrome_status: string
  created_at?: string
  updated_at?: string
}

/** 新增/修改入参：`syndrome_code` 由后端生成，免填 */
export interface SyndromePayload {
  syndrome_name: string
  diagnosis_method: string
  syndrome_status: string
  syndrome_description?: string | null
  common_symptoms?: string | null
  corresponding_treatment?: string | null
}

export interface SyndromeQuery {
  page?: number
  size?: number
  syndrome_name?: string
  diagnosis_method?: string
  syndrome_status?: string
}

export const syndromeApi = {
  list(params: SyndromeQuery) {
    return http.get<PageResult<SyndromeType>>('/syndrome', params)
  },
  get(id: number) {
    return http.get<SyndromeType>(`/syndrome/${id}`)
  },
  create(data: SyndromePayload) {
    return http.post<SyndromeType>('/syndrome', data)
  },
  update(id: number, data: SyndromePayload) {
    return http.put<SyndromeType>(`/syndrome/${id}`, data)
  },
  /** Syndrome_ChangeStatus：停用 / 启用 */
  changeStatus(id: number, syndrome_status: string) {
    return http.post<SyndromeType>(`/syndrome/${id}/status`, { syndrome_status })
  },
}

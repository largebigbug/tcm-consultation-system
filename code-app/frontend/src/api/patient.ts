import { http, type PageResult } from './request'

export interface Patient {
  id: number
  patient_no: string
  patient_name: string
  gender: string
  birth_date: string | null
  age: number | null
  id_type: string | null
  id_no: string | null
  phone: string
  address: string | null
  occupation: string | null
  allergy_history: string | null
  patient_status: string
  remark: string | null
  created_at?: string
  updated_at?: string
}

/** 新增/修改入参：`patient_no` 由后端生成，免填 */
export interface PatientPayload {
  patient_name: string
  gender: string
  birth_date?: string | null
  age?: number | null
  id_type?: string | null
  id_no?: string | null
  phone: string
  address?: string | null
  occupation?: string | null
  allergy_history?: string | null
  patient_status?: string
  remark?: string | null
}

export interface PatientQuery {
  page?: number
  size?: number
  patient_no?: string
  patient_name?: string
  phone?: string
  patient_status?: string
}

export const patientApi = {
  list(params: PatientQuery) {
    return http.get<PageResult<Patient>>('/patient', params)
  },
  get(id: number) {
    return http.get<Patient>(`/patient/${id}`)
  },
  create(data: PatientPayload) {
    return http.post<Patient>('/patient', data)
  },
  update(id: number, data: PatientPayload) {
    return http.put<Patient>(`/patient/${id}`, data)
  },
  /** Patient_ChangeStatus：停用 / 启用 */
  changeStatus(id: number, patient_status: string) {
    return http.post<Patient>(`/patient/${id}/status`, { patient_status })
  },
}

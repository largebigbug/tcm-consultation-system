import { http } from './request'

export interface DictItem {
  code: string
  label: string
}

/** 键形如 `DICT-PATIENT.GENDER`（字典 id + 类型码） */
export type DictionaryMap = Record<string, DictItem[]>

export interface Rule {
  id: string
  name: string
  description: string | null
  expression: string
  rule_type: string
  input_params: { name: string; type: string; sourceField?: string }[]
}

/** 批次 1 用到的字典键（以 models/m1-object-model.yaml 的 data_dictionaries 为准） */
export const DICT = {
  PATIENT_GENDER: 'DICT-PATIENT.GENDER',
  PATIENT_ID_TYPE: 'DICT-PATIENT.ID_TYPE',
  PATIENT_STATUS: 'DICT-PATIENT.PATIENT_STATUS',
  COMMON_USE_STATUS: 'DICT-COMMON.USE_STATUS',
  SYNDROME_DIAG_METHOD: 'DICT-SYNDROME.DIAG_METHOD',
  FORMULA_FORMULA_TYPE: 'DICT-FORMULA.FORMULA_TYPE',
  HERB_HERB_CATEGORY: 'DICT-HERB.HERB_CATEGORY',
  HERB_TOXICITY_LEVEL: 'DICT-HERB.TOXICITY_LEVEL',
  PRESCRIPTION_DECOCTION_METHOD: 'DICT-PRESCRIPTION.DECOCTION_METHOD',
  STOCK_FLOW_FLOW_BIZ_TYPE: 'DICT-STOCK-FLOW.FLOW_BIZ_TYPE',
  // 批次 3（随访管理 + 统计报表）用到的字典键
  VISIT_TYPE: 'DICT-VISIT.VISIT_TYPE',
  VISIT_STATUS: 'DICT-VISIT.VISIT_STATUS',
  VISIT_DEPT: 'DICT-VISIT.DEPT',
  SYNDROME_NATURE: 'DICT-SYNDROME.SYNDROME_NATURE',
  PRESCRIPTION_STATUS: 'DICT-PRESCRIPTION.PRESCRIPTION_STATUS',
  PRESCRIPTION_TYPE: 'DICT-PRESCRIPTION.PRESCRIPTION_TYPE',
  DISPENSE_STATUS: 'DICT-DISPENSE.DISPENSE_STATUS',
  FOLLOWUP_STATUS: 'DICT-FOLLOWUP.FOLLOWUP_STATUS',
  EFFICACY_LEVEL: 'DICT-FOLLOWUP.EFFICACY_LEVEL',
} as const

let dictCache: DictionaryMap | null = null
let dictPending: Promise<DictionaryMap> | null = null

export const metaApi = {
  /** 全部业务字典（内存缓存；force=true 强制刷新） */
  dictionaries(force = false): Promise<DictionaryMap> {
    if (!force && dictCache) return Promise.resolve(dictCache)
    if (!force && dictPending) return dictPending
    dictPending = http
      .get<DictionaryMap>('/meta/dictionaries')
      .then((data) => {
        dictCache = data || {}
        return dictCache
      })
      .finally(() => {
        dictPending = null
      })
    return dictPending
  },
  /** 取单个字典项列表，key 形如 `DICT-PATIENT.GENDER` */
  dict(key: string): Promise<DictItem[]> {
    return metaApi.dictionaries().then((all) => all[key] || [])
  },
  /** 同步取缓存中的字典项（未加载时返回空数组，供渲染期取 label 用） */
  dictSync(key: string): DictItem[] {
    return (dictCache && dictCache[key]) || []
  },
  /** 取字典标签；查不到时回落到原 code */
  label(key: string, code?: string | null): string {
    if (!code) return ''
    const hit = metaApi.dictSync(key).find((it) => it.code === code)
    return hit ? hit.label : code
  },
  rules() {
    return http.get<Rule[]>('/meta/rules')
  },
}

/** 从已加载的字典表里取标签，供组件用 useMemo 后的同步渲染 */
export function dictLabel(dicts: DictionaryMap, key: string, code?: string | null): string {
  if (!code) return ''
  const hit = (dicts[key] || []).find((it) => it.code === code)
  return hit ? hit.label : code
}

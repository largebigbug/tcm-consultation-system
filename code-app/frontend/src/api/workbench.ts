import { http, type PageResult } from './request'
import type { FlowInstance, FlowTask } from './flow'

/** 工作台三页共用筛选（契约 §6）：筛选必须在后端 SQL 生效，前端不做过滤 */
export interface WorkbenchFilter {
  flowName?: string
  activityName?: string
  dateFrom?: string
  dateTo?: string
  /** 待办/已办：任务处理结果（已办页按 action）；我的申请：实例状态 */
  status?: string
  page?: number
  size?: number
}

export interface WorkbenchQuery {
  page: number
  size: number
  flowName?: string
  activityName?: string
  dateFrom?: string
  dateTo?: string
  status?: string
}

/**
 * 组装请求参数：空值不下发（与 request.ts 的 http.get 过滤口径一致），
 * 保证「筛选项与 total 自洽」——筛选真正走 SQL，不做前端过滤。
 */
export function buildWorkbenchQuery(filter: WorkbenchFilter, page: number, size: number): WorkbenchQuery {
  const q: WorkbenchQuery = { page, size }
  const put = (k: 'flowName' | 'activityName' | 'dateFrom' | 'dateTo' | 'status', v?: string) => {
    const s = typeof v === 'string' ? v.trim() : ''
    if (s) q[k] = s
  }
  put('flowName', filter.flowName)
  put('activityName', filter.activityName)
  put('dateFrom', filter.dateFrom)
  put('dateTo', filter.dateTo)
  put('status', filter.status)
  return q
}

/** AGG-PRESCRIPTION-001 处方聚合 id（M1） */
export const AGG_PRESCRIPTION = 'AGG-PRESCRIPTION-001'
/** AGG-DISPENSE-001 调剂发药记录聚合 id（M2） */
export const AGG_DISPENSE = 'AGG-DISPENSE-001'

/** 业务单据引用（旧字段 flow_instance.business_object_refs 的元素） */
export interface BusinessRef {
  aggregateId?: string
  businessId?: number | string
  businessNo?: string
  status?: string | null
  prescriptionStatus?: string | null
  prescription_status?: string | null
  [key: string]: any
}

/**
 * 业务对象（后端工作台三页列表新下发字段 business_objects 的元素）。
 * `status` 为业务对象当前状态 code（如 PENDING_REVIEW / APPROVED / DISPENSING / ISSUED）；
 * 无关联记录时后端下发 null。
 */
export interface BusinessObject {
  aggregateId?: string
  businessId?: number | string
  businessNo?: string
  status?: string | null
  [key: string]: any
}

/** 业务对象/引用数组容错解析（JSON 串 / 数组 / 空 → 数组） */
export function parseRefArray(raw: unknown): BusinessRef[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw as BusinessRef[]
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed as BusinessRef[]
    } catch {
      /* 非 JSON 串 → 无可用引用 */
    }
  }
  return []
}

/** business_object_refs 容错解析（JSON 串 / 数组 / 空） */
export function parseBusinessRefs(raw: unknown): BusinessRef[] {
  return parseRefArray(raw)
}

function refId(r: BusinessRef): string | null {
  const v = r.businessId
  if (v === undefined || v === null || String(v) === '') return null
  return String(v)
}

/**
 * 业务单跳转（契约 §6）：
 *  优先读后端新下发字段 `business_objects`（元素自带业务对象当前状态 code），
 *  该字段为空（null/无记录）时回退旧字段 `business_object_refs`（兼容保留）。
 *  - AGG-PRESCRIPTION-001：status=PENDING_REVIEW → `/pharmacy/review?prescriptionId=<id>`；
 *    APPROVED/DISPENSING/ISSUED → `/pharmacy/dispense?prescriptionId=<id>`
 *  - AGG-DISPENSE-001：`/pharmacy/dispense?recordId=<id>`
 *  status 缺失时沿用原有回退口径（ref 内 prescriptionStatus/prescription_status + 行级 statusHint）。
 * 引用缺失时返回 null（前端不渲染跳转按钮）。
 */
export function businessLink(
  businessObjects?: unknown,
  legacyRefs?: unknown,
  statusHint?: string | null,
): string | null {
  const fresh = parseRefArray(businessObjects)
  const fromNew = fresh.length > 0
  const refs = fromNew ? fresh : parseRefArray(legacyRefs)
  const rx = refs.find((r) => String(r.aggregateId || '') === AGG_PRESCRIPTION)
  if (rx) {
    const id = refId(rx)
    if (id) {
      const st = String(
        fromNew
          ? rx.status || statusHint || ''
          : rx.prescriptionStatus || rx.prescription_status || rx.status || statusHint || '',
      )
        .trim()
        .toUpperCase()
      if (['APPROVED', 'DISPENSING', 'DISPENSED', 'ISSUED'].includes(st)) {
        return `/pharmacy/dispense?prescriptionId=${id}`
      }
      return `/pharmacy/review?prescriptionId=${id}`
    }
  }
  const dr = refs.find((r) => String(r.aggregateId || '') === AGG_DISPENSE)
  if (dr) {
    const id = refId(dr)
    if (id) return `/pharmacy/dispense?recordId=${id}`
  }
  return null
}

/**
 * 审批弹窗动作白名单：**只有「通过」「驳回」**。
 * M6 `Q02.approvalOutcomes = APPROVE,REJECT`；D-25「退回等同于驳回」→ 前端不提供「退回」。
 */
export const APPROVAL_ACTIONS = ['approve', 'reject'] as const
export type ApprovalAction = (typeof APPROVAL_ACTIONS)[number]

/** 当前用户是否可处理该任务（与后端 _load_task_and_check 同口径；后端仍是唯一判权方） */
export function canHandleTask(
  task: { assignee_id?: number | null; role_ref?: string | null } | null | undefined,
  user: { id?: number; roles?: string[] } | null | undefined,
  isAdmin = false,
): boolean {
  if (!task || !user) return false
  if (isAdmin) return true
  if (task.assignee_id !== null && task.assignee_id !== undefined && task.assignee_id === user.id) return true
  const roles = user.roles || []
  return !!task.role_ref && roles.includes(task.role_ref)
}

/**
 * 转办选人候选项（GET /api/users/enabled）：
 * 仅返回**启用用户**，`id` 即用户主键（= 转办接口 assigneeId 口径）。
 * 注意：/api/users/options 返回的是**角色**，其 id 不能当 assigneeId 用。
 */
export interface AssigneeOption {
  id: number
  username: string
  real_name?: string | null
}

/** 选人控件展示名：真实姓名优先，回落登录名 */
export function assigneeLabel(o: AssigneeOption): string {
  return String(o.real_name || o.username)
}

/** GET /api/workbench/todo → flow_task(t.*) + business_key + creator_id + started_at + flow_name */
export interface TodoItem extends FlowTask {
  business_key: string
  creator_id: number
  started_at: string
  flow_name: string | null
  created_at: string
  /** 契约 §6：业务单跳转依据（后端新下发；含业务对象当前状态 code；无记录为 null） */
  business_objects?: BusinessObject[] | string | null
  /** 旧字段（兼容回退） */
  business_object_refs?: string | BusinessRef[] | null
  prescription_status?: string | null
}

/** GET /api/workbench/done → flow_task(t.*) + business_key + flow_name */
export interface DoneItem extends FlowTask {
  business_key: string
  flow_name: string | null
  done_at: string | null
  /** 契约 §6：业务单跳转依据（后端新下发；含业务对象当前状态 code；无记录为 null） */
  business_objects?: BusinessObject[] | string | null
  /** 旧字段（兼容回退） */
  business_object_refs?: string | BusinessRef[] | null
  prescription_status?: string | null
}

/** GET /api/workbench/requested → flow_instance(i.*) + flow_name */
export interface RequestedItem extends FlowInstance {
  flow_name: string | null
  current_activity_ids: string | null
  variables: string | null
  /** 契约 §6：业务单跳转依据（后端新下发；含业务对象当前状态 code；无记录为 null） */
  business_objects?: BusinessObject[] | string | null
  /** 旧字段（兼容回退） */
  business_object_refs?: string | BusinessRef[] | null
  prescription_status?: string | null
}

export const workbenchApi = {
  todo(params: WorkbenchQuery) {
    return http.get<PageResult<TodoItem>>('/workbench/todo', params as Record<string, any>)
  },
  done(params: WorkbenchQuery) {
    return http.get<PageResult<DoneItem>>('/workbench/done', params as Record<string, any>)
  },
  requested(params: WorkbenchQuery) {
    return http.get<PageResult<RequestedItem>>('/workbench/requested', params as Record<string, any>)
  },
  approve(taskId: number, comment: string) {
    return http.post(`/workbench/todo/${taskId}/approve`, { comment })
  },
  reject(taskId: number, comment: string) {
    return http.post(`/workbench/todo/${taskId}/reject`, { comment })
  },
  /** 转办（契约 §4.2 工作台侧新接口：入参 assigneeId） */
  transfer(taskId: number, assigneeId: number) {
    return http.post(`/workbench/todo/${taskId}/transfer`, { assigneeId })
  },
  /** 催办（契约 §4.2 工作台侧新接口；仅 TODO 任务） */
  urge(taskId: number) {
    return http.post(`/workbench/todo/${taskId}/urge`)
  },
  /** 转办选人候选项（GET /api/users/enabled：仅启用用户，id = assigneeId） */
  assigneeOptions() {
    return http.get<AssigneeOption[]>('/users/enabled')
  },
}

/**
 * 屏 id（MU `screens.id`）↔ 前端路由映射。
 *
 * 口径（批次 5 契约 §3.4 `action`）：`render_payload.action.payload.screenId` 是本体注册表的屏 id，
 * 前端须跳转到该屏对应的路由；`prefill` 通过 `navigate(path, { state: { prefill } })` 传递。
 *
 * 屏 id 清单来自 `code-app/docs/批次5-工具清单（注册表抽取）.md` §1（19 屏，与 `src/router/index.tsx`
 * 已注册的 19 条业务路由一一对应）。本文件是**纯函数**（不依赖 React），便于离线自测。
 * 本文件不改动 `src/router/index.tsx`。
 */

/** screenId → 前端路由（19 条，与工具清单 §1 一一对应） */
export const SCREEN_ROUTES: Record<string, string> = {
  frmPatientCreate: '/outpatient/patient',
  frmVisitRegister: '/outpatient/register',
  frmVisitReceive: '/outpatient/receive',
  frmFourDiagnosis: '/outpatient/four-diagnosis',
  frmDiagnosisJudge: '/outpatient/diagnosis',
  frmPrescription: '/outpatient/prescription',
  frmPrescriptionReview: '/pharmacy/review',
  frmDispense: '/pharmacy/dispense',
  frmHerbMaintain: '/stock/herb',
  frmHerbStock: '/stock/alert',
  frmFollowUp: '/followup/register',
  frmSyndromeMaintain: '/basic/syndrome',
  frmFormulaMaintain: '/basic/formula',
  frmVisitStats: '/report/visit-stats',
  frmSyndromeDist: '/report/syndrome-dist',
  frmHerbUsageStats: '/report/herb-usage',
  frmVisitPrescriptionQuery: '/report/visit-prescription',
  frmOverdoseLedger: '/report/overdose-ledger',
  frmFollowUpAnalysis: '/report/followup-analysis',
}

/** 反查：路由 → screenId（用于把当前页面作为 `context.screenId` 上报） */
export function screenIdByPath(pathname: string): string | undefined {
  for (const [screenId, path] of Object.entries(SCREEN_ROUTES)) {
    if (path === pathname) return screenId
  }
  return undefined
}

/** 未识别的 screenId 返回 null（调用方给出中文提示，不跳转、不报错） */
export function screenPath(screenId?: string): string | null {
  if (!screenId) return null
  return SCREEN_ROUTES[screenId] || null
}

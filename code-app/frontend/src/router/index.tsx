import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuth } from '../stores/userStore'
import AdminLayout from '../layouts/AdminLayout'
import Login from '../pages/Login'
import PatientCreate from '../pages/outpatient/PatientCreate'
import VisitRegister from '../pages/outpatient/VisitRegister'
import VisitReceive from '../pages/outpatient/VisitReceive'
import FourDiagnosis from '../pages/outpatient/FourDiagnosis'
import DiagnosisJudge from '../pages/outpatient/DiagnosisJudge'
import Prescription from '../pages/outpatient/Prescription'
import PrescriptionReview from '../pages/pharmacy/PrescriptionReview'
import Dispense from '../pages/pharmacy/Dispense'
import SyndromeMaintain from '../pages/basic/SyndromeMaintain'
import FormulaMaintain from '../pages/basic/FormulaMaintain'
import HerbMaintain from '../pages/stock/HerbMaintain'
import HerbStock from '../pages/stock/HerbStock'
import FollowUpRegister from '../pages/followup/FollowUpRegister'
import VisitStats from '../pages/report/VisitStats'
import SyndromeDistribution from '../pages/report/SyndromeDistribution'
import HerbUsage from '../pages/report/HerbUsage'
import VisitPrescriptionQuery from '../pages/report/VisitPrescriptionQuery'
import OverdoseLedger from '../pages/report/OverdoseLedger'
import FollowUpAnalysis from '../pages/report/FollowUpAnalysis'
import Todo from '../pages/workbench/Todo'
import Done from '../pages/workbench/Done'
import Requested from '../pages/workbench/Requested'
import FlowDefinitions from '../pages/flow/FlowDefinitions'
import FlowDesigner from '../pages/flow/FlowDesigner'
import FlowInstances from '../pages/flow/FlowInstances'
import FlowTasks from '../pages/flow/FlowTasks'
import UserManage from '../pages/system/UserManage'
import RoleManage from '../pages/system/RoleManage'
import PermissionManage from '../pages/system/PermissionManage'
import ResourceManage from '../pages/system/ResourceManage'
import ChangePassword from '../pages/system/ChangePassword'
import AiConfig from '../pages/system/AiConfig'

function RequireAuth({ children }: { children: ReactNode }) {
  const { token, user, setInfo } = useAuth()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (token && !user) {
      setLoading(true)
      authApi
        .info()
        .then((p) => setInfo(p))
        .catch(() => {})
        .finally(() => setLoading(false))
    }
  }, [token, user, setInfo])

  if (!token) return <Navigate to="/login" replace />
  if (loading || !user) return <div style={{ padding: 40, color: '#5b6e8c' }}>加载中…</div>
  return <>{children}</>
}

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AdminLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/outpatient/patient" replace />} />
        <Route path="outpatient/patient" element={<PatientCreate />} />
        <Route path="outpatient/register" element={<VisitRegister />} />
        <Route path="outpatient/receive" element={<VisitReceive />} />
        <Route path="outpatient/four-diagnosis" element={<FourDiagnosis />} />
        <Route path="outpatient/diagnosis" element={<DiagnosisJudge />} />
        <Route path="outpatient/prescription" element={<Prescription />} />
        <Route path="pharmacy/review" element={<PrescriptionReview />} />
        <Route path="pharmacy/dispense" element={<Dispense />} />
        <Route path="basic/syndrome" element={<SyndromeMaintain />} />
        <Route path="basic/formula" element={<FormulaMaintain />} />
        <Route path="stock/herb" element={<HerbMaintain />} />
        <Route path="stock/alert" element={<HerbStock />} />
        {/* 批次 3：随访管理与统计报表 */}
        <Route path="followup/register" element={<FollowUpRegister />} />
        <Route path="report/visit-stats" element={<VisitStats />} />
        <Route path="report/syndrome-dist" element={<SyndromeDistribution />} />
        <Route path="report/herb-usage" element={<HerbUsage />} />
        <Route path="report/visit-prescription" element={<VisitPrescriptionQuery />} />
        <Route path="report/overdose-ledger" element={<OverdoseLedger />} />
        <Route path="report/followup-analysis" element={<FollowUpAnalysis />} />
        <Route path="workbench/todo" element={<Todo />} />
        <Route path="workbench/done" element={<Done />} />
        <Route path="workbench/requested" element={<Requested />} />
        <Route path="flow/definitions" element={<FlowDefinitions />} />
        <Route path="flow/designer/:id" element={<FlowDesigner />} />
        <Route path="flow/instances" element={<FlowInstances />} />
        <Route path="flow/tasks" element={<FlowTasks />} />
        <Route path="system/users" element={<UserManage />} />
        <Route path="system/roles" element={<RoleManage />} />
        <Route path="system/permissions" element={<PermissionManage />} />
        <Route path="system/resources" element={<ResourceManage />} />
        {/* 批次 6：用户菜单入口（不进左侧业务菜单） */}
        <Route path="system/change-password" element={<ChangePassword />} />
        <Route path="system/ai-config" element={<AiConfig />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

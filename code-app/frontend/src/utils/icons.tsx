import {
  Users, UserPlus, Search, ClipboardList, Inbox, CheckSquare, FileText,
  GitBranch, Workflow, List, ListChecks, Settings, User, Shield, Key, Menu,
  Stethoscope, Pill, Boxes, Package, AlertTriangle, ListTree, FlaskConical,
  CalendarClock, BarChart3, Database,
  PieChart, Leaf, ShieldAlert, TrendingUp,
  Circle, type LucideIcon,
} from 'lucide-react'

const iconMap: Record<string, LucideIcon> = {
  Users, UserPlus, Search, ClipboardList, Inbox, CheckSquare, FileText,
  GitBranch, Workflow, List, ListChecks, Settings, User, Shield, Key, Menu,
  // 业务菜单图标（批次 1：门诊管理 / 库存管理 / 基础数据 + 后续批次）
  Stethoscope, Pill, Boxes, Package, AlertTriangle, ListTree, FlaskConical,
  CalendarClock, BarChart3, Database,
  // 批次 3：随访管理 / 统计报表
  PieChart, Leaf, ShieldAlert, TrendingUp,
}

export function MenuIcon({ name, size = 16 }: { name: string | null; size?: number }) {
  const Comp = iconMap[name || ''] || Circle
  return <Comp size={size} />
}

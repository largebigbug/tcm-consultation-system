import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ChevronDown, ChevronRight, PanelLeftClose, PanelRightClose, Sparkles } from 'lucide-react'
import { useAuth } from '../stores/userStore'
import { MenuIcon } from '../utils/icons'
import AiChatPanel from '../components/ai/AiChatPanel'
import UserMenu from '../components/UserMenu'
import type { MenuItem } from '../api/auth'

/* ===== AI 区拖拽调宽（契约 §5）：宽度 280–720px（默认 420），localStorage 持久化，双击复位 ===== */

export const CHAT_WIDTH_KEY = 'cp_chat_width'
export const CHAT_WIDTH_MIN = 280
export const CHAT_WIDTH_MAX = 720
export const CHAT_WIDTH_DEFAULT = 420

/** 夹取到 [280, 720]；非法值回落默认 420。纯函数，便于自测。 */
export function clampChatWidth(w: number): number {
  if (!Number.isFinite(w)) return CHAT_WIDTH_DEFAULT
  return Math.min(CHAT_WIDTH_MAX, Math.max(CHAT_WIDTH_MIN, Math.round(w)))
}

/** 读取持久化宽度（缺省 420；超界/非法回落）。 */
export function readChatWidth(): number {
  try {
    const raw = localStorage.getItem(CHAT_WIDTH_KEY)
    if (raw === null) return CHAT_WIDTH_DEFAULT
    const n = Number(raw)
    return Number.isFinite(n) ? clampChatWidth(n) : CHAT_WIDTH_DEFAULT
  } catch {
    return CHAT_WIDTH_DEFAULT
  }
}

/** 持久化宽度（先夹取再写；存储不可用时静默降级为仅内存）。 */
export function persistChatWidth(w: number): void {
  try {
    localStorage.setItem(CHAT_WIDTH_KEY, String(clampChatWidth(w)))
  } catch {
    /* 隐私模式 / 存储不可用：不阻断拖拽 */
  }
}

export default function AdminLayout() {
  const { user, menus, logout, permissions } = useAuth()
  const isAdmin = permissions.includes('*')
  const navigate = useNavigate()
  const location = useLocation()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [chatCollapsed, setChatCollapsed] = useState(false)
  const [collapsedGroups, setCollapsedGroups] = useState<Set<number>>(new Set())
  const [chatWidth, setChatWidth] = useState<number>(() => readChatWidth())
  const [dragging, setDragging] = useState(false)
  const chatWidthRef = useRef(chatWidth)
  const [tabs, setTabs] = useState<{ path: string; title: string }[]>(() => {
    const t = findTabByPath(menus, location.pathname)
    if (t) return [t]
    return location.pathname === '/' ? [HOME_TAB] : []
  })

  const activePath = location.pathname

  // 刷新 / 深链进入任意路由时补一个 tab（口径与既有 findTabByPath 一致）
  useEffect(() => {
    const path = location.pathname
    setTabs((prev) => {
      if (prev.some((t) => t.path === path)) return prev
      if (path === '/') return [...prev, HOME_TAB]
      const found = findTabByPath(menus, path)
      return found ? [...prev, found] : prev
    })
  }, [location.pathname, menus])

  const applyChatWidth = (w: number) => {
    chatWidthRef.current = w
    setChatWidth(w)
  }

  const onResizeStart = (e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = chatWidthRef.current
    setDragging(true)
    // 拖拽条位于 AI 区左侧：向左拖（clientX 变小）→ AI 区变宽
    const onMove = (ev: MouseEvent) => applyChatWidth(clampChatWidth(startWidth + (startX - ev.clientX)))
    const onUp = () => {
      setDragging(false)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      persistChatWidth(chatWidthRef.current)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  const resetChatWidth = () => {
    applyChatWidth(CHAT_WIDTH_DEFAULT)
    persistChatWidth(CHAT_WIDTH_DEFAULT)
  }

  const toggleGroup = (id: number) => {
    const next = new Set(collapsedGroups)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setCollapsedGroups(next)
  }

  const openTab = (path: string, title: string) => {
    navigate(path)
    setTabs((prev) => (prev.some((t) => t.path === path) ? prev : [...prev, { path, title }]))
  }

  const closeTab = (path: string) => {
    const idx = tabs.findIndex((t) => t.path === path)
    const next = tabs.filter((t) => t.path !== path)
    setTabs(next)
    if (activePath === path) {
      const target = next[idx] || next[idx - 1]
      navigate(target ? target.path : '/')
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 顶栏 */}
      <div className="app-header">
        <div className="header-left">
          <button className="header-icon" onClick={() => setSidebarCollapsed((v) => !v)}>
            <PanelLeftClose size={18} />
          </button>
          <span className="header-title">中医问诊系统</span>
        </div>
        <div className="header-right">
          <button className="header-icon" onClick={() => setChatCollapsed((v) => !v)} title="折叠/展开 AI 区">
            <PanelRightClose size={18} />
          </button>
          <span className="divider" />
          {/* 用户菜单（契约 §5）：修改密码 / 配置大模型（仅管理员）/ 退出登录 */}
          <UserMenu name={user?.real_name || user?.username || ''} isAdmin={isAdmin} onLogout={handleLogout} />
        </div>
      </div>

      <div className="app-body">
        {/* 左侧菜单 */}
        <aside className={`app-sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
          {menus.map((group) => (
            <div className="menu-group" key={group.id}>
              <div className="menu-group-title" onClick={() => toggleGroup(group.id)}>
                <MenuIcon name={group.icon} size={18} />
                <span>{group.name}</span>
                <span className="chevron">
                  {collapsedGroups.has(group.id) ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                </span>
              </div>
              {!collapsedGroups.has(group.id) &&
                (group.children || []).map((child) => (
                  <div
                    key={child.id}
                    className={`menu-item ${activePath === child.path ? 'active' : ''}`}
                    onClick={() => child.path && openTab(child.path, child.name)}
                  >
                    <MenuIcon name={child.icon} size={16} />
                    <span>{child.name}</span>
                  </div>
                ))}
            </div>
          ))}
        </aside>

        {/* 中间工作区 */}
        <main className="app-main">
          <div className="tabs-bar">
            {tabs.map((tab) => (
              <div key={tab.path} className={`tab ${activePath === tab.path ? 'active' : ''}`}>
                <span onClick={() => navigate(tab.path)}>{tab.title}</span>
                <span className="tab-close" onClick={() => closeTab(tab.path)}>
                  ×
                </span>
              </div>
            ))}
          </div>
          <div className="app-content">
            <Outlet />
          </div>
        </main>

        {/* AI 区拖拽调宽（契约 §5）：宽度 280–720px，默认 420，双击复位 */}
        {!chatCollapsed && (
          <div
            className="chat-resizer"
            data-testid="chat-resizer"
            role="separator"
            aria-orientation="vertical"
            title="拖动调整 AI 区宽度，双击复位"
            onMouseDown={onResizeStart}
            onDoubleClick={resetChatWidth}
            style={{
              width: 6,
              flexShrink: 0,
              cursor: 'col-resize',
              background: dragging ? 'var(--primary-color)' : 'var(--divider-color)',
            }}
          />
        )}

        {/* 右侧 AI 对话（批次 5：真实对话组件，只读边界见契约 §9） */}
        <aside
          className={`app-chat ${chatCollapsed ? 'collapsed' : ''}`}
          style={{ width: chatCollapsed ? undefined : chatWidth, transition: dragging ? 'none' : undefined }}
        >
          <div className="chat-header">
            <div className="chat-logo">
              <Sparkles size={16} />
            </div>
            <span className="chat-title">AI 智能助理</span>
          </div>
          <AiChatPanel />
        </aside>
      </div>
    </div>
  )
}

/** 访问 `/` 时工作区的 tab（契约 §5「首页 tab」） */
export const HOME_TAB = { path: '/', title: '首页' }

function findTabByPath(menus: MenuItem[], path: string): { path: string; title: string } | null {
  for (const g of menus) {
    for (const c of g.children || []) {
      if (c.path === path) return { path: c.path!, title: c.name }
    }
  }
  return null
}

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, KeyRound, LogOut, Server, User } from 'lucide-react'

/**
 * 右上角用户菜单（批次 6 契约 §5）。
 *
 * - 用户名处为**下拉**：修改密码 / 配置大模型（仅 `*` 权限管理员可见）/ 退出登录；
 * - 点击外部或按 Esc 关闭；
 * - 样式沿用现有 `--token` 变量，不新增全局 CSS。
 */
export interface UserMenuProps {
  /** 展示名（real_name 优先，调用方已兜底 username） */
  name: string
  /** 是否为管理员（`*` 权限，判断口径与 useAuth().hasPerm('*') 一致） */
  isAdmin: boolean
  onLogout: () => void
}

export default function UserMenu({ name, isAdmin, onLogout }: UserMenuProps) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onDocMouseDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocMouseDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const go = (path: string) => {
    setOpen(false)
    navigate(path)
  }

  const itemStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '9px 14px',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    color: 'var(--text-primary)',
    fontSize: 'var(--font-size-base)',
  }

  return (
    <div className="user-menu" ref={boxRef} style={{ position: 'relative' }}>
      <button
        type="button"
        className="header-icon user-menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        title="用户菜单"
        onClick={() => setOpen((v) => !v)}
        style={{ display: 'flex', alignItems: 'center', gap: 6 }}
      >
        <User size={16} />
        <span className="user-name">{name}</span>
        <ChevronDown size={14} />
      </button>

      {open && (
        <div
          className="user-menu-dropdown"
          role="menu"
          style={{
            position: 'absolute',
            top: 'calc(100% + 8px)',
            right: 0,
            minWidth: 168,
            background: 'var(--card-bg)',
            border: '1px solid var(--divider-color)',
            borderRadius: 'var(--radius-sm)',
            boxShadow: 'var(--shadow-md)',
            padding: '6px 0',
            zIndex: 1200,
            color: 'var(--text-primary)',
          }}
        >
          <div className="user-menu-item" role="menuitem" style={itemStyle} onClick={() => go('/system/change-password')}>
            <KeyRound size={14} /> 修改密码
          </div>
          {/* 配置大模型：仅管理员（`*` 权限）可见 */}
          {isAdmin && (
            <div className="user-menu-item" role="menuitem" style={itemStyle} onClick={() => go('/system/ai-config')}>
              <Server size={14} /> 配置大模型
            </div>
          )}
          <div
            className="user-menu-item user-menu-item-danger"
            role="menuitem"
            style={{ ...itemStyle, color: '#dc2626', borderTop: '1px solid var(--divider-color)', marginTop: 4 }}
            onClick={() => {
              setOpen(false)
              onLogout()
            }}
          >
            <LogOut size={14} /> 退出登录
          </div>
        </div>
      )}
    </div>
  )
}

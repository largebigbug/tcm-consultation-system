import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { authApi } from '../../api/auth'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/** 新密码最小长度（契约 §5：新密码 ≥6 位且 ≠ 用户名） */
export const MIN_PASSWORD_LENGTH = 6

export interface PasswordFormErrors {
  oldPassword?: string
  newPassword?: string
  confirmPassword?: string
}

/**
 * 前端预校验（纯函数，便于自测）：
 * - 旧密码必填；
 * - 新密码 ≥6 位；
 * - 新密码不得与用户名相同；
 * - 两次输入一致。
 * 返回空对象表示通过；服务端仍是唯一裁决方。
 */
export function validatePasswordForm(
  oldPassword: string,
  newPassword: string,
  confirmPassword: string,
  username = '',
): PasswordFormErrors {
  const errs: PasswordFormErrors = {}
  if (!oldPassword) errs.oldPassword = '请输入原密码'
  if (!newPassword) errs.newPassword = '请输入新密码'
  else if (newPassword.length < MIN_PASSWORD_LENGTH) errs.newPassword = `新密码至少 ${MIN_PASSWORD_LENGTH} 位`
  else if (username && newPassword === username) errs.newPassword = '新密码不能与用户名相同'
  if (!confirmPassword) errs.confirmPassword = '请再次输入新密码'
  else if (newPassword && confirmPassword !== newPassword) errs.confirmPassword = '两次输入的新密码不一致'
  return errs
}

/** 修改密码（批次 6 契约 §5）。入口仅在右上角用户菜单；不进入左侧业务菜单。 */
export default function ChangePassword() {
  const { user } = useAuth()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<PasswordFormErrors>({})
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const errs = validatePasswordForm(oldPassword, newPassword, confirmPassword, user?.username || '')
    setErrors(errs)
    if (Object.keys(errs).length > 0) {
      toast(Object.values(errs)[0] as string, 'error')
      return
    }
    setBusy(true)
    try {
      await authApi.changePassword(oldPassword, newPassword)
      toast('密码修改成功，请使用新密码登录')
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setErrors({})
    } catch (err: any) {
      toast(err?.message || '修改密码失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const errStyle: React.CSSProperties = { color: '#dc2626', marginTop: 4, fontSize: '9pt' }

  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <div className="card-title">
        <h3>修改密码</h3>
        <span className="text-secondary">新密码至少 {MIN_PASSWORD_LENGTH} 位，且不能与用户名相同</span>
      </div>
      <form onSubmit={onSubmit} id="formChangePassword">
        <div className="form-item" style={{ marginBottom: 14 }}>
          <label className="field-label required">原密码</label>
          <div className="field-control">
            <input
              id="txtOldPassword"
              type="password"
              autoComplete="current-password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
            />
            {errors.oldPassword && <div style={errStyle}>{errors.oldPassword}</div>}
          </div>
        </div>
        <div className="form-item" style={{ marginBottom: 14 }}>
          <label className="field-label required">新密码</label>
          <div className="field-control">
            <input
              id="txtNewPassword"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            {errors.newPassword && <div style={errStyle}>{errors.newPassword}</div>}
          </div>
        </div>
        <div className="form-item" style={{ marginBottom: 14 }}>
          <label className="field-label required">确认新密码</label>
          <div className="field-control">
            <input
              id="txtConfirmPassword"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
            {errors.confirmPassword && <div style={errStyle}>{errors.confirmPassword}</div>}
          </div>
        </div>
        <div className="toolbar-right">
          <button id="btnSubmitPassword" type="submit" className="btn btn-primary" disabled={busy}>
            <KeyRound size={14} /> 确认修改
          </button>
        </div>
      </form>
    </div>
  )
}

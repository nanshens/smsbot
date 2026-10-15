import { useState } from 'react'
import { ShieldCheck, Radio, ArrowRight, KeyRound } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { post, setCsrf } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/common'

export type Session = { username: string; scope: string; csrf: string }
export function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  return <div className="grid min-h-dvh lg:grid-cols-2">
    <div className="relative hidden flex-col justify-between overflow-hidden bg-[#101a2d] p-14 text-white lg:flex"><div className="flex items-center gap-3 text-xl font-semibold"><Radio className="text-teal-300"/> SMSBot</div><div className="absolute -right-48 top-32 size-[650px] rounded-full border border-white/5 p-20"><div className="h-full rounded-full border border-white/10 p-20"><div className="h-full rounded-full border border-teal-400/20 bg-teal-400/5"/></div></div><div className="relative"><p className="mb-5 text-xs tracking-[.3em] text-teal-300">YOUR MESSAGES. CONNECTED.</p><h1 className="text-5xl leading-tight font-semibold">每条消息，<br/>都有归处。</h1><p className="mt-7 max-w-sm text-base leading-8 text-slate-400">连接电话卡与日常工作。集中查看短信，让重要的消息及时抵达。</p></div><p className="text-xs text-slate-500">自托管 · 多卡管理 · 自动转发</p></div>
    <div className="flex items-center justify-center p-7"><div className="w-full max-w-sm"><div className="mb-10 flex items-center gap-2 text-lg font-bold lg:hidden"><Radio className="text-teal-700"/>SMSBot</div><div className="mb-5 inline-flex rounded-xl border border-slate-200 bg-white p-3"><KeyRound className="text-teal-700" size={22}/></div><h2 className="text-3xl font-semibold tracking-tight text-slate-900">欢迎回来</h2><p className="mt-3 text-sm text-slate-500">登录你的短信工作台</p>
    <form className="mt-9 space-y-5" onSubmit={async e => { e.preventDefault(); setBusy(true); setError(''); const data = new FormData(e.currentTarget); try { const session = await post<Session>('/auth/login', Object.fromEntries(data)); setCsrf(session.csrf); onLogin(session) } catch (err) { setError((err as Error).message) } finally { setBusy(false) } }}>
      <Field title="用户名"><input name="username" required autoComplete="username" placeholder="输入用户名"/></Field><Field title="密码"><input name="password" type="password" required autoComplete="current-password" placeholder="输入密码"/></Field><Field title="动态验证码 / 恢复码"><input name="code" autoComplete="one-time-code" placeholder="首次登录可留空" maxLength={100}/></Field>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}<Button className="w-full" disabled={busy}>{busy ? '正在验证…' : '登录工作台'}<ArrowRight size={16}/></Button>
    </form><p className="mt-7 flex items-center justify-center gap-2 text-xs text-slate-400"><ShieldCheck size={14}/>双重验证保护你的短信与设备</p></div></div>
  </div>
}

export function Setup({ session, onComplete, onLogout }: { session: Session; onComplete: (session: Session) => void; onLogout: () => void }) {
  const [setup, setSetup] = useState<{secret: string; uri: string} | null>(null)
  const [codes, setCodes] = useState<string[]>([])
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  return <div className="flex min-h-dvh items-center justify-center p-5"><div className="panel w-full max-w-md p-7"><ShieldCheck className="mb-5 text-teal-700" size={32}/><h1 className="text-2xl font-semibold">{codes.length ? '保存恢复码' : '绑定二次验证'}</h1><p className="my-4 text-sm leading-6 text-slate-500">{codes.length ? '仅展示一次。请保存到密码管理器，每个恢复码只能使用一次。' : '使用 Google Authenticator 或其他 TOTP 验证器扫码。完成绑定后才能进入工作台。'}</p>
    {codes.length ? <><div className="grid grid-cols-2 gap-2 rounded-xl bg-slate-50 p-4 font-mono text-xs">{codes.map(c => <code key={c}>{c}</code>)}</div><Button className="mt-5 w-full" onClick={() => { setCsrf(token); onComplete({ ...session, scope: 'authenticated', csrf: token }) }}>已安全保存，进入工作台</Button></> : <>
      {!setup ? <Button disabled={busy} onClick={async () => { setBusy(true); try { setSetup(await post('/auth/totp/setup')) } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }}>生成绑定二维码</Button> : <><div className="my-6 flex justify-center"><QRCodeSVG value={setup.uri} size={180}/></div><p className="mb-5 break-all rounded-lg bg-slate-50 p-3 font-mono text-xs">手动密钥：{setup.secret}</p><form className="space-y-4" onSubmit={async e => { e.preventDefault(); setBusy(true); setError(''); const code = new FormData(e.currentTarget).get('code'); try { const result = await post('/auth/totp/confirm', {code}); setCsrf(result.csrf); setToken(result.csrf); setCodes(result.recovery_codes) } catch (err) { setError((err as Error).message) } finally { setBusy(false) } }}><Field title="6 位动态验证码"><input name="code" inputMode="numeric" pattern="[0-9]{6}" autoComplete="one-time-code" required/></Field><Button className="w-full" disabled={busy}>验证并启用</Button></form></>}
      {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}<Button className="mt-4" variant="ghost" onClick={onLogout}>退出登录</Button>
    </>}</div></div>
}

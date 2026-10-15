import { useState } from 'react'
import { Mail, Bell, Plus, Pencil, Trash2, CheckCircle2, ShieldCheck, Wifi, Smartphone, Signal, Copy, Link2 } from 'lucide-react'
import { api, post, date, setCsrf } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { action, Confirm, Empty, Field, LoadError, Modal, useData } from '@/components/common'
import type { Sim } from './Messages'
import type { Session } from './Auth'

type Channel = { id: string; name: string; type: string; enabled: boolean; config: Record<string, any> }

export function Cards({ sims, refresh, onInbox }: { sims: Sim[]; refresh: () => void; onInbox: (id: string) => void }) {
  const [edit, setEdit] = useState<Sim | null>(null)
  const [bindings, setBindings] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  const [initialKey, setInitialKey] = useState('')
  const [keyCard, setKeyCard] = useState<Sim | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<Sim | null>(null)
  const { data: channels } = useData<Channel[]>('/channels')
  return <>
    <div className="mb-5 flex items-center justify-between"><p className="text-sm text-slate-500">共 {sims.length} 张电话卡</p><Button onClick={() => setAdding(true)}><Plus/>添加手机号</Button></div>
    {!sims.length ? <div className="panel"><Empty title="连接你的第一张电话卡" detail="先添加手机号并签发永久 API Key，随时填写到设备配置中接入，无配对时限。"/></div> : <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{sims.map(s => <div className="panel p-6" key={s.id}><div className="flex items-center justify-between"><span className="rounded-xl bg-slate-100 p-3"><Smartphone className="text-slate-600" size={23}/></span><span className={'flex items-center gap-1.5 text-xs ' + (s.online ? 'text-emerald-600' : 'text-slate-400')}><span className={'size-1.5 rounded-full ' + (s.online ? 'bg-emerald-500' : 'bg-slate-300')}/>{s.online ? '设备在线' : '设备离线'}</span></div><h3 className="mt-5 text-lg font-semibold">{s.name}</h3><p className="mt-1 font-mono text-sm text-slate-500">{s.phone_number || '手机号未设置'}</p><dl className="my-5 grid grid-cols-2 gap-y-3 text-xs"><dt className="text-slate-400">运营商</dt><dd className="text-right">{s.operator_name || '未知'}</dd><dt className="text-slate-400">信号强度</dt><dd className="text-right">{s.signal_dbm != null ? `${s.signal_dbm} dBm` : '未知'}</dd><dt className="text-slate-400">SIM / 网络</dt><dd className="text-right">{s.sim_status || '未知'} / {s.network_status || '未知'}</dd><dt className="text-slate-400">最后在线</dt><dd className="text-right">{date(s.last_seen_at)}</dd></dl><p className="truncate rounded-lg bg-slate-50 p-2 font-mono text-[10px] text-slate-400">ICCID {s.iccid}</p>{s.last_error && <p className="mt-3 text-xs text-amber-700">{s.last_error}</p>}<div className="mt-5 flex gap-2"><Button variant="outline" size="sm" className="flex-1" onClick={() => onInbox(s.id)}>查看短信</Button><Button variant="ghost" size="sm" onClick={() => { setEdit(s); setBindings(s.channel_ids) }}><Pencil/>设置</Button><Button variant="ghost" size="sm" onClick={() => { setInitialKey(''); setKeyCard(s) }}>API Key</Button></div></div>)}</div>}
    {keyCard && <SimApiKey sim={keyCard} initialKey={initialKey} onClose={() => { setKeyCard(null); setInitialKey('') }}/>}
    {adding && <Modal open title="添加手机号" description="添加后立即签发长期有效的 API Key，不需要配对，也不限制设备接入时间。" onClose={() => { if (!busy) setAdding(false) }}><form className="space-y-4" onSubmit={async e => { e.preventDefault(); const body = Object.fromEntries(new FormData(e.currentTarget)); setBusy(true); await action(async () => { const result = await post('/sims', body); setAdding(false); refresh(); setInitialKey(result.api_key); setKeyCard({id:result.sim_id,name:result.name,phone_number:result.phone_number,iccid:'',online:false,channel_ids:[],queue_depth:0}) }, '手机号已添加，API Key 已签发'); setBusy(false) }}><Field title="名称"><input name="name" required maxLength={100}/></Field><Field title="手机号"><input name="phone_number" required pattern="\+?[0-9]{3,20}" placeholder="例如 +8613800000000"/></Field><Button disabled={busy} className="w-full">添加并签发 API Key</Button></form></Modal>}
    {edit && <Modal open title="电话卡设置" description="修改卡片信息，并选择收到短信后需要通知的通道。" onClose={() => { if (!busy) setEdit(null) }}><form className="space-y-4" onSubmit={async e => { e.preventDefault(); setBusy(true); const form = Object.fromEntries(new FormData(e.currentTarget)); const ok = await action(async () => { await api(`/sims/${edit.id}`, {method:'PATCH', body: JSON.stringify(form)}); await api(`/sims/${edit.id}/channels`, {method:'PUT', body:JSON.stringify({channel_ids:bindings})}) }); setBusy(false); if (ok) { setEdit(null); refresh() } }}><Field title="名称"><input name="name" defaultValue={edit.name} required maxLength={100}/></Field><Field title="手机号"><input name="phone_number" defaultValue={edit.phone_number} maxLength={32}/></Field><Field title="备注"><textarea name="notes" defaultValue={edit.notes} maxLength={2000}/></Field><div className="space-y-3"><p className="text-sm font-medium">自动转发到</p>{channels?.length ? channels.map(c => <label key={c.id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3 text-sm"><input type="checkbox" checked={bindings.includes(c.id)} onChange={e => setBindings(e.target.checked ? [...bindings,c.id] : bindings.filter(id => id!==c.id))}/>{c.name}{!c.enabled && <span className="text-xs text-slate-400">已停用</span>}</label>) : <p className="text-xs text-slate-400">还没有通知通道，请先在转发设置中添加。</p>}</div><Button className="w-full" disabled={busy}>保存设置</Button></form>{edit.device_id && <Button variant="ghost" className="mt-4 w-full text-red-600" onClick={() => setConfirm(edit)}>解绑设备</Button>}</Modal>}
    {confirm && <Confirm text="撤销后设备无法继续访问平台，正在发送的短信将标为结果未知。重新接入使用此手机号的有效 API Key。" onConfirm={async () => { await post(`/devices/${confirm.device_id}/revoke`); setEdit(null); refresh() }} onClose={() => setConfirm(null)}/>}
  </>
}

export function Channels({ revision, refresh }: { revision: number; refresh: () => void }) {
  const { data, loading, error } = useData<Channel[]>('/channels', revision)
  const [edit, setEdit] = useState<Channel | 'new' | null>(null)
  const [remove, setRemove] = useState<Channel | null>(null)
  const [busy, setBusy] = useState(false)
  return <>
    <div className="mb-5 flex items-center justify-between gap-3"><p className="text-sm text-slate-500">通道创建后，在电话卡设置中绑定。</p><Button onClick={() => setEdit('new')}><Plus/>添加通道</Button></div><LoadError error={error} loading={loading}/>
    <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{data?.map(c => <div className="panel p-6" key={c.id}><div className="flex items-center justify-between"><div className="rounded-xl bg-teal-50 p-3 text-teal-700">{c.type === 'smtp' ? <Mail size={22}/> : <Bell size={22}/>}</div><span className={'text-xs ' + (c.enabled ? 'text-emerald-600' : 'text-slate-400')}>{c.enabled ? '已启用' : '已停用'}</span></div><h3 className="mt-5 text-lg font-semibold">{c.name}</h3><p className="mt-1 text-xs uppercase tracking-wider text-slate-400">{c.type === 'smtp' ? 'Email · SMTP' : c.type}</p><p className="my-5 truncate text-sm text-slate-500">{c.config.recipient || c.config.server}</p><div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={async () => { setBusy(true); await action(() => post(`/channels/${c.id}/test`), '测试通知已发送'); setBusy(false) }}>测试通知</Button><Button size="sm" variant="ghost" onClick={() => setEdit(c)}><Pencil/>编辑</Button><Button size="sm" variant="ghost" aria-label="删除通道" onClick={() => setRemove(c)}><Trash2/></Button></div></div>)}</div>
    {data && !data.length && <div className="panel"><Empty title="让重要消息主动找到你" detail="连接 QQ 邮箱、Gmail、Bark 或 PushDeer，收到短信后自动发送通知。"/></div>}
    {edit && <ChannelForm value={edit === 'new' ? undefined : edit} onClose={() => setEdit(null)} refresh={refresh}/>}
    {remove && <Confirm text={`删除通道“${remove.name}”？未执行的转发任务将被取消。`} onConfirm={async () => { await api(`/channels/${remove.id}`, {method:'DELETE'}); refresh() }} onClose={() => setRemove(null)}/>}
  </>
}

function ChannelForm({ value, onClose, refresh }: { value?: Channel; onClose: () => void; refresh: () => void }) {
  const [kind, setKind] = useState(value?.type || 'smtp')
  const [preset, setPreset] = useState('custom')
  const [busy, setBusy] = useState(false)
  const [enabled, setEnabled] = useState(value?.enabled ?? true)
  const config = value?.config || {}
  return <Modal open title={value ? '编辑通知通道' : '添加通知通道'} description="凭据加密存储，不会在列表或编辑页面回显。" onClose={() => { if (!busy) onClose() }}><form className="space-y-4" onSubmit={async e => { e.preventDefault(); setBusy(true); const values = Object.fromEntries(new FormData(e.currentTarget)) as Record<string,string>; const secret = values.secret; const next = {name:values.name, type:kind, enabled, credentials: secret ? {[kind === 'smtp' ? 'password':'key']: secret} : null, config: kind === 'smtp' ? {host:values.host, port:Number(values.port), tls:values.tls, username:values.username, sender:values.sender, recipient:values.recipient} : {server:values.server}}; const ok = await action(() => api(value ? `/channels/${value.id}` : '/channels', {method:value ? 'PATCH':'POST', body:JSON.stringify(next)})); setBusy(false); if (ok) { refresh(); onClose() } }}>
    <Field title="通道名称"><input name="name" defaultValue={value?.name} required placeholder="例如：我的 QQ 邮箱" maxLength={100}/></Field><Field title="通道类型"><select value={kind} disabled={!!value} onChange={e => setKind(e.target.value)}><option value="smtp">邮件（QQ / Gmail / 自定义 SMTP）</option><option value="bark">Bark</option><option value="pushdeer">PushDeer</option></select></Field>
    {kind === 'smtp' ? <><Field title="SMTP 预设"><select value={preset} onChange={e => setPreset(e.target.value)}><option value="custom">自定义</option><option value="qq">QQ 邮箱</option><option value="gmail">Gmail</option></select></Field><div key={preset} className="space-y-4"><Field title="SMTP 主机"><input name="host" required defaultValue={preset === 'qq' ? 'smtp.qq.com' : preset === 'gmail' ? 'smtp.gmail.com' : config.host} placeholder="smtp.example.com"/></Field><div className="grid grid-cols-2 gap-3"><Field title="端口"><input name="port" type="number" required defaultValue={config.port || 465}/></Field><Field title="加密方式"><select name="tls" defaultValue={config.tls || 'ssl'}><option value="ssl">SSL / TLS</option><option value="starttls">STARTTLS</option></select></Field></div></div><Field title="SMTP 登录账号"><input name="username" defaultValue={config.username} required/></Field><Field title="发件邮箱"><input name="sender" type="email" defaultValue={config.sender} required/></Field><Field title="接收通知的邮箱"><input name="recipient" type="email" defaultValue={config.recipient} required/></Field></> : <Field title="服务地址（不含 Key）"><input name="server" type="url" key={kind} defaultValue={config.server || (kind === 'bark' ? 'https://api.day.app' : 'https://api2.pushdeer.com')} required/></Field>}
    <Field title={kind === 'smtp' ? 'SMTP 授权码 / 应用密码' : '设备 Key / PushKey'}><input name="secret" type="password" autoComplete="new-password" required={!value} placeholder={value ? '已保存，留空保持不变' : '填写凭据'}/></Field><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}/>启用此通道</label><Button className="w-full" disabled={busy}>保存通道</Button>
  </form></Modal>
}

export function Security({ onSession }: { onSession: (session: Partial<Session>) => void }) {
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState('password')
  return <div className="panel max-w-xl p-6 sm:p-8"><div className="mb-6 flex items-center gap-3"><ShieldCheck className="text-teal-700"/><div><h2 className="font-semibold">账户安全</h2><p className="mt-1 text-xs text-slate-500">修改密码或重新绑定验证器需再次确认身份。</p></div></div><form className="space-y-5" onSubmit={async e => { e.preventDefault(); const values = Object.fromEntries(new FormData(e.currentTarget)); setBusy(true); await action(async () => { const result = await post('/auth/security', {...values, new_password: mode === 'password' ? values.new_password : null}); setCsrf(result.csrf); onSession(result) }); setBusy(false) }}><Field title="操作"><select value={mode} onChange={e => setMode(e.target.value)}><option value="password">修改登录密码</option><option value="totp">重新绑定二次验证</option></select></Field><Field title="当前密码"><input name="password" type="password" autoComplete="current-password" required/></Field><Field title="动态验证码 / 恢复码"><input name="code" autoComplete="one-time-code" required/></Field>{mode === 'password' && <Field title="新密码（至少 8 位）"><input name="new_password" type="password" autoComplete="new-password" minLength={8} required/></Field>}<p className="text-xs leading-6 text-slate-500">操作成功后其他会话将失效。重置验证器后，旧恢复码也会失效，需重新绑定。</p><Button disabled={busy}>验证并保存</Button></form></div>
}


type KeyInfo = { active: boolean; key: { key_hint: string; created_at: string; last_used_at: string | null } | null }
function SimApiKey({ sim, onClose, initialKey = '' }: { sim: Sim; onClose: () => void; initialKey?: string }) {
  const [revision, setRevision] = useState(0)
  const { data, error, loading } = useData<KeyInfo>(`/sims/${sim.id}/api-key`, revision)
  const [secret, setSecret] = useState(initialKey)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<'reset' | 'delete' | null>(null)
  async function issue(reset = false) {
    setBusy(true)
    await action(async () => {
      setSecret('')
      const result = await post(`/sims/${sim.id}/api-key${reset ? '/reset' : ''}`)
      setSecret(result.api_key)
      setRevision(v => v + 1)
    }, 'API Key 已签发，请立即保存')
    setBusy(false)
  }
  return <Modal open title="手机号 API Key" description={`${sim.name} · ${sim.phone_number || '手机号未填写'}。永久有效，仅可操作当前手机号；删除或重置后旧 Key 失效，设备也需更新 Key。`} onClose={() => { if (!busy) onClose() }}>
    <LoadError error={error} loading={loading}/>
    {data && <div className="space-y-4">
      <p className="text-sm">状态：{data.active ? '已签发' : '未签发'}</p>
      {data.key && <dl className="space-y-2 text-xs text-slate-500"><div>标识：{data.key.key_hint}</div><div>签发时间：{date(data.key.created_at)}</div><div>最近调用：{date(data.key.last_used_at || undefined)}</div></dl>}
      <p className="break-all text-xs text-slate-500">卡片 ID：{sim.id}</p>
      {secret && <div className="rounded-xl bg-amber-50 p-4"><p className="mb-3 text-sm text-amber-800">完整 Key 仅本次显示，关闭后无法再次查看。请保存在调用程序的环境变量中。</p><code className="block break-all text-xs">{secret}</code><Button className="mt-3" variant="outline" onClick={() => void action(() => navigator.clipboard.writeText(secret), 'Key 已复制')}><Copy/>复制 Key</Button></div>}
      <div className="flex gap-3">{data.active ? <><Button disabled={busy} onClick={() => setConfirm('reset')}>重置 Key</Button><Button disabled={busy} variant="destructive" onClick={() => setConfirm('delete')}>删除 Key</Button></> : <Button disabled={busy} onClick={() => void issue()}>签发 API Key</Button>}</div>
      <p className="text-xs leading-6 text-slate-500">API 入口：/api/v1/sim。请求使用 Authorization: Bearer &lt;API_KEY&gt;。使用方法见项目 docs/API使用方法.md。</p>
    </div>}
    {confirm && <Confirm text={confirm === 'reset' ? '重置后旧 Key 立即失效，请更新所有调用程序。已排队的短信仍会继续发送。' : '删除后外部程序将无法操作此卡片。使用旧 Key 的设备也会失去访问权限；已排队短信保留。'} onClose={() => setConfirm(null)} onConfirm={async () => {
      if (confirm === 'reset') { await issue(true) }
      else { await api(`/sims/${sim.id}/api-key`, {method:'DELETE'}); setSecret(''); setRevision(v => v + 1) }
    }}/>} 
  </Modal>
}

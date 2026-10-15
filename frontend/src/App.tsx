import { useEffect, useState } from 'react'
import { Toaster, toast } from 'sonner'
import { Radio, LayoutDashboard, Smartphone, Inbox, Send, Settings2, ShieldCheck, LogOut, Plus, ArrowUpRight, ArrowDownLeft, Wifi, AlertTriangle, ChevronRight, Menu } from 'lucide-react'
import { api, post, date, setCsrf } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Empty, LoadError, useData } from '@/components/common'
import { Login, Setup, type Session } from '@/pages/Auth'
import { Compose, Messages, type Sim, type Message } from '@/pages/Messages'
import { Cards, Channels, Security } from '@/pages/Settings'

const navigation = [
  { id:'overview', title:'总览', subtitle:'每条消息，尽在掌握。', icon:LayoutDashboard },
  { id:'sims', title:'电话卡', subtitle:'连接设备，查看每张电话卡的状态。', icon:Smartphone },
  { id:'incoming', title:'收件箱', subtitle:'所有电话卡的短信，汇集于此。', icon:Inbox },
  { id:'outgoing', title:'发件箱', subtitle:'创建短信，追踪每一次发送。', icon:Send },
  { id:'channels', title:'转发设置', subtitle:'把重要消息送到你常用的地方。', icon:Settings2 },
  { id:'security', title:'账户安全', subtitle:'管理登录密码与双重验证。', icon:ShieldCheck },
]

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [checking, setChecking] = useState(true)
  useEffect(() => { api<Session>('/auth/me').then(s => { setCsrf(s.csrf); setSession(s) }).catch(() => {}).finally(() => setChecking(false)); const expired = () => { setSession(null); toast.error('会话已过期，请重新登录') }; window.addEventListener('session-expired', expired); return () => window.removeEventListener('session-expired', expired) }, [])
  async function logout() { try { await post('/auth/logout'); setSession(null); setCsrf('') } catch(e) { toast.error((e as Error).message) } }
  return <><Toaster position="top-center" richColors closeButton/>{checking ? <div className="flex min-h-dvh items-center justify-center text-slate-400">正在连接工作台…</div> : !session ? <Login onLogin={setSession}/> : session.scope !== 'authenticated' ? <Setup session={session} onComplete={setSession} onLogout={logout}/> : <Workspace session={session} onSession={next => setSession({...session, ...next})} logout={logout}/>}</>
}

function Workspace({ session, onSession, logout }: { session: Session; onSession: (next: Partial<Session>) => void; logout: () => void }) {
  const [page, setPage] = useState('overview')
  const [revision, setRevision] = useState(0)
  const [simFilter, setSimFilter] = useState('')
  const [compose, setCompose] = useState(false)
  const [original, setOriginal] = useState<Message | undefined>()
  const [menu, setMenu] = useState(false)
  const sims = useData<Sim[]>('/sims', revision)
  const current = navigation.find(n => n.id === page)!
  const refresh = () => setRevision(v => v+1)
  function navigate(id: string) { setPage(id); setMenu(false); if(id !== 'incoming') setSimFilter('') }
  const navContent = <><div className="flex h-24 items-center gap-3 px-7 text-xl font-semibold text-white"><div className="rounded-xl bg-teal-400/10 p-2 text-teal-300"><Radio size={24}/></div>SMSBot<span className="ml-auto rounded border border-slate-700 px-1.5 py-0.5 text-[9px] font-normal text-slate-400">WORKSPACE</span></div><div className="px-5 pt-5"><p className="mb-4 px-3 text-[10px] tracking-[.2em] text-slate-500">工作空间</p><nav className="space-y-1.5">{navigation.map((n,i) => <button key={n.id} onClick={() => { setSimFilter(''); navigate(n.id) }} className={'flex w-full items-center gap-3 rounded-xl px-4 py-3 text-sm transition ' + (page === n.id ? 'bg-teal-400/10 text-teal-300' : 'text-slate-400 hover:bg-white/5 hover:text-slate-200') }><n.icon size={18}/>{n.title}{page === n.id && <span className="ml-auto size-1.5 rounded-full bg-teal-300"/>}</button>)}</nav></div><div className="mt-auto p-5"><div className="mb-5 rounded-xl border border-slate-700/50 p-4"><div className="flex items-center gap-2 text-xs text-slate-300"><ShieldCheck size={15} className="text-teal-400"/>你的私有短信空间</div><p className="mt-2 text-[11px] leading-5 text-slate-500">数据保存在你的服务器<br/>设备与消息统一管理</p></div><button onClick={logout} className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-sm text-slate-400 hover:text-white"><span className="flex size-8 items-center justify-center rounded-full bg-slate-700 text-xs text-white">{session.username.slice(0,1).toUpperCase()}</span><span className="min-w-0 flex-1 truncate text-left">{session.username}</span><LogOut size={16}/></button></div></>
  return <div className="min-h-dvh"><aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col bg-[#101a2d] lg:flex">{navContent}</aside>
    {menu && <div className="fixed inset-0 z-40 lg:hidden"><button aria-label="关闭菜单" className="absolute inset-0 bg-black/40" onClick={() => setMenu(false)}/><aside className="relative flex h-full w-72 flex-col bg-[#101a2d]">{navContent}</aside></div>}
    <div className="lg:ml-64"><header className="flex h-17 items-center justify-between border-b border-slate-200/70 bg-white/80 px-5 sm:px-9"><div className="flex items-center gap-3 text-xs text-slate-400"><button className="lg:hidden" aria-label="打开菜单" onClick={() => setMenu(true)}><Menu size={22}/></button><span>工作空间</span><ChevronRight size={12}/><span className="text-slate-700">{current.title}</span></div><div className="flex items-center gap-2 text-[11px] text-slate-500"><span className="size-1.5 rounded-full bg-teal-500"/>自托管工作台</div></header>
    <main className="mx-auto max-w-[1440px] px-5 py-7 sm:px-9 sm:py-9"><div className="mb-8 flex items-center justify-between gap-4"><div><p className="eyebrow mb-2">{page === 'overview' ? 'OVERVIEW' : 'SMS WORKSPACE'}</p><h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">{current.title}</h1><p className="mt-2 text-xs leading-5 text-slate-500 sm:text-sm">{current.subtitle}</p></div>{(page === 'overview' || page === 'outgoing') && <Button onClick={() => { setOriginal(undefined); setCompose(true) }}><Plus/><span className="hidden sm:inline">新建短信</span><span className="sm:hidden">发短信</span></Button>}</div>
      <LoadError error={sims.error} loading={false}/>
      {page === 'overview' && <Overview sims={sims.data || []} revision={revision} navigate={navigate}/>}
      {page === 'sims' && <Cards sims={sims.data || []} refresh={refresh} onInbox={id => { setSimFilter(id); setPage('incoming') }}/>}
      {(page === 'incoming' || page === 'outgoing') && <Messages key={page+simFilter} kind={page} sims={sims.data || []} revision={revision} refresh={refresh} initialSim={simFilter} onCompose={m => { setOriginal(m); setCompose(true) }}/>}
      {page === 'channels' && <Channels revision={revision} refresh={refresh}/>}
      {page === 'security' && <Security onSession={onSession}/>}
      <footer className="mt-10 flex justify-between border-t border-slate-200/70 pt-5 text-[10px] text-slate-400"><span>SMSBot · 每条消息，都有归处</span><span>每 15 秒更新</span></footer>
    </main></div>{compose && <Compose sims={sims.data || []} original={original} onClose={() => setCompose(false)} onSent={() => { refresh(); navigate('outgoing') }}/>}</div>
}

function Overview({ sims, revision, navigate }: { sims: Sim[]; revision: number; navigate: (id: string) => void }) {
  const stats = useData<Record<string,number>>('/dashboard', revision)
  const recent = useData<{items: Message[]}>('/incoming?size=5', revision)
  const tiles = [ {name:'近 24 小时收信', key:'incoming_today', icon:Inbox, color:'bg-teal-50 text-teal-700'}, {name:'在线设备',key:'online',icon:Wifi,color:'bg-blue-50 text-blue-600'}, {name:'待发送短信',key:'pending',icon:Send,color:'bg-violet-50 text-violet-600'}, {name:'转发失败',key:'forwarding_failed',icon:AlertTriangle,color:'bg-amber-50 text-amber-600'} ]
  return <><LoadError error={stats.error} loading={stats.loading}/><div className="mb-7 grid grid-cols-2 gap-3 xl:grid-cols-4 sm:gap-5">{tiles.map(t => <div key={t.key} className="panel p-4 sm:p-6"><div className="mb-5 flex items-center justify-between"><span className="text-xs text-slate-500">{t.name}</span><span className={'rounded-lg p-2 '+t.color}><t.icon size={16}/></span></div><p className="text-3xl font-semibold tracking-tight text-slate-900">{stats.data?.[t.key] ?? '—'}</p><p className="mt-3 text-[11px] text-slate-400">{t.key === 'online' ? `共 ${sims.length} 张电话卡` : t.key === 'forwarding_failed' ? '可在短信详情中重试' : t.key === 'pending' ? '由设备自动领取' : '自动同步至工作台'}</p></div>)}</div>
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]"><section className="panel overflow-hidden"><div className="flex items-center justify-between border-b border-slate-100 p-5"><h2 className="text-sm font-semibold">最近收到</h2><Button variant="ghost" size="sm" onClick={() => navigate('incoming')}>全部短信<ArrowUpRight size={14}/></Button></div><LoadError error={recent.error} loading={recent.loading}/>{recent.data?.items.length ? <div className="divide-y divide-slate-100">{recent.data.items.map(m => <button key={m.id} className="flex w-full gap-4 p-5 text-left hover:bg-slate-50" onClick={() => navigate('incoming')}><span className="mt-1 rounded-xl bg-teal-50 p-2.5 text-teal-700"><ArrowDownLeft size={18}/></span><div className="min-w-0 flex-1"><div className="flex justify-between gap-3"><span className="text-sm font-semibold">{m.sender}</span><span className="text-[10px] text-slate-400">{date(m.received_at)}</span></div><p className="my-2 line-clamp-2 break-words text-sm leading-6 text-slate-500">{m.body}</p><span className="text-[10px] text-slate-400">{m.sim_name}</span></div></button>)}</div> : !recent.loading && <Empty title="等待第一条消息" detail="连接设备后，短信会自动同步。你的所有消息将在这里井然有序。" action={<Button variant="outline" onClick={() => navigate('sims')}>连接设备<ArrowUpRight/></Button>}/>}</section>
    <div className="space-y-5"><section className="panel p-5"><div className="mb-5 flex items-center justify-between"><h2 className="text-sm font-semibold">电话卡状态</h2><button className="text-xs text-teal-700" onClick={() => navigate('sims')}>管理</button></div>{sims.length ? sims.slice(0,5).map(s => <div key={s.id} className="flex items-center gap-3 border-b border-slate-100 py-4 last:border-0"><Smartphone size={20} className="text-slate-400"/><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{s.name}</p><p className="mt-1 text-[10px] text-slate-400">{s.operator_name || '运营商未知'}</p></div><span className={'text-[10px] '+(s.online ? 'text-emerald-600':'text-slate-400')}>{s.online ? '在线':'离线'}</span></div>) : <p className="py-5 text-center text-xs text-slate-400">暂无已注册的电话卡</p>}</section><section className="rounded-2xl border border-teal-100 bg-teal-50/60 p-6"><div className="mb-4 flex size-9 items-center justify-center rounded-xl bg-white text-teal-700"><Settings2 size={18}/></div><h3 className="text-sm font-semibold text-teal-900">让消息主动抵达</h3><p className="my-3 text-xs leading-6 text-teal-800/65">连接邮箱、Bark 或 PushDeer。为每张电话卡设置专属转发通道。</p><button onClick={() => navigate('channels')} className="flex items-center gap-2 text-xs font-semibold text-teal-800">配置通知通道<ArrowUpRight size={14}/></button></section></div></div>
  </>
}

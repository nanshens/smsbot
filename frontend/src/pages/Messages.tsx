import { useState } from 'react'
import { Copy, Search, Send, Trash2, X, RefreshCw, ArrowUpRight, ArrowDownLeft } from 'lucide-react'
import { toast } from 'sonner'
import { api, post, date } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { action, Confirm, Empty, Field, LoadError, Modal, Status, useData } from '@/components/common'

export type Sim = { id: string; name: string; phone_number?: string; iccid: string; device_id?: string; online: boolean; operator_name?: string; signal_dbm?: number; sim_status?: string; network_status?: string; last_seen_at?: string; notes?: string; channel_ids: string[]; queue_depth: number; last_error?: string }
export type Message = { id: string; sim_id: string; sim_name: string; sim_phone?: string; body: string; sender?: string; recipient?: string; status?: string; received_at?: string; created_at?: string; modem_received_at?: string; last_error?: string; forwarding?: any[]; attempts?: any[] }

export function Compose({ sims, onClose, onSent, original }: { sims: Sim[]; onClose: () => void; onSent: () => void; original?: Message }) {
  const [busy, setBusy] = useState(false)
  const [body, setBody] = useState(original?.body || '')
  const [key] = useState(() => crypto.randomUUID())
  return <Modal open onClose={() => { if (!busy) onClose() }} title={original ? '重新发送短信' : '新建短信'} description={original ? '原短信可能已提交给运营商。确认后创建新的发送记录，可能重复发送。' : '选择电话卡，设备将自动领取并发送。'}>
    <form className="space-y-5" onSubmit={async e => { e.preventDefault(); setBusy(true); const values = Object.fromEntries(new FormData(e.currentTarget)); const ok = await action(() => post('/outgoing', {...values, idempotency_key: key, retry_of: original?.id || null}), '已加入发送队列'); setBusy(false); if (ok) { onSent(); onClose() } }}>
      <Field title="发送电话卡"><select name="sim_id" defaultValue={original?.sim_id || ''} required><option value="" disabled>选择电话卡</option>{sims.map(s => <option key={s.id} value={s.id}>{s.name} · {s.phone_number || s.iccid} {!s.online ? '（离线，稍后发送）' : ''}</option>)}</select></Field>
      <Field title="收件号码"><input name="recipient" placeholder="例如 +8613800000000" defaultValue={original?.recipient} pattern="\+?[0-9]{3,20}" required/></Field>
      <Field title="短信正文"><textarea name="body" value={body} onChange={e => setBody(e.target.value)} maxLength={670} required placeholder="输入短信内容…" rows={5}/></Field>
      <div className="flex justify-between text-xs text-slate-400"><span>使用 UCS2 编码，不支持 emoji</span><span>{body.length} / 670 · {body.length <= 70 ? 1 : Math.ceil(body.length / 67)} 条计费分片</span></div>
      <div className="rounded-xl bg-amber-50 p-3 text-xs leading-6 text-amber-800">发送成功表示模组已提交，不代表对方已收到。费用按 SIM 卡套餐收取。</div>
      <Button disabled={busy} className="w-full"><Send size={16}/>{busy ? '正在提交…' : '加入发送队列'}</Button>
    </form>
  </Modal>
}

export function Messages({ kind, sims, revision, refresh, initialSim, onCompose }: { kind: 'incoming'|'outgoing'; sims: Sim[]; revision: number; refresh: () => void; initialSim: string; onCompose: (message?: Message) => void }) {
  const [sim, setSim] = useState(initialSim)
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [detail, setDetail] = useState<Message | null>(null)
  const [confirm, setConfirm] = useState<{text: string; run: () => Promise<unknown>} | null>(null)
  const params = new URLSearchParams({ page: String(page), q: search, status })
  if (sim) params.set('sim_id', sim)
  if (start) params.set('start', new Date(start).toISOString())
  if (end) params.set('end', new Date(end).toISOString())
  const { data, error, loading } = useData<{ items: Message[]; total: number }>(`/${kind}?${params}`, revision)
  const incoming = kind === 'incoming'
  function deletion(ids: string[]) { setConfirm({ text: `删除 ${ids.length} 条短信？未执行的转发会取消，已送达的通知无法撤回。待发短信请先取消。`, run: async () => { for (const id of ids) await api(`/${kind}/${id}`, {method: 'DELETE'}); setSelected([]); setDetail(null); refresh() } }) }
  return <>
    <div className="panel overflow-hidden"><div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4 sm:p-5">
      <form className="relative min-w-48 flex-1" onSubmit={e => { e.preventDefault(); setSearch(q); setPage(1); setSelected([]) }}><Search className="absolute left-3 top-3 text-slate-400" size={16}/><input aria-label="搜索短信" style={{paddingLeft: 36}} value={q} onChange={e => setQ(e.target.value)} placeholder="搜索短信内容或号码，回车查询"/></form>
      <div className="w-40"><select aria-label="按电话卡筛选" value={sim} onChange={e => { setSim(e.target.value); setPage(1); setSelected([]) }}><option value="">全部电话卡</option>{sims.map(s => <option value={s.id} key={s.id}>{s.name}</option>)}</select></div>
      <div className="w-36"><select aria-label="按状态筛选" value={status} onChange={e => { setStatus(e.target.value); setPage(1); setSelected([]) }}><option value="">全部状态</option><option value="pending">{incoming ? '待转发' : '待发送'}</option><option value="sent">成功</option><option value="failed">失败</option>{!incoming && <><option value="leased">设备已领取</option><option value="unknown">结果未知</option><option value="cancelled">已取消</option></>}</select></div>
      <Button variant="ghost" size="icon" aria-label="刷新" onClick={refresh}><RefreshCw/></Button>
      <div className="flex w-full flex-wrap gap-3"><label className="flex items-center gap-2 text-xs text-slate-500">从<input type="datetime-local" value={start} onChange={e => { setStart(e.target.value); setPage(1) }}/></label><label className="flex items-center gap-2 text-xs text-slate-500">到<input type="datetime-local" value={end} onChange={e => { setEnd(e.target.value); setPage(1) }}/></label>{selected.length > 0 && <Button variant="destructive" size="sm" onClick={() => deletion(selected)}><Trash2/>删除已选 {selected.length} 条</Button>}</div>
    </div>
    <LoadError error={error} loading={loading}/>
    {data && !data.items.length && <Empty title={incoming ? '还没有收到短信' : '还没有发信记录'} detail={incoming ? '设备接入后，收到的短信将自动出现在这里。也可以调整筛选条件。' : '使用已注册的电话卡发送第一条短信。'} action={!incoming && <Button onClick={() => onCompose()}>新建短信</Button>}/>}
    <div className="divide-y divide-slate-100">{data?.items.map(m => <div key={m.id} className="group flex gap-3 p-4 transition-colors hover:bg-slate-50/70 sm:gap-5 sm:p-5">
      <input type="checkbox" aria-label={`选择 ${m.sender || m.recipient} 的短信`} className="mt-2 shrink-0" checked={selected.includes(m.id)} onChange={e => setSelected(e.target.checked ? [...selected,m.id] : selected.filter(id => id !== m.id))}/>
      <div className={'hidden size-10 shrink-0 items-center justify-center rounded-xl sm:flex ' + (incoming ? 'bg-teal-50 text-teal-700' : 'bg-blue-50 text-blue-600')}>{incoming ? <ArrowDownLeft size={20}/> : <ArrowUpRight size={20}/>}</div>
      <button className="min-w-0 flex-1 text-left" onClick={() => setDetail(m)}><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-semibold text-slate-800">{m.sender || m.recipient}</span><span className="text-[11px] text-slate-400">{date(m.received_at || m.created_at)}</span></div><p className="my-2 line-clamp-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{m.body}</p><div className="flex flex-wrap items-center gap-3"><span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-500">{m.sim_name}</span>{incoming ? m.forwarding?.map(f => <Status key={f.id} value={f.status} forwarding/>) : <Status value={m.status!}/>}</div></button>
      <Button size="icon" variant="ghost" aria-label="删除短信" onClick={() => deletion([m.id])}><Trash2 size={15}/></Button>
    </div>)}</div>
    <div className="flex items-center justify-between border-t border-slate-100 p-4 text-xs text-slate-500"><span>共 {data?.total || 0} 条 · 第 {page} 页</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={page === 1} onClick={() => { setPage(page-1); setSelected([]) }}>上一页</Button><Button size="sm" variant="outline" disabled={page*20 >= (data?.total || 0)} onClick={() => { setPage(page+1); setSelected([]) }}>下一页</Button></div></div>
    </div>
    {detail && <Modal open title="短信详情" description={`${detail.sim_name} · ${detail.sender || detail.recipient}`} onClose={() => setDetail(null)}><p className="text-xs text-slate-400">{date(detail.received_at || detail.created_at)}</p><div className="my-4 whitespace-pre-wrap break-words rounded-xl bg-slate-50 p-4 text-sm leading-7">{detail.body}</div><Button size="sm" variant="outline" onClick={() => { void action(() => navigator.clipboard.writeText(detail.body), '正文已复制') }}><Copy/>复制正文</Button>
      {detail.last_error && <p className="mt-4 text-sm text-amber-700">{detail.last_error}</p>}
      <div className="mt-5 space-y-3">{detail.forwarding?.map(f => <div key={f.id} className="rounded-xl border border-slate-100 p-3"><div className="flex items-center justify-between"><span className="text-sm">{f.channel_name}</span><Status value={f.status} forwarding/></div>{f.last_error && <p className="mt-2 text-xs text-amber-700">{f.last_error}</p>}{f.status === 'failed' && <Button className="mt-2" size="sm" variant="outline" onClick={async () => { if (await action(() => post(`/forwarding/${f.id}/retry`), '已安排重试')) { refresh(); setDetail(null) } }}>重试转发</Button>}</div>)}</div>
      {detail.attempts?.map(a => <p key={a.id} className="mt-3 text-xs leading-6 text-slate-500">执行阶段：{a.phase} · {date(a.claimed_at)}{a.error_message && <span className="block text-amber-700">{a.error_message}</span>}</p>)}
      {detail.status === 'pending' && <Button className="mt-4" variant="outline" onClick={async () => { if (await action(() => post(`/outgoing/${detail.id}/cancel`))) { refresh(); setDetail(null) } }}><X/>取消待发任务</Button>}
      {['unknown','failed'].includes(detail.status || '') && <Button className="mt-4" variant="outline" onClick={() => { onCompose(detail); setDetail(null) }}>确认风险后重新发送</Button>}
    </Modal>}
    {confirm && <Confirm text={confirm.text} onConfirm={confirm.run} onClose={() => setConfirm(null)}/>}
  </>
}

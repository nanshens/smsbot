import { useEffect, useState, type ReactNode } from 'react'
import { Inbox, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog'
import { Button } from './ui/button'

export function useData<T>(path: string, revision = 0) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let active = true
    setLoading(true)
    setData(null)
    async function load() {
      try { const next = await api<T>(path); if (active) { setData(next); setError('') } }
      catch (e) { if (active) setError((e as Error).message) }
      finally { if (active) setLoading(false) }
    }
    void load()
    const interval = window.setInterval(load, 15000)
    return () => { active = false; window.clearInterval(interval) }
  }, [path, revision])
  return { data, error, loading }
}

export function Modal({ open, onClose, title, description, children }: { open: boolean; onClose: () => void; title: string; description?: string; children: ReactNode }) {
  return <Dialog open={open} onOpenChange={value => { if (!value) onClose() }}><DialogContent>
    <DialogTitle className="pr-8 text-lg font-semibold text-slate-900">{title}</DialogTitle>
    <DialogDescription className="mt-2 text-sm leading-6 text-slate-500">{description || '管理你的短信工作台'}</DialogDescription>
    <div className="mt-6">{children}</div>
  </DialogContent></Dialog>
}

export function Empty({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <div className="flex flex-col items-center px-5 py-16 text-center"><div className="mb-5 rounded-2xl bg-slate-50 p-4 text-slate-400"><Inbox size={28}/></div><h3 className="font-semibold text-slate-700">{title}</h3><p className="mt-2 max-w-sm text-sm leading-6 text-slate-500">{detail}</p>{action && <div className="mt-5">{action}</div>}</div>
}
export function LoadError({ error, loading }: { error: string; loading: boolean }) {
  return error ? <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p> : loading ? <div className="flex items-center justify-center gap-2 p-10 text-sm text-slate-500"><Loader2 className="animate-spin" size={18}/>正在加载…</div> : null
}
const labels: Record<string, string> = { pending: '待发送', leased: '设备已领取', processing: '转发中', sent: '发送成功', failed: '失败', unknown: '结果未知', cancelled: '已取消' }
export function Status({ value, forwarding = false }: { value: string; forwarding?: boolean }) {
  const style = value === 'sent' ? 'bg-emerald-50 text-emerald-700' : ['failed','unknown'].includes(value) ? 'bg-amber-50 text-amber-700' : value === 'cancelled' ? 'bg-slate-100 text-slate-500' : 'bg-blue-50 text-blue-700'
  return <span className={'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ' + style}><span className="size-1.5 rounded-full bg-current"/>{forwarding && value === 'pending' ? '待转发' : forwarding && value === 'sent' ? '已转发' : labels[value] || value}</span>
}
export function Field({ title, children }: { title: string; children: ReactNode }) { return <label className="field">{title}{children}</label> }
export async function action(callback: () => Promise<unknown>, success = '操作成功') {
  try { await callback(); toast.success(success); return true } catch (e) { toast.error((e as Error).message); return false }
}
export function Confirm({ text, onConfirm, onClose }: { text: string; onConfirm: () => Promise<unknown>; onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  return <Modal open onClose={() => { if (!busy) onClose() }} title="确认操作" description={text}><div className="flex justify-end gap-3"><Button variant="outline" onClick={onClose} disabled={busy}>取消</Button><Button variant="destructive" disabled={busy} onClick={async () => { setBusy(true); if (await action(onConfirm)) onClose(); setBusy(false) }}>确认</Button></div></Modal>
}

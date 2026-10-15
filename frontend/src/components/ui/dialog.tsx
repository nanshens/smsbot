import * as React from 'react'
import * as Primitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export const Dialog = Primitive.Root
export const DialogTrigger = Primitive.Trigger
export const DialogTitle = Primitive.Title
export const DialogDescription = Primitive.Description
export const DialogContent = React.forwardRef<React.ElementRef<typeof Primitive.Content>, React.ComponentPropsWithoutRef<typeof Primitive.Content>>(({ className, children, ...props }, ref) => (
  <Primitive.Portal><Primitive.Overlay className="fixed inset-0 z-40 bg-slate-950/40 backdrop-blur-sm" />
    <Primitive.Content ref={ref} className={cn('fixed left-1/2 top-1/2 z-50 max-h-[90dvh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl outline-none', className)} {...props}>
      {children}<Primitive.Close className="absolute right-4 top-4 rounded-md p-1 text-slate-500 hover:bg-slate-100 focus-visible:ring-2"><X size={18}/><span className="sr-only">关闭</span></Primitive.Close>
    </Primitive.Content>
  </Primitive.Portal>
))
DialogContent.displayName = 'DialogContent'

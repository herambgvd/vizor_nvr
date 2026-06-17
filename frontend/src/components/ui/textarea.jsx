import * as React from "react"

import { cn } from "@/lib/utils"

const Textarea = React.forwardRef(({ className, ...props }, ref) => {
  return (
    <textarea
      className={cn(
        "flex min-h-[60px] w-full rounded-md border border-border bg-card/60 px-3 py-2 text-base text-foreground shadow-sm placeholder:text-muted-foreground hover:border-border focus-visible:outline-none focus-visible:border-[var(--console-accent)] focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring)/0.30)] disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        className
      )}
      ref={ref}
      {...props} />
  );
})
Textarea.displayName = "Textarea"

export { Textarea }

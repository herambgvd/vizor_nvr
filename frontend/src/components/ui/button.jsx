import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva } from "class-variance-authority";

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
        variant: {
          default:
          "bg-[var(--console-accent)] text-[var(--console-accent-foreground)] shadow-[0_0_14px_hsl(var(--ring)/0.20)] hover:brightness-110 active:brightness-90",
        destructive:
          "bg-red-600 text-white shadow-[0_0_18px_rgba(239,68,68,0.22)] hover:bg-red-500 active:bg-red-700",
        outline:
          "border border-red-600/70 bg-transparent text-red-400 shadow-sm hover:bg-red-600/10 hover:border-red-500 hover:text-red-300",
        secondary:
          "bg-card/70 text-foreground border border-border shadow-sm hover:bg-white/[0.10]",
        ghost: "text-[var(--console-muted)] hover:bg-[var(--console-hover)] hover:text-[var(--console-text)]",
        link: "text-[var(--console-accent)] underline-offset-4 hover:underline hover:brightness-125",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-8",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button"
  return (
    <Comp
      className={cn(buttonVariants({ variant, size, className }))}
      ref={ref}
      {...props} />
  );
})
Button.displayName = "Button"

export { Button, buttonVariants }

import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva } from "class-variance-authority";

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
        variant: {
        // Primary = brand green bg + white text, flat (no glow). Reads on both
        // light and dark themes.
        default:
          "bg-[var(--console-accent)] text-white border border-[var(--console-accent)] hover:brightness-110 active:brightness-95",
        destructive:
          "bg-[var(--console-rec)] text-white border border-[var(--console-rec)] hover:brightness-110 active:brightness-95",
        outline:
          "border border-[var(--console-border)] bg-[var(--console-raised)] text-[var(--console-text)] hover:border-[var(--console-muted)]",
        secondary:
          "bg-[var(--console-raised)] text-[var(--console-text)] border border-[var(--console-border)] hover:border-[var(--console-muted)]",
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

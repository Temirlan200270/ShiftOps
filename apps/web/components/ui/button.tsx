import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Button — base interactive control.
 *
 * Sizing: `lg` is the default for HoReCa-thumb ergonomics (per
 * docs/DESIGN_SYSTEM.md). `sm` exists for inline confirmations only;
 * never use it inside the bottom-fixed action area on mobile.
 */
const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap",
    "rounded-md font-medium transition active:scale-[0.98]",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
    "disabled:opacity-50 disabled:pointer-events-none",
  ].join(" "),
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:bg-primary/90 shadow-glow",
        secondary: "bg-elevated text-foreground hover:bg-elevated/80",
        ghost: "bg-transparent text-foreground hover:bg-elevated/60",
        danger: "bg-critical text-critical-foreground hover:bg-critical/90",
        success: "bg-success text-success-foreground hover:bg-success/90",
      },
      size: {
        sm: "h-9 px-3 text-sm",
        md: "h-11 px-4 text-base",
        lg: "h-14 px-6 text-base",
        block: "h-14 px-6 w-full text-base",
      },
    },
    defaultVariants: { variant: "primary", size: "lg" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  function Button({ className, variant, size, asChild = false, ...props }, ref) {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />
    );
  },
);

export { buttonVariants };

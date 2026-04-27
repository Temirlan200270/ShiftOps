import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Card — primary content surface.
 *
 * `accent="critical"` adds a left border accent for tasks that must be
 * completed (per docs/DESIGN_SYSTEM.md §3 — "Critical tasks always get a
 * 4px left border"). This avoids relying on color alone to convey priority,
 * helping the WCAG 1.4.1 (Use of Color) compliance story.
 */
type Accent = "none" | "critical" | "success" | "warning";

const accentStyles: Record<Accent, string> = {
  none: "",
  critical: "border-l-4 border-l-critical",
  success: "border-l-4 border-l-success",
  warning: "border-l-4 border-l-warning",
};

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  accent?: Accent;
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, accent = "none", ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        "rounded-lg bg-surface shadow-card border border-border",
        accentStyles[accent],
        className,
      )}
      {...props}
    />
  );
});

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  function CardHeader({ className, ...props }, ref) {
    return <div ref={ref} className={cn("p-4 pb-2", className)} {...props} />;
  },
);

export const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  function CardTitle({ className, ...props }, ref) {
    return (
      <h3
        ref={ref}
        className={cn("font-semibold leading-tight tracking-tight text-lg", className)}
        {...props}
      />
    );
  },
);

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  function CardContent({ className, ...props }, ref) {
    return <div ref={ref} className={cn("px-4 pb-4 pt-0", className)} {...props} />;
  },
);

export const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  function CardFooter({ className, ...props }, ref) {
    return <div ref={ref} className={cn("flex items-center p-4 pt-2", className)} {...props} />;
  },
);

"use client";

import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as React from "react";

import { cn } from "@/lib/utils";

/* Radix 1.1: Root/Indicator types omit className/children in some @types/react + strict mode resolutions. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- Radix prop types vs DOM (see shadcn/radix issues)
const PRoot = ProgressPrimitive.Root as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const PIndicator = ProgressPrimitive.Indicator as any;

type ProgressProps = {
  className?: string;
  value: number;
  max?: number;
};

export const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(function Progress(
  { className, value, max = 100, ...rest },
  ref,
) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <PRoot
      ref={ref}
      className={cn("relative h-2 w-full overflow-hidden rounded-full bg-elevated", className)}
      value={value}
      max={max}
      {...rest}
    >
      <PIndicator
        className="h-full bg-primary transition-transform duration-500 ease-out"
        style={{ transform: `translateX(-${100 - pct}%)` }}
      />
    </PRoot>
  );
});
Progress.displayName = "Progress";

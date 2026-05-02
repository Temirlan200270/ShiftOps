"use client";

import { ChevronRight, type LucideIcon } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

export function GlassMenu({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div
      className={cn(
        "so-glass divide-y divide-white/[0.06] overflow-hidden rounded-2xl border border-white/[0.06]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function GlassMenuRow({
  icon: Icon,
  title,
  subtitle,
  onClick,
  className,
}: {
  icon: LucideIcon;
  title: string;
  subtitle?: string;
  onClick: () => void;
  className?: string;
}): React.JSX.Element {
  return (
    <button
      type="button"
      className={cn(
        "touch-target flex w-full min-h-12 items-center gap-3 px-4 py-4 text-left active:bg-white/[0.04]",
        className,
      )}
      onClick={onClick}
    >
      <Icon className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-foreground">{title}</span>
        {subtitle ? (
          <span className="mt-0.5 block text-[11px] text-muted-foreground">{subtitle}</span>
        ) : null}
      </span>
      <ChevronRight className="h-5 w-5 shrink-0 text-white/15" aria-hidden />
    </button>
  );
}

"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Toast — global feedback for ephemeral events (saved, retrying, error).
 * Important: in TWA we keep duration short (3s) and use status colors so
 * a busy bartender catches it without reading.
 *
 * Radix 1.1 + strict TS: use `as any` on primitives so className/children match DOM usage
 * (same pattern as components/ui/sheet.tsx).
 */
const ToastProvider = ToastPrimitive.Provider;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const TViewport = ToastPrimitive.Viewport as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const TRoot = ToastPrimitive.Root as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const TClose = ToastPrimitive.Close as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const TTitle = ToastPrimitive.Title as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const TDescription = ToastPrimitive.Description as any;

type ToastViewportProps = Omit<React.ComponentPropsWithRef<typeof TViewport>, "className"> & {
  className?: string;
};

const ToastViewport = React.forwardRef<HTMLOListElement, ToastViewportProps>(function ToastViewport(
  { className, ...props },
  ref,
) {
    return (
      <TViewport
        ref={ref}
        className={cn(
          "fixed top-2 inset-x-0 z-[100] flex flex-col gap-2 p-2 max-w-md mx-auto outline-none",
          className,
        )}
        {...props}
      />
    );
});

type ToastVariant = "default" | "success" | "warning" | "critical";

const toastVariantClasses: Record<ToastVariant, string> = {
  default: "bg-elevated text-foreground border-border",
  success: "bg-success/15 text-success border-success/30",
  warning: "bg-warning/15 text-warning border-warning/30",
  critical: "bg-critical/15 text-critical border-critical/30",
};

type ToastProps = Omit<React.ComponentPropsWithRef<typeof TRoot>, "className" | "children" | "variant"> & {
  className?: string;
  children?: React.ReactNode;
  variant?: ToastVariant;
};

const Toast = React.forwardRef<HTMLLIElement, ToastProps>(function Toast(
  { className, variant = "default", ...props },
  ref,
) {
  // TRoot is `as any`, so `variant` in merged props is inferred as `any` — narrow for the palette map
  const tone: ToastVariant = variant;
  return (
    <TRoot
      ref={ref}
      className={cn(
        "relative grid grid-cols-[1fr_auto] items-start gap-3 rounded-md border p-3 shadow-card",
        "data-[state=open]:animate-in data-[state=open]:fade-in-0",
        "data-[state=closed]:animate-out data-[state=closed]:fade-out-80",
        toastVariantClasses[tone],
        className,
      )}
      {...props}
    />
  );
});

const ToastTitle = TTitle;
const ToastDescription = TDescription;
type ToastCloseProps = Omit<React.ComponentPropsWithRef<typeof TClose>, "className"> & {
  className?: string;
};
const ToastClose = React.forwardRef<HTMLButtonElement, ToastCloseProps>(function ToastClose(
  { className, ...props },
  ref,
) {
    return (
      <TClose
        ref={ref}
        className={cn("text-muted-foreground hover:text-foreground", className)}
        {...props}
      >
        <X className="h-4 w-4" />
      </TClose>
    );
});

export { Toast, ToastClose, ToastDescription, ToastProvider, ToastTitle, ToastViewport };

"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Toast — global feedback for ephemeral events (saved, retrying, error).
 * Important: in TWA we keep duration short (3s) and use status colors so
 * a busy bartender catches it without reading.
 */
const ToastProvider = ToastPrimitive.Provider;

const ToastViewport = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Viewport>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Viewport>
>(function ToastViewport({ className, ...props }, ref) {
  return (
    <ToastPrimitive.Viewport
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

interface ToastProps extends React.ComponentPropsWithoutRef<typeof ToastPrimitive.Root> {
  variant?: ToastVariant;
}

const Toast = React.forwardRef<React.ElementRef<typeof ToastPrimitive.Root>, ToastProps>(
  function Toast({ className, variant = "default", ...props }, ref) {
    return (
      <ToastPrimitive.Root
        ref={ref}
        className={cn(
          "relative grid grid-cols-[1fr_auto] items-start gap-3 rounded-md border p-3 shadow-card",
          "data-[state=open]:animate-in data-[state=open]:fade-in-0",
          "data-[state=closed]:animate-out data-[state=closed]:fade-out-80",
          toastVariantClasses[variant],
          className,
        )}
        {...props}
      />
    );
  },
);

const ToastTitle = ToastPrimitive.Title;
const ToastDescription = ToastPrimitive.Description;
const ToastClose = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Close>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Close>
>(function ToastClose({ className, ...props }, ref) {
  return (
    <ToastPrimitive.Close
      ref={ref}
      className={cn("text-muted-foreground hover:text-foreground", className)}
      {...props}
    >
      <X className="h-4 w-4" />
    </ToastPrimitive.Close>
  );
});

export { Toast, ToastClose, ToastDescription, ToastProvider, ToastTitle, ToastViewport };

"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Sheet — bottom drawer used for forms (waiver request, comment, photo
 * preview). On mobile we always slide from the bottom because that's where
 * the user's thumb is. We deliberately do NOT support `side="right"` etc.
 * for V0 to keep our component surface tiny.
 */
export const Sheet = DialogPrimitive.Root;
/* Radix: Trigger/Children typings + strict TS — allow asChild + children. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const SheetTrigger = DialogPrimitive.Trigger as any;
export const SheetClose = DialogPrimitive.Close;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const DOverlay = DialogPrimitive.Overlay as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const DContent = DialogPrimitive.Content as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const DTitle = DialogPrimitive.Title as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const DDescription = DialogPrimitive.Description as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const DClose = DialogPrimitive.Close as any;

type SheetOverlayProps = Omit<React.ComponentPropsWithRef<typeof DOverlay>, "className"> & {
  className?: string;
};

const SheetOverlay = React.forwardRef<HTMLDivElement, SheetOverlayProps>(function SheetOverlay(
  { className, ...props },
  ref,
) {
  return (
    <DOverlay
      ref={ref}
      className={cn(
        "fixed inset-0 z-50 bg-black/60 backdrop-blur-sm",
        "data-[state=open]:animate-in data-[state=closed]:animate-out",
        "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
        className,
      )}
      {...props}
    />
  );
});

type SheetContentProps = {
  className?: string;
  children?: React.ReactNode;
  title?: string;
};

export const SheetContent = React.forwardRef<HTMLDivElement, SheetContentProps>(function SheetContent(
  { className, children, title, ...props },
  ref,
) {
  return (
    <DialogPrimitive.Portal>
      <SheetOverlay />
      <DContent
        ref={ref}
        className={cn(
          "fixed inset-x-0 bottom-0 z-50 rounded-t-lg bg-surface p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-card",
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          "data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
          "duration-200",
          className,
        )}
        {...props}
      >
        <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-muted" aria-hidden />
        {title ? <DTitle className="text-lg font-semibold mb-2">{title}</DTitle> : null}
        <DDescription className="sr-only">{title ?? "Sheet"}</DDescription>
        {children}
        <DClose
          className="absolute right-4 top-4 rounded-sm p-1 text-muted-foreground hover:bg-elevated"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </DClose>
      </DContent>
    </DialogPrimitive.Portal>
  );
});

"use client";

/**
 * App Router error boundary — avoids a blank white screen if a child crashes.
 * Next.js will render this while keeping the root layout shell.
 */
export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-6 text-center">
      <p className="font-medium text-critical mb-2">ShiftOps</p>
      <p className="text-sm text-muted-foreground mb-4 max-w-xs">
        {error.message || "Unexpected error"}
      </p>
      <button
        type="button"
        className="rounded-md border border-border bg-elevated px-4 py-2 text-sm"
        onClick={() => {
          reset();
        }}
      >
        Try again
      </button>
    </main>
  );
}

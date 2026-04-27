"use client";

/**
 * Bulk schedule importer (CSV) — admin & owner only.
 *
 * UX flow
 * -------
 * 1. Pick a file from disk.
 * 2. Press "Validate (dry run)" — server parses, validates, returns
 *    per-row errors. Nothing is written yet.
 * 3. If errors == 0, "Import for real" becomes enabled. Pressing it
 *    re-uploads the same file with ``dry_run=false`` and the server
 *    inserts shifts in one transaction.
 *
 * Why two clicks: HoReCa rotas are often produced in Excel by a manager
 * who has no idea the file is malformed. A separate dry-run step lets
 * us surface "operator @ivan typed wrong, line 12" *before* a hundred
 * shifts get half-created. Backend already wraps the real import in a
 * transaction, but the dry-run UX is faster than waiting for an
 * unintuitive partial-failure rollback.
 *
 * Error code mapping
 * ------------------
 * The server returns a stable ``code`` per row error. We map it to a
 * localised string via ``analytics.errorCodes.<code>`` keys. Unknown
 * codes fall back to the server-provided ``message``, which is
 * deterministic English from the use case but still informative.
 */

import { ArrowLeft, FileCheck2, FileWarning, FileX2, Upload, UploadCloud } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { importSchedule, type ImportReport } from "@/lib/api/schedule";
import { toast } from "@/lib/stores/toast-store";

interface CsvImportScreenProps {
  onBack: () => void;
}

const ACCEPTED_MIMES = [
  "text/csv",
  "application/vnd.ms-excel",
  "application/csv",
  "text/plain",
];

const _MAX_BYTES = 256 * 1024;

const KNOWN_ERROR_CODES: ReadonlySet<string> = new Set([
  "invalid_date",
  "invalid_time",
  "unknown_location",
  "unknown_template",
  "unknown_operator",
  "empty_window",
  "past_window",
  "duplicate_shift",
  "missing_columns",
  "missing_header",
  "invalid_encoding",
  "too_many_rows",
  "file_too_large",
]);

export function CsvImportScreen({ onBack }: CsvImportScreenProps): React.JSX.Element {
  const tCsv = useTranslations("csvImport");
  const tErrCode = useTranslations("csvImport.errorCodes");
  const tErr = useTranslations("errors");

  const inputRef = React.useRef<HTMLInputElement>(null);
  const [file, setFile] = React.useState<File | null>(null);
  const [report, setReport] = React.useState<ImportReport | null>(null);
  const [busy, setBusy] = React.useState<"idle" | "validating" | "applying">("idle");

  const onPick = (): void => inputRef.current?.click();

  const onFile = (evt: React.ChangeEvent<HTMLInputElement>): void => {
    const picked = evt.target.files?.[0] ?? null;
    if (picked === null) return;
    if (picked.size > _MAX_BYTES) {
      toast({
        variant: "critical",
        title: tCsv("errorCodes.file_too_large"),
        description: picked.name,
      });
      return;
    }
    setFile(picked);
    // Wipe any prior report so the user can't accidentally apply an
    // import that doesn't match the freshly picked file.
    setReport(null);
  };

  const validate = React.useCallback(async () => {
    if (!file) return;
    setBusy("validating");
    const result = await importSchedule(file, true);
    setBusy("idle");
    if (!result.ok) {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseTopLevel(result.code, result.message, tErrCode),
      });
      return;
    }
    setReport(result.data);
  }, [file, tErr, tErrCode]);

  const apply = React.useCallback(async () => {
    if (!file) return;
    if (!report || report.errors.length > 0) return;
    setBusy("applying");
    const result = await importSchedule(file, false);
    setBusy("idle");
    if (!result.ok) {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseTopLevel(result.code, result.message, tErrCode),
      });
      return;
    }
    setReport(result.data);
    toast({
      variant: "success",
      title: tCsv("createdRows", { count: result.data.created.length }),
    });
  }, [file, report, tErr, tCsv, tErrCode]);

  const hasErrors = (report?.errors.length ?? 0) > 0;

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{tCsv("title")}</h1>
          <p className="text-xs text-muted-foreground">{tCsv("subtitle")}</p>
        </div>
      </header>

      <Card className="mb-3">
        <CardContent className="p-4">
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_MIMES.join(",") + ",.csv"}
            className="hidden"
            onChange={onFile}
          />
          <Button variant="secondary" size="block" onClick={onPick} disabled={busy !== "idle"}>
            <UploadCloud className="size-5" />
            {tCsv("pickFile")}
          </Button>
          <p className="text-xs text-muted-foreground mt-2">
            {file ? tCsv("selectedFile", { name: file.name }) : tCsv("noFile")}
          </p>
          <p className="text-[10px] text-muted-foreground mt-2">{tCsv("format")}</p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-2 mb-4">
        <Button
          variant="secondary"
          onClick={() => void validate()}
          disabled={!file || busy !== "idle"}
        >
          {busy === "validating" ? tCsv("validating") : tCsv("dryRunCta")}
        </Button>
        <Button
          variant="primary"
          onClick={() => void apply()}
          disabled={!file || !report || hasErrors || busy !== "idle"}
        >
          <Upload className="size-4" />
          {busy === "applying" ? tCsv("applying") : tCsv("applyCta")}
        </Button>
      </div>

      {!report && file ? (
        <p className="text-xs text-muted-foreground">{tCsv("needValidationFirst")}</p>
      ) : null}

      {report ? (
        <>
          <div className="grid grid-cols-3 gap-2 mb-3">
            <Card>
              <CardContent className="p-3 text-center">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  {tCsv("labels.totalRows")}
                </p>
                <p className="text-xl font-semibold tabular-nums mt-1">{report.totalRows}</p>
              </CardContent>
            </Card>
            <Card accent={report.errors.length > 0 ? "warning" : "none"}>
              <CardContent className="p-3 text-center">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center justify-center gap-1">
                  <FileCheck2 className="size-3 text-success" />
                  {report.dryRun ? tCsv("labels.validated") : tCsv("labels.created")}
                </p>
                <p className="text-xl font-semibold tabular-nums mt-1 text-success">
                  {report.dryRun ? report.skipped.length : report.created.length}
                </p>
              </CardContent>
            </Card>
            <Card accent={hasErrors ? "critical" : "none"}>
              <CardContent className="p-3 text-center">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center justify-center gap-1">
                  <FileX2 className="size-3 text-critical" />
                  {tCsv("labels.errors")}
                </p>
                <p
                  className={`text-xl font-semibold tabular-nums mt-1 ${
                    hasErrors ? "text-critical" : "text-foreground"
                  }`}
                >
                  {report.errors.length}
                </p>
              </CardContent>
            </Card>
          </div>

          {hasErrors ? (
            <Card accent="critical" className="mb-3">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <FileWarning className="size-4 text-critical" />
                  {tCsv("errorsTitle")}
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <ul className="space-y-2">
                  {report.errors.map((err, idx) => (
                    <li
                      key={`${err.lineNo}-${idx}`}
                      className="rounded-md border border-critical/30 bg-critical/5 p-2"
                    >
                      <p className="text-xs font-medium">
                        #{err.lineNo} · {localiseError(err.code, err.message, tErrCode)}
                      </p>
                      {Object.keys(err.columns).length > 0 ? (
                        <p className="text-[11px] text-muted-foreground mt-1 truncate">
                          {Object.entries(err.columns)
                            .filter(([, v]) => Boolean(v))
                            .map(([k, v]) => `${k}=${v}`)
                            .join("  ·  ")}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          {(report.created.length > 0 || report.skipped.length > 0) && !hasErrors ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{tCsv("previewTitle")}</CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <ul className="space-y-2">
                  {(report.dryRun ? report.skipped : report.created).slice(0, 50).map((row) => (
                    <li
                      key={`${row.lineNo}-${row.shiftId ?? "dry"}`}
                      className="text-xs flex items-center gap-2"
                    >
                      <span className="text-muted-foreground tabular-nums w-7 text-right">
                        #{row.lineNo}
                      </span>
                      <span className="tabular-nums">
                        {row.date} · {row.timeStart}–{row.timeEnd}
                      </span>
                      <span className="text-muted-foreground truncate">
                        · {row.location} · {row.template} · {row.operator}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}
    </main>
  );
}

function localiseError(
  code: string,
  fallback: string,
  t: (key: string) => string,
): string {
  if (KNOWN_ERROR_CODES.has(code)) return t(code);
  return fallback || t("fallback");
}

function localiseTopLevel(
  code: string,
  fallback: string,
  t: (key: string) => string,
): string {
  // The schedule endpoint returns ``HTTP 400`` with detail
  // ``"<code>:<message>"`` for use-case Failures. Strip the prefix.
  const cleanCode = code.includes(":") ? code.split(":")[0] : code;
  if (KNOWN_ERROR_CODES.has(cleanCode)) return t(cleanCode);
  return fallback;
}

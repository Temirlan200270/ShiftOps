"use client";

/**
 * Schedule (CSV import) admin client.
 *
 * The backend accepts a multipart upload and a ``dry_run`` query
 * parameter. We always run the dry run first so the admin UI can show
 * a preview/error report before the apply step writes shifts to the
 * database. See ``apps/api/shiftops_api/api/v1/schedule.py`` for the
 * server-side contract.
 */

import { api, type ApiResult } from "@/lib/api/client";

export interface ImportRowResult {
  lineNo: number;
  date: string;
  timeStart: string;
  timeEnd: string;
  location: string;
  template: string;
  operator: string;
  shiftId: string | null;
}

export interface ImportRowError {
  lineNo: number;
  code: string;
  message: string;
  columns: Record<string, string>;
}

export interface ImportReport {
  totalRows: number;
  created: ImportRowResult[];
  skipped: ImportRowResult[];
  errors: ImportRowError[];
  dryRun: boolean;
}

interface RowResultDTO {
  line_no: number;
  date: string;
  time_start: string;
  time_end: string;
  location: string;
  template: string;
  operator: string;
  shift_id: string | null;
}

interface RowErrorDTO {
  line_no: number;
  code: string;
  message: string;
  columns: Record<string, string>;
}

interface ReportDTO {
  total_rows: number;
  created: RowResultDTO[];
  skipped: RowResultDTO[];
  errors: RowErrorDTO[];
  dry_run: boolean;
}

function fromRowResult(dto: RowResultDTO): ImportRowResult {
  return {
    lineNo: dto.line_no,
    date: dto.date,
    timeStart: dto.time_start,
    timeEnd: dto.time_end,
    location: dto.location,
    template: dto.template,
    operator: dto.operator,
    shiftId: dto.shift_id,
  };
}

function fromReport(dto: ReportDTO): ImportReport {
  return {
    totalRows: dto.total_rows,
    created: dto.created.map(fromRowResult),
    skipped: dto.skipped.map(fromRowResult),
    errors: dto.errors.map((e) => ({
      lineNo: e.line_no,
      code: e.code,
      message: e.message,
      columns: e.columns,
    })),
    dryRun: dto.dry_run,
  };
}

export async function importSchedule(
  file: File,
  dryRun: boolean,
): Promise<ApiResult<ImportReport>> {
  const form = new FormData();
  form.append("file", file);
  const result = await api.postForm<ReportDTO>(
    `/v1/schedule/import?dry_run=${dryRun ? "true" : "false"}`,
    form,
  );
  if (!result.ok) return result;
  return { ok: true, status: result.status, data: fromReport(result.data) };
}

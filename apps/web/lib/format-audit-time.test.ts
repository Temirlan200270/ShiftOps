import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { actorInitials, formatAuditTimestamp } from "./format-audit-time";

describe("formatAuditTimestamp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-01T12:00:00.000Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("uses today label when calendar day matches in Asia/Almaty", () => {
    const labels = {
      today: (time: string) => `TODAY:${time}`,
      yesterday: (time: string) => `YEST:${time}`,
    };
    const s = formatAuditTimestamp("2026-05-01T07:00:00.000Z", "ru", labels, "Asia/Almaty");
    expect(s.startsWith("TODAY:")).toBe(true);
  });
});

describe("actorInitials", () => {
  it("uses two letters for two-word names", () => {
    expect(actorInitials("Темирлан Рахимжанов")).toBe("ТР");
  });

  it("uses up to two chars for single token", () => {
    expect(actorInitials("Temir73")).toBe("TE");
  });
});

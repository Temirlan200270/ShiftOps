import { describe, expect, it } from "vitest";

import { getCapabilities } from "./capabilities";

describe("getCapabilities", () => {
  it("gives operator no admin modules without god mode", () => {
    const c = getCapabilities({
      role: "operator",
      tgUserId: 12345,
      superAdminTgId: "999",
    });
    expect(c.canAccessAdminModules).toBe(false);
    expect(c.canManageTeamMembers).toBe(false);
    expect(c.isGodMode).toBe(false);
  });

  it("enables full admin UI for operator when tg id matches super admin env", () => {
    const c = getCapabilities({
      role: "operator",
      tgUserId: 12345,
      superAdminTgId: "12345",
    });
    expect(c.isGodMode).toBe(true);
    expect(c.canAccessAdminModules).toBe(true);
    expect(c.canManageTeamMembers).toBe(true);
  });

  it("trims super admin env and compares stringified tg id", () => {
    const c = getCapabilities({
      role: "bartender",
      tgUserId: 42,
      superAdminTgId: "  42  ",
    });
    expect(c.isGodMode).toBe(true);
    expect(c.canAccessAdminModules).toBe(true);
  });

  it("treats owner as admin modules and team manager", () => {
    const c = getCapabilities({
      role: "owner",
      tgUserId: 1,
      superAdminTgId: null,
    });
    expect(c.canAccessAdminModules).toBe(true);
    expect(c.canManageTeamMembers).toBe(true);
    expect(c.isOrgAdmin).toBe(true);
  });

  it("allows admin to open admin modules but not manage team members", () => {
    const c = getCapabilities({
      role: "admin",
      tgUserId: 1,
      superAdminTgId: undefined,
    });
    expect(c.canAccessAdminModules).toBe(true);
    expect(c.canViewTeam).toBe(true);
    expect(c.canManageTeamMembers).toBe(false);
  });

  it("does not set god mode when tgUserId is null", () => {
    const c = getCapabilities({
      role: "operator",
      tgUserId: null,
      superAdminTgId: "123",
    });
    expect(c.isGodMode).toBe(false);
  });
});

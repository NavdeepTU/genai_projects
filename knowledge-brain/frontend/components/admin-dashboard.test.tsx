import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AdminAuditEntry, Tenant } from "@/lib/api";
import { AdminDashboard } from "@/components/admin-dashboard";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, createTenant: vi.fn() };
});

function makeAuditEntry(overrides: Partial<AdminAuditEntry> = {}): AdminAuditEntry {
  return {
    timestamp: "2026-01-01T00:00:00Z",
    tenant_id: "tenant-1",
    user_id: "user-1",
    action: "query_made",
    resource_type: "query",
    resource_id: "corr-1",
    ...overrides,
  };
}

function makeTenant(overrides: Partial<Tenant> = {}): Tenant {
  return {
    id: "tenant-1",
    name: "Microsoft",
    ...overrides,
  };
}

describe("AdminDashboard", () => {
  it("shows the audit log section by default", () => {
    render(<AdminDashboard auditEntries={[makeAuditEntry({ user_id: "user-42" })]} tenants={[makeTenant()]} />);

    expect(screen.getByText("Audit log (most recent, all users)")).toBeInTheDocument();
    expect(screen.getByText(/user-42/)).toBeInTheDocument();
    expect(screen.queryByText("Registered companies")).not.toBeInTheDocument();
  });

  it("switches to the tenant management section without showing the audit log", async () => {
    const user = userEvent.setup();
    render(
      <AdminDashboard auditEntries={[makeAuditEntry()]} tenants={[makeTenant({ name: "Acme Corp" })]} />,
    );

    await user.click(screen.getByRole("button", { name: /tenant management/i }));

    expect(screen.getByText("Registered companies")).toBeInTheDocument();
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.queryByText("Audit log (most recent, all users)")).not.toBeInTheDocument();
  });

  it("shows an empty-state message when no companies are registered yet", async () => {
    const user = userEvent.setup();
    render(<AdminDashboard auditEntries={[]} tenants={[]} />);

    await user.click(screen.getByRole("button", { name: /tenant management/i }));

    expect(
      screen.getByText("No companies registered yet — use the form above to register the first one."),
    ).toBeInTheDocument();
  });

  it("shows an empty-state message instead of an empty audit log", () => {
    render(<AdminDashboard auditEntries={[]} tenants={[]} />);

    expect(screen.getByText("No audit entries yet.")).toBeInTheDocument();
  });
});

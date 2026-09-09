import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AdminAuditEntry, ReviewQueueItem, Tenant } from "@/lib/api";
import { AdminDashboard } from "@/components/admin-dashboard";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, createTenant: vi.fn(), approveDocument: vi.fn(), rejectDocument: vi.fn() };
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

function makeReviewQueueItem(overrides: Partial<ReviewQueueItem> = {}): ReviewQueueItem {
  return {
    id: "doc-1",
    filename: "flagged.txt",
    uploaded_at: "2026-01-01T00:00:00Z",
    uploaded_by_email: "uploader@example.com",
    has_file: true,
    ...overrides,
  };
}

function renderDashboard(overrides: {
  auditEntries?: AdminAuditEntry[];
  reviewQueue?: ReviewQueueItem[];
  tenants?: Tenant[];
} = {}) {
  return render(
    <AdminDashboard
      auditEntries={overrides.auditEntries ?? []}
      reviewQueue={overrides.reviewQueue ?? []}
      tenants={overrides.tenants ?? []}
    />,
  );
}

describe("AdminDashboard", () => {
  it("shows the audit log section by default", () => {
    renderDashboard({ auditEntries: [makeAuditEntry({ user_id: "user-42" })], tenants: [makeTenant()] });

    expect(screen.getByText("Audit log (most recent, all users)")).toBeInTheDocument();
    expect(screen.getByText(/user-42/)).toBeInTheDocument();
    expect(screen.queryByText("Registered companies")).not.toBeInTheDocument();
  });

  it("switches to the tenant management section without showing the audit log", async () => {
    const user = userEvent.setup();
    renderDashboard({ auditEntries: [makeAuditEntry()], tenants: [makeTenant({ name: "Acme Corp" })] });

    await user.click(screen.getByRole("button", { name: /tenant management/i }));

    expect(screen.getByText("Registered companies")).toBeInTheDocument();
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.queryByText("Audit log (most recent, all users)")).not.toBeInTheDocument();
  });

  it("shows an empty-state message when no companies are registered yet", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: /tenant management/i }));

    expect(
      screen.getByText("No companies registered yet — use the form above to register the first one."),
    ).toBeInTheDocument();
  });

  it("shows an empty-state message instead of an empty audit log", () => {
    renderDashboard();

    expect(screen.getByText("No audit entries yet.")).toBeInTheDocument();
  });

  it("switches to the review queue section and shows a flagged document", async () => {
    const user = userEvent.setup();
    renderDashboard({ reviewQueue: [makeReviewQueueItem({ filename: "resume.pdf" })] });

    await user.click(screen.getByRole("button", { name: /review queue/i }));

    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(screen.getByText(/uploaded by uploader@example.com/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("shows an empty-state message when nothing is awaiting review", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: /review queue/i }));

    expect(screen.getByText("Nothing waiting on a review decision right now.")).toBeInTheDocument();
  });

  it("removes a document from the queue once it's approved", async () => {
    const { approveDocument } = await import("@/lib/api");
    vi.mocked(approveDocument).mockResolvedValue({
      id: "doc-1",
      status: "processing",
      processing_stage: "extracting",
      pii_detected: true,
      failure_reason: null,
      correlation_id: "c1",
    });

    const user = userEvent.setup();
    renderDashboard({ reviewQueue: [makeReviewQueueItem()] });

    await user.click(screen.getByRole("button", { name: /review queue/i }));
    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("Nothing waiting on a review decision right now.")).toBeInTheDocument();
    expect(approveDocument).toHaveBeenCalledWith("doc-1");
  });
});

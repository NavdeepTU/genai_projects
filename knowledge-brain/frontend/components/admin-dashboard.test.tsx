import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AdminAuditEntry, Domain, ReviewQueueItem, Tenant } from "@/lib/api";
import { AdminDashboard } from "@/components/admin-dashboard";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createTenant: vi.fn(),
    approveDocument: vi.fn(),
    rejectDocument: vi.fn(),
    createDomain: vi.fn(),
    renameDomain: vi.fn(),
    mergeDomain: vi.fn(),
    deleteDomain: vi.fn(),
  };
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

function makeDomain(overrides: Partial<Domain> = {}): Domain {
  return {
    id: "domain-1",
    name: "HR",
    ...overrides,
  };
}

function renderDashboard(overrides: {
  auditEntries?: AdminAuditEntry[];
  reviewQueue?: ReviewQueueItem[];
  tenants?: Tenant[];
  domains?: Domain[];
} = {}) {
  return render(
    <AdminDashboard
      auditEntries={overrides.auditEntries ?? []}
      reviewQueue={overrides.reviewQueue ?? []}
      tenants={overrides.tenants ?? []}
      domains={overrides.domains ?? []}
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

  it("switches to the domains section and shows a registered domain", async () => {
    const user = userEvent.setup();
    renderDashboard({ domains: [makeDomain({ name: "Finance" })] });

    await user.click(screen.getByRole("button", { name: /^domains$/i }));

    expect(screen.getByText("Finance")).toBeInTheDocument();
    expect(screen.queryByText("Audit log (most recent, all users)")).not.toBeInTheDocument();
  });

  it("shows an empty-state message when no domains exist yet", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: /^domains$/i }));

    expect(screen.getByText(/no domains yet/i)).toBeInTheDocument();
  });

  it("adds a newly created domain to the list", async () => {
    const { createDomain } = await import("@/lib/api");
    vi.mocked(createDomain).mockResolvedValue({ id: "domain-new", name: "Legal" });

    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: /^domains$/i }));
    await user.type(screen.getByLabelText("Domain name"), "Legal");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Legal")).toBeInTheDocument();
    expect(createDomain).toHaveBeenCalledWith("Legal");
  });

  it("renames a domain in place", async () => {
    const { renameDomain } = await import("@/lib/api");
    vi.mocked(renameDomain).mockResolvedValue({ id: "domain-1", name: "HR" });

    const user = userEvent.setup();
    renderDashboard({ domains: [makeDomain({ name: "Human Resources" })] });

    await user.click(screen.getByRole("button", { name: /^domains$/i }));
    await user.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByLabelText("Rename Human Resources");
    await user.clear(input);
    await user.type(input, "HR");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("HR")).toBeInTheDocument();
    expect(renameDomain).toHaveBeenCalledWith("domain-1", "HR");
  });

  it("removes both domains from the list and shows only the merge target after a merge", async () => {
    const { mergeDomain } = await import("@/lib/api");
    const target = makeDomain({ id: "domain-2", name: "HR" });
    vi.mocked(mergeDomain).mockResolvedValue([target]);

    const user = userEvent.setup();
    renderDashboard({
      domains: [makeDomain({ id: "domain-1", name: "Human Resources" }), target],
    });

    await user.click(screen.getByRole("button", { name: /^domains$/i }));
    const sourceRow = screen.getByText("Human Resources", { selector: "span" }).closest("li");
    if (!sourceRow) throw new Error("source row not found");
    await user.selectOptions(
      within(sourceRow).getByRole("combobox", { name: "Merge Human Resources into" }),
      "domain-2",
    );
    await user.click(within(sourceRow).getByRole("button", { name: "Merge" }));

    await waitFor(() => expect(mergeDomain).toHaveBeenCalledWith("domain-1", "domain-2"));
    expect(screen.queryByText("Human Resources")).not.toBeInTheDocument();
    expect(screen.getByText("HR")).toBeInTheDocument();
  });

  it("removes a domain from the list once deleted", async () => {
    const { deleteDomain } = await import("@/lib/api");
    vi.mocked(deleteDomain).mockResolvedValue(undefined);

    const user = userEvent.setup();
    renderDashboard({ domains: [makeDomain({ name: "HR" })] });

    await user.click(screen.getByRole("button", { name: /^domains$/i }));
    await user.click(screen.getByRole("button", { name: "Delete HR" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByText(/no domains yet/i)).toBeInTheDocument();
    expect(deleteDomain).toHaveBeenCalledWith("domain-1");
  });
});

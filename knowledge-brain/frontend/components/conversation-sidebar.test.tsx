import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/query/conv-1",
}));

import type { ConversationListItem } from "@/lib/api";
import { ConversationSidebar } from "@/components/conversation-sidebar";

function makeConversation(overrides: Partial<ConversationListItem> = {}): ConversationListItem {
  return {
    id: "conv-1",
    title: "What's our vacation policy?",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ConversationSidebar", () => {
  it("renders a New conversation link", () => {
    render(
      <ConversationSidebar conversations={[]}>
        <div>content</div>
      </ConversationSidebar>,
    );

    expect(screen.getAllByText("New conversation").length).toBeGreaterThan(0);
  });

  it("shows an empty state when there are no conversations", () => {
    render(
      <ConversationSidebar conversations={[]}>
        <div>content</div>
      </ConversationSidebar>,
    );

    expect(screen.getAllByText(/No conversations yet/).length).toBeGreaterThan(0);
  });

  it("lists each conversation's title", () => {
    render(
      <ConversationSidebar
        conversations={[
          makeConversation({ id: "conv-1", title: "Vacation policy" }),
          makeConversation({ id: "conv-2", title: "Expense reimbursement" }),
        ]}
      >
        <div>content</div>
      </ConversationSidebar>,
    );

    expect(screen.getAllByText("Vacation policy").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Expense reimbursement").length).toBeGreaterThan(0);
  });

  it("renders the page content passed as children", () => {
    render(
      <ConversationSidebar conversations={[]}>
        <div>the actual chat area</div>
      </ConversationSidebar>,
    );

    expect(screen.getByText("the actual chat area")).toBeInTheDocument();
  });
});

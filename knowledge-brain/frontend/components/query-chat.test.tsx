import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

import type { Turn } from "@/lib/api";
import { QueryChat } from "@/components/query-chat";

function makeStoredTurn(overrides: Partial<Turn> = {}): Turn {
  return {
    id: "turn-1",
    raw_question: "How many vacation days do I get?",
    answer: "20 days per year.",
    sources: [],
    confidence: 0.9,
    domains_used: ["HR"],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function mockFetchOk(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
  });
}

describe("QueryChat resuming a conversation", () => {
  it("renders turns passed in from an existing conversation", () => {
    render(
      <QueryChat
        initialConversationId="conv-1"
        initialTurns={[makeStoredTurn()]}
      />,
    );

    expect(screen.getByText("How many vacation days do I get?")).toBeInTheDocument();
    expect(screen.getByText("20 days per year.")).toBeInTheDocument();
  });

  it("shows the empty state when starting a brand-new conversation", () => {
    render(<QueryChat initialConversationId={null} initialTurns={[]} />);

    expect(screen.getByText("Ask a question")).toBeInTheDocument();
  });

  it("sends the existing conversation_id when asking a follow-up in a resumed conversation", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchOk({
      answer: "5 days.",
      sources: [],
      confidence: 0.8,
      conversation_id: "conv-1",
      correlation_id: "corr-2",
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <QueryChat
        initialConversationId="conv-1"
        initialTurns={[makeStoredTurn()]}
      />,
    );

    await user.type(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      "What about carryover?",
    );
    await user.click(screen.getByRole("button", { name: "" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body).toEqual({ question: "What about carryover?", conversation_id: "conv-1" });

    vi.unstubAllGlobals();
  });

  it("sends conversation_id null on the first question of a brand-new conversation", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchOk({
      answer: "20 days per year.",
      sources: [],
      confidence: 0.9,
      conversation_id: "new-conv",
      correlation_id: "corr-1",
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<QueryChat initialConversationId={null} initialTurns={[]} />);

    await user.type(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      "How many vacation days do I get?",
    );
    await user.click(screen.getByRole("button", { name: "" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body).toEqual({ question: "How many vacation days do I get?", conversation_id: null });

    vi.unstubAllGlobals();
  });
});

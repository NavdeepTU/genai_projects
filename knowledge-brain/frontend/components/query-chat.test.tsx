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
    condensed_question: "How many vacation days do I get?",
    answer: "20 days per year.",
    sources: [],
    confidence: 0.9,
    domains_used: ["HR"],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function doneFrame(overrides: Record<string, unknown> = {}): string {
  return sseFrame("done", {
    answer: "5 days.",
    blocked: false,
    block_reason: null,
    sources: [],
    confidence: 0.8,
    domains_used: ["HR"],
    partial: false,
    conversation_id: "conv-1",
    correlation_id: "corr-2",
    ...overrides,
  });
}

// Delivers the whole SSE body as one chunk — streamQuery's own frame-splitting
// loop is what's under test elsewhere; here we only care what the component
// does with the events it yields.
function mockFetchStream(sseBody: string) {
  const bytes = new TextEncoder().encode(sseBody);
  let sent = false;
  const reader = {
    read: async () => {
      if (sent) return { done: true, value: undefined };
      sent = true;
      return { done: false, value: bytes };
    },
  };
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: { getReader: () => reader },
  });
}

// Delivers frames one `read()` call at a time, so a test can assert on
// intermediate UI state between chunks arriving.
function mockFetchStreamedFrames(frames: string[]) {
  const bytesQueue = frames.map((frame) => new TextEncoder().encode(frame));
  let index = 0;
  const reader = {
    read: async () => {
      if (index >= bytesQueue.length) return { done: true, value: undefined };
      return { done: false, value: bytesQueue[index++] };
    },
  };
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: { getReader: () => reader },
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
    const fetchMock = mockFetchStream(doneFrame());
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

    expect(fetchMock.mock.calls[0][0]).toBe("/api/query/stream");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body).toEqual({ question: "What about carryover?", conversation_id: "conv-1" });

    await waitFor(() => expect(screen.getByText("5 days.")).toBeInTheDocument());

    vi.unstubAllGlobals();
  });

  it("sends conversation_id null on the first question of a brand-new conversation", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchStream(doneFrame({ conversation_id: "new-conv" }));
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

    await waitFor(() => expect(screen.getByText("5 days.")).toBeInTheDocument());

    vi.unstubAllGlobals();
  });

  it("renders each streamed chunk as it arrives, before the final done event", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchStreamedFrames([
      sseFrame("chunk", { text: "Paris is " }),
      sseFrame("chunk", { text: "the capital of France." }),
      doneFrame({ answer: "Paris is the capital of France." }),
    ]);
    vi.stubGlobal("fetch", fetchMock);

    render(<QueryChat initialConversationId="conv-1" initialTurns={[]} />);

    await user.type(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      "What is the capital of France?",
    );
    await user.click(screen.getByRole("button", { name: "" }));

    await waitFor(() => expect(screen.getByText("Paris is ", { exact: false })).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByText("Paris is the capital of France.")).toBeInTheDocument(),
    );

    vi.unstubAllGlobals();
  });

  it("erases streamed text on a retract event, showing only the final blocked answer", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchStreamedFrames([
      sseFrame("chunk", { text: "Something that looks fine at first" }),
      sseFrame("retract", { reason: "injection" }),
      doneFrame({
        answer: "I can't help with that — it didn't pass a safety check. Try rephrasing your question.",
        blocked: true,
        block_reason: "injection",
      }),
    ]);
    vi.stubGlobal("fetch", fetchMock);

    render(<QueryChat initialConversationId="conv-1" initialTurns={[]} />);

    await user.type(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      "A tricky question",
    );
    await user.click(screen.getByRole("button", { name: "" }));

    await waitFor(() =>
      expect(
        screen.getByText(
          "I can't help with that — it didn't pass a safety check. Try rephrasing your question.",
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Something that looks fine at first", { exact: false })).not.toBeInTheDocument();

    vi.unstubAllGlobals();
  });
});

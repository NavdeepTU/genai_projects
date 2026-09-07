import { describe, expect, it, vi } from "vitest";

import { streamQuery, UnauthorizedError } from "@/lib/api";

function bytes(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

// Feeds the reader one Uint8Array per read() call, in order — lets a test
// control exactly how the raw bytes are split across network reads,
// independent of how many SSE frames are actually inside them.
function mockFetchReads(reads: Uint8Array[], opts: { ok?: boolean; status?: number } = {}) {
  let index = 0;
  const reader = {
    read: async () => {
      if (index >= reads.length) return { done: true, value: undefined };
      return { done: false, value: reads[index++] };
    },
  };
  return vi.fn().mockResolvedValue({
    ok: opts.ok ?? true,
    status: opts.status ?? 200,
    body: { getReader: () => reader },
    json: async () => ({}),
  });
}

async function collect<T>(iterable: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of iterable) out.push(item);
  return out;
}

describe("streamQuery", () => {
  it("parses one event per read when each read holds exactly one complete frame", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchReads([bytes(sseFrame("chunk", { text: "Hello" })), bytes(sseFrame("ttft", { ms: 120 }))]),
    );

    const events = await collect(streamQuery("a question", null));

    expect(events).toEqual([
      { type: "chunk", text: "Hello" },
      { type: "ttft", ms: 120 },
    ]);
    vi.unstubAllGlobals();
  });

  it("reassembles a single frame whose bytes arrive split across two reads", async () => {
    const frame = sseFrame("chunk", { text: "Paris is the capital of France." });
    const splitPoint = Math.floor(frame.length / 2);
    const wholeFrame = bytes(frame);

    vi.stubGlobal("fetch", mockFetchReads([wholeFrame.slice(0, splitPoint), wholeFrame.slice(splitPoint)]));

    const events = await collect(streamQuery("a question", null));

    expect(events).toEqual([{ type: "chunk", text: "Paris is the capital of France." }]);
    vi.unstubAllGlobals();
  });

  it("yields every frame found inside a single read that holds more than one", async () => {
    const combined = sseFrame("chunk", { text: "First. " }) + sseFrame("chunk", { text: "Second." });
    vi.stubGlobal("fetch", mockFetchReads([bytes(combined)]));

    const events = await collect(streamQuery("a question", null));

    expect(events).toEqual([
      { type: "chunk", text: "First. " },
      { type: "chunk", text: "Second." },
    ]);
    vi.unstubAllGlobals();
  });

  it("correctly decodes a multi-byte character split across a chunk boundary", async () => {
    // "café" — the "é" is 2 UTF-8 bytes; splitting between them would
    // corrupt the text if the decoder weren't told to buffer partial
    // sequences across reads (TextDecoder's `{ stream: true }` option).
    const frame = sseFrame("chunk", { text: "café" });
    const wholeFrame = bytes(frame);
    // Split one byte into "é"'s 2-byte UTF-8 encoding, so each read holds
    // half of one character.
    const prefixByteLength = new TextEncoder().encode(frame.slice(0, frame.indexOf("é"))).length;
    const splitPoint = prefixByteLength + 1;

    vi.stubGlobal("fetch", mockFetchReads([wholeFrame.slice(0, splitPoint), wholeFrame.slice(splitPoint)]));

    const events = await collect(streamQuery("a question", null));

    expect(events).toEqual([{ type: "chunk", text: "café" }]);
    vi.unstubAllGlobals();
  });

  it("passes the question and conversation_id through as the request body", async () => {
    const fetchMock = mockFetchReads([bytes(sseFrame("chunk", { text: "hi" }))]);
    vi.stubGlobal("fetch", fetchMock);

    await collect(streamQuery("What about carryover?", "conv-1"));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/query/stream",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ question: "What about carryover?", conversation_id: "conv-1" }),
      }),
    );
    vi.unstubAllGlobals();
  });

  it("throws UnauthorizedError on a 401 without trying to read a body", async () => {
    vi.stubGlobal("fetch", mockFetchReads([], { ok: false, status: 401 }));

    await expect(collect(streamQuery("a question", null))).rejects.toBeInstanceOf(UnauthorizedError);
    vi.unstubAllGlobals();
  });

  it("throws an error using the backend's detail message on a non-401 failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      body: null,
      json: async () => ({ detail: "The query engine is temporarily unavailable." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(collect(streamQuery("a question", null))).rejects.toThrow(
      "The query engine is temporarily unavailable.",
    );
    vi.unstubAllGlobals();
  });

  it("falls back to a generic message when a failed response has no JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      body: null,
      json: async () => {
        throw new Error("not JSON");
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(collect(streamQuery("a question", null))).rejects.toThrow("Query failed (status 500)");
    vi.unstubAllGlobals();
  });

  it("ignores a frame with no data lines rather than yielding a malformed event", async () => {
    // A bare comment/keep-alive frame some SSE proxies send — no `data:`
    // line at all — must be skipped, not turned into `{ type: "message" }`.
    const combined = "event: chunk\n\n" + sseFrame("done", { answer: "ok" });
    vi.stubGlobal("fetch", mockFetchReads([bytes(combined)]));

    const events = await collect(streamQuery("a question", null));

    expect(events).toEqual([{ type: "done", answer: "ok" }]);
    vi.unstubAllGlobals();
  });
});

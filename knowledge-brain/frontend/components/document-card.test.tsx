import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DocumentListItem } from "@/lib/api";
import { DocumentCard } from "@/components/document-card";

function makeDocument(overrides: Partial<DocumentListItem> = {}): DocumentListItem {
  return {
    id: "doc-1",
    filename: "handbook.pdf",
    status: "ready",
    uploaded_at: "2026-01-01T00:00:00Z",
    pii_detected: false,
    domains: [],
    ...overrides,
  };
}

describe("DocumentCard", () => {
  it("renders a badge for every domain tag on the document", () => {
    render(<DocumentCard document={makeDocument({ domains: ["HR", "Finance"] })} />);

    expect(screen.getByText("HR")).toBeInTheDocument();
    expect(screen.getByText("Finance")).toBeInTheDocument();
  });

  it("renders no domain badges for an untagged document", () => {
    const { container } = render(<DocumentCard document={makeDocument({ domains: [] })} />);

    expect(screen.getByText("handbook.pdf")).toBeInTheDocument();
    // The domain-tags row only ever renders when domains.length > 0 (see
    // DocumentCard) — its wrapper has this exact class, so its absence
    // confirms the row itself was skipped, not just rendered empty.
    expect(container.querySelector(".flex-wrap")).not.toBeInTheDocument();
  });
});

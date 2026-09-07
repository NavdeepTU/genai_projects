import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

import { DeleteDocumentButton } from "@/components/delete-document-button";

function mockFetchOk() {
  return vi.fn().mockResolvedValue({ ok: true, status: 204, json: async () => ({}) });
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /delete handbook.pdf/i }));
}

describe("DeleteDocumentButton", () => {
  it("shows a confirmation dialog before deleting anything", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchOk();
    vi.stubGlobal("fetch", fetchMock);

    render(<DeleteDocumentButton documentId="doc-1" filename="handbook.pdf" />);
    await openDialog(user);

    expect(screen.getByText("Delete handbook.pdf?")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });

  it("does not delete when the dialog is cancelled", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchOk();
    vi.stubGlobal("fetch", fetchMock);

    render(<DeleteDocumentButton documentId="doc-1" filename="handbook.pdf" />);
    await openDialog(user);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });

  it("calls the delete endpoint and refreshes the list when confirmed", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchOk();
    vi.stubGlobal("fetch", fetchMock);

    render(<DeleteDocumentButton documentId="doc-42" filename="handbook.pdf" />);
    await openDialog(user);
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/documents/doc-42", { method: "DELETE" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());

    vi.unstubAllGlobals();
  });

  it("shows an error message and keeps the dialog open when the delete fails", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Couldn't delete the document. Please try again in a moment." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeleteDocumentButton documentId="doc-1" filename="handbook.pdf" />);
    await openDialog(user);
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(
        screen.getByText("Couldn't delete the document. Please try again in a moment."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Delete handbook.pdf?")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });

  it("redirects to /login on a 401 instead of showing an error", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);

    render(<DeleteDocumentButton documentId="doc-1" filename="handbook.pdf" />);
    await openDialog(user);
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));

    vi.unstubAllGlobals();
  });
});

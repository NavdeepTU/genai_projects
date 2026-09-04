import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

import { UploadDropzone } from "@/components/upload-dropzone";

function makeFile(name = "notes.txt") {
  return new File(["hello world"], name, { type: "text/plain" });
}

function getFileInput(): HTMLInputElement {
  const input = document.querySelector('input[type="file"]');
  if (!input) throw new Error("file input not found");
  return input as HTMLInputElement;
}

function mockUploadResponse(domains: string[] = []) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 201,
    json: async () => ({
      id: "doc-1",
      filename: "notes.txt",
      status: "pending",
      domains,
      correlation_id: "corr-1",
    }),
  });
}

describe("UploadDropzone domain tagging", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders a domains field with the expected label and placeholder", () => {
    render(<UploadDropzone />);

    expect(screen.getByLabelText("Domains (optional)")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("e.g. HR, Finance")).toBeInTheDocument();
  });

  it("lets the user type into the domains field", async () => {
    const user = userEvent.setup();
    render(<UploadDropzone />);

    const input = screen.getByLabelText("Domains (optional)");
    await user.type(input, "HR, Finance");

    expect(input).toHaveValue("HR, Finance");
  });

  it("sends the typed domains alongside the file when uploading", async () => {
    const user = userEvent.setup();
    const fetchMock = mockUploadResponse(["HR"]);
    vi.stubGlobal("fetch", fetchMock);

    render(<UploadDropzone />);
    await user.type(screen.getByLabelText("Domains (optional)"), "HR");
    await user.upload(getFileInput(), makeFile());

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/documents/upload");
    const body = options.body as FormData;
    expect(body.get("domains")).toBe("HR");
    expect((body.get("file") as File).name).toBe("notes.txt");
  });

  it("still sends a domains field, empty, when none was typed", async () => {
    const user = userEvent.setup();
    const fetchMock = mockUploadResponse([]);
    vi.stubGlobal("fetch", fetchMock);

    render(<UploadDropzone />);
    await user.upload(getFileInput(), makeFile());

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("domains")).toBe("");
  });

  it("keeps the typed domains after a successful upload, for tagging the next file the same way", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockUploadResponse(["HR"]));

    render(<UploadDropzone />);
    const input = screen.getByLabelText("Domains (optional)");
    await user.type(input, "HR");
    await user.upload(getFileInput(), makeFile());

    await waitFor(() => expect(input).toHaveValue("HR"));
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

import { UploadDropzone } from "@/components/upload-dropzone";

const HR = { id: "domain-hr", name: "HR" };
const FINANCE = { id: "domain-finance", name: "Finance" };

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

  it("shows a helpful empty state when no domains exist yet", () => {
    render(<UploadDropzone domains={[]} />);

    expect(
      screen.getByText(/no domains have been set up yet/i),
    ).toBeInTheDocument();
  });

  it("renders one checkbox per domain, unchecked by default", () => {
    render(<UploadDropzone domains={[HR, FINANCE]} />);

    expect(screen.getByRole("checkbox", { name: "HR" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Finance" })).not.toBeChecked();
  });

  it("sends the checked domain's real id alongside the file when uploading", async () => {
    const user = userEvent.setup();
    const fetchMock = mockUploadResponse(["HR"]);
    vi.stubGlobal("fetch", fetchMock);

    render(<UploadDropzone domains={[HR, FINANCE]} />);
    await user.click(screen.getByRole("checkbox", { name: "HR" }));
    await user.upload(getFileInput(), makeFile());

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/documents/upload");
    const body = options.body as FormData;
    expect(body.get("domain_ids")).toBe(HR.id);
    expect((body.get("file") as File).name).toBe("notes.txt");
  });

  it("sends every checked domain's id when more than one is selected", async () => {
    const user = userEvent.setup();
    const fetchMock = mockUploadResponse(["HR", "Finance"]);
    vi.stubGlobal("fetch", fetchMock);

    render(<UploadDropzone domains={[HR, FINANCE]} />);
    await user.click(screen.getByRole("checkbox", { name: "HR" }));
    await user.click(screen.getByRole("checkbox", { name: "Finance" }));
    await user.upload(getFileInput(), makeFile());

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const body = fetchMock.mock.calls[0][1].body as FormData;
    const sentIds = (body.get("domain_ids") as string).split(",");
    expect(new Set(sentIds)).toEqual(new Set([HR.id, FINANCE.id]));
  });

  it("still sends a domain_ids field, empty, when nothing was checked", async () => {
    const user = userEvent.setup();
    const fetchMock = mockUploadResponse([]);
    vi.stubGlobal("fetch", fetchMock);

    render(<UploadDropzone domains={[HR]} />);
    await user.upload(getFileInput(), makeFile());

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("domain_ids")).toBe("");
  });

  it("unchecking a domain removes it from what gets sent", async () => {
    const user = userEvent.setup();
    const fetchMock = mockUploadResponse([]);
    vi.stubGlobal("fetch", fetchMock);

    render(<UploadDropzone domains={[HR]} />);
    const checkbox = screen.getByRole("checkbox", { name: "HR" });
    await user.click(checkbox);
    await user.click(checkbox);
    await user.upload(getFileInput(), makeFile());

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("domain_ids")).toBe("");
  });
});

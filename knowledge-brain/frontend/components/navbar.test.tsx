import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ setTheme: vi.fn() }),
}));

import { Navbar } from "@/components/navbar";

function makeUser(overrides: Partial<{ id: string; email: string; is_admin: boolean }> = {}) {
  return { id: "user-1", email: "person@example.com", is_admin: false, ...overrides };
}

describe("Navbar", () => {
  it("shows a link to the profile page when logged in", () => {
    render(<Navbar user={makeUser()} />);

    const profileLink = screen.getByRole("link", { name: "View profile" });
    expect(profileLink).toHaveAttribute("href", "/profile");
  });

  it("does not show a profile link when logged out", () => {
    render(<Navbar user={null} />);

    expect(screen.queryByRole("link", { name: "View profile" })).not.toBeInTheDocument();
  });
});

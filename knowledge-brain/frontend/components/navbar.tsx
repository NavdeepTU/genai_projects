"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { Menu } from "lucide-react";

import type { CurrentUser } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { ThemeToggle } from "@/components/theme-toggle";

const BASE_NAV_ITEMS = [
  { href: "/", label: "Dashboard" },
  { href: "/documents", label: "Documents" },
  { href: "/query", label: "Query" },
  { href: "/analytics", label: "Analytics" },
];

function NavLink({
  href,
  label,
  pathname,
}: {
  href: string;
  label: string;
  pathname: string;
}) {
  const isActive = href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <Link
      href={href}
      className={cn(
        "text-sm transition-colors hover:text-foreground",
        isActive ? "text-foreground font-medium" : "text-muted-foreground",
      )}
    >
      {label}
    </Link>
  );
}

function UserSection({ user }: { user: CurrentUser | null }) {
  const router = useRouter();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutFailed, setLogoutFailed] = useState(false);

  if (!user) {
    return (
      <Link href="/login" className="text-sm text-muted-foreground hover:text-foreground">
        Log in
      </Link>
    );
  }

  async function handleLogout() {
    setIsLoggingOut(true);
    setLogoutFailed(false);
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error("Logout failed");
      router.push("/login");
      router.refresh();
    } catch {
      // A network hiccup shouldn't leave the button stuck reading
      // "Logging out..." forever — reset it and let the user try again.
      setLogoutFailed(true);
    } finally {
      setIsLoggingOut(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="hidden max-w-32 truncate text-xs text-muted-foreground sm:inline">
        {user.email}
      </span>
      {logoutFailed && (
        <span className="text-xs text-destructive">Couldn&apos;t log out — try again</span>
      )}
      <Button variant="outline" size="sm" onClick={handleLogout} disabled={isLoggingOut}>
        {isLoggingOut ? "Logging out..." : "Log out"}
      </Button>
    </div>
  );
}

export function Navbar({ user }: { user: CurrentUser | null }) {
  const pathname = usePathname();
  const navItems = user?.is_admin
    ? [...BASE_NAV_ITEMS, { href: "/admin", label: "Admin" }]
    : BASE_NAV_ITEMS;

  return (
    <header className="border-b">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link href="/" className="font-semibold">
          Knowledge Brain
        </Link>

        <nav className="hidden items-center gap-6 md:flex">
          {navItems.map((item) => (
            <NavLink key={item.href} {...item} pathname={pathname} />
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <UserSection user={user} />
          <ThemeToggle />

          <Sheet>
            <SheetTrigger
              render={
                <Button variant="outline" size="icon" className="md:hidden">
                  <Menu className="h-[1.2rem] w-[1.2rem]" />
                  <span className="sr-only">Open menu</span>
                </Button>
              }
            />
            <SheetContent side="right">
              <SheetHeader>
                <SheetTitle>Knowledge Brain</SheetTitle>
              </SheetHeader>
              <nav className="flex flex-col gap-4 px-4">
                {navItems.map((item) => (
                  <SheetClose key={item.href} render={<NavLink {...item} pathname={pathname} />} />
                ))}
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  );
}

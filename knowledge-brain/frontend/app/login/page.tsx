import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { LoginForm } from "@/components/login-form";

// Reads the session cookie (via getCurrentUser), so this always needs a
// fresh render — same reasoning as every other per-user page in this app.
export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const user = await getCurrentUser();
  if (user) {
    redirect("/");
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-6 px-4 py-24">
      <div className="flex flex-col gap-1 text-center">
        <h1 className="text-xl font-semibold">Log in</h1>
        <p className="text-sm text-muted-foreground">Welcome back to Knowledge Brain.</p>
      </div>

      <LoginForm />

      <p className="text-center text-sm text-muted-foreground">
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="text-foreground underline underline-offset-4">
          Sign up
        </Link>
      </p>
    </div>
  );
}

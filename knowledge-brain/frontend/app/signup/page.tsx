import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getTenants } from "@/lib/server-api";
import { SignupForm } from "@/components/signup-form";

// Reads the session cookie (via getCurrentUser), so this always needs a
// fresh render — same reasoning as every other per-user page in this app.
export const dynamic = "force-dynamic";

export default async function SignupPage() {
  const user = await getCurrentUser();
  if (user) {
    redirect("/");
  }

  // A user picks their tenant from the list an admin has already
  // registered — they never create one themselves (ADR-046).
  const tenants = await getTenants();

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-6 px-4 py-24">
      <div className="flex flex-col gap-1 text-center">
        <h1 className="text-xl font-semibold">Create an account</h1>
        <p className="text-sm text-muted-foreground">Get started with Knowledge Brain.</p>
      </div>

      <SignupForm tenants={tenants} />

      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="text-foreground underline underline-offset-4">
          Log in
        </Link>
      </p>
    </div>
  );
}

"use client";

import { Button } from "@/components/ui/button";

// Unlike every other page's error boundary, this one shows the real
// error message rather than a fixed generic one — a 403 ("you're not
// an admin") and a genuine server error are different situations a
// reader here should be able to tell apart.
export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-4 py-24 text-center">
      <p className="text-lg font-medium">Couldn&apos;t load the admin panel</p>
      <p className="max-w-md text-sm text-muted-foreground">{error.message}</p>
      <Button onClick={() => reset()}>Try again</Button>
    </div>
  );
}

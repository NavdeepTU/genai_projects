"use client";

import { Button } from "@/components/ui/button";

export default function DocumentsError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-4 py-24 text-center">
      <p className="text-lg font-medium">Couldn&apos;t load your documents</p>
      <p className="text-sm text-muted-foreground">
        Something went wrong reaching the server. Try again, or come back in a moment.
      </p>
      <Button onClick={() => reset()}>Try again</Button>
    </div>
  );
}

"use client";

import { Button } from "@/components/ui/button";

export default function QueryError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="text-lg font-medium">Couldn&apos;t load your conversations</p>
      <p className="text-sm text-muted-foreground">
        Something went wrong reaching the server. Try again, or come back in a moment.
      </p>
      <Button onClick={() => reset()}>Try again</Button>
    </div>
  );
}

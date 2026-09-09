"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Send } from "lucide-react";

import { submitDocumentForReview, UnauthorizedError } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function SubmitForReviewButton({ documentId }: { documentId: string }) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setIsSubmitting(true);
    setError(null);
    try {
      await submitDocumentForReview(documentId);
      router.refresh();
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Something went wrong");
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleSubmit}
        disabled={isSubmitting}
        className="h-7 gap-1.5 text-xs"
      >
        <Send className="size-3.5" />
        {isSubmitting ? "Sending…" : "Send for review"}
      </Button>
      {error && <p className="text-[0.65rem] text-destructive">{error}</p>}
    </div>
  );
}

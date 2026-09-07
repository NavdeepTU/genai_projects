"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";

import { deleteDocument, UnauthorizedError } from "@/lib/api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

export function DeleteDocumentButton({
  documentId,
  filename,
}: {
  documentId: string;
  filename: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    setIsDeleting(true);
    setError(null);
    try {
      await deleteDocument(documentId);
      setOpen(false);
      router.refresh();
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <AlertDialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) setError(null);
      }}
    >
      <AlertDialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`Delete ${filename}`}
            className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          />
        }
      >
        <Trash2 />
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {filename}?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently removes the document, its extracted content, and its file. This
            can&apos;t be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={handleDelete}
            disabled={isDeleting}
          >
            {isDeleting ? "Deleting…" : "Delete"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

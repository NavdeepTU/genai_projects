import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function ConversationNotFound() {
  return (
    <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="text-lg font-medium">Conversation not found</p>
      <p className="text-sm text-muted-foreground">
        It may have been deleted, or it belongs to a different account.
      </p>
      <Button render={<Link href="/query">Start a new conversation</Link>} />
    </div>
  );
}

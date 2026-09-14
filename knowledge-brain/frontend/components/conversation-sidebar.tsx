"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { MessageSquare, Plus } from "lucide-react";

import type { ConversationListItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { DeleteConversationButton } from "@/components/delete-conversation-button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

function formatUpdatedAt(updatedAt: string) {
  return new Date(updatedAt).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function NewConversationLink({ onNavigate }: { onNavigate?: () => void }) {
  const link = (
    <Link
      href="/query"
      className="flex items-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted/40"
    >
      <Plus className="size-4" />
      New conversation
    </Link>
  );
  return onNavigate ? <SheetClose render={link} /> : link;
}

function ConversationList({
  conversations,
  pathname,
  onNavigate,
}: {
  conversations: ConversationListItem[];
  pathname: string;
  onNavigate?: () => void;
}) {
  if (conversations.length === 0) {
    return (
      <p className="px-3 py-6 text-center text-xs text-muted-foreground">
        No conversations yet — ask a question to start one.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {conversations.map((conversation) => {
        const href = `/query/${conversation.id}`;
        const isActive = pathname === href;
        // The row's own background carries the active/hover state now, so
        // it still spans the full width once the delete button sits beside
        // the link instead of inside it — a button can't legally nest
        // inside an anchor, and we don't want deleting to also navigate.
        const link = (
          <Link
            href={href}
            className={cn(
              "flex min-w-0 flex-1 flex-col gap-0.5 px-3 py-2 text-sm",
              isActive ? "font-medium" : "text-muted-foreground",
            )}
          >
            <span className="truncate">{conversation.title}</span>
            <span className="text-[0.65rem] text-muted-foreground">
              {formatUpdatedAt(conversation.updated_at)}
            </span>
          </Link>
        );
        return (
          <div
            key={conversation.id}
            className={cn(
              "flex items-center gap-1 rounded-md pr-1 transition-colors hover:bg-muted/40",
              isActive && "bg-muted",
            )}
          >
            {onNavigate ? <SheetClose render={link} /> : link}
            <DeleteConversationButton
              conversationId={conversation.id}
              title={conversation.title}
              isActive={isActive}
            />
          </div>
        );
      })}
    </div>
  );
}

export function ConversationSidebar({
  conversations,
  children,
}: {
  conversations: ConversationListItem[];
  children: ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <aside className="hidden w-64 shrink-0 flex-col gap-2 overflow-y-auto border-r border-border p-3 md:flex">
        <NewConversationLink />
        <ConversationList conversations={conversations} pathname={pathname} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center border-b border-border px-4 py-2 md:hidden">
          <Sheet>
            <SheetTrigger
              render={
                <Button variant="outline" size="sm">
                  <MessageSquare className="size-4" />
                  Conversations
                </Button>
              }
            />
            <SheetContent side="left">
              <SheetHeader>
                <SheetTitle>Conversations</SheetTitle>
              </SheetHeader>
              <div className="flex flex-col gap-2 px-4">
                <NewConversationLink onNavigate={() => {}} />
                <ConversationList conversations={conversations} pathname={pathname} onNavigate={() => {}} />
              </div>
            </SheetContent>
          </Sheet>
        </div>

        <div className="min-h-0 flex-1">{children}</div>
      </div>
    </div>
  );
}

import { notFound } from "next/navigation";

import { getConversation } from "@/lib/server-api";
import { QueryChat } from "@/components/query-chat";

export default async function ConversationPage({ params }: PageProps<"/query/[conversationId]">) {
  const { conversationId } = await params;
  const conversation = await getConversation(conversationId);

  if (conversation === null) {
    notFound();
  }

  return <QueryChat initialConversationId={conversation.id} initialTurns={conversation.turns} />;
}

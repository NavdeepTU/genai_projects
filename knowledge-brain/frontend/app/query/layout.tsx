import { getConversations } from "@/lib/server-api";
import { ConversationSidebar } from "@/components/conversation-sidebar";

// Same per-user, always-fresh reasoning as the Document Library page —
// the conversation list changes on every question asked, so this can't
// be treated as eligible for static prerendering.
export const dynamic = "force-dynamic";

export default async function QueryLayout({ children }: LayoutProps<"/query">) {
  const conversations = await getConversations();

  return <ConversationSidebar conversations={conversations}>{children}</ConversationSidebar>;
}

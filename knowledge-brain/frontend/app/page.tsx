import { DollarSign, FileText, MessageCircle, TrendingUp } from "lucide-react";

import { getDashboard, type RecentQuery } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// This page's data is per-user and changes on every query/upload — without
// this, Next.js could freeze it as a stale, build-time snapshot in a real
// production build. Same reasoning, and same fix, as the Document Library
// page (see ADR-029) — applied here from the start this time, not found
// live after the fact.
export const dynamic = "force-dynamic";

function StatTile({
  icon: Icon,
  label,
  value,
  placeholder,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value?: string | number;
  placeholder?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Icon className="size-4 text-muted-foreground" />
          <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        {placeholder ? (
          <p className="text-xs text-muted-foreground">{placeholder}</p>
        ) : (
          <p className="text-3xl font-semibold">{value}</p>
        )}
      </CardContent>
    </Card>
  );
}

function formatAskedAt(askedAt: string) {
  return new Date(askedAt).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function RecentQueriesCard({ queries }: { queries: RecentQuery[] }) {
  return (
    <Card className="sm:col-span-2 lg:col-span-4">
      <CardHeader>
        <div className="flex items-center gap-2">
          <MessageCircle className="size-4 text-muted-foreground" />
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Recent queries
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        {queries.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No questions asked yet — try the Query page.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {queries.map((query, i) => (
              <li
                key={i}
                className={cn(
                  "flex items-baseline justify-between gap-4 text-sm",
                  i > 0 && "border-t border-border pt-3",
                )}
              >
                <span className="truncate">{query.question}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {formatAskedAt(query.asked_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default async function DashboardPage() {
  const dashboard = await getDashboard();

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-8 text-2xl font-semibold">Dashboard</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile icon={FileText} label="Total documents" value={dashboard.document_count} />
        <StatTile
          icon={TrendingUp}
          label="Retrieval accuracy trend"
          placeholder="Not tracked yet — no per-query ground-truth signal exists. Run the evaluation harness manually for a point-in-time check."
        />
        <StatTile
          icon={DollarSign}
          label="Cost per query (this month)"
          placeholder="Not tracked yet — token/cost instrumentation is build-order item 15 (LLM observability)."
        />
        <RecentQueriesCard queries={dashboard.recent_queries} />
      </div>
    </div>
  );
}

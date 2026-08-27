import { Clock, MessageSquareText, TrendingUp } from "lucide-react";

import { getAnalytics, type TopQuestion } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ListCard } from "@/components/list-card";
import { ProgressBar } from "@/components/progress-bar";
import { NO_QUERIES_MESSAGE, QueryVolumeChart } from "@/components/query-volume-chart";
import { StatTile } from "@/components/stat-tile";

// Same reasoning as the Dashboard (ADR-029/ADR-032): this page's data
// changes on every query, so it must never be frozen as a stale,
// build-time snapshot in a real production build.
export const dynamic = "force-dynamic";

function formatResponseTime(ms: number | null) {
  if (ms === null) return undefined;
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function TopQuestionsCard({ questions }: { questions: TopQuestion[] }) {
  const maxCount = Math.max(1, ...questions.map((q) => q.count));

  return (
    <ListCard
      icon={MessageSquareText}
      title="Top questions (last 30 days)"
      isEmpty={questions.length === 0}
      emptyMessage={NO_QUERIES_MESSAGE}
      className="sm:col-span-2 lg:col-span-4"
    >
      {questions.map((q, i) => (
        <li key={i} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-4 text-sm">
            <span className="truncate">{q.question}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{q.count}× asked</span>
          </div>
          <ProgressBar percent={(q.count / maxCount) * 100} />
        </li>
      ))}
    </ListCard>
  );
}

export default async function AnalyticsPage() {
  const analytics = await getAnalytics();
  const avgResponseTime = formatResponseTime(analytics.avg_response_time_ms);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-8 text-2xl font-semibold">Analytics</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="sm:col-span-2 lg:col-span-4">
          <CardHeader>
            <div className="flex items-center gap-2">
              <TrendingUp className="size-4 text-muted-foreground" />
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Query volume (last 30 days)
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <QueryVolumeChart points={analytics.query_volume} />
          </CardContent>
        </Card>

        <StatTile
          icon={Clock}
          label="Average response time"
          value={avgResponseTime}
          placeholder={
            avgResponseTime === undefined
              ? "Not enough recent queries with timing data yet — ask a question on the Query page."
              : undefined
          }
        />
        <StatTile
          icon={TrendingUp}
          label="Retrieval accuracy trend"
          placeholder="Not tracked yet — no per-query ground-truth signal exists. Run the evaluation harness manually for a point-in-time check."
        />

        <TopQuestionsCard questions={analytics.top_questions} />
      </div>
    </div>
  );
}

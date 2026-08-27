import type { QueryVolumePoint } from "@/lib/api";

const CHART_WIDTH = 600;
const CHART_HEIGHT = 140;
const BAR_GAP = 2;

export const NO_QUERIES_MESSAGE = "No queries in the last 30 days — try the Query page.";

function formatShortDate(dateStr: string) {
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString("en-US", {
    month: "numeric",
    day: "numeric",
  });
}

export function QueryVolumeChart({ points }: { points: QueryVolumePoint[] }) {
  if (points.length === 0) {
    return <p className="text-xs text-muted-foreground">{NO_QUERIES_MESSAGE}</p>;
  }

  const maxCount = Math.max(...points.map((p) => p.count));
  const barWidth = CHART_WIDTH / points.length - BAR_GAP;

  // Only label a handful of bars — every date would overlap illegibly
  // once there are more than a few points.
  const labelEvery = Math.max(1, Math.ceil(points.length / 6));

  return (
    <div className="flex flex-col gap-1">
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT + 20}`}
        className="w-full"
        role="img"
        aria-label="Query volume over the last 30 days"
      >
        {points.map((point, i) => {
          const barHeight = maxCount > 0 ? (point.count / maxCount) * CHART_HEIGHT : 0;
          const x = i * (barWidth + BAR_GAP);
          const y = CHART_HEIGHT - barHeight;
          return (
            <g key={point.date}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={barHeight}
                rx={2}
                style={{ fill: "var(--primary)" }}
              >
                <title>{`${point.date}: ${point.count} ${point.count === 1 ? "query" : "queries"}`}</title>
              </rect>
              {i % labelEvery === 0 && (
                <text
                  x={x + barWidth / 2}
                  y={CHART_HEIGHT + 14}
                  textAnchor="middle"
                  fontSize="9"
                  style={{ fill: "var(--muted-foreground)" }}
                >
                  {formatShortDate(point.date)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

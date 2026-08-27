export default function AnalyticsLoading() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <div className="mb-8 h-8 w-48 animate-pulse rounded-md bg-muted" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="h-40 animate-pulse rounded-lg bg-muted sm:col-span-2 lg:col-span-4" />
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-lg bg-muted" />
        ))}
        <div className="h-40 animate-pulse rounded-lg bg-muted sm:col-span-2 lg:col-span-4" />
      </div>
    </div>
  );
}

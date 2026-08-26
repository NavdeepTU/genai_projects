export default function DashboardLoading() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <div className="mb-8 h-8 w-48 animate-pulse rounded-md bg-muted" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    </div>
  );
}

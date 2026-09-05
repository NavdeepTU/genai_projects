export default function QueryLoading() {
  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <aside className="hidden w-64 shrink-0 flex-col gap-2 border-r border-border p-3 md:flex">
        <div className="h-8 animate-pulse rounded-md bg-muted" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-10 animate-pulse rounded-md bg-muted" />
        ))}
      </aside>
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-3 px-4 py-6">
        <div className="ml-auto h-8 w-2/3 animate-pulse rounded-lg bg-muted" />
        <div className="h-16 w-3/4 animate-pulse rounded-lg bg-muted" />
      </div>
    </div>
  );
}

import { Building2, ScrollText, ShieldCheck } from "lucide-react";

import type { AdminAuditEntry, DocumentPermissionEntry } from "@/lib/api";
import { getAdmin } from "@/lib/server-api";
import { Badge } from "@/components/ui/badge";
import { ListCard } from "@/components/list-card";
import { StatTile } from "@/components/stat-tile";
import { cn } from "@/lib/utils";

// Admin data spans every user, not just the caller's — must never be
// frozen as a stale, build-time snapshot. Same reasoning as every other
// data page in this app (ADR-029/032/033).
export const dynamic = "force-dynamic";

const ACTION_BADGE_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  query_made: "default",
  document_upload: "secondary",
  permission_granted: "outline",
  access_denied: "destructive",
};

function formatTimestamp(value: string) {
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function AuditLogCard({ entries }: { entries: AdminAuditEntry[] }) {
  return (
    <ListCard
      icon={ScrollText}
      title="Audit log (most recent, all users)"
      isEmpty={entries.length === 0}
      emptyMessage="No audit entries yet."
      className="sm:col-span-2 lg:col-span-4"
    >
      {entries.map((entry, i) => (
        <li
          key={i}
          className={cn(
            "flex items-center justify-between gap-4 text-sm",
            i > 0 && "border-t border-border pt-3",
          )}
        >
          <div className="flex min-w-0 items-center gap-2">
            <Badge variant={ACTION_BADGE_VARIANT[entry.action] ?? "outline"}>{entry.action}</Badge>
            <span className="truncate text-xs text-muted-foreground">
              {entry.user_id ?? "unknown user"} · {entry.resource_type}
            </span>
          </div>
          <span className="shrink-0 text-xs text-muted-foreground">
            {formatTimestamp(entry.timestamp)}
          </span>
        </li>
      ))}
    </ListCard>
  );
}

function PermissionsCard({ permissions }: { permissions: DocumentPermissionEntry[] }) {
  return (
    <ListCard
      icon={ShieldCheck}
      title="Document permissions (all documents)"
      isEmpty={permissions.length === 0}
      emptyMessage="No documents have been shared yet."
      className="sm:col-span-2 lg:col-span-4"
    >
      {permissions.map((permission, i) => (
        <li
          key={i}
          className={cn(
            "flex items-center justify-between gap-4 text-sm",
            i > 0 && "border-t border-border pt-3",
          )}
        >
          <div className="flex min-w-0 flex-col">
            <span className="truncate">{permission.filename}</span>
            <span className="text-xs text-muted-foreground">granted to {permission.user_id}</span>
          </div>
          <span className="shrink-0 text-xs text-muted-foreground">
            {formatTimestamp(permission.granted_at)}
          </span>
        </li>
      ))}
    </ListCard>
  );
}

export default async function AdminPage() {
  const admin = await getAdmin();

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-8 text-2xl font-semibold">Admin</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          icon={Building2}
          label="Tenant management"
          placeholder="Not applicable yet — this system is single-tenant. Multi-tenancy is build-order item 14, not built."
          className="sm:col-span-2 lg:col-span-4"
        />
        <PermissionsCard permissions={admin.permissions} />
        <AuditLogCard entries={admin.audit_entries} />
      </div>
    </div>
  );
}

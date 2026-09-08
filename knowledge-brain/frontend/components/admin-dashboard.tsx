"use client";

import { useState } from "react";
import { Building2, ScrollText } from "lucide-react";

import type { AdminAuditEntry, Tenant } from "@/lib/api";
import { createTenant } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ListCard } from "@/components/list-card";
import { cn } from "@/lib/utils";

const ACTION_BADGE_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  query_made: "default",
  document_upload: "secondary",
  tenant_registered: "outline",
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

type SectionId = "audit-log" | "tenants";

const SECTIONS: { id: SectionId; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "audit-log", label: "Audit log", icon: ScrollText },
  { id: "tenants", label: "Tenant management", icon: Building2 },
];

function AuditLogSection({ entries }: { entries: AdminAuditEntry[] }) {
  return (
    <ListCard
      icon={ScrollText}
      title="Audit log (most recent, all users)"
      isEmpty={entries.length === 0}
      emptyMessage="No audit entries yet."
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

function TenantsSection({ tenants }: { tenants: Tenant[] }) {
  const [tenantList, setTenantList] = useState(tenants);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const tenant = await createTenant(name);
      setTenantList((current) => [...current, tenant]);
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Register a new company
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex items-start gap-2">
            <Input
              aria-label="Company name"
              placeholder="Acme Corp"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isSubmitting}
              required
            />
            <Button type="submit" disabled={isSubmitting || name.trim().length === 0}>
              {isSubmitting ? "Registering..." : "Register"}
            </Button>
          </form>
          {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      <ListCard
        icon={Building2}
        title="Registered companies"
        isEmpty={tenantList.length === 0}
        emptyMessage="No companies registered yet — use the form above to register the first one."
      >
        {tenantList.map((tenant, i) => (
          <li
            key={tenant.id}
            className={cn("text-sm", i > 0 && "border-t border-border pt-3")}
          >
            {tenant.name}
          </li>
        ))}
      </ListCard>
    </div>
  );
}

function NavButton({
  section,
  active,
  onSelect,
}: {
  section: (typeof SECTIONS)[number];
  active: boolean;
  onSelect: () => void;
}) {
  const Icon = section.icon;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted/40",
        active ? "bg-muted font-medium text-foreground" : "text-muted-foreground",
      )}
    >
      <Icon className="size-4 shrink-0" />
      <span className="truncate">{section.label}</span>
    </button>
  );
}

export function AdminDashboard({
  auditEntries,
  tenants,
}: {
  auditEntries: AdminAuditEntry[];
  tenants: Tenant[];
}) {
  const [activeSection, setActiveSection] = useState<SectionId>("audit-log");

  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-start md:gap-6">
      <nav className="flex gap-1 overflow-x-auto pb-1 md:w-56 md:shrink-0 md:flex-col md:overflow-visible md:pb-0">
        {SECTIONS.map((section) => (
          <NavButton
            key={section.id}
            section={section}
            active={activeSection === section.id}
            onSelect={() => setActiveSection(section.id)}
          />
        ))}
      </nav>

      <div className="min-w-0 flex-1">
        {activeSection === "audit-log" && <AuditLogSection entries={auditEntries} />}
        {activeSection === "tenants" && <TenantsSection tenants={tenants} />}
      </div>
    </div>
  );
}

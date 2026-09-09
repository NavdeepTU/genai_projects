"use client";

import { useState } from "react";
import { Building2, ExternalLink, ScrollText, ShieldAlert, Tags } from "lucide-react";

import type { AdminAuditEntry, Domain, ReviewQueueItem, Tenant } from "@/lib/api";
import {
  approveDocument,
  createDomain,
  createTenant,
  deleteDomain,
  mergeDomain,
  rejectDocument,
  renameDomain,
} from "@/lib/api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
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

type SectionId = "audit-log" | "review-queue" | "tenants" | "domains";

const SECTIONS: { id: SectionId; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "audit-log", label: "Audit log", icon: ScrollText },
  { id: "review-queue", label: "Review queue", icon: ShieldAlert },
  { id: "tenants", label: "Tenant management", icon: Building2 },
  { id: "domains", label: "Domains", icon: Tags },
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

function ReviewQueueSection({ documents }: { documents: ReviewQueueItem[] }) {
  const [queue, setQueue] = useState(documents);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorId, setErrorId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleDecision(documentId: string, decision: "approve" | "reject") {
    setBusyId(documentId);
    setErrorId(null);
    setError(null);
    try {
      if (decision === "approve") {
        await approveDocument(documentId);
      } else {
        await rejectDocument(documentId);
      }
      setQueue((current) => current.filter((doc) => doc.id !== documentId));
    } catch (err) {
      setErrorId(documentId);
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <ListCard
      icon={ShieldAlert}
      title="Documents awaiting PII review"
      isEmpty={queue.length === 0}
      emptyMessage="Nothing waiting on a review decision right now."
    >
      {queue.map((doc, i) => (
        <li
          key={doc.id}
          className={cn("flex flex-col gap-2 text-sm", i > 0 && "border-t border-border pt-3")}
        >
          <div className="flex items-center justify-between gap-4">
            <div className="flex min-w-0 flex-col">
              <span className="truncate">{doc.filename}</span>
              <span className="text-xs text-muted-foreground">
                uploaded by {doc.uploaded_by_email ?? "unknown user"}
              </span>
            </div>
            {doc.has_file && (
              <a
                href={`/api/documents/${doc.id}/content`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex shrink-0 items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                <ExternalLink className="size-3.5" />
                View
              </a>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              className="h-7 text-xs"
              disabled={busyId === doc.id}
              onClick={() => handleDecision(doc.id, "approve")}
            >
              {busyId === doc.id ? "Working…" : "Approve"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              disabled={busyId === doc.id}
              onClick={() => handleDecision(doc.id, "reject")}
            >
              Reject
            </Button>
          </div>
          {errorId === doc.id && error && <p className="text-xs text-destructive">{error}</p>}
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

function DomainRow({
  domain,
  otherDomains,
  onRenamed,
  onMerged,
  onDeleted,
  className,
}: {
  domain: Domain;
  otherDomains: Domain[];
  onRenamed: (domain: Domain) => void;
  onMerged: (removedId: string, remaining: Domain[]) => void;
  onDeleted: (removedId: string) => void;
  className?: string;
}) {
  const [isRenaming, setIsRenaming] = useState(false);
  const [name, setName] = useState(domain.name);
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRename() {
    setIsBusy(true);
    setError(null);
    try {
      const renamed = await renameDomain(domain.id, name);
      onRenamed(renamed);
      setIsRenaming(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleMerge() {
    if (!mergeTargetId) return;
    setIsBusy(true);
    setError(null);
    try {
      const remaining = await mergeDomain(domain.id, mergeTargetId);
      onMerged(domain.id, remaining);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setIsBusy(false);
    }
  }

  async function handleDelete() {
    setIsBusy(true);
    setError(null);
    try {
      await deleteDomain(domain.id);
      onDeleted(domain.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setIsBusy(false);
    }
  }

  return (
    <li className={cn("flex flex-col gap-2 text-sm", className)}>
      <div className="flex flex-wrap items-center gap-2">
        {isRenaming ? (
          <>
            <Input
              aria-label={`Rename ${domain.name}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isBusy}
              className="h-7 max-w-40 text-xs"
            />
            <Button size="sm" className="h-7 text-xs" disabled={isBusy} onClick={handleRename}>
              Save
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              disabled={isBusy}
              onClick={() => {
                setIsRenaming(false);
                setName(domain.name);
                setError(null);
              }}
            >
              Cancel
            </Button>
          </>
        ) : (
          <>
            <span className="min-w-0 flex-1 truncate font-medium">{domain.name}</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() => setIsRenaming(true)}
            >
              Rename
            </Button>
          </>
        )}
      </div>

      {otherDomains.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            aria-label={`Merge ${domain.name} into`}
            value={mergeTargetId}
            onChange={(e) => setMergeTargetId(e.target.value)}
            disabled={isBusy}
            className="h-7 w-auto text-xs"
          >
            <option value="">Merge into…</option>
            {otherDomains.map((other) => (
              <option key={other.id} value={other.id}>
                {other.name}
              </option>
            ))}
          </Select>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            disabled={isBusy || !mergeTargetId}
            onClick={handleMerge}
          >
            Merge
          </Button>
        </div>
      )}

      <div>
        <AlertDialog>
          <AlertDialogTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Delete ${domain.name}`}
                className="h-7 text-xs text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                disabled={isBusy}
              />
            }
          >
            Delete
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete {domain.name}?</AlertDialogTitle>
              <AlertDialogDescription>
                Any document tagged with this domain is simply untagged — nothing about the
                document itself is deleted.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={handleDelete}>
                Delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}
    </li>
  );
}

function DomainsSection({ domains }: { domains: Domain[] }) {
  const [domainList, setDomainList] = useState(domains);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const domain = await createDomain(name);
      setDomainList((current) => [...current, domain].sort((a, b) => a.name.localeCompare(b.name)));
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
            Create a new domain
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex items-start gap-2">
            <Input
              aria-label="Domain name"
              placeholder="HR"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isSubmitting}
              required
            />
            <Button type="submit" disabled={isSubmitting || name.trim().length === 0}>
              {isSubmitting ? "Creating..." : "Create"}
            </Button>
          </form>
          {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      <ListCard
        icon={Tags}
        title="Domains"
        isEmpty={domainList.length === 0}
        emptyMessage="No domains yet — use the form above to create the first one. Documents can then be tagged with it at upload."
      >
        {domainList.map((domain, i) => (
          <DomainRow
            key={domain.id}
            domain={domain}
            otherDomains={domainList.filter((d) => d.id !== domain.id)}
            className={i > 0 ? "border-t border-border pt-3" : undefined}
            onRenamed={(renamed) =>
              setDomainList((current) =>
                current
                  .map((d) => (d.id === renamed.id ? renamed : d))
                  .sort((a, b) => a.name.localeCompare(b.name)),
              )
            }
            onMerged={(removedId, remaining) => setDomainList(remaining)}
            onDeleted={(removedId) =>
              setDomainList((current) => current.filter((d) => d.id !== removedId))
            }
          />
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
  reviewQueue,
  tenants,
  domains,
}: {
  auditEntries: AdminAuditEntry[];
  reviewQueue: ReviewQueueItem[];
  tenants: Tenant[];
  domains: Domain[];
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
        {activeSection === "review-queue" && <ReviewQueueSection documents={reviewQueue} />}
        {activeSection === "tenants" && <TenantsSection tenants={tenants} />}
        {activeSection === "domains" && <DomainsSection domains={domains} />}
      </div>
    </div>
  );
}

import { getAdmin, getDomains, getReviewQueue, getTenants } from "@/lib/server-api";
import { AdminDashboard } from "@/components/admin-dashboard";

// Admin data spans every user, not just the caller's — must never be
// frozen as a stale, build-time snapshot. Same reasoning as every other
// data page in this app (ADR-029/032/033).
export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const [admin, reviewQueue, tenants, domains] = await Promise.all([
    getAdmin(),
    getReviewQueue(),
    getTenants(),
    getDomains(),
  ]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-8 text-2xl font-semibold">Admin</h1>
      <AdminDashboard
        auditEntries={admin.audit_entries}
        reviewQueue={reviewQueue}
        tenants={tenants}
        domains={domains}
      />
    </div>
  );
}

import { Building2, Calendar, Mail, ShieldCheck } from "lucide-react";

import { getUserProfile } from "@/lib/server-api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Same reasoning as every other per-user page (ADR-029/ADR-032): this is
// the logged-in caller's own account info, never eligible for a shared,
// build-time-frozen prerender.
export const dynamic = "force-dynamic";

function formatMemberSince(createdAt: string) {
  return new Date(createdAt).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function ProfileRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 border-b border-border py-3 last:border-b-0">
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="truncate text-sm font-medium">{value}</span>
      </div>
    </div>
  );
}

export default async function ProfilePage() {
  const profile = await getUserProfile();

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="mb-8 text-2xl font-semibold">Profile</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Account information
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col">
          <ProfileRow icon={Mail} label="Email" value={profile.email} />
          <ProfileRow
            icon={ShieldCheck}
            label="Role"
            value={
              <Badge variant={profile.is_admin ? "default" : "outline"}>
                {profile.is_admin ? "Admin" : "Member"}
              </Badge>
            }
          />
          <ProfileRow icon={Building2} label="Organization" value={profile.tenant_name} />
          <ProfileRow
            icon={Calendar}
            label="Member since"
            value={formatMemberSince(profile.created_at)}
          />
        </CardContent>
      </Card>
    </div>
  );
}

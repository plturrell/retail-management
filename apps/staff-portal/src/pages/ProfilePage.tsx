import { useEffect, useState } from "react";
import { Mail, Phone, Briefcase, Globe2, Building2, CreditCard, Landmark } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";
import { formatMoney, formatDate } from "../lib/format";
import { PageHeader } from "../components/ui/PageHeader";
import { Card } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";
import { Badge } from "../components/ui/Badge";

interface UserMe {
  id: string;
  full_name: string;
  email: string;
  phone: string | null;
  store_roles: { store_id: string; role: string }[];
}

interface EmployeeProfile {
  date_of_birth: string;
  nationality: string;
  basic_salary: number;
  hourly_rate: number | null;
  commission_rate: number | null;
  bank_account: string | null;
  bank_name: string;
  cpf_account_number: string | null;
  start_date: string;
  end_date: string | null;
  is_active: boolean;
}

function Field({
  label,
  value,
  icon,
}: {
  label: string;
  value: string | null | undefined;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3">
      {icon && (
        <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--color-surface-subtle)] text-[var(--color-ink-secondary)]">
          {icon}
        </div>
      )}
      <div className="min-w-0">
        <dt className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
          {label}
        </dt>
        <dd className="mt-0.5 truncate text-sm font-medium text-[var(--color-ink-primary)]">
          {value || "—"}
        </dd>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const { user } = useAuth();
  const [me, setMe] = useState<UserMe | null>(null);
  const [profile, setProfile] = useState<EmployeeProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const meRes = await api.get<{ data: UserMe }>("/users/me");
        setMe(meRes.data);
        try {
          const profRes = await api.get<{ data: EmployeeProfile }>(
            `/employees/${meRes.data.id}/profile`,
          );
          setProfile(profRes.data);
        } catch {
          /* profile may not exist */
        }
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Profile" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
    );
  }

  const role = me?.store_roles?.[0]?.role;
  const roleLabel = role ? role.charAt(0).toUpperCase() + role.slice(1) : undefined;
  const statusActive = profile?.is_active;
  const nationalityLabel = profile?.nationality
    ? ({ citizen: "Singapore Citizen", pr: "Permanent Resident", foreigner: "Foreigner" } as const)[
        profile.nationality as "citizen" | "pr" | "foreigner"
      ] ?? profile.nationality
    : undefined;

  const initial = (me?.full_name?.[0] ?? me?.email?.[0] ?? user?.email?.[0] ?? "U").toUpperCase();

  return (
    <div className="space-y-6">
      <PageHeader title="Profile" description="Your account and employment details." />

      {/* Identity card */}
      <Card padding="lg">
        <div className="flex flex-col items-center gap-3 text-center sm:flex-row sm:items-center sm:gap-5 sm:text-left">
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-[var(--color-brand-500)] to-[var(--color-brand-700)] text-2xl font-bold text-white shadow-[var(--shadow-card)]">
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-bold text-[var(--color-ink-primary)]">
              {me?.full_name || me?.email || user?.email}
            </h2>
            <p className="mt-0.5 truncate text-sm text-[var(--color-ink-muted)]">
              {me?.email ?? user?.email}
            </p>
            <div className="mt-2 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
              {roleLabel && <Badge tone="brand">{roleLabel}</Badge>}
              {profile && (
                <Badge tone={statusActive ? "positive" : "neutral"}>
                  {statusActive ? "Active" : "Inactive"}
                </Badge>
              )}
            </div>
          </div>
        </div>
      </Card>

      {/* Personal info */}
      <Card padding="lg">
        <h3 className="text-base font-semibold text-[var(--color-ink-primary)]">
          Personal information
        </h3>
        <dl className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2">
          <Field label="Email" value={me?.email ?? user?.email} icon={<Mail size={16} />} />
          <Field label="Phone" value={me?.phone} icon={<Phone size={16} />} />
          <Field label="Role" value={roleLabel} icon={<Briefcase size={16} />} />
          <Field label="Nationality" value={nationalityLabel} icon={<Globe2 size={16} />} />
        </dl>
      </Card>

      {/* Employment details */}
      {profile && (
        <Card padding="lg">
          <h3 className="text-base font-semibold text-[var(--color-ink-primary)]">
            Employment details
          </h3>
          <dl className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2">
            <Field
              label="Hire date"
              value={profile.start_date ? formatDate(profile.start_date + "T00:00:00") : undefined}
              icon={<Building2 size={16} />}
            />
            {profile.end_date && (
              <Field
                label="End date"
                value={formatDate(profile.end_date + "T00:00:00")}
                icon={<Building2 size={16} />}
              />
            )}
            <Field label="Basic salary" value={formatMoney(profile.basic_salary)} />
            {profile.hourly_rate != null && (
              <Field label="Hourly rate" value={`${formatMoney(profile.hourly_rate)}/hr`} />
            )}
            {profile.commission_rate != null && (
              <Field label="Commission rate" value={`${profile.commission_rate}%`} />
            )}
          </dl>
        </Card>
      )}

      {/* Bank & CPF */}
      {profile && (profile.bank_account || profile.cpf_account_number) && (
        <Card padding="lg">
          <h3 className="text-base font-semibold text-[var(--color-ink-primary)]">Bank & CPF</h3>
          <dl className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2">
            <Field label="Bank" value={profile.bank_name} icon={<Landmark size={16} />} />
            <Field
              label="Bank account"
              value={profile.bank_account}
              icon={<CreditCard size={16} />}
            />
            <Field label="CPF account" value={profile.cpf_account_number} />
          </dl>
        </Card>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";

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

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs font-medium text-gray-400 uppercase tracking-wide">{label}</dt>
      <dd className="mt-0.5 text-sm text-gray-800">{value || "—"}</dd>
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
          const profRes = await api.get<{ data: EmployeeProfile }>(`/employees/${meRes.data.id}/profile`);
          setProfile(profRes.data);
        } catch { /* profile may not exist */ }
      } catch { /* ignore */ }
      finally { setLoading(false); }
    })();
  }, []);

  if (loading) return <div className="flex items-center justify-center py-20 text-gray-400">Loading profile…</div>;

  const role = me?.store_roles?.[0]?.role;
  const statusLabel = profile?.is_active ? "Active" : profile ? "Inactive" : undefined;
  const nationalityLabel = profile?.nationality
    ? { citizen: "Singapore Citizen", pr: "Permanent Resident", foreigner: "Foreigner" }[profile.nationality] ?? profile.nationality
    : undefined;

  return (
    <div>
      <h1 className="text-xl font-bold text-gray-800">Profile</h1>
      <p className="mt-1 text-sm text-gray-500">Your account and employment details.</p>

      {/* Personal info */}
      <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Personal Information</h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Full Name" value={me?.full_name} />
          <Field label="Email" value={me?.email ?? user?.email} />
          <Field label="Phone" value={me?.phone} />
          <Field label="Role" value={role ? role.charAt(0).toUpperCase() + role.slice(1) : undefined} />
          <Field label="Nationality" value={nationalityLabel} />
          <Field label="Employment Status" value={statusLabel} />
        </dl>
      </div>

      {/* Employment details */}
      {profile && (
        <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Employment Details</h2>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Hire Date" value={profile.start_date ? new Date(profile.start_date + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" }) : undefined} />
            {profile.end_date && <Field label="End Date" value={new Date(profile.end_date + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" })} />}
            <Field label="Basic Salary" value={`$${profile.basic_salary.toFixed(2)}`} />
            {profile.hourly_rate != null && <Field label="Hourly Rate" value={`$${profile.hourly_rate.toFixed(2)}/hr`} />}
            {profile.commission_rate != null && <Field label="Commission Rate" value={`${profile.commission_rate}%`} />}
          </dl>
        </div>
      )}

      {/* Bank details */}
      {profile && (profile.bank_account || profile.cpf_account_number) && (
        <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Bank & CPF</h2>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Bank" value={profile.bank_name} />
            <Field label="Bank Account" value={profile.bank_account} />
            <Field label="CPF Account" value={profile.cpf_account_number} />
          </dl>
        </div>
      )}
    </div>
  );
}

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { cagExportApi, type CagErrorEntry, type CagPushResponse } from "../lib/master-data-api";
import { Icon, type IconName } from "../components/Icon";

interface StoreSummary {
  id: string;
  store_code: string | null;
  name: string;
  location: string;
  nec_tenant_code: string | null;
  nec_store_id: string | null;
  nec_taxable: boolean;
}

interface PaginatedStores {
  data: StoreSummary[];
  total: number;
}

/* ----------------------------------------------------------------------- */
/* Types                                                                   */
/* ----------------------------------------------------------------------- */

interface CagConfigPublic {
  host: string;
  port: number;
  username: string;
  key_path: string;
  tenant_folder: string;
  inbound_working: string;
  inbound_error: string;
  inbound_archive: string;
  default_nec_store_id: string;
  default_taxable: boolean;
  scheduler_enabled: boolean;
  scheduler_cron: string;
  scheduler_default_tenant: string;
  scheduler_default_store_id: string;
  scheduler_default_taxable: boolean;
  scheduler_last_run_at: string;
  scheduler_last_run_status: string;
  scheduler_last_run_message: string;
  scheduler_last_run_files: number;
  scheduler_last_run_bytes: number;
  scheduler_last_run_trigger: string;
  scheduler_sa_email: string;
  scheduler_audience: string;
  has_password: boolean;
  has_key_passphrase: boolean;
  is_configured: boolean;
  updated_at: string;
  updated_by: string;
}

interface TestResponse {
  ok: boolean;
  message: string;
  working_dir?: string;
  error_dir?: string;
  archive_dir?: string;
}

type ReadinessState = "ok" | "warn" | "fail";

interface ReadinessCheck {
  id: string;
  label: string;
  detail: string;
  state: ReadinessState;
  icon: IconName;
}

type FormState = {
  host: string;
  port: string;
  username: string;
  password: string;
  key_path: string;
  key_passphrase: string;
  tenant_folder: string;
  inbound_working: string;
  inbound_error: string;
  inbound_archive: string;
  default_nec_store_id: string;
  default_taxable: boolean;
  scheduler_enabled: boolean;
  scheduler_cron: string;
  scheduler_default_tenant: string;
  scheduler_default_store_id: string;
  scheduler_default_taxable: boolean;
};

const EMPTY: FormState = {
  host: "",
  port: "22",
  username: "",
  password: "",
  key_path: "",
  key_passphrase: "",
  tenant_folder: "",
  inbound_working: "Inbound/Working",
  inbound_error: "Inbound/Error",
  inbound_archive: "Inbound/Archive",
  default_nec_store_id: "",
  default_taxable: true,
  scheduler_enabled: true,
  scheduler_cron: "0 */3 * * *",
  scheduler_default_tenant: "",
  scheduler_default_store_id: "",
  scheduler_default_taxable: false,
};

/* ----------------------------------------------------------------------- */

function fromConfig(cfg: CagConfigPublic): FormState {
  return {
    host: cfg.host ?? "",
    port: String(cfg.port ?? 22),
    username: cfg.username ?? "",
    password: "",
    key_path: cfg.key_path ?? "",
    key_passphrase: "",
    tenant_folder: cfg.tenant_folder ?? "",
    inbound_working: cfg.inbound_working || "Inbound/Working",
    inbound_error: cfg.inbound_error || "Inbound/Error",
    inbound_archive: cfg.inbound_archive || "Inbound/Archive",
    default_nec_store_id: cfg.default_nec_store_id ?? "",
    default_taxable: cfg.default_taxable ?? true,
    scheduler_enabled: cfg.scheduler_enabled ?? true,
    scheduler_cron: cfg.scheduler_cron || "0 */3 * * *",
    scheduler_default_tenant: cfg.scheduler_default_tenant ?? "",
    scheduler_default_store_id: cfg.scheduler_default_store_id ?? "",
    scheduler_default_taxable: cfg.scheduler_default_taxable ?? false,
  };
}

function isFiveDigitNecId(value: string | null | undefined): boolean {
  return /^\d{5}$/.test((value ?? "").trim());
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function taxModeLabel(taxable: boolean): string {
  return taxable ? "Landside (G)" : "Airside (N)";
}

export default function CagSettingsPage() {
  const [cfg, setCfg] = useState<CagConfigPublic | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [runningPush, setRunningPush] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err" | "info"; text: string } | null>(null);
  const [testResult, setTestResult] = useState<TestResponse | null>(null);
  const [pushResult, setPushResult] = useState<CagPushResponse | null>(null);
  const [errorEntries, setErrorEntries] = useState<CagErrorEntry[]>([]);
  const [errorsLoading, setErrorsLoading] = useState(false);
  const [errorFetchMsg, setErrorFetchMsg] = useState<string | null>(null);
  const [errorsLoadedAt, setErrorsLoadedAt] = useState<string>("");

  // Per-store NEC mapping table state.
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [storeDrafts, setStoreDrafts] = useState<Record<string, Partial<StoreSummary>>>({});
  const [storesLoading, setStoresLoading] = useState(false);
  const [storeSavingId, setStoreSavingId] = useState<string | null>(null);

  const loadStores = useCallback(async () => {
    setStoresLoading(true);
    try {
      const res = await api.get<PaginatedStores>("/stores?page=1&page_size=200");
      setStores(res.data ?? []);
      setStoreDrafts({});
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? `Stores load failed: ${e.message}` : "Stores load failed" });
    } finally {
      setStoresLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<CagConfigPublic>("/cag/config");
      setCfg(res);
      setForm(fromConfig(res));
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Failed to load config" });
    } finally {
      setLoading(false);
    }
  }, []);

  const loadErrorEntries = useCallback(async () => {
    setErrorsLoading(true);
    try {
      const entries = await cagExportApi.errors(50);
      setErrorEntries(entries);
      setErrorFetchMsg(null);
      setErrorsLoadedAt(new Date().toISOString());
    } catch (e) {
      setErrorFetchMsg(e instanceof Error ? e.message : "Failed to load CAG errors");
    } finally {
      setErrorsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadStores();
  }, [load, loadStores]);

  useEffect(() => {
    if (!cfg?.is_configured) return;
    void loadErrorEntries();
  }, [cfg?.is_configured, loadErrorEntries]);

  const updateStoreDraft = (id: string, patch: Partial<StoreSummary>) =>
    setStoreDrafts((d) => ({ ...d, [id]: { ...(d[id] ?? {}), ...patch } }));

  const saveStoreRow = async (store: StoreSummary) => {
    const draft = storeDrafts[store.id];
    if (!draft) return;
    setStoreSavingId(store.id);
    try {
      const patch: Record<string, unknown> = {};
      if (draft.nec_tenant_code !== undefined) patch.nec_tenant_code = draft.nec_tenant_code || null;
      if (draft.nec_store_id !== undefined) patch.nec_store_id = draft.nec_store_id || null;
      if (draft.nec_taxable !== undefined) patch.nec_taxable = draft.nec_taxable;
      const res = await api.patch<{ data: StoreSummary }>(`/stores/${store.id}`, patch);
      const updated = (res as unknown as { data: StoreSummary }).data ?? (res as unknown as StoreSummary);
      setStores((list) => list.map((s) => (s.id === store.id ? { ...s, ...updated } : s)));
      setStoreDrafts((d) => {
        const next = { ...d };
        delete next[store.id];
        return next;
      });
      setMsg({ kind: "ok", text: `Saved ${store.store_code ?? store.name}` });
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setStoreSavingId(null);
    }
  };

  const dirtyStoreIds = useMemo(() => new Set(Object.keys(storeDrafts)), [storeDrafts]);
  const savedForm = useMemo(() => (cfg ? fromConfig(cfg) : EMPTY), [cfg]);
  const formDirty = useMemo(() => {
    if (!cfg) return false;
    const keys = Object.keys(savedForm) as Array<keyof FormState>;
    const hasFieldChanges = keys.some((key) => form[key] !== savedForm[key]);
    return hasFieldChanges || Boolean(form.password || form.key_passphrase);
  }, [cfg, form, savedForm]);
  const effectiveTenant = cfg?.scheduler_default_tenant || cfg?.tenant_folder || "";
  const effectiveStoreId = cfg?.scheduler_default_store_id || cfg?.default_nec_store_id || "";
  const effectiveTaxable = cfg?.scheduler_default_taxable ?? false;
  const latestFailedErrors = useMemo(
    () => errorEntries.filter((entry) => entry.status.toLowerCase() === "failed"),
    [errorEntries],
  );
  const readinessChecks = useMemo<ReadinessCheck[]>(() => {
    const schedulerIdentityOk = Boolean(cfg?.scheduler_sa_email && cfg?.scheduler_audience);
    const lastPushState: ReadinessState = !cfg?.scheduler_last_run_at
      ? "warn"
      : cfg.scheduler_last_run_status === "success"
        ? "ok"
        : "fail";
    const errorsState: ReadinessState = errorFetchMsg
      ? "warn"
      : errorsLoadedAt
        ? latestFailedErrors.length === 0
          ? "ok"
          : "fail"
        : "warn";

    return [
      {
        id: "saved",
        label: "Saved settings",
        detail: formDirty || dirtyStoreIds.size > 0 ? "Unsaved changes pending" : "Saved values are active",
        state: formDirty || dirtyStoreIds.size > 0 ? "warn" : "ok",
        icon: "document",
      },
      {
        id: "sftp",
        label: "SFTP credentials",
        detail: cfg?.is_configured ? `${cfg.host}:${cfg.port} as ${cfg.username}` : "Host, username, and auth required",
        state: cfg?.is_configured ? "ok" : "fail",
        icon: "lock",
      },
      {
        id: "tenant",
        label: "Tenant folder",
        detail: effectiveTenant || "Missing tenant/customer number",
        state: effectiveTenant ? "ok" : "fail",
        icon: "archive",
      },
      {
        id: "store",
        label: "NEC Store ID",
        detail: effectiveStoreId || "Missing 5-digit NEC Store ID",
        state: isFiveDigitNecId(effectiveStoreId) ? "ok" : "fail",
        icon: "home",
      },
      {
        id: "scheduler",
        label: "Scheduler identity",
        detail: schedulerIdentityOk ? cfg?.scheduler_sa_email ?? "" : "OIDC env vars missing",
        state: schedulerIdentityOk ? "ok" : "fail",
        icon: "clock",
      },
      {
        id: "connection",
        label: "Connection test",
        detail: testResult ? testResult.message : "Not tested in this session",
        state: testResult ? (testResult.ok ? "ok" : "fail") : "warn",
        icon: "database",
      },
      {
        id: "last-push",
        label: "Last push",
        detail: cfg?.scheduler_last_run_at
          ? `${cfg.scheduler_last_run_status || "unknown"} · ${formatDateTime(cfg.scheduler_last_run_at)}`
          : "No recorded push yet",
        state: lastPushState,
        icon: "package",
      },
      {
        id: "remote-errors",
        label: "Remote errors",
        detail: errorFetchMsg
          ? "Error log fetch failed"
          : errorsLoadedAt
            ? latestFailedErrors.length === 0
              ? "No failed CAG log rows"
              : `${latestFailedErrors.length} failed row(s)`
            : "Not loaded yet",
        state: errorsState,
        icon: "alert",
      },
    ];
  }, [
    cfg,
    dirtyStoreIds.size,
    effectiveStoreId,
    effectiveTenant,
    errorFetchMsg,
    errorsLoadedAt,
    formDirty,
    latestFailedErrors.length,
    testResult,
  ]);
  const readyCount = readinessChecks.filter((check) => check.state === "ok").length;
  const canRunScheduledPush = Boolean(
    cfg?.is_configured &&
      effectiveTenant &&
      isFiveDigitNecId(effectiveStoreId) &&
      !formDirty &&
      dirtyStoreIds.size === 0,
  );

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const onSave = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const patch: Record<string, unknown> = {
        host: form.host.trim(),
        port: Number(form.port) || 22,
        username: form.username.trim(),
        key_path: form.key_path.trim(),
        tenant_folder: form.tenant_folder.trim(),
        inbound_working: form.inbound_working.trim() || "Inbound/Working",
        inbound_error: form.inbound_error.trim() || "Inbound/Error",
        inbound_archive: form.inbound_archive.trim() || "Inbound/Archive",
        default_nec_store_id: form.default_nec_store_id.trim(),
        default_taxable: form.default_taxable,
        scheduler_enabled: form.scheduler_enabled,
        scheduler_cron: form.scheduler_cron.trim() || "0 */3 * * *",
        scheduler_default_tenant: form.scheduler_default_tenant.trim(),
        scheduler_default_store_id: form.scheduler_default_store_id.trim(),
        scheduler_default_taxable: form.scheduler_default_taxable,
      };
      // Send secrets only if the user typed something — empty string keeps existing.
      if (form.password) patch.password = form.password;
      if (form.key_passphrase) patch.key_passphrase = form.key_passphrase;

      const updated = await api.put<CagConfigPublic>("/cag/config", patch);
      setCfg(updated);
      setForm(fromConfig(updated));
      setMsg({ kind: "ok", text: "Settings saved." });
      if (updated.is_configured) void loadErrorEntries();
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  };

  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    setMsg(null);
    try {
      const res = await api.post<TestResponse>("/cag/config/test", {});
      setTestResult(res);
      setMsg({
        kind: res.ok ? "ok" : "err",
        text: res.ok ? "SFTP connection OK." : `SFTP test failed: ${res.message}`,
      });
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Test failed" });
    } finally {
      setTesting(false);
    }
  };

  const onClear = async () => {
    if (!confirm("Wipe the saved CAG config? Environment defaults (.env) will remain.")) return;
    setClearing(true);
    try {
      const updated = await api.delete<CagConfigPublic>("/cag/config");
      setCfg(updated);
      setForm(fromConfig(updated));
      setErrorEntries([]);
      setErrorFetchMsg(null);
      setErrorsLoadedAt("");
      setMsg({ kind: "info", text: "Cleared. Falling back to .env defaults (if any)." });
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Clear failed" });
    } finally {
      setClearing(false);
    }
  };

  const onRunScheduledPush = async () => {
    if (
      !confirm(
        "Run the NEC CAG scheduled push now using the current defaults? " +
          "This uploads the live master bundle to the configured SFTP target.",
      )
    )
      return;
    setRunningPush(true);
    setPushResult(null);
    setMsg(null);
    try {
      const res = await cagExportApi.testScheduledPush({});
      setPushResult(res);
      const ok = (res.errors || []).length === 0;
      setMsg({
        kind: ok ? "ok" : "err",
        text: ok
          ? `Push OK — ${res.files_uploaded.length} file(s), ${res.bytes_uploaded} bytes.`
          : `Push completed with errors: ${res.errors.join("; ")}`,
      });
      // Refresh config so the last-run telemetry banner updates immediately.
      await load();
      await loadErrorEntries();
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "On-demand push failed" });
    } finally {
      setRunningPush(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-1">
      <header>
        <h1 className="text-xl font-bold text-gray-800">CAG / NEC POS — Integration Settings</h1>
        <p className="mt-1 text-xs text-gray-500">
          SFTP credentials + tenant identifiers used by the master-file uploader and the
          Data Quality "TXT (.zip) / Push SFTP" buttons. Secrets are stored in Firestore
          and never returned to the browser. Leave password / passphrase blank to keep
          the previously-saved value.
        </p>
        {cfg && (
          <p className="mt-1 text-[11px] text-gray-400">
            Status:{" "}
            <span className={cfg.is_configured ? "font-semibold text-emerald-700" : "font-semibold text-amber-700"}>
              {cfg.is_configured ? "configured" : "incomplete"}
            </span>
            {cfg.updated_at && (
              <>
                {" · last updated "}
                {new Date(cfg.updated_at).toLocaleString()}
                {cfg.updated_by ? ` by ${cfg.updated_by}` : ""}
              </>
            )}
          </p>
        )}
      </header>

      {msg && (
        <div
          className={
            msg.kind === "ok"
              ? "rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700"
              : msg.kind === "info"
                ? "rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-700"
                : "rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
          }
        >
          {msg.text}
        </div>
      )}

      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-800">Go-live console</h2>
            <p className="mt-1 text-xs text-gray-500">
              {readyCount} of {readinessChecks.length} checks ready
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <Metric label="Tenant" value={effectiveTenant || "Missing"} tone={effectiveTenant ? "ok" : "fail"} />
            <Metric
              label="NEC Store"
              value={effectiveStoreId || "Missing"}
              tone={isFiveDigitNecId(effectiveStoreId) ? "ok" : "fail"}
            />
            <Metric label="Tax mode" value={taxModeLabel(effectiveTaxable)} tone="ok" />
            <Metric
              label="Last push"
              value={cfg?.scheduler_last_run_status || "None"}
              tone={cfg?.scheduler_last_run_status === "success" ? "ok" : cfg?.scheduler_last_run_status ? "fail" : "warn"}
            />
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
          {readinessChecks.map((check) => (
            <ReadinessItem key={check.id} check={check} />
          ))}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-[1fr_1.4fr]">
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs">
            <div className="mb-2 flex items-center justify-between">
              <div className="font-semibold text-gray-700">Effective scheduled payload</div>
              <StatusPill state={cfg?.scheduler_enabled ? "ok" : "warn"} label={cfg?.scheduler_enabled ? "enabled" : "paused"} />
            </div>
            <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-gray-600">
              <dt className="text-gray-400">Tenant</dt>
              <dd className="font-mono">{effectiveTenant || "—"}</dd>
              <dt className="text-gray-400">Store ID</dt>
              <dd className="font-mono">{effectiveStoreId || "—"}</dd>
              <dt className="text-gray-400">Tax code</dt>
              <dd>{effectiveTaxable ? "G — taxable" : "N — non-taxable"}</dd>
              <dt className="text-gray-400">Cron</dt>
              <dd className="font-mono">{cfg?.scheduler_cron || "—"}</dd>
              <dt className="text-gray-400">Audience</dt>
              <dd className="truncate" title={cfg?.scheduler_audience || ""}>
                {cfg?.scheduler_audience || "—"}
              </dd>
            </dl>
          </div>

          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="font-semibold text-gray-700">Latest CAG error logs</div>
                <div className="text-[11px] text-gray-400">
                  {errorsLoadedAt ? `Loaded ${formatDateTime(errorsLoadedAt)}` : "Not loaded"}
                </div>
              </div>
              <button
                onClick={() => void loadErrorEntries()}
                disabled={errorsLoading || !cfg?.is_configured}
                className="rounded-md bg-gray-200 px-2 py-1 text-[11px] font-semibold text-gray-700 hover:bg-gray-300 disabled:opacity-50"
              >
                {errorsLoading ? "Loading..." : "Refresh errors"}
              </button>
            </div>
            {errorFetchMsg && <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-amber-800">{errorFetchMsg}</div>}
            {!errorFetchMsg && !errorsLoadedAt && (
              <div className="rounded border border-gray-200 bg-white px-2 py-2 text-gray-500">
                Error logs have not been refreshed.
              </div>
            )}
            {!errorFetchMsg && errorsLoadedAt && errorEntries.length === 0 && (
              <div className="rounded border border-emerald-200 bg-emerald-50 px-2 py-2 text-emerald-800">
                No CAG error rows returned.
              </div>
            )}
            {errorEntries.length > 0 && (
              <div className="max-h-48 overflow-y-auto rounded border border-gray-200 bg-white">
                {errorEntries.slice(0, 12).map((entry, idx) => (
                  <div
                    key={`${entry.source_file ?? "inline"}:${entry.line}:${idx}`}
                    className="border-b border-gray-100 px-2 py-2 last:border-b-0"
                  >
                    <div className="flex items-center gap-2">
                      <StatusPill
                        state={entry.status.toLowerCase() === "failed" ? "fail" : "warn"}
                        label={entry.status}
                      />
                      <span className="text-[11px] text-gray-400">line {entry.line}</span>
                      {entry.source_file && <span className="truncate text-[11px] text-gray-400">{entry.source_file}</span>}
                    </div>
                    <div className="mt-1 break-words text-gray-700">{entry.message}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      <Section title="SFTP server (provided by NEC)">
        <Field label="Host" hint="e.g. sftp.cag.example.com">
          <input className={inputCls} value={form.host} onChange={(e) => update("host", e.target.value)} />
        </Field>
        <Field label="Port">
          <input
            type="number"
            inputMode="numeric"
            className={inputCls}
            value={form.port}
            onChange={(e) => update("port", e.target.value)}
          />
        </Field>
        <Field label="Username">
          <input className={inputCls} value={form.username} onChange={(e) => update("username", e.target.value)} />
        </Field>
        <Field
          label="Password"
          hint={cfg?.has_password ? "(saved — leave blank to keep)" : "Optional if using key auth"}
        >
          <input
            type="password"
            className={inputCls}
            value={form.password}
            onChange={(e) => update("password", e.target.value)}
            autoComplete="new-password"
            placeholder={cfg?.has_password ? "•••••• (unchanged)" : ""}
          />
        </Field>
        <Field label="Private key path" hint="Server-side absolute path; preferred over password">
          <input className={inputCls} value={form.key_path} onChange={(e) => update("key_path", e.target.value)} />
        </Field>
        <Field
          label="Key passphrase"
          hint={cfg?.has_key_passphrase ? "(saved — leave blank to keep)" : "Optional"}
        >
          <input
            type="password"
            className={inputCls}
            value={form.key_passphrase}
            onChange={(e) => update("key_passphrase", e.target.value)}
            autoComplete="new-password"
            placeholder={cfg?.has_key_passphrase ? "•••••• (unchanged)" : ""}
          />
        </Field>
      </Section>

      <Section title="Tenant identifiers (provided by CAG / Jewel)">
        <Field label="Tenant folder" hint="6/7-digit Customer No. (e.g. 200151)">
          <input
            className={inputCls}
            value={form.tenant_folder}
            onChange={(e) => update("tenant_folder", e.target.value)}
          />
        </Field>
        <Field label="Default NEC Store ID" hint="5-digit Store ID assigned by NEC (e.g. 80001)">
          <input
            className={inputCls}
            inputMode="numeric"
            maxLength={5}
            value={form.default_nec_store_id}
            onChange={(e) => update("default_nec_store_id", e.target.value)}
          />
        </Field>
        <Field label="Default tax mode" hint="Landside stores price inclusive of GST; airside is exclusive">
          <select
            className={inputCls}
            value={form.default_taxable ? "landside" : "airside"}
            onChange={(e) => update("default_taxable", e.target.value === "landside")}
          >
            <option value="landside">Landside (taxable, GST inclusive)</option>
            <option value="airside">Airside (non-taxable, GST exclusive)</option>
          </select>
        </Field>
      </Section>

      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-700">Per-store NEC mappings</h2>
            <p className="mt-0.5 text-[11px] text-gray-500">
              Each store needs its own 5-digit NEC Store ID and tax mode (landside G / airside N).
              Per-store values override the defaults above when generating master files.
            </p>
          </div>
          <button
            onClick={() => void loadStores()}
            disabled={storesLoading}
            className="rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-200 disabled:opacity-50"
          >
            {storesLoading ? "Loading…" : "Refresh"}
          </button>
        </div>
        {stores.length === 0 ? (
          <p className="text-xs italic text-gray-400">
            {storesLoading ? "Loading stores…" : "No stores accessible to this account."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-gray-50 text-[11px] uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-2 py-1 text-left">Store</th>
                  <th className="px-2 py-1 text-left">Code</th>
                  <th className="px-2 py-1 text-left">NEC Tenant</th>
                  <th className="px-2 py-1 text-left">NEC Store ID</th>
                  <th className="px-2 py-1 text-left">Tax mode</th>
                  <th className="px-2 py-1" />
                </tr>
              </thead>
              <tbody>
                {stores.map((s) => {
                  const draft = storeDrafts[s.id] ?? {};
                  const tenantVal = draft.nec_tenant_code ?? s.nec_tenant_code ?? "";
                  const idVal = draft.nec_store_id ?? s.nec_store_id ?? "";
                  const taxableVal = draft.nec_taxable ?? s.nec_taxable;
                  const dirty = dirtyStoreIds.has(s.id);
                  const validId = !idVal || /^\d{5}$/.test(idVal);
                  return (
                    <tr key={s.id} className={dirty ? "bg-amber-50" : "border-t border-gray-100"}>
                      <td className="px-2 py-1.5 font-medium text-gray-700">{s.name}</td>
                      <td className="px-2 py-1 text-gray-500">{s.store_code ?? "—"}</td>
                      <td className="px-2 py-1">
                        <input
                          className="w-32 rounded border border-gray-300 px-2 py-1 text-xs"
                          placeholder="(use default)"
                          value={tenantVal}
                          onChange={(e) =>
                            updateStoreDraft(s.id, { nec_tenant_code: e.target.value })
                          }
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          inputMode="numeric"
                          maxLength={5}
                          className={`w-24 rounded border px-2 py-1 text-xs ${
                            validId ? "border-gray-300" : "border-red-400 bg-red-50"
                          }`}
                          placeholder="80001"
                          value={idVal}
                          onChange={(e) => updateStoreDraft(s.id, { nec_store_id: e.target.value })}
                        />
                      </td>
                      <td className="px-2 py-1">
                        <select
                          className="rounded border border-gray-300 px-2 py-1 text-xs"
                          value={taxableVal ? "G" : "N"}
                          onChange={(e) =>
                            updateStoreDraft(s.id, { nec_taxable: e.target.value === "G" })
                          }
                        >
                          <option value="G">Landside (G — taxable)</option>
                          <option value="N">Airside (N — non-taxable)</option>
                        </select>
                      </td>
                      <td className="px-2 py-1 text-right">
                        <button
                          onClick={() => void saveStoreRow(s)}
                          disabled={!dirty || storeSavingId === s.id || !validId}
                          className="rounded bg-blue-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-blue-700 disabled:opacity-40"
                        >
                          {storeSavingId === s.id ? "Saving…" : dirty ? "Save" : "—"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Section title="SFTP folders (rarely changed)">
        <Field label="Inbound / Working">
          <input
            className={inputCls}
            value={form.inbound_working}
            onChange={(e) => update("inbound_working", e.target.value)}
          />
        </Field>
        <Field label="Inbound / Error">
          <input
            className={inputCls}
            value={form.inbound_error}
            onChange={(e) => update("inbound_error", e.target.value)}
          />
        </Field>
        <Field label="Inbound / Archive">
          <input
            className={inputCls}
            value={form.inbound_archive}
            onChange={(e) => update("inbound_archive", e.target.value)}
          />
        </Field>
      </Section>

      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Scheduled push (Cloud Scheduler)</h2>
          <p className="mt-0.5 text-[11px] text-gray-500">
            Defaults below are read by the Cloud-Scheduler-triggered push and the
            on-demand <em>Run scheduled push now</em> button. The cron expression
            is informational — the actual schedule lives in Google Cloud Scheduler
            and is provisioned via{" "}
            <code className="rounded bg-gray-100 px-1">backend/scripts/setup_cag_scheduler.sh</code>.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Enabled" hint="Toggle off to mark the schedule as paused (informational)">
            <select
              className={inputCls}
              value={form.scheduler_enabled ? "yes" : "no"}
              onChange={(e) => update("scheduler_enabled", e.target.value === "yes")}
            >
              <option value="yes">Enabled</option>
              <option value="no">Paused</option>
            </select>
          </Field>
          <Field label="Cron expression" hint="Default: every 3 hours (0 */3 * * *)">
            <input
              className={inputCls}
              value={form.scheduler_cron}
              onChange={(e) => update("scheduler_cron", e.target.value)}
              placeholder="0 */3 * * *"
            />
          </Field>
          <Field label="Default tenant code" hint="Falls back to the tenant folder above if blank">
            <input
              className={inputCls}
              value={form.scheduler_default_tenant}
              onChange={(e) => update("scheduler_default_tenant", e.target.value)}
              placeholder={form.tenant_folder || "200151"}
            />
          </Field>
          <Field label="Default NEC Store ID" hint="5-digit Store ID used by the unattended push">
            <input
              className={inputCls}
              inputMode="numeric"
              maxLength={5}
              value={form.scheduler_default_store_id}
              onChange={(e) => update("scheduler_default_store_id", e.target.value)}
              placeholder={form.default_nec_store_id || "80001"}
            />
          </Field>
          <Field label="Default tax mode" hint="Landside = G (taxable); Airside = N (non-taxable)">
            <select
              className={inputCls}
              value={form.scheduler_default_taxable ? "landside" : "airside"}
              onChange={(e) =>
                update("scheduler_default_taxable", e.target.value === "landside")
              }
            >
              <option value="landside">Landside (taxable, GST inclusive)</option>
              <option value="airside">Airside (non-taxable, GST exclusive)</option>
            </select>
          </Field>
          <Field label="Service account (read-only)" hint="OIDC identity Cloud Scheduler authenticates as">
            <input
              className={`${inputCls} bg-gray-50 text-gray-500`}
              value={cfg?.scheduler_sa_email || ""}
              readOnly
              placeholder="(env: CAG_SCHEDULER_SA_EMAIL)"
            />
          </Field>
        </div>

        {cfg?.scheduler_last_run_at && (
          <div
            className={`mt-3 rounded-lg border p-3 text-xs ${
              cfg.scheduler_last_run_status === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                : "border-red-200 bg-red-50 text-red-800"
            }`}
          >
            <div className="font-semibold">
              Last run · {cfg.scheduler_last_run_status || "unknown"}
              {cfg.scheduler_last_run_trigger ? ` (${cfg.scheduler_last_run_trigger})` : ""}
            </div>
            <div className="mt-1">
              {new Date(cfg.scheduler_last_run_at).toLocaleString()} —{" "}
              {cfg.scheduler_last_run_files} file(s), {cfg.scheduler_last_run_bytes} bytes
            </div>
            {cfg.scheduler_last_run_message && (
              <div className="mt-1 text-[11px] opacity-80">{cfg.scheduler_last_run_message}</div>
            )}
          </div>
        )}
      </section>

      {testResult && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
          <div className="font-semibold">Connection test result</div>
          <div className="mt-1">{testResult.message}</div>
          {testResult.working_dir && (
            <div className="mt-1 grid grid-cols-3 gap-2 text-[11px] text-gray-500">
              <div>working: {testResult.working_dir}</div>
              <div>error: {testResult.error_dir}</div>
              <div>archive: {testResult.archive_dir}</div>
            </div>
          )}
        </div>
      )}

      {pushResult && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
          <div className="font-semibold">On-demand push result</div>
          <div className="mt-1">
            {pushResult.files_uploaded.length} file(s), {pushResult.bytes_uploaded} bytes — started{" "}
            {new Date(pushResult.started_at).toLocaleTimeString()}
            {pushResult.finished_at
              ? `, finished ${new Date(pushResult.finished_at).toLocaleTimeString()}`
              : ""}
          </div>
          {pushResult.files_uploaded.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-[11px] text-gray-500">
              {pushResult.files_uploaded.slice(0, 8).map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          )}
          {pushResult.errors.length > 0 && (
            <div className="mt-1 text-[11px] text-red-700">{pushResult.errors.join("; ")}</div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={onSave}
          disabled={saving}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save settings"}
        </button>
        <button
          onClick={onTest}
          disabled={testing}
          className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
        >
          {testing ? "Testing..." : "Test SFTP connection"}
        </button>
        <button
          onClick={onRunScheduledPush}
          disabled={runningPush || !canRunScheduledPush}
          title={
            canRunScheduledPush
              ? "Run the scheduled NEC CAG push now using the defaults above"
              : "Save complete CAG settings with a valid 5-digit NEC Store ID first"
          }
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {runningPush ? "Pushing..." : "Run scheduled push now"}
        </button>
        <button
          onClick={onClear}
          disabled={clearing}
          className="rounded-lg bg-gray-200 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-300 disabled:opacity-50"
        >
          {clearing ? "Clearing..." : "Clear saved values"}
        </button>
        <button
          onClick={() => void load()}
          className="ml-auto rounded-lg bg-gray-100 px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-200"
        >
          Reload
        </button>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------------- */
/* Layout helpers                                                          */
/* ----------------------------------------------------------------------- */

const inputCls =
  "w-full rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200";

function stateClasses(state: ReadinessState): string {
  if (state === "ok") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (state === "warn") return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-red-200 bg-red-50 text-red-800";
}

function StatusPill({ state, label }: { state: ReadinessState; label: string }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${stateClasses(state)}`}>
      {label}
    </span>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone: ReadinessState }) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${stateClasses(tone)}`}>
      <div className="text-[10px] font-semibold uppercase opacity-70">{label}</div>
      <div className="mt-0.5 truncate text-sm font-semibold" title={value}>
        {value}
      </div>
    </div>
  );
}

function ReadinessItem({ check }: { check: ReadinessCheck }) {
  return (
    <div className={`flex min-h-20 gap-3 rounded-lg border p-3 ${stateClasses(check.state)}`}>
      <div className="mt-0.5">
        <Icon name={check.icon} className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="font-semibold">{check.label}</div>
        <div className="mt-1 truncate text-[11px] opacity-80" title={check.detail}>
          {check.detail}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold text-gray-700">{title}</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{children}</div>
    </section>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="font-medium text-gray-700">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-gray-400">{hint}</span>}
    </label>
  );
}

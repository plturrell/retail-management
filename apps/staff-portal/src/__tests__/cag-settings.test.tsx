import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import CagSettingsPage from "../pages/CagSettingsPage";
import { api } from "../lib/api";
import { cagExportApi } from "../lib/master-data-api";

vi.mock("../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

vi.mock("../lib/master-data-api", () => ({
  cagExportApi: { errors: vi.fn(), testScheduledPush: vi.fn() },
}));

const mockedApi = api as unknown as { get: Mock; post: Mock; put: Mock; patch: Mock; delete: Mock };
const mockedTest = cagExportApi.testScheduledPush as unknown as Mock;
const mockedErrors = cagExportApi.errors as unknown as Mock;

const baseConfig = {
  host: "sftp.example.com",
  port: 22,
  username: "u",
  key_path: "",
  tenant_folder: "200151",
  inbound_working: "Inbound/Working",
  inbound_error: "Inbound/Error",
  inbound_archive: "Inbound/Archive",
  default_nec_store_id: "80001",
  default_taxable: true,
  scheduler_enabled: true,
  scheduler_cron: "0 */3 * * *",
  scheduler_default_tenant: "200151",
  scheduler_default_store_id: "80001",
  scheduler_default_taxable: false,
  scheduler_last_run_at: "2026-04-29T05:30:00Z",
  scheduler_last_run_status: "success",
  scheduler_last_run_message: "OK",
  scheduler_last_run_files: 6,
  scheduler_last_run_bytes: 1234,
  scheduler_last_run_trigger: "scheduler",
  scheduler_sa_email: "cag-scheduler@victoriaenso.iam.gserviceaccount.com",
  scheduler_audience: "https://retailsg-api-victoriaenso.run.app",
  has_password: true,
  has_key_passphrase: false,
  is_configured: true,
  updated_at: "2026-04-29T00:00:00Z",
  updated_by: "owner@victoriaenso.com",
};

beforeEach(() => {
  mockedApi.get.mockImplementation((path: string) => {
    if (path.startsWith("/cag/config")) return Promise.resolve({ ...baseConfig });
    if (path.startsWith("/stores")) return Promise.resolve({ data: [], total: 0 });
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
  mockedApi.put.mockResolvedValue({ ...baseConfig });
  mockedTest.mockResolvedValue({
    files_uploaded: ["SKU_10001_20260429000000.txt"],
    bytes_uploaded: 42,
    counts: { sku: 1 },
    started_at: "2026-04-29T06:00:00Z",
    finished_at: "2026-04-29T06:00:01Z",
    errors: [],
  });
  mockedErrors.mockResolvedValue([]);
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CagSettingsPage scheduler section", () => {
  it("renders scheduler defaults and last-run badge", async () => {
    render(<CagSettingsPage />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith("/cag/config"));

    expect(await screen.findByText(/Scheduled push \(Cloud Scheduler\)/i)).toBeTruthy();
    expect(screen.getByText(/Go-live console/i)).toBeTruthy();
    const cronInput = screen.getByDisplayValue("0 */3 * * *");
    expect(cronInput).toBeTruthy();
    // Last-run badge is rendered from scheduler_last_run_at.
    expect(screen.getByText(/Last run · success \(scheduler\)/i)).toBeTruthy();
    expect(screen.getByText(/6 file\(s\), 1234 bytes/i)).toBeTruthy();
    expect(await screen.findByText(/No CAG error rows returned/i)).toBeTruthy();
  });

  it("submits scheduler fields to /cag/config on save", async () => {
    render(<CagSettingsPage />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith("/cag/config"));

    const cronInput = screen.getByDisplayValue("0 */3 * * *") as HTMLInputElement;
    fireEvent.change(cronInput, { target: { value: "*/30 * * * *" } });

    fireEvent.click(screen.getByRole("button", { name: /save settings/i }));

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled());
    const [path, body] = mockedApi.put.mock.calls[0];
    expect(path).toBe("/cag/config");
    expect(body.scheduler_cron).toBe("*/30 * * * *");
    expect(body.scheduler_enabled).toBe(true);
    expect(body.scheduler_default_tenant).toBe("200151");
    expect(body.scheduler_default_store_id).toBe("80001");
    expect(body.scheduler_default_taxable).toBe(false);
  });

  it("invokes testScheduledPush and renders the result panel", async () => {
    render(<CagSettingsPage />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith("/cag/config"));

    fireEvent.click(screen.getByRole("button", { name: /run scheduled push now/i }));

    await waitFor(() => expect(mockedTest).toHaveBeenCalledWith({}));
    expect(await screen.findByText(/On-demand push result/i)).toBeTruthy();
    expect(screen.getByText(/SKU_10001_20260429000000\.txt/)).toBeTruthy();
    expect(screen.getByText(/Push OK — 1 file\(s\), 42 bytes\./i)).toBeTruthy();
    // Refreshes config so the badge reflects latest telemetry.
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(mockedErrors).toHaveBeenCalled());
  });

  it("disables Run-now while config is not yet configured", async () => {
    mockedApi.get.mockImplementation((path: string) => {
      if (path.startsWith("/cag/config"))
        return Promise.resolve({ ...baseConfig, is_configured: false });
      if (path.startsWith("/stores")) return Promise.resolve({ data: [], total: 0 });
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });
    render(<CagSettingsPage />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith("/cag/config"));
    const btn = screen.getByRole("button", { name: /run scheduled push now/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("surfaces an error message when the on-demand push fails", async () => {
    mockedTest.mockRejectedValueOnce(new Error("boom from server"));
    render(<CagSettingsPage />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith("/cag/config"));

    fireEvent.click(screen.getByRole("button", { name: /run scheduled push now/i }));
    expect(await screen.findByText(/boom from server/i)).toBeTruthy();
  });

  it("renders CAG error rows in the go-live console", async () => {
    mockedErrors.mockResolvedValueOnce([
      {
        status: "Failed",
        line: 3,
        message: "Mandatory fields are not filled: SKU_CODE",
        source_file: "SKU_80001_20260429000000.errorLog",
      },
    ]);
    render(<CagSettingsPage />);
    await waitFor(() => expect(mockedErrors).toHaveBeenCalledWith(50));
    expect(await screen.findByText(/Mandatory fields are not filled/i)).toBeTruthy();
    expect(screen.getByText(/1 failed row\(s\)/i)).toBeTruthy();
  });
});

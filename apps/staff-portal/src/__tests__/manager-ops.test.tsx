import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import AppShell from "../components/AppShell";
import ManagerOnlyRoute from "../components/ManagerOnlyRoute";
import OwnerOnlyRoute from "../components/OwnerOnlyRoute";
import type { BackendProfile, StoreRole, StoreSummary } from "../contexts/AuthContext";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../lib/api";
import ManagerOpsPage from "../pages/ManagerOpsPage";

vi.mock("../contexts/AuthContext", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockedUseAuth = vi.mocked(useAuth);
const mockedApi = api as unknown as {
  get: Mock;
  post: Mock;
  patch: Mock;
  put: Mock;
  delete: Mock;
};

const store: StoreSummary = {
  id: "store-1",
  name: "Flagship Orchard",
  location: "Singapore",
  address: "Orchard Road",
  is_active: true,
};

const profile: BackendProfile = {
  id: "user-1",
  firebase_uid: "firebase-user-1",
  email: "manager@example.com",
  full_name: "Manager Example",
  phone: null,
  store_roles: [],
};

function roleLabel(role: StoreRole["role"]) {
  switch (role) {
    case "system_admin":
      return "System Admin";
    case "owner":
      return "Owner Director";
    case "manager":
      return "Store Manager";
    case "staff":
      return "Sales Promoter";
  }
}

function buildAuthContext(role: StoreRole["role"]) {
  const selectedStoreRole: StoreRole = {
    id: `role-${role}`,
    store_id: store.id,
    role,
  };

  const isSystemAdmin = role === "system_admin";
  const isOwner = isSystemAdmin || role === "owner";
  const isManager = isOwner || role === "manager";

  return {
    user: { email: "manager@example.com" } as never,
    profile: {
      ...profile,
      store_roles: [selectedStoreRole],
    },
    stores: [store],
    selectedStore: store,
    selectedStoreRole,
    isManager,
    isOwner,
    isSystemAdmin,
    canViewSensitiveOperations: isOwner,
    roleLabel: roleLabel(role),
    loading: false,
    mustChangePassword: false,
    login: vi.fn(),
    logout: vi.fn(),
    refreshProfile: vi.fn(),
    refreshTokenClaims: vi.fn(),
    setSelectedStoreId: vi.fn(),
  };
}

function configureManagerData(options?: { includeOwnerData?: boolean; approvedRecommendation?: boolean }) {
  const includeOwnerData = options?.includeOwnerData ?? false;
  const recommendationStatus = options?.approvedRecommendation ? "approved" : "pending";

  const responses = new Map<string, unknown>([
    [
      `/stores/${store.id}/copilot/summary`,
      {
        data: {
          store_id: store.id,
          analysis_status: "ready",
          last_generated_at: "2026-04-14T01:00:00Z",
          low_stock_count: 1,
          anomaly_count: 0,
          pending_price_recommendations: 1,
          pending_reorder_recommendations: 1,
          pending_stock_anomalies: 0,
          open_purchase_orders: includeOwnerData ? 1 : 0,
          active_work_orders: includeOwnerData ? 1 : 0,
          in_transit_transfers: includeOwnerData ? 1 : 0,
          purchased_units: includeOwnerData ? 14 : 0,
          material_units: includeOwnerData ? 8 : 0,
          finished_units: 6,
          recent_outcomes: [],
        },
      },
    ],
    [
      `/stores/${store.id}/copilot/inventory`,
      {
        data: [
          {
            inventory_id: "inv-1",
            sku_id: "sku-1",
            store_id: store.id,
            sku_code: "SKU-001",
            description: "Signature Candle",
            long_description: "Standard manufactured candle",
            inventory_type: "finished",
            sourcing_strategy: "manufactured_standard",
            supplier_name: includeOwnerData ? "WaxWorks" : null,
            cost_price: includeOwnerData ? 15 : null,
            current_price: 42,
            current_price_valid_until: null,
            purchased_qty: includeOwnerData ? 10 : 0,
            purchased_incoming_qty: includeOwnerData ? 4 : 0,
            material_qty: includeOwnerData ? 8 : 0,
            material_incoming_qty: includeOwnerData ? 0 : 0,
            material_allocated_qty: includeOwnerData ? 2 : 0,
            finished_qty: 6,
            finished_allocated_qty: 1,
            in_transit_qty: includeOwnerData ? 3 : 0,
            active_work_order_count: includeOwnerData ? 1 : 0,
            qty_on_hand: 6,
            reorder_level: 5,
            reorder_qty: 12,
            low_stock: true,
            anomaly_flag: false,
            anomaly_reason: null,
            recent_sales_qty: 18,
            recent_sales_revenue: 756,
            avg_daily_sales: 0.6,
            days_of_cover: 10,
            pending_recommendation_count: 2,
            pending_price_recommendation_count: 1,
            last_updated: "2026-04-14T01:00:00Z",
          },
        ],
      },
    ],
    [
      `/stores/${store.id}/copilot/recommendations`,
      {
        data: [
          {
            id: "rec-1",
            store_id: store.id,
            sku_id: "sku-1",
            inventory_id: "inv-1",
            inventory_type: "finished",
            sourcing_strategy: "manufactured_standard",
            supplier_name: includeOwnerData ? "WaxWorks" : null,
            type: "reorder",
            status: recommendationStatus,
            title: "Replenish signature candle",
            rationale: "Recent sales are trending above the reorder threshold.",
            confidence: 0.88,
            supporting_metrics: { days_of_cover: 10 },
            source: "multica",
            expected_impact: "Avoid an out-of-stock next week.",
            current_price: 42,
            suggested_price: null,
            suggested_order_qty: 12,
            workflow_action: "purchase_order",
            analysis_status: "ready",
            generated_at: "2026-04-14T01:00:00Z",
            decided_at: null,
            applied_at: null,
            note: null,
          },
        ],
      },
    ],
    [
      `/stores/${store.id}/copilot/adjustments`,
      {
        data: [],
      },
    ],
  ]);

  if (includeOwnerData) {
    responses.set(`/stores/${store.id}/supply-chain/summary`, {
      data: {
        store_id: store.id,
        supplier_count: 1,
        open_purchase_orders: 1,
        active_work_orders: 1,
        in_transit_transfers: 1,
        purchased_units: 14,
        material_units: 8,
        finished_units: 6,
      },
    });
    responses.set(`/stores/${store.id}/supply-chain/suppliers?active_only=true`, {
      data: [
        {
          id: "supplier-1",
          name: "WaxWorks",
          contact_name: "Sasha",
          email: "ops@waxworks.test",
          phone: null,
          lead_time_days: 7,
          currency: "SGD",
          notes: null,
          is_active: true,
        },
      ],
    });
    responses.set(`/stores/${store.id}/supply-chain/stages`, {
      data: [
        {
          id: "stage-1",
          store_id: store.id,
          sku_id: "sku-1",
          sku_code: "SKU-001",
          description: "Signature Candle",
          inventory_type: "finished",
          sourcing_strategy: "manufactured_standard",
          supplier_name: "WaxWorks",
          quantity_on_hand: 6,
          incoming_quantity: 3,
          allocated_quantity: 1,
          available_quantity: 5,
        },
      ],
    });
    responses.set(`/stores/${store.id}/supply-chain/purchase-orders`, {
      data: [
        {
          id: "po-1",
          supplier_id: "supplier-1",
          supplier_name: "WaxWorks",
          status: "ordered",
          lines: [
            {
              line_id: "line-1",
              sku_id: "sku-1",
              sku_code: "SKU-001",
              description: "Signature Candle",
              stage_inventory_type: "purchased",
              quantity: 12,
              unit_cost: 15,
              received_quantity: 0,
              open_quantity: 12,
              note: null,
            },
          ],
          total_quantity: 12,
          total_cost: 180,
          expected_delivery_date: "2026-04-21",
          note: null,
          recommendation_id: "rec-1",
        },
      ],
    });
    responses.set(`/stores/${store.id}/supply-chain/bom-recipes`, { data: [] });
    responses.set(`/stores/${store.id}/supply-chain/work-orders`, {
      data: [
        {
          id: "wo-1",
          finished_sku_id: "sku-1",
          finished_sku_code: "SKU-001",
          finished_description: "Signature Candle",
          work_order_type: "standard",
          status: "scheduled",
          target_quantity: 12,
          completed_quantity: 0,
          components: [],
          due_date: "2026-04-18",
          note: null,
          recommendation_id: null,
        },
      ],
    });
    responses.set(`/stores/${store.id}/supply-chain/transfers`, {
      data: [
        {
          id: "transfer-1",
          sku_id: "sku-1",
          sku_code: "SKU-001",
          description: "Signature Candle",
          quantity: 3,
          from_inventory_type: "finished",
          to_inventory_type: "finished",
          status: "in_transit",
          note: null,
          recommendation_id: null,
          dispatched_at: "2026-04-13T10:00:00Z",
          received_at: null,
        },
      ],
    });
  }

  mockedApi.get.mockImplementation(async (path: string) => {
    const response = responses.get(path);
    if (!response) {
      throw new Error(`Unhandled manager API GET ${path}`);
    }
    return response;
  });
}

describe("manager web hardening", () => {
  beforeEach(() => {
    mockedApi.get.mockReset();
    mockedApi.post.mockReset();
    mockedApi.patch.mockReset();
    mockedApi.put.mockReset();
    mockedApi.delete.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows role-aware navigation across promoter, manager, and owner", () => {
    mockedUseAuth.mockReturnValue(buildAuthContext("manager"));
    const { rerender } = render(
      <MemoryRouter initialEntries={["/schedule"]}>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route path="schedule" element={<div>Schedule page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getAllByText("Manager Ops")).toHaveLength(2);
    expect(screen.queryAllByText("Staging Vault")).toHaveLength(0);
    expect(screen.queryAllByText("Invoice Review")).toHaveLength(0);
    expect(screen.getAllByText("Store Manager")).toHaveLength(1);

    mockedUseAuth.mockReturnValue(buildAuthContext("owner"));
    rerender(
      <MemoryRouter initialEntries={["/schedule"]}>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route path="schedule" element={<div>Schedule page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getAllByText("Manager Ops")).toHaveLength(2);
    expect(screen.getAllByText("Staging Vault")).toHaveLength(2);
    expect(screen.getAllByText("Invoice Review")).toHaveLength(2);
    expect(screen.getAllByText("Owner Director")).toHaveLength(1);

    mockedUseAuth.mockReturnValue(buildAuthContext("staff"));
    rerender(
      <MemoryRouter initialEntries={["/schedule"]}>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route path="schedule" element={<div>Schedule page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryAllByText("Manager Ops")).toHaveLength(0);
    expect(screen.queryAllByText("Staging Vault")).toHaveLength(0);
    expect(screen.queryAllByText("Invoice Review")).toHaveLength(0);
    expect(screen.getAllByText("Sales Promoter")).toHaveLength(1);
  });

  it("redirects staff away from manager-only routes", async () => {
    mockedUseAuth.mockReturnValue(buildAuthContext("staff"));

    render(
      <MemoryRouter initialEntries={["/manager"]}>
        <Routes>
          <Route path="/schedule" element={<div>Schedule home</div>} />
          <Route
            path="/manager"
            element={
              <ManagerOnlyRoute>
                <div>Manager page</div>
              </ManagerOnlyRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("Schedule home")).toBeInTheDocument();
    expect(screen.queryByText("Manager page")).not.toBeInTheDocument();
  });

  it("redirects store managers away from owner-only routes", async () => {
    mockedUseAuth.mockReturnValue(buildAuthContext("manager"));

    render(
      <MemoryRouter initialEntries={["/supplier-review"]}>
        <Routes>
          <Route path="/manager" element={<div>Manager home</div>} />
          <Route
            path="/supplier-review"
            element={
              <OwnerOnlyRoute>
                <div>Owner page</div>
              </OwnerOnlyRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("Manager home")).toBeInTheDocument();
    expect(screen.queryByText("Owner page")).not.toBeInTheDocument();
  });

  it("keeps the store manager console free of supplier, cost, and procurement data", async () => {
    mockedUseAuth.mockReturnValue(buildAuthContext("manager"));
    configureManagerData();
    mockedApi.post.mockResolvedValue({ data: null });

    render(
      <MemoryRouter>
        <ManagerOpsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText("Replenish signature candle")).toBeInTheDocument();
    expect(screen.queryByText("Cost Price")).not.toBeInTheDocument();
    expect(screen.queryByText("WaxWorks")).not.toBeInTheDocument();
    expect(screen.queryByText("Procurement & Delivery")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Receive Remaining" })).not.toBeInTheDocument();
    expect(screen.getByText(/Owner-Only Operations/)).toBeInTheDocument();

    const calledPaths = mockedApi.get.mock.calls.map(([path]) => path as string);
    expect(calledPaths.every((path) => !path.includes("/supply-chain/"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Run Inventory Brain" }));

    await waitFor(() => {
      expect(mockedApi.post).toHaveBeenCalledWith(
        `/stores/${store.id}/copilot/recommendations/analyze`,
        {
          force_refresh: true,
          lookback_days: 30,
          low_stock_threshold: 5,
        }
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(mockedApi.post).toHaveBeenCalledWith(
        `/stores/${store.id}/copilot/recommendations/rec-1/approve`,
        {
          note: "Approved from the manager operations console.",
        }
      );
    });
  });

  it("keeps owner-director access to procurement controls", async () => {
    mockedUseAuth.mockReturnValue(buildAuthContext("owner"));
    configureManagerData({ includeOwnerData: true });
    mockedApi.post.mockResolvedValue({ data: null });

    render(
      <MemoryRouter>
        <ManagerOpsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText("Procurement & Delivery")).toBeInTheDocument();
    expect(screen.getAllByText("WaxWorks").length).toBeGreaterThan(0);
    expect(screen.getByText("Cost Price")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Receive Remaining" }));

    await waitFor(() => {
      expect(mockedApi.post).toHaveBeenCalledWith(
        `/stores/${store.id}/supply-chain/purchase-orders/po-1/receive`,
        {
          lines: [{ line_id: "line-1", quantity_received: 12 }],
          note: "Received from the manager operations console.",
        }
      );
    });
  });
});

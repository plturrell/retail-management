import {
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type FormEvent,
  type SetStateAction,
} from "react";
import { api } from "../lib/api";
import type {
  BOMRecipe,
  InventoryInsight,
  InventoryType,
  Supplier,
} from "../lib/manager-contracts";

interface Props {
  storeId: string;
  selectedItem: InventoryInsight | null;
  inventory: InventoryInsight[];
  suppliers: Supplier[];
  bomRecipes: BOMRecipe[];
  onMutated: () => Promise<void>;
}

interface ComponentDraft {
  sku_id: string;
  quantity_required: number;
  note: string;
}

const emptySupplierForm = {
  id: null as string | null,
  name: "",
  contact_name: "",
  email: "",
  phone: "",
  lead_time_days: 7,
  currency: "SGD",
  notes: "",
  is_active: true,
};

export function ManagerWorkflowStudio({
  storeId,
  selectedItem,
  inventory,
  suppliers,
  bomRecipes,
  onMutated,
}: Props) {
  const [supplierForm, setSupplierForm] = useState(emptySupplierForm);
  const [purchaseOrderSupplierId, setPurchaseOrderSupplierId] = useState("");
  const [purchaseOrderQuantity, setPurchaseOrderQuantity] = useState(1);
  const [purchaseOrderUnitCost, setPurchaseOrderUnitCost] = useState(0);
  const [purchaseOrderExpectedDate, setPurchaseOrderExpectedDate] = useState("");
  const [purchaseOrderNote, setPurchaseOrderNote] = useState("");
  const [bomName, setBomName] = useState("");
  const [bomYieldQuantity, setBomYieldQuantity] = useState(1);
  const [bomNotes, setBomNotes] = useState("");
  const [bomComponents, setBomComponents] = useState<ComponentDraft[]>([
    { sku_id: "", quantity_required: 1, note: "" },
  ]);
  const [selectedBomId, setSelectedBomId] = useState("");
  const [workOrderType, setWorkOrderType] = useState<"standard" | "custom">("standard");
  const [workOrderQuantity, setWorkOrderQuantity] = useState(1);
  const [workOrderDueDate, setWorkOrderDueDate] = useState("");
  const [workOrderNote, setWorkOrderNote] = useState("");
  const [workOrderComponents, setWorkOrderComponents] = useState<ComponentDraft[]>([
    { sku_id: "", quantity_required: 1, note: "" },
  ]);
  const [transferQuantity, setTransferQuantity] = useState(1);
  const [transferFromType, setTransferFromType] = useState<InventoryType>("purchased");
  const [transferToType, setTransferToType] = useState<InventoryType>("finished");
  const [transferNote, setTransferNote] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const candidateComponentOptions = useMemo(
    () =>
      inventory.filter((item) => item.sku_id !== selectedItem?.sku_id).sort((a, b) =>
        a.sku_code.localeCompare(b.sku_code)
      ),
    [inventory, selectedItem?.sku_id]
  );

  const selectedBomRecipes = useMemo(
    () => bomRecipes.filter((item) => item.finished_sku_id === selectedItem?.sku_id),
    [bomRecipes, selectedItem?.sku_id]
  );

  useEffect(() => {
    if (!purchaseOrderSupplierId && suppliers[0]) {
      setPurchaseOrderSupplierId(suppliers[0].id);
    }
  }, [purchaseOrderSupplierId, suppliers]);

  useEffect(() => {
    if (selectedBomRecipes.length && !selectedBomId) {
      setSelectedBomId(selectedBomRecipes[0].id);
    }
    if (!selectedBomRecipes.length) {
      setSelectedBomId("");
    }
  }, [selectedBomId, selectedBomRecipes]);

  useEffect(() => {
    if (selectedItem?.sourcing_strategy === "manufactured_custom") {
      setWorkOrderType("custom");
    } else if (selectedItem?.sourcing_strategy === "manufactured_standard") {
      setWorkOrderType("standard");
    }
  }, [selectedItem?.sourcing_strategy]);

  const mutate = async (key: string, action: () => Promise<void>) => {
    setBusyAction(key);
    setError(null);
    try {
      await action();
      await onMutated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save manager workflow action.");
    } finally {
      setBusyAction(null);
    }
  };

  const hydrateSupplierForEdit = (supplier: Supplier) => {
    setSupplierForm({
      id: supplier.id,
      name: supplier.name,
      contact_name: supplier.contact_name ?? "",
      email: supplier.email ?? "",
      phone: supplier.phone ?? "",
      lead_time_days: supplier.lead_time_days,
      currency: supplier.currency,
      notes: supplier.notes ?? "",
      is_active: supplier.is_active,
    });
  };

  const handleSupplierSave = async (event: FormEvent) => {
    event.preventDefault();
    if (!supplierForm.name.trim()) return;

    const payload = {
      name: supplierForm.name.trim(),
      contact_name: supplierForm.contact_name.trim() || null,
      email: supplierForm.email.trim() || null,
      phone: supplierForm.phone.trim() || null,
      lead_time_days: supplierForm.lead_time_days,
      currency: supplierForm.currency.trim() || "SGD",
      notes: supplierForm.notes.trim() || null,
      is_active: supplierForm.is_active,
    };

    await mutate("supplier-save", async () => {
      if (supplierForm.id) {
        await api.patch(`/stores/${storeId}/supply-chain/suppliers/${supplierForm.id}`, payload);
      } else {
        await api.post(`/stores/${storeId}/supply-chain/suppliers`, payload);
      }
      setSupplierForm(emptySupplierForm);
    });
  };

  const handleCreatePurchaseOrder = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedItem || !purchaseOrderSupplierId) return;

    await mutate("purchase-order-create", async () => {
      await api.post(`/stores/${storeId}/supply-chain/purchase-orders`, {
        supplier_id: purchaseOrderSupplierId,
        lines: [
          {
            sku_id: selectedItem.sku_id,
            quantity: Math.max(purchaseOrderQuantity, 1),
            unit_cost: Math.max(purchaseOrderUnitCost, 0),
            note: purchaseOrderNote.trim() || null,
          },
        ],
        expected_delivery_date: purchaseOrderExpectedDate || null,
        note: purchaseOrderNote.trim() || null,
        source: "manual",
      });
      setPurchaseOrderQuantity(1);
      setPurchaseOrderUnitCost(0);
      setPurchaseOrderExpectedDate("");
      setPurchaseOrderNote("");
    });
  };

  const handleCreateBom = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedItem) return;

    const components = bomComponents
      .filter((item) => item.sku_id && item.quantity_required > 0)
      .map((item) => ({
        sku_id: item.sku_id,
        quantity_required: item.quantity_required,
        note: item.note.trim() || null,
      }));
    if (!bomName.trim() || !components.length) return;

    await mutate("bom-create", async () => {
      await api.post(`/stores/${storeId}/supply-chain/bom-recipes`, {
        finished_sku_id: selectedItem.sku_id,
        name: bomName.trim(),
        yield_quantity: Math.max(bomYieldQuantity, 1),
        components,
        notes: bomNotes.trim() || null,
      });
      setBomName("");
      setBomYieldQuantity(1);
      setBomNotes("");
      setBomComponents([{ sku_id: "", quantity_required: 1, note: "" }]);
    });
  };

  const handleCreateWorkOrder = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedItem) return;

    const customComponents = workOrderComponents
      .filter((item) => item.sku_id && item.quantity_required > 0)
      .map((item) => ({
        sku_id: item.sku_id,
        quantity_required: item.quantity_required,
        note: item.note.trim() || null,
      }));

    await mutate("work-order-create", async () => {
      await api.post(`/stores/${storeId}/supply-chain/work-orders`, {
        finished_sku_id: selectedItem.sku_id,
        target_quantity: Math.max(workOrderQuantity, 1),
        bom_id: selectedBomId || null,
        work_order_type: workOrderType,
        custom_components: selectedBomId ? [] : customComponents,
        due_date: workOrderDueDate || null,
        note: workOrderNote.trim() || null,
        source: "manual",
      });
      setWorkOrderQuantity(1);
      setWorkOrderDueDate("");
      setWorkOrderNote("");
      setWorkOrderComponents([{ sku_id: "", quantity_required: 1, note: "" }]);
    });
  };

  const handleCreateTransfer = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedItem) return;

    await mutate("transfer-create", async () => {
      await api.post(`/stores/${storeId}/supply-chain/transfers`, {
        sku_id: selectedItem.sku_id,
        quantity: Math.max(transferQuantity, 1),
        from_inventory_type: transferFromType,
        to_inventory_type: transferToType,
        note: transferNote.trim() || null,
        source: "manual",
      });
      setTransferQuantity(1);
      setTransferNote("");
    });
  };

  const updateDraft = (
    drafts: ComponentDraft[],
    setDrafts: Dispatch<SetStateAction<ComponentDraft[]>>,
    index: number,
    updates: Partial<ComponentDraft>
  ) => {
    setDrafts(
      drafts.map((item, itemIndex) => (itemIndex === index ? { ...item, ...updates } : item))
    );
  };

  const addDraftRow = (setDrafts: Dispatch<SetStateAction<ComponentDraft[]>>) => {
    setDrafts((items) => [...items, { sku_id: "", quantity_required: 1, note: "" }]);
  };

  const removeDraftRow = (
    drafts: ComponentDraft[],
    setDrafts: Dispatch<SetStateAction<ComponentDraft[]>>,
    index: number
  ) => {
    setDrafts(drafts.filter((_, itemIndex) => itemIndex !== index));
  };

  return (
    <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="border-b border-gray-100 pb-4">
        <h2 className="text-lg font-semibold text-gray-900">Manager Workflow Studio</h2>
        <p className="text-sm text-gray-500">
          Create suppliers, purchase orders, BOM recipes, work orders, and stock transfers without
          leaving the manager console.
        </p>
      </div>

      {error && (
        <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="mt-5 grid gap-6 xl:grid-cols-2">
        <article className="rounded-3xl border border-slate-200 bg-slate-50 p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-slate-900">Supplier Desk</h3>
              <p className="text-sm text-slate-500">Create or update the suppliers used by the pilot store.</p>
            </div>
            <button
              type="button"
              onClick={() => setSupplierForm(emptySupplierForm)}
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700"
            >
              New supplier
            </button>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {suppliers.map((supplier) => (
              <button
                key={supplier.id}
                type="button"
                onClick={() => hydrateSupplierForEdit(supplier)}
                className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-700 shadow-sm"
              >
                {supplier.name}
              </button>
            ))}
            {!suppliers.length && <span className="text-xs text-slate-500">No suppliers yet.</span>}
          </div>

          <form onSubmit={(event) => void handleSupplierSave(event)} className="mt-4 space-y-3">
            <input
              value={supplierForm.name}
              onChange={(event) => setSupplierForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Supplier name"
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
            />
            <div className="grid gap-3 md:grid-cols-2">
              <input
                value={supplierForm.contact_name}
                onChange={(event) =>
                  setSupplierForm((current) => ({ ...current, contact_name: event.target.value }))
                }
                placeholder="Contact name"
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
              />
              <input
                value={supplierForm.email}
                onChange={(event) => setSupplierForm((current) => ({ ...current, email: event.target.value }))}
                placeholder="Email"
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
              />
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <input
                value={supplierForm.phone}
                onChange={(event) => setSupplierForm((current) => ({ ...current, phone: event.target.value }))}
                placeholder="Phone"
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
              />
              <input
                type="number"
                min={0}
                max={365}
                value={supplierForm.lead_time_days}
                onChange={(event) =>
                  setSupplierForm((current) => ({
                    ...current,
                    lead_time_days: Number(event.target.value || 0),
                  }))
                }
                placeholder="Lead time"
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
              />
              <input
                value={supplierForm.currency}
                onChange={(event) =>
                  setSupplierForm((current) => ({ ...current, currency: event.target.value.toUpperCase() }))
                }
                placeholder="Currency"
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
              />
            </div>
            <textarea
              value={supplierForm.notes}
              onChange={(event) => setSupplierForm((current) => ({ ...current, notes: event.target.value }))}
              placeholder="Supplier notes"
              rows={3}
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
            />
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={supplierForm.is_active}
                onChange={(event) =>
                  setSupplierForm((current) => ({ ...current, is_active: event.target.checked }))
                }
              />
              Supplier is active
            </label>
            <button
              type="submit"
              disabled={busyAction === "supplier-save" || !supplierForm.name.trim()}
              className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busyAction === "supplier-save"
                ? "Saving supplier…"
                : supplierForm.id
                  ? "Update Supplier"
                  : "Create Supplier"}
            </button>
          </form>
        </article>

        <article className="rounded-3xl border border-blue-200 bg-blue-50 p-5">
          <h3 className="text-base font-semibold text-blue-950">Purchase Order Builder</h3>
          <p className="mt-1 text-sm text-blue-800">
            Create a supplier order for the selected SKU{selectedItem ? ` ${selectedItem.sku_code}` : ""}.
          </p>
          {!selectedItem ? (
            <div className="mt-4 rounded-2xl border border-dashed border-blue-200 bg-white px-4 py-6 text-sm text-blue-800">
              Pick a SKU from the watchlist before creating a purchase order.
            </div>
          ) : (
            <form onSubmit={(event) => void handleCreatePurchaseOrder(event)} className="mt-4 space-y-3">
              <select
                value={purchaseOrderSupplierId}
                onChange={(event) => setPurchaseOrderSupplierId(event.target.value)}
                className="w-full rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm"
              >
                <option value="">Select supplier</option>
                {suppliers.map((supplier) => (
                  <option key={supplier.id} value={supplier.id}>
                    {supplier.name}
                  </option>
                ))}
              </select>
              <div className="grid gap-3 md:grid-cols-3">
                <input
                  type="number"
                  min={1}
                  value={purchaseOrderQuantity}
                  onChange={(event) => setPurchaseOrderQuantity(Number(event.target.value || 1))}
                  placeholder="Quantity"
                  className="rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm"
                />
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  value={purchaseOrderUnitCost}
                  onChange={(event) => setPurchaseOrderUnitCost(Number(event.target.value || 0))}
                  placeholder="Unit cost"
                  className="rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm"
                />
                <input
                  type="date"
                  value={purchaseOrderExpectedDate}
                  onChange={(event) => setPurchaseOrderExpectedDate(event.target.value)}
                  className="rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm"
                />
              </div>
              <textarea
                value={purchaseOrderNote}
                onChange={(event) => setPurchaseOrderNote(event.target.value)}
                placeholder="PO note"
                rows={3}
                className="w-full rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={busyAction === "purchase-order-create" || !purchaseOrderSupplierId}
                className="rounded-xl bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {busyAction === "purchase-order-create" ? "Creating PO…" : "Create Purchase Order"}
              </button>
            </form>
          )}
        </article>

        <article className="rounded-3xl border border-violet-200 bg-violet-50 p-5">
          <h3 className="text-base font-semibold text-violet-950">BOM Recipe Builder</h3>
          <p className="mt-1 text-sm text-violet-800">
            Capture standard material recipes for the selected finished SKU.
          </p>
          {!selectedItem ? (
            <div className="mt-4 rounded-2xl border border-dashed border-violet-200 bg-white px-4 py-6 text-sm text-violet-800">
              Pick a finished or manufactured SKU before creating a BOM recipe.
            </div>
          ) : (
            <form onSubmit={(event) => void handleCreateBom(event)} className="mt-4 space-y-3">
              <input
                value={bomName}
                onChange={(event) => setBomName(event.target.value)}
                placeholder="Recipe name"
                className="w-full rounded-xl border border-violet-200 bg-white px-3 py-2 text-sm"
              />
              <div className="grid gap-3 md:grid-cols-2">
                <input
                  type="number"
                  min={1}
                  value={bomYieldQuantity}
                  onChange={(event) => setBomYieldQuantity(Number(event.target.value || 1))}
                  placeholder="Yield quantity"
                  className="rounded-xl border border-violet-200 bg-white px-3 py-2 text-sm"
                />
                <textarea
                  value={bomNotes}
                  onChange={(event) => setBomNotes(event.target.value)}
                  placeholder="Recipe notes"
                  rows={2}
                  className="rounded-xl border border-violet-200 bg-white px-3 py-2 text-sm"
                />
              </div>

              <div className="space-y-3 rounded-2xl border border-violet-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-violet-950">Components</div>
                  <button
                    type="button"
                    onClick={() => addDraftRow(setBomComponents)}
                    className="rounded-xl border border-violet-200 px-3 py-1.5 text-xs font-semibold text-violet-800"
                  >
                    Add component
                  </button>
                </div>
                {bomComponents.map((component, index) => (
                  <div key={`bom-component-${index}`} className="grid gap-3 lg:grid-cols-[1.4fr_120px_1fr_auto]">
                    <select
                      value={component.sku_id}
                      onChange={(event) =>
                        updateDraft(bomComponents, setBomComponents, index, { sku_id: event.target.value })
                      }
                      className="rounded-xl border border-violet-200 px-3 py-2 text-sm"
                    >
                      <option value="">Select material SKU</option>
                      {candidateComponentOptions.map((item) => (
                        <option key={item.sku_id} value={item.sku_id}>
                          {item.sku_code} · {item.description}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min={1}
                      value={component.quantity_required}
                      onChange={(event) =>
                        updateDraft(bomComponents, setBomComponents, index, {
                          quantity_required: Number(event.target.value || 1),
                        })
                      }
                      className="rounded-xl border border-violet-200 px-3 py-2 text-sm"
                    />
                    <input
                      value={component.note}
                      onChange={(event) =>
                        updateDraft(bomComponents, setBomComponents, index, { note: event.target.value })
                      }
                      placeholder="Component note"
                      className="rounded-xl border border-violet-200 px-3 py-2 text-sm"
                    />
                    <button
                      type="button"
                      onClick={() => removeDraftRow(bomComponents, setBomComponents, index)}
                      disabled={bomComponents.length === 1}
                      className="rounded-xl border border-violet-200 px-3 py-2 text-xs font-semibold text-violet-800 disabled:opacity-40"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>

              <button
                type="submit"
                disabled={busyAction === "bom-create" || !bomName.trim()}
                className="rounded-xl bg-violet-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {busyAction === "bom-create" ? "Saving recipe…" : "Create BOM Recipe"}
              </button>
            </form>
          )}
        </article>

        <article className="rounded-3xl border border-emerald-200 bg-emerald-50 p-5">
          <h3 className="text-base font-semibold text-emerald-950">Work Orders & Transfers</h3>
          <p className="mt-1 text-sm text-emerald-800">
            Create manufacturing runs and stock movements for the selected SKU.
          </p>
          {!selectedItem ? (
            <div className="mt-4 rounded-2xl border border-dashed border-emerald-200 bg-white px-4 py-6 text-sm text-emerald-800">
              Pick a SKU before creating a work order or transfer.
            </div>
          ) : (
            <div className="mt-4 space-y-6">
              <form onSubmit={(event) => void handleCreateWorkOrder(event)} className="space-y-3 rounded-2xl border border-emerald-200 bg-white p-4">
                <div className="text-sm font-semibold text-emerald-950">Manual Work Order</div>
                <div className="grid gap-3 md:grid-cols-2">
                  <select
                    value={selectedBomId}
                    onChange={(event) => setSelectedBomId(event.target.value)}
                    className="rounded-xl border border-emerald-200 px-3 py-2 text-sm"
                  >
                    <option value="">No BOM recipe selected</option>
                    {selectedBomRecipes.map((recipe) => (
                      <option key={recipe.id} value={recipe.id}>
                        {recipe.name} · yield {recipe.yield_quantity}
                      </option>
                    ))}
                  </select>
                  <select
                    value={workOrderType}
                    onChange={(event) => setWorkOrderType(event.target.value as "standard" | "custom")}
                    className="rounded-xl border border-emerald-200 px-3 py-2 text-sm"
                  >
                    <option value="standard">Standard work order</option>
                    <option value="custom">Custom work order</option>
                  </select>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  <input
                    type="number"
                    min={1}
                    value={workOrderQuantity}
                    onChange={(event) => setWorkOrderQuantity(Number(event.target.value || 1))}
                    placeholder="Target quantity"
                    className="rounded-xl border border-emerald-200 px-3 py-2 text-sm"
                  />
                  <input
                    type="date"
                    value={workOrderDueDate}
                    onChange={(event) => setWorkOrderDueDate(event.target.value)}
                    className="rounded-xl border border-emerald-200 px-3 py-2 text-sm"
                  />
                  <input
                    value={workOrderNote}
                    onChange={(event) => setWorkOrderNote(event.target.value)}
                    placeholder="Work order note"
                    className="rounded-xl border border-emerald-200 px-3 py-2 text-sm"
                  />
                </div>
                {!selectedBomId && (
                  <div className="space-y-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-semibold text-emerald-950">Custom components</div>
                      <button
                        type="button"
                        onClick={() => addDraftRow(setWorkOrderComponents)}
                        className="rounded-xl border border-emerald-200 px-3 py-1.5 text-xs font-semibold text-emerald-800"
                      >
                        Add component
                      </button>
                    </div>
                    {workOrderComponents.map((component, index) => (
                      <div key={`work-order-component-${index}`} className="grid gap-3 lg:grid-cols-[1.4fr_120px_1fr_auto]">
                        <select
                          value={component.sku_id}
                          onChange={(event) =>
                            updateDraft(workOrderComponents, setWorkOrderComponents, index, {
                              sku_id: event.target.value,
                            })
                          }
                          className="rounded-xl border border-emerald-200 px-3 py-2 text-sm"
                        >
                          <option value="">Select material SKU</option>
                          {candidateComponentOptions.map((item) => (
                            <option key={item.sku_id} value={item.sku_id}>
                              {item.sku_code} · {item.description}
                            </option>
                          ))}
                        </select>
                        <input
                          type="number"
                          min={1}
                          value={component.quantity_required}
                          onChange={(event) =>
                            updateDraft(workOrderComponents, setWorkOrderComponents, index, {
                              quantity_required: Number(event.target.value || 1),
                            })
                          }
                          className="rounded-xl border border-emerald-200 px-3 py-2 text-sm"
                        />
                        <input
                          value={component.note}
                          onChange={(event) =>
                            updateDraft(workOrderComponents, setWorkOrderComponents, index, {
                              note: event.target.value,
                            })
                          }
                          placeholder="Component note"
                          className="rounded-xl border border-emerald-200 px-3 py-2 text-sm"
                        />
                        <button
                          type="button"
                          onClick={() => removeDraftRow(workOrderComponents, setWorkOrderComponents, index)}
                          disabled={workOrderComponents.length === 1}
                          className="rounded-xl border border-emerald-200 px-3 py-2 text-xs font-semibold text-emerald-800 disabled:opacity-40"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <button
                  type="submit"
                  disabled={busyAction === "work-order-create"}
                  className="rounded-xl bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                >
                  {busyAction === "work-order-create" ? "Creating work order…" : "Create Work Order"}
                </button>
              </form>

              <form onSubmit={(event) => void handleCreateTransfer(event)} className="space-y-3 rounded-2xl border border-cyan-200 bg-white p-4">
                <div className="text-sm font-semibold text-cyan-950">Manual Stock Transfer</div>
                <div className="grid gap-3 md:grid-cols-3">
                  <select
                    value={transferFromType}
                    onChange={(event) => setTransferFromType(event.target.value as InventoryType)}
                    className="rounded-xl border border-cyan-200 px-3 py-2 text-sm"
                  >
                    <option value="purchased">From purchased</option>
                    <option value="material">From material</option>
                    <option value="finished">From finished</option>
                  </select>
                  <select
                    value={transferToType}
                    onChange={(event) => setTransferToType(event.target.value as InventoryType)}
                    className="rounded-xl border border-cyan-200 px-3 py-2 text-sm"
                  >
                    <option value="finished">To finished</option>
                    <option value="material">To material</option>
                    <option value="purchased">To purchased</option>
                  </select>
                  <input
                    type="number"
                    min={1}
                    value={transferQuantity}
                    onChange={(event) => setTransferQuantity(Number(event.target.value || 1))}
                    className="rounded-xl border border-cyan-200 px-3 py-2 text-sm"
                  />
                </div>
                <textarea
                  value={transferNote}
                  onChange={(event) => setTransferNote(event.target.value)}
                  placeholder="Transfer note"
                  rows={2}
                  className="w-full rounded-xl border border-cyan-200 px-3 py-2 text-sm"
                />
                <button
                  type="submit"
                  disabled={busyAction === "transfer-create"}
                  className="rounded-xl bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                >
                  {busyAction === "transfer-create" ? "Creating transfer…" : "Create Transfer"}
                </button>
              </form>
            </div>
          )}
        </article>
      </div>
    </section>
  );
}

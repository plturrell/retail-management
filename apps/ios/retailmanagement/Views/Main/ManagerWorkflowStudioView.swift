//
//  ManagerWorkflowStudioView.swift
//  retailmanagement
//

import Observation
import SwiftUI

struct ManagerWorkflowStudioView: View {
    @Bindable var inventoryVM: InventoryViewModel
    let storeId: String
    let selectedInsight: InventoryInsight?

    @State private var supplierId: String?
    @State private var supplierName = ""
    @State private var supplierContactName = ""
    @State private var supplierEmail = ""
    @State private var supplierPhone = ""
    @State private var supplierLeadTimeDays = "7"
    @State private var supplierCurrency = "SGD"
    @State private var supplierNotes = ""
    @State private var supplierIsActive = true

    @State private var purchaseOrderSupplierId = ""
    @State private var purchaseOrderQuantity = "1"
    @State private var purchaseOrderUnitCost = "0"
    @State private var purchaseOrderExpectedDate = ""
    @State private var purchaseOrderNote = ""

    @State private var bomName = ""
    @State private var bomYieldQuantity = "1"
    @State private var bomNotes = ""
    @State private var bomComponents: [ComponentDraft] = [.empty]

    @State private var selectedBOMId = ""
    @State private var workOrderType = "standard"
    @State private var workOrderQuantity = "1"
    @State private var workOrderDueDate = ""
    @State private var workOrderNote = ""
    @State private var workOrderComponents: [ComponentDraft] = [.empty]

    @State private var transferQuantity = "1"
    @State private var transferFromInventoryType = InventoryType.purchased
    @State private var transferToInventoryType = InventoryType.finished
    @State private var transferNote = ""

    private var componentOptions: [InventoryInsight] {
        inventoryVM.insights
            .filter { $0.skuId != selectedInsight?.skuId }
            .sorted { $0.skuCode < $1.skuCode }
    }

    private var selectedRecipes: [BOMRecipeSummary] {
        inventoryVM.bomRecipes(for: selectedInsight?.skuId)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Manager Workflow Studio")
                .font(.headline)
                .accessibilityIdentifier("managerInventory.workflowStudioTitle")

            if let errorMessage = inventoryVM.errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.red.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 18))
            }

            supplierDesk
            purchaseOrderBuilder
            bomRecipeBuilder
            workOrderAndTransferBuilder
        }
        .onAppear {
            seedDefaultSelections()
        }
        .onChange(of: inventoryVM.suppliers.map(\.id)) { _, _ in
            seedDefaultSelections()
        }
        .onChange(of: selectedRecipes.map(\.id)) { _, recipes in
            if recipes.contains(selectedBOMId) {
                return
            }
            selectedBOMId = recipes.first ?? ""
        }
        .onChange(of: selectedInsight?.skuId) { _, _ in
            if selectedInsight?.sourcingStrategy == .manufacturedCustom {
                workOrderType = "custom"
            } else if selectedInsight?.sourcingStrategy == .manufacturedStandard {
                workOrderType = "standard"
            }
            if let first = selectedRecipes.first?.id, selectedBOMId.isEmpty {
                selectedBOMId = first
            }
        }
    }

    private var supplierDesk: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Supplier Desk")
                        .font(.headline)
                    Text("Create or update supplier records for this store.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("New Supplier") {
                    resetSupplierForm()
                }
                .buttonStyle(.bordered)
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(inventoryVM.suppliers) { supplier in
                        Button(supplier.name) {
                            hydrateSupplierForm(supplier)
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }

            VStack(alignment: .leading, spacing: 10) {
                TextField("Supplier name", text: $supplierName)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    TextField("Contact name", text: $supplierContactName)
                        .textFieldStyle(.roundedBorder)
                    TextField("Email", text: $supplierEmail)
                        .textFieldStyle(.roundedBorder)
                }
                HStack {
                    TextField("Phone", text: $supplierPhone)
                        .textFieldStyle(.roundedBorder)
                    TextField("Lead time days", text: $supplierLeadTimeDays)
                        .keyboardTypeCompat(.numberPad)
                        .textFieldStyle(.roundedBorder)
                    TextField("Currency", text: $supplierCurrency)
                        .textFieldStyle(.roundedBorder)
                }
                TextField("Notes", text: $supplierNotes, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                Toggle("Supplier is active", isOn: $supplierIsActive)

                Button(supplierId == nil ? "Create Supplier" : "Update Supplier") {
                    Task {
                        await inventoryVM.saveSupplier(
                            storeId: storeId,
                            supplierId: supplierId,
                            name: supplierName,
                            contactName: supplierContactName,
                            email: supplierEmail,
                            phone: supplierPhone,
                            leadTimeDays: Int(supplierLeadTimeDays) ?? 7,
                            currency: supplierCurrency,
                            notes: supplierNotes,
                            isActive: supplierIsActive
                        )
                        if inventoryVM.errorMessage == nil {
                            resetSupplierForm()
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(inventoryVM.activeActionKey == "supplier-save" || supplierName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .padding()
            .background(Color.gray.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 20))
        }
        .padding()
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 24))
    }

    private var purchaseOrderBuilder: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Purchase Order Builder")
                .font(.headline)

            if let selectedInsight {
                Text("Create a supplier order for \(selectedInsight.skuCode).")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                Picker("Supplier", selection: $purchaseOrderSupplierId) {
                    Text("Select supplier").tag("")
                    ForEach(inventoryVM.suppliers) { supplier in
                        Text(supplier.name).tag(supplier.id)
                    }
                }
                .pickerStyle(.menu)

                HStack {
                    TextField("Quantity", text: $purchaseOrderQuantity)
                        .keyboardTypeCompat(.numberPad)
                        .textFieldStyle(.roundedBorder)
                    TextField("Unit cost", text: $purchaseOrderUnitCost)
                        .keyboardTypeCompat(.decimalPad)
                        .textFieldStyle(.roundedBorder)
                    TextField("Expected delivery", text: $purchaseOrderExpectedDate)
                        .textFieldStyle(.roundedBorder)
                }

                TextField("PO note", text: $purchaseOrderNote, axis: .vertical)
                    .textFieldStyle(.roundedBorder)

                Button("Create Purchase Order") {
                    Task {
                        await inventoryVM.createPurchaseOrder(
                            storeId: storeId,
                            supplierId: purchaseOrderSupplierId,
                            skuId: selectedInsight.skuId,
                            quantity: Int(purchaseOrderQuantity) ?? 1,
                            unitCost: Double(purchaseOrderUnitCost) ?? 0,
                            expectedDeliveryDate: purchaseOrderExpectedDate,
                            note: purchaseOrderNote
                        )
                        if inventoryVM.errorMessage == nil {
                            purchaseOrderQuantity = "1"
                            purchaseOrderUnitCost = "0"
                            purchaseOrderExpectedDate = ""
                            purchaseOrderNote = ""
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(inventoryVM.activeActionKey == "purchase-order-create" || purchaseOrderSupplierId.isEmpty)
            } else {
                Text("Pick a SKU before creating a purchase order.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 24))
    }

    private var bomRecipeBuilder: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("BOM Recipe Builder")
                .font(.headline)

            if let selectedInsight {
                Text("Define a material recipe for \(selectedInsight.skuCode).")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                TextField("Recipe name", text: $bomName)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    TextField("Yield quantity", text: $bomYieldQuantity)
                        .keyboardTypeCompat(.numberPad)
                        .textFieldStyle(.roundedBorder)
                    TextField("Recipe notes", text: $bomNotes, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                }

                componentDraftSection(
                    title: "Components",
                    drafts: $bomComponents,
                    options: componentOptions
                )

                Button("Create BOM Recipe") {
                    Task {
                        await inventoryVM.createBOMRecipe(
                            storeId: storeId,
                            finishedSkuId: selectedInsight.skuId,
                            name: bomName,
                            yieldQuantity: Int(bomYieldQuantity) ?? 1,
                            components: bomComponents.map(\.payload),
                            notes: bomNotes
                        )
                        if inventoryVM.errorMessage == nil {
                            bomName = ""
                            bomYieldQuantity = "1"
                            bomNotes = ""
                            bomComponents = [.empty]
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(inventoryVM.activeActionKey == "bom-create" || bomName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            } else {
                Text("Pick a SKU before creating a BOM recipe.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 24))
    }

    private var workOrderAndTransferBuilder: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Work Orders & Transfers")
                .font(.headline)

            if let selectedInsight {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Create manufacturing runs for \(selectedInsight.skuCode).")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    Picker("BOM", selection: $selectedBOMId) {
                        Text("No BOM recipe selected").tag("")
                        ForEach(selectedRecipes) { recipe in
                            Text("\(recipe.name) · yield \(recipe.yieldQuantity)").tag(recipe.id)
                        }
                    }
                    .pickerStyle(.menu)

                    Picker("Work order type", selection: $workOrderType) {
                        Text("Standard").tag("standard")
                        Text("Custom").tag("custom")
                    }
                    .pickerStyle(.segmented)

                    HStack {
                        TextField("Target qty", text: $workOrderQuantity)
                            .keyboardTypeCompat(.numberPad)
                            .textFieldStyle(.roundedBorder)
                        TextField("Due date", text: $workOrderDueDate)
                            .textFieldStyle(.roundedBorder)
                    }

                    TextField("Work order note", text: $workOrderNote, axis: .vertical)
                        .textFieldStyle(.roundedBorder)

                    if selectedBOMId.isEmpty {
                        componentDraftSection(
                            title: "Custom components",
                            drafts: $workOrderComponents,
                            options: componentOptions
                        )
                    }

                    Button("Create Work Order") {
                        Task {
                            await inventoryVM.createWorkOrder(
                                storeId: storeId,
                                finishedSkuId: selectedInsight.skuId,
                                targetQuantity: Int(workOrderQuantity) ?? 1,
                                bomId: selectedBOMId,
                                workOrderType: workOrderType,
                                customComponents: workOrderComponents.map(\.payload),
                                dueDate: workOrderDueDate,
                                note: workOrderNote
                            )
                            if inventoryVM.errorMessage == nil {
                                workOrderQuantity = "1"
                                workOrderDueDate = ""
                                workOrderNote = ""
                                workOrderComponents = [.empty]
                            }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(inventoryVM.activeActionKey == "work-order-create")
                }
                .padding()
                .background(Color.gray.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 20))

                VStack(alignment: .leading, spacing: 10) {
                    Text("Manual Stock Transfer")
                        .font(.headline)
                    HStack {
                        Picker("From", selection: $transferFromInventoryType) {
                            Text("Purchased").tag(InventoryType.purchased)
                            Text("Material").tag(InventoryType.material)
                            Text("Finished").tag(InventoryType.finished)
                        }
                        Picker("To", selection: $transferToInventoryType) {
                            Text("Finished").tag(InventoryType.finished)
                            Text("Material").tag(InventoryType.material)
                            Text("Purchased").tag(InventoryType.purchased)
                        }
                    }
                    .pickerStyle(.menu)

                    HStack {
                        TextField("Quantity", text: $transferQuantity)
                            .keyboardTypeCompat(.numberPad)
                            .textFieldStyle(.roundedBorder)
                        TextField("Transfer note", text: $transferNote, axis: .vertical)
                            .textFieldStyle(.roundedBorder)
                    }

                    Button("Create Transfer") {
                        Task {
                            await inventoryVM.createTransfer(
                                storeId: storeId,
                                skuId: selectedInsight.skuId,
                                quantity: Int(transferQuantity) ?? 1,
                                fromInventoryType: transferFromInventoryType.rawValue,
                                toInventoryType: transferToInventoryType.rawValue,
                                note: transferNote
                            )
                            if inventoryVM.errorMessage == nil {
                                transferQuantity = "1"
                                transferNote = ""
                            }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(inventoryVM.activeActionKey == "transfer-create")
                }
                .padding()
                .background(Color.gray.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 20))
            } else {
                Text("Pick a SKU before creating work orders or transfers.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 24))
    }

    private func componentDraftSection(
        title: String,
        drafts: Binding<[ComponentDraft]>,
        options: [InventoryInsight]
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Button("Add Component") {
                    drafts.wrappedValue.append(.empty)
                }
                .buttonStyle(.bordered)
            }

            ForEach(Array(drafts.wrappedValue.indices), id: \.self) { index in
                VStack(alignment: .leading, spacing: 8) {
                    Picker("Component SKU", selection: binding(for: drafts, index: index, keyPath: \.skuId)) {
                        Text("Select component").tag("")
                        ForEach(options) { option in
                            Text("\(option.skuCode) · \(option.description)").tag(option.skuId)
                        }
                    }
                    .pickerStyle(.menu)

                    HStack {
                        TextField("Qty", text: binding(for: drafts, index: index, keyPath: \.quantityRequired))
                            .keyboardTypeCompat(.numberPad)
                            .textFieldStyle(.roundedBorder)
                        TextField("Note", text: binding(for: drafts, index: index, keyPath: \.note))
                            .textFieldStyle(.roundedBorder)
                        Button("Remove") {
                            if drafts.wrappedValue.count > 1 {
                                drafts.wrappedValue.remove(at: index)
                            }
                        }
                        .buttonStyle(.bordered)
                        .disabled(drafts.wrappedValue.count == 1)
                    }
                }
                .padding()
                .background(Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 16))
            }
        }
    }

    private func binding(
        for drafts: Binding<[ComponentDraft]>,
        index: Int,
        keyPath: WritableKeyPath<ComponentDraft, String>
    ) -> Binding<String> {
        Binding(
            get: { drafts.wrappedValue[index][keyPath: keyPath] },
            set: { drafts.wrappedValue[index][keyPath: keyPath] = $0 }
        )
    }

    private func hydrateSupplierForm(_ supplier: SupplierSummary) {
        supplierId = supplier.id
        supplierName = supplier.name
        supplierContactName = supplier.contactName ?? ""
        supplierEmail = supplier.email ?? ""
        supplierPhone = supplier.phone ?? ""
        supplierLeadTimeDays = String(supplier.leadTimeDays)
        supplierCurrency = supplier.currency
        supplierNotes = supplier.notes ?? ""
        supplierIsActive = supplier.isActive
    }

    private func resetSupplierForm() {
        supplierId = nil
        supplierName = ""
        supplierContactName = ""
        supplierEmail = ""
        supplierPhone = ""
        supplierLeadTimeDays = "7"
        supplierCurrency = "SGD"
        supplierNotes = ""
        supplierIsActive = true
    }

    private func seedDefaultSelections() {
        if purchaseOrderSupplierId.isEmpty, let firstSupplier = inventoryVM.suppliers.first {
            purchaseOrderSupplierId = firstSupplier.id
        }
        if selectedBOMId.isEmpty, let firstRecipe = selectedRecipes.first {
            selectedBOMId = firstRecipe.id
        }
    }
}

private struct ComponentDraft: Identifiable {
    let id = UUID()
    var skuId: String
    var quantityRequired: String
    var note: String

    static let empty = ComponentDraft(skuId: "", quantityRequired: "1", note: "")

    var payload: ComponentDraftPayload {
        ComponentDraftPayload(
            skuId: skuId,
            quantityRequired: max(Int(quantityRequired) ?? 0, 0),
            note: note
        )
    }
}

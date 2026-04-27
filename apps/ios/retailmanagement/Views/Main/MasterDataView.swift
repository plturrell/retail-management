//
//  MasterDataView.swift
//  retailmanagement
//
//  iPad/macOS twin of apps/staff-portal/src/pages/MasterDataPage.tsx.
//  Talks to the LAN-bound master-data mini-server (no auth).
//

import SwiftUI
import UniformTypeIdentifiers

struct MasterDataView: View {
    @State private var vm = MasterDataViewModel()
    @State private var showFilePicker = false
    @State private var showVisualPicker = false
    @State private var showApiBaseEditor = false
    @State private var apiBaseDraft = MasterDataService.shared.baseUrl
    @State private var commitAlert: String?
    @State private var recommendationAlert: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    bannerBar
                    headerActions
                    if let err = vm.globalError { errorCard(err) }
                    bulkBanner
                    if let stats = vm.stats { statsRow(stats) }
                    filterBar
                    if let last = vm.lastExport { exportResultCard(last) }
                    productList
                }
                .padding()
            }
            .navigationTitle("Master Data — Pricing")
            .task { await vm.load() }
            .refreshable { await vm.load() }
            .fileImporter(
                isPresented: $showFilePicker,
                allowedContentTypes: [.pdf, .image, .jpeg, .png, .tiff],
                allowsMultipleSelection: false
            ) { result in
                handleFilePick(result)
            }
            .fileImporter(
                isPresented: $showVisualPicker,
                allowedContentTypes: [.image, .jpeg, .png, .heic],
                allowsMultipleSelection: false
            ) { result in
                handleVisualPick(result)
            }
            .sheet(isPresented: visualSheetBinding) {
                if case .result(let response) = vm.visualSearch {
                    VisualSearchSheet(
                        response: response,
                        onClose: { vm.cancelVisualSearch() }
                    )
                }
            }
            .alert("Visual search failed", isPresented: visualErrorBinding) {
                Button("OK") { vm.cancelVisualSearch() }
            } message: {
                if case .error(let msg) = vm.visualSearch { Text(msg) }
            }
            .sheet(isPresented: previewSheetBinding) {
                if case .preview(let p, let sel) = vm.ingest {
                    IngestPreviewSheet(
                        preview: p,
                        selected: sel,
                        onToggle: { vm.togglePreviewItem(code: $0) },
                        onCancel: { vm.cancelIngest() },
                        onCommit: {
                            Task {
                                await vm.commitIngest()
                                if case .idle = vm.ingest {
                                    commitAlert = "Products added. Pull to refresh if you don't see them."
                                }
                            }
                        }
                    )
                }
            }
            .sheet(isPresented: recommendationSheetBinding) {
                if case .preview(let response, let selected) = vm.recommendations {
                    PriceRecommendationsSheet(
                        response: response,
                        selected: selected,
                        onToggle: { vm.toggleRecommendation(sku: $0) },
                        onCancel: { vm.cancelRecommendations() },
                        onCommit: {
                            Task {
                                let applied = await vm.applyRecommendations()
                                if case .idle = vm.recommendations, applied > 0 {
                                    recommendationAlert = "Applied \(applied) AI price recommendation\(applied == 1 ? "" : "s")."
                                }
                            }
                        }
                    )
                }
            }
            .alert("Master data", isPresented: Binding(
                get: { commitAlert != nil },
                set: { if !$0 { commitAlert = nil } }
            )) {
                Button("OK") { commitAlert = nil }
            } message: {
                Text(commitAlert ?? "")
            }
            .alert("AI recommendations", isPresented: Binding(
                get: { recommendationAlert != nil },
                set: { if !$0 { recommendationAlert = nil } }
            )) {
                Button("OK") { recommendationAlert = nil }
            } message: {
                Text(recommendationAlert ?? "")
            }
            .alert("Invoice ingest failed", isPresented: ingestErrorBinding) {
                Button("OK") { vm.cancelIngest() }
            } message: {
                if case .error(let msg) = vm.ingest { Text(msg) }
            }
            .alert("AI price recommendations failed", isPresented: recommendationErrorBinding) {
                Button("OK") { vm.cancelRecommendations() }
            } message: {
                if case .error(let msg) = vm.recommendations { Text(msg) }
            }
            .sheet(isPresented: $showApiBaseEditor) {
                apiBaseSheet
            }
        }
    }

    // MARK: - Header pieces

    private var bannerBar: some View {
        HStack(spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.yellow)
            Text("Local-only mode · API at \(MasterDataService.shared.baseUrl)")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Button("Configure API URL") {
                apiBaseDraft = MasterDataService.shared.baseUrl
                showApiBaseEditor = true
            }
            .font(.caption)
        }
        .padding(8)
        .background(Color.yellow.opacity(0.12))
        .cornerRadius(6)
    }

    private var headerActions: some View {
        HStack(spacing: 8) {
            Button {
                Task { await vm.generatePriceRecommendations() }
            } label: {
                Label(recommendationButtonLabel, systemImage: "sparkles")
            }
            .buttonStyle(.borderedProminent)
            .disabled(isRecommendationInFlight)

            Button {
                showFilePicker = true
            } label: {
                Label(uploadButtonLabel, systemImage: "doc.viewfinder")
            }
            .buttonStyle(.bordered)
            .disabled(isUploadInFlight)

            Button {
                showVisualPicker = true
            } label: {
                Label(visualSearchButtonLabel, systemImage: "camera.viewfinder")
            }
            .buttonStyle(.bordered)
            .disabled(isVisualSearchInFlight)

            Spacer()

            Button {
                Task { await vm.bulkMarkSaleReady() }
            } label: {
                Label(bulkButtonLabel, systemImage: "checkmark.seal")
            }
            .buttonStyle(.bordered)
            .disabled(isBulkInFlight)

            Button {
                Task { await vm.regenerateExcel() }
            } label: {
                if vm.isExporting {
                    ProgressView()
                } else {
                    Label("Regenerate NEC Excel", systemImage: "tablecells")
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(vm.isExporting)
        }
    }

    private var bulkButtonLabel: String {
        if case .running = vm.bulk { return "Marking…" }
        return "Mark all priced sale-ready"
    }

    private var isBulkInFlight: Bool {
        if case .running = vm.bulk { return true }
        return false
    }

    private var uploadButtonLabel: String {
        switch vm.ingest {
        case .uploading(let f): return "OCR'ing \(f)…"
        case .committing: return "Adding…"
        default: return "Process invoice…"
        }
    }

    private var recommendationButtonLabel: String {
        switch vm.recommendations {
        case .generating: return "Generating AI prices…"
        case .applying: return "Applying AI prices…"
        default: return "AI recommend prices…"
        }
    }

    private var isUploadInFlight: Bool {
        switch vm.ingest {
        case .uploading, .committing: return true
        default: return false
        }
    }

    private var isRecommendationInFlight: Bool {
        switch vm.recommendations {
        case .generating, .applying: return true
        default: return false
        }
    }

    private var visualSearchButtonLabel: String {
        switch vm.visualSearch {
        case .searching(let f): return "Matching \(f)…"
        default: return "Find by photo"
        }
    }

    private var isVisualSearchInFlight: Bool {
        if case .searching = vm.visualSearch { return true }
        return false
    }

    @ViewBuilder
    private var bulkBanner: some View {
        switch vm.bulk {
        case .done(let r):
            HStack(alignment: .top, spacing: 8) {
                Label("\(r.updated) flipped to sale-ready", systemImage: "checkmark.seal.fill")
                    .font(.callout)
                    .foregroundStyle(.green)
                Text("skipped: \(r.skipped.noPrice) no price · \(r.skipped.alreadyReady) already ready")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Dismiss") { vm.dismissBulk() }
                    .font(.caption2)
            }
            .padding(10)
            .background(Color.green.opacity(0.10))
            .cornerRadius(6)
        case .error(let msg):
            HStack(alignment: .top, spacing: 8) {
                Label("Bulk update failed", systemImage: "xmark.octagon.fill")
                    .font(.callout)
                    .foregroundStyle(.red)
                Text(msg).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                Spacer()
                Button("Dismiss") { vm.dismissBulk() }
                    .font(.caption2)
            }
            .padding(10)
            .background(Color.red.opacity(0.08))
            .cornerRadius(6)
        default:
            EmptyView()
        }
    }

    private func errorCard(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(message).font(.callout).foregroundStyle(.red)
            Text("Start the mini-server on the Mac with: python tools/server/master_data_api.py")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.red.opacity(0.08))
        .cornerRadius(8)
    }

    private func statsRow(_ s: MasterDataStats) -> some View {
        let columns = [GridItem(.adaptive(minimum: 150), spacing: 12)]
        let totalLabel = (s.purchasedOnly ?? false) ? "Purchased SKUs" : "Total products"
        return LazyVGrid(columns: columns, spacing: 12) {
            statTile(totalLabel, value: s.total)
            statTile("Sale ready", value: s.saleReady, tone: s.saleReady > 0 ? .green : nil)
            statTile("Sale-ready missing price", value: s.saleReadyMissingPrice, tone: s.saleReadyMissingPrice > 0 ? .orange : .green)
            statTile("New SKUs awaiting price", value: s.needsPriceFlag, tone: s.needsPriceFlag > 0 ? .orange : .green)
            if let missing = s.missingCost {
                statTile("Missing cost", value: missing, tone: missing > 0 ? .orange : .green)
            }
        }
    }

    private func statTile(_ label: String, value: Int, tone: Color? = nil) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label.uppercased())
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text("\(value)")
                .font(.title2.bold())
                .foregroundStyle(tone ?? .primary)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .cornerRadius(8)
    }

    private var filterBar: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("Search SKU, internal code, barcode, description…", text: $vm.search)
                    .textFieldStyle(.roundedBorder)
            }
            HStack(spacing: 12) {
                Picker("Supplier", selection: $vm.supplierFilter) {
                    Text("All suppliers").tag("all")
                    ForEach(vm.supplierOptions, id: \.self) { code in
                        Text(supplierLabel(code)).tag(code)
                    }
                }
                .pickerStyle(.menu)

                Toggle("Purchased only", isOn: $vm.purchasedOnly)
                    .toggleStyle(.switch)
                    .onChange(of: vm.purchasedOnly) { _, _ in
                        Task { await vm.load() }
                    }

                Toggle("Needs price only", isOn: $vm.needsPriceOnly)
                    .toggleStyle(.switch)
                    .onChange(of: vm.needsPriceOnly) { _, _ in
                        Task { await vm.load() }
                    }

                Spacer()
                Button {
                    Task { await vm.load() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
        }
    }

    private func exportResultCard(_ res: MasterDataExportResult) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if res.ok {
                Text("Excel regenerated").font(.callout.bold()).foregroundStyle(.green)
                if let url = res.downloadUrl {
                    Text("\(MasterDataService.shared.baseUrl)\(url)")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            } else {
                Text("Export failed (exit \(res.exitCode))")
                    .font(.callout.bold())
                    .foregroundStyle(.red)
                Text(res.stderr.isEmpty ? res.stdout : res.stderr)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(8)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background((res.ok ? Color.green : Color.red).opacity(0.08))
        .cornerRadius(8)
    }

    // MARK: - Product list

    private var productList: some View {
        VStack(alignment: .leading, spacing: 0) {
            if vm.isLoading && vm.rows.isEmpty {
                HStack { Spacer(); ProgressView(); Spacer() }.padding(40)
            } else if vm.filteredRows.isEmpty {
                HStack {
                    Spacer()
                    Text("Nothing to show with these filters.")
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(40)
            } else {
                ForEach(vm.filteredRows) { row in
                    ProductRowCard(
                        row: row,
                        onPriceChange: { newValue in
                            vm.updateRow(row.id) { $0.draftPrice = newValue; $0.save = .idle }
                        },
                        onNotesChange: { newValue in
                            vm.updateRow(row.id) { $0.draftNotes = newValue; $0.save = .idle }
                        },
                        onSaleReadyChange: { newValue in
                            vm.updateRow(row.id) { $0.saleReady = newValue; $0.save = .idle }
                        },
                        onCommit: { Task { await vm.saveRow(id: row.id) } }
                    )
                    Divider()
                }
            }
        }
        .background(.background)
        .cornerRadius(8)
    }

    // MARK: - Helpers

    private func handleFilePick(_ result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            guard let url = urls.first else { return }
            let didStart = url.startAccessingSecurityScopedResource()
            let mime = mimeType(for: url)
            Task {
                defer { if didStart { url.stopAccessingSecurityScopedResource() } }
                await vm.uploadInvoice(fileURL: url, mimeType: mime)
            }
        case .failure(let err):
            vm.globalError = err.localizedDescription
        }
    }

    private func handleVisualPick(_ result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            guard let url = urls.first else { return }
            let didStart = url.startAccessingSecurityScopedResource()
            let mime = mimeType(for: url)
            Task {
                defer { if didStart { url.stopAccessingSecurityScopedResource() } }
                await vm.runVisualSearch(fileURL: url, mimeType: mime)
            }
        case .failure(let err):
            vm.globalError = err.localizedDescription
        }
    }

    private func mimeType(for url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "pdf": return "application/pdf"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "tif", "tiff": return "image/tiff"
        case "heic", "heif": return "image/heic"
        default: return "application/octet-stream"
        }
    }

    private func supplierLabel(_ code: String) -> String {
        switch code {
        case "CN-001": return "Hengwei Craft"
        case "(none)": return "Internal / Other"
        default: return code
        }
    }

    private var previewSheetBinding: Binding<Bool> {
        Binding(
            get: { if case .preview = vm.ingest { return true } else { return false } },
            set: { if !$0 { vm.cancelIngest() } }
        )
    }

    private var ingestErrorBinding: Binding<Bool> {
        Binding(
            get: { if case .error = vm.ingest { return true } else { return false } },
            set: { if !$0 { vm.cancelIngest() } }
        )
    }

    private var recommendationSheetBinding: Binding<Bool> {
        Binding(
            get: { if case .preview = vm.recommendations { return true } else { return false } },
            set: { if !$0 { vm.cancelRecommendations() } }
        )
    }

    private var recommendationErrorBinding: Binding<Bool> {
        Binding(
            get: { if case .error = vm.recommendations { return true } else { return false } },
            set: { if !$0 { vm.cancelRecommendations() } }
        )
    }

    private var visualSheetBinding: Binding<Bool> {
        Binding(
            get: { if case .result = vm.visualSearch { return true } else { return false } },
            set: { if !$0 { vm.cancelVisualSearch() } }
        )
    }

    private var visualErrorBinding: Binding<Bool> {
        Binding(
            get: { if case .error = vm.visualSearch { return true } else { return false } },
            set: { if !$0 { vm.cancelVisualSearch() } }
        )
    }

    private var apiBaseSheet: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("e.g. http://192.168.1.42:8765", text: $apiBaseDraft)
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        #endif
                        .autocorrectionDisabled(true)
                } header: {
                    Text("Master-data API base URL")
                } footer: {
                    Text("On iPad, set this to the Mac's LAN IP shown in the mini-server startup banner.")
                }
            }
            .navigationTitle("Configure API")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { showApiBaseEditor = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        MasterDataService.shared.baseUrl = apiBaseDraft.trimmingCharacters(in: .whitespacesAndNewlines)
                        showApiBaseEditor = false
                        Task { await vm.load() }
                    }
                }
            }
        }
    }
}

// MARK: - Row card

private struct ProductRowCard: View {
    let row: MasterDataRowDraft
    let onPriceChange: (String) -> Void
    let onNotesChange: (String) -> Void
    let onSaleReadyChange: (Bool) -> Void
    let onCommit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(row.product.skuCode)
                        .font(.callout.monospaced())
                    Text("PLU \(row.product.necPlu ?? "—")")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                    if let code = row.product.internalCode {
                        Text("internal \(code)")
                            .font(.caption2.monospaced())
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(minWidth: 180, alignment: .leading)

                VStack(alignment: .leading, spacing: 2) {
                    Text(row.product.description ?? "—")
                        .font(.subheadline)
                        .lineLimit(2)
                    HStack(spacing: 10) {
                        if let t = row.product.productType { tag(t) }
                        if let m = row.product.material { tag(m) }
                        if let s = row.product.size, !s.isEmpty { tag(s) }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                VStack(alignment: .trailing, spacing: 2) {
                    Text("Cost")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(formatMoney(row.product.costPrice))
                        .font(.callout.monospaced())
                    if let qty = row.product.qtyOnHand {
                        Text("qty \(Int(qty))")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(width: 80, alignment: .trailing)
            }

            HStack(spacing: 10) {
                priceField
                marginLabel
                Toggle("Sale ready", isOn: Binding(
                    get: { row.saleReady },
                    set: { onSaleReadyChange($0); onCommit() }
                ))
                .toggleStyle(.switch)
                Spacer()
                statusLabel
            }

            TextField("Pricing notes (optional)", text: Binding(
                get: { row.draftNotes },
                set: { onNotesChange($0) }
            ), onCommit: { onCommit() })
            .textFieldStyle(.roundedBorder)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
    }

    private var priceField: some View {
        HStack(spacing: 4) {
            Text("S$").font(.caption).foregroundStyle(.secondary)
            TextField(suggestedPrice, text: Binding(
                get: { row.draftPrice },
                set: { onPriceChange($0) }
            ), onCommit: { onCommit() })
            .textFieldStyle(.roundedBorder)
            #if os(iOS)
            .keyboardType(.decimalPad)
            #endif
            .frame(width: 100)
        }
    }

    private var marginLabel: some View {
        let margin = computeMarginPct()
        return Text(margin.map { "margin \($0)%" } ?? "—")
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    @ViewBuilder
    private var statusLabel: some View {
        switch row.save {
        case .idle:
            EmptyView()
        case .saving:
            HStack(spacing: 4) { ProgressView().controlSize(.mini); Text("Saving…").font(.caption2) }
                .foregroundStyle(.secondary)
        case .saved:
            Label("Saved", systemImage: "checkmark.circle.fill")
                .font(.caption2)
                .foregroundStyle(.green)
        case .error(let msg):
            Label(msg, systemImage: "xmark.octagon.fill")
                .font(.caption2)
                .foregroundStyle(.red)
                .lineLimit(1)
        }
    }

    private func tag(_ text: String) -> some View {
        Text(text)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Color.secondary.opacity(0.12))
            .cornerRadius(4)
    }

    private var suggestedPrice: String {
        guard let cost = row.product.costPrice, cost > 0 else { return "—" }
        let target = (cost / 0.4 / 5.0).rounded() * 5.0
        return String(format: "%g", target)
    }

    private func computeMarginPct() -> Int? {
        guard let cost = row.product.costPrice,
              let price = Double(row.draftPrice),
              cost > 0, price > 0 else { return nil }
        return Int(((price - cost) / price * 100).rounded())
    }

    private func formatMoney(_ v: Double?) -> String {
        guard let v else { return "—" }
        return String(format: "S$%.2f", v)
    }
}

// MARK: - Ingest preview sheet

private struct IngestPreviewSheet: View {
    let preview: IngestPreview
    let selected: Set<String>
    let onToggle: (String) -> Void
    let onCancel: () -> Void
    let onCommit: () -> Void

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 0) {
                header
                List {
                    ForEach(preview.items) { item in
                        previewRow(item)
                    }
                }
                .listStyle(.plain)
                footer
            }
            .navigationTitle("OCR preview")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel", action: onCancel)
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(headerTitle).font(.headline)
            Text(headerSubtitle).font(.caption).foregroundStyle(.secondary)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.secondary.opacity(0.06))
    }

    private var headerTitle: String {
        let bits = [preview.documentType, preview.documentNumber].compactMap { $0 }.filter { !$0.isEmpty }
        return bits.isEmpty ? "Document" : bits.joined(separator: " · ")
    }

    private var headerSubtitle: String {
        var parts: [String] = []
        if let s = preview.supplierName { parts.append(s) }
        if let d = preview.documentDate { parts.append(d) }
        if let c = preview.currency, let t = preview.documentTotal {
            parts.append("\(c) \(Int(t))")
        }
        let s = preview.summary
        parts.append("\(s.newSkus) new · \(s.alreadyExists) exists · \(s.skipped) skipped")
        if let withImg = s.itemsWithImage, let extracted = s.imagesExtracted, extracted > 0 {
            parts.append("\(withImg)/\(s.totalLines) matched to \(extracted) images")
        }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private func thumbnail(for path: String?, confidence: String?) -> some View {
        if let url = MasterDataService.shared.resolveAssetUrl(path) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .empty:
                    Rectangle().fill(Color.secondary.opacity(0.12))
                case .success(let image):
                    image.resizable().aspectRatio(contentMode: .fill)
                case .failure:
                    Image(systemName: "photo")
                        .foregroundStyle(.secondary)
                @unknown default:
                    EmptyView()
                }
            }
            .frame(width: 56, height: 56)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(
                RoundedRectangle(cornerRadius: 6)
                    .stroke(confidence == "matched" ? Color.green.opacity(0.6) : Color.secondary.opacity(0.3), lineWidth: 1)
            )
        } else {
            Rectangle()
                .fill(Color.secondary.opacity(0.08))
                .frame(width: 56, height: 56)
                .overlay(Image(systemName: "photo").foregroundStyle(.secondary).opacity(0.4))
                .clipShape(RoundedRectangle(cornerRadius: 6))
        }
    }

    @ViewBuilder
    private func previewRow(_ item: IngestPreviewItem) -> some View {
        let code = item.supplierItemCode
        let isNew = item.proposedSku != nil && !(item.alreadyExists ?? false) && item.skipReason == nil && code != nil
        let isChecked = code.map { selected.contains($0) } ?? false

        HStack(alignment: .top, spacing: 10) {
            if isNew, let code {
                Button {
                    onToggle(code)
                } label: {
                    Image(systemName: isChecked ? "checkmark.square.fill" : "square")
                        .font(.title3)
                }
                .buttonStyle(.plain)
            } else {
                Image(systemName: "minus.square")
                    .font(.title3)
                    .foregroundStyle(.secondary)
                    .opacity(0.4)
            }

            thumbnail(for: item.imageUrl, confidence: item.imageMatchConfidence)

            VStack(alignment: .leading, spacing: 2) {
                Text(item.productNameEn ?? "—").font(.subheadline).lineLimit(2)
                HStack(spacing: 8) {
                    Text(code ?? "—").font(.caption.monospaced()).foregroundStyle(.secondary)
                    if let t = item.productType { Text(t).font(.caption2).foregroundStyle(.secondary) }
                    if let m = item.material { Text(m).font(.caption2).foregroundStyle(.secondary) }
                    if let s = item.size, !s.isEmpty { Text(s).font(.caption2).foregroundStyle(.secondary) }
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 2) {
                if let q = item.quantity { Text("qty \(q)").font(.caption2).foregroundStyle(.secondary) }
                if let p = item.unitPriceCny { Text("¥\(Int(p))").font(.caption.monospaced()) }
                if let s = item.proposedCostSgd { Text("S$\(String(format: "%.2f", s))").font(.caption.monospaced()) }
            }

            VStack(alignment: .trailing, spacing: 2) {
                Text(item.proposedSku ?? "—").font(.caption.monospaced())
                Text(item.proposedPlu ?? "—").font(.caption2.monospaced()).foregroundStyle(.secondary)
                stateLabel(item)
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private func stateLabel(_ item: IngestPreviewItem) -> some View {
        if item.alreadyExists ?? false {
            Text("exists").font(.caption2).foregroundStyle(.secondary)
        } else if let r = item.skipReason {
            Text(r).font(.caption2).foregroundStyle(.orange).lineLimit(1)
        } else if item.proposedSku != nil {
            Text("new").font(.caption2).foregroundStyle(.green)
        }
    }

    private var footer: some View {
        HStack {
            Text("\(selected.count) selected of \(eligibleCount) new SKUs.")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Button("Add \(selected.count) to master", action: onCommit)
                .buttonStyle(.borderedProminent)
                .disabled(selected.isEmpty)
        }
        .padding()
        .background(Color.secondary.opacity(0.06))
    }

    private var eligibleCount: Int {
        preview.items.filter {
            $0.proposedSku != nil
            && !($0.alreadyExists ?? false)
            && $0.skipReason == nil
            && $0.supplierItemCode != nil
        }.count
    }
}

// MARK: - AI recommendation sheet

private struct PriceRecommendationsSheet: View {
    let response: PriceRecommendationsResponse
    let selected: Set<String>
    let onToggle: (String) -> Void
    let onCancel: () -> Void
    let onCommit: () -> Void

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 0) {
                header
                List {
                    if let rules = response.rulesInferred, !rules.isEmpty {
                        Section("Inferred rules") {
                            ForEach(Array(rules.enumerated()), id: \.offset) { _, rule in
                                Text(rule)
                                    .font(.subheadline)
                            }
                        }
                    }

                    if let notes = response.notes, !notes.isEmpty {
                        Section("Notes") {
                            Text(notes)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    }

                    Section("Recommendations") {
                        ForEach(response.recommendations) { recommendation in
                            recommendationRow(recommendation)
                        }
                }
                }
                .listStyle(.inset)
                footer
            }
            .navigationTitle("AI price preview")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel", action: onCancel)
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Preview AI-generated retail prices before writing them back to master data.")
                .font(.headline)
            Text(headerSubtitle)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.secondary.opacity(0.06))
    }

    private var headerSubtitle: String {
        var parts: [String] = []
        if let priced = response.pricedExamplesCount {
            parts.append("\(priced) priced examples")
        }
        if let targets = response.targetCount {
            parts.append("\(targets) targets")
        }
        parts.append("\(selected.count) selected")
        return parts.joined(separator: " · ")
    }

    private func recommendationRow(_ recommendation: PriceRecommendation) -> some View {
        let isChecked = selected.contains(recommendation.skuCode)
        return HStack(alignment: .top, spacing: 10) {
            Button {
                onToggle(recommendation.skuCode)
            } label: {
                Image(systemName: isChecked ? "checkmark.square.fill" : "square")
                    .font(.title3)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(recommendation.skuCode)
                        .font(.caption.monospaced())
                    Text(recommendation.confidence.label)
                        .font(.caption2)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(confidenceColor(recommendation.confidence).opacity(0.14))
                        .foregroundStyle(confidenceColor(recommendation.confidence))
                        .cornerRadius(4)
                }

                Text(recommendation.rationale)
                    .font(.subheadline)

                if let comparable = recommendation.comparableSkus, !comparable.isEmpty {
                    Text("Comps: \(comparable.joined(separator: ", "))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 4) {
                Text("S$\(String(format: "%.2f", recommendation.recommendedRetailSgd))")
                    .font(.headline.monospaced())
                Text(recommendation.impliedMarginPct.map { "margin \($0)%" } ?? "margin —")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    private var footer: some View {
        HStack {
            Text("\(selected.count) selected of \(response.recommendations.count) recommendations.")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Button(selected.count == response.recommendations.count ? "Apply all" : "Apply \(selected.count)") {
                onCommit()
            }
            .buttonStyle(.borderedProminent)
            .disabled(selected.isEmpty)
        }
        .padding()
        .background(Color.secondary.opacity(0.06))
    }

    private func confidenceColor(_ confidence: PriceRecommendationConfidence) -> Color {
        switch confidence {
        case .high: return .green
        case .medium: return .orange
        case .low: return .red
        }
    }
}

// MARK: - Visual search sheet

private struct VisualSearchSheet: View {
    let response: VisualSearchResponse
    let onClose: () -> Void

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 0) {
                header
                List {
                    Section("Top \(response.matches.count) matches") {
                        ForEach(response.matches) { match in
                            matchRow(match)
                        }
                    }
                }
                .listStyle(.inset)
            }
            .navigationTitle("Visual search")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", action: onClose)
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Gemini description")
                .font(.headline)
            Text(response.queryText.isEmpty ? "—" : response.queryText)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text("Searched \(response.catalogSize) catalog images")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.secondary.opacity(0.06))
    }

    @ViewBuilder
    private func matchRow(_ m: VisualSearchMatch) -> some View {
        HStack(alignment: .top, spacing: 12) {
            thumbnail(m.imageUrl)
                .frame(width: 72, height: 72)
                .clipShape(RoundedRectangle(cornerRadius: 6))

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text(m.sku ?? m.code ?? "—")
                        .font(.callout.monospaced())
                    if let plu = m.necPlu {
                        Text("PLU \(plu)")
                            .font(.caption2.monospaced())
                            .foregroundStyle(.secondary)
                    }
                }
                Text(m.description ?? m.catalogText ?? "—")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 2) {
                Text("\(Int((m.similarity * 100).rounded()))%")
                    .font(.headline.monospaced())
                    .foregroundStyle(similarityColor(m.similarity))
                if let p = m.retailPrice {
                    Text("S$\(String(format: "%.2f", p))").font(.caption2.monospaced())
                }
                if let q = m.qtyOnHand {
                    Text("qty \(Int(q))").font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private func thumbnail(_ path: String?) -> some View {
        if let url = MasterDataService.shared.resolveAssetUrl(path) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .empty: Rectangle().fill(Color.secondary.opacity(0.12))
                case .success(let img): img.resizable().aspectRatio(contentMode: .fill)
                case .failure: Image(systemName: "photo").foregroundStyle(.secondary)
                @unknown default: EmptyView()
                }
            }
        } else {
            Rectangle()
                .fill(Color.secondary.opacity(0.08))
                .overlay(Image(systemName: "photo").foregroundStyle(.secondary).opacity(0.4))
        }
    }

    private func similarityColor(_ s: Double) -> Color {
        if s >= 0.85 { return .green }
        if s >= 0.7 { return .orange }
        return .secondary
    }
}

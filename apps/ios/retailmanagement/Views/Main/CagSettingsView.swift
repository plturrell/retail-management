//
//  CagSettingsView.swift
//  retailmanagement
//
//  System-admin-only mobile parity for the staff-portal CagSettingsPage.
//  Surfaces SFTP credentials, tenant identifiers, scheduler defaults, and
//  the same Save / Test SFTP / Run scheduled push now / Clear actions.
//  Per-store NEC mappings and the remote error log panel remain web-only.
//  Owners no longer see this screen — the SettingsView nav entry is gated
//  on ``AppUser.isSystemAdmin``, matching the backend ``require_system_admin``
//  gate on PUT/DELETE /api/cag/config.
//

import SwiftUI

struct CagSettingsView: View {
    @State private var vm = CagSettingsViewModel()
    @State private var confirmClear = false
    @State private var confirmRunPush = false

    var body: some View {
        Group {
            if vm.isLoading && vm.config == nil {
                ProgressView().controlSize(.large).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                form
            }
        }
        .navigationTitle("NEC CAG Integration")
        #if !os(macOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .task { if vm.config == nil { await vm.load() } }
        .refreshable { await vm.load() }
        .alert("Wipe saved CAG config?", isPresented: $confirmClear) {
            Button("Cancel", role: .cancel) {}
            Button("Wipe", role: .destructive) { Task { await vm.clear() } }
        } message: {
            Text("Environment defaults (.env) will remain.")
        }
        .alert("Run scheduled push now?", isPresented: $confirmRunPush) {
            Button("Cancel", role: .cancel) {}
            Button("Run") { Task { await vm.runScheduledPush() } }
        } message: {
            Text("Uploads the live master bundle to the configured SFTP target using the current defaults.")
        }
    }

    private var form: some View {
        Form {
            statusSection
            if let banner = vm.banner { bannerSection(banner) }
            effectivePayloadSection
            sftpSection
            tenantSection
            foldersSection
            schedulerSection
            if let r = vm.testResult { testResultSection(r) }
            if let r = vm.pushResult { pushResultSection(r) }
            actionsSection
        }
        #if os(macOS)
        .formStyle(.grouped)
        #endif
    }

    // MARK: - Sections

    private var statusSection: some View {
        Section {
            HStack {
                Image(systemName: vm.config?.isConfigured == true ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                    .foregroundStyle(vm.config?.isConfigured == true ? .green : .orange)
                VStack(alignment: .leading, spacing: 2) {
                    Text(vm.config?.isConfigured == true ? "Configured" : "Incomplete")
                        .font(.subheadline.bold())
                    if let updated = vm.config?.updatedAt, !updated.isEmpty {
                        Text("Last updated \(updated)\(vm.config?.updatedBy.isEmpty == false ? " by \(vm.config!.updatedBy)" : "")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            if let cfg = vm.config, !cfg.schedulerLastRunAt.isEmpty {
                lastRunBanner(cfg)
            }
        }
    }

    private func bannerSection(_ banner: CagSettingsViewModel.Banner) -> some View {
        Section {
            Label(banner.text, systemImage: bannerIcon(banner.kind))
                .foregroundStyle(bannerTint(banner.kind))
                .font(.caption)
        }
    }

    private var effectivePayloadSection: some View {
        Section("Effective scheduled payload") {
            LabeledContent("Tenant", value: vm.effectiveTenant.isEmpty ? "—" : vm.effectiveTenant)
            LabeledContent("Store ID", value: vm.effectiveStoreId.isEmpty ? "—" : vm.effectiveStoreId)
                .foregroundStyle(vm.effectiveStoreIdValid ? Color.primary : Color.red)
            LabeledContent("Tax mode", value: vm.schedulerDefaultTaxable ? "G — Landside (taxable)" : "N — Airside (non-taxable)")
            LabeledContent("Cron", value: vm.config?.schedulerCron ?? "—")
            if let aud = vm.config?.schedulerAudience, !aud.isEmpty {
                LabeledContent("Audience", value: aud)
                    .lineLimit(2)
                    .truncationMode(.middle)
            }
        }
    }

    private var sftpSection: some View {
        Section("SFTP server") {
            TextField("Host", text: $vm.host)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            TextField("Port", text: $vm.port)
                #if !os(macOS)
                .keyboardType(.numberPad)
                #endif
            TextField("Username", text: $vm.username)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            SecureField(vm.config?.hasPassword == true ? "•••••• (saved — leave blank to keep)" : "Password (optional if using key)",
                        text: $vm.password)
            TextField("Private key path", text: $vm.keyPath)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            SecureField(vm.config?.hasKeyPassphrase == true ? "•••••• (saved — leave blank to keep)" : "Key passphrase (optional)",
                        text: $vm.keyPassphrase)
        }
    }

    private var tenantSection: some View {
        Section("Tenant identifiers") {
            TextField("Tenant folder (Customer No.)", text: $vm.tenantFolder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            TextField("Default NEC Store ID (5 digits)", text: $vm.defaultNecStoreId)
                #if !os(macOS)
                .keyboardType(.numberPad)
                #endif
            Picker("Default tax mode", selection: $vm.defaultTaxable) {
                Text("Landside (taxable)").tag(true)
                Text("Airside (non-taxable)").tag(false)
            }
        }
    }


    private var foldersSection: some View {
        Section("SFTP folders (rarely changed)") {
            TextField("Inbound / Working", text: $vm.inboundWorking)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            TextField("Inbound / Error", text: $vm.inboundError)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            TextField("Inbound / Archive", text: $vm.inboundArchive)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
        }
    }

    private var schedulerSection: some View {
        Section {
            Picker("Status", selection: $vm.schedulerEnabled) {
                Text("Enabled").tag(true)
                Text("Paused").tag(false)
            }
            TextField("Cron expression", text: $vm.schedulerCron)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            TextField("Default tenant code", text: $vm.schedulerDefaultTenant, prompt: Text(vm.tenantFolder.isEmpty ? "200151" : vm.tenantFolder))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            TextField("Default NEC Store ID", text: $vm.schedulerDefaultStoreId, prompt: Text(vm.defaultNecStoreId.isEmpty ? "80001" : vm.defaultNecStoreId))
                #if !os(macOS)
                .keyboardType(.numberPad)
                #endif
            Picker("Default tax mode", selection: $vm.schedulerDefaultTaxable) {
                Text("Landside (taxable)").tag(true)
                Text("Airside (non-taxable)").tag(false)
            }
            if let sa = vm.config?.schedulerSaEmail, !sa.isEmpty {
                LabeledContent("Service account", value: sa)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } header: {
            Text("Scheduled push")
        } footer: {
            Text("Defaults are read by the Cloud-Scheduler-triggered push and the Run scheduled push now button. The cron is informational — the live schedule is in Google Cloud Scheduler.")
        }
    }

    private func testResultSection(_ res: CagSftpTestResponse) -> some View {
        Section("Connection test result") {
            Label(res.message, systemImage: res.ok ? "checkmark.circle" : "xmark.octagon")
                .foregroundStyle(res.ok ? .green : .red)
                .font(.caption)
            if let w = res.workingDir { LabeledContent("working", value: w).font(.caption) }
            if let e = res.errorDir { LabeledContent("error", value: e).font(.caption) }
            if let a = res.archiveDir { LabeledContent("archive", value: a).font(.caption) }
        }
    }

    private func pushResultSection(_ res: CagPushResponse) -> some View {
        Section("On-demand push result") {
            Text("\(res.filesUploaded.count) file(s), \(res.bytesUploaded) bytes — started \(res.startedAt)")
                .font(.caption)
            if !res.filesUploaded.isEmpty {
                ForEach(res.filesUploaded.prefix(8), id: \.self) { f in
                    Text(f).font(.caption2).foregroundStyle(.secondary)
                }
            }
            if !res.errors.isEmpty {
                Text(res.errors.joined(separator: "; "))
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
    }

    private var actionsSection: some View {
        Section {
            Button {
                Task { await vm.save() }
            } label: {
                if vm.isSaving { ProgressView() } else { Label("Save settings", systemImage: "square.and.arrow.down") }
            }
            .disabled(vm.isSaving)

            Button {
                Task { await vm.test() }
            } label: {
                if vm.isTesting { ProgressView() } else { Label("Test SFTP connection", systemImage: "network") }
            }
            .disabled(vm.isTesting)

            Button {
                confirmRunPush = true
            } label: {
                if vm.isRunningPush { ProgressView() } else { Label("Run scheduled push now", systemImage: "paperplane") }
            }
            .disabled(vm.isRunningPush || !vm.canRunScheduledPush)

            Button(role: .destructive) {
                confirmClear = true
            } label: {
                if vm.isClearing { ProgressView() } else { Label("Clear saved values", systemImage: "trash") }
            }
            .disabled(vm.isClearing)
        }
    }

    // MARK: - Helpers

    private func lastRunBanner(_ cfg: CagConfigPublic) -> some View {
        let ok = cfg.schedulerLastRunStatus.lowercased() == "success"
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .foregroundStyle(ok ? .green : .red)
                Text("Last run · \(cfg.schedulerLastRunStatus.isEmpty ? "unknown" : cfg.schedulerLastRunStatus)\(cfg.schedulerLastRunTrigger.isEmpty ? "" : " (\(cfg.schedulerLastRunTrigger))")")
                    .font(.caption.bold())
            }
            Text("\(cfg.schedulerLastRunAt) — \(cfg.schedulerLastRunFiles) file(s), \(cfg.schedulerLastRunBytes) bytes")
                .font(.caption2)
                .foregroundStyle(.secondary)
            if !cfg.schedulerLastRunMessage.isEmpty {
                Text(cfg.schedulerLastRunMessage)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
        }
    }

    private func bannerIcon(_ kind: CagSettingsViewModel.BannerKind) -> String {
        switch kind {
        case .ok: return "checkmark.circle"
        case .info: return "info.circle"
        case .err: return "exclamationmark.octagon"
        }
    }

    private func bannerTint(_ kind: CagSettingsViewModel.BannerKind) -> Color {
        switch kind {
        case .ok: return .green
        case .info: return .blue
        case .err: return .red
        }
    }
}

#Preview {
    NavigationStack { CagSettingsView() }
}

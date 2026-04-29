//
//  CagSettingsViewModel.swift
//  retailmanagement
//
//  System-admin-only form state for the NEC CAG integration. Mirrors the
//  staff-portal CagSettingsPage logic: load → edit → PUT, with on-demand
//  SFTP test and scheduled-push trigger that refresh telemetry on success.
//

import Foundation
import Observation

@MainActor
@Observable
final class CagSettingsViewModel {
    // Server snapshot (last loaded from GET /cag/config).
    var config: CagConfigPublic?

    // Form fields — string-based for binding to TextFields.
    var host = ""
    var port = "22"
    var username = ""
    var password = ""
    var keyPath = ""
    var keyPassphrase = ""
    var tenantFolder = ""
    var inboundWorking = "Inbound/Working"
    var inboundError = "Inbound/Error"
    var inboundArchive = "Inbound/Archive"
    var defaultNecStoreId = ""
    var defaultTaxable = true
    var schedulerEnabled = true
    var schedulerCron = "0 */3 * * *"
    var schedulerDefaultTenant = ""
    var schedulerDefaultStoreId = ""
    var schedulerDefaultTaxable = false

    // Status flags.
    var isLoading = true
    var isSaving = false
    var isTesting = false
    var isClearing = false
    var isRunningPush = false

    // Toast/banner state.
    enum BannerKind { case ok, info, err }
    struct Banner { let kind: BannerKind; let text: String }
    var banner: Banner?

    // Transient panels.
    var testResult: CagSftpTestResponse?
    var pushResult: CagPushResponse?

    // Derived helpers used by the view.
    var effectiveTenant: String {
        let s = schedulerDefaultTenant.trimmingCharacters(in: .whitespaces)
        return s.isEmpty ? tenantFolder.trimmingCharacters(in: .whitespaces) : s
    }
    var effectiveStoreId: String {
        let s = schedulerDefaultStoreId.trimmingCharacters(in: .whitespaces)
        return s.isEmpty ? defaultNecStoreId.trimmingCharacters(in: .whitespaces) : s
    }
    var effectiveStoreIdValid: Bool {
        let v = effectiveStoreId
        guard v.count == 5 else { return false }
        return v.allSatisfy { $0.isNumber }
    }
    var canRunScheduledPush: Bool {
        (config?.isConfigured ?? false)
            && !effectiveTenant.isEmpty
            && effectiveStoreIdValid
    }

    // MARK: - Loading & mutations

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let cfg = try await CagConfigService.get()
            apply(cfg)
            banner = nil
        } catch {
            banner = .init(kind: .err, text: error.localizedDescription)
        }
    }

    func save() async {
        isSaving = true
        banner = nil
        defer { isSaving = false }
        do {
            let patch = CagConfigPatch(
                host: host.trimmingCharacters(in: .whitespaces),
                port: Int(port) ?? 22,
                username: username.trimmingCharacters(in: .whitespaces),
                password: password.isEmpty ? nil : password,
                keyPath: keyPath.trimmingCharacters(in: .whitespaces),
                keyPassphrase: keyPassphrase.isEmpty ? nil : keyPassphrase,
                tenantFolder: tenantFolder.trimmingCharacters(in: .whitespaces),
                inboundWorking: trimmedOrDefault(inboundWorking, "Inbound/Working"),
                inboundError: trimmedOrDefault(inboundError, "Inbound/Error"),
                inboundArchive: trimmedOrDefault(inboundArchive, "Inbound/Archive"),
                defaultNecStoreId: defaultNecStoreId.trimmingCharacters(in: .whitespaces),
                defaultTaxable: defaultTaxable,
                schedulerEnabled: schedulerEnabled,
                schedulerCron: trimmedOrDefault(schedulerCron, "0 */3 * * *"),
                schedulerDefaultTenant: schedulerDefaultTenant.trimmingCharacters(in: .whitespaces),
                schedulerDefaultStoreId: schedulerDefaultStoreId.trimmingCharacters(in: .whitespaces),
                schedulerDefaultTaxable: schedulerDefaultTaxable
            )
            let updated = try await CagConfigService.put(patch)
            apply(updated)
            banner = .init(kind: .ok, text: "Settings saved.")
        } catch {
            banner = .init(kind: .err, text: error.localizedDescription)
        }
    }

    func test() async {
        isTesting = true
        testResult = nil
        banner = nil
        defer { isTesting = false }
        do {
            let res = try await CagConfigService.test()
            testResult = res
            banner = .init(kind: res.ok ? .ok : .err,
                           text: res.ok ? "SFTP connection OK." : "SFTP test failed: \(res.message)")
        } catch {
            banner = .init(kind: .err, text: error.localizedDescription)
        }
    }

    func clear() async {
        isClearing = true
        defer { isClearing = false }
        do {
            let updated = try await CagConfigService.clear()
            apply(updated)
            banner = .init(kind: .info, text: "Cleared. Falling back to .env defaults (if any).")
        } catch {
            banner = .init(kind: .err, text: error.localizedDescription)
        }
    }


    func runScheduledPush() async {
        isRunningPush = true
        pushResult = nil
        banner = nil
        defer { isRunningPush = false }
        do {
            let res = try await CagConfigService.runScheduledPush()
            pushResult = res
            let ok = res.errors.isEmpty
            banner = .init(
                kind: ok ? .ok : .err,
                text: ok
                    ? "Push OK — \(res.filesUploaded.count) file(s), \(res.bytesUploaded) bytes."
                    : "Push completed with errors: \(res.errors.joined(separator: "; "))"
            )
            // Refresh telemetry (last_run_*) without resetting transient panels.
            if let cfg = try? await CagConfigService.get() {
                config = cfg
            }
        } catch {
            banner = .init(kind: .err, text: error.localizedDescription)
        }
    }

    // MARK: - Helpers

    private func apply(_ cfg: CagConfigPublic) {
        config = cfg
        host = cfg.host
        port = String(cfg.port == 0 ? 22 : cfg.port)
        username = cfg.username
        password = ""
        keyPath = cfg.keyPath
        keyPassphrase = ""
        tenantFolder = cfg.tenantFolder
        inboundWorking = cfg.inboundWorking
        inboundError = cfg.inboundError
        inboundArchive = cfg.inboundArchive
        defaultNecStoreId = cfg.defaultNecStoreId
        defaultTaxable = cfg.defaultTaxable
        schedulerEnabled = cfg.schedulerEnabled
        schedulerCron = cfg.schedulerCron.isEmpty ? "0 */3 * * *" : cfg.schedulerCron
        schedulerDefaultTenant = cfg.schedulerDefaultTenant
        schedulerDefaultStoreId = cfg.schedulerDefaultStoreId
        schedulerDefaultTaxable = cfg.schedulerDefaultTaxable
    }

    private func trimmedOrDefault(_ value: String, _ fallback: String) -> String {
        let s = value.trimmingCharacters(in: .whitespaces)
        return s.isEmpty ? fallback : s
    }
}

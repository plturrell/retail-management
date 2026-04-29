//
//  CagConfig.swift
//  retailmanagement
//
//  Mirrors the backend `CagConfigPublic` payload used by both the read-only
//  NecStatusCard and the system-admin-only CagSettingsView. All fields
//  default to empty / 0 / false so older backend responses still decode
//  cleanly.
//

import Foundation

struct CagConfigPublic: Decodable, Sendable {
    let host: String
    let port: Int
    let username: String
    let keyPath: String
    let tenantFolder: String
    let inboundWorking: String
    let inboundError: String
    let inboundArchive: String
    let defaultNecStoreId: String
    let defaultTaxable: Bool
    let schedulerEnabled: Bool
    let schedulerCron: String
    let schedulerDefaultTenant: String
    let schedulerDefaultStoreId: String
    let schedulerDefaultTaxable: Bool
    let schedulerLastRunAt: String
    let schedulerLastRunStatus: String
    let schedulerLastRunMessage: String
    let schedulerLastRunFiles: Int
    let schedulerLastRunBytes: Int
    let schedulerLastRunTrigger: String
    let schedulerSaEmail: String
    let schedulerAudience: String
    let hasPassword: Bool
    let hasKeyPassphrase: Bool
    let isConfigured: Bool
    let updatedAt: String
    let updatedBy: String

    enum CodingKeys: String, CodingKey {
        case host, port, username
        case keyPath = "key_path"
        case tenantFolder = "tenant_folder"
        case inboundWorking = "inbound_working"
        case inboundError = "inbound_error"
        case inboundArchive = "inbound_archive"
        case defaultNecStoreId = "default_nec_store_id"
        case defaultTaxable = "default_taxable"
        case schedulerEnabled = "scheduler_enabled"
        case schedulerCron = "scheduler_cron"
        case schedulerDefaultTenant = "scheduler_default_tenant"
        case schedulerDefaultStoreId = "scheduler_default_store_id"
        case schedulerDefaultTaxable = "scheduler_default_taxable"
        case schedulerLastRunAt = "scheduler_last_run_at"
        case schedulerLastRunStatus = "scheduler_last_run_status"
        case schedulerLastRunMessage = "scheduler_last_run_message"
        case schedulerLastRunFiles = "scheduler_last_run_files"
        case schedulerLastRunBytes = "scheduler_last_run_bytes"
        case schedulerLastRunTrigger = "scheduler_last_run_trigger"
        case schedulerSaEmail = "scheduler_sa_email"
        case schedulerAudience = "scheduler_audience"
        case hasPassword = "has_password"
        case hasKeyPassphrase = "has_key_passphrase"
        case isConfigured = "is_configured"
        case updatedAt = "updated_at"
        case updatedBy = "updated_by"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        host = try c.decodeIfPresent(String.self, forKey: .host) ?? ""
        port = try c.decodeIfPresent(Int.self, forKey: .port) ?? 22
        username = try c.decodeIfPresent(String.self, forKey: .username) ?? ""
        keyPath = try c.decodeIfPresent(String.self, forKey: .keyPath) ?? ""
        tenantFolder = try c.decodeIfPresent(String.self, forKey: .tenantFolder) ?? ""
        inboundWorking = try c.decodeIfPresent(String.self, forKey: .inboundWorking) ?? "Inbound/Working"
        inboundError = try c.decodeIfPresent(String.self, forKey: .inboundError) ?? "Inbound/Error"
        inboundArchive = try c.decodeIfPresent(String.self, forKey: .inboundArchive) ?? "Inbound/Archive"
        defaultNecStoreId = try c.decodeIfPresent(String.self, forKey: .defaultNecStoreId) ?? ""
        defaultTaxable = try c.decodeIfPresent(Bool.self, forKey: .defaultTaxable) ?? true
        schedulerEnabled = try c.decodeIfPresent(Bool.self, forKey: .schedulerEnabled) ?? false
        schedulerCron = try c.decodeIfPresent(String.self, forKey: .schedulerCron) ?? ""
        schedulerDefaultTenant = try c.decodeIfPresent(String.self, forKey: .schedulerDefaultTenant) ?? ""
        schedulerDefaultStoreId = try c.decodeIfPresent(String.self, forKey: .schedulerDefaultStoreId) ?? ""
        schedulerDefaultTaxable = try c.decodeIfPresent(Bool.self, forKey: .schedulerDefaultTaxable) ?? false
        schedulerLastRunAt = try c.decodeIfPresent(String.self, forKey: .schedulerLastRunAt) ?? ""
        schedulerLastRunStatus = try c.decodeIfPresent(String.self, forKey: .schedulerLastRunStatus) ?? ""
        schedulerLastRunMessage = try c.decodeIfPresent(String.self, forKey: .schedulerLastRunMessage) ?? ""
        schedulerLastRunFiles = try c.decodeIfPresent(Int.self, forKey: .schedulerLastRunFiles) ?? 0
        schedulerLastRunBytes = try c.decodeIfPresent(Int.self, forKey: .schedulerLastRunBytes) ?? 0
        schedulerLastRunTrigger = try c.decodeIfPresent(String.self, forKey: .schedulerLastRunTrigger) ?? ""
        schedulerSaEmail = try c.decodeIfPresent(String.self, forKey: .schedulerSaEmail) ?? ""
        schedulerAudience = try c.decodeIfPresent(String.self, forKey: .schedulerAudience) ?? ""
        hasPassword = try c.decodeIfPresent(Bool.self, forKey: .hasPassword) ?? false
        hasKeyPassphrase = try c.decodeIfPresent(Bool.self, forKey: .hasKeyPassphrase) ?? false
        isConfigured = try c.decodeIfPresent(Bool.self, forKey: .isConfigured) ?? false
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt) ?? ""
        updatedBy = try c.decodeIfPresent(String.self, forKey: .updatedBy) ?? ""
    }
}

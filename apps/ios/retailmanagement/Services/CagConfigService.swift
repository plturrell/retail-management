//
//  CagConfigService.swift
//  retailmanagement
//
//  Owner-only client for the NEC CAG integration settings: SFTP credentials,
//  tenant identifiers, scheduler defaults, on-demand test push. Mirrors the
//  staff-portal CagSettingsPage but limited to fields the mobile form
//  surfaces (per-store mappings + error log panel remain web-only).
//

import Foundation

struct CagSftpTestResponse: Decodable, Sendable {
    let ok: Bool
    let message: String
    let workingDir: String?
    let errorDir: String?
    let archiveDir: String?

    enum CodingKeys: String, CodingKey {
        case ok, message
        case workingDir = "working_dir"
        case errorDir = "error_dir"
        case archiveDir = "archive_dir"
    }
}

struct CagPushResponse: Decodable, Sendable {
    let filesUploaded: [String]
    let bytesUploaded: Int
    let counts: [String: Int]
    let startedAt: String
    let finishedAt: String?
    let errors: [String]

    enum CodingKeys: String, CodingKey {
        case filesUploaded = "files_uploaded"
        case bytesUploaded = "bytes_uploaded"
        case counts
        case startedAt = "started_at"
        case finishedAt = "finished_at"
        case errors
    }
}

/// Patch sent to PUT /api/cag/config. Optional secret fields are only
/// included when the user typed something — empty string keeps existing.
struct CagConfigPatch: Encodable, Sendable {
    let host: String
    let port: Int
    let username: String
    let password: String?
    let keyPath: String
    let keyPassphrase: String?
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

    enum CodingKeys: String, CodingKey {
        case host, port, username, password
        case keyPath = "key_path"
        case keyPassphrase = "key_passphrase"
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
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(host, forKey: .host)
        try c.encode(port, forKey: .port)
        try c.encode(username, forKey: .username)
        if let pw = password, !pw.isEmpty { try c.encode(pw, forKey: .password) }
        try c.encode(keyPath, forKey: .keyPath)
        if let kp = keyPassphrase, !kp.isEmpty { try c.encode(kp, forKey: .keyPassphrase) }
        try c.encode(tenantFolder, forKey: .tenantFolder)
        try c.encode(inboundWorking, forKey: .inboundWorking)
        try c.encode(inboundError, forKey: .inboundError)
        try c.encode(inboundArchive, forKey: .inboundArchive)
        try c.encode(defaultNecStoreId, forKey: .defaultNecStoreId)
        try c.encode(defaultTaxable, forKey: .defaultTaxable)
        try c.encode(schedulerEnabled, forKey: .schedulerEnabled)
        try c.encode(schedulerCron, forKey: .schedulerCron)
        try c.encode(schedulerDefaultTenant, forKey: .schedulerDefaultTenant)
        try c.encode(schedulerDefaultStoreId, forKey: .schedulerDefaultStoreId)
        try c.encode(schedulerDefaultTaxable, forKey: .schedulerDefaultTaxable)
    }
}

struct CagScheduledPushRequest: Encodable, Sendable {
    let tenantCode: String?
    let necStoreId: String?
    let taxable: Bool?

    enum CodingKeys: String, CodingKey {
        case tenantCode = "tenant_code"
        case necStoreId = "nec_store_id"
        case taxable
    }
}

enum CagConfigService {
    static func get() async throws -> CagConfigPublic {
        try await NetworkService.shared.get(endpoint: "/api/cag/config")
    }

    static func put(_ patch: CagConfigPatch) async throws -> CagConfigPublic {
        try await NetworkService.shared.put(endpoint: "/api/cag/config", body: patch)
    }

    static func clear() async throws -> CagConfigPublic {
        try await NetworkService.shared.delete(endpoint: "/api/cag/config")
    }

    static func test() async throws -> CagSftpTestResponse {
        try await NetworkService.shared.post(
            endpoint: "/api/cag/config/test",
            body: [String: String]()
        )
    }

    static func runScheduledPush(_ body: CagScheduledPushRequest = .init(tenantCode: nil, necStoreId: nil, taxable: nil)) async throws -> CagPushResponse {
        try await NetworkService.shared.post(endpoint: "/api/cag/export/push/test", body: body)
    }
}

//
//  Session.swift
//  retailmanagement
//
//  Mirrors the backend `SessionRead` payload returned by
//  GET /api/users/me/sessions. Each row represents a (user, device,
//  approximate-network) tuple aggregated from auth_events.
//

import Foundation

nonisolated struct SessionRead: Codable, Identifiable, Sendable {
    let fingerprint: String
    let ip: String?
    let userAgent: String?
    let firstSeen: String?
    let lastSeen: String?
    let count: Int

    var id: String { fingerprint }

    enum CodingKeys: String, CodingKey {
        case fingerprint, ip, count
        case userAgent = "user_agent"
        case firstSeen = "first_seen"
        case lastSeen = "last_seen"
    }
}

nonisolated struct SignOutResponse: Decodable, Sendable {
    let message: String?
}

nonisolated struct EmptyBody: Encodable, Sendable {}

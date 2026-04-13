//
//  User.swift
//  retailmanagement
//

import Foundation

nonisolated enum UserRole: String, Codable, CaseIterable, Sendable {
    case owner, manager, staff

    var displayName: String { rawValue.capitalized }

    /// Role hierarchy: owner > manager > staff
    var level: Int {
        switch self {
        case .owner: return 3
        case .manager: return 2
        case .staff: return 1
        }
    }
}

nonisolated struct AppUser: Codable, Identifiable, Sendable {
    let id: String
    let firebaseUid: String
    let email: String
    let fullName: String
    let phone: String?
    let storeRoles: [UserStoreRole]

    /// Returns the role for a given store, if any.
    func role(for storeId: String) -> UserRole? {
        storeRoles.first { $0.storeId == storeId }?.role
    }

    /// Returns the highest role across all stores.
    var highestRole: UserRole? {
        storeRoles.map(\.role).max { $0.level < $1.level }
    }
}

nonisolated struct UserStoreRole: Codable, Identifiable, Sendable {
    let id: String
    let userId: String?
    let storeId: String
    let role: UserRole
    let createdAt: String?

    init(id: String, userId: String? = nil, storeId: String, role: UserRole, createdAt: String? = nil) {
        self.id = id
        self.userId = userId
        self.storeId = storeId
        self.role = role
        self.createdAt = createdAt
    }
}

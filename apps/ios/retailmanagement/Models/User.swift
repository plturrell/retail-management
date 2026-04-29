//
//  User.swift
//  retailmanagement
//

import Foundation

nonisolated enum UserRole: String, Codable, CaseIterable, Sendable {
    case systemAdmin = "system_admin"
    case owner, manager, staff

    var displayName: String {
        switch self {
        case .systemAdmin: return "System Admin"
        case .owner: return "Owner Director"
        case .manager: return "Store Manager"
        case .staff: return "Sales Promoter"
        }
    }

    /// Role hierarchy: systemAdmin > owner > manager > staff
    var level: Int {
        switch self {
        case .systemAdmin: return 4
        case .owner: return 3
        case .manager: return 2
        case .staff: return 1
        }
    }

    /// True iff this role outranks-or-equals ``owner``. Used in place of
    /// `role == .owner` so ``systemAdmin`` (the global tier above owner)
    /// inherits owner-gated surfaces — Master Data, Vendor Review, etc.
    var isOwnerOrAbove: Bool { level >= UserRole.owner.level }
}

nonisolated struct AppUser: Codable, Identifiable, Sendable {
    let id: String
    let firebaseUid: String
    let email: String
    let fullName: String
    let phone: String?
    let storeRoles: [UserStoreRole]

    var username: String {
        AuthService.username(fromEmail: email)
    }

    /// Returns the role for a given store, if any.
    func role(for storeId: String) -> UserRole? {
        storeRoles.first { $0.storeId == storeId }?.role
    }

    /// Returns the highest role across all stores.
    var highestRole: UserRole? {
        storeRoles.map(\.role).max { $0.level < $1.level }
    }

    /// True iff the user holds ``system_admin`` on any store. System admins
    /// bypass per-store membership checks server-side; the iOS surface mirrors
    /// that by gating admin-only screens (NEC CAG settings) on this flag.
    var isSystemAdmin: Bool {
        storeRoles.contains { $0.role == .systemAdmin }
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

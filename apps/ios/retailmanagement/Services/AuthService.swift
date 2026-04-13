//
//  AuthService.swift
//  retailmanagement
//

import FirebaseAuth
import FirebaseCore
import Foundation

/// Wraps Firebase Authentication using the Firebase Auth SDK.
final class AuthService: @unchecked Sendable {
    static let shared = AuthService()

    private init() {}

    /// Whether Firebase has been configured (GoogleService-Info.plist was found).
    var isFirebaseConfigured: Bool {
        FirebaseApp.app() != nil
    }

    var hasCurrentUser: Bool {
        guard isFirebaseConfigured else { return false }
        return Auth.auth().currentUser != nil
    }

    var currentUserEmail: String? {
        Auth.auth().currentUser?.email
    }

    var currentUserDisplayName: String? {
        Auth.auth().currentUser?.displayName
    }

    // MARK: - Auth Methods

    /// Sign in with email and password.
    @discardableResult
    func signIn(email: String, password: String) async throws -> FirebaseAuth.User {
        let result = try await Auth.auth().signIn(withEmail: email, password: password)
        return result.user
    }

    /// Register a new account.
    @discardableResult
    func register(email: String, password: String, fullName: String) async throws -> FirebaseAuth.User {
        let result = try await Auth.auth().createUser(withEmail: email, password: password)
        let changeRequest = result.user.createProfileChangeRequest()
        changeRequest.displayName = fullName
        try await changeRequest.commitChanges()
        return result.user
    }

    /// Sign out.
    func signOut() {
        try? Auth.auth().signOut()
    }

    /// Get the current user's ID token for API authentication.
    func getIdToken() async throws -> String? {
        return try await Auth.auth().currentUser?.getIDToken()
    }
}

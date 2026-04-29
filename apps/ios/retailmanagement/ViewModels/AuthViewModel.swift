//
//  AuthViewModel.swift
//  retailmanagement
//

import FirebaseAuth
import Foundation
import Observation
import SwiftUI

@MainActor
@Observable
final class AuthViewModel {
    var authState: AuthState = .loading
    var currentUser: AppUser?
    var errorMessage: String?
    var isLoading = false
    /// True when the Firebase token carries ``must_change_password=true``.
    /// Mirrors the staff-portal web behaviour: every gated screen redirects to
    /// ``ForceChangePasswordView`` until the user rotates their password and
    /// the backend clears the claim.
    var mustChangePassword: Bool = false

    private let authService = AuthService.shared

    init() {
        Task {
            await checkCurrentUser()
        }
    }

    /// Check if a user session already exists on launch.
    func checkCurrentUser() async {
        authState = .loading

        let hasExistingSession = authService.hasCurrentUser

        if hasExistingSession {
            do {
                mustChangePassword = await readForceChangeClaim(forceRefresh: true)
                let user = try await fetchUserProfile()
                currentUser = user
                authState = .authenticated
            } catch {
                authState = .unauthenticated
            }
        } else {
            mustChangePassword = false
            authState = .unauthenticated
        }
    }

    /// Sign in with username and password.
    func signIn(username: String, password: String) async {
        guard !username.isEmpty, !password.isEmpty else {
            errorMessage = "Username and password are required."
            return
        }

        isLoading = true
        errorMessage = nil

        do {
            try await authService.signIn(username: username, password: password)
            mustChangePassword = await readForceChangeClaim(forceRefresh: true)
            let user = try await fetchUserProfile()
            currentUser = user
            authState = .authenticated
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    /// Re-read the Firebase custom claims and update ``mustChangePassword``.
    /// Call this after the user successfully rotates their password so the
    /// gate releases without requiring a sign-out/sign-in cycle.
    func refreshTokenClaims() async {
        mustChangePassword = await readForceChangeClaim(forceRefresh: true)
    }

    private func readForceChangeClaim(forceRefresh: Bool) async -> Bool {
        do {
            let claims = try await authService.customClaims(forceRefresh: forceRefresh)
            return (claims["must_change_password"] as? Bool) == true
        } catch {
            return false
        }
    }

    /// Register a new account.
    func register(email: String, password: String, fullName: String) async {
        guard !email.isEmpty, !password.isEmpty, !fullName.isEmpty else {
            errorMessage = "All fields are required."
            return
        }

        isLoading = true
        errorMessage = nil

        do {
            let fbUser = try await authService.register(email: email, password: password, fullName: fullName)
            // Create the user record on the backend
            let body = CreateUserBody(
                firebaseUid: fbUser.uid,
                email: email,
                fullName: fullName,
                phone: nil
            )
            let _: DataResponse<AppUser> = try await NetworkService.shared.post(
                endpoint: "/api/users",
                body: body
            )
            let user = try await fetchUserProfile()
            currentUser = user
            authState = .authenticated
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    /// Refresh the user profile from the backend.
    func refreshProfile() async {
        do {
            let user = try await fetchUserProfile()
            currentUser = user
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Sign out the current user.
    func signOut() {
        authService.signOut()
        currentUser = nil
        mustChangePassword = false
        authState = .unauthenticated
    }

    // MARK: - Private

    /// Fetch the user profile from the backend API.
    private func fetchUserProfile() async throws -> AppUser {
        let response: DataResponse<AppUser> = try await NetworkService.shared.get(
            endpoint: "/api/users/me"
        )
        return response.data
    }
}

// MARK: - Request Bodies

private struct CreateUserBody: Encodable {
    let firebaseUid: String
    let email: String
    let fullName: String
    let phone: String?
}

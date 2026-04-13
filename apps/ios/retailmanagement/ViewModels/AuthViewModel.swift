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
                let user = try await fetchUserProfile()
                currentUser = user
                authState = .authenticated
            } catch {
                authState = .unauthenticated
            }
        } else {
            authState = .unauthenticated
        }
    }

    /// Sign in with email and password.
    func signIn(email: String, password: String) async {
        guard !email.isEmpty, !password.isEmpty else {
            errorMessage = "Email and password are required."
            return
        }

        isLoading = true
        errorMessage = nil

        do {
            try await authService.signIn(email: email, password: password)
            let user = try await fetchUserProfile()
            currentUser = user
            authState = .authenticated
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
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

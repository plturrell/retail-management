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
    var infoMessage: String?
    var isLoading = false
    var isResettingPassword = false
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
        infoMessage = nil
        let email = AuthService.authEmail(forUsername: username)

        do {
            try await authService.signIn(username: username, password: password)
            await reportSuccessfulLogin(email: email)
            mustChangePassword = await readForceChangeClaim(forceRefresh: true)
            let user = try await fetchUserProfile()
            currentUser = user
            authState = .authenticated
        } catch {
            let report = await reportFailedLogin(email: email)
            errorMessage = loginErrorMessage(error, report: report)
        }

        isLoading = false
    }

    func resetPassword(username: String) async {
        let email = AuthService.authEmail(forUsername: username)
        guard !email.isEmpty else {
            errorMessage = "Enter your username above first, then tap Forgot password."
            infoMessage = nil
            return
        }

        isResettingPassword = true
        errorMessage = nil
        infoMessage = nil

        do {
            try await authService.sendPasswordReset(username: username)
            infoMessage = "If that username has an account, a reset link has been sent. Check your inbox and spam."
        } catch {
            if error.localizedDescription.lowercased().contains("invalid") {
                errorMessage = "That doesn't look like a valid username."
            } else {
                errorMessage = "Could not send reset email. Try again in a minute."
            }
        }

        isResettingPassword = false
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

    private func reportFailedLogin(email: String) async -> LockoutReport? {
        guard !email.isEmpty else { return nil }
        return try? await NetworkService.shared.post(
            endpoint: "/api/auth/report-failed-login",
            body: AuthReport(email: email)
        )
    }

    private func reportSuccessfulLogin(email: String) async {
        guard !email.isEmpty else { return }
        let _: AuthSuccessReport? = try? await NetworkService.shared.post(
            endpoint: "/api/auth/report-successful-login",
            body: AuthReport(email: email)
        )
    }

    private func loginErrorMessage(_ error: Error, report: LockoutReport?) -> String {
        if report?.locked == true {
            return "This account has been locked after too many failed sign-ins. Ask an owner or manager to re-enable it, or use Forgot password to reset."
        }
        if let report, report.remaining > 0, report.remaining <= 2 {
            let plural = report.remaining == 1 ? "" : "s"
            return "Incorrect username or password. \(report.remaining) attempt\(plural) left before this account is temporarily locked."
        }

        let message = error.localizedDescription.lowercased()
        if message.contains("disabled") {
            return "This account is disabled. Contact an owner to re-enable it."
        }
        if message.contains("too many") {
            return "Too many sign-in attempts from this device. Wait a few minutes and try again."
        }
        if message.contains("password") || message.contains("credential") || message.contains("user") {
            return "Incorrect username or password."
        }
        return error.localizedDescription
    }
}

// MARK: - Request Bodies

private struct AuthReport: Encodable {
    let email: String
}

private struct LockoutReport: Decodable {
    let locked: Bool
    let remaining: Int
    let threshold: Int
    let windowMinutes: Int
}

private struct AuthSuccessReport: Decodable {
    let ok: Bool
}

private struct CreateUserBody: Encodable {
    let firebaseUid: String
    let email: String
    let fullName: String
    let phone: String?
}

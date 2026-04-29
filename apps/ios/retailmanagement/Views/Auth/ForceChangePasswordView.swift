//
//  ForceChangePasswordView.swift
//  retailmanagement
//
//  Renders when the signed-in user carries the Firebase custom claim
//  `must_change_password=true` (set by the backend `admin_reset_password`
//  endpoint when a manager/owner resets another user's password). Mirrors the
//  staff-portal web `ForceChangePasswordPage` — no navigation, no way to
//  bypass. The user must rotate their password before the main tab view
//  becomes reachable again.
//

import SwiftUI

struct ForceChangePasswordView: View {
    @Environment(AuthViewModel.self) private var authViewModel

    @State private var current: String = ""
    @State private var next: String = ""
    @State private var confirm: String = ""
    @State private var isSubmitting = false
    @State private var errorMessage: String?

    var body: some View {
        AuthLayout {
            VStack(spacing: 24) {
                VStack(spacing: 8) {
                    Image(systemName: "lock.shield")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 48, height: 48)
                        .foregroundStyle(.tint)
                    Text("Update your password")
                        .font(.title2.bold())
                    Text("An administrator reset your password. Choose a new one to continue.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                VStack(spacing: 12) {
                    SecureField("Current password", text: $current)
                        .textContentType(.password)
                        .textFieldStyle(.roundedBorder)
                    SecureField("New password (≥10 characters)", text: $next)
                        .textContentType(.newPassword)
                        .textFieldStyle(.roundedBorder)
                    SecureField("Confirm new password", text: $confirm)
                        .textContentType(.newPassword)
                        .textFieldStyle(.roundedBorder)
                }

                if let errorMessage {
                    Text(errorMessage)
                        .font(.callout)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                }

                Button {
                    Task { await submit() }
                } label: {
                    if isSubmitting {
                        ProgressView().controlSize(.regular)
                    } else {
                        Text("Update password").frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isSubmitting || current.isEmpty || next.isEmpty || confirm.isEmpty)

                Button("Sign out") {
                    authViewModel.signOut()
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
            }
            .frame(maxWidth: 420)
            .padding(.horizontal)
        }
    }

    private func submit() async {
        errorMessage = nil
        guard next.count >= 10 else {
            errorMessage = "New password must be at least 10 characters."
            return
        }
        guard next == confirm else {
            errorMessage = "New password and confirmation do not match."
            return
        }

        isSubmitting = true
        defer { isSubmitting = false }

        do {
            try await AuthService.shared.reauthenticate(currentPassword: current)
            let _: ChangePasswordResponse = try await NetworkService.shared.post(
                endpoint: "/api/users/me/change-password",
                body: ChangePasswordRequest(newPassword: next)
            )
            await authViewModel.refreshTokenClaims()
        } catch {
            errorMessage = friendlyMessage(for: error)
        }
    }

    private func friendlyMessage(for error: Error) -> String {
        let raw = error.localizedDescription
        if raw.contains("wrong-password") || raw.contains("invalid-credential") {
            return "Current password is incorrect."
        }
        if raw.contains("too-many-requests") {
            return "Too many attempts — wait a few minutes and try again."
        }
        return raw
    }
}

private struct ChangePasswordRequest: Encodable {
    let newPassword: String
}

private struct ChangePasswordResponse: Decodable {
    let message: String?
}

#Preview {
    ForceChangePasswordView()
        .environment(AuthViewModel())
}

//
//  RegisterView.swift
//  retailmanagement
//

import SwiftUI

struct RegisterView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var fullName = ""
    @State private var username = ""
    @State private var password = ""
    @State private var confirmPassword = ""
    @State private var localError: String?

    // MARK: - Fluid Focus States
    enum Field {
        case fullName, username, password, confirmPassword
    }
    @FocusState private var focusedField: Field?

    var body: some View {
        NavigationStack {
            AuthLayout {
                VStack(spacing: 32) {
                    VStack(spacing: 8) {
                        Image(systemName: "person.badge.plus")
                            .font(.system(size: 40))
                            .foregroundStyle(Color.primary)
                        Text("Create Account")
                            .font(.system(size: 24, weight: .bold, design: .serif))
                    }

                    VStack(spacing: 16) {
                        TextField("Full Name", text: $fullName)
                            .focused($focusedField, equals: .fullName)
                            .textContentType(.name)
                            .autocorrectionDisabled()
                            .padding()
                            .background(Color.systemBackground.opacity(0.5))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(focusedField == .fullName ? Color.blue : Color.primary.opacity(0.1), lineWidth: focusedField == .fullName ? 2 : 1))
                            .shadow(color: focusedField == .fullName ? Color.blue.opacity(0.2) : .clear, radius: 8, x: 0, y: 4)
                            .animation(.easeOut(duration: 0.2), value: focusedField)

                        TextField("Username", text: $username)
                            .focused($focusedField, equals: .username)
                            .textContentType(.username)
                            #if canImport(UIKit)
                            .keyboardType(.asciiCapable)
                            .textInputAutocapitalization(.never)
                            #endif
                            .autocorrectionDisabled()
                            .padding()
                            .background(Color.systemBackground.opacity(0.5))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(focusedField == .username ? Color.blue : Color.primary.opacity(0.1), lineWidth: focusedField == .username ? 2 : 1))
                            .shadow(color: focusedField == .username ? Color.blue.opacity(0.2) : .clear, radius: 8, x: 0, y: 4)
                            .animation(.easeOut(duration: 0.2), value: focusedField)

                        SecureField("Password", text: $password)
                            .focused($focusedField, equals: .password)
                            .textContentType(.newPassword)
                            .padding()
                            .background(Color.systemBackground.opacity(0.5))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(focusedField == .password ? Color.blue : Color.primary.opacity(0.1), lineWidth: focusedField == .password ? 2 : 1))
                            .shadow(color: focusedField == .password ? Color.blue.opacity(0.2) : .clear, radius: 8, x: 0, y: 4)
                            .animation(.easeOut(duration: 0.2), value: focusedField)

                        SecureField("Confirm Password", text: $confirmPassword)
                            .focused($focusedField, equals: .confirmPassword)
                            .textContentType(.newPassword)
                            .padding()
                            .background(Color.systemBackground.opacity(0.5))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(focusedField == .confirmPassword ? Color.blue : Color.primary.opacity(0.1), lineWidth: focusedField == .confirmPassword ? 2 : 1))
                            .shadow(color: focusedField == .confirmPassword ? Color.blue.opacity(0.2) : .clear, radius: 8, x: 0, y: 4)
                            .animation(.easeOut(duration: 0.2), value: focusedField)
                    }

                    if let error = localError ?? authViewModel.errorMessage {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .multilineTextAlignment(.center)
                            .padding(.top, -8)
                            .onAppear {
                                HapticManager.generateFeedback(style: .error)
                            }
                    }

                    Button {
                        HapticManager.generateFeedback(style: .medium)
                        register()
                    } label: {
                        Group {
                            if authViewModel.isLoading {
                                ProgressView()
                                    .tint(.white)
                            } else {
                                Text("Register")
                                    .fontWeight(.semibold)
                            }
                        }
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.primary)
                        .foregroundStyle(Color.systemBackground)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .shadow(color: .black.opacity(0.2), radius: 10, x: 0, y: 5)
                    }
                    .disabled(authViewModel.isLoading)
                }
                .macOSFormWidth(520)
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(.primary)
                }
            }
        }
    }

    private func register() {
        localError = nil

        guard password == confirmPassword else {
            localError = "Passwords do not match."
            HapticManager.generateFeedback(style: .error)
            return
        }

        guard password.count >= 6 else {
            localError = "Password must be at least 6 characters."
            HapticManager.generateFeedback(style: .error)
            return
        }

        Task {
            await authViewModel.register(email: AuthService.authEmail(forUsername: username), password: password, fullName: fullName)
            if authViewModel.authState == .authenticated {
                HapticManager.generateFeedback(style: .success)
                dismiss()
            }
        }
    }
}

#Preview {
    RegisterView()
        .environment(AuthViewModel())
}

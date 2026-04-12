//
//  RegisterView.swift
//  retailmanagement
//

import SwiftUI

struct RegisterView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var fullName = ""
    @State private var email = ""
    @State private var password = ""
    @State private var confirmPassword = ""
    @State private var localError: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                VStack(spacing: 8) {
                    Image(systemName: "person.badge.plus")
                        .font(.system(size: 48))
                        .foregroundStyle(.blue)
                    Text("Create Account")
                        .font(.title2.bold())
                }
                .padding(.top, 32)

                VStack(spacing: 16) {
                    TextField("Full Name", text: $fullName)
                        .textContentType(.name)
                        .autocorrectionDisabled()
                        .padding()
                        .background(.quaternary)
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    TextField("Email", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .padding()
                        .background(.quaternary)
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    SecureField("Password", text: $password)
                        .textContentType(.newPassword)
                        .padding()
                        .background(.quaternary)
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    SecureField("Confirm Password", text: $confirmPassword)
                        .textContentType(.newPassword)
                        .padding()
                        .background(.quaternary)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                if let error = localError ?? authViewModel.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                }

                Button {
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
                    .background(.blue)
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                }
                .disabled(authViewModel.isLoading)

                Spacer()
            }
            .padding(.horizontal, 32)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private func register() {
        localError = nil

        guard password == confirmPassword else {
            localError = "Passwords do not match."
            return
        }

        guard password.count >= 6 else {
            localError = "Password must be at least 6 characters."
            return
        }

        Task {
            await authViewModel.register(email: email, password: password, fullName: fullName)
            if authViewModel.authState == .authenticated {
                dismiss()
            }
        }
    }
}

#Preview {
    RegisterView()
        .environment(AuthViewModel())
}

//
//  LoginView.swift
//  retailmanagement
//

import SwiftUI

struct LoginView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @State private var username = ""
    @State private var password = ""
    @State private var showRegister = false

    // MARK: - Fluid Focus States
    enum Field {
        case username, password
    }
    @FocusState private var focusedField: Field?

    var body: some View {
        NavigationStack {
            AuthLayout {
                VStack(spacing: 28) {
                    VStack(spacing: 20) {
                        Image("BrandLogo")
                            .resizable()
                            .scaledToFit()
                            .frame(height: 44)
                            .padding(6)
                            .background(Color.white.opacity(0.8))
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: 16, style: .continuous)
                                    .stroke(Color.white.opacity(0.9), lineWidth: 1)
                            )
                            .shadow(color: .black.opacity(0.09), radius: 36, x: 0, y: 10)

                        Text("Retail Management")
                            .font(.system(size: 12, weight: .semibold))
                            .textCase(.uppercase)
                            .tracking(2)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.bottom, 4)

                    VStack(spacing: 16) {
                        TextField("Username", text: $username)
                            .focused($focusedField, equals: .username)
                            .textContentType(.username)
                            #if canImport(UIKit)
                            .keyboardType(.asciiCapable)
                            .textInputAutocapitalization(.never)
                            #endif
                            .autocorrectionDisabled()
                            .modifier(LoginFieldChrome(isFocused: focusedField == .username))

                        SecureField("Password", text: $password)
                            .focused($focusedField, equals: .password)
                            .textContentType(.password)
                            .modifier(LoginFieldChrome(isFocused: focusedField == .password))
                    }

                    if let error = authViewModel.errorMessage {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .multilineTextAlignment(.center)
                            .padding(.top, -8)
                            .onAppear {
                                HapticManager.generateFeedback(style: .error)
                            }
                    }
                    if let info = authViewModel.infoMessage {
                        Text(info)
                            .font(.caption)
                            .foregroundStyle(.green)
                            .multilineTextAlignment(.center)
                            .padding(.top, -8)
                    }

                    VStack(spacing: 16) {
                        Button {
                            HapticManager.generateFeedback(style: .medium)
                            Task {
                                await authViewModel.signIn(username: username, password: password)
                                if authViewModel.authState == .authenticated {
                                    HapticManager.generateFeedback(style: .success)
                                }
                            }
                        } label: {
                            Group {
                                if authViewModel.isLoading {
                                    ProgressView()
                                        .tint(.white)
                                } else {
                                    Text("Sign In")
                                        .fontWeight(.semibold)
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .frame(minHeight: 52)
                            .background(Color(red: 0.039, green: 0.388, blue: 0.965))
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 17, style: .continuous))
                            .shadow(color: Color(red: 0.039, green: 0.388, blue: 0.965).opacity(0.24), radius: 30, x: 0, y: 12)
                        }
                        .disabled(authViewModel.isLoading)

                        HStack(spacing: 18) {
                            Button(authViewModel.isResettingPassword ? "Sending reset..." : "Forgot password?") {
                                HapticManager.generateFeedback(style: .light)
                                Task { await authViewModel.resetPassword(username: username) }
                            }
                            .disabled(authViewModel.isResettingPassword)

                            Button("Create an Account") {
                                HapticManager.generateFeedback(style: .light)
                                showRegister = true
                            }
                        }
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(.primary)
                    }
                }
            }
            #if canImport(UIKit)
            .navigationBarHidden(true)
            #endif
            .sheet(isPresented: $showRegister) {
                RegisterView()
            }
        }
    }
}

#Preview {
    LoginView()
        .environment(AuthViewModel())
}

private struct LoginFieldChrome: ViewModifier {
    let isFocused: Bool

    func body(content: Content) -> some View {
        content
            .font(.system(size: 16))
            .padding(.horizontal, 16)
            .frame(minHeight: 52)
            .background(Color.white.opacity(0.76))
            .clipShape(RoundedRectangle(cornerRadius: 17, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 17, style: .continuous)
                    .stroke(
                        isFocused
                            ? Color(red: 0.039, green: 0.388, blue: 0.965).opacity(0.7)
                            : Color.primary.opacity(0.1),
                        lineWidth: 1
                    )
            )
            .shadow(
                color: isFocused
                    ? Color(red: 0.039, green: 0.388, blue: 0.965).opacity(0.12)
                    : .black.opacity(0.045),
                radius: isFocused ? 30 : 26,
                x: 0,
                y: isFocused ? 10 : 8
            )
            .animation(.easeOut(duration: 0.2), value: isFocused)
    }
}

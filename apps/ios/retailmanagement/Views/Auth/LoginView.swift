//
//  LoginView.swift
//  retailmanagement
//

import SwiftUI

struct LoginView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @State private var email = ""
    @State private var password = ""
    @State private var showRegister = false

    // MARK: - Fluid Focus States
    enum Field {
        case email, password
    }
    @FocusState private var focusedField: Field?

    var body: some View {
        @Bindable var authVM = authViewModel

        NavigationStack {
            AuthLayout {
                VStack(spacing: 32) {
                    // App branding
                    VStack(spacing: 12) {
                        Image("BrandLogo")
                            .resizable()
                            .scaledToFit()
                            .frame(height: 60)
                            .shadow(color: .black.opacity(0.15), radius: 6, x: 0, y: 3)

                        Text("Irina Jewellery")
                            .font(.system(size: 28, weight: .bold, design: .serif))
                        
                        Text("Retail Management")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .textCase(.uppercase)
                            .tracking(2)
                    }
                    .padding(.bottom, 8)

                    // Login form with Fluid Glass TextFields
                    VStack(spacing: 16) {
                        TextField("Email", text: $email)
                            .focused($focusedField, equals: .email)
                            .textContentType(.emailAddress)
                            #if canImport(UIKit)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            #endif
                            .autocorrectionDisabled()
                            .padding()
                            .background(Color.systemBackground.opacity(0.5))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .overlay(
                                RoundedRectangle(cornerRadius: 12)
                                    .stroke(focusedField == .email ? Color.blue : Color.primary.opacity(0.1), lineWidth: focusedField == .email ? 2 : 1)
                            )
                            .shadow(color: focusedField == .email ? Color.blue.opacity(0.2) : .clear, radius: 8, x: 0, y: 4)
                            .animation(.easeOut(duration: 0.2), value: focusedField)

                        SecureField("Password", text: $password)
                            .focused($focusedField, equals: .password)
                            .textContentType(.password)
                            .padding()
                            .background(Color.systemBackground.opacity(0.5))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .overlay(
                                RoundedRectangle(cornerRadius: 12)
                                    .stroke(focusedField == .password ? Color.blue : Color.primary.opacity(0.1), lineWidth: focusedField == .password ? 2 : 1)
                            )
                            .shadow(color: focusedField == .password ? Color.blue.opacity(0.2) : .clear, radius: 8, x: 0, y: 4)
                            .animation(.easeOut(duration: 0.2), value: focusedField)
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

                    VStack(spacing: 16) {
                        Button {
                            HapticManager.generateFeedback(style: .medium)
                            Task {
                                await authViewModel.signIn(email: email, password: password)
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
                            .padding()
                            .background(Color.primary)
                            .foregroundStyle(Color.systemBackground)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .shadow(color: .black.opacity(0.2), radius: 10, x: 0, y: 5)
                        }
                        .disabled(authViewModel.isLoading)

                        Button("Create an Account") {
                            HapticManager.generateFeedback(style: .light)
                            showRegister = true
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

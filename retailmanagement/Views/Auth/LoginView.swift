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

    var body: some View {
        @Bindable var authVM = authViewModel

        NavigationStack {
            VStack(spacing: 24) {
                Spacer()

                // App branding
                VStack(spacing: 8) {
                    Image(systemName: "storefront")
                        .font(.system(size: 60))
                        .foregroundStyle(.blue)
                    Text("RetailSG")
                        .font(.largeTitle.bold())
                    Text("Retail Management")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                // Login form
                VStack(spacing: 16) {
                    TextField("Email", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .padding()
                        .background(.quaternary)
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    SecureField("Password", text: $password)
                        .textContentType(.password)
                        .padding()
                        .background(.quaternary)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                if let error = authViewModel.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                }

                Button {
                    Task {
                        await authViewModel.signIn(email: email, password: password)
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
                    .background(.blue)
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                }
                .disabled(authViewModel.isLoading)

                Button("Create an Account") {
                    showRegister = true
                }
                .font(.footnote)

                Spacer()
            }
            .padding(.horizontal, 32)
            .navigationBarHidden(true)
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

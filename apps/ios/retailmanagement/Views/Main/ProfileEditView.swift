//
//  ProfileEditView.swift
//  retailmanagement
//

import SwiftUI

private struct UpdateProfileBody: Encodable {
    var fullName: String?
    var phone: String?
}

@MainActor
@Observable
final class ProfileEditViewModel {
    var fullName: String = ""
    var phone: String = ""
    var isSaving = false
    var errorMessage: String?
    var didSave = false

    private static let maxNameLength = 100
    private static let sgPhoneRegex = /^(\+65)?[689]\d{7}$/

    func load(from user: AppUser) {
        fullName = user.fullName
        phone = user.phone ?? ""
    }

    func save() async {
        let trimmedName = fullName.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedPhone = phone.trimmingCharacters(in: .whitespacesAndNewlines)

        guard !trimmedName.isEmpty else {
            errorMessage = "Name cannot be empty."
            return
        }
        guard trimmedName.count <= Self.maxNameLength else {
            errorMessage = "Name must be \(Self.maxNameLength) characters or fewer."
            return
        }
        if !trimmedPhone.isEmpty {
            guard trimmedPhone.wholeMatch(of: Self.sgPhoneRegex) != nil else {
                errorMessage = "Please enter a valid Singapore phone number (e.g. 91234567)."
                return
            }
        }

        isSaving = true
        errorMessage = nil

        do {
            let body = UpdateProfileBody(
                fullName: trimmedName,
                phone: trimmedPhone.isEmpty ? nil : trimmedPhone
            )
            let _: DataResponse<AppUser> = try await NetworkService.shared.patch(
                endpoint: "/api/users/me",
                body: body
            )
            didSave = true
        } catch {
            errorMessage = error.localizedDescription
        }

        isSaving = false
    }
}

struct ProfileEditView: View {
    @Environment(AuthViewModel.self) var authViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var viewModel = ProfileEditViewModel()

    var body: some View {
        NavigationStack {
            Form {
                Section("Personal Information") {
                    TextField("Full Name", text: $viewModel.fullName)
                        .textContentType(.name)
                        .autocorrectionDisabled()

                    TextField("Phone", text: $viewModel.phone)
                        .textContentType(.telephoneNumber)
                        #if canImport(UIKit)
                        .keyboardType(.phonePad)
                        #endif
                }

                Section("Account") {
                    LabeledContent("Username", value: authViewModel.currentUser?.username ?? "—")
                }

                if let error = viewModel.errorMessage {
                    Section {
                        Text(error)
                            .foregroundStyle(.red)
                            .font(.caption)
                    }
                }
            }
            .macOSFormWidth(560)
            .navigationTitle("Edit Profile")
            #if canImport(UIKit)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button {
                        Task { await viewModel.save() }
                    } label: {
                        if viewModel.isSaving {
                            ProgressView()
                        } else {
                            Text("Save")
                        }
                    }
                    .disabled(viewModel.isSaving)
                }
            }
            .onAppear {
                if let user = authViewModel.currentUser {
                    viewModel.load(from: user)
                }
            }
            .onChange(of: viewModel.didSave) { _, saved in
                if saved {
                    Task {
                        await authViewModel.refreshProfile()
                    }
                    dismiss()
                }
            }
        }
    }
}

#Preview {
    ProfileEditView()
        .environment(AuthViewModel())
}

//
//  ContentView.swift
//  retailmanagement
//
//  Created by Craig on 11/4/26.
//

import SwiftUI

struct ContentView: View {
    @Environment(AuthViewModel.self) var authViewModel

    var body: some View {
        Group {
            switch authViewModel.authState {
            case .loading:
                LoadingView(message: "Checking authentication...")
            case .unauthenticated:
                LoginView()
            case .authenticated:
                MainTabView()
            }
        }
        .animation(.easeInOut, value: authViewModel.authState)
    }
}

#Preview {
    ContentView()
        .environment(AuthViewModel())
}

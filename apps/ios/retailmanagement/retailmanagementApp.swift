//
//  retailmanagementApp.swift
//  retailmanagement
//
//  Created by Craig on 11/4/26.
//

import FirebaseCore
import SwiftUI

// MARK: - Platform-Adaptive App Delegates

#if canImport(UIKit)
import UIKit

class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        configureFirebaseIfAvailable()
        return true
    }
}
#else
import AppKit

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        configureFirebaseIfAvailable()
    }
}
#endif

// MARK: - Safe Firebase Initialization

/// Configures Firebase only if GoogleService-Info.plist is present in the bundle.
/// This prevents a fatal crash when the plist is missing (e.g. fresh clone, CI).
private func configureFirebaseIfAvailable() {
    if Bundle.main.path(forResource: "GoogleService-Info", ofType: "plist") != nil {
        FirebaseApp.configure()
    } else {
        print("⚠️ GoogleService-Info.plist not found — Firebase is NOT configured.")
        print("   Download it from https://console.firebase.google.com and add it to the app bundle.")
    }
}

// MARK: - App Entry Point

@main
struct retailmanagementApp: App {
    #if canImport(UIKit)
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    #else
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    #endif

    @State private var authViewModel = AuthViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(authViewModel)
            #if os(macOS)
                .frame(minWidth: 900, minHeight: 600)
            #endif
        }
        #if os(macOS)
        .defaultSize(width: 1100, height: 750)
        .commands {
            CommandGroup(replacing: .appInfo) {
                Button("About RetailSG") {
                    // Future: show about panel
                }
            }
            CommandGroup(after: .appSettings) {
                Button("Sign Out") {
                    authViewModel.signOut()
                }
                .keyboardShortcut("Q", modifiers: [.command, .shift])
            }
        }
        #endif
    }
}

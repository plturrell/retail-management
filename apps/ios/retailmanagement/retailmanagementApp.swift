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
    if AppLaunchMode.isManagerInventoryUITest {
        print("UI test harness launch detected — skipping Firebase configuration.")
        return
    }
    if Bundle.main.path(forResource: "GoogleService-Info", ofType: "plist") != nil {
        FirebaseApp.configure()
    } else {
        print("⚠️ GoogleService-Info.plist not found — Firebase is NOT configured.")
        print("   Download it from https://console.firebase.google.com and add it to the app bundle.")
    }
}

// MARK: - Cross-Window Command Notifications

extension Notification.Name {
    /// Posted when the user invokes the Refresh menu item / shortcut.
    static let appRefreshRequested = Notification.Name("appRefreshRequested")
    /// Posted when the user invokes the Find menu item / shortcut.
    static let appFindRequested = Notification.Name("appFindRequested")
    /// Posted when the app should open a per-store window.
    /// `userInfo["storeId"] as? String` carries the target store id.
    static let openStoreWindowRequested = Notification.Name("openStoreWindowRequested")
}

// MARK: - App Entry Point

@main
struct retailmanagementApp: App {
    #if canImport(UIKit)
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    #else
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    #endif

    @State private var authViewModel: AuthViewModel?
    @State private var storeViewModel = StoreViewModel()

    /// User-controllable toggle for the macOS menu bar extra. Persisted across launches.
    @AppStorage("menuBarExtraEnabled") private var menuBarExtraEnabled: Bool = true

    init() {
        _authViewModel = State(
            initialValue: AppLaunchMode.isManagerInventoryUITest ? nil : AuthViewModel()
        )
    }

    var body: some Scene {
        WindowGroup(id: "main") {
            Group {
                if AppLaunchMode.isManagerInventoryUITest {
                    ManagerInventoryUITestHarnessView()
                } else if let authViewModel {
                    ContentView()
                        .environment(authViewModel)
                        .environment(storeViewModel)
                        #if os(macOS)
                        .modifier(OpenStoreWindowBridge())
                        #endif
                } else {
                    LoadingView(message: "Starting RetailSG…")
                }
            }
            #if os(macOS)
            .frame(minWidth: 900, minHeight: 600)
            #endif
        }
        #if os(macOS)
        .defaultSize(width: 1100, height: 750)
        .windowResizability(.contentMinSize)
        .commands {
            // Real About panel (replaces the no-op stub).
            CommandGroup(replacing: .appInfo) {
                Button("About RetailSG") {
                    NSApplication.shared.orderFrontStandardAboutPanel(nil)
                }
            }
            // Refresh — ⌘R, broadcast to whichever view is active.
            CommandGroup(after: .newItem) {
                Button("Refresh") {
                    NotificationCenter.default.post(name: .appRefreshRequested, object: nil)
                }
                .keyboardShortcut("R", modifiers: [.command])
            }
            // Find — ⌘F, broadcast to focus the active .searchable field.
            CommandGroup(after: .textEditing) {
                Button("Find") {
                    NotificationCenter.default.post(name: .appFindRequested, object: nil)
                }
                .keyboardShortcut("F", modifiers: [.command])
            }
            // File menu — Open Store in New Window.
            CommandGroup(after: .newItem) {
                Button("New Store Window") {
                    if let storeId = storeViewModel.selectedStore?.id {
                        NotificationCenter.default.post(
                            name: .openStoreWindowRequested,
                            object: nil,
                            userInfo: ["storeId": storeId]
                        )
                    }
                }
                .keyboardShortcut("N", modifiers: [.command, .option])
                .disabled(storeViewModel.selectedStore == nil)
            }
            // Account menu (avoid clobbering ⇧⌘Q which is "Quit and keep windows").
            CommandMenu("Account") {
                Button("Sign Out") {
                    authViewModel?.signOut()
                }
                .keyboardShortcut("O", modifiers: [.command, .shift])
            }
        }
        #endif

        #if os(macOS)
        // Per-store window — opens pinned to a specific store id. Each window
        // gets its own scoped `StoreViewModel`, so users can view two stores
        // side by side without cross-mutating the shared selection.
        WindowGroup("Store", id: "store", for: String.self) { $storeId in
            if let authViewModel {
                if let storeId {
                    ScopedStoreWindow(storeId: storeId)
                        .environment(authViewModel)
                        .frame(minWidth: 900, minHeight: 600)
                } else {
                    Text("No store selected.")
                        .frame(minWidth: 600, minHeight: 400)
                }
            } else {
                LoadingView(message: "Starting RetailSG…")
                    .frame(minWidth: 600, minHeight: 400)
            }
        }
        .defaultSize(width: 1100, height: 750)
        .windowResizability(.contentMinSize)
        #endif

        #if os(macOS)
        // Native Preferences/Settings window — opens with ⌘,
        Settings {
            if let authViewModel {
                SettingsView()
                    .environment(authViewModel)
                    .environment(storeViewModel)
                    .frame(minWidth: 480, idealWidth: 540, minHeight: 420, idealHeight: 520)
            } else {
                LoadingView(message: "Starting RetailSG…")
            }
        }

        // System-wide menu bar shortcut: current store + user, quick switching, sign out.
        MenuBarExtra(
            "RetailSG",
            systemImage: "cart.fill",
            isInserted: $menuBarExtraEnabled
        ) {
            if let authViewModel {
                MenuBarContent()
                    .environment(authViewModel)
                    .environment(storeViewModel)
            } else {
                Text("Starting RetailSG…")
            }
        }
        .menuBarExtraStyle(.menu)
        #endif
    }
}

// MARK: - macOS Menu Bar Content

#if os(macOS)
/// Compact menu shown from the macOS menu bar extra. Renders as a native menu
/// (per `.menuBarExtraStyle(.menu)`), so all controls must be `Button`/`Picker`/etc.
private struct MenuBarContent: View {
    @Environment(AuthViewModel.self) private var authViewModel
    @Environment(StoreViewModel.self) private var storeViewModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        // Account block.
        if let user = authViewModel.currentUser {
            Text(user.fullName)
            Text(user.username).font(.caption)
        } else {
            Text("Not signed in")
        }

        Divider()

        // Current store + quick switch.
        if storeViewModel.stores.isEmpty {
            Text("No stores available")
        } else {
            Menu("Store: \(storeViewModel.selectedStore?.name ?? "None")") {
                ForEach(storeViewModel.stores) { store in
                    Button {
                        storeViewModel.selectStore(store)
                    } label: {
                        if storeViewModel.selectedStore?.id == store.id {
                            Label(store.name, systemImage: "checkmark")
                        } else {
                            Text(store.name)
                        }
                    }
                }
            }

            // Per-store window opener.
            Menu("Open Store in New Window") {
                ForEach(storeViewModel.stores) { store in
                    Button(store.name) {
                        openWindow(id: "store", value: store.id)
                        NSApp.activate(ignoringOtherApps: true)
                    }
                }
            }
        }

        Divider()

        Button("Open Main Window") {
            openWindow(id: "main")
            NSApp.activate(ignoringOtherApps: true)
        }
        .keyboardShortcut("0", modifiers: [.command])

        Button("Refresh") {
            NotificationCenter.default.post(name: .appRefreshRequested, object: nil)
        }
        .keyboardShortcut("R", modifiers: [.command])

        Divider()

        if authViewModel.authState == .authenticated {
            Button("Sign Out") {
                authViewModel.signOut()
            }
            .keyboardShortcut("O", modifiers: [.command, .shift])
        }

        Button("Quit RetailSG") {
            NSApplication.shared.terminate(nil)
        }
        .keyboardShortcut("Q", modifiers: [.command])
    }
}

// MARK: - Scoped Store Window

/// Hosts a `MainTabView` pinned to a single store id. Each instance creates
/// its own `StoreViewModel(pinnedStoreId:)`, so multiple per-store windows
/// can coexist without cross-mutating the shared store selection.
private struct ScopedStoreWindow: View {
    let storeId: String
    @State private var storeViewModel: StoreViewModel

    init(storeId: String) {
        self.storeId = storeId
        _storeViewModel = State(initialValue: StoreViewModel(pinnedStoreId: storeId))
    }

    var body: some View {
        MainTabView()
            .environment(storeViewModel)
            .navigationTitle(storeViewModel.selectedStore?.name ?? "Store")
    }
}

// MARK: - Open-Store-Window Notification Bridge

/// Bridges the `File > New Store Window` command (which lives outside the
/// view hierarchy and so cannot read `\.openWindow`) into an `openWindow`
/// invocation in the main window's view tree.
private struct OpenStoreWindowBridge: ViewModifier {
    @Environment(\.openWindow) private var openWindow

    func body(content: Content) -> some View {
        content
            .onReceive(NotificationCenter.default.publisher(for: .openStoreWindowRequested)) { note in
                guard let storeId = note.userInfo?["storeId"] as? String else { return }
                openWindow(id: "store", value: storeId)
            }
    }
}
#endif

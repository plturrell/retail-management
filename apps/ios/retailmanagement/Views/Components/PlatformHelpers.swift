//
//  PlatformHelpers.swift
//  retailmanagement
//
//  Cross-platform helpers for macOS / iOS / visionOS.
//

import SwiftUI

// MARK: - Platform Color Alias

#if canImport(UIKit)
import UIKit
typealias PlatformColor = UIColor
#elseif canImport(AppKit)
import AppKit
typealias PlatformColor = NSColor
#endif

// MARK: - Cross-Platform Colors

extension Color {
    /// A system background color that resolves correctly on both iOS and macOS.
    static var systemBackground: Color {
        #if canImport(UIKit)
        Color(uiColor: .systemBackground)
        #else
        Color(nsColor: .windowBackgroundColor)
        #endif
    }

    /// A secondary system background for grouped content.
    static var secondarySystemBackground: Color {
        #if canImport(UIKit)
        Color(uiColor: .secondarySystemBackground)
        #else
        Color(nsColor: .controlBackgroundColor)
        #endif
    }
}

// MARK: - Adaptive Column Count

/// Returns an appropriate column count based on platform and available width.
enum AdaptiveLayout {
    static var kpiColumns: Int {
        #if os(macOS)
        return 4
        #else
        return 2
        #endif
    }

    static func kpiGridColumns() -> [GridItem] {
        Array(repeating: GridItem(.flexible()), count: kpiColumns)
    }
}

// MARK: - Apple Liquid Glass Modifier

/// A universal glassmorphism modifier that perfectly standardizes
/// translucency, inner bevels, and outer drop shadows across the UI to 
/// match top-tier WWDC/Apple designs.
struct LiquidGlassUI: ViewModifier {
    var cornerRadius: CGFloat = 20

    /// iOS uses `.ultraThinMaterial` which reads well over photographic content;
    /// macOS windows are typically opaque, so a `.thinMaterial` reads cleaner
    /// and avoids the washed-out look of ultra-thin over solid window chrome.
    private var platformMaterial: Material {
        #if os(macOS)
        return .thinMaterial
        #else
        return .ultraThinMaterial
        #endif
    }

    func body(content: Content) -> some View {
        content
            .background(platformMaterial)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(LinearGradient(
                        colors: [.white.opacity(0.4), .clear, .white.opacity(0.1)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ), lineWidth: 0.5)
                    .blendMode(.overlay)
            )
            .shadow(color: .black.opacity(0.15), radius: 15, x: 0, y: 8)
    }
}

// MARK: - Cross-Platform Haptics

enum HapticManager {
    static func generateFeedback(style: FeedbackStyle = .light) {
        #if canImport(UIKit)
        switch style {
        case .light:
            let generator = UIImpactFeedbackGenerator(style: .light)
            generator.impactOccurred()
        case .medium:
            let generator = UIImpactFeedbackGenerator(style: .medium)
            generator.impactOccurred()
        case .success:
            let generator = UINotificationFeedbackGenerator()
            generator.notificationOccurred(.success)
        case .error:
            let generator = UINotificationFeedbackGenerator()
            generator.notificationOccurred(.error)
        }
        #elseif canImport(AppKit)
        // AppKit haptics only fire on trackpads that support it; for very subtle
        // "light" feedback we intentionally no-op to avoid spurious buzzes.
        switch style {
        case .success, .medium:
            NSHapticFeedbackManager.defaultPerformer.perform(.generic, performanceTime: .default)
        case .error:
            NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .default)
        case .light:
            break
        }
        #endif
    }

    enum FeedbackStyle {
        case light, medium, success, error
    }
}

// MARK: - Cross-Platform Pasteboard

/// Copies a string to the system pasteboard on iOS or macOS.
func copyToPasteboard(_ text: String) {
    #if canImport(UIKit)
    UIPasteboard.general.string = text
    #elseif canImport(AppKit)
    let pb = NSPasteboard.general
    pb.clearContents()
    pb.setString(text, forType: .string)
    #endif
}

// MARK: - Cross-Platform Keyboard Type

/// Cross-platform keyboard type. Maps to `UIKeyboardType` on UIKit,
/// no-op on AppKit (where there is no software keyboard concept).
enum CompatKeyboardType {
    case `default`
    case numberPad
    case decimalPad
    case emailAddress
    case phonePad
    case url

    #if canImport(UIKit)
    var uiKitValue: UIKeyboardType {
        switch self {
        case .default: return .default
        case .numberPad: return .numberPad
        case .decimalPad: return .decimalPad
        case .emailAddress: return .emailAddress
        case .phonePad: return .phonePad
        case .url: return .URL
        }
    }
    #endif
}

// MARK: - Conditional View Modifiers

extension View {
    /// Applies iOS-specific text input autocapitalization.
    @ViewBuilder
    func textInputAutocapitalizationCompat(_ autocapitalization: Never? = nil) -> some View {
        #if canImport(UIKit)
        self.textInputAutocapitalization(.never)
        #else
        self
        #endif
    }

    /// Applies a keyboard type on UIKit; no-op on AppKit.
    @ViewBuilder
    func keyboardTypeCompat(_ type: CompatKeyboardType) -> some View {
        #if canImport(UIKit)
        self.keyboardType(type.uiKitValue)
        #else
        self
        #endif
    }

    /// Applies `.insetGrouped` on UIKit and `.inset` on AppKit (where `insetGrouped` is unavailable).
    @ViewBuilder
    func insetGroupedListStyleCompat() -> some View {
        #if canImport(UIKit)
        self.listStyle(.insetGrouped)
        #else
        self.listStyle(.inset)
        #endif
    }

    /// Constrains width on macOS for forms that shouldn't stretch full-width.
    @ViewBuilder
    func macOSFormWidth(_ maxWidth: CGFloat = 480) -> some View {
        #if os(macOS)
        self.frame(maxWidth: maxWidth)
        #else
        self
        #endif
    }
}

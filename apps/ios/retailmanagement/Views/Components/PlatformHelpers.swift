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

    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial)
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
        switch style {
        case .success, .medium:
            NSHapticFeedbackManager.defaultPerformer.perform(.generic, performanceTime: .default)
        case .error:
            NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .default)
        case .light:
            NSHapticFeedbackManager.defaultPerformer.perform(.levelChange, performanceTime: .default)
        }
        #endif
    }

    enum FeedbackStyle {
        case light, medium, success, error
    }
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

    /// Applies iOS-specific keyboard type.
    @ViewBuilder
    func keyboardTypeCompat(_ type: Int = 0) -> some View {
        #if canImport(UIKit)
        self.keyboardType(.emailAddress)
        #else
        self
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

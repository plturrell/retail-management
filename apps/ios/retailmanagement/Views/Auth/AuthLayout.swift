//
//  AuthLayout.swift
//  retailmanagement
//

import Combine
import SwiftUI

struct AuthLayout<Content: View>: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    let content: Content

    // MARK: - Carousel State
    @State private var currentImageIndex = 1
    // The timer publishes every 6 seconds on the main loop
    let timer = Timer.publish(every: 6.0, on: .main, in: .common).autoconnect()

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        #if os(macOS)
        macOSLayout
            .onReceive(timer) { _ in cycleImage() }
        #else
        if horizontalSizeClass == .regular {
            macOSLayout // Use split layout on iPad landscape / large screens
                .onReceive(timer) { _ in cycleImage() }
        } else {
            iOSLayout
                .onReceive(timer) { _ in cycleImage() }
        }
        #endif
    }

    private func cycleImage() {
        withAnimation(.easeInOut(duration: 2.0)) {
            currentImageIndex = currentImageIndex >= 5 ? 1 : currentImageIndex + 1
        }
    }

    private var macOSLayout: some View {
        HStack(spacing: 0) {
            // Left Side: Brand Imagery
            GeometryReader { geo in
                ZStack {
                    Color.black // Base to prevent flashing during crossfades
                    
                    Image("Jewelry\(currentImageIndex)")
                        .resizable()
                        .scaledToFill()
                        .frame(width: geo.size.width, height: geo.size.height)
                        .clipped()
                        // Ensure smooth crossfades between changing IDs
                        .id(currentImageIndex)
                        .transition(.opacity)
                }
            }
            .ignoresSafeArea()

            // Right Side: Form Content
            ZStack {
                Color.systemBackground
                    .ignoresSafeArea()

                content
                    .frame(width: 400)
                    .padding(40)
            }
            .frame(width: 480)
            .shadow(color: .black.opacity(0.1), radius: 20, x: -10, y: 0)
        }
    }

    private var iOSLayout: some View {
        ZStack {
            // Background Image Carousel
            GeometryReader { geo in
                ZStack {
                    Color.black
                    
                    Image("Jewelry\(currentImageIndex)")
                        .resizable()
                        .scaledToFill()
                        .frame(width: geo.size.width, height: geo.size.height)
                        .clipped()
                        .id(currentImageIndex)
                        .transition(.opacity)
                }
            }
            .ignoresSafeArea()

            // Blur Gradient Overlay for readability
            LinearGradient(
                colors: [.black.opacity(0.4), .clear, .black.opacity(0.6)],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            // Center Form Content with Liquid Glass
            content
                .padding(32)
                .modifier(LiquidGlassUI(cornerRadius: 24))
                .padding()
        }
    }
}

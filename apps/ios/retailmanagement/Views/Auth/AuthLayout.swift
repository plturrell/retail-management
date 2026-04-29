//
//  AuthLayout.swift
//  retailmanagement
//

import SwiftUI

struct AuthLayout<Content: View>: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        GeometryReader { proxy in
            ZStack {
                LinearGradient(
                    colors: [
                        Color(red: 0.984, green: 0.992, blue: 1.0),
                        Color(red: 0.965, green: 0.976, blue: 0.988),
                        Color(red: 0.933, green: 0.965, blue: 0.957)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                Ellipse()
                    .fill(Color.white.opacity(0.12))
                    .overlay(
                        Ellipse()
                            .stroke(Color.white.opacity(0.7), lineWidth: 1)
                    )
                    .frame(width: max(proxy.size.width * 1.55, 540), height: 310)
                    .shadow(color: .black.opacity(0.035), radius: 70, x: 0, y: 18)
                    .offset(y: proxy.size.height * 0.03)

                LinearGradient(
                    colors: [Color(red: 0.847, green: 0.906, blue: 0.89).opacity(0.24), .clear],
                    startPoint: .bottom,
                    endPoint: .top
                )
                .frame(height: 160)
                .frame(maxHeight: .infinity, alignment: .bottom)
                .ignoresSafeArea()

                content
                    .frame(maxWidth: formWidth)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 40)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private var formWidth: CGFloat {
        #if os(macOS)
        return 350
        #else
        return horizontalSizeClass == .regular ? 400 : 350
        #endif
    }
}

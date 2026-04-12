//
//  AuthState.swift
//  retailmanagement
//

import Foundation

nonisolated enum AuthState: Equatable, Sendable {
    case loading
    case unauthenticated
    case authenticated
}

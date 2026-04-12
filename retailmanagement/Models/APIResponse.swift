//
//  APIResponse.swift
//  retailmanagement
//

import Foundation

nonisolated struct DataResponse<T: Codable & Sendable>: Codable, Sendable {
    let success: Bool
    let message: String
    let data: T
}

nonisolated struct PaginatedResponse<T: Codable & Sendable>: Codable, Sendable {
    let success: Bool
    let message: String
    let data: [T]
    let total: Int
    let page: Int
    let pageSize: Int
}

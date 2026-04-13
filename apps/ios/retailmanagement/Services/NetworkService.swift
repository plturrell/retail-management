//
//  NetworkService.swift
//  retailmanagement
//

import Foundation

enum NetworkError: LocalizedError {
    case invalidURL
    case invalidResponse
    case unauthorized
    case serverError(statusCode: Int, message: String?)
    case decodingError(Error)
    case offline
    case unknown(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid URL."
        case .invalidResponse:
            return "Invalid server response."
        case .unauthorized:
            return "Session expired. Please sign in again."
        case .serverError(let code, let message):
            return message ?? "Server error (\(code))."
        case .decodingError:
            return "Failed to process server response."
        case .offline:
            return "No internet connection. Please check your network."
        case .unknown(let error):
            return error.localizedDescription
        }
    }

    var isRetryable: Bool {
        switch self {
        case .serverError(let code, _): return code >= 500
        case .unknown: return true
        case .offline: return true
        default: return false
        }
    }
}

actor NetworkService {
    static let shared = NetworkService()

    /// Resolves the API base URL from Info.plist or defaults to localhost.
    private static var resolvedBaseURL: String {
        if let url = Bundle.main.infoDictionary?["RETAILSG_API_URL"] as? String, !url.isEmpty {
            return url
        }
        #if DEBUG
        return "http://localhost:8000"
        #else
        return "https://retailsg-api-561509133799.asia-southeast1.run.app"
        #endif
    }

    private let baseURL: String
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    /// Called when a 401 is received so the app can sign the user out.
    var onUnauthorized: (@Sendable () -> Void)?

    /// Base URL defaults to localhost for development.
    /// For production, set the RETAILSG_API_URL in a Config.plist or xcconfig.
    private init(baseURL: String? = nil) {
        self.baseURL = baseURL ?? Self.resolvedBaseURL
        self.session = URLSession.shared

        self.decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        self.encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
    }

    // MARK: - Public API

    func get<T: Decodable>(endpoint: String) async throws -> T {
        let request = try await buildRequest(endpoint: endpoint, method: "GET")
        return try await execute(request)
    }

    func get<T: Decodable>(endpoint: String, queryItems: [URLQueryItem]) async throws -> T {
        let request = try await buildRequest(endpoint: endpoint, queryItems: queryItems, method: "GET")
        return try await execute(request)
    }

    func post<T: Decodable, B: Encodable>(endpoint: String, body: B) async throws -> T {
        var request = try await buildRequest(endpoint: endpoint, method: "POST")
        request.httpBody = try encoder.encode(body)
        return try await execute(request)
    }

    func put<T: Decodable, B: Encodable>(endpoint: String, body: B) async throws -> T {
        var request = try await buildRequest(endpoint: endpoint, method: "PUT")
        request.httpBody = try encoder.encode(body)
        return try await execute(request)
    }

    func patch<T: Decodable, B: Encodable>(endpoint: String, body: B) async throws -> T {
        var request = try await buildRequest(endpoint: endpoint, method: "PATCH")
        request.httpBody = try encoder.encode(body)
        return try await execute(request)
    }

    func delete<T: Decodable>(endpoint: String) async throws -> T {
        let request = try await buildRequest(endpoint: endpoint, method: "DELETE")
        return try await execute(request)
    }

    func deleteNoContent(endpoint: String) async throws {
        let request = try await buildRequest(endpoint: endpoint, method: "DELETE")
        let (_, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw NetworkError.invalidResponse
        }
        guard (200...299).contains(httpResponse.statusCode) else {
            if httpResponse.statusCode == 401 {
                onUnauthorized?()
                throw NetworkError.unauthorized
            }
            throw NetworkError.serverError(statusCode: httpResponse.statusCode, message: nil)
        }
    }

    // MARK: - Private

    private func buildRequest(endpoint: String, queryItems: [URLQueryItem]? = nil, method: String) async throws -> URLRequest {
        let url: URL
        if let queryItems, !queryItems.isEmpty {
            guard var components = URLComponents(string: baseURL + endpoint) else {
                throw NetworkError.invalidURL
            }
            components.queryItems = (components.queryItems ?? []) + queryItems
            guard let built = components.url else {
                throw NetworkError.invalidURL
            }
            url = built
        } else {
            guard let parsed = URL(string: baseURL + endpoint) else {
                throw NetworkError.invalidURL
            }
            url = parsed
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = try? await AuthService.shared.getIdToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        return request
    }

    private static let maxRetries = 2
    private static let baseRetryDelay: UInt64 = 500_000_000  // 0.5s in nanoseconds

    private func execute<T: Decodable>(_ request: URLRequest) async throws -> T {
        var lastError: NetworkError = .invalidResponse

        for attempt in 0...Self.maxRetries {
            do {
                let result: T = try await executeOnce(request)
                return result
            } catch let error as NetworkError {
                lastError = error
                guard error.isRetryable, attempt < Self.maxRetries else { throw error }
                let delay = Self.baseRetryDelay * UInt64(1 << attempt)
                try? await Task.sleep(nanoseconds: delay)
            }
        }
        throw lastError
    }

    private func executeOnce<T: Decodable>(_ request: URLRequest) async throws -> T {
        let data: Data
        let response: URLResponse

        do {
            (data, response) = try await session.data(for: request)
        } catch let urlError as URLError where urlError.code == .notConnectedToInternet
            || urlError.code == .networkConnectionLost {
            throw NetworkError.offline
        } catch {
            throw NetworkError.unknown(error)
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw NetworkError.invalidResponse
        }

        switch httpResponse.statusCode {
        case 200...299:
            do {
                return try decoder.decode(T.self, from: data)
            } catch {
                throw NetworkError.decodingError(error)
            }
        case 401:
            onUnauthorized?()
            throw NetworkError.unauthorized
        default:
            let message = String(data: data, encoding: .utf8)
            throw NetworkError.serverError(statusCode: httpResponse.statusCode, message: message)
        }
    }
}

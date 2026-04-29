//
//  NecStatusCard.swift
//  retailmanagement
//
//  Read-only telemetry card surfacing the latest NEC CAG scheduled push
//  outcome to mobile owners. The full SFTP/scheduler configuration UI lives
//  on staff-portal (CagSettingsPage); this card is the mobile parity for
//  "did the 3-hour push succeed?" without re-implementing the whole form.
//

import SwiftUI

struct NecStatusCard: View {
    @State private var config: CagConfigPublic?
    @State private var errorMessage: String?
    @State private var isLoading = true

    var body: some View {
        Group {
            if isLoading {
                placeholder("Checking NEC scheduler\u{2026}", system: "clock.arrow.circlepath")
            } else if let cfg = config {
                content(cfg)
            } else if let err = errorMessage {
                placeholder("NEC status unavailable: \(err)", system: "exclamationmark.triangle")
            }
        }
        .task { await load() }
    }

    private func content(_ cfg: CagConfigPublic) -> some View {
        let tint = statusTint(for: cfg.schedulerLastRunStatus)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: cfg.schedulerEnabled ? "clock.arrow.2.circlepath" : "pause.circle")
                    .foregroundStyle(tint)
                Text("NEC scheduled push")
                    .font(.subheadline.bold())
                Spacer()
                Text(cfg.schedulerEnabled ? cfg.schedulerCron : "Paused")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 12) {
                badge(cfg.schedulerLastRunStatus.isEmpty ? "no runs yet" : cfg.schedulerLastRunStatus,
                      tint: tint)
                if !cfg.schedulerLastRunAt.isEmpty {
                    Text(cfg.schedulerLastRunAt)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                if cfg.schedulerLastRunFiles > 0 {
                    Text("\(cfg.schedulerLastRunFiles) file(s) · \(cfg.schedulerLastRunBytes) bytes")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            if !cfg.schedulerLastRunMessage.isEmpty {
                Text(cfg.schedulerLastRunMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(12)
        .background(.ultraThinMaterial)
        .cornerRadius(10)
    }

    private func placeholder(_ text: String, system: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: system).foregroundStyle(.secondary)
            Text(text).font(.caption).foregroundStyle(.secondary)
            Spacer()
        }
        .padding(12)
        .background(.ultraThinMaterial)
        .cornerRadius(10)
    }

    private func badge(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(.caption2.bold())
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(tint.opacity(0.15))
            .foregroundStyle(tint)
            .cornerRadius(4)
    }

    private func statusTint(for status: String) -> Color {
        switch status.lowercased() {
        case "ok", "success": return .green
        case "error", "failed": return .red
        case "running": return .orange
        default: return .secondary
        }
    }

    private func load() async {
        isLoading = true
        do {
            let cfg: CagConfigPublic = try await NetworkService.shared.get(endpoint: "/api/cag/config")
            await MainActor.run {
                self.config = cfg
                self.errorMessage = nil
                self.isLoading = false
            }
        } catch {
            await MainActor.run {
                self.errorMessage = (error as? NetworkError)?.localizedDescription
                    ?? error.localizedDescription
                self.isLoading = false
            }
        }
    }
}

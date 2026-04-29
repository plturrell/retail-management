package com.retailmanagement.ui.staff

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PauseCircle
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.CagConfigPublic
import kotlinx.coroutines.launch

/**
 * Read-only telemetry card surfacing the latest NEC CAG scheduled push
 * outcome to mobile owners. Mirrors the iOS [NecStatusCard]: the full
 * SFTP/scheduler config form remains web-only (CagSettingsPage); this card
 * is the mobile parity for "did the 3-hour push succeed?" without
 * re-implementing the whole form.
 */
@Composable
fun NecStatusCard() {
    var config by remember { mutableStateOf<CagConfigPublic?>(null) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var isLoading by remember { mutableStateOf(true) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        scope.launch {
            try {
                config = RetrofitClient.api.getCagConfig()
                errorMessage = null
            } catch (e: Exception) {
                errorMessage = e.localizedMessage ?: "unavailable"
            } finally {
                isLoading = false
            }
        }
    }

    when {
        isLoading -> Placeholder("Checking NEC scheduler\u2026", Icons.Default.Schedule)
        config != null -> Content(config!!)
        else -> Placeholder("NEC status unavailable: ${errorMessage.orEmpty()}", Icons.Default.Warning)
    }
}

@Composable
private fun Content(cfg: CagConfigPublic) {
    val (tint, label) = statusTintAndLabel(cfg.schedulerLastRunStatus)
    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(10.dp)
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    if (cfg.schedulerEnabled) Icons.Default.Schedule else Icons.Default.PauseCircle,
                    contentDescription = null,
                    tint = tint,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    "NEC scheduled push",
                    fontWeight = FontWeight.SemiBold,
                    style = MaterialTheme.typography.bodyMedium
                )
                Spacer(Modifier.weight(1f))
                Text(
                    if (cfg.schedulerEnabled) cfg.schedulerCron.ifBlank { "—" } else "Paused",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Badge(label, tint)
                Spacer(Modifier.width(8.dp))
                if (cfg.schedulerLastRunAt.isNotBlank()) {
                    Text(
                        cfg.schedulerLastRunAt,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(Modifier.width(8.dp))
                }
                if (cfg.schedulerLastRunFiles > 0) {
                    Text(
                        "${cfg.schedulerLastRunFiles} file(s) · ${cfg.schedulerLastRunBytes} bytes",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            if (cfg.schedulerLastRunMessage.isNotBlank()) {
                Text(
                    cfg.schedulerLastRunMessage,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2
                )
            }
        }
    }
}

@Composable
private fun Placeholder(text: String, icon: androidx.compose.ui.graphics.vector.ImageVector) {
    ElevatedCard(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(10.dp)) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text(text, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun Badge(text: String, tint: Color) {
    Surface(color = tint.copy(alpha = 0.15f), shape = RoundedCornerShape(4.dp)) {
        Text(
            text,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
            style = MaterialTheme.typography.labelSmall,
            color = tint,
            fontWeight = FontWeight.Bold
        )
    }
}

private fun statusTintAndLabel(status: String): Pair<Color, String> = when (status.lowercase()) {
    "ok", "success" -> Color(0xFF1E8A44) to status
    "error", "failed" -> Color(0xFFC62828) to status
    "running" -> Color(0xFFE65100) to status
    else -> Color(0xFF757575) to status.ifBlank { "no runs yet" }
}

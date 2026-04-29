package com.retailmanagement.ui.staff

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.firebase.auth.FirebaseAuth
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.EmployeeProfileRead
import com.retailmanagement.data.model.UserRead
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private fun emailToUsername(value: String?): String {
    if (value.isNullOrBlank()) return "–"
    return value.substringBefore("@")
}

class ProfileViewModel : ViewModel() {
    private val _user = MutableStateFlow<UserRead?>(null)
    val user = _user.asStateFlow()
    private val _profile = MutableStateFlow<EmployeeProfileRead?>(null)
    val profile = _profile.asStateFlow()
    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()
    private val _sessions = MutableStateFlow<List<com.retailmanagement.data.model.SessionRead>>(emptyList())
    val sessions = _sessions.asStateFlow()
    private val _sessionsBusy = MutableStateFlow(false)
    val sessionsBusy = _sessionsBusy.asStateFlow()
    private val _sessionsMessage = MutableStateFlow<String?>(null)
    val sessionsMessage = _sessionsMessage.asStateFlow()
    private val _sessionsError = MutableStateFlow<String?>(null)
    val sessionsError = _sessionsError.asStateFlow()

    fun load(userId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            try {
                _user.value = RetrofitClient.api.getMe().data
                try {
                    _profile.value = RetrofitClient.api.getEmployeeProfile(userId).data
                } catch (_: Exception) { /* profile may not exist */ }
                try {
                    _sessions.value = RetrofitClient.api.listMySessions().data
                } catch (_: Exception) { /* sessions endpoint may not be reachable yet */ }
            } catch (_: Exception) { /* ignore */ }
            finally { _isLoading.value = false }
        }
    }

    fun signOutOthers() {
        viewModelScope.launch {
            _sessionsBusy.value = true
            _sessionsMessage.value = null
            _sessionsError.value = null
            try {
                val res = RetrofitClient.api.signOutOtherDevices()
                _sessionsMessage.value = res.message ?: "Other devices signed out."
            } catch (e: Exception) {
                _sessionsError.value = e.localizedMessage ?: "Could not sign out other devices."
            } finally {
                _sessionsBusy.value = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    userId: String,
    onLogout: () -> Unit,
    onOpenCagSettings: (() -> Unit)? = null,
    vm: ProfileViewModel = viewModel()
) {
    val user by vm.user.collectAsState()
    val profile by vm.profile.collectAsState()
    val isLoading by vm.isLoading.collectAsState()
    LaunchedEffect(userId) { vm.load(userId) }

    if (isLoading) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }

    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        // Personal Info
        item {
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Person, null, Modifier.size(40.dp), tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(12.dp))
                        Column {
                            Text(user?.fullName ?: "–", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                            Text(emailToUsername(user?.email), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    if (user?.phone != null) {
                        Spacer(Modifier.height(8.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Phone, null, Modifier.size(16.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(user!!.phone!!, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    // Store roles
                    user?.storeRoles?.let { roles ->
                        if (roles.isNotEmpty()) {
                            Spacer(Modifier.height(8.dp))
                            roles.forEach { role ->
                                AssistChip(onClick = {}, label = { Text(role.role.replaceFirstChar { it.uppercase() }) })
                            }
                        }
                    }
                }
            }
        }

        // Employment Details
        if (profile != null) {
            item {
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Work, null, tint = MaterialTheme.colorScheme.tertiary)
                            Spacer(Modifier.width(8.dp))
                            Text("Employment Details", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        }
                        Spacer(Modifier.height(12.dp))
                        ProfileRow("Nationality", profile!!.nationality.replaceFirstChar { it.uppercase() })
                        ProfileRow("Start Date", profile!!.startDate)
                        profile!!.endDate?.let { ProfileRow("End Date", it) }
                        ProfileRow("Basic Salary", "$${String.format("%.2f", profile!!.basicSalary)}")
                        profile!!.hourlyRate?.let { ProfileRow("Hourly Rate", "$${String.format("%.2f", it)}") }
                        profile!!.commissionRate?.let { ProfileRow("Commission", "${String.format("%.1f", it)}%") }
                        ProfileRow("Bank", profile!!.bankName)
                        ProfileRow("Status", if (profile!!.isActive) "Active" else "Inactive")
                    }
                }
            }
        }

        // Active devices
        item { SessionsCard(vm) }

        if (onOpenCagSettings != null) {
            item {
                Spacer(Modifier.height(8.dp))
                OutlinedButton(
                    onClick = onOpenCagSettings,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Icon(Icons.Default.SettingsInputAntenna, null)
                    Spacer(Modifier.width(8.dp))
                    Text("NEC CAG Integration")
                }
            }
        }

        // Logout
        item {
            Spacer(Modifier.height(16.dp))
            OutlinedButton(
                onClick = {
                    FirebaseAuth.getInstance().signOut()
                    onLogout()
                },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)
            ) {
                Icon(Icons.AutoMirrored.Filled.Logout, null)
                Spacer(Modifier.width(8.dp))
                Text("Sign Out")
            }
        }
        item { Spacer(Modifier.height(80.dp)) }
    }
}

@Composable
private fun ProfileRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun SessionsCard(vm: ProfileViewModel) {
    val sessions by vm.sessions.collectAsState()
    val busy by vm.sessionsBusy.collectAsState()
    val message by vm.sessionsMessage.collectAsState()
    val errorMessage by vm.sessionsError.collectAsState()
    var confirmOpen by remember { mutableStateOf(false) }

    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Devices, null)
                Spacer(Modifier.width(8.dp))
                Text("Active devices", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(8.dp))
            message?.let { Text(it, color = Color(0xFF1E8A44), style = MaterialTheme.typography.bodySmall) }
            errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            if (sessions.isEmpty()) {
                Text("No recorded sessions yet.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall)
            } else {
                sessions.forEach { s ->
                    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                        Text(prettyUserAgent(s.userAgent), fontWeight = FontWeight.SemiBold)
                        Text("${s.ip ?: "unknown network"} · seen ${s.count}\u00d7",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("Last ${s.lastSeen ?: "—"}",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = { confirmOpen = true },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)
            ) {
                if (busy) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                else Text("Sign out other devices")
            }
        }
    }

    if (confirmOpen) {
        AlertDialog(
            onDismissRequest = { confirmOpen = false },
            title = { Text("Sign out other devices?") },
            text = { Text("This revokes refresh tokens on every device. You may also need to sign in again within the hour.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmOpen = false
                    vm.signOutOthers()
                }) { Text("Sign out", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { confirmOpen = false }) { Text("Cancel") } }
        )
    }
}

private fun prettyUserAgent(ua: String?): String {
    if (ua.isNullOrBlank()) return "Unknown device"
    return when {
        "iPhone" in ua -> "iPhone"
        "iPad" in ua -> "iPad"
        "Macintosh" in ua -> "Mac"
        "Android" in ua -> "Android"
        "Chrome" in ua -> "Chrome browser"
        "Safari" in ua -> "Safari browser"
        else -> ua.take(40)
    }
}

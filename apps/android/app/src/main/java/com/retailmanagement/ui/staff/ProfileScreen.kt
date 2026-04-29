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

    fun load(userId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            try {
                _user.value = RetrofitClient.api.getMe().data
                try {
                    _profile.value = RetrofitClient.api.getEmployeeProfile(userId).data
                } catch (_: Exception) { /* profile may not exist */ }
            } catch (_: Exception) { /* ignore */ }
            finally { _isLoading.value = false }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(userId: String, onLogout: () -> Unit, vm: ProfileViewModel = viewModel()) {
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

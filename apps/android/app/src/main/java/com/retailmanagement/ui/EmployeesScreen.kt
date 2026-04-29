package com.retailmanagement.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
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
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class EmployeesViewModel : ViewModel() {
    private val _employees = MutableStateFlow<List<StoreEmployeeRead>>(emptyList())
    val employees = _employees.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()

    // Search / Invite State
    private val _searchResults = MutableStateFlow<List<SearchedUser>>(emptyList())
    val searchResults = _searchResults.asStateFlow()
    
    private val _isSearching = MutableStateFlow(false)
    val isSearching = _isSearching.asStateFlow()
    
    private val _actionError = MutableStateFlow<String?>(null)
    val actionError = _actionError.asStateFlow()

    private val _isActionLoading = MutableStateFlow(false)
    val isActionLoading = _isActionLoading.asStateFlow()

    fun loadEmployees(storeId: String) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            try {
                val response = RetrofitClient.api.getStoreEmployees(storeId)
                _employees.value = response.data
            } catch (e: Exception) {
                _error.value = e.message
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun searchUsers(emailPrefix: String) {
        viewModelScope.launch {
            _isSearching.value = true
            _actionError.value = null
            try {
                // The API actually expects the exact email prefix, but let's append our domain logic 
                // or just pass the query. The iOS app translates username to email.
                val email = if (emailPrefix.contains("@")) emailPrefix else "$emailPrefix@victoriaenso.com"
                val response = RetrofitClient.api.searchUsers(email)
                _searchResults.value = response.data
                if (response.data.isEmpty()) {
                    _actionError.value = "No users found"
                }
            } catch (e: Exception) {
                _actionError.value = e.message
            } finally {
                _isSearching.value = false
            }
        }
    }

    fun clearSearch() {
        _searchResults.value = emptyList()
        _actionError.value = null
    }

    fun inviteUser(storeId: String, userId: String, role: String, onSuccess: () -> Unit) {
        viewModelScope.launch {
            _isActionLoading.value = true
            _actionError.value = null
            try {
                RetrofitClient.api.assignUserRole(UserStoreRoleCreate(userId, storeId, role))
                loadEmployees(storeId)
                onSuccess()
            } catch (e: Exception) {
                _actionError.value = e.message
            } finally {
                _isActionLoading.value = false
            }
        }
    }

    fun changeRole(storeId: String, roleId: String, newRole: String) {
        viewModelScope.launch {
            _isActionLoading.value = true
            _actionError.value = null
            try {
                RetrofitClient.api.updateUserRole(roleId, UserStoreRoleUpdate(newRole))
                loadEmployees(storeId)
            } catch (e: Exception) {
                _actionError.value = e.message
            } finally {
                _isActionLoading.value = false
            }
        }
    }

    fun removeEmployee(storeId: String, roleId: String) {
        viewModelScope.launch {
            _isActionLoading.value = true
            _actionError.value = null
            try {
                RetrofitClient.api.removeUserRole(roleId)
                loadEmployees(storeId)
            } catch (e: Exception) {
                _actionError.value = e.message
            } finally {
                _isActionLoading.value = false
            }
        }
    }

    /// Generate a one-time password reset link. Owners only on the backend.
    fun resetPassword(userId: String, onResult: (com.retailmanagement.data.model.AdminResetResult?, String?) -> Unit) {
        viewModelScope.launch {
            _isActionLoading.value = true
            _actionError.value = null
            try {
                val result = RetrofitClient.api.adminResetPassword(userId)
                onResult(result, null)
            } catch (e: Exception) {
                _actionError.value = e.message
                onResult(null, e.message ?: "Reset failed.")
            } finally {
                _isActionLoading.value = false
            }
        }
    }

    /// Disable or re-enable an account.
    fun setDisabled(userId: String, disabled: Boolean, onResult: (String?) -> Unit) {
        viewModelScope.launch {
            _isActionLoading.value = true
            _actionError.value = null
            try {
                val res = if (disabled) RetrofitClient.api.adminDisableUser(userId)
                          else RetrofitClient.api.adminEnableUser(userId)
                onResult(res.message ?: if (disabled) "Account disabled." else "Account re-enabled.")
            } catch (e: Exception) {
                _actionError.value = e.message
                onResult(e.message ?: "Action failed.")
            } finally {
                _isActionLoading.value = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EmployeesScreen(storeId: String, vm: EmployeesViewModel = viewModel()) {
    val employees by vm.employees.collectAsState()
    val isLoading by vm.isLoading.collectAsState()
    val error by vm.error.collectAsState()
    
    var searchQuery by remember { mutableStateOf("") }
    var selectedEmployee by remember { mutableStateOf<StoreEmployeeRead?>(null) }
    var showInviteDialog by remember { mutableStateOf(false) }

    LaunchedEffect(storeId) {
        vm.loadEmployees(storeId)
    }

    val filteredEmployees = if (searchQuery.isEmpty()) {
        employees
    } else {
        employees.filter {
            it.fullName.contains(searchQuery, ignoreCase = true) ||
            it.username.contains(searchQuery, ignoreCase = true)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Employees") },
                actions = {
                    IconButton(onClick = { showInviteDialog = true }) {
                        Icon(Icons.Default.PersonAdd, contentDescription = "Add Employee")
                    }
                }
            )
        }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            OutlinedTextField(
                value = searchQuery,
                onValueChange = { searchQuery = it },
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                placeholder = { Text("Search employees") },
                leadingIcon = { Icon(Icons.Default.Search, null) },
                singleLine = true
            )

            if (isLoading && employees.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            } else if (error != null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(error!!, color = MaterialTheme.colorScheme.error)
                }
            } else if (filteredEmployees.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("No employees found", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(filteredEmployees) { emp ->
                        EmployeeRowItem(emp) {
                            selectedEmployee = emp
                        }
                    }
                }
            }
        }
    }

    if (showInviteDialog) {
        InviteEmployeeDialog(
            storeId = storeId,
            vm = vm,
            onDismiss = { 
                showInviteDialog = false 
                vm.clearSearch()
            }
        )
    }

    selectedEmployee?.let { emp ->
        EmployeeDetailDialog(
            employee = emp,
            storeId = storeId,
            vm = vm,
            onDismiss = { selectedEmployee = null }
        )
    }
}

@Composable
fun EmployeeRowItem(emp: StoreEmployeeRead, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(emp.fullName, fontWeight = FontWeight.Medium) },
        supportingContent = { Text(emp.username) },
        trailingContent = { 
            AssistChip(
                onClick = {}, 
                label = { Text(emp.role.replaceFirstChar { it.uppercase() }) },
                colors = AssistChipDefaults.assistChipColors(
                    containerColor = when(emp.role) {
                        "owner" -> MaterialTheme.colorScheme.primaryContainer
                        "manager" -> MaterialTheme.colorScheme.secondaryContainer
                        else -> MaterialTheme.colorScheme.surfaceVariant
                    }
                )
            )
        },
        leadingContent = {
            Icon(Icons.Default.Person, contentDescription = null, modifier = Modifier.size(40.dp))
        },
        modifier = Modifier.clickable(onClick = onClick)
    )
    androidx.compose.material3.Divider()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InviteEmployeeDialog(storeId: String, vm: EmployeesViewModel, onDismiss: () -> Unit) {
    var searchUsername by remember { mutableStateOf("") }
    var selectedRole by remember { mutableStateOf("staff") }
    
    val searchResults by vm.searchResults.collectAsState()
    val isSearching by vm.isSearching.collectAsState()
    val actionError by vm.actionError.collectAsState()
    val isActionLoading by vm.isActionLoading.collectAsState()

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().padding(16.dp).padding(bottom = 32.dp)) {
            Text("Invite Employee", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(16.dp))
            
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = searchUsername,
                    onValueChange = { searchUsername = it },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("Username") },
                    singleLine = true
                )
                Spacer(Modifier.width(8.dp))
                Button(
                    onClick = { vm.searchUsers(searchUsername) },
                    enabled = searchUsername.length >= 3 && !isSearching
                ) {
                    if (isSearching) {
                        CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(Icons.Default.Search, null)
                    }
                }
            }
            
            if (actionError != null) {
                Text(actionError!!, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
            }
            
            if (searchResults.isNotEmpty()) {
                Spacer(Modifier.height(16.dp))
                Text("Results", style = MaterialTheme.typography.titleMedium)
                LazyColumn(modifier = Modifier.heightIn(max = 200.dp)) {
                    items(searchResults) { user ->
                        ListItem(
                            headlineContent = { Text(user.fullName) },
                            supportingContent = { Text(user.username) },
                            trailingContent = {
                                Button(
                                    onClick = { vm.inviteUser(storeId, user.id, selectedRole) { onDismiss() } },
                                    enabled = !isActionLoading
                                ) {
                                    Text("Invite")
                                }
                            }
                        )
                    }
                }
            }
            
            Spacer(Modifier.height(16.dp))
            Text("Assign Role", style = MaterialTheme.typography.titleMedium)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                listOf("staff", "manager", "owner").forEach { role ->
                    FilterChip(
                        selected = selectedRole == role,
                        onClick = { selectedRole = role },
                        label = { Text(role.replaceFirstChar { it.uppercase() }) }
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EmployeeDetailDialog(employee: StoreEmployeeRead, storeId: String, vm: EmployeesViewModel, onDismiss: () -> Unit) {
    var showRolePicker by remember { mutableStateOf(false) }
    val isActionLoading by vm.isActionLoading.collectAsState()
    
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().padding(16.dp).padding(bottom = 32.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(Icons.Default.AccountCircle, null, Modifier.size(64.dp), tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.height(8.dp))
            Text(employee.fullName, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(employee.role.replaceFirstChar { it.uppercase() }, color = MaterialTheme.colorScheme.secondary)
            
            Spacer(Modifier.height(24.dp))
            
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("Contact", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(4.dp))
                    Text("Username: ${employee.username}", style = MaterialTheme.typography.bodyLarge)
                    if (employee.phone != null) {
                        Text("Phone: ${employee.phone}", style = MaterialTheme.typography.bodyLarge)
                    }
                }
            }
            
            Spacer(Modifier.height(24.dp))
            
            if (showRolePicker) {
                Text("Select New Role", style = MaterialTheme.typography.titleMedium)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                    listOf("staff", "manager", "owner").filter { it != employee.role }.forEach { role ->
                        Button(
                            onClick = { 
                                vm.changeRole(storeId, employee.roleId, role)
                                onDismiss()
                            },
                            enabled = !isActionLoading
                        ) {
                            Text(role.replaceFirstChar { it.uppercase() })
                        }
                    }
                }
            } else {
                Button(
                    onClick = { showRolePicker = true },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !isActionLoading
                ) {
                    Icon(Icons.Default.VpnKey, null)
                    Spacer(Modifier.width(8.dp))
                    Text("Change Role")
                }
            }
            
            Spacer(Modifier.height(8.dp))

            // Reset password (owner action). Surfaces the one-time link inline
            // because we don't have a clipboard helper here yet — owner can
            // long-press to copy, matching staff-portal behaviour.
            var lastResetLink by remember { mutableStateOf<String?>(null) }
            var lastResetMessage by remember { mutableStateOf<String?>(null) }
            var lastDisableMessage by remember { mutableStateOf<String?>(null) }

            OutlinedButton(
                onClick = {
                    vm.resetPassword(employee.id) { result, _ ->
                        lastResetLink = result?.resetLink
                        lastResetMessage = result?.message
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = !isActionLoading
            ) {
                Icon(Icons.Default.VpnKey, null)
                Spacer(Modifier.width(8.dp))
                Text("Reset password")
            }
            lastResetLink?.let {
                Spacer(Modifier.height(8.dp))
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("One-time reset link", style = MaterialTheme.typography.labelMedium)
                        Text(it, style = MaterialTheme.typography.bodySmall)
                        lastResetMessage?.let { m -> Text(m, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                }
            }

            Spacer(Modifier.height(8.dp))

            OutlinedButton(
                onClick = {
                    vm.setDisabled(employee.id, disabled = true) { msg ->
                        lastDisableMessage = msg
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                enabled = !isActionLoading
            ) {
                Icon(Icons.Default.Block, null)
                Spacer(Modifier.width(8.dp))
                Text("Disable account")
            }
            lastDisableMessage?.let {
                Text(it, style = MaterialTheme.typography.labelSmall, color = Color(0xFF1E8A44), modifier = Modifier.padding(top = 4.dp))
            }

            Spacer(Modifier.height(8.dp))

            OutlinedButton(
                onClick = {
                    vm.removeEmployee(storeId, employee.roleId)
                    onDismiss()
                },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                enabled = !isActionLoading
            ) {
                Icon(Icons.Default.PersonRemove, null)
                Spacer(Modifier.width(8.dp))
                Text("Remove from Store")
            }
        }
    }
}

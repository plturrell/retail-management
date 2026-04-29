package com.retailmanagement.ui.staff

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ListAlt
import androidx.compose.material.icons.automirrored.filled.TrendingUp
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.google.firebase.auth.FirebaseAuth
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.ui.InventoryScreen
import com.retailmanagement.ui.MasterDataScreen
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed class StaffTab(val route: String, val label: String, val icon: ImageVector) {
    object Schedule : StaffTab("schedule", "Schedule", Icons.Default.CalendarMonth)
    object Timesheet : StaffTab("timesheet", "Timesheet", Icons.Default.Timer)
    object Pay : StaffTab("pay", "Pay", Icons.Default.Payments)
    object Commission : StaffTab("commission", "Commission", Icons.Default.Percent)
    object Performance : StaffTab("performance", "Performance", Icons.AutoMirrored.Filled.TrendingUp)
    object Inventory : StaffTab("inventory", "Inventory", Icons.Default.Inventory2)
    object MasterData : StaffTab("master-data", "Master Data", Icons.AutoMirrored.Filled.ListAlt)
    object Employees : StaffTab("employees", "Employees", Icons.Default.People)
    object TeamSchedule : StaffTab("team-schedule", "Team Sched", Icons.Default.EditCalendar)
    object TimesheetApprovals : StaffTab("timesheet-approvals", "Approvals", Icons.Default.AssignmentTurnedIn)
    object Orders : StaffTab("orders", "Orders", Icons.Default.ShoppingCart)
    object Financials : StaffTab("financials", "Financials", Icons.Default.BarChart)
    object Profile : StaffTab("profile", "Profile", Icons.Default.Person)
}

private val staffTabs = listOf(StaffTab.Schedule, StaffTab.Timesheet, StaffTab.Pay, StaffTab.Commission, StaffTab.Performance, StaffTab.Profile)

// Mirrors backend allowlist (settings.MASTER_DATA_PUBLISHER_EMAILS in
// backend/app/config.py). Server is the source of truth — non-allowlisted
// users get 403 from /publish_price even if this client copy drifts.
private val MASTER_DATA_PUBLISHER_ALLOWLIST: Set<String> = setOf(
    "craig@victoriaenso.com",
    "irina@victoriaenso.com"
)

class StaffAppViewModel : ViewModel() {
    private val _userId = MutableStateFlow<String?>(null)
    val userId = _userId.asStateFlow()
    private val _storeId = MutableStateFlow<String?>(null)
    val storeId = _storeId.asStateFlow()
    private val _role = MutableStateFlow("staff")
    val role = _role.asStateFlow()
    private val _isLoggedIn = MutableStateFlow(FirebaseAuth.getInstance().currentUser != null)
    val isLoggedIn = _isLoggedIn.asStateFlow()
    // Mirrors the staff-portal web behaviour: every gated screen redirects to
    // ForceChangePasswordScreen until the user rotates their password and the
    // backend clears the must_change_password custom claim.
    private val _mustChangePassword = MutableStateFlow(false)
    val mustChangePassword = _mustChangePassword.asStateFlow()

    fun onLoginSuccess() {
        _isLoggedIn.value = true
        loadUserContext()
    }

    fun onLogout() {
        _isLoggedIn.value = false
        _userId.value = null
        _storeId.value = null
        _role.value = "staff"
        _mustChangePassword.value = false
    }

    fun loadUserContext() {
        viewModelScope.launch {
            refreshClaims()
            try {
                val me = RetrofitClient.api.getMe().data
                _userId.value = me.id
                val firstRole = me.storeRoles?.firstOrNull()
                _storeId.value = firstRole?.storeId
                _role.value = firstRole?.role ?: "staff"
            } catch (_: Exception) { /* will retry on screen load */ }
        }
    }

    fun refreshClaims() {
        val user = FirebaseAuth.getInstance().currentUser ?: run {
            _mustChangePassword.value = false
            return
        }
        user.getIdToken(true).addOnSuccessListener { result ->
            _mustChangePassword.value = (result.claims["must_change_password"] as? Boolean) == true
        }.addOnFailureListener {
            _mustChangePassword.value = false
        }
    }

    init {
        if (_isLoggedIn.value) loadUserContext()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StaffApp(vm: StaffAppViewModel = viewModel()) {
    val isLoggedIn by vm.isLoggedIn.collectAsState()
    val userId by vm.userId.collectAsState()
    val storeId by vm.storeId.collectAsState()
    val role by vm.role.collectAsState()

    if (!isLoggedIn) {
        LoginScreen(onLoginSuccess = { vm.onLoginSuccess() })
        return
    }

    val mustChangePassword by vm.mustChangePassword.collectAsState()
    if (mustChangePassword) {
        ForceChangePasswordScreen(
            onPasswordChanged = { vm.refreshClaims() },
            onSignOut = {
                FirebaseAuth.getInstance().signOut()
                vm.onLogout()
            }
        )
        return
    }

    val navController = rememberNavController()
    val currentEntry by navController.currentBackStackEntryAsState()
    val currentRoute = currentEntry?.destination?.route
    val visibleTabs = remember(role) {
        when (role) {
            "owner" -> listOf(
                StaffTab.Schedule,
                StaffTab.Timesheet,
                StaffTab.Pay,
                StaffTab.Performance,
                StaffTab.TeamSchedule,
                StaffTab.TimesheetApprovals,
                StaffTab.Orders,
                StaffTab.Financials,
                StaffTab.Inventory,
                StaffTab.MasterData,
                StaffTab.Employees,
                StaffTab.Profile
            )
            "manager" -> listOf(
                StaffTab.Schedule,
                StaffTab.Timesheet,
                StaffTab.Pay,
                StaffTab.Performance,
                StaffTab.TeamSchedule,
                StaffTab.TimesheetApprovals,
                StaffTab.Orders,
                StaffTab.Financials,
                StaffTab.Inventory,
                StaffTab.Employees,
                StaffTab.Profile
            )
            else -> staffTabs
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(visibleTabs.find { it.route == currentRoute }?.label ?: "VictoriaEnso") },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                    titleContentColor = MaterialTheme.colorScheme.onPrimaryContainer
                )
            )
        },
        bottomBar = {
            NavigationBar {
                visibleTabs.forEach { tab ->
                    NavigationBarItem(
                        selected = currentRoute == tab.route,
                        onClick = {
                            if (currentRoute != tab.route) {
                                navController.navigate(tab.route) {
                                    popUpTo(navController.graph.startDestinationId) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            }
                        },
                        icon = { Icon(tab.icon, contentDescription = tab.label) },
                        label = { Text(tab.label) }
                    )
                }
            }
        }
    ) { padding ->
        val sid = storeId ?: ""
        val uid = userId ?: ""
        val email = FirebaseAuth.getInstance().currentUser?.email?.lowercase()
        val canPublishPrice = role == "owner" && email != null && email in MASTER_DATA_PUBLISHER_ALLOWLIST

        NavHost(navController, startDestination = StaffTab.Schedule.route, Modifier.padding(padding)) {
            composable(StaffTab.Schedule.route) { ScheduleScreen(storeId = sid) }
            composable(StaffTab.Timesheet.route) { TimesheetScreen(storeId = sid, userId = uid) }
            composable(StaffTab.Pay.route) { PayScreen(storeId = sid, userId = uid) }
            composable(StaffTab.Commission.route) { CommissionScreen(storeId = sid, userId = uid) }
            composable(StaffTab.Performance.route) { PerformanceScreen(storeId = sid, userId = uid) }
            composable(StaffTab.Inventory.route) { InventoryScreen(storeId = sid) }
            composable(StaffTab.MasterData.route) {
                MasterDataScreen(canEdit = role == "owner", canPublishPrice = canPublishPrice)
            }
            composable(StaffTab.Employees.route) { com.retailmanagement.ui.EmployeesScreen(storeId = sid) }
            composable(StaffTab.TeamSchedule.route) { com.retailmanagement.ui.ManagerScheduleScreen(storeId = sid) }
            composable(StaffTab.TimesheetApprovals.route) { com.retailmanagement.ui.ManagerTimesheetsScreen(storeId = sid) }
            composable(StaffTab.Orders.route) { com.retailmanagement.ui.ManagerOrdersScreen(storeId = sid) }
            composable(StaffTab.Financials.route) { com.retailmanagement.ui.FinancialsScreen(storeId = sid) }
            composable(StaffTab.Profile.route) {
                ProfileScreen(
                    userId = uid,
                    onLogout = { vm.onLogout() },
                    onOpenCagSettings = if (role == "owner") {
                        { navController.navigate("cag-settings") }
                    } else null
                )
            }
            composable("cag-settings") {
                CagSettingsScreen(onBack = { navController.popBackStack() })
            }
        }
    }
}

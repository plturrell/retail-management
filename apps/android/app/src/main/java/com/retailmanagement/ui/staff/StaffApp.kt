package com.retailmanagement.ui.staff

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
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
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed class StaffTab(val route: String, val label: String, val icon: ImageVector) {
    object Schedule : StaffTab("schedule", "Schedule", Icons.Default.CalendarMonth)
    object Timesheet : StaffTab("timesheet", "Timesheet", Icons.Default.Timer)
    object Pay : StaffTab("pay", "Pay", Icons.Default.Payments)
    object Performance : StaffTab("performance", "Performance", Icons.Default.TrendingUp)
    object Profile : StaffTab("profile", "Profile", Icons.Default.Person)
}

private val tabs = listOf(StaffTab.Schedule, StaffTab.Timesheet, StaffTab.Pay, StaffTab.Performance, StaffTab.Profile)

class StaffAppViewModel : ViewModel() {
    private val _userId = MutableStateFlow<String?>(null)
    val userId = _userId.asStateFlow()
    private val _storeId = MutableStateFlow<String?>(null)
    val storeId = _storeId.asStateFlow()
    private val _isLoggedIn = MutableStateFlow(FirebaseAuth.getInstance().currentUser != null)
    val isLoggedIn = _isLoggedIn.asStateFlow()

    fun onLoginSuccess() {
        _isLoggedIn.value = true
        loadUserContext()
    }

    fun onLogout() {
        _isLoggedIn.value = false
        _userId.value = null
        _storeId.value = null
    }

    fun loadUserContext() {
        viewModelScope.launch {
            try {
                val me = RetrofitClient.api.getMe().data
                _userId.value = me.id
                _storeId.value = me.storeRoles?.firstOrNull()?.storeId
            } catch (_: Exception) { /* will retry on screen load */ }
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

    if (!isLoggedIn) {
        LoginScreen(onLoginSuccess = { vm.onLoginSuccess() })
        return
    }

    val navController = rememberNavController()
    val currentEntry by navController.currentBackStackEntryAsState()
    val currentRoute = currentEntry?.destination?.route

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(tabs.find { it.route == currentRoute }?.label ?: "RetailSG") },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                    titleContentColor = MaterialTheme.colorScheme.onPrimaryContainer
                )
            )
        },
        bottomBar = {
            NavigationBar {
                tabs.forEach { tab ->
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

        NavHost(navController, startDestination = StaffTab.Schedule.route, Modifier.padding(padding)) {
            composable(StaffTab.Schedule.route) { ScheduleScreen(storeId = sid) }
            composable(StaffTab.Timesheet.route) { TimesheetScreen(storeId = sid, userId = uid) }
            composable(StaffTab.Pay.route) { PayScreen(storeId = sid, userId = uid) }
            composable(StaffTab.Performance.route) { PerformanceScreen(storeId = sid, userId = uid) }
            composable(StaffTab.Profile.route) { ProfileScreen(userId = uid, onLogout = { vm.onLogout() }) }
        }
    }
}

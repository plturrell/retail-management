package com.retailmanagement.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.*

@Composable
fun RetailApp() {
    val navController = rememberNavController()
    
    Scaffold(
        bottomBar = { RetailBottomNav(navController) }
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = "dashboard",
            modifier = Modifier.padding(innerPadding)
        ) {
            composable("dashboard") { DashboardScreen() }
            composable("inventory") { InventoryScreen() }
            composable("financials") { FinancialsScreen() }
            composable("orders") { OrdersScreen() }
            composable("employees") { EmployeesScreen() }
            
            // Owner Supply Chain Routes
            composable("owner_master_data") { MasterDataScreen(canEdit = true) }
            composable("owner_ops") { com.retailmanagement.ui.owner.OwnerOpsScreen() }
        }
    }
}

@Composable
fun RetailBottomNav(navController: NavHostController) {
    // Navigation bar implementation matching iOS MainTabView
}

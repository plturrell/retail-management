package com.retailmanagement.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.*
import com.google.firebase.auth.FirebaseAuth

// Mirrors backend allowlist (settings.MASTER_DATA_PUBLISHER_EMAILS in
// backend/app/config.py). Server is the source of truth — non-allowlisted
// users get 403 from /publish_price even if this client copy drifts.
private val MASTER_DATA_PUBLISHER_ALLOWLIST: Set<String> = setOf(
    "craig@victoriaenso.com",
    "irina@victoriaenso.com"
)

@Composable
fun RetailApp() {
    val navController = rememberNavController()
    val currentEmail = FirebaseAuth.getInstance().currentUser?.email?.lowercase()
    val canPublishPrice = currentEmail != null && currentEmail in MASTER_DATA_PUBLISHER_ALLOWLIST

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
            composable("employees") { EmployeesScreen(storeId = "") }

            // Owner Supply Chain Routes
            composable("owner_master_data") {
                MasterDataScreen(canEdit = true, canPublishPrice = canPublishPrice)
            }
            composable("vendor_review") { com.retailmanagement.ui.owner.VendorReviewScreen() }
        }
    }
}

@Suppress("UNUSED_PARAMETER")
@Composable
fun RetailBottomNav(navController: NavHostController) {
    // Navigation bar implementation matching iOS MainTabView
}

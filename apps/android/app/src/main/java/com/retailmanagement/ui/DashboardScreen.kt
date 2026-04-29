package com.retailmanagement.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun DashboardScreen() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Retail Dashboard")
    }
}

@Composable
fun FinancialsScreen() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Financials")
    }
}

@Composable
fun OrdersScreen() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Orders & Fulfillment")
    }
}


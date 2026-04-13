package com.retailmanagement.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun InventoryScreen() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Inventory Management")
        // TODO: Integrate Google ML Kit CameraX Preview for Barcode/OCR scanning
        // TODO: Integrate Google Gemini SDK for automatic image categorization
    }
}

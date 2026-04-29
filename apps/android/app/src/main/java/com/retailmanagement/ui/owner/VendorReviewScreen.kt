package com.retailmanagement.ui.owner

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.ImageLoader
import coil.compose.AsyncImage
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.owner.ReviewLineStatus
import com.retailmanagement.data.owner.VendorReviewLineItem

@Composable
fun VendorReviewScreen(vm: VendorReviewViewModel = viewModel()) {
    val order by vm.order.collectAsState()
    val workspace by vm.workspace.collectAsState()
    val isLoading by vm.isLoading.collectAsState()
    val error by vm.error.collectAsState()

    var selectedLineKey by remember { mutableStateOf<String?>("1") }

    LaunchedEffect(Unit) {
        vm.loadOrder()
    }

    if (isLoading) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
        return
    }

    if (error != null) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("Error: $error", color = MaterialTheme.colorScheme.error)
        }
        return
    }

    val currentOrder = order ?: return

    val context = LocalContext.current
    val imageLoader = remember {
        ImageLoader.Builder(context)
            .okHttpClient(RetrofitClient.okHttpClient)
            .build()
    }
    val invoiceImageUrl = remember(currentOrder) {
        val artifact = currentOrder.sourceArtifacts.firstOrNull { it.type == "scan_image" }
            ?: currentOrder.sourceArtifacts.firstOrNull()
        artifact?.file?.let { rel ->
            val base = RetrofitClient.baseUrl.trimEnd('/')
            "$base/api/supplier-review/${currentOrder.supplierId}/artifacts/$rel"
        }
    }

    Column(Modifier.fillMaxSize()) {
        // Top Half: Image Viewer (simplified for demo)
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(0.4f)
                .background(Color.DarkGray),
            contentAlignment = Alignment.Center
        ) {
            if (invoiceImageUrl != null) {
                AsyncImage(
                    model = invoiceImageUrl,
                    imageLoader = imageLoader,
                    contentDescription = "Invoice",
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxSize()
                )
            } else {
                Text("No invoice scan attached.", color = Color.White)
            }
            // Note: In a fully productionized version, we would implement an interactive
            // Transformable canvas here that translates the 1056x4026 native coordinates
            // into the scaled screen coordinates.
            Text("Crop Regions highlighted natively in iOS. Android canvas omitted for brevity.", color = Color.White, modifier = Modifier.align(Alignment.BottomCenter).padding(8.dp))
        }
        
        androidx.compose.material3.Divider()

        // Bottom Half: Reconciliation List
        LazyColumn(
            modifier = Modifier
                .fillMaxWidth()
                .weight(0.6f)
        ) {
            items(currentOrder.lineItems) { line ->
                val key = line.sourceLineNumber.toString()
                val isSelected = selectedLineKey == key
                val orderState = workspace.orders[currentOrder.orderNumber]
                val lineState = orderState?.lines?.get(key)
                
                val status = lineState?.status ?: ReviewLineStatus.UNREVIEWED

                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp)
                        .clickable { selectedLineKey = key },
                    colors = CardDefaults.cardColors(
                        containerColor = if (isSelected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface
                    ),
                    elevation = CardDefaults.cardElevation(defaultElevation = if (isSelected) 4.dp else 1.dp)
                ) {
                    Column(Modifier.padding(16.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Line ${line.sourceLineNumber}", style = MaterialTheme.typography.labelMedium)
                            Text("¥${line.lineTotalCny ?: 0}", style = MaterialTheme.typography.titleMedium)
                        }
                        Spacer(Modifier.height(4.dp))
                        Text(line.displayName ?: line.materialDescription ?: "Unknown Item", style = MaterialTheme.typography.bodyLarge)
                        
                        Spacer(Modifier.height(8.dp))
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "SKU: ${line.supplierItemCode ?: "UNMAPPED"}",
                                color = if (line.supplierItemCode == null) MaterialTheme.colorScheme.error else Color(0xFF388E3C),
                                style = MaterialTheme.typography.labelLarge
                            )
                            
                            // Status Picker (Simplified to a text button cycling statuses)
                            TextButton(onClick = {
                                val nextStatus = when (status) {
                                    ReviewLineStatus.UNREVIEWED -> ReviewLineStatus.VERIFIED
                                    ReviewLineStatus.VERIFIED -> ReviewLineStatus.NEEDS_FOLLOW_UP
                                    ReviewLineStatus.NEEDS_FOLLOW_UP -> ReviewLineStatus.UNREVIEWED
                                }
                                vm.updateLineStatus(currentOrder.orderNumber, key, nextStatus, "")
                            }) {
                                Text(status.name)
                            }
                        }
                    }
                }
            }
        }
    }
}

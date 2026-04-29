package com.retailmanagement.ui.staff

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.google.firebase.auth.EmailAuthProvider
import com.google.firebase.auth.FirebaseAuth
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.ChangePasswordRequest
import kotlinx.coroutines.launch

/**
 * Renders when the signed-in user carries the Firebase custom claim
 * `must_change_password=true`. Mirrors the staff-portal web
 * `ForceChangePasswordPage` and the iOS `ForceChangePasswordView` — the user
 * must reauthenticate with their current password and rotate to a new one
 * before the main bottom-tab UI becomes reachable again.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ForceChangePasswordScreen(
    onPasswordChanged: () -> Unit,
    onSignOut: () -> Unit
) {
    var current by remember { mutableStateOf("") }
    var next by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Icon(
                Icons.Default.Lock,
                contentDescription = null,
                modifier = Modifier.size(48.dp),
                tint = MaterialTheme.colorScheme.primary
            )
            Spacer(Modifier.height(12.dp))
            Text(
                "Update your password",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold
            )
            Spacer(Modifier.height(8.dp))
            Text(
                "An administrator reset your password. Choose a new one to continue.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center
            )

            Spacer(Modifier.height(24.dp))

            OutlinedTextField(
                value = current,
                onValueChange = { current = it },
                label = { Text("Current password") },
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = next,
                onValueChange = { next = it },
                label = { Text("New password (\u226510 characters)") },
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = confirm,
                onValueChange = { confirm = it },
                label = { Text("Confirm new password") },
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth()
            )

            errorMessage?.let {
                Spacer(Modifier.height(12.dp))
                Text(it, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center)
            }

            Spacer(Modifier.height(24.dp))

            Button(
                onClick = {
                    errorMessage = null
                    when {
                        next.length < 10 ->
                            errorMessage = "New password must be at least 10 characters."
                        next != confirm ->
                            errorMessage = "New password and confirmation do not match."
                        else -> {
                            val user = FirebaseAuth.getInstance().currentUser
                            val email = user?.email
                            if (user == null || email.isNullOrBlank()) {
                                errorMessage = "Not signed in."
                            } else {
                                isLoading = true
                                val cred = EmailAuthProvider.getCredential(email, current)
                                user.reauthenticate(cred)
                                .addOnSuccessListener {
                                    scope.launch {
                                        try {
                                            RetrofitClient.api.changePassword(ChangePasswordRequest(next))
                                            onPasswordChanged()
                                        } catch (e: Exception) {
                                            errorMessage = e.localizedMessage
                                                ?: "Could not update password."
                                        } finally {
                                            isLoading = false
                                        }
                                    }
                                }
                                    .addOnFailureListener { e ->
                                        isLoading = false
                                        val raw = e.localizedMessage.orEmpty()
                                        errorMessage = when {
                                            raw.contains("wrong-password", true) ||
                                                raw.contains("invalid-credential", true) ->
                                                "Current password is incorrect."
                                            raw.contains("too-many-requests", true) ->
                                                "Too many attempts \u2014 wait a few minutes and try again."
                                            else -> raw.ifBlank { "Could not verify current password." }
                                        }
                                    }
                            }
                        }
                    }
                },
                enabled = !isLoading && current.isNotBlank() && next.isNotBlank() && confirm.isNotBlank(),
                modifier = Modifier.fillMaxWidth().height(50.dp)
            ) {
                if (isLoading) CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    color = MaterialTheme.colorScheme.onPrimary,
                    strokeWidth = 2.dp
                ) else Text("Update password")
            }

            Spacer(Modifier.height(8.dp))
            TextButton(onClick = onSignOut) { Text("Sign out") }
        }
    }
}

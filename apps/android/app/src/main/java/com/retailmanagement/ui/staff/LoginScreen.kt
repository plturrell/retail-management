package com.retailmanagement.ui.staff

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.firebase.auth.FirebaseAuth
import com.retailmanagement.R
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.AuthReport
import com.retailmanagement.data.model.LockoutReport
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await

private const val DEFAULT_AUTH_EMAIL_DOMAIN = "victoriaenso.com"
private val LoginBlue = Color(0xFF0A63F6)
private val LoginText = Color(0xFF020617)
private val LoginMuted = Color(0xFF64748B)
private val LoginBorder = Color(0xFFCBD5E1)

private fun usernameToAuthEmail(value: String): String {
    val identifier = value.trim().lowercase()
    return if (identifier.isBlank() || identifier.contains("@")) identifier else "$identifier@$DEFAULT_AUTH_EMAIL_DOMAIN"
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(onLoginSuccess: () -> Unit) {
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var passwordVisible by remember { mutableStateOf(false) }
    var isLoading by remember { mutableStateOf(false) }
    var isResettingPassword by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var infoMessage by remember { mutableStateOf<String?>(null) }

    val auth = FirebaseAuth.getInstance()
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        if (auth.currentUser != null) {
            onLoginSuccess()
        }
    }

    Scaffold(containerColor = Color.Transparent) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(
                    Brush.verticalGradient(
                        colors = listOf(
                            Color(0xFFFBFDFF),
                            Color(0xFFF6F9FC),
                            Color(0xFFEEF6F4)
                        )
                    )
                )
        ) {
            Box(
                modifier = Modifier
                    .align(Alignment.Center)
                    .offset(y = 16.dp)
                    .width(620.dp)
                    .height(310.dp)
                    .background(Color.White.copy(alpha = 0.12f), RoundedCornerShape(percent = 50))
                    .border(1.dp, Color.White.copy(alpha = 0.70f), RoundedCornerShape(percent = 50))
            )

            Box(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .height(160.dp)
                    .background(
                        Brush.verticalGradient(
                            colors = listOf(Color.Transparent, Color(0x3DD8E7E3))
                        )
                    )
            )

            Box(
                modifier = Modifier
                    .align(Alignment.Center)
                    .offset(y = (-28).dp)
                    .fillMaxWidth()
                    .padding(horizontal = 32.dp),
                contentAlignment = Alignment.Center
            ) {
                Column(
                    modifier = Modifier.widthIn(max = 350.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    BrandHeader()

                    Spacer(modifier = Modifier.height(36.dp))

                    OutlinedTextField(
                        value = username,
                        onValueChange = {
                            username = it
                            errorMessage = null
                            infoMessage = null
                        },
                        placeholder = { Text("Username") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
                        singleLine = true,
                        shape = RoundedCornerShape(17.dp),
                        colors = loginFieldColors(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 52.dp)
                            .shadow(26.dp, RoundedCornerShape(17.dp), clip = false)
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    OutlinedTextField(
                        value = password,
                        onValueChange = {
                            password = it
                            errorMessage = null
                            infoMessage = null
                        },
                        placeholder = { Text("Password") },
                        trailingIcon = {
                            IconButton(onClick = { passwordVisible = !passwordVisible }) {
                                Icon(
                                    if (passwordVisible) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                    contentDescription = if (passwordVisible) "Hide password" else "Show password",
                                    tint = LoginMuted
                                )
                            }
                        },
                        visualTransformation = if (passwordVisible) VisualTransformation.None else PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        singleLine = true,
                        shape = RoundedCornerShape(17.dp),
                        colors = loginFieldColors(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 52.dp)
                            .shadow(26.dp, RoundedCornerShape(17.dp), clip = false)
                    )

                    if (errorMessage != null) {
                        Spacer(modifier = Modifier.height(10.dp))
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(16.dp),
                            color = Color(0xFFFEF2F2),
                            border = BorderStroke(1.dp, Color(0xFFFECACA))
                        ) {
                            Text(
                                text = errorMessage!!,
                                color = Color(0xFFB91C1C),
                                style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp)
                            )
                        }
                    }
                    if (infoMessage != null) {
                        Spacer(modifier = Modifier.height(10.dp))
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(16.dp),
                            color = Color(0xFFF0FDF4),
                            border = BorderStroke(1.dp, Color(0xFFBBF7D0))
                        ) {
                            Text(
                                text = infoMessage!!,
                                color = Color(0xFF15803D),
                                style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(24.dp))

                    Button(
                        onClick = {
                            scope.launch {
                                val email = usernameToAuthEmail(username)
                                isLoading = true
                                errorMessage = null
                                infoMessage = null
                                try {
                                    auth.signInWithEmailAndPassword(email, password).await()
                                    runCatching {
                                        RetrofitClient.api.reportSuccessfulLogin(AuthReport(email))
                                    }
                                    onLoginSuccess()
                                } catch (e: Exception) {
                                    val report = runCatching {
                                        RetrofitClient.api.reportFailedLogin(AuthReport(email))
                                    }.getOrNull()
                                    errorMessage = loginErrorMessage(e, report)
                                } finally {
                                    isLoading = false
                                }
                            }
                        },
                        enabled = !isLoading && username.isNotBlank() && password.isNotBlank(),
                        shape = RoundedCornerShape(17.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = LoginBlue,
                            contentColor = Color.White,
                            disabledContainerColor = LoginBlue.copy(alpha = 0.5f),
                            disabledContentColor = Color.White.copy(alpha = 0.72f)
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(52.dp)
                            .shadow(30.dp, RoundedCornerShape(17.dp), clip = false)
                    ) {
                        if (isLoading) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                color = Color.White,
                                strokeWidth = 2.dp
                            )
                        } else {
                            Text(
                                text = "Sign In",
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 15.sp
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(16.dp))

                    TextButton(
                        onClick = {
                            scope.launch {
                                val email = usernameToAuthEmail(username)
                                if (email.isBlank()) {
                                    errorMessage = "Enter your username above first, then tap Forgot password."
                                    infoMessage = null
                                    return@launch
                                }
                                isResettingPassword = true
                                errorMessage = null
                                infoMessage = null
                                try {
                                    auth.sendPasswordResetEmail(email).await()
                                    infoMessage = "If that username has an account, a reset link has been sent. Check your inbox and spam."
                                } catch (e: Exception) {
                                    val msg = e.localizedMessage?.lowercase().orEmpty()
                                    errorMessage = if (msg.contains("invalid")) {
                                        "That doesn't look like a valid username."
                                    } else {
                                        "Could not send reset email. Try again in a minute."
                                    }
                                } finally {
                                    isResettingPassword = false
                                }
                            }
                        },
                        enabled = !isResettingPassword
                    ) {
                        Text(
                            text = if (isResettingPassword) "Sending reset..." else "Forgot password?",
                            color = LoginText,
                            fontWeight = FontWeight.Medium
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun BrandHeader() {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(
            modifier = Modifier
                .shadow(36.dp, RoundedCornerShape(16.dp), clip = false)
                .background(Color.White.copy(alpha = 0.80f), RoundedCornerShape(16.dp))
                .border(1.dp, Color.White.copy(alpha = 0.90f), RoundedCornerShape(16.dp))
                .padding(6.dp)
        ) {
            Image(
                painter = painterResource(id = R.drawable.brand_logo),
                contentDescription = "VictoriaEnso",
                contentScale = ContentScale.Fit,
                modifier = Modifier.height(44.dp)
            )
        }

        Spacer(modifier = Modifier.height(20.dp))

        Text(
            text = "Retail Management",
            color = LoginMuted,
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold,
            letterSpacing = 2.sp
        )
    }
}

@Composable
private fun loginFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor = LoginText,
    unfocusedTextColor = LoginText,
    focusedContainerColor = Color.White.copy(alpha = 0.76f),
    unfocusedContainerColor = Color.White.copy(alpha = 0.76f),
    cursorColor = LoginBlue,
    focusedBorderColor = LoginBlue.copy(alpha = 0.70f),
    unfocusedBorderColor = LoginBorder.copy(alpha = 0.75f),
    focusedPlaceholderColor = LoginMuted.copy(alpha = 0.7f),
    unfocusedPlaceholderColor = LoginMuted.copy(alpha = 0.7f)
)

private fun loginErrorMessage(error: Exception, report: LockoutReport?): String {
    if (report?.locked == true) {
        return "This account has been locked after too many failed sign-ins. Ask an owner or manager to re-enable it, or use Forgot password to reset."
    }
    if (report != null && report.remaining in 1..2) {
        val plural = if (report.remaining == 1) "" else "s"
        return "Incorrect username or password. ${report.remaining} attempt$plural left before this account is temporarily locked."
    }

    val message = error.localizedMessage?.lowercase().orEmpty()
    return when {
        message.contains("disabled") -> "This account is disabled. Contact an owner to re-enable it."
        message.contains("too many") -> "Too many sign-in attempts from this device. Wait a few minutes and try again."
        message.contains("password") || message.contains("credential") || message.contains("user") -> "Incorrect username or password."
        else -> error.localizedMessage ?: "Login failed"
    }
}

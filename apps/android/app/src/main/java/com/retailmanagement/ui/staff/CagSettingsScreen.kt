package com.retailmanagement.ui.staff

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.retailmanagement.data.api.RetrofitClient
import com.retailmanagement.data.model.CagConfigPatch
import com.retailmanagement.data.model.CagConfigPublic
import com.retailmanagement.data.model.CagPushResponse
import com.retailmanagement.data.model.CagScheduledPushRequest
import com.retailmanagement.data.model.CagSftpTestResponse
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Mobile parity for the staff-portal CagSettingsPage. Owner-only SFTP +
 * scheduler config form with Save / Test / Run scheduled push now / Clear.
 * Per-store NEC mappings and the remote error log panel remain web-only.
 */
class CagSettingsViewModel : ViewModel() {
    private val _config = MutableStateFlow<CagConfigPublic?>(null)
    val config = _config.asStateFlow()

    var host = MutableStateFlow("")
    var port = MutableStateFlow("22")
    var username = MutableStateFlow("")
    var password = MutableStateFlow("")
    var keyPath = MutableStateFlow("")
    var keyPassphrase = MutableStateFlow("")
    var tenantFolder = MutableStateFlow("")
    var inboundWorking = MutableStateFlow("Inbound/Working")
    var inboundError = MutableStateFlow("Inbound/Error")
    var inboundArchive = MutableStateFlow("Inbound/Archive")
    var defaultNecStoreId = MutableStateFlow("")
    var defaultTaxable = MutableStateFlow(true)
    var schedulerEnabled = MutableStateFlow(true)
    var schedulerCron = MutableStateFlow("0 */3 * * *")
    var schedulerDefaultTenant = MutableStateFlow("")
    var schedulerDefaultStoreId = MutableStateFlow("")
    var schedulerDefaultTaxable = MutableStateFlow(false)

    val isLoading = MutableStateFlow(true)
    val isSaving = MutableStateFlow(false)
    val isTesting = MutableStateFlow(false)
    val isClearing = MutableStateFlow(false)
    val isRunningPush = MutableStateFlow(false)

    enum class BannerKind { OK, INFO, ERR }
    data class Banner(val kind: BannerKind, val text: String)
    val banner = MutableStateFlow<Banner?>(null)
    val testResult = MutableStateFlow<CagSftpTestResponse?>(null)
    val pushResult = MutableStateFlow<CagPushResponse?>(null)

    fun load() {
        viewModelScope.launch {
            isLoading.value = true
            try {
                apply(RetrofitClient.api.getCagConfig())
                banner.value = null
            } catch (e: Exception) {
                banner.value = Banner(BannerKind.ERR, e.message ?: "Failed to load")
            } finally { isLoading.value = false }
        }
    }

    fun save() {
        viewModelScope.launch {
            isSaving.value = true
            banner.value = null
            try {
                val patch = CagConfigPatch(
                    host = host.value.trim(),
                    port = port.value.toIntOrNull() ?: 22,
                    username = username.value.trim(),
                    password = password.value.ifEmpty { null },
                    keyPath = keyPath.value.trim(),
                    keyPassphrase = keyPassphrase.value.ifEmpty { null },
                    tenantFolder = tenantFolder.value.trim(),
                    inboundWorking = inboundWorking.value.trim().ifEmpty { "Inbound/Working" },
                    inboundError = inboundError.value.trim().ifEmpty { "Inbound/Error" },
                    inboundArchive = inboundArchive.value.trim().ifEmpty { "Inbound/Archive" },
                    defaultNecStoreId = defaultNecStoreId.value.trim(),
                    defaultTaxable = defaultTaxable.value,
                    schedulerEnabled = schedulerEnabled.value,
                    schedulerCron = schedulerCron.value.trim().ifEmpty { "0 */3 * * *" },
                    schedulerDefaultTenant = schedulerDefaultTenant.value.trim(),
                    schedulerDefaultStoreId = schedulerDefaultStoreId.value.trim(),
                    schedulerDefaultTaxable = schedulerDefaultTaxable.value
                )
                apply(RetrofitClient.api.putCagConfig(patch))
                banner.value = Banner(BannerKind.OK, "Settings saved.")
            } catch (e: Exception) {
                banner.value = Banner(BannerKind.ERR, e.message ?: "Save failed")
            } finally { isSaving.value = false }
        }
    }

    fun test() {
        viewModelScope.launch {
            isTesting.value = true; banner.value = null; testResult.value = null
            try {
                val r = RetrofitClient.api.testCagSftp()
                testResult.value = r
                banner.value = Banner(
                    if (r.ok) BannerKind.OK else BannerKind.ERR,
                    if (r.ok) "SFTP connection OK." else "SFTP test failed: ${r.message}"
                )
            } catch (e: Exception) {
                banner.value = Banner(BannerKind.ERR, e.message ?: "Test failed")
            } finally { isTesting.value = false }
        }
    }

    fun clear() {
        viewModelScope.launch {
            isClearing.value = true
            try {
                apply(RetrofitClient.api.clearCagConfig())
                banner.value = Banner(BannerKind.INFO, "Cleared. Falling back to .env defaults (if any).")
            } catch (e: Exception) {
                banner.value = Banner(BannerKind.ERR, e.message ?: "Clear failed")
            } finally { isClearing.value = false }
        }
    }

    fun runScheduledPush() {
        viewModelScope.launch {
            isRunningPush.value = true; banner.value = null; pushResult.value = null
            try {
                val r = RetrofitClient.api.runScheduledCagPush(CagScheduledPushRequest())
                pushResult.value = r
                val ok = r.errors.isEmpty()
                banner.value = Banner(
                    if (ok) BannerKind.OK else BannerKind.ERR,
                    if (ok) "Push OK — ${r.filesUploaded.size} file(s), ${r.bytesUploaded} bytes."
                    else "Push completed with errors: ${r.errors.joinToString("; ")}"
                )
                runCatching { _config.value = RetrofitClient.api.getCagConfig() }
            } catch (e: Exception) {
                banner.value = Banner(BannerKind.ERR, e.message ?: "Push failed")
            } finally { isRunningPush.value = false }
        }
    }

    fun effectiveTenant(): String =
        schedulerDefaultTenant.value.trim().ifEmpty { tenantFolder.value.trim() }

    fun effectiveStoreId(): String =
        schedulerDefaultStoreId.value.trim().ifEmpty { defaultNecStoreId.value.trim() }

    fun effectiveStoreIdValid(): Boolean {
        val v = effectiveStoreId()
        return v.length == 5 && v.all { it.isDigit() }
    }

    fun canRunScheduledPush(): Boolean {
        val cfg = _config.value ?: return false
        return cfg.isConfigured && effectiveTenant().isNotEmpty() && effectiveStoreIdValid()
    }

    private fun apply(cfg: CagConfigPublic) {
        _config.value = cfg
        host.value = cfg.host
        port.value = (if (cfg.port == 0) 22 else cfg.port).toString()
        username.value = cfg.username
        password.value = ""
        keyPath.value = cfg.keyPath
        keyPassphrase.value = ""
        tenantFolder.value = cfg.tenantFolder
        inboundWorking.value = cfg.inboundWorking
        inboundError.value = cfg.inboundError
        inboundArchive.value = cfg.inboundArchive
        defaultNecStoreId.value = cfg.defaultNecStoreId
        defaultTaxable.value = cfg.defaultTaxable
        schedulerEnabled.value = cfg.schedulerEnabled
        schedulerCron.value = cfg.schedulerCron.ifEmpty { "0 */3 * * *" }
        schedulerDefaultTenant.value = cfg.schedulerDefaultTenant
        schedulerDefaultStoreId.value = cfg.schedulerDefaultStoreId
        schedulerDefaultTaxable.value = cfg.schedulerDefaultTaxable
    }
}


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CagSettingsScreen(
    onBack: () -> Unit,
    vm: CagSettingsViewModel = viewModel()
) {
    LaunchedEffect(Unit) { if (vm.config.value == null) vm.load() }

    val cfg by vm.config.collectAsState()
    val isLoading by vm.isLoading.collectAsState()
    val banner by vm.banner.collectAsState()
    val testRes by vm.testResult.collectAsState()
    val pushRes by vm.pushResult.collectAsState()
    val isSaving by vm.isSaving.collectAsState()
    val isTesting by vm.isTesting.collectAsState()
    val isClearing by vm.isClearing.collectAsState()
    val isRunningPush by vm.isRunningPush.collectAsState()

    var confirmClear by remember { mutableStateOf(false) }
    var confirmRunPush by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("NEC CAG Integration") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, contentDescription = "Back") }
                }
            )
        }
    ) { padding ->
        if (isLoading && cfg == null) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            StatusCard(cfg)
            banner?.let { BannerView(it) }
            EffectivePayloadCard(vm, cfg)
            SectionTitle("SFTP server")
            FormField("Host", vm.host)
            FormField("Port", vm.port, keyboardType = KeyboardType.Number)
            FormField("Username", vm.username)
            FormField(
                if (cfg?.hasPassword == true) "Password (saved — leave blank to keep)" else "Password (optional if using key)",
                vm.password, isSecret = true
            )
            FormField("Private key path", vm.keyPath)
            FormField(
                if (cfg?.hasKeyPassphrase == true) "Key passphrase (saved — leave blank to keep)" else "Key passphrase (optional)",
                vm.keyPassphrase, isSecret = true
            )

            SectionTitle("Tenant identifiers")
            FormField("Tenant folder (Customer No.)", vm.tenantFolder)
            FormField("Default NEC Store ID (5 digits)", vm.defaultNecStoreId, keyboardType = KeyboardType.Number)
            BoolPicker("Default tax mode", vm.defaultTaxable, "Landside (taxable)", "Airside (non-taxable)")

            SectionTitle("SFTP folders (rarely changed)")
            FormField("Inbound / Working", vm.inboundWorking)
            FormField("Inbound / Error", vm.inboundError)
            FormField("Inbound / Archive", vm.inboundArchive)

            SectionTitle("Scheduled push")
            BoolPicker("Status", vm.schedulerEnabled, "Enabled", "Paused")
            FormField("Cron expression", vm.schedulerCron)
            FormField("Default tenant code", vm.schedulerDefaultTenant)
            FormField("Default NEC Store ID", vm.schedulerDefaultStoreId, keyboardType = KeyboardType.Number)
            BoolPicker("Default tax mode", vm.schedulerDefaultTaxable, "Landside (taxable)", "Airside (non-taxable)")
            cfg?.schedulerSaEmail?.takeIf { it.isNotEmpty() }?.let {
                Text("Service account: $it", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(
                "Defaults are read by the Cloud-Scheduler-triggered push and the Run scheduled push now button. " +
                    "The cron is informational — the live schedule is in Google Cloud Scheduler.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            testRes?.let { TestResultCard(it) }
            pushRes?.let { PushResultCard(it) }

            Divider()
            Button(onClick = { vm.save() }, enabled = !isSaving, modifier = Modifier.fillMaxWidth()) {
                if (isSaving) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                else { Icon(Icons.Default.Save, null); Spacer(Modifier.width(8.dp)); Text("Save settings") }
            }
            OutlinedButton(onClick = { vm.test() }, enabled = !isTesting, modifier = Modifier.fillMaxWidth()) {
                if (isTesting) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                else { Icon(Icons.Default.NetworkCheck, null); Spacer(Modifier.width(8.dp)); Text("Test SFTP connection") }
            }
            OutlinedButton(
                onClick = { confirmRunPush = true },
                enabled = !isRunningPush && vm.canRunScheduledPush(),
                modifier = Modifier.fillMaxWidth()
            ) {
                if (isRunningPush) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                else { Icon(Icons.Default.Send, null); Spacer(Modifier.width(8.dp)); Text("Run scheduled push now") }
            }
            TextButton(
                onClick = { confirmClear = true },
                enabled = !isClearing,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)
            ) {
                if (isClearing) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                else { Icon(Icons.Default.DeleteOutline, null); Spacer(Modifier.width(8.dp)); Text("Clear saved values") }
            }
        }
    }

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text("Wipe saved CAG config?") },
            text = { Text("Environment defaults (.env) will remain.") },
            confirmButton = {
                TextButton(onClick = { confirmClear = false; vm.clear() }) { Text("Wipe", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("Cancel") } }
        )
    }
    if (confirmRunPush) {
        AlertDialog(
            onDismissRequest = { confirmRunPush = false },
            title = { Text("Run scheduled push now?") },
            text = { Text("Uploads the live master bundle to the configured SFTP target using the current defaults.") },
            confirmButton = {
                TextButton(onClick = { confirmRunPush = false; vm.runScheduledPush() }) { Text("Run") }
            },
            dismissButton = { TextButton(onClick = { confirmRunPush = false }) { Text("Cancel") } }
        )
    }
}


@Composable
private fun StatusCard(cfg: CagConfigPublic?) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            val ok = cfg?.isConfigured == true
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    if (ok) Icons.Default.CheckCircle else Icons.Default.Warning,
                    contentDescription = null,
                    tint = if (ok) Color(0xFF2E7D32) else Color(0xFFEF6C00)
                )
                Spacer(Modifier.width(8.dp))
                Text(if (ok) "Configured" else "Incomplete", fontWeight = FontWeight.SemiBold)
            }
            cfg?.updatedAt?.takeIf { it.isNotEmpty() }?.let {
                val by = cfg.updatedBy.takeIf { it.isNotEmpty() }?.let { " by $it" } ?: ""
                Text("Last updated $it$by", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (cfg != null && cfg.schedulerLastRunAt.isNotEmpty()) LastRunRow(cfg)
        }
    }
}

@Composable
private fun LastRunRow(cfg: CagConfigPublic) {
    val ok = cfg.schedulerLastRunStatus.equals("success", ignoreCase = true)
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                if (ok) Icons.Default.CheckCircle else Icons.Default.Warning,
                contentDescription = null,
                tint = if (ok) Color(0xFF2E7D32) else Color(0xFFC62828)
            )
            Spacer(Modifier.width(6.dp))
            val trig = cfg.schedulerLastRunTrigger.takeIf { it.isNotEmpty() }?.let { " ($it)" } ?: ""
            Text(
                "Last run · ${cfg.schedulerLastRunStatus.ifEmpty { "unknown" }}$trig",
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.SemiBold
            )
        }
        Text(
            "${cfg.schedulerLastRunAt} — ${cfg.schedulerLastRunFiles} file(s), ${cfg.schedulerLastRunBytes} bytes",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        if (cfg.schedulerLastRunMessage.isNotEmpty()) {
            Text(cfg.schedulerLastRunMessage, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun BannerView(b: CagSettingsViewModel.Banner) {
    val (icon, tint) = when (b.kind) {
        CagSettingsViewModel.BannerKind.OK -> Icons.Default.CheckCircle to Color(0xFF2E7D32)
        CagSettingsViewModel.BannerKind.INFO -> Icons.Default.Info to Color(0xFF1565C0)
        CagSettingsViewModel.BannerKind.ERR -> Icons.Default.ErrorOutline to Color(0xFFC62828)
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = tint)
        Spacer(Modifier.width(8.dp))
        Text(b.text, style = MaterialTheme.typography.bodySmall, color = tint)
    }
}

@Composable
private fun EffectivePayloadCard(vm: CagSettingsViewModel, cfg: CagConfigPublic?) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Effective scheduled payload", fontWeight = FontWeight.SemiBold)
            val tenant = vm.effectiveTenant().ifEmpty { "—" }
            val store = vm.effectiveStoreId().ifEmpty { "—" }
            val storeColor = if (vm.effectiveStoreIdValid() || store == "—") MaterialTheme.colorScheme.onSurface else Color(0xFFC62828)
            val taxable by vm.schedulerDefaultTaxable.collectAsState()
            Text("Tenant: $tenant", style = MaterialTheme.typography.bodySmall)
            Text("Store ID: $store", style = MaterialTheme.typography.bodySmall, color = storeColor)
            Text("Tax mode: ${if (taxable) "G — Landside (taxable)" else "N — Airside (non-taxable)"}", style = MaterialTheme.typography.bodySmall)
            cfg?.schedulerCron?.takeIf { it.isNotEmpty() }?.let { Text("Cron: $it", style = MaterialTheme.typography.bodySmall) }
            cfg?.schedulerAudience?.takeIf { it.isNotEmpty() }?.let {
                Text("Audience: $it", style = MaterialTheme.typography.bodySmall, maxLines = 2)
            }
        }
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 8.dp))
}

@Composable
private fun FormField(
    label: String,
    state: MutableStateFlow<String>,
    keyboardType: KeyboardType = KeyboardType.Text,
    isSecret: Boolean = false
) {
    val value by state.collectAsState()
    OutlinedTextField(
        value = value,
        onValueChange = { state.value = it },
        label = { Text(label) },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        visualTransformation = if (isSecret) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BoolPicker(label: String, state: MutableStateFlow<Boolean>, trueLabel: String, falseLabel: String) {
    val value by state.collectAsState()
    Column {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = value, onClick = { state.value = true }, label = { Text(trueLabel) })
            FilterChip(selected = !value, onClick = { state.value = false }, label = { Text(falseLabel) })
        }
    }
}

@Composable
private fun TestResultCard(r: CagSftpTestResponse) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text("Connection test result", fontWeight = FontWeight.SemiBold)
            Text(r.message, style = MaterialTheme.typography.bodySmall, color = if (r.ok) Color(0xFF2E7D32) else Color(0xFFC62828))
            r.workingDir?.let { Text("working: $it", style = MaterialTheme.typography.bodySmall) }
            r.errorDir?.let { Text("error: $it", style = MaterialTheme.typography.bodySmall) }
            r.archiveDir?.let { Text("archive: $it", style = MaterialTheme.typography.bodySmall) }
        }
    }
}

@Composable
private fun PushResultCard(r: CagPushResponse) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text("On-demand push result", fontWeight = FontWeight.SemiBold)
            Text("${r.filesUploaded.size} file(s), ${r.bytesUploaded} bytes — started ${r.startedAt}", style = MaterialTheme.typography.bodySmall)
            r.filesUploaded.take(8).forEach { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            if (r.errors.isNotEmpty()) Text(r.errors.joinToString("; "), style = MaterialTheme.typography.bodySmall, color = Color(0xFFC62828))
        }
    }
}

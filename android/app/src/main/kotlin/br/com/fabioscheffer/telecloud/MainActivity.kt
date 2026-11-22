package br.com.fabioscheffer.telecloud

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val td = (application as TeleCloudApp).td
        td.iniciar()
        val nuvem = (application as TeleCloudApp).nuvem
        receber(intent)
        // Android 13+: sem esta permissão a notificação das transferências em segundo plano não aparece.
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) !=
            android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) {}
                .launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent { MaterialTheme { Raiz(td, nuvem) } }
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        receber(intent)
    }

    /** Arquivos vindos de "Compartilhar" em outro app: ficam esperando a escolha da pasta. */
    @Suppress("DEPRECATION")
    private fun receber(intent: android.content.Intent?) {
        val i = intent ?: return
        val uris = when (i.action) {
            android.content.Intent.ACTION_SEND ->
                listOfNotNull(i.getParcelableExtra<android.net.Uri>(android.content.Intent.EXTRA_STREAM))
            android.content.Intent.ACTION_SEND_MULTIPLE ->
                i.getParcelableArrayListExtra<android.net.Uri>(android.content.Intent.EXTRA_STREAM).orEmpty()
            else -> emptyList()
        }
        (application as TeleCloudApp).nuvem.receberCompartilhados(uris)
    }
}

@Composable
fun Raiz(td: Td, nuvem: Nuvem) {
    val etapa by td.etapa.collectAsState()
    if (etapa == Etapa.Pronto) TelaArquivos(nuvem) else Tela(td)
}

@Composable
fun Tela(td: Td) {
    val etapa by td.etapa.collectAsState()
    val erro by td.erro.collectAsState()
    val dica by td.dica.collectAsState()

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // key(etapa): cada passo recria os campos e leva o foco ao novo campo.
        androidx.compose.runtime.key(etapa) {
            when (etapa) {
                Etapa.Iniciando -> Titulo("Abrindo o TeleCloud…")
                Etapa.Chaves -> PassoChaves(td)
                Etapa.Telefone -> PassoCampo(
                    "Seu telefone", "Telefone com código do país, por exemplo +55 41 99999-9999",
                    "Enviar código", KeyboardType.Phone, false, td::enviarTelefone,
                )
                Etapa.Codigo -> PassoCampo(
                    "Código de confirmação", "Código recebido", "Entrar", KeyboardType.Number, false, td::enviarCodigo,
                )
                Etapa.Senha -> PassoCampo(
                    "Senha em duas etapas", "Senha", "Entrar", KeyboardType.Password, true, td::enviarSenha,
                )
                Etapa.Pronto -> Titulo("Conectado ao Telegram.")
                Etapa.Encerrado -> Titulo("Sessão encerrada. Feche e abra o app de novo.")
            }
        }
        if (dica.isNotBlank()) Text(dica)
        // Região ativa: o erro é anunciado assim que aparece.
        Text(
            erro ?: "",
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Assertive },
        )
        Text("Versão ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun Titulo(texto: String) {
    Text(texto, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.semantics { heading() })
}

@Composable
private fun PassoCampo(
    titulo: String, rotulo: String, botao: String, teclado: KeyboardType, senha: Boolean, enviar: (String) -> Unit,
) {
    var valor by remember { mutableStateOf("") }
    val foco = remember { FocusRequester() }
    LaunchedEffect(Unit) { foco.requestFocus() }
    Titulo(titulo)
    OutlinedTextField(
        value = valor, onValueChange = { valor = it }, label = { Text(rotulo) }, singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = teclado),
        visualTransformation = if (senha) PasswordVisualTransformation() else VisualTransformation.None,
        modifier = Modifier.fillMaxWidth().focusRequester(foco),
    )
    Button(onClick = { enviar(valor) }, modifier = Modifier.heightIn(min = 48.dp)) { Text(botao) }
}

/** Seletor de arquivo que também pede permissão de apagar o arquivo escolhido (as chaves não devem ficar em Download). */
private class AbrirParaImportar : androidx.activity.result.contract.ActivityResultContracts.OpenDocument() {
    override fun createIntent(context: android.content.Context, input: Array<String>): android.content.Intent =
        super.createIntent(context, input).addFlags(
            android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
        )
}

@Composable
private fun PassoChaves(td: Td) {
    var id by remember { mutableStateOf("") }
    var hash by remember { mutableStateOf("") }
    var aviso by remember { mutableStateOf("") }
    val contexto = androidx.compose.ui.platform.LocalContext.current
    val importar = androidx.activity.compose.rememberLauncherForActivityResult(AbrirParaImportar()) { uri ->
        if (uri != null) {
            val texto = runCatching {
                contexto.contentResolver.openInputStream(uri)?.use { it.readBytes().toString(Charsets.UTF_8) }
            }.getOrNull()
            if (texto != null && td.importarChaves(texto)) {
                // As chaves já estão guardadas no app; o arquivo em Download não deve ficar por aí.
                val apagou = runCatching { android.provider.DocumentsContract.deleteDocument(contexto.contentResolver, uri) }
                    .getOrDefault(false)
                aviso = if (apagou) "Chaves importadas. O arquivo foi apagado da pasta Download."
                else "Chaves importadas. Apague o arquivo telecloud-config.json da pasta Download."
            } else if (texto == null) {
                aviso = "Não consegui ler o arquivo escolhido."
            }
        }
    }
    val foco = remember { FocusRequester() }
    LaunchedEffect(Unit) { foco.requestFocus() }
    Titulo("Chaves do Telegram")
    Text(
        "São as mesmas chaves api_id e api_hash que o TeleCloud do Windows usa. O jeito mais fácil: no computador, " +
            "no menu do ícone do TeleCloud, escolha Exportar as chaves para o celular, copie o arquivo para a pasta " +
            "Download deste aparelho e toque em Importar o arquivo de chaves. Elas ficam só neste aparelho.",
    )
    Button(
        onClick = { importar.launch(arrayOf("application/json", "text/plain", "application/octet-stream", "*/*")) },
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).focusRequester(foco),
    ) { Text("Importar o arquivo de chaves (telecloud-config.json)") }
    if (aviso.isNotEmpty()) Text(aviso, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
    Text("Ou digite as chaves:")
    OutlinedTextField(
        value = id, onValueChange = { id = it }, label = { Text("api_id") }, singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        modifier = Modifier.fillMaxWidth(),
    )
    OutlinedTextField(
        value = hash, onValueChange = { hash = it }, label = { Text("api_hash") }, singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
    Button(onClick = { td.salvarChaves(id, hash) }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Continuar") }
}

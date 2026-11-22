package br.com.fabioscheffer.telecloud

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun TelaArquivos(nuvem: Nuvem) {
    val e by nuvem.estado.collectAsState()
    LaunchedEffect(Unit) { nuvem.carregar() }
    val msg by nuvem.transferencia.collectAsState()
    var escolhido by remember { mutableStateOf<No?>(null) }
    val salvar = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/octet-stream"),
    ) { uri ->
        val no = escolhido
        if (uri != null && no != null) nuvem.baixar(no, uri)
    }
    val recebidos by nuvem.compartilhados.collectAsState()
    val enviar = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) nuvem.enviar(uris)
    }
    BackHandler(enabled = e.caminho.isNotEmpty()) { nuvem.subir() }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        val local = if (e.caminho.isEmpty()) "TeleCloud" else e.caminho.last().nome
        Text(
            local, style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.semantics { heading() },
        )
        // Região ativa: carregamento e erro são anunciados.
        Text(
            when {
                e.carregando -> "Carregando o índice do Telegram…"
                e.erro != null -> "Erro: ${e.erro}"
                e.itens.isEmpty() && e.pronto -> "Esta pasta está vazia."
                else -> ""
            },
            color = if (e.erro != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        )
        Text(msg, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        if (e.erro != null) {
            Button(onClick = { nuvem.carregar() }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Tentar de novo") }
        }
        if (e.pronto) {
            Button(onClick = { enviar.launch(arrayOf("*/*")) }, modifier = Modifier.heightIn(min = 48.dp)) {
                Text("Enviar arquivo para $local")
            }
            Button(onClick = { nuvem.atualizar() }, modifier = Modifier.heightIn(min = 48.dp)) {
                Text("Atualizar a lista")
            }
            if (recebidos.isNotEmpty()) {
                Button(
                    onClick = {
                        nuvem.enviar(recebidos)
                        nuvem.descartarCompartilhados()
                    },
                    modifier = Modifier.heightIn(min = 48.dp),
                ) { Text("Enviar para $local os ${recebidos.size} arquivo(s) compartilhado(s)") }
            }
        }
        if (e.caminho.isNotEmpty()) {
            val pai = e.caminho.dropLast(1).lastOrNull()?.nome ?: "TeleCloud"
            Button(onClick = { nuvem.subir() }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Voltar para $pai") }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
            items(e.itens, key = { it.id }) { no ->
                val texto = descrever(no)
                val mod = Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(vertical = 8.dp)
                if (no.pasta) {
                    Text(
                        texto,
                        modifier = mod.clickable(role = Role.Button, onClickLabel = "Abrir pasta") { nuvem.abrir(no) },
                    )
                } else {
                    Text(
                        texto,
                        modifier = mod.clickable(role = Role.Button, onClickLabel = "Baixar arquivo") {
                            escolhido = no
                            salvar.launch(no.nome)
                        },
                    )
                }
            }
        }
        Text("Versão ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall)
    }
}

/** Texto único por item: o mesmo serve para a tela e para o leitor de tela. */
private fun descrever(no: No): String {
    if (no.pasta) return "Pasta ${no.nome}"
    val data = SimpleDateFormat("dd/MM/yyyy", Locale("pt", "BR")).format(Date((no.modificado * 1000).toLong()))
    return "${no.nome}, ${formatarTamanho(no.tamanho)}, modificado em $data"
}

fun formatarTamanho(bytes: Long): String {
    val un = arrayOf("B", "KB", "MB", "GB", "TB")
    var v = bytes.toDouble()
    var i = 0
    while (v >= 1024 && i < un.size - 1) {
        v /= 1024
        i++
    }
    return if (i == 0) "$bytes B" else String.format(Locale("pt", "BR"), "%.1f %s", v, un[i])
}

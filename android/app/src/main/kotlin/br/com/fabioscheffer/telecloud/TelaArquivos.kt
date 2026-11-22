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
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private enum class Acao { Nenhuma, Renomear, Apagar }

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
    // Painéis de opções ficam dentro da própria lista (sem janelas por cima): um item aberto por vez.
    var aberto by remember { mutableStateOf<Long?>(null) }
    var acao by remember { mutableStateOf(Acao.Nenhuma) }
    var novoNome by remember { mutableStateOf("") }
    var criando by remember { mutableStateOf(false) }
    var nomePasta by remember { mutableStateOf("") }
    fun fecharPaineis() {
        aberto = null
        acao = Acao.Nenhuma
        criando = false
    }
    BackHandler(enabled = e.caminho.isNotEmpty()) {
        fecharPaineis()
        nuvem.subir()
    }

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
            Button(
                onClick = {
                    val abrir = !criando
                    fecharPaineis()
                    criando = abrir
                    nomePasta = ""
                },
                modifier = Modifier.heightIn(min = 48.dp),
            ) { Text(if (criando) "Cancelar nova pasta" else "Nova pasta em $local") }
            if (criando) {
                CampoNome("Nome da nova pasta", nomePasta, { nomePasta = it }) {
                    Button(
                        onClick = {
                            nuvem.criarPasta(nomePasta)
                            fecharPaineis()
                        },
                        modifier = Modifier.heightIn(min = 48.dp),
                    ) { Text("Criar pasta") }
                }
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
            Button(
                onClick = {
                    fecharPaineis()
                    nuvem.subir()
                },
                modifier = Modifier.heightIn(min = 48.dp),
            ) { Text("Voltar para $pai") }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
            items(e.itens, key = { it.id }) { no ->
                val texto = descrever(no)
                val mod = Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(vertical = 8.dp)
                val principal: () -> Unit = {
                    fecharPaineis()
                    if (no.pasta) {
                        nuvem.abrir(no)
                    } else if (android.os.Build.VERSION.SDK_INT >= 29) {
                        nuvem.baixar(no)
                    } else {
                        escolhido = no
                        salvar.launch(no.nome)
                    }
                }
                val aberto1 = aberto == no.id
                Column(Modifier.fillMaxWidth()) {
                    Text(
                        texto,
                        modifier = mod
                            .clickable(
                                role = Role.Button,
                                onClickLabel = if (no.pasta) "Abrir pasta" else "Baixar para a pasta Download",
                                onClick = principal,
                            )
                            // Ações do leitor de tela: o mesmo que os botões de opções abaixo.
                            .semantics {
                                customActions = listOf(
                                    CustomAccessibilityAction("Renomear") {
                                        criando = false
                                        aberto = no.id
                                        acao = Acao.Renomear
                                        novoNome = no.nome
                                        true
                                    },
                                    CustomAccessibilityAction("Apagar") {
                                        criando = false
                                        aberto = no.id
                                        acao = Acao.Apagar
                                        true
                                    },
                                )
                            },
                    )
                    Button(
                        onClick = {
                            val abrir = !aberto1
                            fecharPaineis()
                            if (abrir) aberto = no.id
                        },
                        modifier = Modifier.heightIn(min = 48.dp),
                    ) { Text(if (aberto1) "Fechar opções de ${no.nome}" else "Opções de ${no.nome}") }
                    if (aberto1) {
                        when (acao) {
                            Acao.Nenhuma -> {
                                Button(
                                    onClick = {
                                        acao = Acao.Renomear
                                        novoNome = no.nome
                                    },
                                    modifier = Modifier.heightIn(min = 48.dp),
                                ) { Text("Renomear ${no.nome}") }
                                Button(onClick = { acao = Acao.Apagar }, modifier = Modifier.heightIn(min = 48.dp)) {
                                    Text("Apagar ${no.nome}")
                                }
                            }
                            Acao.Renomear -> CampoNome("Novo nome de ${no.nome}", novoNome, { novoNome = it }) {
                                Button(
                                    onClick = {
                                        nuvem.renomear(no, novoNome)
                                        fecharPaineis()
                                    },
                                    modifier = Modifier.heightIn(min = 48.dp),
                                ) { Text("Salvar o novo nome") }
                            }
                            Acao.Apagar -> {
                                Text(
                                    if (no.pasta) "Apagar a pasta ${no.nome}? Só é possível se ela estiver vazia."
                                    else "Apagar ${no.nome}? Ele será removido do Telegram e não dá para desfazer.",
                                )
                                Button(
                                    onClick = {
                                        nuvem.apagar(no)
                                        fecharPaineis()
                                    },
                                    modifier = Modifier.heightIn(min = 48.dp),
                                ) { Text("Confirmar: apagar ${no.nome}") }
                            }
                        }
                    }
                }
            }
        }
        Text("Versão ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall)
    }
}

/** Campo de nome com o foco já nele, seguido do botão de confirmar. */
@Composable
private fun CampoNome(rotulo: String, valor: String, aoMudar: (String) -> Unit, botao: @Composable () -> Unit) {
    val foco = remember { FocusRequester() }
    LaunchedEffect(Unit) { foco.requestFocus() }
    OutlinedTextField(
        value = valor, onValueChange = aoMudar, label = { Text(rotulo) }, singleLine = true,
        modifier = Modifier.fillMaxWidth().focusRequester(foco),
    )
    botao()
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

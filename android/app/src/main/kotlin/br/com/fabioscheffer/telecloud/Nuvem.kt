package br.com.fabioscheffer.telecloud

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.drinkless.tdlib.TdApi
import java.io.File
import java.io.InputStream
import java.util.zip.InflaterInputStream

const val NOME_GRUPO = "TeleCloud"
const val MARCA_INDICE = "#telecloud_indice"
const val TAMANHO_PARTE = 64L * 1024 * 1024
const val TOPICO_RAIZ = "(raiz)"

data class EstadoNuvem(
    val carregando: Boolean = false,
    val erro: String? = null,
    /** Pastas abertas, da raiz até a atual. */
    val caminho: List<No> = emptyList(),
    val itens: List<No> = emptyList(),
    val pronto: Boolean = false,
)

class Nuvem(private val td: Td, private val ctx: Context) {
    private val escopo = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val trava = Mutex() // uma operação de transferência por vez: o índice é um arquivo só
    private var indice: Indice? = null
    private var grupo = 0L
    private val topicos = HashMap<String, Int>()

    /** Id (da TDLib) da cópia do índice que este aparelho já baixou ou publicou. */
    @Volatile
    private var indiceConhecido = 0L

    init {
        // O Telegram avisa na hora quando o PC publica um índice novo: atualiza a lista sozinho.
        td.aoNovaMensagem = { m ->
            val c = m.content
            if (grupo != 0L && m.chatId == grupo && m.id != indiceConhecido && indice != null &&
                c is TdApi.MessageDocument && c.caption.text.trim() == MARCA_INDICE
            ) {
                atualizar(automatico = m.id)
            }
        }
    }

    private val _estado = MutableStateFlow(EstadoNuvem())
    val estado: StateFlow<EstadoNuvem> = _estado

    private val _transferencia = MutableStateFlow("")

    /** Andamento de download/envio (anunciado por região ativa). */
    val transferencia: StateFlow<String> = _transferencia

    private val _compartilhados = MutableStateFlow<List<Uri>>(emptyList())

    /** Arquivos recebidos de outros apps (Compartilhar), esperando a escolha da pasta. */
    val compartilhados: StateFlow<List<Uri>> = _compartilhados

    fun receberCompartilhados(uris: List<Uri>) {
        if (uris.isNotEmpty()) _compartilhados.value = uris
    }

    fun descartarCompartilhados() {
        _compartilhados.value = emptyList()
    }

    fun carregar() {
        if (_estado.value.carregando || indice != null) return
        _estado.value = EstadoNuvem(carregando = true)
        escopo.launch {
            try {
                val idx = baixarIndice()
                indice = idx
                _estado.value = EstadoNuvem(itens = idx.listar(RAIZ), pronto = true)
                vigiar()
            } catch (e: Exception) {
                Registro.erro(ctx, "carregar índice", e)
                _estado.value = EstadoNuvem(erro = e.message ?: e.toString())
            }
        }
    }

    /** Baixa de novo o índice do grupo (o PC pode ter mudado algo) e mantém a pasta aberta, se ela ainda existir. */
    fun atualizar(automatico: Long = 0L) {
        if (automatico == 0L && _estado.value.carregando) return
        escopo.launch {
            trava.withLock {
                // Aviso automático: se uma operação nossa já deixou o índice conhecido em dia, não repete.
                if (automatico != 0L && automatico == indiceConhecido) return@withLock
                val antes = _estado.value.caminho
                _estado.value = _estado.value.copy(carregando = true, erro = null)
                try {
                    indice?.fechar()
                    indice = null
                    val idx = baixarIndice()
                    indice = idx
                    var caminho = emptyList<No>()
                    for (p in antes) {
                        if (!idx.existe(p.id)) break
                        caminho = caminho + p
                    }
                    _estado.value = EstadoNuvem(
                        caminho = caminho, itens = idx.listar(caminho.lastOrNull()?.id ?: RAIZ), pronto = true,
                    )
                    _transferencia.value =
                        if (automatico != 0L) "A lista foi atualizada com novidades do computador." else "Lista atualizada."
                } catch (e: Exception) {
                    Registro.erro(ctx, "atualizar índice", e)
                    // Mantém a lista que já estava na tela; só avisa. O índice antigo foi fechado: reabre.
                    runCatching { indice = Indice(File(ctx.filesDir, "indice.db")) }
                    _estado.value = _estado.value.copy(carregando = false, erro = null)
                    _transferencia.value = "Não consegui atualizar a lista agora: ${e.message ?: e}"
                }
            }
        }
    }

    fun abrir(pasta: No) {
        val idx = indice ?: return
        val atual = _estado.value
        _estado.value = atual.copy(caminho = atual.caminho + pasta, itens = idx.listar(pasta.id))
    }

    fun subir() {
        val idx = indice ?: return
        val atual = _estado.value
        if (atual.caminho.isEmpty()) return
        val novo = atual.caminho.dropLast(1)
        _estado.value = atual.copy(caminho = novo, itens = idx.listar(novo.lastOrNull()?.id ?: RAIZ))
    }

    // ---------- download ----------

    /** Baixa as partes do arquivo, em ordem, direto para o destino escolhido pelo usuário. */
    fun baixar(no: No, destino: Uri) {
        val idx = indice ?: return
        escopo.launch {
            trava.withLock {
                try {
                    val partes = idx.partes(no.id)
                    if (partes.isEmpty()) throw IllegalStateException("O índice não tem partes para este arquivo.")
                    ctx.contentResolver.openOutputStream(destino, "w").use { saida ->
                        if (saida == null) throw IllegalStateException("Não foi possível gravar no destino escolhido.")
                        partes.forEachIndexed { i, p ->
                            _transferencia.value = "Baixando ${no.nome}: parte ${i + 1} de ${partes.size}"
                            val msg = td.chamar(TdApi.GetMessage(grupo, idDaTdlib(p.ref)))
                            val c = msg.content as? TdApi.MessageDocument
                                ?: throw IllegalStateException("A mensagem da parte ${i + 1} não tem arquivo.")
                            val f = td.chamar(TdApi.DownloadFile(c.document.document.id, 32, 0, 0, true))
                            if (!f.local.isDownloadingCompleted) {
                                throw IllegalStateException("Download da parte ${i + 1} incompleto.")
                            }
                            File(f.local.path).inputStream().use { it.copyTo(saida) }
                            // Libera o espaço do cache da TDLib: o conteúdo já está no destino.
                            runCatching { td.chamar(TdApi.DeleteFile(f.id)) }
                        }
                    }
                    _transferencia.value = "${no.nome} baixado."
                } catch (e: Exception) {
                    Registro.erro(ctx, "baixar ${no.nome} (no ${no.id})", e)
                    // O seletor já criou o arquivo vazio no destino; não deixar a sobra de 0 B.
                    runCatching { android.provider.DocumentsContract.deleteDocument(ctx.contentResolver, destino) }
                    _transferencia.value = "Erro ao baixar ${no.nome}: ${e.message ?: e}"
                }
            }
        }
    }

    // ---------- envio ----------

    /** Envia arquivos para a pasta aberta no momento. */
    fun enviar(uris: List<Uri>) {
        val pastaAtual = _estado.value.caminho
        escopo.launch {
            trava.withLock {
                for (uri in uris) {
                    val (nome, tamanho) = nomeETamanho(uri)
                    try {
                        enviarUm(uri, nome, tamanho, pastaAtual)
                        _transferencia.value = "$nome enviado."
                    } catch (e: Exception) {
                        Registro.erro(ctx, "enviar $nome", e)
                        _transferencia.value = "Erro ao enviar $nome: ${e.message ?: e}"
                        break
                    }
                }
            }
        }
    }

    private suspend fun enviarUm(uri: Uri, nome: String, tamanho: Long, pasta: List<No>) {
        if (tamanho == 0L) throw IllegalStateException("O arquivo está vazio.")
        // Antes de gravar, pega o índice mais recente (o Windows pode ter mudado algo).
        _transferencia.value = "Atualizando o índice antes de enviar $nome…"
        indice?.fechar()
        indice = null
        val idx = baixarIndice()
        indice = idx
        val pai = pasta.lastOrNull()?.id ?: RAIZ
        if (!idx.existe(pai)) throw IllegalStateException("A pasta de destino não existe mais no índice.")

        val topico = topicoDe(if (pasta.isEmpty()) TOPICO_RAIZ else pasta.first().nome)
        val total = if (tamanho > 0) ((tamanho + TAMANHO_PARTE - 1) / TAMANHO_PARTE).toInt() else 0
        val partes = ArrayList<Parte>()
        val temp = File(ctx.cacheDir, "envio").apply { mkdirs() }
        ctx.contentResolver.openInputStream(uri).use { entrada ->
            if (entrada == null) throw IllegalStateException("Não foi possível ler o arquivo escolhido.")
            var i = 0
            while (true) {
                val arq = File(temp, "%s.%03d".format(nome, i))
                val n = copiarAte(entrada, arq, TAMANHO_PARTE)
                if (n == 0L) {
                    arq.delete()
                    break
                }
                _transferencia.value = "Enviando $nome: parte ${i + 1}" + if (total > 0) " de $total" else ""
                try {
                    val msg = td.enviarMensagem(
                        TdApi.SendMessage(
                            grupo, TdApi.MessageTopicForum(topico), null, null, null,
                            TdApi.InputMessageDocument().apply {
                                document = TdApi.InputDocument(TdApi.InputFileLocal(arq.path), null, true)
                                caption = TdApi.FormattedText("", emptyArray())
                            },
                        ),
                    )
                    partes += Parte(i, idDoServidor(msg.id).toString(), n)
                    (msg.content as? TdApi.MessageDocument)?.let { runCatching { td.chamar(TdApi.DeleteFile(it.document.document.id)) } }
                } finally {
                    arq.delete()
                }
                i++
                if (n < TAMANHO_PARTE) break
            }
        }
        if (partes.isEmpty()) throw IllegalStateException("O arquivo está vazio.")

        _transferencia.value = "Salvando o índice no Telegram…"
        val antigas = idx.gravarArquivo(pai, nome, partes)
        salvarIndice(idx)
        if (antigas.isNotEmpty()) {
            runCatching {
                td.chamar(TdApi.DeleteMessages(grupo, antigas.map { idDaTdlib(it) }.toLongArray(), true))
            }
        }
        // Mostra o resultado na pasta aberta.
        _estado.value = _estado.value.copy(itens = idx.listar(pai))
    }

    /** Copia até [limite] bytes do fluxo para o arquivo; devolve quantos copiou. */
    private fun copiarAte(entrada: InputStream, destino: File, limite: Long): Long {
        var copiado = 0L
        val buf = ByteArray(256 * 1024)
        destino.outputStream().use { saida ->
            while (copiado < limite) {
                val ler = entrada.read(buf, 0, minOf(buf.size.toLong(), limite - copiado).toInt())
                if (ler < 0) break
                saida.write(buf, 0, ler)
                copiado += ler
            }
        }
        return copiado
    }

    private fun nomeETamanho(uri: Uri): Pair<String, Long> {
        var nome = uri.lastPathSegment?.substringAfterLast('/') ?: "arquivo"
        var tamanho = -1L
        runCatching {
            ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val n = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val t = c.getColumnIndex(OpenableColumns.SIZE)
                    if (n >= 0 && !c.isNull(n)) nome = c.getString(n)
                    if (t >= 0 && !c.isNull(t)) tamanho = c.getLong(t)
                }
            }
        }
        return nome to tamanho
    }

    /** Tópico do grupo cujo nome é o da pasta de primeiro nível (ou "(raiz)"); cria se não existir. */
    private suspend fun topicoDe(nome: String): Int {
        topicos[nome]?.let { return it }
        val achados = td.chamar(TdApi.GetForumTopics(grupo, nome, 0, 0, 0, 100))
        val id = achados.topics.firstOrNull { it.info.name == nome }?.info?.forumTopicId
            ?: td.chamar(TdApi.CreateForumTopic(grupo, nome.take(128), false, null)).forumTopicId
        topicos[nome] = id
        return id
    }

    /** Publica a cópia do índice no grupo (tópico geral) e apaga as cópias antigas, como o Windows faz. */
    private suspend fun salvarIndice(idx: Indice) {
        val dados = withContext(Dispatchers.IO) { idx.exportar() }
        val arq = File(ctx.cacheDir, "indice.db.z")
        arq.writeBytes(dados)
        try {
            val nova = td.enviarMensagem(
                TdApi.SendMessage(
                    grupo, null, null, null, null,
                    TdApi.InputMessageDocument().apply {
                        document = TdApi.InputDocument(TdApi.InputFileLocal(arq.path), null, true)
                        caption = TdApi.FormattedText(MARCA_INDICE, emptyArray())
                    },
                ),
            )
            indiceConhecido = nova.id
            val velhas = indicesNoGrupo().filter { it.id != nova.id }.map { it.id }
            if (velhas.isNotEmpty()) {
                runCatching { td.chamar(TdApi.DeleteMessages(grupo, velhas.toLongArray(), true)) }
            }
            (nova.content as? TdApi.MessageDocument)?.let { runCatching { td.chamar(TdApi.DeleteFile(it.document.document.id)) } }
        } finally {
            arq.delete()
        }
    }

    // ---------- grupo e índice ----------

    /** A TDLib usa, em grupos, o id do servidor deslocado 20 bits; o índice guarda o id do servidor. */
    private fun idDaTdlib(ref: String): Long = ref.substringAfterLast(':').toLong() shl 20
    private fun idDoServidor(idTdlib: Long): Long = idTdlib shr 20

    private suspend fun achaGrupo(): Long {
        val achados = td.chamar(TdApi.SearchChatsOnServer(NOME_GRUPO, null, 20))
        for (id in achados.chatIds) {
            val chat = td.chamar(TdApi.GetChat(id))
            val tipo = chat.type as? TdApi.ChatTypeSupergroup ?: continue
            if (tipo.isChannel || chat.title != NOME_GRUPO) continue
            val sg = td.chamar(TdApi.GetSupergroup(tipo.supergroupId))
            if (sg.status is TdApi.ChatMemberStatusCreator) {
                runCatching { td.chamar(TdApi.OpenChat(id)) }
                return id
            }
        }
        throw IllegalStateException("O grupo \"$NOME_GRUPO\" não foi encontrado nesta conta do Telegram.")
    }

    /** Mensagens de índice do grupo. A busca por texto demora minutos para enxergar mensagens novas; a lista de
     *  documentos do tópico geral enxerga na hora. Junta as duas (a mais nova vale). */
    private suspend fun indicesNoGrupo(): List<TdApi.Message> {
        val achados = HashMap<Long, TdApi.Message>()
        fun guardar(l: Array<TdApi.Message>) {
            for (m in l) {
                val c = m.content
                if (c is TdApi.MessageDocument && c.caption.text.trim() == MARCA_INDICE) achados[m.id] = m
            }
        }
        guardar(
            td.chamar(
                TdApi.SearchChatMessages(grupo, TdApi.MessageTopicForum(1), "", null, 0, 0, 100, TdApi.SearchMessagesFilterDocument()),
            ).messages,
        )
        runCatching {
            guardar(td.chamar(TdApi.SearchChatMessages(grupo, null, MARCA_INDICE, null, 0, 0, 50, null)).messages)
        }
        return achados.values.sortedByDescending { it.id }
    }

    private var vigia: kotlinx.coroutines.Job? = null

    /** Confere o grupo a cada 30 s: se o PC publicou um índice novo, atualiza a lista (o aviso em tempo real
     *  do Telegram nem sempre chega ao app). */
    private fun vigiar() {
        if (vigia?.isActive == true) return
        vigia = escopo.launch {
            while (true) {
                kotlinx.coroutines.delay(30_000)
                try {
                    if (indice == null || trava.isLocked || grupo == 0L) continue
                    val m = indicesNoGrupo().firstOrNull() ?: continue
                    if (m.id != indiceConhecido) atualizar(automatico = m.id)
                } catch (_: Exception) {
                    // sem rede agora: tenta de novo na próxima volta
                }
            }
        }
    }

    private suspend fun baixarIndice(): Indice {
        if (grupo == 0L) grupo = achaGrupo()
        // O PC publica a cópia nova e só depois apaga a antiga; se a busca cair nesse intervalo (ou o Telegram
        // ainda não indexou a mensagem), tenta de novo algumas vezes antes de desistir.
        var msg: TdApi.Message? = null
        for (tentativa in 1..5) {
            msg = indicesNoGrupo().maxByOrNull { it.id }
            if (msg != null) break
            kotlinx.coroutines.delay(3000)
        }
        msg ?: throw IllegalStateException("O índice do TeleCloud não foi encontrado no grupo. Toque em \"Tentar de novo\".")
        val doc = (msg.content as TdApi.MessageDocument).document.document
        indiceConhecido = msg.id
        val arq = td.chamar(TdApi.DownloadFile(doc.id, 32, 0, 0, true))
        val caminho = arq.local.path
        if (!arq.local.isDownloadingCompleted || caminho.isNullOrEmpty()) {
            throw IllegalStateException("Não foi possível baixar o índice.")
        }
        return withContext(Dispatchers.IO) {
            val destino = File(ctx.filesDir, "indice.db")
            destino.delete()
            File(destino.path + "-wal").delete()
            File(destino.path + "-shm").delete()
            File(caminho).inputStream().use { entrada ->
                InflaterInputStream(entrada).use { z -> destino.outputStream().use { z.copyTo(it) } }
            }
            runCatching { td.chamar(TdApi.DeleteFile(arq.id)) }
            Indice(destino)
        }
    }
}

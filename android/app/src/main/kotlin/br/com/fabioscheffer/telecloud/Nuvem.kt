package br.com.fabioscheffer.telecloud

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
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

/** Texto curto com o que mudou entre duas versões do índice; vazio se nada mudou. */
fun descreverMudancas(antes: Map<String, Assinatura>, depois: Map<String, Assinatura>): String {
    fun nome(c: String) = c.substringAfterLast('/')
    fun pasta(c: String) = if ('/' in c) c.substringBeforeLast('/') else "TeleCloud"
    val novos = (depois.keys - antes.keys).toMutableSet()
    val removidos = (antes.keys - depois.keys).toMutableSet()
    val linhas = ArrayList<String>()

    // Pasta renomeada: some um caminho e surge outro na mesma pasta com o mesmo conteúdo por dentro.
    // Os itens de dentro mudam de caminho junto, então saem da conta (senão viraria uma lista de "movidos").
    fun filhos(base: String, mapa: Map<String, Assinatura>, chaves: Set<String>): Map<String, Assinatura> =
        chaves.filter { it.startsWith("$base/") }.associate { it.removePrefix("$base/") to mapa[it]!! }
    for (r in removidos.filter { antes[it]!!.pasta }.sorted()) {
        if (r !in removidos) continue // já levado por uma pasta renomeada acima dela
        val dentro = filhos(r, antes, removidos)
        val candidatas = novos.filter { depois[it]!!.pasta && pasta(it) == pasta(r) && filhos(it, depois, novos) == dentro }
        val alvo = candidatas.singleOrNull() ?: continue
        linhas += "Pasta ${nome(r)} renomeada para ${nome(alvo)}"
        removidos.removeAll { it == r || it.startsWith("$r/") }
        novos.removeAll { it == alvo || it.startsWith("$alvo/") }
    }
    // Arquivo renomeado (mesma pasta, mesmo tamanho e data) ou movido (outra pasta, mesmo nome e tamanho).
    for (r in removidos.filter { !antes[it]!!.pasta }.sorted()) {
        val a = antes[r]!!
        val renomeado = novos.firstOrNull { n ->
            val d = depois[n]!!
            !d.pasta && pasta(n) == pasta(r) && d.tamanho == a.tamanho && d.modificado == a.modificado
        }
        if (renomeado != null) {
            linhas += "${nome(r)} renomeado para ${nome(renomeado)}"
            removidos.remove(r)
            novos.remove(renomeado)
            continue
        }
        val movido = novos.firstOrNull { n -> val d = depois[n]!!; !d.pasta && nome(n) == nome(r) && d.tamanho == a.tamanho }
        if (movido != null) {
            linhas += "${nome(r)} movido de ${pasta(r)} para ${pasta(movido)}"
            removidos.remove(r)
            novos.remove(movido)
        }
    }
    for (n in novos.sorted()) linhas += if (depois[n]!!.pasta) "Nova pasta ${nome(n)}" else "Novo: ${nome(n)} em ${pasta(n)}"
    for (r in removidos.sorted()) linhas += if (antes[r]!!.pasta) "Pasta ${nome(r)} removida" else "Removido: ${nome(r)} de ${pasta(r)}"
    for ((c, d) in depois) {
        val a = antes[c] ?: continue
        if (!d.pasta && (a.tamanho != d.tamanho || a.modificado != d.modificado)) linhas += "Alterado: ${nome(c)}"
    }
    if (linhas.isEmpty()) return ""
    val extra = linhas.size - 4
    return linhas.take(4).joinToString(". ") + if (extra > 0) ". E mais $extra mudança(s)" else ""
}

data class EstadoNuvem(
    val carregando: Boolean = false,
    val erro: String? = null,
    /** Pastas abertas, da raiz até a atual. */
    val caminho: List<No> = emptyList(),
    val itens: List<No> = emptyList(),
    val pronto: Boolean = false,
)

class Nuvem(private val td: Td, private val ctx: Context) {
    val contexto: Context get() = ctx

    /** Mostra uma mensagem na região de avisos da tela. */
    fun avisar(texto: String) {
        _transferencia.value = texto
    }
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

    private val ativas = java.util.concurrent.atomic.AtomicInteger(0)

    /** Executa uma transferência com o serviço em primeiro plano ligado (notificação) enquanto durar. */
    private suspend fun <T> emSegundoPlano(bloco: suspend () -> T): T {
        if (ativas.incrementAndGet() == 1) TransferenciaService.iniciar(ctx)
        try {
            return bloco()
        } finally {
            if (ativas.decrementAndGet() == 0) TransferenciaService.parar(ctx)
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

    /** Nome de exibição de um arquivo recebido de outro app. */
    fun nomeDe(uri: Uri): String = nomeETamanho(uri).first

    fun receberCompartilhados(uris: List<Uri>) {
        if (uris.isEmpty()) return
        _compartilhados.value = uris
        val nomes = uris.joinToString(", ") { nomeDe(it) }
        // Anunciado pela região de avisos: quem usa leitor de tela precisa saber que há algo esperando.
        _transferencia.value = "Recebido para enviar ao TeleCloud: $nomes. Abra a pasta de destino e toque em Enviar aqui."
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
                avisarProvedor(idx)
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
                    val mapaAntes = withContext(Dispatchers.IO) { indice?.mapa() }
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
                    avisarProvedor(idx)
                    val mudancas = if (mapaAntes == null) "" else descreverMudancas(mapaAntes, withContext(Dispatchers.IO) { idx.mapa() })
                    // Só anuncia o que de fato mudou; atualização automática sem mudança fica em silêncio.
                    if (mudancas.isNotEmpty()) {
                        _transferencia.value = "Novidades do computador: $mudancas"
                    } else if (automatico == 0L) {
                        _transferencia.value = "Lista atualizada. Sem mudanças."
                    }
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

    /**
     * Baixa as partes do arquivo, em ordem. Sem [destino], grava na pasta Download do aparelho (Android 10+) como
     * arquivo "pendente": só aparece para o usuário quando estiver completo, então nunca sobra um arquivo de 0 B
     * nem um arquivo pela metade. Com [destino] (Android 9 ou menos), grava no local escolhido no seletor.
     */
    fun baixar(no: No, destino: Uri? = null) {
        val idx = indice ?: return
        escopo.launch {
            emSegundoPlano { trava.withLock {
                var alvo: Uri? = destino
                val pendente = destino == null
                try {
                    val partes = idx.partes(no.id)
                    if (partes.isEmpty()) throw IllegalStateException("O índice não tem partes para este arquivo.")
                    val resolver = ctx.contentResolver
                    if (alvo == null) alvo = criarEmDownloads(no.nome)
                    resolver.openOutputStream(alvo, "w").use { saida ->
                        if (saida == null) throw IllegalStateException("Não foi possível gravar no destino.")
                        partes.forEachIndexed { i, p ->
                            val rotulo = "Baixando ${no.nome}" + if (partes.size > 1) ", parte ${i + 1} de ${partes.size}" else ""
                            _transferencia.value = rotulo
                            val msg = td.chamar(TdApi.GetMessage(grupo, idDaTdlib(p.ref)))
                            val c = msg.content as? TdApi.MessageDocument
                                ?: throw IllegalStateException("A mensagem da parte ${i + 1} não tem arquivo.")
                            val arquivo = c.document.document
                            val f = baixarAcompanhando(arquivo.id, rotulo)
                            File(f.local.path).inputStream().use { it.copyTo(saida) }
                            // Libera o espaço do cache da TDLib: o conteúdo já está no destino.
                            runCatching { td.chamar(TdApi.DeleteFile(f.id)) }
                        }
                    }
                    if (pendente) liberarDownload(alvo!!)
                    _transferencia.value = "${no.nome} baixado" + if (pendente) " na pasta Download." else "."
                } catch (e: Exception) {
                    Registro.erro(ctx, "baixar ${no.nome} (no ${no.id})", e)
                    // Não deixar sobra: apaga o arquivo vazio ou incompleto do destino.
                    alvo?.let { u ->
                        runCatching { if (pendente) ctx.contentResolver.delete(u, null, null)
                        else android.provider.DocumentsContract.deleteDocument(ctx.contentResolver, u) }
                    }
                    _transferencia.value = "Erro ao baixar ${no.nome}: ${e.message ?: e}"
                }
            } }
        }
    }

    /** Baixa uma parte pela TDLib e vai anunciando o percentual (de 10 em 10 %), na tela e na notificação. */
    private suspend fun baixarAcompanhando(fileId: Int, rotulo: String): TdApi.File = coroutineScope {
        val vigia = launch {
            var ultimo = -1
            while (true) {
                delay(1000)
                val f = runCatching { td.chamar(TdApi.GetFile(fileId)) }.getOrNull() ?: continue
                val total = if (f.size > 0) f.size else f.expectedSize
                if (total > 0) {
                    val pct = (f.local.downloadedSize * 100 / total).toInt() / 10 * 10
                    if (pct != ultimo) {
                        ultimo = pct
                        _transferencia.value = "$rotulo: $pct%"
                    }
                }
            }
        }
        try {
            val f = td.chamar(TdApi.DownloadFile(fileId, 32, 0, 0, true))
            if (!f.local.isDownloadingCompleted) throw IllegalStateException("Download incompleto.")
            f
        } finally {
            vigia.cancel()
        }
    }

    /** Cria na pasta Download um arquivo "pendente" (invisível até [liberarDownload]). */
    private fun criarEmDownloads(nome: String): Uri {
        if (android.os.Build.VERSION.SDK_INT < 29) throw IllegalStateException("Escolha o destino do arquivo.")
        val ext = nome.substringAfterLast('.', "").lowercase()
        val mime = android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
        val valores = android.content.ContentValues().apply {
            put(android.provider.MediaStore.Downloads.DISPLAY_NAME, nome)
            put(android.provider.MediaStore.Downloads.MIME_TYPE, mime)
            put(android.provider.MediaStore.Downloads.RELATIVE_PATH, android.os.Environment.DIRECTORY_DOWNLOADS)
            put(android.provider.MediaStore.Downloads.IS_PENDING, 1)
        }
        return ctx.contentResolver.insert(android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, valores)
            ?: throw IllegalStateException("Não consegui criar o arquivo na pasta Download.")
    }

    private fun liberarDownload(uri: Uri) {
        val v = android.content.ContentValues().apply { put(android.provider.MediaStore.Downloads.IS_PENDING, 0) }
        ctx.contentResolver.update(uri, v, null, null)
    }

    // ---------- provedor de documentos (o TeleCloud dentro do app Arquivos) ----------

    /**
     * Índice pronto para o provedor de documentos, que roda em outra thread e pode ser chamado com o app fechado:
     * liga a TDLib, espera o login e carrega o índice. Devolve null se não houver login ou der tempo esgotado.
     */
    fun indiceParaProvedor(): Indice? = runBlocking(Dispatchers.IO) {
        td.iniciar()
        withTimeoutOrNull(30_000) { td.etapa.first { it != Etapa.Iniciando } }
        if (td.etapa.value != Etapa.Pronto) return@runBlocking null
        if (indice == null) {
            carregar()
            withTimeoutOrNull(90_000) { estado.first { !it.carregando && (it.pronto || it.erro != null) } }
        }
        indice
    }

    private val arquivosDasPartes = java.util.concurrent.ConcurrentHashMap<String, Int>()

    /** Lê até [quer] bytes da parte [parte], a partir de [dentro]: baixa a parte inteira pela TDLib (uma vez) e lê do cache. */
    suspend fun lerDaParte(parte: Parte, dentro: Long, destino: ByteArray, posDestino: Int, quer: Int, usados: MutableSet<Int>): Int {
        val id = arquivosDasPartes[parte.ref] ?: run {
            val msg = td.chamar(TdApi.GetMessage(grupo, idDaTdlib(parte.ref)))
            val c = msg.content as? TdApi.MessageDocument ?: throw IllegalStateException("A parte não tem arquivo.")
            c.document.document.id.also { arquivosDasPartes[parte.ref] = it }
        }
        usados += id
        val f = td.chamar(TdApi.DownloadFile(id, 16, 0, 0, true))
        if (!f.local.isDownloadingCompleted) throw IllegalStateException("Download da parte incompleto.")
        var lido = 0
        java.io.RandomAccessFile(f.local.path, "r").use { r ->
            r.seek(dentro)
            while (lido < quer) {
                val n = r.read(destino, posDestino + lido, quer - lido)
                if (n < 0) break
                lido += n
            }
        }
        return lido
    }

    /** Libera o cache da TDLib das partes lidas pelo provedor (o app Arquivos terminou de usar o arquivo). */
    suspend fun liberarPartes(ids: Set<Int>) {
        for (id in ids) runCatching { td.chamar(TdApi.DeleteFile(id)) }
    }

    /** Avisa o app Arquivos de que o conteúdo das pastas pode ter mudado. */
    private fun avisarProvedor(idx: Indice) {
        runCatching {
            val r = ctx.contentResolver
            for (id in idx.pastas().take(3000)) {
                r.notifyChange(android.provider.DocumentsContract.buildChildDocumentsUri(TeleCloudProvider.AUTORIDADE, "n:$id"), null)
            }
        }
    }

    // ---------- organizar: nova pasta, renomear, apagar ----------

    fun criarPasta(nome: String) = organizar("Criando a pasta $nome…", "Pasta ${nome.trim()} criada.") { idx, pai ->
        val n = idx.criarPasta(pai, nome)
        if (pai == RAIZ) topicoDe(n.nome) // pasta de primeiro nível = tópico do grupo, como no Windows
        emptyList()
    }

    fun renomear(no: No, novoNome: String) =
        organizar("Renomeando ${no.nome}…", "${no.nome} renomeado para ${novoNome.trim()}.") { idx, pai ->
            val alvo = idx.filhoPorNome(pai, no.nome) ?: throw IllegalStateException("${no.nome} não existe mais.")
            idx.renomear(alvo, pai, novoNome)
            emptyList()
        }

    fun apagar(no: No) = organizar("Apagando ${no.nome}…", "${no.nome} apagado.") { idx, pai ->
        val alvo = idx.filhoPorNome(pai, no.nome) ?: throw IllegalStateException("${no.nome} não existe mais.")
        idx.apagar(alvo) // devolve as partes para apagar do Telegram depois de publicar o índice
    }

    /**
     * Aplica uma mudança ao índice mais recente do grupo, publica o índice e só então apaga do Telegram as partes
     * que sobraram (se o índice falhar ao publicar, nada foi apagado).
     */
    private fun organizar(fazendo: String, pronto: String, mudar: suspend (Indice, Long) -> List<String>) {
        val nomes = _estado.value.caminho.map { it.nome }
        escopo.launch { organizarAgora(nomes, fazendo, pronto, mudar) }
    }

    /** Faz a mudança na pasta de caminho [nomes]; devolve null se deu certo, ou o erro. */
    private suspend fun organizarAgora(
        nomes: List<String>, fazendo: String, pronto: String, mudar: suspend (Indice, Long) -> List<String>,
    ): Throwable? = emSegundoPlano { trava.withLock {
        try {
            _transferencia.value = fazendo
            indice?.fechar()
            indice = null
            val idx = baixarIndice()
            indice = idx
            val pastas = idx.resolverPastas(nomes)
                ?: throw IllegalStateException("A pasta não existe mais. Atualize a lista.")
            val pai = pastas.lastOrNull()?.id ?: RAIZ
            val refs = mudar(idx, pai)
            salvarIndice(idx)
            if (refs.isNotEmpty()) {
                runCatching { td.chamar(TdApi.DeleteMessages(grupo, refs.map { idDaTdlib(it) }.toLongArray(), true)) }
            }
            atualizarListaAtual(idx)
            avisarProvedor(idx)
            _transferencia.value = pronto
            null
        } catch (e: Exception) {
            Registro.erro(ctx, fazendo, e)
            // A mudança não foi publicada: volta ao índice do grupo para a tela não mostrar algo que não existe.
            runCatching {
                indice?.fechar()
                indice = null
                val idx = baixarIndice()
                indice = idx
                atualizarListaAtual(idx)
            }
            _transferencia.value = "Não foi possível: ${e.message ?: e}"
            e
        }
    } }

    /** Reaplica à tela a pasta que está aberta, com os itens do índice [idx]. */
    private fun atualizarListaAtual(idx: Indice) {
        val pastas = idx.resolverPastas(_estado.value.caminho.map { it.nome }) ?: emptyList()
        _estado.value = _estado.value.copy(caminho = pastas, itens = idx.listar(pastas.lastOrNull()?.id ?: RAIZ))
    }

    // ---------- chamadas do provedor de documentos que gravam ----------

    private suspend fun garantirLogin() {
        td.iniciar()
        withTimeoutOrNull(30_000) { td.etapa.first { it != Etapa.Iniciando } }
        if (td.etapa.value != Etapa.Pronto) throw IllegalStateException("Entre na conta no app TeleCloud.")
    }

    fun criarPastaParaProvedor(nomesPai: List<String>, nome: String): Long = runBlocking(Dispatchers.IO) {
        garantirLogin()
        val erro = organizarAgora(nomesPai, "Criando a pasta $nome…", "Pasta $nome criada.") { idx, pai ->
            val n = idx.criarPasta(pai, nome)
            if (pai == RAIZ) topicoDe(n.nome)
            emptyList()
        }
        if (erro != null) throw erro
        val idx = indice ?: throw IllegalStateException("Índice indisponível.")
        val pastas = idx.resolverPastas(nomesPai) ?: throw IllegalStateException("A pasta não existe mais.")
        idx.filhoPorNome(pastas.lastOrNull()?.id ?: RAIZ, nome)?.id ?: throw IllegalStateException("A pasta não foi criada.")
    }

    fun renomearParaProvedor(nomesPai: List<String>, nome: String, novo: String) = runBlocking(Dispatchers.IO) {
        garantirLogin()
        val erro = organizarAgora(nomesPai, "Renomeando $nome…", "$nome renomeado para ${novo.trim()}.") { idx, pai ->
            val alvo = idx.filhoPorNome(pai, nome) ?: throw IllegalStateException("$nome não existe mais.")
            idx.renomear(alvo, pai, novo)
            emptyList()
        }
        if (erro != null) throw erro
    }

    fun apagarParaProvedor(nomesPai: List<String>, nome: String) = runBlocking(Dispatchers.IO) {
        garantirLogin()
        val erro = organizarAgora(nomesPai, "Apagando $nome…", "$nome apagado.") { idx, pai ->
            val alvo = idx.filhoPorNome(pai, nome) ?: throw IllegalStateException("$nome não existe mais.")
            idx.apagar(alvo)
        }
        if (erro != null) throw erro
    }

    /** Envia um arquivo que o provedor recebeu de outro app (substitui o de mesmo nome); apaga o temporário no fim. */
    fun enviarDoProvedor(arquivo: File, nome: String, nomesPasta: List<String>) {
        escopo.launch {
            emSegundoPlano { trava.withLock {
                try {
                    garantirLogin()
                    if (arquivo.length() == 0L) {
                        _transferencia.value = "$nome está vazio e não foi enviado."
                    } else {
                        enviarUm(Uri.fromFile(arquivo), nome, arquivo.length(), nomesPasta)
                        _transferencia.value = "$nome enviado."
                    }
                } catch (e: Exception) {
                    Registro.erro(ctx, "enviar pelo provedor $nome", e)
                    _transferencia.value = "Erro ao enviar $nome: ${e.message ?: e}"
                } finally {
                    arquivo.delete()
                }
            } }
        }
    }

    // ---------- envio ----------

    /** Envia arquivos para a pasta aberta no momento. */
    fun enviar(uris: List<Uri>) {
        val pastaAtual = _estado.value.caminho.map { it.nome }
        escopo.launch {
            emSegundoPlano { trava.withLock {
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
            } }
        }
    }

    private suspend fun enviarUm(uri: Uri, nome: String, tamanho: Long, nomesPasta: List<String>) {
        if (tamanho == 0L) throw IllegalStateException("O arquivo está vazio.")
        // Antes de gravar, pega o índice mais recente (o Windows pode ter mudado algo).
        _transferencia.value = "Atualizando o índice antes de enviar $nome…"
        indice?.fechar()
        indice = null
        val idx = baixarIndice()
        indice = idx
        val pastas = idx.resolverPastas(nomesPasta) ?: throw IllegalStateException("A pasta de destino não existe mais no índice.")
        val pai = pastas.lastOrNull()?.id ?: RAIZ

        val topico = topicoDe(if (pastas.isEmpty()) TOPICO_RAIZ else pastas.first().nome)
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
        // Mostra o resultado na pasta aberta e avisa o app Arquivos.
        atualizarListaAtual(idx)
        avisarProvedor(idx)
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
    private suspend fun indicesNoGrupo(rapido: Boolean = false): List<TdApi.Message> {
        val achados = HashMap<Long, TdApi.Message>()
        val diag = StringBuilder()
        fun guardar(origem: String, l: Array<TdApi.Message>) {
            diag.append("$origem=${l.size}[")
            for (m in l) {
                val c = m.content
                val leg = (c as? TdApi.MessageDocument)?.caption?.text ?: ""
                diag.append("${m.id shr 20}:${c.javaClass.simpleName.removePrefix("Message")}:${leg.take(20)} ")
                if (c is TdApi.MessageDocument && leg.trim() == MARCA_INDICE) achados[m.id] = m
            }
            diag.append("] ")
        }
        try {
            guardar(
                "tipo",
                td.chamar(
                    TdApi.SearchChatMessages(grupo, TdApi.MessageTopicForum(1), "", null, 0, 0, 100, TdApi.SearchMessagesFilterDocument()),
                ).messages,
            )
        } catch (e: Exception) {
            diag.append("tipo=ERRO(${e.message}) ")
        }
        if (!rapido) {
            try {
                guardar("texto", td.chamar(TdApi.SearchChatMessages(grupo, null, MARCA_INDICE, null, 0, 0, 50, null)).messages)
            } catch (e: Exception) {
                diag.append("texto=ERRO(${e.message}) ")
            }
        }
        if (achados.isEmpty()) {
            // Terceira via, sem busca: as mensagens mais recentes do grupo (o índice é publicado depois de cada
            // mudança, então costuma estar entre as últimas).
            try {
                guardar("recentes", td.chamar(TdApi.GetChatHistory(grupo, 0, 0, 100, false)).messages)
            } catch (e: Exception) {
                diag.append("recentes=ERRO(${e.message}) ")
            }
        }
        if (achados.isEmpty() && !rapido) {
            Registro.erro(ctx, "índice não achado: grupo=$grupo $diag", RuntimeException("diagnóstico"))
        }
        ultimoDiagnostico = diag.toString()
        return achados.values.sortedByDescending { it.id }
    }

    @Volatile
    private var ultimoDiagnostico = ""

    private var vigia: kotlinx.coroutines.Job? = null

    /** Confere o grupo a cada 10 s: se o PC publicou um índice novo, atualiza a lista (o aviso em tempo real
     *  do Telegram nem sempre chega ao app). */
    private fun vigiar() {
        if (vigia?.isActive == true) return
        vigia = escopo.launch {
            var volta = 0
            while (true) {
                kotlinx.coroutines.delay(10_000)
                volta++
                try {
                    if (indice == null || trava.isLocked || grupo == 0L) continue
                    val m = indicesNoGrupo(rapido = true).firstOrNull()
                    if (volta % 12 == 1) {
                        Registro.info(ctx, "vigia: topo=${m?.id?.shr(20)} conhecido=${indiceConhecido shr 20} :: ${ultimoDiagnostico.take(300)}")
                    }
                    if (m != null && m.id != indiceConhecido) {
                        Registro.info(ctx, "vigia: índice novo ${m.id shr 20} (conhecido ${indiceConhecido shr 20}); atualizando")
                        atualizar(automatico = m.id)
                    }
                } catch (e: Exception) {
                    Registro.info(ctx, "vigia: falhou ${e.message}")
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

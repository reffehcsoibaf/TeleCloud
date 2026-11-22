package br.com.fabioscheffer.telecloud

import android.database.Cursor
import android.database.MatrixCursor
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Handler
import android.os.HandlerThread
import android.os.ParcelFileDescriptor
import android.os.ProxyFileDescriptorCallback
import android.os.storage.StorageManager
import android.provider.DocumentsContract
import android.provider.DocumentsContract.Document
import android.provider.DocumentsContract.Root
import android.provider.DocumentsProvider
import android.system.ErrnoException
import android.system.OsConstants
import android.webkit.MimeTypeMap
import kotlinx.coroutines.runBlocking
import java.io.File
import java.io.FileNotFoundException
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * O TeleCloud dentro do app Arquivos do Android (e de qualquer app que abra ou salve arquivos).
 * Identificadores de documento: "n:<id do nó do índice>" para o que já existe e "p:<uuid>" para um arquivo que
 * está sendo gravado (recebido de outro app e ainda a caminho do Telegram).
 */
class TeleCloudProvider : DocumentsProvider() {
    /** Arquivo recebido de outro app: vai para o temporário e, ao fechar, sobe para o Telegram. */
    private class Escrita(val nomesPai: List<String>, val nome: String, val arquivo: File) {
        @Volatile var tamanho: Long = 0
    }

    companion object {
        const val AUTORIDADE = "br.com.fabioscheffer.telecloud.documentos"
        private const val RAIZ_ID = "raiz"
        private val COLUNAS_RAIZ = arrayOf(
            Root.COLUMN_ROOT_ID, Root.COLUMN_DOCUMENT_ID, Root.COLUMN_TITLE, Root.COLUMN_SUMMARY,
            Root.COLUMN_FLAGS, Root.COLUMN_ICON,
        )
        private val COLUNAS_DOC = arrayOf(
            Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME, Document.COLUMN_SIZE,
            Document.COLUMN_MIME_TYPE, Document.COLUMN_LAST_MODIFIED, Document.COLUMN_FLAGS,
        )
        private const val FLAGS_ARQUIVO = Document.FLAG_SUPPORTS_DELETE or Document.FLAG_SUPPORTS_RENAME or Document.FLAG_SUPPORTS_WRITE
        private const val FLAGS_PASTA = Document.FLAG_DIR_SUPPORTS_CREATE or Document.FLAG_SUPPORTS_DELETE or Document.FLAG_SUPPORTS_RENAME
        private val escritas = ConcurrentHashMap<String, Escrita>()
    }

    private val nuvem get() = (context!!.applicationContext as TeleCloudApp).nuvem
    private val fio by lazy { HandlerThread("leitura-telecloud").also { it.start() } }

    override fun onCreate(): Boolean = true

    private fun idDe(documentId: String): Long =
        documentId.removePrefix("n:").toLongOrNull() ?: throw FileNotFoundException("Documento inválido: $documentId")

    private fun mime(nome: String, pasta: Boolean): String {
        if (pasta) return Document.MIME_TYPE_DIR
        val ext = nome.substringAfterLast('.', "").lowercase()
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
    }

    private fun linha(c: MatrixCursor, no: No) {
        c.newRow()
            .add(Document.COLUMN_DOCUMENT_ID, "n:${no.id}")
            .add(Document.COLUMN_DISPLAY_NAME, no.nome)
            .add(Document.COLUMN_SIZE, if (no.pasta) null else no.tamanho)
            .add(Document.COLUMN_MIME_TYPE, mime(no.nome, no.pasta))
            .add(Document.COLUMN_LAST_MODIFIED, (no.modificado * 1000).toLong())
            .add(Document.COLUMN_FLAGS, if (no.pasta) FLAGS_PASTA else FLAGS_ARQUIVO)
    }

    private fun indice(): Indice =
        nuvem.indiceParaProvedor() ?: throw FileNotFoundException("Entre na conta no app TeleCloud.")

    override fun queryRoots(projection: Array<out String>?): Cursor {
        val c = MatrixCursor(projection ?: COLUNAS_RAIZ)
        c.newRow()
            .add(Root.COLUMN_ROOT_ID, RAIZ_ID)
            .add(Root.COLUMN_DOCUMENT_ID, "n:$RAIZ")
            .add(Root.COLUMN_TITLE, "TeleCloud")
            .add(Root.COLUMN_SUMMARY, "Arquivos guardados no Telegram")
            .add(Root.COLUMN_FLAGS, Root.FLAG_SUPPORTS_CREATE or Root.FLAG_SUPPORTS_IS_CHILD)
            .add(Root.COLUMN_ICON, R.drawable.ic_nuvem)
        return c
    }

    override fun queryDocument(documentId: String, projection: Array<out String>?): Cursor {
        val c = MatrixCursor(projection ?: COLUNAS_DOC)
        if (documentId.startsWith("p:")) {
            val e = escritas[documentId.removePrefix("p:")] ?: throw FileNotFoundException("O arquivo não existe mais.")
            c.newRow()
                .add(Document.COLUMN_DOCUMENT_ID, documentId)
                .add(Document.COLUMN_DISPLAY_NAME, e.nome)
                .add(Document.COLUMN_SIZE, if (e.arquivo.exists()) e.arquivo.length() else e.tamanho)
                .add(Document.COLUMN_MIME_TYPE, mime(e.nome, false))
                .add(Document.COLUMN_LAST_MODIFIED, System.currentTimeMillis())
                .add(Document.COLUMN_FLAGS, Document.FLAG_SUPPORTS_WRITE or Document.FLAG_SUPPORTS_DELETE)
            return c
        }
        val id = idDe(documentId)
        if (id == RAIZ) {
            c.newRow()
                .add(Document.COLUMN_DOCUMENT_ID, documentId)
                .add(Document.COLUMN_DISPLAY_NAME, "TeleCloud")
                .add(Document.COLUMN_SIZE, null)
                .add(Document.COLUMN_MIME_TYPE, Document.MIME_TYPE_DIR)
                .add(Document.COLUMN_LAST_MODIFIED, null)
                .add(Document.COLUMN_FLAGS, Document.FLAG_DIR_SUPPORTS_CREATE)
            return c
        }
        linha(c, indice().obter(id) ?: throw FileNotFoundException("O item não existe mais."))
        return c
    }

    override fun queryChildDocuments(parentDocumentId: String, projection: Array<out String>?, sortOrder: String?): Cursor {
        val c = MatrixCursor(projection ?: COLUNAS_DOC)
        c.setNotificationUri(context!!.contentResolver, DocumentsContract.buildChildDocumentsUri(AUTORIDADE, parentDocumentId))
        val idx = nuvem.indiceParaProvedor()
        if (idx == null) {
            c.extras = Bundle().apply {
                putString(DocumentsContract.EXTRA_ERROR, "Abra o app TeleCloud e entre na sua conta do Telegram.")
            }
            return c
        }
        for (no in idx.listar(idDe(parentDocumentId))) linha(c, no)
        return c
    }

    override fun isChildDocument(parentDocumentId: String, documentId: String): Boolean {
        if (documentId.startsWith("p:") || parentDocumentId.startsWith("p:")) return false
        val idx = nuvem.indiceParaProvedor() ?: return false
        val pai = idDe(parentDocumentId)
        var atual: Long? = idDe(documentId)
        while (atual != null) {
            if (atual == pai) return true
            atual = idx.paiDe(atual)
        }
        return false
    }

    // ---------- gravação ----------

    /** Se já existe um item com esse nome na pasta, devolve "nome (2).ext", "nome (3).ext"… */
    private fun nomeUnico(idx: Indice, pai: Long, nome: String): String {
        if (idx.filhoPorNome(pai, nome) == null) return nome
        val base = nome.substringBeforeLast('.', nome)
        val ext = if ('.' in nome) "." + nome.substringAfterLast('.') else ""
        var n = 2
        while (idx.filhoPorNome(pai, "$base ($n)$ext") != null) n++
        return "$base ($n)$ext"
    }

    private fun novaEscrita(nomesPai: List<String>, nome: String): String {
        val dir = File(context!!.cacheDir, "provedor").apply { mkdirs() }
        val uuid = UUID.randomUUID().toString()
        escritas[uuid] = Escrita(nomesPai, nome, File(dir, uuid))
        return uuid
    }

    override fun createDocument(parentDocumentId: String, mimeType: String, displayName: String): String {
        val idx = indice()
        val paiId = idDe(parentDocumentId)
        val nomesPai = idx.nomesDasPastasAte(paiId)
        val nome = nomeUnico(idx, paiId, displayName.trim())
        if (mimeType == Document.MIME_TYPE_DIR) {
            return "n:${nuvem.criarPastaParaProvedor(nomesPai, nome)}"
        }
        return "p:${novaEscrita(nomesPai, nome)}"
    }

    override fun deleteDocument(documentId: String) {
        if (documentId.startsWith("p:")) {
            escritas.remove(documentId.removePrefix("p:"))?.arquivo?.delete()
            return
        }
        val idx = indice()
        val id = idDe(documentId)
        val no = idx.obter(id) ?: throw FileNotFoundException("O item não existe mais.")
        nuvem.apagarParaProvedor(idx.nomesDasPastasAte(idx.paiDe(id)), no.nome)
    }

    override fun renameDocument(documentId: String, displayName: String): String? {
        if (documentId.startsWith("p:")) return null
        val idx = indice()
        val id = idDe(documentId)
        val no = idx.obter(id) ?: throw FileNotFoundException("O item não existe mais.")
        nuvem.renomearParaProvedor(idx.nomesDasPastasAte(idx.paiDe(id)), no.nome, displayName)
        return documentId // o nó continua o mesmo; só o nome mudou
    }

    override fun openDocument(documentId: String, mode: String, signal: CancellationSignal?): ParcelFileDescriptor {
        val gravar = mode.contains('w')
        if (documentId.startsWith("p:")) {
            val e = escritas[documentId.removePrefix("p:")] ?: throw FileNotFoundException("O arquivo não existe mais.")
            if (!gravar) throw FileNotFoundException("O arquivo ainda está sendo enviado.")
            return abrirParaGravar(e)
        }
        val idx = indice()
        val id = idDe(documentId)
        val no = idx.obter(id)?.takeIf { !it.pasta } ?: throw FileNotFoundException("O arquivo não existe mais.")
        if (gravar) {
            // Regravar um arquivo existente: o conteúdo novo substitui o antigo (mesmo nome, mesma pasta).
            val e = escritas[novaEscrita(idx.nomesDasPastasAte(idx.paiDe(id)), no.nome)]!!
            return abrirParaGravar(e)
        }
        if (mode != "r") throw SecurityException("Modo de abertura não suportado: $mode")
        val partes = idx.partes(id)
        if (partes.isEmpty()) throw FileNotFoundException("O arquivo ainda não foi enviado por completo.")
        val gerente = context!!.getSystemService(StorageManager::class.java)
        return gerente.openProxyFileDescriptor(ParcelFileDescriptor.MODE_READ_ONLY, LeitorRemoto(nuvem, partes), Handler(fio.looper))
    }

    /** Entrega um arquivo temporário para o app gravar; quando ele fecha, o conteúdo sobe para o Telegram. */
    private fun abrirParaGravar(e: Escrita): ParcelFileDescriptor {
        e.arquivo.parentFile?.mkdirs()
        val modo = ParcelFileDescriptor.MODE_WRITE_ONLY or ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE
        return ParcelFileDescriptor.open(e.arquivo, modo, Handler(fio.looper)) { erro ->
            if (erro == null) {
                e.tamanho = e.arquivo.length()
                nuvem.enviarDoProvedor(e.arquivo, e.nome, e.nomesPai)
            } else {
                e.arquivo.delete()
            }
        }
    }
}

/** Entrega ao app que abriu o arquivo os bytes pedidos, baixando as partes do Telegram sob demanda. */
private class LeitorRemoto(private val nuvem: Nuvem, private val partes: List<Parte>) : ProxyFileDescriptorCallback() {
    private val inicios = LongArray(partes.size).also { a ->
        var pos = 0L
        partes.forEachIndexed { i, p ->
            a[i] = pos
            pos += p.tamanho
        }
    }
    private val total = partes.sumOf { it.tamanho }
    private val usados = ConcurrentHashMap.newKeySet<Int>()

    override fun onGetSize(): Long = total

    override fun onRead(offset: Long, size: Int, data: ByteArray): Int {
        try {
            var lido = 0
            while (lido < size && offset + lido < total) {
                val pos = offset + lido
                var i = partes.size - 1
                while (i > 0 && inicios[i] > pos) i--
                val dentro = pos - inicios[i]
                val quer = minOf((size - lido).toLong(), partes[i].tamanho - dentro).toInt()
                val n = runBlocking { nuvem.lerDaParte(partes[i], dentro, data, lido, quer, usados) }
                if (n <= 0) break
                lido += n
            }
            return lido
        } catch (e: Exception) {
            Registro.erro(nuvem.contexto, "ler pelo provedor", e)
            throw ErrnoException("onRead", OsConstants.EIO)
        }
    }

    override fun onRelease() {
        val ids = usados.toSet()
        if (ids.isNotEmpty()) runBlocking { nuvem.liberarPartes(ids) }
    }
}

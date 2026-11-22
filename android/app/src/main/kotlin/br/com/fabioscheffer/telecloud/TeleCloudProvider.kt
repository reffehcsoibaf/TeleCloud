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

/**
 * O TeleCloud dentro do app Arquivos do Android (e de qualquer app que abra ou salve arquivos).
 * Leitura: navegar pelas pastas do índice e abrir/copiar arquivos. Identificador de documento: "n:<id do nó>".
 */
class TeleCloudProvider : DocumentsProvider() {
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
    }

    private val nuvem get() = (context!!.applicationContext as TeleCloudApp).nuvem
    private val fio by lazy { HandlerThread("leitura-telecloud").also { it.start() } }

    override fun onCreate(): Boolean = true

    private fun idDe(documentId: String): Long =
        documentId.removePrefix("n:").toLongOrNull() ?: throw java.io.FileNotFoundException("Documento inválido: $documentId")

    private fun mime(no: No): String {
        if (no.pasta) return Document.MIME_TYPE_DIR
        val ext = no.nome.substringAfterLast('.', "").lowercase()
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
    }

    private fun linha(c: MatrixCursor, no: No) {
        c.newRow()
            .add(Document.COLUMN_DOCUMENT_ID, "n:${no.id}")
            .add(Document.COLUMN_DISPLAY_NAME, no.nome)
            .add(Document.COLUMN_SIZE, if (no.pasta) null else no.tamanho)
            .add(Document.COLUMN_MIME_TYPE, mime(no))
            .add(Document.COLUMN_LAST_MODIFIED, (no.modificado * 1000).toLong())
            .add(Document.COLUMN_FLAGS, 0)
    }

    override fun queryRoots(projection: Array<out String>?): Cursor {
        val c = MatrixCursor(projection ?: COLUNAS_RAIZ)
        c.newRow()
            .add(Root.COLUMN_ROOT_ID, RAIZ_ID)
            .add(Root.COLUMN_DOCUMENT_ID, "n:$RAIZ")
            .add(Root.COLUMN_TITLE, "TeleCloud")
            .add(Root.COLUMN_SUMMARY, "Arquivos guardados no Telegram")
            .add(Root.COLUMN_FLAGS, Root.FLAG_SUPPORTS_IS_CHILD)
            .add(Root.COLUMN_ICON, R.drawable.ic_nuvem)
        return c
    }

    override fun queryDocument(documentId: String, projection: Array<out String>?): Cursor {
        val c = MatrixCursor(projection ?: COLUNAS_DOC)
        val id = idDe(documentId)
        if (id == RAIZ) {
            c.newRow()
                .add(Document.COLUMN_DOCUMENT_ID, documentId)
                .add(Document.COLUMN_DISPLAY_NAME, "TeleCloud")
                .add(Document.COLUMN_SIZE, null)
                .add(Document.COLUMN_MIME_TYPE, Document.MIME_TYPE_DIR)
                .add(Document.COLUMN_LAST_MODIFIED, null)
                .add(Document.COLUMN_FLAGS, 0)
            return c
        }
        val idx = nuvem.indiceParaProvedor() ?: throw java.io.FileNotFoundException("Entre na conta no app TeleCloud.")
        linha(c, idx.obter(id) ?: throw java.io.FileNotFoundException("O item não existe mais."))
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
        val idx = nuvem.indiceParaProvedor() ?: return false
        val pai = idDe(parentDocumentId)
        var atual: Long? = idDe(documentId)
        while (atual != null) {
            if (atual == pai) return true
            atual = idx.paiDe(atual)
        }
        return false
    }

    override fun openDocument(documentId: String, mode: String, signal: CancellationSignal?): ParcelFileDescriptor {
        if (mode != "r") throw SecurityException("Por enquanto o TeleCloud só permite leitura pelo app Arquivos.")
        val idx = nuvem.indiceParaProvedor() ?: throw java.io.FileNotFoundException("Entre na conta no app TeleCloud.")
        val id = idDe(documentId)
        val no = idx.obter(id)?.takeIf { !it.pasta } ?: throw java.io.FileNotFoundException("O arquivo não existe mais.")
        val partes = idx.partes(id)
        if (partes.isEmpty()) throw java.io.FileNotFoundException("O arquivo ainda não foi enviado por completo.")
        val gerente = context!!.getSystemService(StorageManager::class.java)
        return gerente.openProxyFileDescriptor(ParcelFileDescriptor.MODE_READ_ONLY, LeitorRemoto(nuvem, partes), Handler(fio.looper))
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
    private val usados = java.util.concurrent.ConcurrentHashMap.newKeySet<Int>()

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

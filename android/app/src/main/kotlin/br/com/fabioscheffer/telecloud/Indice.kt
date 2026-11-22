package br.com.fabioscheffer.telecloud

import android.database.sqlite.SQLiteDatabase
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.Deflater
import java.util.zip.DeflaterOutputStream

const val RAIZ = 1L

/** Pasta ou arquivo do índice (mesma tabela `nos` do TeleCloud do Windows). */
data class No(val id: Long, val nome: String, val pasta: Boolean, val tamanho: Long, val modificado: Double)

data class Parte(val seq: Int, val ref: String, val tamanho: Long)

/** Assinatura de um item do índice para comparar duas versões (por caminho completo). */
data class Assinatura(val pasta: Boolean, val tamanho: Long, val modificado: Long)

/** Índice SQLite que o TeleCloud do Windows guarda no grupo do Telegram (tabelas `nos` e `partes`). */
class Indice(private val arquivo: File) {
    private var bd = abrir()

    private fun abrir() = SQLiteDatabase.openDatabase(arquivo.path, null, SQLiteDatabase.OPEN_READWRITE)

    fun listar(pai: Long): List<No> {
        val r = ArrayList<No>()
        bd.rawQuery(
            "SELECT id, nome, pasta, tamanho, modificado FROM nos WHERE pai = ? " +
                "ORDER BY pasta DESC, nome COLLATE NOCASE",
            arrayOf(pai.toString()),
        ).use { c ->
            while (c.moveToNext()) {
                r += No(c.getLong(0), c.getString(1), c.getInt(2) != 0, c.getLong(3), c.getDouble(4))
            }
        }
        return r
    }

    /** Todos os itens do índice por caminho completo ("Backups/a.zip"), para descobrir o que mudou entre duas versões. */
    fun mapa(): Map<String, Assinatura> {
        class Linha(val pai: Long?, val nome: String, val a: Assinatura)
        val linhas = HashMap<Long, Linha>()
        bd.rawQuery("SELECT id, pai, nome, pasta, tamanho, modificado FROM nos", null).use { c ->
            while (c.moveToNext()) {
                linhas[c.getLong(0)] = Linha(
                    if (c.isNull(1)) null else c.getLong(1), c.getString(2),
                    Assinatura(c.getInt(3) != 0, c.getLong(4), c.getDouble(5).toLong()),
                )
            }
        }
        val caminhos = HashMap<Long, String>()
        fun caminho(id: Long): String {
            caminhos[id]?.let { return it }
            val n = linhas[id] ?: return ""
            val r = if (n.pai == null) "" else if (n.pai == RAIZ) n.nome else caminho(n.pai) + "/" + n.nome
            caminhos[id] = r
            return r
        }
        val saida = HashMap<String, Assinatura>()
        for ((id, n) in linhas) if (n.pai != null) saida[caminho(id)] = n.a
        return saida
    }

    fun existe(id: Long): Boolean =
        bd.rawQuery("SELECT 1 FROM nos WHERE id = ?", arrayOf(id.toString())).use { it.moveToFirst() }

    fun partes(no: Long): List<Parte> {
        val r = ArrayList<Parte>()
        bd.rawQuery("SELECT seq, ref, tamanho FROM partes WHERE no = ? ORDER BY seq", arrayOf(no.toString())).use { c ->
            while (c.moveToNext()) r += Parte(c.getInt(0), c.getString(1), c.getLong(2))
        }
        return r
    }

    /**
     * Grava (ou substitui) um arquivo na pasta [pai], como o `gravar` do TeleCloud do Windows.
     * Devolve as referências das partes antigas, que o chamador apaga do Telegram depois de salvar o índice.
     */
    fun gravarArquivo(pai: Long, nome: String, partes: List<Parte>): List<String> {
        val agora = System.currentTimeMillis() / 1000.0
        val total = partes.sumOf { it.tamanho }
        var antigas = emptyList<String>()
        bd.beginTransaction()
        try {
            var id = -1L
            bd.rawQuery(
                "SELECT id, pasta FROM nos WHERE pai = ? AND nome = ? COLLATE NOCASE", arrayOf(pai.toString(), nome),
            ).use { c ->
                if (c.moveToFirst()) {
                    if (c.getInt(1) != 0) throw IllegalStateException("Já existe uma pasta chamada \"$nome\" aqui.")
                    id = c.getLong(0)
                }
            }
            if (id >= 0) {
                antigas = partes(id).map { it.ref }
            } else {
                bd.execSQL(
                    "INSERT INTO nos(pai, nome, pasta, tamanho, modificado) VALUES(?,?,0,0,?)",
                    arrayOf<Any>(pai, nome, agora),
                )
                bd.rawQuery("SELECT last_insert_rowid()", null).use { c -> c.moveToFirst(); id = c.getLong(0) }
            }
            bd.execSQL("DELETE FROM partes WHERE no = ?", arrayOf<Any>(id))
            for (p in partes) {
                bd.execSQL("INSERT INTO partes(no, seq, ref, tamanho) VALUES(?,?,?,?)", arrayOf<Any>(id, p.seq, p.ref, p.tamanho))
            }
            bd.execSQL("UPDATE nos SET tamanho = ?, modificado = ? WHERE id = ?", arrayOf<Any>(total, agora, id))
            bd.setTransactionSuccessful()
        } finally {
            bd.endTransaction()
        }
        return antigas
    }

    /** Cópia do índice para o Telegram: zlib sobre o arquivo SQLite, igual ao `exportar` do Windows. */
    fun exportar(): ByteArray {
        bd.rawQuery("PRAGMA wal_checkpoint(TRUNCATE)", null).use { it.moveToFirst() }
        bd.close()
        try {
            val saida = ByteArrayOutputStream()
            DeflaterOutputStream(saida, Deflater(6)).use { z -> arquivo.inputStream().use { it.copyTo(z) } }
            return saida.toByteArray()
        } finally {
            bd = abrir()
        }
    }

    fun fechar() = bd.close()
}

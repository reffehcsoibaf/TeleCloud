package br.com.fabioscheffer.telecloud

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MudancasTest {
    private fun arq(t: Long = 10, m: Long = 1) = Assinatura(false, t, m)
    private val pasta = Assinatura(true, 0, 1)

    @Test
    fun semMudancaFicaVazio() {
        val m = mapOf("Backups" to pasta, "Backups/a.zip" to arq())
        assertEquals("", descreverMudancas(m, m))
    }

    @Test
    fun arquivoMovidoDaRaizParaPasta() {
        val antes = mapOf("Backups" to pasta, "a.zip" to arq(50))
        val depois = mapOf("Backups" to pasta, "Backups/a.zip" to arq(50))
        assertEquals("a.zip movido de TeleCloud para Backups", descreverMudancas(antes, depois))
    }

    @Test
    fun novoERemovidoEAlterado() {
        val antes = mapOf("x.bin" to arq(1), "y.bin" to arq(2, 1))
        val depois = mapOf("novo.bin" to arq(3), "y.bin" to arq(2, 9))
        val t = descreverMudancas(antes, depois)
        assertTrue(t, t.contains("Novo: novo.bin em TeleCloud"))
        assertTrue(t, t.contains("Removido: x.bin de TeleCloud"))
        assertTrue(t, t.contains("Alterado: y.bin"))
    }

    @Test
    fun limitaAQuatroLinhas() {
        val depois = (1..7).associate { "f$it.bin" to arq(it.toLong()) }
        val t = descreverMudancas(emptyMap(), depois)
        assertTrue(t, t.endsWith("E mais 3 mudança(s)"))
    }

    @Test
    fun pastaRenomeadaNaoListaOsArquivosDeDentro() {
        val antes = mapOf(
            "Velha" to pasta, "Velha/a.zip" to arq(5), "Velha/sub" to pasta, "Velha/sub/b.zip" to arq(6), "Outra" to pasta,
        )
        val depois = mapOf(
            "Nova" to pasta, "Nova/a.zip" to arq(5), "Nova/sub" to pasta, "Nova/sub/b.zip" to arq(6), "Outra" to pasta,
        )
        assertEquals("Pasta Velha renomeada para Nova", descreverMudancas(antes, depois))
    }

    @Test
    fun arquivoRenomeadoNaMesmaPasta() {
        val antes = mapOf("P" to pasta, "P/x.bin" to arq(7, 3))
        val depois = mapOf("P" to pasta, "P/y.bin" to arq(7, 3))
        assertEquals("x.bin renomeado para y.bin", descreverMudancas(antes, depois))
    }

    @Test
    fun pastaRenomeadaMaisArquivoNovoDentro() {
        val antes = mapOf("A" to pasta, "A/f.bin" to arq(1))
        val depois = mapOf("B" to pasta, "B/f.bin" to arq(1), "B/g.bin" to arq(2))
        val t = descreverMudancas(antes, depois)
        // Conteúdo diferente: não é possível afirmar que foi só renomeação; não pode sumir nada em silêncio.
        assertTrue(t, t.isNotEmpty())
    }
}

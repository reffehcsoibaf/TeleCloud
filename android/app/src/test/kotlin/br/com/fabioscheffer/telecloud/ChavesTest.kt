package br.com.fabioscheffer.telecloud

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ChavesTest {
    @Test
    fun leChavesNumericasEEmTexto() {
        assertEquals(12345 to "abcdef0123456789", lerChaves("""{"api_id": 12345, "api_hash": "abcdef0123456789"}"""))
        assertEquals(12345 to "abcdef0123456789", lerChaves("""{"api_id": "12345", "api_hash": " abcdef0123456789 "}"""))
    }

    @Test
    fun recusaConteudoInvalido() {
        assertNull(lerChaves("isto não é json"))
        assertNull(lerChaves("""{"api_id": 0, "api_hash": "abcdef0123456789"}"""))
        assertNull(lerChaves("""{"api_id": 1, "api_hash": "curto"}"""))
        assertNull(lerChaves("""{"api_hash": "abcdef0123456789"}"""))
    }
}

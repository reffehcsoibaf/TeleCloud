package br.com.fabioscheffer.telecloud

import android.content.Context
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Log de erros do app: `files/telecloud.log` (no PC: `adb shell run-as <pacote> cat files/telecloud.log`). */
object Registro {
    private const val MAX = 200_000L

    @Synchronized
    fun info(ctx: Context, texto: String) {
        Log.i("TeleCloud", texto)
        runCatching {
            val f = File(ctx.filesDir, "telecloud.log")
            if (f.length() > MAX) f.delete()
            val hora = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())
            f.appendText("$hora  $texto\n\n")
        }
    }

    @Synchronized
    fun erro(ctx: Context, onde: String, e: Throwable) {
        Log.e("TeleCloud", onde, e)
        runCatching {
            val f = File(ctx.filesDir, "telecloud.log")
            if (f.length() > MAX) f.delete()
            val hora = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())
            f.appendText("$hora  $onde\n${Log.getStackTraceString(e)}\n")
        }
    }
}

package br.com.fabioscheffer.telecloud

import android.app.Application

class TeleCloudApp : Application() {
    val td by lazy { Td(this) }
    val nuvem by lazy { Nuvem(td, this) }
}

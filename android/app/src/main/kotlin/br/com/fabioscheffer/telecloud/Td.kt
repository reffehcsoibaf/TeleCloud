package br.com.fabioscheffer.telecloud

import android.content.Context
import android.os.Build
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.drinkless.tdlib.Client
import org.drinkless.tdlib.TdApi

/**
 * Lê as chaves do arquivo telecloud-config.json gerado no Windows: {"api_id": 123, "api_hash": "..."}.
 * Devolve (api_id, api_hash) ou null se o conteúdo não servir.
 */
fun lerChaves(json: String): Pair<Int, String>? = try {
    val o = org.json.JSONObject(json)
    val id = o.opt("api_id").toString().trim().toIntOrNull()
    val hash = o.optString("api_hash").trim()
    if (id != null && id > 0 && hash.length >= 8) id to hash else null
} catch (e: Exception) {
    null
}

/** Passos do login, na ordem em que a TDLib os pede. */
enum class Etapa { Iniciando, Chaves, Telefone, Codigo, Senha, Pronto, Encerrado }

/**
 * Liga o app à TDLib (cliente oficial do Telegram). As chaves api_id/api_hash são as mesmas que o
 * TeleCloud do Windows usa; ficam só no armazenamento privado do app, nunca no código.
 */
class Td(private val ctx: Context) {
    private val prefs = ctx.getSharedPreferences("telecloud", Context.MODE_PRIVATE)
    private var client: Client? = null

    private val _etapa = MutableStateFlow(Etapa.Iniciando)
    val etapa: StateFlow<Etapa> = _etapa
    private val _erro = MutableStateFlow<String?>(null)
    val erro: StateFlow<String?> = _erro
    private val _dica = MutableStateFlow("")

    /** Texto de apoio do passo atual (ex.: para onde o código foi enviado). */
    val dica: StateFlow<String> = _dica

    fun iniciar() {
        if (client != null) return
        if (BuildConfig.API_ID != 0 && BuildConfig.API_HASH.isNotBlank()) {
            prefs.edit().putInt("api_id", BuildConfig.API_ID).putString("api_hash", BuildConfig.API_HASH).apply()
        }
        if (prefs.getInt("api_id", 0) == 0 || prefs.getString("api_hash", "").isNullOrBlank()) {
            _etapa.value = Etapa.Chaves
            return
        }
        client = Client.create({ obj -> aoReceber(obj) }, null, null)
    }

    fun salvarChaves(apiId: String, apiHash: String) {
        val id = apiId.trim().toIntOrNull()
        val hash = apiHash.trim()
        if (id == null || id <= 0 || hash.length < 8) {
            _erro.value = "Confira o api_id (só números) e o api_hash."
            return
        }
        _erro.value = null
        prefs.edit().putInt("api_id", id).putString("api_hash", hash).apply()
        iniciar()
    }

    /** Importa as chaves do conteúdo de um telecloud-config.json; devolve true se deu certo. */
    fun importarChaves(json: String): Boolean {
        val chaves = lerChaves(json)
        if (chaves == null) {
            _erro.value = "Esse arquivo não tem as chaves do TeleCloud (api_id e api_hash)."
            return false
        }
        salvarChaves(chaves.first.toString(), chaves.second)
        return true
    }

    fun enviarTelefone(telefone: String) = pedir(TdApi.SetAuthenticationPhoneNumber(telefone.trim(), null))
    fun enviarCodigo(codigo: String) = pedir(TdApi.CheckAuthenticationCode(codigo.trim()))
    fun enviarSenha(senha: String) = pedir(TdApi.CheckAuthenticationPassword(senha))

    /** Envia uma chamada à TDLib e espera o resultado; erro do Telegram vira exceção. */
    @Suppress("UNCHECKED_CAST")
    suspend fun <T : TdApi.Object> chamar(f: TdApi.Function<T>): T =
        kotlinx.coroutines.suspendCancellableCoroutine { cont ->
            val c = client
            if (c == null) {
                cont.resumeWith(Result.failure(IllegalStateException("Sem conexão com o Telegram.")))
            } else {
                c.send(f) { r ->
                    if (r is TdApi.Error) {
                        cont.resumeWith(Result.failure(IllegalStateException(traduzir(r))))
                    } else {
                        cont.resumeWith(Result.success(r as T))
                    }
                }
            }
        }

    private fun pedir(f: TdApi.Function<*>) {
        _erro.value = null
        client?.send(f) { r -> if (r is TdApi.Error) _erro.value = traduzir(r) }
    }

    /** Chamado para cada mensagem nova que chega a qualquer conversa (usado para perceber o índice novo). */
    @Volatile
    var aoNovaMensagem: ((TdApi.Message) -> Unit)? = null

    private val envios =java.util.concurrent.ConcurrentHashMap<Long, kotlinx.coroutines.CompletableDeferred<TdApi.Message>>()

    private fun aoReceber(obj: TdApi.Object) {
        when (obj) {
            is TdApi.UpdateAuthorizationState -> aoMudarEstado(obj.authorizationState)
            is TdApi.UpdateNewMessage -> aoNovaMensagem?.invoke(obj.message)
            is TdApi.UpdateMessageSendSucceeded ->
                envios.getOrPut(obj.oldMessageId) { kotlinx.coroutines.CompletableDeferred() }.complete(obj.message)
            is TdApi.UpdateMessageSendFailed ->
                envios.getOrPut(obj.oldMessageId) { kotlinx.coroutines.CompletableDeferred() }
                    .completeExceptionally(IllegalStateException(traduzir(obj.error)))
            else -> Unit
        }
    }

    /** Envia a mensagem e espera o Telegram confirmar; devolve a mensagem definitiva (com o id final). */
    suspend fun enviarMensagem(f: TdApi.SendMessage): TdApi.Message {
        val provisoria = chamar(f)
        val espera = envios.getOrPut(provisoria.id) { kotlinx.coroutines.CompletableDeferred() }
        try {
            return espera.await()
        } finally {
            envios.remove(provisoria.id)
        }
    }

    private fun aoMudarEstado(e: TdApi.AuthorizationState) {
        _dica.value = ""
        when (e) {
            is TdApi.AuthorizationStateWaitTdlibParameters -> enviarParametros()
            is TdApi.AuthorizationStateWaitPhoneNumber -> _etapa.value = Etapa.Telefone
            is TdApi.AuthorizationStateWaitCode -> {
                _dica.value = descreverEnvio(e.codeInfo)
                _etapa.value = Etapa.Codigo
            }
            is TdApi.AuthorizationStateWaitPassword -> {
                val d = e.passwordHint
                _dica.value = if (d.isNullOrBlank()) "" else "Dica da senha: $d"
                _etapa.value = Etapa.Senha
            }
            is TdApi.AuthorizationStateReady -> _etapa.value = Etapa.Pronto
            is TdApi.AuthorizationStateClosed -> {
                client = null
                _etapa.value = Etapa.Encerrado
            }
            else -> Unit
        }
    }

    private fun enviarParametros() {
        val p = TdApi.SetTdlibParameters().apply {
            useTestDc = false
            databaseDirectory = ctx.filesDir.resolve("td").absolutePath
            filesDirectory = ctx.filesDir.resolve("td-arquivos").absolutePath
            databaseEncryptionKey = ByteArray(0)
            useFileDatabase = true
            useChatInfoDatabase = true
            useMessageDatabase = true
            useSecretChats = false
            apiId = prefs.getInt("api_id", 0)
            apiHash = prefs.getString("api_hash", "") ?: ""
            systemLanguageCode = "pt-BR"
            deviceModel = Build.MODEL
            systemVersion = Build.VERSION.RELEASE
            applicationVersion = BuildConfig.VERSION_NAME
        }
        client?.send(p) { r -> if (r is TdApi.Error) _erro.value = traduzir(r) }
    }

    private fun descreverEnvio(i: TdApi.AuthenticationCodeInfo): String = when (i.type) {
        is TdApi.AuthenticationCodeTypeTelegramMessage ->
            "O código foi enviado como mensagem no app do Telegram em outro aparelho seu."
        is TdApi.AuthenticationCodeTypeSms -> "O código foi enviado por SMS para ${i.phoneNumber}."
        is TdApi.AuthenticationCodeTypeCall -> "O código será dito em uma ligação para ${i.phoneNumber}."
        else -> "O código foi enviado para ${i.phoneNumber}."
    }

    private fun traduzir(e: TdApi.Error): String = when {
        e.message.contains("PHONE_NUMBER_INVALID") -> "Número inválido. Use o formato +55 41 99999-9999."
        e.message.contains("PHONE_CODE_INVALID") -> "Código incorreto."
        e.message.contains("PHONE_CODE_EXPIRED") -> "O código expirou. Volte e peça outro."
        e.message.contains("PASSWORD_HASH_INVALID") -> "Senha incorreta."
        e.message.contains("FLOOD") || e.code == 429 -> "Muitas tentativas. Aguarde um pouco e tente de novo."
        else -> "Erro do Telegram: ${e.message}"
    }
}

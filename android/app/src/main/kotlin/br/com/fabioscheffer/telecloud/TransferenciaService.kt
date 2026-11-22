package br.com.fabioscheffer.telecloud

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Serviço em primeiro plano: mantém o app vivo enquanto há download ou envio em andamento, mesmo com a tela
 * apagada ou o app fechado, e mostra o andamento numa notificação.
 */
class TransferenciaService : Service() {
    private val escopo = CoroutineScope(Dispatchers.Main)
    private var job: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        criarCanal()
        val nuvem = (application as TeleCloudApp).nuvem
        iniciarPrimeiroPlano(notificacao(nuvem.transferencia.value.ifBlank { "Transferindo arquivos…" }))
        job?.cancel()
        job = escopo.launch {
            nuvem.transferencia.collect { texto ->
                if (texto.isNotBlank()) getSystemService(NotificationManager::class.java).notify(ID, notificacao(texto))
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        escopo.cancel()
        super.onDestroy()
    }

    private fun iniciarPrimeiroPlano(n: Notification) {
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(ID, n)
        }
    }

    private fun criarCanal() {
        val gerente = getSystemService(NotificationManager::class.java)
        if (gerente.getNotificationChannel(CANAL) == null) {
            gerente.createNotificationChannel(
                NotificationChannel(CANAL, "Transferências", NotificationManager.IMPORTANCE_LOW),
            )
        }
    }

    private fun notificacao(texto: String): Notification {
        val abrir = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return Notification.Builder(this, CANAL)
            .setContentTitle("TeleCloud")
            .setContentText(texto)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(abrir)
            .build()
    }

    companion object {
        private const val ID = 1
        private const val CANAL = "transferencias"

        fun iniciar(ctx: Context) {
            runCatching { ctx.startForegroundService(Intent(ctx, TransferenciaService::class.java)) }
        }

        fun parar(ctx: Context) {
            ctx.stopService(Intent(ctx, TransferenciaService::class.java))
        }
    }
}

package cl.ikercare.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

class MedicationReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val scheduleId = intent.getIntExtra("schedule_id", 0)
        val name = intent.getStringExtra("name") ?: "Medicamento"
        val dose = intent.getStringExtra("dose").orEmpty()
        val route = intent.getStringExtra("route").orEmpty()
        val clock = intent.getStringExtra("clock") ?: return
        val timezone = intent.getStringExtra("timezone") ?: java.time.ZoneId.systemDefault().id

        createChannel(context)
        val openIntent = Intent(context, MainActivity::class.java)
        val openPending = PendingIntent.getActivity(
            context,
            scheduleId,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val detail = listOf(dose, route).filter { it.isNotBlank() }.joinToString(" · ")
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Horario registrado: $name")
            .setContentText(if (detail.isBlank()) "Revisa la indicación vigente." else "$detail · Revisa la indicación vigente.")
            .setStyle(NotificationCompat.BigTextStyle().bigText(
                if (detail.isBlank())
                    "IkerCare te recuerda un horario registrado. Confirma siempre con la indicación médica vigente."
                else "$detail. IkerCare te recuerda un horario registrado. Confirma siempre con la indicación médica vigente."
            ))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(openPending)
            .setAutoCancel(true)
            .build()

        val allowed = Build.VERSION.SDK_INT < 33 ||
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        if (allowed) NotificationManagerCompat.from(context).notify(scheduleId, notification)

        // Reprograma el siguiente día después de disparar.
        MedicationReminderScheduler.scheduleOne(context, scheduleId, name, dose, route, clock, timezone)
    }

    private fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val channel = NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.notification_channel),
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description = context.getString(R.string.notification_channel_description)
            }
            manager.createNotificationChannel(channel)
        }
    }

    companion object { const val CHANNEL_ID = "medication_reminders" }
}

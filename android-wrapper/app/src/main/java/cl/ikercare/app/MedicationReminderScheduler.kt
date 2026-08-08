package cl.ikercare.app

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import org.json.JSONObject
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime

object MedicationReminderScheduler {
    private const val PREFS = "ikercare_native"
    private const val KEY_SCHEDULE = "medication_schedule_json"

    fun sync(context: Context, json: String) {
        // Cancela primero el horario anterior; así también desaparecen alarmas
        // de medicamentos que ya fueron retirados del plan.
        cancelAllKnown(context)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_SCHEDULE, json).apply()
        scheduleFromJson(context, json)
    }

    fun restore(context: Context) {
        val json = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_SCHEDULE, null) ?: return
        scheduleFromJson(context, json)
    }

    private fun scheduleFromJson(context: Context, json: String) {
        runCatching {
            val root = JSONObject(json)
            val timezone = root.optString("timezone", ZoneId.systemDefault().id)
            val items = root.optJSONArray("items") ?: return
            for (index in 0 until items.length()) {
                val item = items.getJSONObject(index)
                scheduleOne(
                    context = context,
                    scheduleId = item.getInt("schedule_id"),
                    name = item.optString("name", "Medicamento"),
                    dose = item.optString("dose", ""),
                    route = item.optString("route", ""),
                    clock = item.getString("time"),
                    timezone = timezone,
                )
            }
        }
    }

    fun scheduleOne(
        context: Context,
        scheduleId: Int,
        name: String,
        dose: String,
        route: String,
        clock: String,
        timezone: String,
    ) {
        val zone = runCatching { ZoneId.of(timezone) }.getOrElse { ZoneId.systemDefault() }
        val localTime = runCatching { LocalTime.parse(clock) }.getOrElse { return }
        var next = ZonedDateTime.now(zone).withHour(localTime.hour).withMinute(localTime.minute).withSecond(0).withNano(0)
        if (!next.isAfter(ZonedDateTime.now(zone))) next = next.plusDays(1)

        val intent = Intent(context, MedicationReminderReceiver::class.java).apply {
            putExtra("schedule_id", scheduleId)
            putExtra("name", name)
            putExtra("dose", dose)
            putExtra("route", route)
            putExtra("clock", clock)
            putExtra("timezone", timezone)
        }
        val pending = PendingIntent.getBroadcast(
            context,
            scheduleId,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        // Deliberadamente inexacto: evita pedir acceso especial a alarmas exactas.
        // IkerCare es apoyo familiar, no una alarma clínica ni un dispositivo médico.
        alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, next.toInstant().toEpochMilli(), pending)
    }

    private fun cancelAllKnown(context: Context) {
        val json = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_SCHEDULE, null) ?: return
        runCatching {
            val items = JSONObject(json).optJSONArray("items") ?: return
            val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            for (index in 0 until items.length()) {
                val scheduleId = items.getJSONObject(index).optInt("schedule_id", -1)
                if (scheduleId < 0) continue
                val intent = Intent(context, MedicationReminderReceiver::class.java)
                val pending = PendingIntent.getBroadcast(
                    context,
                    scheduleId,
                    intent,
                    PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE,
                )
                if (pending != null) alarmManager.cancel(pending)
            }
        }
    }
}

package com.birdfy.viewer;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;

/**
 * Foreground service that holds a streaming connection to a self-hosted ntfy
 * topic and raises an Android notification for each new bird event. No Google
 * Play Services / FCM required — works on a de-Googled phone.
 *
 * The capture server publishes to ntfy when a new event's image.jpg arrives;
 * the message body is the event id, the title is human text.
 */
public class NtfyService extends Service {

    static volatile boolean running = false;
    private static final String FG_CHANNEL = "birdfy_watch";
    private static final String EV_CHANNEL = "birdfy_events";
    private static final int FG_ID = 1;
    private static final AtomicInteger evId = new AtomicInteger(1000);

    private volatile boolean stop = false;
    private Thread worker;

    static void start(Context ctx) {
        ctx.getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE)
                .edit().putString("watchEnabled", "1").apply();
        Intent i = new Intent(ctx, NtfyService.class);
        if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i);
        else ctx.startService(i);
    }

    static void stop(Context ctx) {
        ctx.getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE)
                .edit().putString("watchEnabled", "0").apply();
        ctx.stopService(new Intent(ctx, NtfyService.class));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createChannels();
        startForegroundSafe();
        running = true;
        worker = new Thread(this::loop, "ntfy-loop");
        worker.start();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        stop = true;
        running = false;
        if (worker != null) worker.interrupt();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    private void loop() {
        long backoff = 2000;
        while (!stop) {
            HttpURLConnection c = null;
            try {
                SharedPreferences p = getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE);
                String base = p.getString("ntfyUrl", "").trim();
                String topic = p.getString("ntfyTopic", "").trim();
                if (base.isEmpty() || topic.isEmpty()) { Thread.sleep(5000); continue; }
                if (base.endsWith("/")) base = base.substring(0, base.length() - 1);

                URL url = new URL(base + "/" + topic + "/json");
                c = (HttpURLConnection) url.openConnection();
                c.setReadTimeout(0);            // stream stays open
                c.setConnectTimeout(15000);
                String token = p.getString("ntfyToken", "").trim();
                if (!token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
                c.connect();

                BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream()));
                backoff = 2000; // connected: reset backoff
                String line;
                while (!stop && (line = r.readLine()) != null) {
                    if (line.isEmpty()) continue;
                    handleLine(line);
                }
            } catch (Throwable t) {
                // fall through to backoff
            } finally {
                if (c != null) try { c.disconnect(); } catch (Throwable ignored) {}
            }
            if (stop) break;
            try { Thread.sleep(backoff); } catch (InterruptedException e) { break; }
            backoff = Math.min(backoff * 2, 60000);
        }
    }

    private void handleLine(String line) {
        try {
            JSONObject o = new JSONObject(line);
            String event = o.optString("event", "message");
            if (!"message".equals(event)) return; // skip keepalive/open
            String body = o.optString("message", "");
            String title = o.optString("title", "Bird spotted");
            notifyEvent(title, body);
        } catch (Throwable ignored) {}
    }

    private void notifyEvent(String title, String eventId) {
        Intent open = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        if (eventId != null && !eventId.isEmpty()) open.putExtra("openEvent", eventId);
        int piFlags = PendingIntent.FLAG_UPDATE_CURRENT
                | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent pi = PendingIntent.getActivity(this, evId.get(), open, piFlags);

        Notification.Builder b = (Build.VERSION.SDK_INT >= 26)
                ? new Notification.Builder(this, EV_CHANNEL)
                : new Notification.Builder(this);
        b.setSmallIcon(android.R.drawable.ic_menu_camera)
                .setContentTitle(title)
                .setContentText(eventId == null || eventId.isEmpty() ? "New motion event" : "Tap to view")
                .setAutoCancel(true)
                .setContentIntent(pi);
        nm().notify(evId.incrementAndGet(), b.build());
    }

    private void startForegroundSafe() {
        Notification n = (Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, FG_CHANNEL)
                : new Notification.Builder(this))
                .setSmallIcon(android.R.drawable.ic_menu_view)
                .setContentTitle("Birdfy")
                .setContentText("Watching for birds")
                .setOngoing(true)
                .build();
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(FG_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            } else {
                startForeground(FG_ID, n);
            }
        } catch (Throwable t) {
            startForeground(FG_ID, n);
        }
    }

    private void createChannels() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager m = nm();
        NotificationChannel fg = new NotificationChannel(
                FG_CHANNEL, "Watch service", NotificationManager.IMPORTANCE_LOW);
        fg.setShowBadge(false);
        NotificationChannel ev = new NotificationChannel(
                EV_CHANNEL, "Bird events", NotificationManager.IMPORTANCE_HIGH);
        m.createNotificationChannel(fg);
        m.createNotificationChannel(ev);
    }

    private NotificationManager nm() {
        return (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
    }
}

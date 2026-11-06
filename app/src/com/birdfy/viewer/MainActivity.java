package com.birdfy.viewer;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.Toast;

/**
 * Thin native shell: hosts the viewer UI (assets/index.html) in a WebView and
 * exposes a small bridge for persistent settings and controlling the ntfy
 * background push service. All gallery / playback / recognition logic lives in
 * the web UI; the native side exists for WebView + real background notifications.
 */
public class MainActivity extends Activity {

    static final String PREFS = "birdfy";
    private WebView web;
    private String pendingEvent; // event id to open, delivered from a notification tap

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        pendingEvent = getIntent() != null ? getIntent().getStringExtra("openEvent") : null;

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        web.setWebChromeClient(new WebChromeClient());
        web.addJavascriptInterface(new Bridge(), "Android");
        setContentView(web);

        web.loadUrl("file:///android_asset/index.html");

        if (Build.VERSION.SDK_INT >= 33) requestNotifPermission();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String ev = intent != null ? intent.getStringExtra("openEvent") : null;
        if (ev != null && web != null) {
            final String e = ev.replace("'", "");
            web.post(() -> web.evaluateJavascript("window.openEvent && window.openEvent('" + e + "')", null));
        }
    }

    private void requestNotifPermission() {
        try {
            if (checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1);
            }
        } catch (Throwable ignored) {}
    }

    /** JS-callable bridge. Everything here runs on a binder thread. */
    public class Bridge {
        @JavascriptInterface
        public String getPref(String key, String def) {
            return prefs().getString(key, def);
        }

        @JavascriptInterface
        public void setPref(String key, String val) {
            prefs().edit().putString(key, val).apply();
        }

        @JavascriptInterface
        public void startWatch() {
            NtfyService.start(MainActivity.this);
        }

        @JavascriptInterface
        public void stopWatch() {
            NtfyService.stop(MainActivity.this);
        }

        @JavascriptInterface
        public boolean isWatching() {
            return NtfyService.running;
        }

        @JavascriptInterface
        public String takePendingEvent() {
            String e = pendingEvent;
            pendingEvent = null;
            return e == null ? "" : e;
        }

        @JavascriptInterface
        public void toast(String msg) {
            runOnUiThread(() -> Toast.makeText(MainActivity.this, msg, Toast.LENGTH_SHORT).show());
        }
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
}

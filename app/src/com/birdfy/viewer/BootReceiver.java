package com.birdfy.viewer;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Restarts the watch service after reboot if the user had it enabled. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context ctx, Intent intent) {
        if (intent == null || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        String enabled = ctx.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE)
                .getString("watchEnabled", "0");
        if ("1".equals(enabled)) NtfyService.start(ctx);
    }
}

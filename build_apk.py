"""
Builds AnyLocal.apk for Android using Android SDK build-tools and JDK.
Generates an installable, standalone Android application with:
- Fullscreen WebView
- Hardware acceleration (desynchronized canvas)
- Camera QR Scanner permissions
- Offline bundled assets
- High-res AnyLocal app icon
"""

import os
import sys
import shutil
import zipfile
import subprocess
from PIL import Image, ImageDraw, ImageFont

SDK_ROOT = r"C:\Users\Admin\AppData\Local\Android\Sdk"
BUILD_TOOLS = os.path.join(SDK_ROOT, "build-tools", "34.0.0")
PLATFORM_JAR = os.path.join(SDK_ROOT, "platforms", "android-34", "android.jar")
JDK_BIN = r"C:\Program Files\Java\jdk-17\bin"

AAPT2 = os.path.join(BUILD_TOOLS, "aapt2.exe")
D8 = os.path.join(BUILD_TOOLS, "d8.bat")
ZIPALIGN = os.path.join(BUILD_TOOLS, "zipalign.exe")
APKSIGNER = os.path.join(BUILD_TOOLS, "apksigner.bat")
JAVAC = os.path.join(JDK_BIN, "javac.exe")
KEYTOOL = os.path.join(JDK_BIN, "keytool.exe")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
BUILD_DIR = os.path.join(BASE_DIR, "android_build")
DIST_DIR = os.path.join(BASE_DIR, "dist")
WEB_DIR = os.path.join(BASE_DIR, "web")

def create_app_icon(out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img = Image.new("RGBA", (192, 192), (15, 23, 42, 255))
    draw = ImageDraw.Draw(img)
    # Background rounded card
    draw.rounded_rectangle([(16, 16), (176, 176)], radius=36, fill=(2, 132, 199, 255), outline=(56, 189, 248, 255), width=4)
    # Inner monitor screen
    draw.rounded_rectangle([(40, 44), (152, 128)], radius=12, fill=(15, 23, 42, 255), outline=(255, 255, 255, 200), width=3)
    # Monitor stand
    draw.rectangle([(88, 128), (104, 146)], fill=(203, 213, 225, 255))
    draw.rounded_rectangle([(64, 146), (128, 154)], radius=4, fill=(203, 213, 225, 255))
    # Lightning bolt inside screen
    points = [(100, 56), (78, 86), (96, 86), (92, 116), (116, 82), (98, 82)]
    draw.polygon(points, fill=(56, 189, 248, 255))
    img.save(out_path, "PNG")

def main():
    print("=" * 50)
    print("Building AnyLocal Standalone Android APK...")
    print("=" * 50)

    os.makedirs(DIST_DIR, exist_ok=True)
    os.makedirs(BUILD_DIR, exist_ok=True)

    # 1. Generate Icon
    icon_path = os.path.join(BUILD_DIR, "res", "mipmap-xxxhdpi", "ic_launcher.png")
    icon_default = os.path.join(BUILD_DIR, "res", "mipmap", "ic_launcher.png")
    create_app_icon(icon_path)
    create_app_icon(icon_default)

    # 2. Strings.xml
    res_values = os.path.join(BUILD_DIR, "res", "values")
    os.makedirs(res_values, exist_ok=True)
    with open(os.path.join(res_values, "strings.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">AnyLocal</string>\n</resources>\n')

    # 3. AndroidManifest.xml
    manifest_path = os.path.join(BUILD_DIR, "AndroidManifest.xml")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write('''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.anylocal.remote"
    android:versionCode="2"
    android:versionName="1.1.0">

    <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="34" />

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-permission android:name="android.permission.VIBRATE" />
    <uses-permission android:name="android.permission.WAKE_LOCK" />

    <uses-feature android:name="android.hardware.camera" android:required="false" />

    <application
        android:label="AnyLocal"
        android:icon="@mipmap/ic_launcher"
        android:hardwareAccelerated="true"
        android:usesCleartextTraffic="true"
        android:theme="@android:style/Theme.NoTitleBar.Fullscreen">

        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize|keyboardHidden|smallestScreenSize|screenLayout"
            android:windowSoftInputMode="adjustResize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
''')

    # 4. Copy Web Assets
    assets_dir = os.path.join(BUILD_DIR, "assets")
    if os.path.exists(assets_dir):
        shutil.rmtree(assets_dir)
    shutil.copytree(WEB_DIR, assets_dir)

    # 5. MainActivity.java
    src_dir = os.path.join(BUILD_DIR, "src", "com", "anylocal", "remote")
    os.makedirs(src_dir, exist_ok=True)
    with open(os.path.join(src_dir, "MainActivity.java"), "w", encoding="utf-8") as f:
        f.write('''package com.anylocal.remote;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.webkit.PermissionRequest;
import android.view.Window;
import android.view.WindowManager;
import android.view.View;
import android.content.pm.PackageManager;
import android.Manifest;

public class MainActivity extends Activity {
    private WebView mWebView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN, WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        mWebView = new WebView(this);
        setContentView(mWebView);

        WebSettings settings = mWebView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);

        // Hardware Acceleration
        mWebView.setLayerType(View.LAYER_TYPE_HARDWARE, null);

        mWebView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return false;
            }
        });

        mWebView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                request.grant(request.getResources());
            }
            @Override
            public boolean onJsAlert(WebView view, String url, String message, final android.webkit.JsResult result) {
                new android.app.AlertDialog.Builder(MainActivity.this)
                    .setTitle("AnyLocal")
                    .setMessage(message)
                    .setPositiveButton(android.R.string.ok, (dialog, which) -> result.confirm())
                    .setCancelable(false)
                    .create()
                    .show();
                return true;
            }
            @Override
            public boolean onJsConfirm(WebView view, String url, String message, final android.webkit.JsResult result) {
                new android.app.AlertDialog.Builder(MainActivity.this)
                    .setTitle("AnyLocal")
                    .setMessage(message)
                    .setPositiveButton(android.R.string.ok, (dialog, which) -> result.confirm())
                    .setNegativeButton(android.R.string.cancel, (dialog, which) -> result.cancel())
                    .setCancelable(false)
                    .create()
                    .show();
                return true;
            }
        });

        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, 101);
        }

        mWebView.loadUrl("file:///android_asset/index.html");
    }

    @Override
    public void onBackPressed() {
        if (mWebView.canGoBack()) {
            mWebView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
''')

    # Step A: Compile Resources with AAPT2
    print("[1/6] Compiling Android resources with AAPT2...")
    compiled_res = os.path.join(BUILD_DIR, "compiled_res.zip")
    if os.path.exists(compiled_res):
        os.remove(compiled_res)
    res_dir = os.path.join(BUILD_DIR, "res")
    cmd_aapt_compile = [AAPT2, "compile", "--dir", res_dir, "-o", compiled_res]
    subprocess.check_call(cmd_aapt_compile)

    # Step B: Link Resources
    print("[2/6] Linking APK and generating R.java...")
    gen_dir = os.path.join(BUILD_DIR, "gen")
    os.makedirs(gen_dir, exist_ok=True)
    unaligned_apk = os.path.join(BUILD_DIR, "unaligned.apk")
    if os.path.exists(unaligned_apk):
        os.remove(unaligned_apk)

    cmd_aapt_link = [
        AAPT2, "link",
        compiled_res,
        "-I", PLATFORM_JAR,
        "--manifest", manifest_path,
        "-A", assets_dir,
        "-o", unaligned_apk,
        "--java", gen_dir
    ]
    subprocess.check_call(cmd_aapt_link)

    # Step C: Compile Java Sources
    print("[3/6] Compiling Java source files with javac...")
    classes_dir = os.path.join(BUILD_DIR, "bin", "classes")
    os.makedirs(classes_dir, exist_ok=True)
    r_java = os.path.join(gen_dir, "com", "anylocal", "remote", "R.java")
    main_java = os.path.join(src_dir, "MainActivity.java")

    cmd_javac = [
        JAVAC,
        "-cp", PLATFORM_JAR,
        "-d", classes_dir,
        r_java,
        main_java
    ]
    subprocess.check_call(cmd_javac)

    # Step D: Dexing with D8
    print("[4/6] Converting bytecode to Dalvik Executable (classes.dex) with D8...")
    dex_dir = os.path.join(BUILD_DIR, "bin", "dex")
    os.makedirs(dex_dir, exist_ok=True)
    class_files = []
    class_pkg = os.path.join(classes_dir, "com", "anylocal", "remote")
    for f in os.listdir(class_pkg):
        if f.endswith(".class"):
            class_files.append(os.path.join(class_pkg, f))

    cmd_d8 = [D8, "--lib", PLATFORM_JAR, "--output", dex_dir] + class_files
    subprocess.check_call(cmd_d8, shell=True)

    # Step E: Add classes.dex into unaligned.apk using Python zipfile
    print("[5/6] Bundling classes.dex into APK...")
    classes_dex = os.path.join(dex_dir, "classes.dex")
    with zipfile.ZipFile(unaligned_apk, 'a') as apk_zip:
        apk_zip.write(classes_dex, "classes.dex")

    # Step F: ZipAlign and Sign
    print("[6/6] Zipaligning and Signing AnyLocal.apk...")
    final_apk = os.path.join(DIST_DIR, "AnyLocal.apk")
    if os.path.exists(final_apk):
        os.remove(final_apk)

    cmd_zipalign = [ZIPALIGN, "-p", "-f", "-v", "4", unaligned_apk, final_apk]
    subprocess.check_call(cmd_zipalign)

    keystore_path = os.path.join(BUILD_DIR, "debug.keystore")
    cmd_sign = [
        APKSIGNER, "sign",
        "--ks", keystore_path,
        "--ks-pass", "pass:android",
        "--key-pass", "pass:android",
        final_apk
    ]
    subprocess.check_call(cmd_sign, shell=True)

    cmd_verify = [APKSIGNER, "verify", final_apk]
    subprocess.check_call(cmd_verify, shell=True)

    size_mb = os.path.getsize(final_apk) / (1024 * 1024)
    print("=" * 50)
    print(f"SUCCESS! APK built and signed successfully!")
    print(f"Output: {final_apk} ({size_mb:.2f} MB)")
    print("=" * 50)

if __name__ == "__main__":
    main()

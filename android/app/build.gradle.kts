plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "br.com.fabioscheffer.telecloud"
    compileSdk = 35

    defaultConfig {
        applicationId = "br.com.fabioscheffer.telecloud"
        minSdk = 26
        targetSdk = 35
        versionCode = 28
        versionName = "2026.11.22.26"
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64") }

        // Por padrão o APK NÃO leva as chaves api_id/api_hash: elas entram no celular pelo arquivo
        // telecloud-config.json (ferramentas\enviar_chaves_para_celular.bat) e ficam só no armazenamento do app.
        // Só com `gradlew -PembutirChaves=true` elas são lidas de ..\dados\config.json e embutidas no APK
        // (nesse caso, não compartilhe esse APK).
        var chaveId = 0
        var chaveHash = ""
        val cfg = rootProject.file("../dados/config.json")
        if (cfg.exists() && project.findProperty("embutirChaves") == "true") {
            @Suppress("UNCHECKED_CAST")
            val j = groovy.json.JsonSlurper().parseText(cfg.readText().removePrefix("﻿")) as Map<String, Any?>
            chaveId = (j["api_id"] as? Number)?.toInt() ?: 0
            chaveHash = (j["api_hash"] as? String) ?: ""
        }
        buildConfigField("int", "API_ID", chaveId.toString())
        buildConfigField("String", "API_HASH", "\"$chaveHash\"")
    }

    // A TDLib vem do fluxo de trabalho "TDLib para Android" (pasta ignorada pelo git).
    sourceSets["main"].java.srcDir("../tdlib-baixado/java")
    sourceSets["main"].jniLibs.srcDir("../tdlib-baixado/libs")

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    testOptions { unitTests.isReturnDefaultValues = true }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.10.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.annotation:annotation:1.9.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}

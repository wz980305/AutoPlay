import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("jvm")
    kotlin("plugin.serialization")
    application
}

dependencies {
    implementation(project(":protocol"))
    implementation("io.ktor:ktor-server-core:3.6.0")
    implementation("io.ktor:ktor-server-netty:3.6.0")
    implementation("io.ktor:ktor-server-websockets:3.6.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
    implementation("org.jmdns:jmdns:3.6.3")
    implementation("org.bouncycastle:bcpkix-jdk18on:1.79")
    implementation("org.slf4j:slf4j-simple:2.0.20")
    testImplementation("junit:junit:4.13.2")
}

// The boxes serve HTTP/1.1 and HTTP/2 over TLS on Linux: Ktor's Netty engine also brings HTTP/3 (QUIC with natives for
// five platforms, 11 MB) and the protobuf / JBoss Marshalling codecs, none of which they load. (kqueue stays: the engine
// names it on every start, 2026-10-20.)
configurations.named("runtimeClasspath") {
    exclude(group = "io.netty", module = "netty-codec-http3")
    exclude(group = "io.netty", module = "netty-codec-classes-quic")
    exclude(group = "io.netty", module = "netty-codec-native-quic")
    exclude(group = "io.netty", module = "netty-codec-protobuf")
    exclude(group = "io.netty", module = "netty-codec-marshalling")
}

java {
    sourceCompatibility = JavaVersion.VERSION_21
    targetCompatibility = JavaVersion.VERSION_21
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_21)
    }
}

application {
    mainClass.set("com.playport.server.MainKt")
    applicationDefaultJvmArgs = listOf("-Dorg.slf4j.simpleLogger.defaultLogLevel=info")
}

// Run from the repository root so ./identity and ./web/dist resolve by default.
tasks.named<JavaExec>("run") {
    workingDir = rootProject.projectDir
}

package com.shilapi.xcertplay.transport

import java.io.Closeable
import org.slf4j.LoggerFactory

/**
 * The iPhone's USBMUX bulk pipe in the CarPlay USB configuration (wired CarPlay with the accessory as
 * USB host). On Android this was a UsbDeviceConnection; on Linux a helper process owns the device
 * (see UsbBridgePipe in the server). One write is one bulk transfer.
 */
interface Iap2UsbSession : Closeable {
    fun write(data: ByteArray, timeoutMillis: Int)

    /** Returns null only when nothing arrived within [timeoutMillis]. */
    fun read(timeoutMillis: Long): ByteArray?
}

/** android.util.Log for the code taken over from the Android app; forwards to SLF4J. */
internal object Log {
    fun i(tag: String, message: String) = LoggerFactory.getLogger(tag).info(message)
    fun w(tag: String, message: String) = LoggerFactory.getLogger(tag).warn(message)
    fun d(tag: String, message: String) = LoggerFactory.getLogger(tag).debug(message)
    fun e(tag: String, message: String, error: Throwable? = null) = LoggerFactory.getLogger(tag).error(message, error)
}

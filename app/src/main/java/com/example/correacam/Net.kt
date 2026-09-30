package com.example.correacam

import java.net.Inet4Address
import java.net.NetworkInterface

object Net {
    /** IPv4 de la interfaz WiFi (o Ethernet / hotspot). No devuelve la de datos moviles. */
    fun localIp(): String? {
        return try {
            NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
                .filter {
                    it.isUp && !it.isLoopback &&
                        (it.name.startsWith("wlan") || it.name.startsWith("eth") || it.name.startsWith("ap"))
                }
                .flatMap { it.inetAddresses.toList() }
                .filterIsInstance<Inet4Address>()
                .firstOrNull()
                ?.hostAddress
        } catch (e: Exception) {
            null
        }
    }
}

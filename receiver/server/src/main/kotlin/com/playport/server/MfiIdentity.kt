package com.playport.server

import com.shilapi.xcertplay.mfi.LocalMfiAuthenticationClient
import com.shilapi.xcertplay.mfi.MfiAuthenticator
import java.nio.file.Files

/**
 * Loads the MFi authenticator from the local recovered identity (offline-mfi/identity.pk8 + certificate.p7b).
 * The remote MFi server client went with the dead-code trim: the box only ever ran with the offline identity.
 *
 * The offline identity is supplied by the deployment and never committed to this repository.
 */
object MfiIdentity {
    fun load(config: ServerConfig): MfiAuthenticator {
        val directory = config.mfiDirectory
        require(Files.isDirectory(directory)) {
            "MFi identity directory $directory is missing; place offline-mfi/identity.pk8 and " +
                "offline-mfi/certificate.p7b there"
        }
        val client = LocalMfiAuthenticationClient.load(directory.toFile())
        check(client.protocolMajor() == 3) { "Expected MFi protocol major 3" }
        return client
    }
}

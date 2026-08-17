package io.livekit.android.example.voiceassistant

/**
 * Where the glasses fetch their join token.
 *
 * This is agent/src/token_server.py running on the development machine. It must
 * be the machine's LAN address, not localhost, because the glasses resolve it on
 * their own network stack. Update it whenever that address changes.
 *
 * Cleartext http:// and ws:// only work because app/src/debug permits cleartext
 * traffic; a release build would refuse both.
 */
const val tokenEndpoint = "http://192.168.3.34:3000/getToken"

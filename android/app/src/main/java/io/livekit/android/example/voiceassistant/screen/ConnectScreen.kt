package io.livekit.android.example.voiceassistant.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.example.voiceassistant.TokenEndpoint
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.theme.Blue500
import kotlinx.serialization.Serializable

@Serializable
object ConnectRoute

@Composable
fun ConnectScreen(
    navigateToVoiceAssistant: (VoiceAssistantRoute) -> Unit
) {
    // Hoisted above Eyes on purpose: the content below is composed once per eye,
    // so state declared inside it would exist twice and the two copies would
    // disagree the moment either one changed. See Eyes.
    val context = LocalContext.current
    var endpoint by rememberSaveable { mutableStateOf(TokenEndpoint.get(context)) }
    var credential by rememberSaveable { mutableStateOf(TokenEndpoint.getCredential(context)) }

    Eyes {
        // Everything here has to fit one 640x480 panel, less the safe-area
        // margin Eyes applies — so roughly 592x432 dp to work with.
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.fillMaxSize()
        ) {
            Text(
                text = "RayNeo X3 Pro assistant",
                color = MaterialTheme.colorScheme.onBackground,
                fontSize = 20.sp
            )

            Spacer(Modifier.size(20.dp))

            // On screen only for the case where no cable is attached. Prefer
            // `adb shell am start ... -e token_endpoint <url>` when one is: the
            // IME is laid out across the full 1280 px surface, so it straddles
            // both eyes and is genuinely hard to use. See TokenEndpoint.
            OutlinedTextField(
                value = endpoint,
                onValueChange = { endpoint = it },
                label = { Text("Token endpoint") },
                singleLine = true,
                textStyle = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 13.sp),
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(Modifier.size(8.dp))

            // Sent as `Authorization: Bearer ...`. Blank is right when the
            // backend runs AUTH_MODE=dev. See TokenEndpoint.
            OutlinedTextField(
                value = credential,
                onValueChange = { credential = it },
                label = { Text("Credential (blank for dev)") },
                singleLine = true,
                textStyle = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 13.sp),
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(Modifier.size(16.dp))

            // Deliberately the full width of the eye. A temple-touchpad tap
            // lands somewhere you cannot see your own finger, which is why
            // RayNeo's SDK drives selection by focus (FocusHolder, the
            // *FocusTracker classes) instead of by pointing. A single target
            // that fills the panel needs neither approach to be hittable.
            Button(
                onClick = {
                    // Persist whatever is in the field so the next launch keeps it.
                    TokenEndpoint.set(context, endpoint)
                    TokenEndpoint.setCredential(context, credential)
                    navigateToVoiceAssistant(
                        VoiceAssistantRoute(
                            tokenEndpoint = endpoint.trim(),
                            credential = credential.trim(),
                        )
                    )
                },
                colors = ButtonDefaults.buttonColors(
                    containerColor = Blue500,
                    contentColor = Color.White
                ),
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(64.dp)
            ) {
                Text(
                    text = "START CALL",
                    style = TextStyle(
                        fontFamily = FontFamily.Monospace,
                        letterSpacing = 2.sp,
                        fontSize = 18.sp
                    )
                )
            }
        }
    }
}

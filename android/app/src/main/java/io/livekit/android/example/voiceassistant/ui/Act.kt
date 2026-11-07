package io.livekit.android.example.voiceassistant.ui

import android.os.SystemClock
import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import io.livekit.android.example.voiceassistant.CallLog
import io.livekit.android.room.participant.Participant
import io.livekit.android.util.flow

/**
 * What the agent does this instant, from its participant attribute `rayneo.agent` (guide.py `Build.act_now`): "yes n"
 * or "not n" the moment the agent's second line says the brick in the hand is or is not the step's, which the dots
 * flash green or red; "looking n" while the brain judges a placement it was called to, shown as the dots' LOOKING;
 * empty otherwise. The count makes every act a change of the attribute, so two "not"s in a row both flash. The
 * attribute rides the signalling channel like the step list, and so arrives even when the media does not; a value sent
 * again after a reconnect is the one already seen and does nothing.
 *
 * Every change is logged under `rayneo-agent` and as an `agent` event in CallLog with the wall clock, so a run's record
 * can put the glasses' moment beside the agent's (`moment_say`, `look_now` in the agent's record).
 */
data class Act(val looking: Boolean, val flash: Flash?) {
    companion object {
        val NONE = Act(looking = false, flash = null)
    }
}

@Composable
fun rememberAct(agent: Participant?): State<Act> {
    val attributes: Map<String, String> = if (agent == null) emptyMap() else agent::attributes.flow.collectAsState().value
    val value = attributes[ACT_ATTRIBUTE] ?: ""
    var act by remember { mutableStateOf(Act.NONE) }
    var seen by remember { mutableStateOf("") }
    LaunchedEffect(value) {
        if (value == seen) return@LaunchedEffect
        seen = value
        val at = System.currentTimeMillis()
        Log.i(ACT_TAG, "${value.ifEmpty { "idle" }} at=$at")
        CallLog.add("agent", mapOf("act" to value), at)
        act = when (value.substringBefore(' ')) {
            "yes", "not" -> Act(looking = false, flash = Flash(yes = value.startsWith("yes"), at = SystemClock.uptimeMillis()))
            "looking" -> Act(looking = true, flash = act.flash)
            else -> Act(looking = false, flash = act.flash)
        }
    }
    return rememberUpdatedState(act)
}

/** The attribute's name, as guide.py publishes it. */
private const val ACT_ATTRIBUTE = "rayneo.agent"

/** Log tag of the act lines; deploy/pull_run.py collects it into glasses.log. */
private const val ACT_TAG = "rayneo-agent"

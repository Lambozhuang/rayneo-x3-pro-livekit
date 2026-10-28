package io.livekit.android.example.voiceassistant

import io.livekit.android.example.voiceassistant.ui.BuildProgress
import org.junit.Assert.assertEquals
import org.junit.Test

/** BuildProgress reads the attributes as guide.py writes them (Build.attributes). */
class BuildProgressTest {
    @Test
    fun readsTheFishAsGuidePyPublishesIt() {
        val progress = BuildProgress.of(
            mapOf(
                "rayneo.build.title" to "LEGO fish on a baseplate",
                "rayneo.build.steps" to "Blue 2x6, body\nDark grey round, head\nRed 2x4, tail",
                "rayneo.build.step" to "1",
                "rayneo.picture" to "step-2.png",
            )
        )
        assertEquals("LEGO fish on a baseplate", progress.title)
        assertEquals(listOf("Blue 2x6, body", "Dark grey round, head", "Red 2x4, tail"), progress.steps)
        assertEquals(1, progress.current)
    }

    @Test
    fun noStepsMeansNoBuild() {
        assertEquals(BuildProgress.NONE, BuildProgress.of(emptyMap()))
    }
}

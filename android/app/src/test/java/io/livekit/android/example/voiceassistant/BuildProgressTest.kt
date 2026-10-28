package io.livekit.android.example.voiceassistant

import androidx.compose.ui.graphics.Color
import io.livekit.android.example.voiceassistant.ui.Brick
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
                "rayneo.build.bricks" to "#1e5bc6 7 7 12 8\n#555555 3 6 6 9 round\n#c8102e 13 6 14 9",
                "rayneo.build.plate" to "16",
                "rayneo.build.step" to "1",
                "rayneo.build.picture" to "2",
            )
        )
        assertEquals("LEGO fish on a baseplate", progress.title)
        assertEquals(listOf("Blue 2x6, body", "Dark grey round, head", "Red 2x4, tail"), progress.steps)
        assertEquals(1, progress.current)
        assertEquals(16, progress.plate)
        assertEquals(2, progress.picture)
        assertEquals(
            listOf(
                Brick(Color(0xFF1E5BC6), 7, 7, 12, 8),
                Brick(Color(0xFF555555), 3, 6, 6, 9, round = true),
                Brick(Color(0xFFC8102E), 13, 6, 14, 9),
            ),
            progress.bricks,
        )
    }

    @Test
    fun noStepsMeansNoBuild() {
        assertEquals(BuildProgress.NONE, BuildProgress.of(emptyMap()))
    }

    /** The agent publishes 0 when the square is to show the camera; a step past the last brick is not drawn either. */
    @Test
    fun zeroOrOutOfRangePictureMeansTheCamera() {
        val attributes = mapOf(
            "rayneo.build.steps" to "Blue 2x6, body",
            "rayneo.build.bricks" to "#1e5bc6 7 7 12 8",
            "rayneo.build.step" to "0",
        )
        assertEquals(null, BuildProgress.of(attributes + ("rayneo.build.picture" to "0")).picture)
        assertEquals(null, BuildProgress.of(attributes + ("rayneo.build.picture" to "2")).picture)
        assertEquals(1, BuildProgress.of(attributes + ("rayneo.build.picture" to "1")).picture)
    }
}

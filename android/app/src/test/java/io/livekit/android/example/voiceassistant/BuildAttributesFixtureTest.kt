package io.livekit.android.example.voiceassistant

import io.livekit.android.example.voiceassistant.ui.BuildProgress
import java.util.Properties
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Every guide's attributes as guide.py publishes them, read back by BuildProgress: one brick per step, every brick
 * inside the plate, a round plate square. The fixtures under src/test/resources/build_attributes are written by
 * backend/agent/write_build_fixture.py from Build.attributes(); run it after changing a task file or that method.
 */
class BuildAttributesFixtureTest {
    private fun resource(name: String) = javaClass.classLoader!!.getResourceAsStream("build_attributes/$name")!!

    @Test
    fun everyGuideReadsBack() {
        val names = resource("guides.txt").bufferedReader().readLines().filter { it.isNotBlank() }
        assertEquals(13, names.size)
        for (name in names) {
            val props = Properties().apply { resource("$name.properties").use { load(it) } }
            val p = BuildProgress.of(props.entries.associate { it.key as String to it.value as String })
            assertEquals(name, 5, p.steps.size)
            assertEquals(name, p.steps.size, p.bricks.size)
            assertEquals(name, 0, p.current)
            assertTrue(name, p.title.isNotEmpty())
            for (b in p.bricks) {
                assertTrue("$name: $b", b.col0 in 1..b.col1 && b.col1 <= p.plate && b.row0 in 1..b.row1 && b.row1 <= p.plate)
                if (b.round) assertEquals("$name: $b", b.col1 - b.col0, b.row1 - b.row0)
            }
        }
    }
}

package io.livekit.android.example.voiceassistant

import io.livekit.android.example.voiceassistant.ui.BuildProgress
import java.util.Properties
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Every guide's attributes as guide.py publishes them, read back by BuildProgress: a title, five steps for a build, six
 * rounds for a trial of the placement game, two picks for one of game A and none for free play, the first one current,
 * no picture named and no hint at the start. The fixtures under src/test/resources/build_attributes are written by backend/agent/write_build_fixture.py
 * from Build.attributes(); run it after changing a task file or that method.
 */
class BuildAttributesFixtureTest {
    private fun resource(name: String) = javaClass.classLoader!!.getResourceAsStream("build_attributes/$name")!!

    @Test
    fun everyGuideReadsBack() {
        val names = resource("guides.txt").bufferedReader().readLines().filter { it.isNotBlank() }
        assertEquals(26, names.size)
        for (name in names) {
            val props = Properties().apply { resource("$name.properties").use { load(it) } }
            val p = BuildProgress.of(props.entries.associate { it.key as String to it.value as String })
            assertEquals(name, if (name.startsWith("a-")) 2 else if (name.startsWith("b-")) 6 else if (name == "free") 0 else 5, p.steps.size)
            assertEquals(name, 0, p.current)
            assertTrue(name, p.title.isNotEmpty())
            assertEquals(name, "", p.hint)
            assertEquals(name, "", props.getProperty("rayneo.picture"))
        }
    }
}

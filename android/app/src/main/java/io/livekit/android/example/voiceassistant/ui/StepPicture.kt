package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import kotlin.math.hypot

/**
 * One brick on the plate: its colour and the cells it covers, columns and rows counted from 1 as task.toml's `cells`
 * counts them, the far edge of the plate at the top. A round plate covers its square but not the corners.
 */
data class Brick(val color: Color, val col0: Int, val row0: Int, val col1: Int, val row1: Int, val round: Boolean = false)

/**
 * The build as seen from above at the current step, drawn as tasks/sheet.html draws it: the plate as a grid of studs,
 * the bricks of the steps done in their colours, the brick of the current step in its colour with a white edge, the
 * bricks still to come not drawn. The plate is dark grey, not green: the display is additive, so a bright plate would
 * be a lamp in the wearer's eye and the bricks are what has to read.
 *
 * @param plate the plate's side in studs.
 * @param current index of the step being built; everything after it is left out. Equal to the count once finished,
 * which draws every brick and marks none.
 */
@Composable
fun StepPicture(plate: Int, bricks: List<Brick>, current: Int, modifier: Modifier = Modifier) {
    Canvas(modifier = modifier) {
        val cell = size.minDimension / plate
        drawRect(PLATE, size = Size(cell * plate, cell * plate))
        for (r in 0 until plate) for (c in 0 until plate) {
            drawCircle(STUD, radius = cell * 0.18f, center = Offset((c + 0.5f) * cell, (r + 0.5f) * cell))
        }
        for ((i, b) in bricks.withIndex()) {
            if (i > current) break
            val topLeft = Offset((b.col0 - 1) * cell, (b.row0 - 1) * cell)
            val extent = Size((b.col1 - b.col0 + 1) * cell, (b.row1 - b.row0 + 1) * cell)
            val centre = Offset(topLeft.x + extent.width / 2, topLeft.y + extent.height / 2)
            val radius = extent.minDimension / 2
            if (b.round) drawCircle(b.color, radius, centre) else drawRect(b.color, topLeft, extent)
            for (r in b.row0..b.row1) for (c in b.col0..b.col1) {
                val stud = Offset((c - 0.5f) * cell, (r - 0.5f) * cell)
                // On a round plate the corner studs are outside the disc.
                if (b.round && hypot(stud.x - centre.x, stud.y - centre.y) > radius - cell * 0.1f) continue
                drawCircle(BRICK_STUD, radius = cell * 0.22f, center = stud)
            }
            if (i == current) {
                val edge = Stroke(2.dp.toPx())
                if (b.round) drawCircle(Color.White, radius, centre, style = edge) else drawRect(Color.White, topLeft, extent, style = edge)
            }
        }
    }
}

private val PLATE = Color(0xFF1C1C1C)
private val STUD = Color(0xFF333333)
private val BRICK_STUD = Color(0x33000000)

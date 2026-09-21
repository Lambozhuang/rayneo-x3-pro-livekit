"""Export a Mecabricks model open in Blender as the GLB a build guide ships with.

Run inside Blender (Scripting tab, or `blender -b model.blend -P this.py -- out.glb`)
after editing PARTS below. What it does and why:

- One glTF node per brick, named `stepNN_<colour>_<part>`: the glasses highlight a
  brick by node name, and the agent's `highlight_part(step)` maps to the `stepNN`
  prefix.
- One material per brick, plain Principled with the brick's colour. Mecabricks
  materials are node groups the glTF exporter cannot read (it would export every
  brick white); the colour sits on the `mb_base_*` group's "Color" input. Own
  material per brick also means two bricks of the same colour can be highlighted
  independently.
- Root node `model` scaled 0.001: Mecabricks units are millimetres, glTF wants metres.
- Y up, no Draco (nothing to decode on the glasses), modifiers applied.

The scene is left as it was: everything is done on copies that are removed afterwards.
"""

import os
import sys

import bpy

# Blender object name -> export node name, bottom-up build order. Edit per model.
# Object names come from the Mecabricks import ("part", "part.001", ...); check them in
# the outliner. The mesh data name (e.g. "3001.002") is the LEGO part number.
PARTS = {
    "part": "step01_darkpurple_2x4_3001",
    "part.001": "step02_yellow_1x4_3010",
    "part.002": "step03_blue_1x4_3010",
    "part.003": "step04_red_slope3x4_3297",
}
OUT = (sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv
       else os.path.join(os.path.dirname(bpy.data.filepath) or ".", "model.glb"))


def brick_colour(mat):
    for n in mat.node_tree.nodes:
        if n.type == "GROUP" and n.node_tree and n.node_tree.name.startswith("mb_base"):
            return list(n.inputs["Color"].default_value)
    raise RuntimeError(f"{mat.name}: no mb_base_* group, is this a Mecabricks material?")


def export(path: str) -> int:
    col = bpy.data.collections.new("__export")
    bpy.context.scene.collection.children.link(col)
    root = bpy.data.objects.new("model", None)
    col.objects.link(root)
    root.scale = (0.001,) * 3
    made = []
    try:
        for src_name, name in PARTS.items():
            src = bpy.data.objects[src_name]
            dup = src.copy()
            dup.data = src.data.copy()
            dup.name = dup.data.name = name
            dup.matrix_world = src.matrix_world.copy()
            col.objects.link(dup)
            dup.parent = root
            dup.matrix_parent_inverse = root.matrix_world.inverted()
            mat = bpy.data.materials.new("mat_" + name)
            mat.use_nodes = True
            bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf.inputs["Base Color"].default_value = brick_colour(src.data.materials[0])
            bsdf.inputs["Roughness"].default_value = 0.35
            bsdf.inputs["Metallic"].default_value = 0.0
            dup.data.materials.clear()
            dup.data.materials.append(mat)
            made.append((dup, mat))
        bpy.ops.object.select_all(action="DESELECT")
        for o in col.objects:
            o.select_set(True)
        bpy.context.view_layer.objects.active = root
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        bpy.ops.export_scene.gltf(
            filepath=path, export_format="GLB", use_selection=True, export_apply=True,
            export_yup=True, export_draco_mesh_compression_enable=False, export_materials="EXPORT",
        )
        return os.path.getsize(path)
    finally:
        for dup, mat in made:
            mesh = dup.data
            bpy.data.objects.remove(dup, do_unlink=True)
            bpy.data.meshes.remove(mesh)
            bpy.data.materials.remove(mat)
        bpy.data.objects.remove(root, do_unlink=True)
        bpy.data.collections.remove(col)


if __name__ == "__main__":
    print(f"wrote {OUT}: {export(OUT)} bytes")

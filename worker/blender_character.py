"""Render the selected character asset as a transparent PNG sequence.

This script runs inside Blender, after the chosen `.blend` has been opened.
It deliberately requires a named gesture action so a requested gesture can
never be silently ignored.
"""

import argparse
import json
import os
import re
import struct
import sys
import unicodedata
from pathlib import Path

import bpy


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--fps", required=True, type=int)
    parser.add_argument("--frames", required=True, type=int)
    parser.add_argument("--position", required=True)
    parser.add_argument("--entrance", required=True)
    parser.add_argument("--gesture", required=True)
    parser.add_argument("--character")
    parser.add_argument("--character-format", choices=(".gltf", ".glb", ".fbx"))
    parser.add_argument("--imported-blend")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def normalized(value):
    return re.sub(r"[\W_]+", "_", unicodedata.normalize("NFKC", value).lower()).strip("_")


def _gltf_document(path, character_format):
    try:
        if character_format == ".gltf":
            return json.loads(Path(path).read_text(encoding="utf-8"))
        data = Path(path).read_bytes()
        if len(data) < 20 or data[:4] != b"glTF":
            raise ValueError("missing GLB header")
        _, version, length = struct.unpack("<4sII", data[:12])
        if version != 2 or length != len(data):
            raise ValueError("invalid GLB version or length")
        chunk_length, chunk_type = struct.unpack("<I4s", data[12:20])
        if chunk_type != b"JSON" or 20 + chunk_length > len(data):
            raise ValueError("missing GLB JSON chunk")
        return json.loads(data[20:20 + chunk_length].decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, struct.error) as error:
        raise RuntimeError(f"could not inspect {character_format} character resources: {error}") from error


def reject_external_gltf_resources(path, character_format):
    document = _gltf_document(path, character_format)
    external = []
    for key in ("buffers", "images"):
        for resource in document.get(key, []):
            uri = resource.get("uri") if isinstance(resource, dict) else None
            if isinstance(uri, str) and not uri.startswith("data:"):
                external.append(uri)
    if external:
        raise RuntimeError(
            f"{character_format} character references external resources ({', '.join(external[:3])}); upload a self-contained GLB or embedded-resource glTF"
        )


def reject_external_fbx_textures():
    external = [image.filepath for image in bpy.data.images if image.source == "FILE" and image.packed_file is None]
    if external:
        raise RuntimeError(
            f"FBX character references external textures ({', '.join(external[:3])}); embed the resources before upload"
        )


def import_character(args):
    if not (args.character and args.character_format and args.imported_blend):
        raise RuntimeError("character import requires a file, format, and temporary .blend path")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.character_format in {".gltf", ".glb"}:
        reject_external_gltf_resources(args.character, args.character_format)
        bpy.ops.import_scene.gltf(filepath=args.character)
    else:
        bpy.ops.import_scene.fbx(filepath=args.character)
        reject_external_fbx_textures()


def character_position_offset(position):
    """Place the armature in the active camera's established world-space setup."""
    positions = {
        "foreground_left": (-2.8, 0.0, 0.0),
        "foreground_center": (0.0, 0.0, 0.0),
        "foreground_right": (2.8, 0.0, 0.0),
    }
    try:
        return positions[position]
    except KeyError as error:
        raise RuntimeError(f"unsupported character position: {position}") from error


def fade_materials(armature, start_frame, end_frame):
    """Keyframe node alpha for every character mesh material on the transparent plate."""
    materials = set()
    for item in [armature, *armature.children_recursive]:
        if item.type == "MESH":
            materials.update(slot.material for slot in item.material_slots if slot.material is not None)
    faded = False
    for material in materials:
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"
        elif hasattr(material, "blend_method"):
            material.blend_method = "BLEND"
        if not material.use_nodes:
            continue
        principled = material.node_tree.nodes.get("Principled BSDF")
        alpha = principled.inputs.get("Alpha") if principled else None
        if alpha is None:
            continue
        alpha.default_value = 0.0
        alpha.keyframe_insert(data_path="default_value", frame=start_frame)
        alpha.default_value = 1.0
        alpha.keyframe_insert(data_path="default_value", frame=end_frame)
        faded = True
    if not faded:
        raise RuntimeError("character asset has no alpha-capable material for fade_in")


def main():
    args = arguments()
    imported = args.character is not None
    if imported:
        import_character(args)
    armatures = [item for item in bpy.context.scene.objects if item.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError("character asset must contain an armature")
    if bpy.context.scene.camera is None:
        raise RuntimeError("character asset must define an active camera")
    gesture = normalized(args.gesture)
    actions = [item for item in bpy.data.actions if normalized(item.name) == gesture]
    if not actions:
        raise RuntimeError(f"character asset does not contain the requested gesture action: {args.gesture}")
    if len(actions) > 1:
        raise RuntimeError(f"requested gesture action matches multiple actions: {args.gesture}")
    armature = armatures[0]
    action = actions[0]
    armature.animation_data_create()
    armature.animation_data.action = action
    if imported:
        bpy.ops.wm.save_as_mainfile(filepath=args.imported_blend)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.fps = args.fps
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.frame_start = 1
    scene.frame_end = args.frames
    os.makedirs(args.output_dir, exist_ok=True)
    scene.render.filepath = os.path.join(args.output_dir, "character_")

    start_location = armature.location.copy()
    start_scale = armature.scale.copy()
    offset = character_position_offset(args.position)
    target_location = start_location.copy()
    target_location.x += offset[0]
    target_location.y += offset[1]
    target_location.z += offset[2]
    armature.location = target_location
    entrance_end = max(2, round(args.fps * 0.35))
    if args.entrance == "pop_in":
        armature.scale = (0.001, 0.001, 0.001)
        armature.keyframe_insert(data_path="scale", frame=1)
        armature.scale = start_scale
        armature.keyframe_insert(data_path="scale", frame=entrance_end)
    elif args.entrance in {"slide_left", "slide_right"}:
        distance = -3 if args.entrance == "slide_left" else 3
        armature.location.x = target_location.x + distance
        armature.keyframe_insert(data_path="location", frame=1)
        armature.location = target_location
        armature.keyframe_insert(data_path="location", frame=entrance_end)
    elif args.entrance == "fade_in":
        fade_materials(armature, 1, entrance_end)
    else:
        raise RuntimeError(f"unsupported entrance: {args.entrance}")
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()

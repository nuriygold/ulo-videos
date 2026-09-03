"""Render the selected character asset as a transparent PNG sequence.

This script runs inside Blender, after the chosen `.blend` has been opened.
It deliberately requires a named gesture action so a requested gesture can
never be silently ignored.
"""

import argparse
import os
import sys

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
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def normalized(value):
    return "".join(character for character in value.lower() if character.isalnum())


def main():
    args = arguments()
    armature = next((item for item in bpy.context.scene.objects if item.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("character asset must contain an armature")
    if bpy.context.scene.camera is None:
        raise RuntimeError("character asset must define an active camera")
    action = next((item for item in bpy.data.actions if normalized(item.name) == normalized(args.gesture)), None)
    if action is None:
        raise RuntimeError(f"character asset does not contain the requested gesture action: {args.gesture}")
    armature.animation_data_create()
    armature.animation_data.action = action

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
    if args.entrance == "pop_in":
        armature.scale = (0.001, 0.001, 0.001)
        armature.keyframe_insert(data_path="scale", frame=1)
        armature.scale = start_scale
        armature.keyframe_insert(data_path="scale", frame=max(2, round(args.fps * 0.35)))
    elif args.entrance in {"slide_left", "slide_right"}:
        distance = -3 if args.entrance == "slide_left" else 3
        armature.location.x = start_location.x + distance
        armature.keyframe_insert(data_path="location", frame=1)
        armature.location = start_location
        armature.keyframe_insert(data_path="location", frame=max(2, round(args.fps * 0.35)))
    elif args.entrance == "fade_in":
        # Alpha fading is asset/material-specific; keeping transparent film preserves the plate.
        pass
    else:
        raise RuntimeError(f"unsupported entrance: {args.entrance}")
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()

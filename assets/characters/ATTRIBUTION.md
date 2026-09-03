# Character Asset Attribution

## lizard.blend

- **Model:** "Lizardman" rigged character by **thecubber**, commissioned by the
  OpenGameArt.org community
- **License:** Creative Commons Attribution 3.0 Unported
  (https://creativecommons.org/licenses/by/3.0/)
- **Downloaded from:** https://opengameart.org (file: `raptile_rig_fin.blend.7z`,
  hosted at https://opengameart.org/sites/default/files/raptile_rig_fin.blend_.7z)

### Modifications made for this project (2026-09-02)

- Repacked for Blender 5.2 (original file was Blender 2.54 / 2010 format)
- Removed bundled lights and cameras
- Legacy material rebuilt as a Principled BSDF; the 2010-era packed textures were
  extracted to `lizard_diffuse.png` (sRGB) and `lizard_normal.png` (Non-Color) and
  rebound as packed file-source images
- UV layer (`UVTex`) `active_render` flag set (lost during format conversion, which
  rendered the model untextured)
- Normal-map link disconnected (the 128x128 "normal detail" image is not a valid
  tangent-space normal map and distorted shading)
- Three pose actions added on the existing 105-bone rig, all with fake users so they
  persist in the library file:
  - `pop_in` — entrance scale pop (frames 1-13)
  - `idle` — sine breathing loop (frames 1-97, 30 fps)
  - `shrug_and_point` — shrug gesture into an audience-facing point (frames 1-60)
- Saved at rest pose, 30 fps, no lights/cameras (the render adapter supplies its own)

Redistribution of this file is permitted under CC-BY 3.0 with the attribution above.
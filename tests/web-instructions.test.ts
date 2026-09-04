import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Home from "../app/page";

test("workspace explains the complete interrupted-video workflow", () => {
  const markup = renderToStaticMarkup(React.createElement(Home));

  assert.match(markup, /How to create your interrupted video/);
  assert.match(markup, /Accepted video formats:.*MP4, MOV, or WebM/);
  assert.match(markup, /Character file \(unavailable\)/);
  assert.match(markup, /Character upload unavailable/);
  assert.doesNotMatch(markup, /accept="\.blend,\.gltf,\.glb,\.fbx/);
  assert.match(markup, /Renderer status reports active character formats/);
  assert.match(markup, /Accepted logo formats:.*PNG, JPEG, WebP, or SVG/);
  assert.match(markup, /select.*Submit render/);
  assert.match(markup, /finished video/);
  assert.match(markup, /Vercel fallback applies freeze\/resume, logo, and captions/);
  assert.match(markup, /Character, source audio, voice, and lip-sync are unavailable/);
  assert.match(markup, /Voice reference \(unavailable\)/);
});

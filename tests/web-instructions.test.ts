import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Home from "../app/page";

test("workspace explains the complete interrupted-video workflow", () => {
  const markup = renderToStaticMarkup(React.createElement(Home));

  assert.match(markup, /How to create your interrupted video/);
  assert.match(markup, /Accepted video formats:.*MP4, MOV, or WebM/);
  assert.match(markup, /compatible Blender/);
  assert.match(markup, /\.blend.*file/);
  assert.match(markup, /Accepted logo formats:.*PNG, JPEG, WebP, or SVG/);
  assert.match(markup, /select.*Submit render/);
  assert.match(markup, /finished video/);
});

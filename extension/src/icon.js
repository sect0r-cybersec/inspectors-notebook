"use strict";

// Toolbar icon for each state (FR-37), drawn at runtime so there are no image files.
// The notebook glyph is the panel's logo; colour has the same jobs as in the panel.
const ICON_COLOURS = {
  closed: { glyph: "#7D8792", dot: null },
  connected: { glyph: "#F2B544", dot: null },
  recording: { glyph: "#F2B544", dot: "#F06A6A" },
};

function drawIcon(size, state) {
  const { glyph, dot } = ICON_COLOURS[state];
  const canvas = new OffscreenCanvas(size, size);
  const ctx = canvas.getContext("2d");
  const s = size / 24;
  ctx.scale(s, s);
  ctx.strokeStyle = glyph;
  ctx.lineWidth = 2.2;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.roundRect(5, 3, 14, 18, 2);
  ctx.moveTo(9, 8);
  ctx.lineTo(15, 8);
  ctx.moveTo(9, 12);
  ctx.lineTo(15, 12);
  ctx.moveTo(9, 16);
  ctx.lineTo(12, 16);
  ctx.stroke();
  if (dot) {
    ctx.fillStyle = dot;
    ctx.beginPath();
    ctx.arc(18.5, 18.5, 4.5, 0, Math.PI * 2);
    ctx.fill();
  }
  return ctx.getImageData(0, 0, size, size);
}

function iconImages(state) {
  return { 16: drawIcon(16, state), 32: drawIcon(32, state) };
}

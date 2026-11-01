// Pixels, without a dependency (§168).
//
// The whole point of a pixel gate is to assert things the DOM cannot: that the theme's colour actually
// reached the screen, that a card was **painted** and not just present in the markup, that nothing
// spilled outside its panel. That needs the bitmap, and the bitmap arrives as a PNG.
//
// Why not a PNG library: `web/` is deliberately zero-build (see `cdp.mjs`), and a screenshot decoder is
// ~120 lines of `zlib.inflateSync` plus the five scanline filters. One copy of "PNG → RGBA" beats a
// dependency that has to be installed before a gate can run.
//
// Scope: 8-bit, non-interlaced, colour type 2 (RGB) or 6 (RGBA) -- what Chrome emits. Anything else
// **throws** rather than returning a wrong-sized buffer: a silently mis-stride'd bitmap would make
// every assertion below meaningless while still "passing".

import { inflateSync } from "node:zlib";

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];

/**
 * Decode a PNG buffer into `{ width, height, data }` where `data` is RGBA8, row-major.
 *
 * @param {Buffer} buffer
 * @returns {{width: number, height: number, data: Buffer}}
 */
export function decodePng(buffer) {
  for (let i = 0; i < SIGNATURE.length; i++) {
    if (buffer[i] !== SIGNATURE[i]) throw new Error("not a PNG (bad signature)");
  }
  let at = SIGNATURE.length;
  let header = null;
  const idat = [];
  while (at + 8 <= buffer.length) {
    const length = buffer.readUInt32BE(at);
    const type = buffer.toString("ascii", at + 4, at + 8);
    const body = buffer.subarray(at + 8, at + 8 + length);
    at += 12 + length; // length + type + body + crc
    if (type === "IHDR") {
      header = {
        width: body.readUInt32BE(0),
        height: body.readUInt32BE(4),
        depth: body[8],
        colour: body[9],
        compression: body[10],
        filter: body[11],
        interlace: body[12],
      };
    } else if (type === "IDAT") {
      idat.push(body);
    } else if (type === "IEND") {
      break;
    }
  }
  if (!header) throw new Error("PNG has no IHDR");
  if (header.depth !== 8) throw new Error(`PNG bit depth ${header.depth}, expected 8`);
  if (header.interlace !== 0) throw new Error("interlaced PNG is not supported");
  const channels = header.colour === 6 ? 4 : header.colour === 2 ? 3 : 0;
  if (channels === 0) throw new Error(`PNG colour type ${header.colour} is not RGB/RGBA`);
  if (header.compression !== 0 || header.filter !== 0) {
    throw new Error("PNG uses a compression/filter method this decoder does not know");
  }

  const raw = inflateSync(Buffer.concat(idat));
  const { width, height } = header;
  const stride = width * channels;
  const expected = (stride + 1) * height;
  if (raw.length !== expected) {
    // A short/long buffer means the scanline walk below would read the wrong bytes. Refuse.
    throw new Error(`PNG scanlines are ${raw.length} B, expected ${expected} B`);
  }

  const out = Buffer.alloc(width * height * 4);
  let previous = Buffer.alloc(stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    const current = unfilter(filter, line, previous, channels);
    for (let x = 0; x < width; x++) {
      const src = x * channels;
      const dst = (y * width + x) * 4;
      out[dst] = current[src];
      out[dst + 1] = current[src + 1];
      out[dst + 2] = current[src + 2];
      out[dst + 3] = channels === 4 ? current[src + 3] : 255;
    }
    previous = current;
  }
  return { width, height, data: out };
}

function unfilter(filter, line, previous, channels) {
  const out = Buffer.alloc(line.length);
  for (let i = 0; i < line.length; i++) {
    const x = line[i];
    const a = i >= channels ? out[i - channels] : 0;
    const b = previous[i];
    const c = i >= channels ? previous[i - channels] : 0;
    let value;
    switch (filter) {
      case 0: value = x; break;
      case 1: value = x + a; break;
      case 2: value = x + b; break;
      case 3: value = x + ((a + b) >> 1); break;
      case 4: value = x + paeth(a, b, c); break;
      default: throw new Error(`PNG scanline filter ${filter} is not defined`);
    }
    out[i] = value & 0xff;
  }
  return out;
}

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  return pb <= pc ? b : c;
}

/** A rectangle in **viewport CSS pixels**; `x2`/`y2` are exclusive. */
export function rect(x, y, width, height) {
  return { x, y, width, height };
}

function clampRect(bitmap, box) {
  const x1 = Math.max(0, Math.floor(box.x));
  const y1 = Math.max(0, Math.floor(box.y));
  const x2 = Math.min(bitmap.width, Math.floor(box.x + box.width));
  const y2 = Math.min(bitmap.height, Math.floor(box.y + box.height));
  return { x1, y1, x2, y2 };
}

/** Pixel at `(x, y)` as `[r, g, b, a]`. */
export function pixelAt(bitmap, x, y) {
  const at = (y * bitmap.width + x) * 4;
  return [bitmap.data[at], bitmap.data[at + 1], bitmap.data[at + 2], bitmap.data[at + 3]];
}

/** How far two colours are apart, channel-wise (max absolute difference, ignoring alpha). */
export function distance(a, b) {
  return Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]), Math.abs(a[2] - b[2]));
}

/** The most common colour in a box -- i.e. "what is this panel's background". */
export function dominantColour(bitmap, box) {
  const { x1, y1, x2, y2 } = clampRect(bitmap, box);
  const counts = new Map();
  for (let y = y1; y < y2; y++) {
    for (let x = x1; x < x2; x++) {
      const [r, g, b] = pixelAt(bitmap, x, y);
      const key = (r << 16) | (g << 8) | b;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  let best = 0;
  let bestKey = 0;
  for (const [key, count] of counts) {
    if (count > best) {
      best = count;
      bestKey = key;
    }
  }
  return [(bestKey >> 16) & 0xff, (bestKey >> 8) & 0xff, bestKey & 0xff, 255];
}

/**
 * Count pixels in `box` that differ from `background` by more than `tolerance`.
 *
 * This is the "ink" measurement every assertion below is built on: a panel that renders as a flat fill
 * has ~0 ink, a panel with text and chips has plenty.
 */
export function inkCount(bitmap, box, background, tolerance = 24) {
  const { x1, y1, x2, y2 } = clampRect(bitmap, box);
  let ink = 0;
  for (let y = y1; y < y2; y++) {
    for (let x = x1; x < x2; x++) {
      if (distance(pixelAt(bitmap, x, y), background) > tolerance) ink += 1;
    }
  }
  return ink;
}

/**
 * Fraction of `box` that is ink, over the box **clipped to the bitmap**.
 *
 * One function so the numerator and the denominator cannot come from different rectangles. They did:
 * a board 895 px tall inside a 720 px viewport had its ink counted over the visible 720 rows and
 * divided by 895 -- two ledgers added together, which reads as a plausible 4.08% instead of the real
 * 5.08%. (FACT §4.5 has this exact shape.)
 */
export function inkFraction(bitmap, box, background, tolerance = 24) {
  const { x1, y1, x2, y2 } = clampRect(bitmap, box);
  const area = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  if (area === 0) return 0;
  return inkCount(bitmap, box, background, tolerance) / area;
}

/** How many pixels in `box` are within `tolerance` of `colour`. */
export function colourCount(bitmap, box, colour, tolerance = 24) {
  const { x1, y1, x2, y2 } = clampRect(bitmap, box);
  let hits = 0;
  for (let y = y1; y < y2; y++) {
    for (let x = x1; x < x2; x++) {
      if (distance(pixelAt(bitmap, x, y), colour) <= tolerance) hits += 1;
    }
  }
  return hits;
}

/** Bounding box of the ink in `box`, or `null` when there is none. */
export function inkBounds(bitmap, box, background, tolerance = 24) {
  const { x1, y1, x2, y2 } = clampRect(bitmap, box);
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (let y = y1; y < y2; y++) {
    for (let x = x1; x < x2; x++) {
      if (distance(pixelAt(bitmap, x, y), background) <= tolerance) continue;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }
  if (minX === Infinity) return null;
  return { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 };
}

/**
 * Pixels that differ between two bitmaps **inside one box**.
 *
 * This is how "was it painted" is answered without naming a background colour: render the element,
 * hide it, render again, and ask whether its own rectangle changed. A painted element must change; an
 * element the DOM has but the screen does not leaves its box untouched.
 *
 * (A background-colour version of this was tried first and the negative control killed it: with the
 * element hidden, what shows through is *not* the colour you measured while it was visible.)
 */
export function diffCountIn(a, b, box, tolerance = 8) {
  if (a.width !== b.width || a.height !== b.height) return -1;
  const { x1, y1, x2, y2 } = clampRect(a, box);
  let different = 0;
  for (let y = y1; y < y2; y++) {
    for (let x = x1; x < x2; x++) {
      const at = (y * a.width + x) * 4;
      const worst = Math.max(
        Math.abs(a.data[at] - b.data[at]),
        Math.abs(a.data[at + 1] - b.data[at + 1]),
        Math.abs(a.data[at + 2] - b.data[at + 2])
      );
      if (worst > tolerance) different += 1;
    }
  }
  return different;
}

/** True when two bitmaps are pixel-identical (same size and same bytes). */
export function sameBitmap(a, b) {
  if (a.width !== b.width || a.height !== b.height) return false;
  return a.data.equals(b.data);
}

/** How many pixels differ between two bitmaps of equal size; `-1` when the sizes differ. */
export function diffCount(a, b, tolerance = 0) {
  if (a.width !== b.width || a.height !== b.height) return -1;
  let different = 0;
  for (let i = 0; i < a.data.length; i += 4) {
    const dr = Math.abs(a.data[i] - b.data[i]);
    const dg = Math.abs(a.data[i + 1] - b.data[i + 1]);
    const db = Math.abs(a.data[i + 2] - b.data[i + 2]);
    if (Math.max(dr, dg, db) > tolerance) different += 1;
  }
  return different;
}

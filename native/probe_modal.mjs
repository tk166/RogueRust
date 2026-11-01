// One-off probe: what is `#modalClose`'s layout while the deck picker is open?
//
// Written as a file because the interesting expression contains quotes and braces, and pasting that
// into `-c` or a heredoc is how three earlier sessions corrupted their own source.
import { openPage } from "./cdp.mjs";

const page = await openPage({ query: "debug", waitFor: "!!window.RD_DEBUG" });

const dump = async (label) => {
  const state = await page.evaluate(`(() => {
    const modal = document.getElementById("modal");
    const box = document.querySelector(".modal-box");
    const close = document.getElementById("modalClose");
    const rect = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return {
        x: Math.round(r.left), y: Math.round(r.top),
        w: Math.round(r.width), h: Math.round(r.height),
        display: style.display, visibility: style.visibility, opacity: style.opacity,
        position: style.position, offsetW: el.offsetWidth, offsetH: el.offsetHeight,
      };
    };
    return { hidden: modal ? modal.hidden : null, modal: rect(modal), box: rect(box), close: rect(close) };
  })()`);
  console.log(label, JSON.stringify(state, null, 1));
};

await dump("before open");
await page.evaluate("RD_DEBUG.showDeckPicker('probe', function () {})");
await dump("immediately after open");
await new Promise((r) => setTimeout(r, 300));
await dump("300 ms later");
await page.close();

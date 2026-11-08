// §304 一次性浏览器验证（不进闸门）：`gambling_chip` / `toolbox` 的问句在**真页面**上出现、
// 文案说到点上、点"确认"之后能接着打。
//
// 跑法：node native/p304_page.mjs
//
// 为什么值得单独跑一次：句子是**页面写的**（`titles[source + ":" + kind]`），内核那边的负控钉不到
// 它 —— 少一个 key 时页面会退成"选牌"，也就是"有弹窗、但它不知道自己问什么"。
// 驱动形状抄 `web/browser_test.mjs`：祝福 → （可能的选牌）→ 地图第一个可走节点 → 开战。
import { openPage } from "../web/cdp.mjs";

const page = await openPage({
  query: "p304-page&debug",
  gate: "P304_PAGE",
  waitFor: 'Boolean(window.ex && document.querySelector("#nodePanel [data-panel-action]"))',
});
const { evaluate } = page;

const report = await evaluate(`(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const panel = () => document.getElementById("nodePanel");
  const out = {};
  const title = () => document.getElementById("modalTitle").textContent;
  const modalOpen = () => document.getElementById("modal").hidden === false;

  const walk = async (relic) => {
    RD_DEBUG.startWithSeed(7, 0);
    await sleep(60);
    out[relic + "Grant"] = RD_DEBUG.giveRelic(relic);
    // 祝福：第一个选项。
    panel().querySelector("[data-panel-action]").click();
    await sleep(40);
    // 有的祝福欠一次选牌。
    if (ex.rd_run_pending() === 7) {
      const pick = panel().querySelector("[data-panel-action]");
      if (pick) { pick.click(); await sleep(30); }
      const card = document.querySelector("#modalBody [data-pick]");
      if (card) { card.click(); await sleep(30); }
    }
    // 地图：第一个可走的房间，再点开战。
    const lit = [...document.querySelectorAll("#mapbox g.node.reachable")];
    if (lit.length) { lit[0].dispatchEvent(new MouseEvent("click", { bubbles: true })); await sleep(40); }
    const fight = panel().querySelector("[data-panel-action]");
    if (fight) { fight.click(); await sleep(80); }
  };

  await walk("gambling_chip");
  out.chipPending = ex.rd_env_choice_pending();
  out.chipModal = modalOpen();
  out.chipTitle = title();
  const ticked = [...document.querySelectorAll("#modalBody [data-choice]")];
  out.chipOptions = ticked.length;
  for (const el of ticked.slice(0, 2)) { el.onclick(); await sleep(15); }
  const confirm = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
  out.chipHasConfirm = Boolean(confirm);
  if (confirm) { confirm.onclick(); await sleep(80); }
  out.chipAfter = ex.rd_env_choice_pending();
  out.chipModalAfter = modalOpen();
  out.chipHand = document.querySelectorAll("#hand button.card").length;

  await walk("toolbox");
  out.toolboxPending = ex.rd_env_choice_pending();
  out.toolboxTitle = title();
  const options = [...document.querySelectorAll("#modalBody [data-choice]")];
  out.toolboxOptions = options.length;
  if (options[0]) { options[0].onclick(); await sleep(30); }
  const confirm2 = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
  if (confirm2) { confirm2.onclick(); await sleep(80); }
  out.toolboxAfter = ex.rd_env_choice_pending();
  return out;
})()`);

const want = {
  chipPending: 1,
  chipModal: true,
  chipHasConfirm: true,
  chipAfter: 0,
  chipModalAfter: false,
  toolboxPending: 1,
  toolboxOptions: 3,
  toolboxAfter: 0,
};
let failures = 0;
for (const [key, value] of Object.entries(want)) {
  const got = report[key];
  const ok = got === value;
  if (!ok) failures += 1;
  console.log(`${ok ? "ok  " : "FAIL"} ${key}: ${JSON.stringify(got)} (want ${JSON.stringify(value)})`);
}
for (const key of ["chipTitle", "toolboxTitle"]) {
  const text = report[key] || "";
  const specific = text.length > 0 && !text.startsWith("选牌");
  if (!specific) failures += 1;
  console.log(`${specific ? "ok  " : "FAIL"} ${key}: ${text}`);
}
console.log(failures === 0 ? "P304_PAGE PASS" : `P304_PAGE FAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);

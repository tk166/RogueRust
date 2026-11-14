"""给闸门 56 加 §388–§391 的判据（状态中文名 / 遗物与药水悬浮窗 / 牌组选择器等宽 / 顶栏 HP）。

## 为什么放在闸门 56

它已经是"布局宽度 + 词表"那道闸门：§389（一个面板、挂在对的位置）与 §390（等宽）都是**布局**，
§388（状态中文名）是**词表**。放一起，红了能一眼看出是哪一类。

## 四条判据

1. **§388**：`zh.ts` 的 `statuses` 表覆盖内容包里**每一条** `Statuses[].Id`
   （`orichalcum` / `incense_burner` 就是玩家报的那两条）—— 穷尽遍历，不抽查；
2. **§389 遗物**：指着遗物条上的 chip ⇒ `[data-card-tip]` 出现，标题是中文；
3. **§390 牌组选择器**：每一行都有二维卡面、中文名，且**所有行的宽度完全相等**；
4. **§391 顶栏 HP**：战斗中顶栏显示的是**战斗快照**的 HP（`data-run-hp`），不是运行层那份
   （玩家被砸 35 点后血条纹丝不动，就是因为读了运行层）。
"""

import io

PATH = 'native/ui_layout_words_check.mjs'
t = io.open(PATH, encoding='utf-8').read()

# ── 纯函数部分：§388 状态中文名穷尽 ────────────────────────────────────────
OLD = '''  summary.cards = needsTarget.length;'''
NEW = '''  summary.cards = needsTarget.length;

  // ── §388：状态表必须覆盖内容里**每一条** status（穷尽）────────────────────
  //
  // 玩家报的："一些状态依旧显示英文例如 orichalcum 和 incense_burner"。
  // 那两条是**遗物挂的状态**（`StartCombatStatus`），旧的 13 条小表里没有 ⇒ 屏幕上就是英文 id。
  const zhSource = await readFile(join(REPO, "web-next/src/i18n/zh.ts"), "utf8");
  const statusesBlock = /"statuses": (\\{[\\s\\S]*?\\n \\}),\\n/.exec(zhSource);
  check(statusesBlock !== null, "`zh.ts` 里有 statuses 表");
  const statusKeys = new Set(
    [...(statusesBlock ? statusesBlock[1] : "").matchAll(/"([^"]+)": \\{/g)].map((m) => m[1])
  );
  const missingStatus = [];
  for (const status of content.Statuses ?? []) {
    if (!statusKeys.has(status.Id)) missingStatus.push(status.Id);
  }
  check(
    missingStatus.length === 0,
    "内容里**每一条**状态都有中文名（穷尽 150 条）",
    missingStatus.length === 0 ? `${statusKeys.size} 条` : JSON.stringify(missingStatus.slice(0, 6))
  );
  // 玩家点名的两条，单独钉住（回归时最想知道的就是它们）。
  for (const id of ["standard.orichalcum", "standard.incense_burner"]) {
    const row = new RegExp(`"${id.replace(/[.]/g, "\\\\.")}": \\\\{\\\\s*"name": "([^"]+)"`).exec(zhSource);
    check(
      row !== null && /[\\u4e00-\\u9fa5]/.test(row[1]),
      `\`${id}\` 有中文名（玩家点名的那两条之一）`,
      row ? row[1] : "缺"
    );
  }'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# ── 浏览器部分：遗物 chip 的悬浮窗 + 牌组选择器 + 顶栏 HP ──────────────────
OLD2 = '''await page.close();
console.log("");
if (failures > 0) {'''
NEW2 = '''// ── §389：遗物条上的 chip 指着要出详情 ─────────────────────────────────────
{
  const chipPoint = await ev(`(() => {
    const el = document.querySelector("[data-relic-id]");
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, id: el.dataset.relicId };
  })()`);
  check(chipPoint !== null, "遗物条上有 chip 可指", chipPoint?.id);
  if (chipPoint) {
    await page.send("Input.dispatchMouseEvent", {
      type: "mouseMoved", x: chipPoint.x, y: chipPoint.y, button: "none", buttons: 0,
    });
    await sleep(150);
    const tip = await ev(`(() => {
      const node = document.querySelector("[data-card-tip]");
      if (!node) return null;
      return {
        kind: node.dataset.tipKind,
        title: node.querySelector("[data-tip-title-text]")?.textContent.trim() ?? "",
      };
    })()`);
    check(tip !== null, "指着遗物 ⇒ 出现详情面板（§389 的唯一面板）");
    check(tip !== null && tip.kind === "relic", "面板说的是**遗物**", tip?.kind);
    check(
      tip !== null && /[\\u4e00-\\u9fa5]/.test(tip.title),
      "遗物详情标题是中文名",
      tip?.title
    );
  }
}

// ── §390：牌组选择器（祝福选牌那条路一开局就能开）────────────────────────
{
  const scene = await ev("window.__run.scene()");
  if (scene.base === "SC-01b") {
    const rows = await ev(`(() => {
      const list = document.querySelector("[data-deck-count]");
      if (!list) return null;
      return Array.from(list.querySelectorAll("[data-deck-pick]")).slice(0, 6).map((row) => ({
        id: row.dataset.deckPickId,
        name: row.querySelector(".deck-select-name")?.textContent.trim() ?? "",
        badges: row.querySelectorAll("[data-asset-badge]").length,
        width: Math.round(row.getBoundingClientRect().width * 10) / 10,
      }));
    })()`);
    check(rows !== null && rows.length > 0, "牌组选择器有行", JSON.stringify(rows?.length));
    check(
      rows !== null && rows.every((row) => row.badges > 0),
      "每一行都有**二维卡面**（§390）",
      JSON.stringify(rows?.map((row) => row.badges))
    );
    check(
      rows !== null && rows.every((row) => /[\\u4e00-\\u9fa5]/.test(row.name)),
      "每一行都是**中文名**（不是英文 id）",
      JSON.stringify(rows?.map((row) => row.name))
    );
    const widths = rows?.map((row) => row.width) ?? [];
    check(
      widths.length > 0 && new Set(widths).size === 1,
      "每一行**等宽**（玩家报的参差）",
      JSON.stringify(widths)
    );
    // 指着某一行 ⇒ 同一个面板给出"种类 · 费用 · 稀有度"。
    const point = await ev(`(() => {
      const el = document.querySelector("[data-deck-pick]");
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    })()`);
    if (point) {
      await page.send("Input.dispatchMouseEvent", {
        type: "mouseMoved", x: point.x, y: point.y, button: "none", buttons: 0,
      });
      await sleep(150);
      const sub = await ev(
        `document.querySelector("[data-card-tip] [data-tip-subtitle-text]")?.textContent.trim() ?? ""`
      );
      check(/费|不可打出/.test(sub), "牌组选择器的详情带**费用**", sub);
    }
  } else {
    check(true, `这一局没有祝福选牌（${scene.base}），牌组选择器部分跳过`);
  }
}

// ── §391：战斗中顶栏 HP 必须跟战斗快照 ───────────────────────────────────
{
  const scene = await ev("window.__run.scene()");
  if (scene.base === "SC-03b") {
    const pair = await ev(`(() => {
      const hp = document.querySelector("[data-run-hp]")?.dataset.runHp ?? "";
      const combat = window.__run.hand();
      return { topbar: hp, combat: combat ? combat.heroHp : null };
    })()`);
    check(
      pair.combat !== null && pair.topbar.split("/")[0] === String(pair.combat),
      "战斗中顶栏 HP == 战斗快照的 HP（不是运行层那份陈旧值）",
      JSON.stringify(pair)
    );
  } else {
    check(true, `现在不在战斗里（${scene.base}），顶栏 HP 部分跳过`);
  }
}

await page.close();
console.log("");
if (failures > 0) {'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('闸门 56 加了四条判据')

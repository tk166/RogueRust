"""§346 页面接线：`has_relic` 取代两处遍历；祝福按内核给的条数；三个 DOM 钩子。

## 页面改了三件事

1. **`singingBowl` 不再遍历遗物**：原来在奖励屏与加牌屏各写了一遍"遍历 `relicCount` 个、
   逐个读 id、比字符串"。现在一条 `hasRelic("singing_bowl")` —— 一个来源。
2. **祝福条数**：`for (let slot = 0; slot < 2; slot++)` → `ex.rd_run_start_offer_count()`。
3. **事件 id / 遭遇 id / 活跃墙位**：挂成 DOM 的 `data-*` 钩子。DOM 版**不用**它们（它已经画好了），
   但 3D/美术层要按 id 选背景与高亮 —— 挂 `data-*` 是**唯一**不改变现有像素、又能让外部读到的地方。

⚠️ 为什么不把这三个显示出来：`#msg` 的文本被浏览器判据逐字比过，往里加一句会连带改判据；
而"现在是谁的回合"在 DOM 版里已经有 `next up · <意图>` 的表达。

## `hasRelic` 用 scratch 缓冲，不猜 `__heap_base`

`rd_run_has_relic(ptr, len)` 收一对 `(指针, 长度)`。第一版想"模块加载时把 id 钉进堆里、
每帧复用"，但 `__heap_base` **不一定被导出**，而猜错就是写坏内存。

`rd_env_scratch_buf()` 的文档原话就是"1 KiB 的暂存区，让 JS 不必自带 malloc 就能交变长文本" ——
一次 `set` + 一次调用，读完就还。这个 id 只有 12 字节。
"""

import io

PAGE = 'web/index.html'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PAGE, encoding='utf-8').read()

# ── ① 一个 `hasRelic` 助手（放在 `readText` 旁边：同一种"给 wasm 递文本"的活）──
t = sub(t, '''function readText(lenFn, intoFn, index) {''',
        '''/// §346（缺口 G3）：**身上有没有这件遗物** —— 一条查询，取代"遍历遗物比字符串"。
///
/// 文本走 `rd_env_scratch_buf()`：那是 1 KiB 的暂存区，文档原话就是"让 JS 不必自带 malloc
/// 就能交变长文本"。一次 `set` + 一次调用，读完就还（id 只有十几个字节）。
/// ⚠️ 不要猜 `__heap_base` —— 它不一定被导出，猜错就是写坏内存。
function hasRelic(id) {
  const bytes = new TextEncoder().encode(id);
  const ptr = Number(ex.rd_env_scratch_buf());
  new Uint8Array(ex.memory.buffer, ptr, bytes.length).set(bytes);
  return ex.rd_run_has_relic(ptr, bytes.length) === 1;
}

function readText(lenFn, intoFn, index) {''', 'hasRelic helper')

# ── ② singingBowl：两处遍历 → 一个查询 ─────────────────────────────────────
t = sub(t, '''    // ⚠️ 这条判据必须是"**我持有的遗物里有没有** `singing_bowl`"，不是"有没有欠账"：
    // 见 `describePickupAdd` 的注释 —— 一个永远画出来的 +2 按钮就是死按钮。
    for (let i = 0, n = ex.rd_run_observe(6); i < n; i++) {
      const id = readText((k) => ex.rd_run_relic_id_len(k),
                          (ptr, k) => ex.rd_run_relic_id_into(k, ptr), i);
      if (id === "singing_bowl") snapshot.singingBowl = true;
    }''',
        '''    // ⚠️ 这条判据必须是"**我持有的遗物里有没有** `singing_bowl`"，不是"有没有欠账"：
    // 见 `describePickupAdd` 的注释 —— 一个永远画出来的 +2 按钮就是死按钮。
    // §346：一条查询取代了"遍历遗物比字符串"（这段原来在下面还有一份 —— 两处漏一处不会红）。
    snapshot.singingBowl = hasRelic("singing_bowl");''', 'singingBowl loop 1')

t = sub(t, '''  if (snapshot.pending === 4 && !snapshot.singingBowl) {
    for (let i = 0, n = ex.rd_run_observe(6); i < n; i++) {
      const id = readText((k) => ex.rd_run_relic_id_len(k),
                          (ptr, k) => ex.rd_run_relic_id_into(k, ptr), i);
      if (id === "singing_bowl") snapshot.singingBowl = true;
    }
  }''',
        '''  if (snapshot.pending === 4 && !snapshot.singingBowl) {
    snapshot.singingBowl = hasRelic("singing_bowl");
  }''', 'singingBowl loop 2')

# ── ③ 祝福条数：内核给 ────────────────────────────────────────────────────
t = sub(t, '''    case 6:
      for (let slot = 0; slot < 2; slot++) {''',
        '''    case 6:
      // §346：条数由内核给（原来写死 2 —— 内容一变就静默少画一个按钮）。
      for (let slot = 0, offers = ex.rd_run_start_offer_count(); slot < offers; slot++) {''',
        'offer count')

# ── ④ 事件 id：挂到节点面板上（美术钩子）──────────────────────────────────
t = sub(t, '''function renderNode() {
  const panel = document.getElementById("nodePanel");
  const description = RD_PANELS.describe(runSnapshot());''',
        '''function renderNode() {
  const panel = document.getElementById("nodePanel");
  const description = RD_PANELS.describe(runSnapshot());
  // §346（缺口 G6）：事件的 **id** 挂在面板上 —— DOM 版不用它（正文已经画好了），
  // 但 3D/美术层要按 id 选背景，而事件文本会随文案改动。没有事件时是空串。
  panel.dataset.eventId = ex.rd_run_pending() === 5
    ? readText(() => ex.rd_run_event_id_len(), (ptr) => ex.rd_run_event_id_into(ptr))
    : "";''', 'event id hook')

# ── ⑤ 遭遇 id + 活跃墙位 ──────────────────────────────────────────────────
t = sub(t, '''  document.getElementById("deckCount").textContent = String(Math.max(0, deck));''',
        '''  document.getElementById("deckCount").textContent = String(Math.max(0, deck));
  // §346（缺口 G6）：这一场（或刚打完那一场）的**遭遇 id** —— 美术层按它选背景。
  document.getElementById("runStats").dataset.encounterId =
    readText(() => ex.rd_run_encounter_id_len(), (ptr) => ex.rd_run_encounter_id_into(ptr));
  // §346（缺口 G12）：**现在是谁的回合**，作为墙位（`-1` 英雄 / `0..5` 敌人 / `-2` 没人）。
  // DOM 版已经有 `next up · <意图>` 的表达，所以这里只挂钩子（高亮交给渲染层）。
  document.getElementById("enemies").dataset.activeSlot = String(ex.rd_env_active_slot());''',
        'encounter id + active slot hooks')
io.open(PAGE, 'w', encoding='utf-8', newline='\n').write(t)
print('§346 page: hasRelic helper, offer count, three DOM hooks')

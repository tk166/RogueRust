"""§345 显示层：**内核给 id，显示层给名字**（映射表 + 美化 id）。

## 用户给的架构方向

> 最终需要的效果是 UI 显示的名字和内核的名字可以不一样（规避版权等用途，通过映射表实现），
> 所以接口是 id 可能是好事。

⇒ 这一节不改内核的名字导出（G4/G8 的"缺导出"其实不成立：id 早就有），只加**一个**真的缺的
（Boss 的敌人 id，§345 内核侧），其余全在显示层：

```js
displayName(id, kernelName) =
    NAMES[id]        // ① 替换表：版权改名、本地化、任何"屏幕上的名字"
 ?? kernelName       // ② 内核/内容给的名字（遗物的 DisplayName、卡的 NameKey）
 ?? prettifyId(id)   // ③ 兜底：`entropic_brew` -> `Entropic Brew`
```

为什么这个顺序：① 必须能**覆盖**内核的名字（否则"规避版权"这件事做不到），而 ② 比 ③ 好
（内容里真的有 `Slime Boss` 这样的显示名时，美化出来的 `Slime Boss` 可能不如它）。

## 美化规则（`prettifyId`）

| 输入 | 输出 | 规则 |
|---|---|---|
| `entropic_brew` | `Entropic Brew` | 按 `_` 分词、每词首字母大写 |
| `acid_slime_m` | `Acid Slime M` | 单字母词整体大写 |
| `defend+` | `Defend+` | `+` 是升级标记，属于后缀，不参与分词 |
| `standard.constricted` | `Constricted` | 去掉内容命名空间（最后一个 `.` 之后） |
| `""` / `null` | `""` | 空就是空，不编一个名字 |

⚠️ 它只是**兜底**。真正要改的名字进 `NAMES` —— 那张表是**唯一**该放"屏幕上的名字"的地方。
"""

import io

RENDER = 'web/ui_render.js'
PAGE = 'web/index.html'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① ui_render.js：NAMES / prettifyId / displayName ────────────────────────
t = io.open(RENDER, encoding='utf-8').read()

ANCHOR = '''  const H = {
    ROUND: 0, TURN: 1, PHASE: 2, RESULT: 3, HP: 4, HP_MAX: 5, BLOCK: 6, WARD: 7,
    ENERGY: 8, ENERGY_MAX: 9, HAND: 10, ENEMIES: 11,
  };'''

NAMES = '''  // ---------------------------------------------------------------------------------------------
  // Display names (§345)
  //
  // **内核给 id，显示层给名字。** 这是有意的：最终要能"屏幕上的名字与内核的名字不同"
  // （规避版权等用途、本地化、以及纯粹的品味），而那件事只能发生在**显示层** ——
  // 一旦内核把"Slime Boss"写进 ABI，改名的成本就从"改一张表"变成"改内容 + 重编镜像"。
  //
  // 所以：ABI 一律给 id（药水 id、商店四排 id、遗物 id、Boss 的敌人 id），这里决定怎么念。
  // ---------------------------------------------------------------------------------------------

  /// 替换表：**id → 屏幕上的名字**。命中的条目**覆盖**内核/内容给的名字。
  ///
  /// 空表是**正常状态**：美化规则（`prettifyId`）已经能把 `entropic_brew` 念成
  /// "Entropic Brew"。要改名（版权、本地化、某个名字太丑）就往这里加一行 ——
  /// 加在这里而不是内核里，是因为**同一个内核要能喂两套名字**（比如正式版与试玩版）。
  const NAMES = {
    // 例：`slime_boss: "胶质巨像",`  // 屏幕上一个字都不提原版
  };

  /// `id` → 一个能念的字符串。**只是兜底**，不是"内容的正式名字"。
  ///
  /// | 输入 | 输出 | 规则 |
  /// |---|---|---|
  /// | `entropic_brew` | `Entropic Brew` | 按 `_` 分词、每词首字母大写 |
  /// | `acid_slime_m` | `Acid Slime M` | 单字母词整体大写 |
  /// | `defend+` | `Defend+` | `+` 是升级标记，属于后缀 |
  /// | `standard.constricted` | `Constricted` | 去掉内容命名空间 |
  function prettifyId(id) {
    if (!id) return "";
    let text = String(id);
    const dot = text.lastIndexOf(".");
    if (dot >= 0) text = text.slice(dot + 1);
    let plus = "";
    while (text.endsWith("+")) { plus += "+"; text = text.slice(0, -1); }
    const words = text.split(/[_\s]+/).filter(Boolean).map((word) =>
      word.length <= 1 ? word.toUpperCase() : word.charAt(0).toUpperCase() + word.slice(1));
    return words.join(" ") + plus;
  }

  /// 屏幕上的名字：**替换表 → 内核/内容给的名字 → 美化 id**。
  ///
  /// `kernelName` 是可选的第二来源（遗物的 `DisplayName`、卡的 `NameKey`）。
  /// 顺序不能反：替换表必须能覆盖内核的名字，否则"改名"这件事做不到。
  function displayName(id, kernelName) {
    if (id && Object.prototype.hasOwnProperty.call(NAMES, id)) return NAMES[id];
    if (kernelName) return kernelName;
    return prettifyId(id);
  }

  const H = {
    ROUND: 0, TURN: 1, PHASE: 2, RESULT: 3, HP: 4, HP_MAX: 5, BLOCK: 6, WARD: 7,
    ENERGY: 8, ENERGY_MAX: 9, HAND: 10, ENEMIES: 11,
  };'''

t = sub(t, ANCHOR, NAMES, 'display names block')

# 导出（让 `ui_test.mjs` 能测纯函数）
t = sub(t, '''    RESULT_NAMES, INTENT_KINDS, ACTION_PLAY, ACTION_END_TURN,''',
        '''    RESULT_NAMES, INTENT_KINDS, ACTION_PLAY, ACTION_END_TURN,
    // §345：显示层名字（替换表 + 美化 id）
    NAMES, prettifyId, displayName,''', 'export')
io.open(RENDER, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② index.html：把"打印 id"的地方换成 displayName ────────────────────────
t = io.open(PAGE, encoding='utf-8').read()

# 药水腰带：原来直接印 id（`entropic_brew`）
t = sub(t, '''    const id = runRead.potionName(index) || "potion";''',
        '''    // §345：内核给 **id**，这里给名字（替换表 → 美化 id）。原来直接把 id 印在屏幕上。
    const id = RD_UI.displayName(runRead.potionName(index), "");''', 'potion belt')

# 遗物 chip：内核给的是 DisplayName（内容里的名字），替换表优先
t = sub(t, '''    chips.push(`<span class="chip relic">${esc(runRead.relicName(index) || "relic")}</span>`);''',
        '''    // §345：遗物的 `DisplayName` 是**内容**的名字；替换表（`RD_UI.NAMES`）优先。
    const relicId = runRead.relicId(index);
    chips.push(
      `<span class="chip relic">${esc(RD_UI.displayName(relicId, runRead.relicName(index)))}</span>`
    );''', 'relic chips')

# 敌人面板：`rd_env_enemy_name_*` 给的是敌人 **id**（`acid_slime_m`）
t = sub(t, '''const enemyName = (e) =>''',
        '''/// §345：敌人名 = 敌人 **id** 经显示层。内核给的本来就是 id（`acid_slime_m`）。
const enemyName = (e) => RD_UI.displayName(rawEnemyName(e), "");
const rawEnemyName = (e) =>''', 'enemy name wrapper')

# 商店四排：`title` 原来是空串（面板回退到 id）
t = sub(t, '''        snapshot.shopCards.push({
          id: shopCardId(slot),
          // No title export exists for shop stock; `describe` falls back to the id.
          title: "",''',
        '''        const cardId = shopCardId(slot);
        snapshot.shopCards.push({
          id: cardId,
          // §345：内核给 **id**，这里给名字（原来 `title` 是空串 ⇒ 面板把 id 印出来）。
          title: RD_UI.displayName(cardId, ""),''', 'shop cards title')

t = sub(t, '''        snapshot.shopColorless.push({
          id: shopColorlessId(slot),
          title: "",''',
        '''        const colorlessId = shopColorlessId(slot);
        snapshot.shopColorless.push({
          id: colorlessId,
          title: RD_UI.displayName(colorlessId, ""),''', 'shop colorless title')

t = sub(t, '''        snapshot.shopPotions.push({
          id: shopPotionId(slot),
          title: "",''',
        '''        const potionId = shopPotionId(slot);
        snapshot.shopPotions.push({
          id: potionId,
          title: RD_UI.displayName(potionId, ""),''', 'shop potions title')

t = sub(t, '''        snapshot.shopRelics.push({
          id: shopRelicId(slot),
          title: "",''',
        '''        const relicId = shopRelicId(slot);
        snapshot.shopRelics.push({
          id: relicId,
          title: RD_UI.displayName(relicId, ""),''', 'shop relics title')

# Boss 名：原来是写死的 "Slime Boss"
t = sub(t, '''    bossName: "Slime Boss",''',
        '''    // §345（缺口 G5）：本幕 Boss 的**敌人 id**（`slime_boss` / `the_guardian` / …）经显示层。
    // 原来是写死的 "Slime Boss" —— 第二、三幕会显示错的 Boss 名。
    bossName: RD_UI.displayName(
      readText(() => ex.rd_run_boss_id_len(), (ptr) => ex.rd_run_boss_id_into(ptr)),
      ""
    ),''', 'boss name')
io.open(PAGE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ③ smoke.mjs ─────────────────────────────────────────────────────────────
t = io.open('web/smoke.mjs', encoding='utf-8').read()
t = sub(t, '''  // §344: 缺口 G1/G2/G9 —— 局终判据、幕尽动作、篝火回复量。''',
        '''  // §345: 本幕 Boss 的**敌人 id**（显示层决定怎么念）。
  "rd_run_boss_id_len", "rd_run_boss_id_into",
  // §344: 缺口 G1/G2/G9 —— 局终判据、幕尽动作、篝火回复量。''', 'smoke REQUIRED')
io.open('web/smoke.mjs', 'w', encoding='utf-8', newline='\n').write(t)
print('§345 display layer + page wiring + smoke')

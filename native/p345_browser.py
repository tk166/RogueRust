"""§345 收尾：给敌人面板加 `data-enemy-id`，让浏览器判据查 **id** 而不是显示名。

## 为什么

浏览器判据原来这样取名字：`entry.split(/\\s+/)[0]`（面板文本的第一个词）。那在"页面直接印 id"
的时代等价于 id；现在页面印的是**显示名**（"Bronze Orb"），于是：

* 三个面板的第一个词都变成 "Bronze"（Boss 是 "Bronze Automaton"、两个球是 "Bronze Orb"）——
  判据分不出谁是谁，报 `got ["Bronze","Bronze","Bronze"]`。

⇒ 面板加 `data-enemy-id`（内核给的**敌人 id**），判据改查它。这比原来**更准**：
它验的是"这一格确实有身份"，而不是"第一个词长什么样"。显示名怎么变都不影响它 ——
这正是 §345 那条架构（内核给 id、显示层给名字）想要的性质。
"""

import io

PAGE = 'web/index.html'
TEST = 'web/browser_test.mjs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 页面：面板带 data-enemy-id ────────────────────────────────────────────
t = io.open(PAGE, encoding='utf-8').read()
t = sub(t, '''           data-enemy-panel="${e.slot}" ${aimable ? `data-target-slot="${e.slot}"` : ""}>''',
        '''           data-enemy-panel="${e.slot}" data-enemy-id="${esc(rawEnemyName(e.slot))}" ${
             aimable ? `data-target-slot="${e.slot}"` : ""}>''', 'enemy panel id attr')
io.open(PAGE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② 判据：另收一份 id ────────────────────────────────────────────────────
t = io.open(TEST, encoding='utf-8').read()

t = sub(t, '''  const enemySlots = () => {
    const panelEl = document.getElementById("enemies");
    // One entry per painted enemy: the panel gives each a data-enemy-panel ordinal.
    const shown = [...panelEl.querySelectorAll("[data-enemy-panel]")];
    return shown.map((el) => (el.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 40));
  };''',
        '''  const enemySlots = () => {
    const panelEl = document.getElementById("enemies");
    // One entry per painted enemy: the panel gives each a data-enemy-panel ordinal.
    const shown = [...panelEl.querySelectorAll("[data-enemy-panel]")];
    return shown.map((el) => (el.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 40));
  };
  /// §345：每个面板的**敌人 id**（内核给的那个）。显示名是显示层的事，判据只关心身份 ——
  /// 原来按"面板文本的第一个词"取名字，在页面开始印显示名（"Bronze Orb"）之后分不出谁是谁。
  const enemyIds = () => {
    const panelEl = document.getElementById("enemies");
    return [...panelEl.querySelectorAll("[data-enemy-panel]")]
      .map((el) => el.getAttribute("data-enemy-id") || "");
  };''', 'enemyIds helper')

t = sub(t, '''      out.act2.after = enemySlots();''',
        '''      out.act2.after = enemySlots();
      out.act2.afterIds = enemyIds();''', 'collect ids')

t = sub(t, '''const summonedNames = (act2.after || []).map((entry) => entry.split(/\\s+/)[0].trim());
want(summonedNames.filter((name) => name === "bronze_orb").length === 2,
  `act 2: both summoned orbs must be named bronze_orb; got ${JSON.stringify(summonedNames)}`);
want(!summonedNames.some((name) => /^enemy #/.test(name)),
  `act 2: a summoned enemy still has no name: ${JSON.stringify(summonedNames)}`);''',
        '''// §345：查 **id**（`data-enemy-id`），不查显示名的第一个词 —— 显示名由显示层的映射表决定，
// 判据关心的是"这一格确实有身份"（原来是按面板文本的第一个词，页面一印显示名就分不清了）。
const summonedIds = act2.afterIds || [];
want(summonedIds.filter((id) => id === "bronze_orb").length === 2,
  `act 2: both summoned orbs must carry the id bronze_orb; got ${JSON.stringify(summonedIds)}`);
want(!summonedIds.some((id) => id === "" || id === null),
  `act 2: a summoned enemy still has no id: ${JSON.stringify(summonedIds)}`);''', 'assert ids')
io.open(TEST, 'w', encoding='utf-8', newline='\n').write(t)
print('§345: data-enemy-id + browser assertion on ids')

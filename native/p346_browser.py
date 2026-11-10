"""§346 浏览器判据收尾：act1（走运行层）有值、act2（直接建）为空。

## 这两条断言在说什么

`data-encounter-id` 的来源是运行层的 `last_encounter`：

* **act 1** 那一场是"走地图 → 点开始战斗"开的，`rd_run_fight_begin` 会写 `last_encounter`
  ⇒ 钩子有值（`enc_...`）；
* **act 2** 那一场是 `rd_env_start_encounter` **直接建**的（调试/训练入口，不经过运行层）
  ⇒ `last_encounter` 是空的 ⇒ 钩子**应当是空串**。

第一版对 act2 断言"必须有值"，于是红在 `got ""` —— 而那是**正确行为**。
把这一条写成"应当为空"，等于把"这个钩子反映的是**运行层**的遭遇"这件事写进判据，
否则下一个人会以为它坏了。

`data-active-slot` 是**战斗**事实，两种入口都有值。
"""

import io

TEST = 'web/browser_test.mjs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(TEST, encoding='utf-8').read()

# ── ① act1：走运行层开战 ⇒ 收集两个钩子 ────────────────────────────────────
t = sub(t, '''  out.fight = { inFight: !document.getElementById("handPanel").hidden, energy: cell(8) };''',
        '''  out.fight = { inFight: !document.getElementById("handPanel").hidden, energy: cell(8) };
  // §346：**走运行层**开的那一场，两个钩子必须有值（见下面 782 行附近的断言）。
  out.fight.encounterId = document.getElementById("enemies").dataset.encounterId || "";
  out.fight.activeSlot = document.getElementById("enemies").dataset.activeSlot || "";''',
        'act1 collect')

# ── ② act2：直接建 ⇒ 遭遇 id 应当为空 ─────────────────────────────────────
t = sub(t, '''want(/^enc_/.test(act2.encounterId || ""),
  `act 2: data-encounter-id must name the encounter, got ${JSON.stringify(act2.encounterId)}`);''',
        '''// §346：act 2 的这一场是 `rd_env_start_encounter` **直接建**的（不经过运行层），所以运行层的
// `last_encounter` 是空的 ⇒ 钩子**应当是空串**。这条断言把"这个钩子反映的是**运行层**的遭遇"
// 写下来 —— 第一版断言"必须有值"，红在 `got ""`，而那恰恰是正确行为。
want(act2.encounterId === "",
  `act 2: a directly-built fight has no run-layer encounter, got ${JSON.stringify(act2.encounterId)}`);''',
        'act2 assert empty')
io.open(TEST, 'w', encoding='utf-8', newline='\n').write(t)
print('browser: act1 has values, act2 is empty')

"""§397 R0-1：横屏队形 **n ≤ 4 单排**（把 §361 的回退改回来）。

## 这轮审阅的第 1 条（P1）成立，而且是我自己的错

时间线：

* `8383837`（§360）按**用户原话**（"n<=4 的时候都只有一排"）把单排阈值改成 4；
* `35bf81a`（§361）照第十四轮 Review 的 P1-C 又改回 3 —— 那条审阅说"n=4 一排 4 名违反
  **每排 ≤ 3** 这条更早、更强的约束"。**但那条约束不存在**：`inv:` 里没有它，参考包也没有；
  它只出现在那条审阅自己的措辞里，然后被我抄进了注释和闸门断言（
  `native/ui_pure_check.mjs` 的"每排至多 3 名"就是这么来的）。

⇒ 教训：**审阅意见不能盖过用户明确说过的话**。审阅是证据的一种，不是需求来源；
一条"更强的约束"必须能指到 `inv:§` 或 wiki 原文，否则它只是审阅者的偏好。

## 修法

`singleRow = n <= 4`；n=5 → 3+2；n=6 → 3+3（每排仍不超过 3，但那是**结果**，不是阈值）。
注释、闸门断言、`port-plan` 一起改回，并把这条教训写进注释里，避免下一轮又"修回去"。
"""

import io


def patch(path, pairs, label):
    t = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert t.count(old) == 1, '%s: %r (%d)' % (label, old[:50], t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', label)


patch(
    'web-next/src/stage/formation.ts',
    [
        (
            '''  // 横屏：**每排至多 3 名**。n ≤ 3 只占一排，n ≥ 4 分两排（4 → 2+2，5 → 3+2，6 → 3+3）。
  //
  // ⚠️ 两条历史教训都在这里：
  // 1. 参考包写的是 `ceil(n/2)` / `floor(n/2)`，**n = 2 时"每排各 1 名"**，而每排只有一名时
  //    `rowX` 返回同一个 `mid` ⇒ 两个怪**上下叠在一条竖线上**，横屏看起来像竖屏。
  // 2. §360 为了修 (1) 改成 `n <= 4` 单排，结果 **n = 4 变成一排 4 名**，违反"每排 ≤ 3"这条
  //    更早、更强的约束（第十四轮 Review P1-C）。
  // 所以：单排的阈值是 **3**（一排最多 3 名），不是 4。
  const singleRow = n <= 3;''',
            '''  // 横屏：**n ≤ 4 单排**；n = 5 → 3+2；n = 6 → 3+3。
  //
  // ⚠️ 这里被改过三次，把账写清楚（否则下一轮还会有人"修回去"）：
  // 1. 参考包写 `ceil(n/2)` / `floor(n/2)`，**n = 2 时每排各 1 名**，而每排只有一名时 `rowX`
  //    返回同一个 `mid` ⇒ 两个怪**上下叠成一条竖线**，横屏看起来像竖屏（截图抓到过）。
  // 2. §360 修 (1)：按**用户原话**改成 `n <= 4` 单排。
  // 3. §361 照第十四轮 Review 的 P1-C 又改回 `n <= 3` —— 那条审阅说 4 名一排违反
  //    "**每排 ≤ 3** 这条更早、更强的约束"，但**那条约束并不存在**（`inv:§` 与参考包里都没有，
  //    只出现在审阅措辞里）。于是"用户明确说过的需求"被一条不存在的约束盖掉了。
  //
  // ⇒ 现在的规则：**单排阈值 = 4**（用户的明确需求）。n ≥ 5 才分两排，且每排仍然 ≤ 3 ——
  // 但那是 5/6 的自然结果，不是一条独立约束。
  const singleRow = n <= 4;''',
        ),
    ],
    'formation',
)

patch(
    'native/ui_pure_check.mjs',
    [
        (
            '''    // 规则：**每排至多 3 名** ⇒ n ≤ 3 单排，n ≥ 4 两排（4 → 2+2）。
    const wantUpper = n <= 3 ? n : Math.ceil(n / 2);''',
            '''    // 规则：**n ≤ 4 单排**（用户明确需求），n ≥ 5 才分两排（5 → 3+2、6 → 3+3）。
    const wantUpper = n <= 4 ? n : Math.ceil(n / 2);''',
        ),
        (
            '''  check(rowOk, "队形：横屏 n≤3 一排、n≥4 两排（每排 ≤3）");''',
            '''  check(rowOk, "队形：横屏 n≤4 一排、n≥5 两排（5 → 3+2、6 → 3+3）");''',
        ),
        (
            '''  // ⚠️ n=4 **不能**一排 4 名：原始约束是"每行 1–3 个"。§360 曾经为了修 n=2 的竖叠而放开到
  // n≤4 单排，那是把一条更早、更强的约束改掉了（第十四轮 Review P1-C）。
  const wide4 = formation.computeCombatFormation([0, 1, 2, 3], desktop);
  const upper4 = wide4.enemies.filter((enemy) => enemy.row === 0).length;
  const lower4 = wide4.enemies.filter((enemy) => enemy.row === 1).length;
  check(
    upper4 === 2 && lower4 === 2,
    "队形：横屏 4 个敌人 = 2+2（每排至多 3 名）",
    JSON.stringify({ upper: upper4, lower: lower4 })
  );
  check(
    upper4 <= 3 && lower4 <= 3,
    "队形：横屏每排人数 ≤ 3（对所有 n）",
    JSON.stringify({ n: 4, upper: upper4, lower: lower4 })
  );''',
            '''  // ⚠️ §397：n=4 **必须**一排 4 名（用户原话"n<=4 的时候都只有一排"）。
  // 这条断言在 §361 被改成"4 = 2+2"，理由是"每排至多 3 名"——而那条约束**不存在**
  // （只出现在上一轮审阅的措辞里）。审阅不能盖过用户明确说过的需求。
  const wide4 = formation.computeCombatFormation([0, 1, 2, 3], desktop);
  const upper4 = wide4.enemies.filter((enemy) => enemy.row === 0).length;
  const lower4 = wide4.enemies.filter((enemy) => enemy.row === 1).length;
  check(
    upper4 === 4 && lower4 === 0,
    "队形：横屏 4 个敌人**一排 4 名**（§397 用户需求）",
    JSON.stringify({ upper: upper4, lower: lower4 })
  );
  check(
    wide4.enemies.every((enemy) => enemy.row === 0) &&
      new Set(wide4.enemies.map((enemy) => Number(enemy.x.toFixed(2)))).size === 4,
    "队形：横屏 4 名**同一排且 x 两两不同**（不叠）",
    JSON.stringify(wide4.enemies.map((enemy) => Number(enemy.x.toFixed(2))))
  );''',
        ),
    ],
    'ui_pure_check',
)

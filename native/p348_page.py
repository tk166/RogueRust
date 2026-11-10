"""§348 页面/场景侧：P2-1（`noRun` 不再用 seed 哨兵）+ P2-2（未知 `pending` 必须显性化）。

## P2-1：`noRun` 改用 `rd_run_exists()`

原来 `noRun: ex.rd_run_seed() === -2147483648` —— 那是拿**数据域里的一个合法值**当"无值"哨兵，
而 `rd_run_start(i32::MIN, ..)` 并不拒绝这个 seed ⇒ 用那个种子开的局会被判成"未开局"。
现在 `noRun: ex.rd_run_exists() !== 1`。

## P2-2：兜底不能再无条件

`RAW` 最后一条原来是 `test: () => true`，于是 `SC-??` **不可达**：将来内核新增 `Pending = 99`，
页面会静默把它画成普通地图。现在：

* 兜底要求 `pending === 0`（地图只在"无待决"时才是兜底）；
* 表外的 `pending` 落到 **`SC-??`**，并且 `describe` 给它一份**显式**的"未知状态"面板
  （写出那个值），而不是"这个节点没有可做的事"。

⚠️ 与 §347 的"构造即互斥"配合：`SC-??` 不是 `SCENES` 的一条，它是 `classifyScene` 在
**一条都没命中**时的返回值 —— 所以它天然不会被包装层吞掉。
"""

import io

PANELS = 'web/ui_panels.js'
PAGE = 'web/index.html'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① ui_panels.js：兜底要 pending === 0；SC-?? 有显式面板 ──────────────────
t = io.open(PANELS, encoding='utf-8').read()

t = sub(t, '''    // 18 地图（兜底）：无条件 —— "前面一条都没命中"由包装层保证。
    { id: "SC-02", overlay: false, test: () => true },''',
        '''    // 18 地图（兜底）：**只在"无待决"时**才是兜底。
    //
    // §348（第十轮 Review P2-2）：这里原来是 `() => true`，于是 `SC-??` **不可达** ——
    // 将来内核新增一个 `Pending`，页面会静默把它画成普通地图。现在表外的 `pending`
    // 会落到 `SC-??`，由 `describe` 给一份**显式**的"未知状态"面板。
    { id: "SC-02", overlay: false, test: (s) => s.pending === 0 },''', 'fallback pending 0')

t = sub(t, '''      // SC-00 / SC-02 / SC-03b / SC-?? 都落在 `describeIdle`：
      // 前三个是"这一屏不是节点面板"（战斗由 `render()` 画、地图由 `renderMap()` 画），
      // 而 `SC-??` 是表外状态 —— 给它一句"这个节点没有可做的事"比空白好。
      default:
        return describeIdle(s);''',
        '''      // SC-??：**表外状态**（内核给了一个场景表里没有的 `pending`）。
      //
      // §348：它必须**显性**说出来，而不是画成地图或"这个节点没有可做的事" ——
      // 静默降级正是"新增一个 Pending，UI 悄悄画错屏"的形状。
      case "SC-??":
        return {
          title: "未知状态",
          lines: [`内核给的待决值 ${s.pending} 不在场景表里 · 这一屏不知道怎么画`],
          rows: [],
          buttons: [],
        };
      // SC-00 / SC-02 / SC-03b 落在 `describeIdle`：它们不是"节点面板"那一屏
      // （战斗由 `render()` 画、地图由 `renderMap()` 画），节点面板只是兜底。
      default:
        return describeIdle(s);''', 'SC-?? panel')
io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② index.html：noRun 用 rd_run_exists ──────────────────────────────────
t = io.open(PAGE, encoding='utf-8').read()
t = sub(t, '''    noRun: ex.rd_run_seed() === -2147483648,''',
        '''    // §348：**不要**用 `rd_run_seed() === i32::MIN` —— 那是一个**合法 seed**
    // （`rd_run_start` 不拒绝它），拿它当"无值"哨兵会让那一局被判成"未开局"。
    noRun: ex.rd_run_exists() !== 1,''', 'noRun')
io.open(PAGE, 'w', encoding='utf-8', newline='\n').write(t)
print('§348 page/panels: rd_run_exists + SC-?? explicit')

"""§381–§383 的文档。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


SECTION = '''

---

## §381–§383 玩家第二轮：宽度塌了、悬浮窗抖、定向牌不选目标、效果码、"红钥匙"

第二轮实机报障五条。第 1、2 条是**同一个根因**（宽度由内容决定）；第 3、4 条是**同一个根因**
（同一个词表被两处认识，一处没跟上）；第 5 条查证下来**内核是对的**，缺的是别的东西。

| # | 报障 | 根因 | 修法 |
|---|---|---|---|
| 1 | 地图宽度明显不对（节点压在一起） | `.scene` 有 `margin: 0 auto` ⇒ 作为 flex item 失去 `stretch`，宽度退回 **fit-content**；而 §376 把地图节点改成绝对定位之后，画布**没有固有宽度**了 ⇒ 整个场景塌成"最长那一行文字"的宽度（实测 230px） | `.scene { width: 100% }`（`width` + `max-width` + `auto` 外边距 = 占满但不超过上限并居中） |
| 2 | 悬浮窗宽度不固定，卡牌一列/两列来回跳 | `CardTip` 是 **`sticky`（在流内）**：面板宽度由文字长度决定 ⇒ 撑动容器 ⇒ 卡牌重排 ⇒ 鼠标下的牌换位置 ⇒ hover 换目标 ⇒ 面板换文字 ⇒ **死循环抖动** | `position: fixed` + `width: min(92vw, 520px)`（与容器、与文字长度都无关） |
| 3 | `观察意图`（观察弱点）不选敌人就结算 | 生成器判"要不要目标"只看 `sel.eventTarget`，而 `spot_weakness` 用 `conditional{ intent.targetIntendsAttack }` **间接**读事件目标 ⇒ 被判成无目标 ⇒ 界面把"牌 × 每个敌人"的多条动作**归并成一次无目标出牌**，条件读到空目标，力量一点没加 | 判据加上 `intent.target*`（88 张定向牌，穷尽核对） |
| 4 | 事件「翅膀雕像 · 祈祷」显示"未知效果 6（0）" | 界面 `effectLabel` 停在 §9 的 **1..5**，内核的效果码已经到 **16**（§143/§278/§280/§285 陆续加的）；而且 `-1`（"这一条没有效果码"）被画成"未知效果 -1" | 词表覆盖 1..16；`-1` 返回空串（调用方不画那一行）；祝福屏那份**复制品**改成复用同一个函数 |
| 5 | 篝火一开始就有红钥匙 | **内核是对的**：wiki 两个来源都说"任何篝火都能拿"（见下） | 缺的是①钥匙解锁（元进度）②第四幕本身 ⇒ `ACT4_IMPLEMENTED = false` 时不提供 Recall（白拿的空门票是陷阱） |

### 381.1 第 1、2 条的判据：**自比**

这两条都不能靠"某个具体像素值"守（窗口一变就红），所以闸门 56 用**自比**：

> 同一屏在「没有面板 / 指着第 1 张 / 第 2 张 / 第 3 张」四种状态下，
> **场景宽度、面板宽度、卡牌行数**都必须完全不变。

实测：`[720,720,720,720]` / `[520,520,520]` / `[1,1,1,1]`。修前是 `[330, 720, 330, 720…]` 这种来回跳。

⚠️ 第一版行数度量用 `getBoundingClientRect().top`，把 `.reward-card:hover` 的
`translateY(-1px)` 数成"换了一行"（报了假红 `[1,2,2,2]`）⇒ 改用 `offsetTop`（布局位置）。

### 381.2 第 3 条：为什么判据要"穷尽 + 落点"

只断言 `cardMeta.spot_weakness.targeting === "singleEnemy"` 不够 —— 那只能证明**这一张**。
闸门 56 做两件事：

1. **穷尽**：扫内容包 295 张牌，凡程序里出现 `sel.eventTarget` 或 `intent.target` 的，
   **每一张**都必须被标成 `singleEnemy`（当前 88 张，漏一张就红）；
2. **落点**：直接跑 `viewFromWasm`，断言 `optionsFor` 对 `spot_weakness` 给**每个敌人一个落点**
   （`[0,1]`），对 `defend` 仍然归并成一个 `slot: -1`。后半条是反证 ——
   没有它，"所有牌都变定向"也能让前半条绿。

### 381.3 第 4 条：闭集必须两边一样长

内核 `effect_code` / `effect_code_of` 是**闭集**，界面必须逐条对齐：

| 码 | 原子 | 码 | 原子 |
|---|---|---|---|
| 1 | `heal` | 9 | `curse:<id>` |
| 2 | `gold` | 10 | `relic:<id>` |
| 3 | `damage` | 11 | `damage_pct:<n>` |
| 4 | `max_hp` | 12 | `max_hp_pct:<n>` |
| 5 | `nothing` | 13 | `gold_cost` |
| 6 | `remove_card` | 14 | `heal_pct:<n>` |
| 7 | `upgrade_card` | 15 | `heal_full` |
| 8 | `transform_card` | 16 | `gold_random:<a>:<b>` |

`-1` **不是**"未知"：内核用它表示"这一条没有效果码"（§279–§324 的一贯做法：真正的作用在内容
字符串里，比如 `card:<id>` / `relic_lose:<id>` / `transform_choose:<n>`，而选项自己的文字已经
说清楚了）。把它画成"未知效果 -1（0）"是在**报告一个不存在的错误**。

闸门 56 遍历这 16 条断言每一条都有人话，并且**反证** `effectLabel(99)` 仍然响亮
（"未知"与"没有码"混成一件事是另一种错法）。

### 381.4 第 5 条：红钥匙 —— 查证结果

两个独立来源：

* fandom `Keys`：*"The Ruby Key is obtained by taking the Recall action at Rest Sites.
  **The key may be obtained at any Rest Site along the run.**"*
* wiki.gg `Mechanics`：*"Ruby Key: Can be obtained at a Rest Site by clicking the Recall action,
  instead of Smith or Rest (or Lift, Dig and Toke) at the same fire."*

所以**第一幕第一个篝火就能 Recall 是对的**。真正缺的是两件：

1. **解锁**：钥匙只在"用 Ironclad / Silent / Defect 各通关一次"之后出现
   （fandom `Keys`：*"Once the Act 3 Boss has been defeated with all characters except the
   Watcher at least once in a normal run, three keys will begin to appear"*）——
   我们没有任何元进度，等于"永远已解锁"；
2. **第四幕不存在**：钥匙唯一的用途是进 Act 4。于是 Recall 花掉一次篝火机会、
   换来一个永远用不上的布尔 —— 对玩家就是**陷阱选项**。

修法：`RunState::ACT4_IMPLEMENTED = false`，`campfire_options()` 在它为 false 时**不提供** Recall。
`rd_run_recall` 与 `ruby_key` 一个字节都没动，第四幕落地时把常量翻成 `true` 即可。
判据写成"选项 == 常量"（而不是写死 `false`），翻常量时测试自动继续有效。

### 381.5 闸门

**56 `ui-layout-words`**（13 条）：布局四条自比 + 定向牌两条穷尽/落点 + 效果词表四条 + 反证三条。

### 381.6 还欠的

* 悬浮面板 `fixed` 在底部 —— 鼠标用户可能希望它跟着指针（但那样又会和布局耦合，要小心）；
* 效果词表里 `curse:<id>` / `relic:<id>` / `card:<id>` 只画**类别**（"获得一张诅咒牌"），
  不点名具体是哪一张 —— 要点名得让内核把载荷也导出（`rd_run_event_effect_atom_*`）；
* 钥匙的**解锁条件**（三职业通关）没有元进度可依，只能等有了存档/成就系统再说；
* 第四幕（`The Ending`）本身仍是最大的缺口（`sts-wiki-gap.md` 最后一行）。
'''

PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §381' not in t
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + SECTION)

edit('README.md', '**聚合验收**：55 道闸门', '**聚合验收**：56 道闸门', 'readme gates')
edit(
    'docs/sts-wiki-gap.md',
    '| 篝火选项 | **六个全通**（§259）：Rest / Smith / **Recall**（红钥匙）/ **Lift**（`Girya`，最多 3 次、之后每场战斗带这些力量）/ **Toke**（`Peace Pipe`，删牌免费）/ **Dig**（`Shovel`，只抽 Common/Uncommon/Rare）',
    '| 篝火选项 | **六个全通**（§259）：Rest / Smith / **Recall**（红钥匙）/ **Lift**（`Girya`，最多 3 次、之后每场战斗带这些力量）/ **Toke**（`Peace Pipe`，删牌免费）/ **Dig**（`Shovel`，只抽 Common/Uncommon/Rare）。⚠️ §383：**Recall 当前不提供** —— wiki 允许任何篝火拿钥匙，但钥匙的用途只有第四幕（未实现）+ 解锁条件（三职业通关，无元进度）⇒ 提供一个永远用不上的选项是陷阱；`ACT4_IMPLEMENTED` 翻成 `true` 即恢复',
    'gap recall',
)
print('docs written')

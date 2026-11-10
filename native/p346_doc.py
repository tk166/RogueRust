"""§346 文档：G3 / G6 / G7 / G12 关闭 + G13/G14 正式不做。"""

import io

DOC = 'docs/ui-state-model.md'
PLAN = 'docs/port-plan.md'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(DOC, encoding='utf-8').read()

# ── ① §6 表：四条关闭 ──────────────────────────────────────────────────────
t = sub(t, '''| **G3** | **"我有没有某件遗物"要遍历 id** | `for i in 0..relic_count { relicId(i) }`（`singingBowl` 就这样） | `rd_run_has_relic(idPtr, len)` → `0/1`，或一个遗物**位掩码** | 小，但位掩码要随内容增长 ⇒ 用 id 查询更稳 |''',
        '''| ~~**G3**~~ | ~~"我有没有某件遗物"要遍历 id~~ | — | **已关闭（§346）**：`rd_run_has_relic(ptr, len)` → `1/0/-1` | 已完成。页面原来在**两处**各写了一遍遍历（漏一处不会红），现在一条查询 |''',
        'G3 closed')

t = sub(t, '''| **G6** | **没有"事件 id / 遭遇 id"** | 事件只有一行文本；战斗只有敌人名 | `rd_run_event_id_len/into`、`rd_env_encounter_id_len/into` | 中：`EV`/`ENCT` 段有 id，只是没导出 |''',
        '''| ~~**G6**~~ | ~~没有"事件 id / 遭遇 id"~~ | — | **已关闭（§346）**：`rd_run_event_id_len/into`（当前事件）、`rd_run_encounter_id_len/into`（这一场/刚打完那一场的遭遇） | 已完成。**都在运行层**：`last_encounter` 本来就是运行层字段（§153）；放 `rd_env_*` 会假装它是战斗状态 |''',
        'G6 closed')

t = sub(t, '''| **G7** | **祝福只有 2 个 offer（写死）** | `for slot in 0..2` | `rd_run_start_offer_count()` | 很小 |''',
        '''| ~~**G7**~~ | ~~祝福只有 2 个 offer（写死）~~ | — | **已关闭（§346）**：`rd_run_start_offer_count()` | 已完成 |''',
        'G7 closed')

t = sub(t, '''| **G12** | **"现在是谁的回合"只有文本** | `rd_env_active_len()` 返回 `Exec(...)` 那种诊断串 | `rd_env_active_slot()` → 墙位（`-1` 英雄 / `0..5`） | 小 |''',
        '''| ~~**G12**~~ | ~~"现在是谁的回合"只有文本~~ | — | **已关闭（§346）**：`rd_env_active_slot()` → 墙位（`-1` 英雄 / `0..5` 敌人 / `-2` 没人 / `-3` 没有会话）。诊断串 `rd_env_active_len()` **留着** —— 它能说出"卡在哪个节点"，而墙位说不出 | 已完成 |''',
        'G12 closed')

# ── ② G13 / G14 正式不做（写清理由，而不是留着"以后再说"）────────────────
t = sub(t, '''| **G13** | **手牌没有 id 导出** | 只有 `def_slot` + 名字/标题/文本 | 3D 图集按 `def_slot` 建表即可 | 0（够用，但要知道 `def_slot` 是**内容行号**，跨版本会变） |''',
        '''| ~~**G13**~~ | ~~手牌没有 id 导出~~ | — | **不做（§346 判定）**：`def_slot` 是**内容行号**，跨版本会变 —— 但 3D 图集要的就是"这一份内容里的第几行"，而 id 反而是第二把键。手牌有 `name`/`title`/`text`/`kind` 四份文本，够画一张牌 | 0（不做的理由已写清，不再当"待办"） |''',
        'G13 wontfix')

t = sub(t, '''| **G14** | **费用的"未修饰 vs 修饰"不分离** | 只有最终价；每副本 delta 不可见 | 若要演"这张牌降价了"，需要 `rd_env_card_cost_printed(slot)` | 小 |''',
        '''| ~~**G14**~~ | ~~费用的"未修饰 vs 修饰"不分离~~ | — | **不做（§346 判定）**：观察向量给的是**最终价**，而"演一次降价动画"需要知道原价。但那件事今天**没有消费者**（动画走 `diffObservations`，它只看最终价变没变）；真要做时再加 `rd_env_card_cost_printed(slot)` | 0（同上） |''',
        'G14 wontfix')

# ── ③ §2.1 顶栏与 §3.10 事件：三个新钩子的落点 ───────────────────────────
t = sub(t, '''| `bossId` | 敌人 id（`slime_boss` / …） | 换幕 | `R.txt(boss_id)` = `rd_run_boss_id_len` / `rd_run_boss_id_into` | T1 |''',
        '''| `bossId` | 敌人 id（`slime_boss` / …） | 换幕 | `R.txt(boss_id)` = `rd_run_boss_id_len` / `rd_run_boss_id_into` | T1 |
| `encounterId` | 遭遇 id（`enc_...`） | 开战 | `R.txt(encounter_id)` = `rd_run_encounter_id_len` / `rd_run_encounter_id_into` | T1 | §346：**运行层**字段（`last_encounter`）；挂在 `#enemies` 的 `data-encounter-id` 上 |
| `activeSlot` | `-1` 英雄 / `0..5` 敌人 / `-2` 没人 / `-3` 没有会话 | 每回合 | `rd_env_active_slot()` | T2 | §346：挂在 `#enemies` 的 `data-active-slot` 上（DOM 版靠 `next up` 表达，高亮交给渲染层） |''',
        'top bar hooks')

t = sub(t, '''| `text` | 字符串 | `R.txt(event_text)` | 一行描述（3D 需要**事件 id** 才能选背景，§6-G6） |''',
        '''| `text` | 字符串 | `R.txt(event_text)` | 一行描述 |
| `id` | 事件 id（`golden_idol` / …） | `R.txt(event_id)` = `rd_run_event_id_len` / `rd_run_event_id_into` | §346：**美术按 id 选背景**，文本会随文案改动。没有事件时是**空串**（不是 `-1`） |''',
        'event id row')
io.open(DOC, 'w', encoding='utf-8', newline='\n').write(t)

# ── ④ port-plan §346 ─────────────────────────────────────────────────────
SECTION = """
## §346 四条小缺口：G3 / G6 / G7 / G12（+ G13/G14 正式不做）

`ui-state-model.md` §6 里剩下的四条"做不好看"那一档的缺口，加两个**判定不做**。

| 缺口 | 导出 | 为什么值得加 |
|---|---|---|
| **G3** 页面靠遍历遗物找 `singing_bowl` | `rd_run_has_relic(ptr, len)` → `1/0/-1` | 页面有**两处**各写了一遍循环（漏一处不会红）—— 而"哪件遗物决定哪个按钮"在内核里已经有一份 |
| **G6** 没有事件/遭遇 id | `rd_run_event_id_*`、`rd_run_encounter_id_*` | 3D/美术要按 id 选背景；文本（一行描述）做不到 |
| **G7** 祝福数量写死 2 | `rd_run_start_offer_count()` | 内容一变就静默少画一个按钮 |
| **G12** "现在是谁的回合"只有诊断串 | `rd_env_active_slot()` → 墙位 | `Exec(...)` 那种串不是给渲染层索引的 |

### 两处放对位置的决定

1. **遭遇 id 放运行层**（`rd_run_*` 而不是 `rd_env_*`）：`last_encounter` 本来就是运行层字段
   （§153：下一场避免重复）。战斗期间它就是这一场的遭遇，战斗结束后它仍然保留。放 `rd_env_*`
   会假装它是战斗状态 —— 而它不是。
2. **`rd_env_active_len()` 留着**：那是**诊断串**（能说出"卡在哪个节点"），新导出是**墙位**
   （能直接索引）。两个都留着，因为两件事都要有人能问。

### 页面接线：三个 `data-*` 钩子

`data-event-id`（`#nodePanel`）、`data-encounter-id` 与 `data-active-slot`（`#enemies`）。
DOM 版**自己不消费**它们（正文与 `next up` 已经画好了），它们是给 3D/美术层读的 ——
而"写了但没人读"正是本项目最恨的形态之一，所以浏览器判据要断言它们在真实局面里**有值**。

⚠️ 两个坑，都是判据当场抓出来的：

* **`data-encounter-id` 挂在 `renderTopBar()` 里时战斗中恒为空串** —— 那个函数不在战斗重绘路径上。
  挪进 `render()`（战斗容器的唯一写者）才对。
* **act 2 那一场是 `rd_env_start_encounter` 直接建的**（不经过运行层）⇒ `last_encounter` 是空的
  ⇒ 钩子**应当是空串**。第一版断言"必须有值"，红在 `got ""` —— 而那恰恰是正确行为。
  现在判据把它写成"应当为空"，等于把"这个钩子反映的是**运行层**的遭遇"这件事写进判据。

### `rd_env_active_slot` 的一个哨兵差点说谎

第一版用了 `ensure_session()` —— 那个函数会**懒建**一个会话，于是"没有会话"永远到不了，
`-3` 就是一个永远不出现的哨兵。**查询不该创建状态**，改用 `slot()`。

### G13 / G14：正式不做（理由写清，而不是留着"以后再说"）

* **G13 手牌 id**：`def_slot` 是**内容行号**，跨版本会变 —— 但 3D 图集要的就是"这一份内容里的
  第几行"，id 反而是第二把键。手牌已有 `name`/`title`/`text`/`kind` 四份文本，够画一张牌。
* **G14 费用拆分**：观察向量给的是**最终价**，而"演一次降价动画"需要原价 —— 但那件事今天
  **没有消费者**（动画走 `diffObservations`，只看最终价变没变）。真要做时再加
  `rd_env_card_cost_printed(slot)`。

### 判据与负控

| 判据 | 钉住什么 |
|---|---|
| `the_run_facts_the_ui_asks_about`（rd-wasm） | 五个导出各测**两侧**（恒 1 / 恒空 / 恒 -1 的实现都会各红一次） |
| 浏览器 `act 1` 段 | 走运行层开的那一场，`data-encounter-id` / `data-active-slot` **有值** |
| 浏览器 `act 2` 段 | 直接建的那一场，`data-encounter-id` **是空串**（钩子反映的是运行层的遭遇） |

负控 **5/5**（`native/p346_negative.py`）：`has_relic` 恒 1 / `offer_count` 恒 0 /
`event_id` 没事件时返回垃圾 / `active_slot` 用回 `ensure_session()` / 遭遇 id 挂回 `renderTopBar`。

### 数字

`rd-wasm 189`（188 + 1）、`rd-run 225`、`rd-core 819`、units **1233**（下限 1232 → 1233）；
导出 226 → **233**；四条对拍不动；`WEB_SMOKE` / `UI_RENDER` / `MAP_RENDER` / `BROWSER_TEST` PASS；
23/23 闸门。
"""

p = io.open(PLAN, encoding='utf-8').read()
assert '## §346' not in p
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(p.rstrip('\n') + '\n' + SECTION)
print('ui-state-model G3/G6/G7/G12 closed + G13/G14 wontfix ; port-plan §346')

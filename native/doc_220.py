"""§220 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §220 两个生命周期载体：`Drawn` 与 `Exhausted`（以及一次被对拍挡回来的设计）

§219 结尾说还剩两条"真正缺载体"的：`void` 的"抽到时失去 1 能量"与 `sentinel` 的"被消耗时 +2 能量"。
这一节把它们做出来。**过程里最值钱的不是功能，是那条被 `FIGHT_DIFF` 挡回来的设计**。

### 220.1 事件与钩子

参考的 `CardLifecycleTrigger` 只有 `TurnEndInHand` 一个成员，这两个是**我们自己的扩展**
（与 §198 的 `Operation::ScalePercentPerStack` 同级）。内核侧：

* `state::CardLifecycleEvent { Drawn, Exhausted }` + `lifecycle_name_matches(name, wanted)`：
  名字→事件，**不认识的键仍然 `IrError::UnknownKind`**（"内容写了本层读不懂的触发器"不是"没有触发器"）；
* `host::card_lifecycle_program(content, definition, wanted)`：`LifecyclePrograms` 里按**指定事件**
  取节目（原来那个只认 `TurnEndInHand` 的函数泛化而成）；
* `host::run_card_lifecycle(state, content, owner, definition, event)`：**有节目才跑**
  （`execute_program`，与回合末生命周期同一条路）；
* `TurnHost::card_drawn` / `card_exhausted`：两个钩子，**默认空实现**（只有知道内容的宿主才有节目）。

触发点（都是"卡真的跨过边界"的地方）：

| 事件 | 触发点 |
|---|---|
| `Drawn` | 回合开始抽牌（手牌尾部新增的那几张，按堆序逐张）；`drawCards` 效果节点 |
| `Exhausted` | 回合末手牌清扫（虚无）；`MoveCardToZone` 请求（= 打出即消耗 + 内容自己搬牌） |

### 220.2 第一版设计与它为什么被挡回来（这一节的重点）

第一版把通知做成 `EffectRequest::CardLifecycle`，从 `state.move_card` 这个**唯一漏斗**上发。
理由听起来很对（"一个漏斗，漏不掉"），结果：

* 一次纯状态测试（池槽位不回收）连搬 1000 次牌 ⇒ 64 格效果队列在第 64 次满了 ⇒
  **"搬一张牌"开始报 `Full(PendingEffects)`**。状态操作不该依赖效果队列的深度。
* 更要命的是对拍：`FIGHT_DIFF` **182/182 → 18/182**、`CARD_DIFF` **62/62 → 0/62**，
  分叉全在 `chain_num` 那一行 —— 每一次入队都会 `??` 出一条根链、推进 `next_effect_chain_number`，
  而**参考实现根本没有这条请求**。也就是说：给"没有节目的牌"也发一条通知，等于改了哈希契约。

现在的设计把这两件事分开：

* **知道内容的层**（宿主 / `exec` 的节点）决定"要不要跑"，**没有节目就零开销**（不入队、不发号）；
* 状态层保持纯粹（`move_card` 只搬牌）。

对拍恢复 **182/182 · 62/62 · 124/124 · 394/394**，这本身就是"零开销"这条设计的证据。

### 220.3 内容与判据

* `void`（`Drawn` → `loseResource energy 1`）、`sentinel`（`Exhausted` → `gainResource energy 2`）、
  `sentinel+`（3 —— 节目挂在**定义**上，升级行有自己的一份）。
* 内容门新增 `check_card_lifecycle`：`LifecyclePrograms` 的**键集合**与**事实**两个方向都查；
  `program_facts` 补了 `gainResource` / `loseResource` 两个节点（否则事实列表是空的，pin 没有区分力）。
  ⚠️ 这条新闸门第一次跑就翻出一笔旧账：**`burn+` 的回合末 4 点伤害从来没有被 pin 过**
  （§175 只写了"由 card-lifecycle 测试检查"，而那条测试只覆盖手搓镜像）。
* 判据走真实状态机：
  - `a_void_drawn_from_the_pile_costs_one_energy`：回合开始抽牌 ⇒ 能量 3 → 2；
  - `a_sentinel_that_gets_exhausted_pays_two_energy`：回合末虚无 ⇒ 能量 0 → 2（`sentinel+` → 3）。
* 负控：删掉 `void` 的 `Drawn` 节目 ⇒ 内容门点名 + 测试 `left: 3 right: 2`；
  把 `sentinel` 的 2 改成 7 ⇒ 内容门点名 + 测试 `left: 3 right: 2`。
* 顺带修正一条**过时的测试前提**：`a_lifecycle_trigger_other_than_turn_end_in_hand_is_loud`
  原本断言"`Drawn` 必须响亮"（它是缺口时代的写法）；现在 `Drawn` 支持了，于是它改成
  "回合末扫描对 `curse.weird` 返回 `Ok(())`"，而"未知键响亮"这条性质改由映射表钉住
  （`lifecycle_name_matches("Teleported", None) == None`）。

### 220.4 一个判据写法上的坑

`sentinel` 的第一版判据把能量留在 3/3 就去断言"加了 2 点" —— 结果是 3：**`gain 2` 被上限吃掉了**，
"给了 2 点"与"一点没给"在数值上完全一样。判据必须先 `give_energy(0)` 腾出空间。
同族的坑在 §212（靶子血不够）、§219（敌人没有力量）都踩过：**先确保这一格能显示出差值**。

### 220.5 数字

* **21/21 闸门绿**，单测 **909**（708 core + 108 run + 93 wasm，比 §218 多 3 条）；四条对拍不变。
* 镜像 **81,200 B**（core 68,640；+244 B：三条 `LifecyclePrograms` + 两个资源节点）。
* 矩阵 **361 行**、具名测试 **911**、`SourceTie:wiki` 224（卡牌的 `Drawn`/`Exhausted` 也进 pin）。
* 与 §218/§219 的偏差表一致：`void` 与 `sentinel` 的"没有载体"说明已删/收窄（`sentinel` 只剩
  `ethereal` 标签这一条）。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §220' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §220 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
for old, new in [
    ('（§1–§219，每一轮都留数字、记下被推翻的结论）', '（§1–§220，每一轮都留数字、记下被推翻的结论）'),
    ('编译成 80,956 B 的 `rdcf` 镜像（core 镜像 68,396 B）', '编译成 81,200 B 的 `rdcf` 镜像（core 镜像 68,640 B）'),
]:
    assert readme.count(old) == 1, old[:40]
    readme = readme.replace(old, new)
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme)
print('README updated')

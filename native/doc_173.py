"""Append §173 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 173. 精英池扩容：内容写完了、机制验过了，最后被一个**既有死锁**挡住

这一节是**没落地的一节**，留在这里的原因是它记下的东西比"又加了三个精英"值钱。经过：
内容全写完、门全绿（19/20）、两个新机制都被测试证明、然后 `web-soak` 抓到**敌方回合跑不完**
的死锁。按纪律（闸门不绿就不算做完）内容已回退到 HEAD；补丁脚本、wiki 取数与下面这些结论留作
下一轮的起点。

### 173.1 写完了什么（可复现）

`native/patch_173_elites.py` 一次生成全部内容；`native/patch_173_inventory.py` 同步内容门里的清单
（`sts_content_check.py` **就是** `sts-act1-inventory.md` 的可执行版本，加内容就必须同时加它）。

| 精英 | HP | 招式（A0） | 出处 |
|---|---|---|---|
| **Lagavulin** | 109-111 | Metallicize 8；Sleep ×3（什么都不做）；Attack 18；Siphon Soul（−1 力量/−1 敏捷） | `wiki/Lagavulin` |
| **Book of Stabbing** | 160-164 | Multi Stab 6×N（N = 使用次数 + 2）；Big Stab 21 | `wiki/Book_of_Stabbing` |
| **Taskmaster** | 54-60 | Scouring Whip 7 + 1 张 Wound 进弃牌堆 | `wiki/Taskmaster` |
| （Slavers 遭遇） | — | Taskmaster + Red Slaver + Blue Slaver，顺序即回合顺序 | `wiki/Slavers` |

加上一张 **Wound** 牌（`slimed` 同形：status / unplayable / 无程序）。池子变成
Act1 `Elite` 3 个、Act2 `Elite2` 3 个 —— 与 wiki 的"每幕三个精英"对上。

### 173.2 两个机制真的跑通了（这是最有价值的部分）

两条测试都用 `build_session_at(seed, "enc_…")` 直接建遭遇，再走 `rd_env_step(结束回合)`：

* `lagavulin_sleeps_for_three_rounds_and_then_attacks`：连续三个结束回合英雄血量**不变**，
  第四个回合正好掉 18。它的做法值得记：`intent.round <= 3 → lagavulin.sleep`（优先级规则 + 空程序
  动作），而 `Actions` 刻意排成 `[siphon_soul, attack]`，让第 4 回合的 `(4-1) % 2 = 1` 落在 Attack ——
  wiki 说它醒来立刻攻击。
* `book_of_stabbing_escalates_by_its_own_use_count`：三下 Multi Stab 打出 **18 / 21 / 24 / 21 / 30**
  （与 Big Stab 交替），完全对上 wiki 的 `6 × N`。

### 173.3 ★ 三个内容侧的真发现

1. **`CounterId` 有两种拼法，写错会静默错位**。`node.setCombatantCounter` 的 `CounterId` 在源 JSON 里
   是 `{"value": "…"}`（字符串字面量方言），而 `combatantCounter` **表达式**的 `CounterId` 是裸字符串。
   我一开始两处都写裸字符串 ⇒ 编码错位 ⇒ **后面所有 term 移位** ⇒ 一条**无关的** `ritual` 触发器读到
   非 term（`Ir(WrongKind("F_TERM"))`）。表现是"改 A 坏了 B"，找了一轮才定位。
   ⚠️ 我因此一度去"修" `sts_content_check.py` 里那行 `body["CounterId"]["value"]` —— **它原本是对的**，
   内核读的是编译后的 `F_STR`，源方言是编译器的事。
2. **效果是入队的，程序读不到自己刚写的计数器**。`setCombatantCounter` 把请求**入队**，所以
   "先 bump 再 `repeat`"里的 Count 读到的仍是旧值（实测 12 = (0+2)×6）。改成"读旧值 + 3，再 bump"，
   与 wiki 的 `N = 使用次数 + 2` **恒等**（第一次 0+3=3、第二次 1+3=4…）。递增仍成立、语义也仍然精确。
3. **`fx.incrementCounter` 在镜像里有名字、内核里没有 dispatch**（`ir.rs` 的清单里出现一次，
   `exec.rs` 里零处）。所以递增只能写成 `setCombatantCounter` 的"读+1 再写回"或"相对 +1"。

### 173.4 ★ 挡住落地的那个死锁（未修，下一轮第一件事）

`web-soak` 在 seed 102 上抓到（**可复现**）：

```json
{"panel":"精英节点（3 × Sentry）开始战斗","envActions":0,"envDone":0,"envResult":0,
 "duringFight":true,"handCards":0,"endDisabled":true,"turnPhase":0,
 "log":[…,"—— 第 5 回合 · 2 ——","打出 strike、defend、bash、metallicize"],
 "lastClicks":[…,"panel:开始战斗","use-potion:0 用"]}
```

判读：日志里 `leftHand`（回合结束弃牌）之后进入 **round 5 · turn 2**（敌方回合），然后**再没有任何
推进**；`active_combatant_id` 停在敌人身上，于是 `hero_is_active == false` ⇒ 动作表里既没有牌也没有
"结束回合" ⇒ 页面无处可点。

两条已排除/已确认的事实：

* **父提交（`105659c`）同一 seed 跑 soak 是绿的** ⇒ 这个状态在我的内容下才走到。不是我的内容"算错"，
  而是它改变了走的路径（精英池从 2/1/1 变成 3/3/1，RNG 抽到的遭遇与以前不同）。
* 一个"贪心打第一张牌 + 结束回合"的内核复现**没有**复现出来（`diag_greedy…` 测试通过），
  所以触发条件大概率在**药水/选牌**那条交互路径上（卡死前最后一个动作是 `use-potion:0`）。

⇒ 下一轮的第一件事不是加内容，而是**让"敌方回合跑不完"不可能发生**：`run_fight` 的驱动在
"Ongoing 且 active 不是英雄且动作表为空"时必须是**响亮错误**（或自动推进），而不是安静地停住。
这条一旦修好，§173 的内容可以直接从补丁脚本重新生成（脚本是幂等的：已存在的 id 不会重复追加）。

### 173.5 还差的两个精英（下一轮的后半）

按同样的口径还差 Act 3 的 **Nemesis** 与 **Reptomancer**，各自的机制缺口已经查清：

* **Nemesis**（HP 185，Tri Attack 6×3、Tri Burn 3 张 Burn 进弃牌堆、Scythe 45，"隔回合无形"）：
  `remainder` 表达式在（`expr.rs` 有 `remainder`），`roundNumber` 也在 ⇒ "隔回合"可表达；
  但"无形"要挂在一个**回合开始的触发器**上，而敌人的触发器只能挂在**状态**上 ⇒ 要么给 Nemesis 造一个
  载波状态（内容可加，但会多一个可见状态），要么内核支持"遭遇级触发器"（`ENCT.TriggeredEffects`
  今天被读出来但**没有人执行**）。
* **Reptomancer**（HP 180-190，Spawn Dagger / Big Bite 30 / Snake Strike 13×2 + 1 Weak）与 **Dagger**
  （HP 20-25，Wound 9 + 1 张 Wound / Explode 25 且自身死亡）：召唤有 `node.createCombatant`（Slime Boss
  分裂在用），但**没有 `destroyCombatant`** ⇒ "Explode 之后自己死"表达不出来。

### 173.6 数字

内容侧（生成后实测）：34 怪 / 25 遭遇 / 37 卡 / 71 敌动作，镜像 40,988 B（core 33,952 B），
`STS_CONTENT PASS`；`rd-wasm` +2 个机制测试（62 个）；20 项门里 19 项绿。
**但这一节没有交付**：`web-soak` 红 ⇒ 按纪律回退，工作树回到 `105659c` 的状态。

### 173.7 教训

**"内容加完、门绿了"不等于"能玩"。** 这一轮 19/20 的门、814 个单测、两条机制测试全绿，而一个随机
soak 在第 108 次点击时把局面卡死。这正是 soak 存在的理由 —— 它也是唯一一道**用时间换状态覆盖**的门。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "## 173." not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()

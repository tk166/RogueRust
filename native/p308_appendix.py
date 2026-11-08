"""把"我对这份审阅报告的核对结论 + 实施计划"附在报告末尾。

为什么附在报告里而不是另写一份：这份报告是**外部输入**，它的结论要不要执行取决于核对结果；
把核对结论写在它自己的末尾，下一次读它的人不会先读一半就开工。
"""
import io

PATH = 'D:/Vibe/sts-tui/docs/vibe/Review_2a8d87a_5842c59_07_Content_Scaling.md'

APPENDIX = r'''

---

# 附：本仓的核对结论与实施计划（§308 起）

> 写于 `5842c59` 之后。**下面每一条都对着源码验过**，不是对报告的重述。
> 核对时用的工具留在 `native/check_state_fields.py`（字段清点，已加成闸门 22）。

## A.1 逐条判定

| 报告条目 | 判定 | 证据 |
|---|---|---|
| P0 `RunState` 新字段未接存档/回放指纹 | **真，且比报告的清单更长** | 报告列 5 组；穷尽遍历结构体是 **18 个字段**：`marks` `bosses_fought` `event_step` `event_resume` `event_next` `event_fight` `event_fight_pool` `fight_gold_bonus` `fight_gold_set` `fight_no_relic` `fight_relic_rarity` `fight_extra_relic` `fight_relic` `fight_potion_chance` `chest_extra` `chest_empty` `pickup_relics` `pickup_potions`。其中 `event_step` 是**指纹有、存档没有**（报告说"哈希覆盖不全"，方向对，但两栏是不对称的） |
| P0 "`marks` 不进 hash 的理由不成立" | **真**（那句话是本仓自己写的） | `state.rs` 原注释：*"它不进 run hash：参考的运行层没有这个概念"* —— 把 `hash_golden`（参考逐字节复刻）与 `hash.rs`（**我们自己**的回放指纹）混为一谈。已改 |
| P1 拾取类遗物无失败原子性 | **真（潜伏）** | `PickupTinyHouse` / `PickupAddCards` 先改金币/上限/欠账，再 `roll_pickup_offer(pool)?`。只有 `pool=[]` 时可达（真调用方都给全池），但它违反本仓"拒绝 ⇒ 一个字节都不改" |
| P1 `CombatBonus` 满容时静默丢 | **真，且不是"待复现"** | `MAX_COMBAT_STATUSES = 4`，`combat_bonus` 里 5 处 `let _ = bonus.push_status(...)`。**合法组合直接超**：`vajra`(力量) + `oddly_smooth_stone`(敏捷) + `thread_and_needle`(镀甲) + `bronze_scales`(荆棘) + `orichalcum` = 5 条，第 5 件静默失效。不需要稀有组合 |
| P1 `Orange Pellets` 效果错 | **真** | 内容状态行 `standard.orange_pellets` 的 `DescriptionKey` 与程序就是"+3 力量 +3 敏捷"；wiki 是 *"Whenever you play a Power, Attack, and Skill in the same turn, **remove all debuffs**"*（wiki 页 + Debuff 页两个独立来源）。**成本比报告估的高**：今天内容里没有任何"清 Debuff"节点，要走 `status_catalog` 的 `polarity`（`is_debuff()` 已有）+ 新节点，不是纯 JSON |
| P2 `Nilry's Codex` 进顶 vs 洗入 | **真，但已声明** | wiki：*"choose 1 of 3 random cards to **shuffle into** your draw pile"*。`docs/sts-wiki-gap.md` §F.19 早就写了"进**顶**不是洗入" |
| P2 `Dead Branch` 无色池 | **真，但已声明** | 同 §F.19（"池子是任意基础牌（含无色）"） |
| P2 `Cauldron` 记成逐项欠账 | **真，但根因是 P0** | 欠账本身是设计选择（`pickup_potions`），问题在它**没进存档**（已随 §308 修） |
| §7 `event-gaps.md` 的 `Mind Bloom` 描述错 | **真，是我写的** | wiki 四选项：*I am War*（打第 1 幕 Boss + 稀有遗物 + 50/25 金）、*I am Awake*（升级所有牌 + **Mark of the Bloom**）、*I am Rich*（999 金 + 2 `Normality`）、*I am Healthy*（回满 + `Doubt`）；第三项在 Rich/Healthy 之间换。我写的"复制整副牌"**根本不存在** |
| §7 `ancient_writing` 名不符实 | **真** | 我们的正文是 "Glyphs older than the Spire cover the wall."（升级一张牌），不是 wiki 的 Ancient Writing。**同名 id 会让下一次 wiki 对账看起来"已做"** |

## A.2 报告加分的地方

**它的证据路径是对的**：`Orange Pellets` 的错在**内容 JSON 的 `Statuses` 行**里（遗物行只带
`DisplayName`/`Rarity`，行为挂在"开战状态"上）。核对时一度以为是它看错了层，查完发现是我错。

## A.3 它没看出的两件事（比它列的更坏）

1. **那条"整局相等"的存档判据是瞎的。** `archive.rs` 的 round-trip 测试写着
   *"`RunState` 派生 `PartialEq`，所以判据是整局相等 —— 漏还原一个字段就红"*，
   而夹具 `sample()` 只设了六个字段：**漏 18 个字段它照样绿**。
   ⇒ 修字段只是第一步，**把夹具做成"每一格都非默认"** 才是那一条判据开始工作的时刻。
   负控已做：删掉 `chest_extra` 的写入、删掉 `marks` 的写循环，两次都红（`native/p308_negative.py`）。
2. **`docs/sts-wiki-gap.md` 的"wiki"那一列是从我们自己的行为抄的。**
   §F.19 原文：`orange_pellets | wiki: 一回合内 Power+Attack+Skill ⇒ +3 力量/敏捷 | 已做 | **一致**`
   —— 代码错 → 文档把错的行为写成"wiki 语义" → 对账永远通过。
   更糟的是 `coverage-matrix` 把 `orange_pellets_pays_once_all_three_card_kinds_were_played`
   （测试名本身把错规则写死）记成 `Implemented + TestNamed`：**这条测试会替 bug 站岗**。

## A.4 与报告不同的优先级

| 报告 | 本仓 |
|---|---|
| 1. P0 存档（六项并成一格） | **`event_step` 排第一**：事件中途存档＝重开时静默跳回第一屏（玩家按一次"保存"就撞上）；`marks` 要 `Ritual Dagger` 才可见 |
| 4. P1 `CombatBonus` 容量 | **提到与 P0 同级**：合法遗物组合 5 件就触发，且失败是静默的；上限 4 是我们自己写的，加宽到 8 只是一行 |
| 2. P1 `Orange Pellets` | **第二位**，但成本含一个新节点 + 一条替 bug 站岗的测试要一起改 |
| 6. 内容：Act 2/3 事件 | **报告漏了更大的一个**：Act 2 **普通遭遇池只有 3 条**（wiki 13 种组合） |
| §8 建议"15–30 个四联索引" | 同意，但落地成 `coverage-matrix` 的第 5 列（wiki 条款 id），**不要新建一份清单** —— 否则同一份事实第二存法 |

## A.5 实施计划

| 节 | 等级 | 工作 | 验收 |
|---|---|---|---|
| **§308** | P0 | 18 个字段同时进存档与指纹；`sample_full()` 做成总夹具；两个 `marks` 遗留（删牌不清尾槽、加牌继承）| `STATE_FIELDS PASS (63 fields)`（**新闸门 22**）+ round-trip 在总夹具上跑 + 两条负控红 |
| **§309** | P1 | `CombatBonus` 容量（加宽 + 失败不再静默）；`PickupTinyHouse`/`PickupAddCards` 的原子性（失败时 `state == before`）| 5 件合法遗物组合的状态条数 == 5；空池返回错误时整局相等 |
| **§310** | P1 | `Orange Pellets` 改成"清 Debuff"（新内容节点 + `polarity`）+ 修 §F.19 的"wiki"列 + 改掉那条站岗测试 | Weak/Frail 被清、Buff 保留、三类牌时序；一条"wiki 条款 → 节点 → 断言"的样板 |
| **§311** | 文档 | `event-gaps.md` 的 `Mind Bloom` 事实错误、`ancient_writing` 改名、Act 2 池缺口进 README | 与 wiki 逐条对齐 |

一组**不做**的（报告与我都同意）：重写 Core/Run/WASM 分层、开 V2、为嵌入式预算限制 WASM 内容、
把像素门禁变成开发阻塞。
'''

def main():
    text = io.open(PATH, encoding='utf-8').read()
    assert ' 附：本仓的核对结论' not in text
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.rstrip('\n') + '\n' + APPENDIX)
    print('appendix appended, %d bytes' % len(APPENDIX))


main()

"""§268 接线判据 + 文档（含轻资产档的钩子位置表）。"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'

WIRING_ANCHOR = '''    /// §267：零基建批次的接线'''

WIRING = r'''    /// §268：零基建档收尾的接线（5 条载体 + `black_blood` 的战后回血）。
    #[test]
    fn the_zero_infrastructure_tail_wires_its_carriers() {
        let carrier = [
            ("self_forming_clay", "standard.self_forming_clay"),
            ("bird_faced_urn", "standard.bird_faced_urn"),
            ("runic_pyramid", "standard.runic_pyramid"),
            ("lizard_tail", "standard.lizard_tail"),
            ("unceasing_top", "standard.unceasing_top"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
        }

        // `black_blood` 没有载体：它的效果是战后的 `EndOfCombatHeal(12)`。
        let mut run = ironclad();
        run.push_relic("black_blood").expect("black_blood");
        run.adjust_health(-30);
        let before = run.health();
        assert_eq!(run.end_of_combat(), Ok(12), "Black Blood: heals 12 after a fight");
        assert_eq!(run.health(), before + 12);
    }

'''

DOC = '''
---

## §268 零基建档收尾（6 件）+ 轻资产档的**钩子位置表**

### 268.1 这一批

| 遗物 | 稀有度 | wiki 原话 | 机制 |
|---|---|---|---|
| `self_forming_clay` | Uncommon | "Whenever you lose HP, gain 3 Block next turn." | 掉血立待决标记，`TurnStarted` 兑现 |
| `bird_faced_urn` | Rare | "Whenever you play a Power card, heal 2 HP." | `CardPlayed` + `card.hasTag.power` |
| `runic_pyramid` | Boss | "At the end of your turn, you no longer discard your hand." | 状态的 **`retain_hand` 标签** |
| `lizard_tail` | Rare | "When you would die, heal to 50% of your Max HP instead (works once)." | 状态的 **`DeathPrevention` 行** |
| `black_blood` | Boss | "Replaces Burning Blood. At the end of combat, heal 12 HP." | 既有 `EndOfCombatHeal` |
| `unceasing_top` | Rare | "Whenever you have no cards in hand during your turn, draw a card." | `CardPlayed` + 手牌区计数 |

后两件的两条通道（`host.rs::TAG_RETAIN_HAND` 与 `status_bind::death_prevention`）在内核侧
**早就接好了**，但一直是**没有消费者的死代码**（`retain_hand` 的注释甚至写着"23/23 状态都不带它"）。
这一批是第一次有内容去点亮它们 —— 判据也因此盯着"那条通道真的生效"而不是"状态挂上了"：

* `runic_pyramid`：回合末手牌**不清**（基线：清空重抽 5 张）；
* `lizard_tail`：致命伤后血在 **50%**，且**第二次**致命伤真的死（`Repeating: false` 的语义）。

### 268.2 `dead_branch` 为什么不算零基建

`node.createRandomCardInstance` 的 `Tag` **必填**，而 StS 的"随机一张牌"没有"任意"写法 ⇒
要一个小钩子（`Tag` 允许缺席 = 任意）。归轻资产。

### 268.3 轻资产档：钩子该放哪儿（这批"标记"的产物）

每条都指向**已经存在**的那个位置 —— 轻资产之所以"轻"，就是因为不需要新概念，只需要在
既有的一行旁边加一个判断。

| 遗物 | 钩子位置 |
|---|---|
| `preserved_insect`（精英 -25% 血） | `rd-wasm/src/run.rs::fight_begin` 里已有的 `enemy_health_bonus_percent(fight_kind)` —— A7/A8/A9 走的就是它 |
| `pantograph`（Boss 战回 25）/ `slavers_collar`（Boss·精英 +1 能量）/ `sling_of_courage`（精英 +2 力量） | 同上那条 `fight_kind`；`combat_bonus()` 需要一个 `FightKind` 参数（升阶的 `enemy_health_bonus_percent` 已是先例） |
| `question_card`（多 1 张选牌）/ `busted_crown`（少 2 张）/ `prayer_wheel`（普通怪多 1 张牌奖励）/ `black_star`（精英多 1 件遗物）/ `white_beast_statue`（必出药水）/ `sacred_bark`（药水翻倍） | `rd-run/src/state.rs::roll_reward` + `potion_chance`（`POTION_DROP_START` 就在旁边） |
| `omamori`（挡 2 个诅咒）/ `ceramic_fish`（+9 金币）/ `darkstone_periapt`（+6 上限）/ `molten_egg`·`frozen_egg`·`toxic_egg`（加牌即升级）/ `singing_bowl`（改成 +2 上限） | `rd-run/src/state.rs::push_card` —— **所有**加牌的入口 |
| `bloody_idol`（得金币回 5）/ `ectoplasm`（不能再得金币）/ `maw_bank`（上楼 +12） | `rd-run/src/state.rs::adjust_gold` |
| `membership_card`（-50%）/ `the_courier`（-20% + 补货）/ `smiling_mask`（删牌 50） | `rd-run/src/state.rs::buy_card` / `buy_relic` / `remove_card` + `card_price_band` |
| `meal_ticket`（进商店回 15）/ `ancient_tea_set`（休息后下场 +2 能量）/ `tiny_chest`（每 4 个 ? 变宝箱）/ `juzu_bracelet`（? 不再出普通战）/ `ssserpent_head`（? 房 +50 金） | `rd-run/src/state.rs::enter_node`（`?` 房的落在同一处） |
| `toy_ornithopter`（用药水回 5） | `rd-wasm/src/run.rs::rd_env_use_potion` |
| `sozu`（不能再拿药水） | `RunState::push_potion` |
| `face_of_cleric`（战后上限 +1）/ `old_coin`（拾取 +300 金）/ `lee's waffle`（拾取 +7 上限并回满）/ `war_paint`·`whetstone`（拾取升级 2 张）/ `astrolabe`·`pandoras_box`·`empty_cage`（拾取改造牌组） | 各自是一个新的 `RelicEffect` 变体 + 拾取那一刻（`push_relic` 的副作用区） |
| `dead_branch`（消耗时随机加一张牌） | `node.createRandomCardInstance` 的 `Tag` 允许缺席 = 任意 |
| `sundial`（每洗 3 次 +2 能量）/ `the_abacus`（每次洗完 +6 格挡） | **中资产**：需要一个 `DeckShuffled` 事件（洗牌点在 `rd-core/src/battle.rs`），`CardExhausted`/`CardsDrawn` 是它的样板 |
| `tough_bandages`（弃牌 +3 格挡）/ `tingsha`（弃牌 3 点随机敌人） | **中资产**：需要 `CardDiscarded` 事件（弃牌有两条路：回合末 `hand_turn_end_lifecycle` 与效果请求） |
| `hand_drill`（破格挡加 2 易伤） | **中资产**：`exec::resolve_damage_of_kind` 的 S4 池吸收处需要一个"这一下把格挡打穿"的事实位 |
| `velvet_choker`（每回合最多 6 张）/ `blue_candle`·`medical_kit`（诅咒可出）/ `orange_pellets` / `chemical_x` / `strange_spoon` / `necronomicon` / `toolbox` / `enchiridion` / `warped_tongs` / `gambling_chip` / `matryoshka` / `dollys_mirror` / `orrery` / `cauldron` | **中资产**：出牌校验、手牌升级、待决问句（`PendingChoice`）各自的扩展 |

⚠️ 这张表的用法：做轻资产档时**先来查它在哪一行**，别新开一条路径 ——
同一个语义出现两个入口，就是 §4.20 说的"同一个词表被两处认识就一定漂"。

### 268.4 账

遗物 **74 → 80 件**；`rd-core` 788 / `rd-run` 127 / `rd-wasm` 121；内容 119 状态 / 80 遗物；
四条对拍全过；`ACT1_SLICE` / `SOAK` / `MAP_RENDER` PASS；21/21。
零基建档到此**基本清空**（剩 `dead_branch` 归轻资产、`tough_bandages`/`tingsha`/`sundial`/`the_abacus`/
`hand_drill` 归中资产）。
'''


def main():
    src = io.open(RUN, encoding='utf-8').read()
    assert src.count(WIRING_ANCHOR) == 1
    assert 'the_zero_infrastructure_tail_wires_its_carriers' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(
        src.replace(WIRING_ANCHOR, WIRING + WIRING_ANCHOR))

    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)
    print('wiring test + doc §268 written')


main()

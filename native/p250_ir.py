"""§250 内核（2/3）：`ir.rs` 的四个新节点 + `exec.rs` 的实现。

四个节点，每一个都只服务"原本表达不出来"的语义（不是为了少写一行内容）：

| 节点 | 谁要 | 为什么现有节点不行 |
|---|---|---|
| `node.dealDamageAndIfFatal` | `Ritual Dagger` / `Hand of Greed` | 整棵树**先派发完**请求才落地 ⇒ `sequence[dealDamage, conditional]` 里的条件求值时伤害还没结算（与 §238 `dealDamageAndGainMaxHealthIfFatal` 同一个理由）。区别是这个把"致命之后做什么"交给**一段子节目**，所以一条节点同时解决了涨计数、给金币、以及将来的任何"If Fatal"。 |
| `node.gainGold` | `Hand of Greed` | 战斗里没有"钱"这个资源；`gainResource` 只认 `ResourceId`（energy 那类战斗资源）。金币是**跨层**的账，落在 `CombatState.gold_gained`。 |
| `node.createCardCopy` | `Pride` / `Necronomicurse` | `createCardInstance` 要一个**定义 id 字面量**，而这两张牌要的是"**这一张**的副本"。参考实现里对应的是 `node.createCardCopy`。 |
| `node.offerRandomCards` | `Discovery` | 现有的 `createRandomCardInstance` 是"直接造进某个牌区"，而 `Discovery` 要**先问**（三选一）。问句的 `Offered` 来源只有药水在用 —— 卡牌侧没有入口。 |

`offerRandomCards` 的池子规则写在一处（[`in_offer_pool`]），并**明写**了它是什么：
非 `+` 行、不是无色/诅咒/状态/垃圾、不是 X 费 —— 也就是"你职业牌池里的真牌"。
StS 的池子是"你的职业"，我们的内容里没有职业 tag（`colorless` 是唯一的分色标记），
所以只能从"排除了什么"来定义，并且把这条差别记在 `port-plan.md` §250。
"""
import io

IR = 'D:/Vibe/sts-tui/kernel/rd-core/src/ir.rs'
EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'

# ---------------------------------------------------------------------------
# ir.rs：枚举变体 + wire 名 + 反查表
# ---------------------------------------------------------------------------
IR_PATCHES = [
    ('''    /// §238：**打伤害，如果打死了就抬高自己的最大生命**（`Feed` 的 "If Fatal, raise your Max HP"）。''',
     '''    /// §250：**打伤害，如果打死了就跑一段子节目**（`Ritual Dagger` / `Hand of Greed`）。
    ///
    /// 与 §238 那条（`DealDamageAndGainMaxHealthIfFatal`）是同一个动机的**一般形态**：
    /// 整棵树先派发完请求、伤害才落地，所以"If Fatal"必须是**一个节点**。差别在于这条不把
    /// "致命之后做什么"写死：那段节目是内容给的（涨这份副本的计数器 / 加金币 / 以后的任何事）。
    ///
    /// `Amount` 在打伤害**之前**求值 —— 所以 `Ritual Dagger` 读到的是**这一次**该打的伤害，
    /// 子节目里涨的计数器只影响下一次。
    DealDamageAndIfFatal,
    /// §250：**在战斗里拿到金币**（`Hand of Greed` 的 "If Fatal, gain 20 Gold"）。
    ///
    /// 金币不是战斗资源（`gainResource` 只认 `ResourceId`），它是跨层的账：这里只累加
    /// `CombatState.gold_gained`，运行层在 `fight_end` 读一次。
    GainGold,
    /// §250：**造"这一张"的副本**（`Pride` / `Necronomicurse`）。
    ///
    /// `createCardInstance` 要一个定义 id 的**字面量**；这两张牌要的是"当前正在结算的这份"
    /// 的副本，而定义 id 只有 `cardInstance.resolving` 那类表达式拿得到、`createCardInstance`
    /// 却只收字面串。参考实现里的对应节点就叫 `createCardCopy`。
    ///
    /// 字段：`{ToZone, Count?, Placement?}`（`Count` 缺席 = 1，`Placement` 缺席 = `Bottom`）。
    CreateCardCopy,
    /// §250：**问玩家三选一：从"职业牌池"里随机取 N 张**（`Discovery`）。
    ///
    /// 字段：`{Count, Min?, Max?}`。候选是**卡定义**（`ChoiceSource::Offered`），选完进手牌
    /// 并且**这一份免费**（`ChoiceThen::ToHandFree`）。
    ///
    /// 池子规则见 `exec.rs` 的 `in_offer_pool`：非 `+` 行、不带 `colorless`/`curse`/`status`/
    /// `junk`/`unplayable`、不是 X 费。**这是与 StS 的已知差别**（它是"你的职业牌池"，
    /// 我们的内容没有职业 tag），记在 `port-plan.md` §250。
    OfferRandomCards,
    /// §238：**打伤害，如果打死了就抬高自己的最大生命**（`Feed` 的 "If Fatal, raise your Max HP"）。'''),
    ('''            NodeKind::DealDamageAndGainMaxHealthIfFatal => "node.dealDamageAndGainMaxHealthIfFatal",''',
     '''            NodeKind::DealDamageAndGainMaxHealthIfFatal => "node.dealDamageAndGainMaxHealthIfFatal",
            NodeKind::DealDamageAndIfFatal => "node.dealDamageAndIfFatal",
            NodeKind::GainGold => "node.gainGold",
            NodeKind::CreateCardCopy => "node.createCardCopy",
            NodeKind::OfferRandomCards => "node.offerRandomCards",'''),
    ('''            // §238：抬高最大生命（Feed 的 "If Fatal"）。
            NodeKind::GainMaxHealth,
            NodeKind::DealDamageAndGainMaxHealthIfFatal,''',
     '''            // §238：抬高最大生命（Feed 的 "If Fatal"）。
            NodeKind::GainMaxHealth,
            NodeKind::DealDamageAndGainMaxHealthIfFatal,
            // §250：一般形态的 "If Fatal" + 金币 + 造这一张的副本 + 三选一候选。
            NodeKind::DealDamageAndIfFatal,
            NodeKind::GainGold,
            NodeKind::CreateCardCopy,
            NodeKind::OfferRandomCards,'''),
]

# ---------------------------------------------------------------------------
# exec.rs：预检（哪些节点带节点孩子）+ 分派 + 实现
# ---------------------------------------------------------------------------
EXEC_PATCHES = [
    # 预检：`DealDamageAndIfFatal` 的子节目必须被走查（否则深树会绕过步数预算）。
    ('''        NodeKind::ForEachTarget => {
            // `ForEachTargetEffectNode.Children => [Body]`（`EffectProgramNodes.cs:255`）：''',
     '''        // §250：`DealDamageAndIfFatal` 的 `Program` 是**节点孩子**，与 `Then` 同一条理由：
        // 预检走不进去，一棵超深的树就能绕过步数预算（而且"先打伤害再报错"= 部分执行）。
        if kind == NodeKind::DealDamageAndIfFatal {
            if let Some(body) = node.node_field("Program")? {
                preflight(body, max_steps, walk)?;
            }
        }
        NodeKind::ForEachTarget => {
            // `ForEachTargetEffectNode.Children => [Body]`（`EffectProgramNodes.cs:255`）：'''),
    # 分派
    ('''        NodeKind::DealDamage => deal_damage_node(node, ctx, frame, slot, stats),''',
     '''        NodeKind::DealDamage => deal_damage_node(node, ctx, frame, slot, stats),
        // §250：四条新节点。
        NodeKind::DealDamageAndIfFatal => {
            deal_damage_and_if_fatal_node(node, ctx, frame, slot, depth, stats)
        }
        NodeKind::GainGold => gain_gold_node(node, ctx, frame, slot, stats),
        NodeKind::CreateCardCopy => create_card_copy_node(node, ctx, frame, slot, stats),
        NodeKind::OfferRandomCards => offer_random_cards_node(node, ctx, frame, slot, stats),'''),
]

def main():
    src = io.open(IR, encoding='utf-8').read()
    for old, new in IR_PATCHES:
        assert src.count(old) == 1, ('ir', old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(IR, 'w', encoding='utf-8', newline='\n').write(src)
    print('ir.rs patched (%d edits)' % len(IR_PATCHES))

    src = io.open(EXEC, encoding='utf-8').read()
    for old, new in EXEC_PATCHES:
        assert src.count(old) == 1, ('exec', old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)
    print('exec.rs wiring patched (%d edits)' % len(EXEC_PATCHES))


main()

"""§240 内核：`infernal_blade` —— "把一张随机 Attack 加进手牌，它本回合费用为 0"。

三块都是通用的：
1. `EffectRequest::CreateRandomCard`（按 tag 从**卡表**里随机挑一个定义，造实例）；
2. `node.createRandomCardInstance`（内容入口）；
3. 费用归零 = 每副本价格计数器（§161.4 的 `standard.card_cost_delta`，出牌付款后清）。

两条被排除进随机池的东西，都有原因：
* **`+` 行**（`strike+` 之类）：StS 的随机池是**基础牌**，升级行只是同一张牌的另一个定义；
* **X 费牌**：本内核的每副本价格对 X 费牌**看不见**（§238 起的既有裁决：Liquid Memories /
  Attack Potion 选到 X 费牌时拒绝并保持问句不动），随机造一张 X 费牌加个 -费用 delta 会造出
  "说是 0 费、实际仍是全部能量"的假象。⇒ 不进池。
"""
import io

K = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = K + name
    s = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', name)


# ---------------------------------------------------------------- state.rs：请求变体
patch('state.rs', [
    ('''    CreateCardInstance {
        /// 归属战斗员。
        owner: CombatantId,
        /// 卡定义。
        definition: CardDefinitionId,''',
     '''    /// §240：**造一张随机牌**（`Infernal Blade`："Add a random Attack into your hand."）。
    ///
    /// 与 [`Self::CreateCardInstance`] 的唯一区别是"定义不是内容写死的，而是按 tag 从卡表里抽"。
    /// 抽签用 `random_step`，与其它随机（洗牌、随机目标）同一条账。
    CreateRandomCard {
        /// 归属战斗员。
        owner: CombatantId,
        /// 只从这个 tag 的牌里抽（`attack`）。
        tag: crate::state::TagId,
        /// 张数。
        count: i32,
        /// 落到哪个区。
        to_zone: CardZone,
        /// 造出来的这张**本回合费用为 0**（每副本价格 `-印刷费用`）。`false` = 不动费用。
        cost_zero: bool,
    },
    CreateCardInstance {
        /// 归属战斗员。
        owner: CombatantId,
        /// 卡定义。
        definition: CardDefinitionId,'''),
])

# ---------------------------------------------------------------- ir.rs：新节点
patch('ir.rs', [
    ('''    CreateCardInstance,''',
     '''    CreateCardInstance,
    /// §240：**造一张随机牌**（`Infernal Blade`）。`{Tag, ToZone, Count, CostZero}`。
    ///
    /// 为什么要单独的节点：定义 id 不是内容写的，而是按 tag 从卡表里抽的 —— 那条"抽签"逻辑在
    /// 内核里（`exec::create_random_card`），内容只说"要什么样的牌、落到哪儿"。
    CreateRandomCardInstance,'''),
    ('''        const ALL: [NodeKind; 32] = [''', '''        const ALL: [NodeKind; 33] = ['''),
    ('''            NodeKind::DealDamageAndGainMaxHealthIfFatal,''',
     '''            NodeKind::DealDamageAndGainMaxHealthIfFatal,
            NodeKind::CreateRandomCardInstance,'''),
    ('''            NodeKind::DealDamageAndGainMaxHealthIfFatal => "node.dealDamageAndGainMaxHealthIfFatal",''',
     '''            NodeKind::DealDamageAndGainMaxHealthIfFatal => "node.dealDamageAndGainMaxHealthIfFatal",
            NodeKind::CreateRandomCardInstance => "node.createRandomCardInstance",'''),
])

# ---------------------------------------------------------------- exec.rs：节点 + 请求解析 + 池
patch('exec.rs', [
    ('''        // §238：`gainMaxHealth`（抬高上限）与它的 "If Fatal" 变体。无孩子。''',
     '''        // §240：`createRandomCardInstance`（造一张随机牌）。无孩子。
        | NodeKind::CreateRandomCardInstance
        // §238：`gainMaxHealth`（抬高上限）与它的 "If Fatal" 变体。无孩子。'''),
    ('''        NodeKind::CreateCardInstance => create_card_instance_node(node, ctx, frame, slot, stats),''',
     '''        NodeKind::CreateCardInstance => create_card_instance_node(node, ctx, frame, slot, stats),
        NodeKind::CreateRandomCardInstance => {
            create_random_card_instance_node(node, ctx, frame, slot, stats)
        }'''),
    # request_target 的穷尽 match
    ('''        EffectRequest::DrawCards { .. }
        | EffectRequest::CreateCardInstance { .. }''',
     '''        EffectRequest::DrawCards { .. }
        | EffectRequest::CreateCardInstance { .. }
        | EffectRequest::CreateRandomCard { .. }'''),
    ('''            | EffectRequest::CreateCardInstance { .. }
            | EffectRequest::MoveCardToZone { .. }
            | EffectRequest::EndTurn => None,''',
     '''            | EffectRequest::CreateCardInstance { .. }
            | EffectRequest::CreateRandomCard { .. }
            | EffectRequest::MoveCardToZone { .. }
            | EffectRequest::EndTurn => None,'''),
])
print('done')

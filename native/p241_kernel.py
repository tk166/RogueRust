"""§241 内核：`havoc` —— 强制打出抽牌堆顶那张（不付费、打完进消耗堆）。

三块：
1. `PlayRequest::override_destination`（"打完落在哪儿"可以由调用方改）；
2. `node.playTopCardOfDrawPile` + `EffectRequest::PlayTopCardOfDrawPile`；
3. 强制出牌的实体：移到手牌 → 绝对价格 = 0（复用 §240 那一格）→ 随机敌人当目标 → 打。

⚠️ 为什么"付费为 0"用绝对价格而不是给 `PlayRequest` 再加一个 `free`：§240 那条路径已经证明了
"这一份的价格就是 0"就是 `standard.card_cost_override`，多一个 `free` 布尔就是同一个问题答两次。
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


# ------------------------------------------------------------ play.rs：落区可以被调用方改
patch('play.rs', [
    ('''    pub target: Option<CombatantId>,
}

impl PlayRequest {
    /// 常用形状：给一个人、一张卡、一个目标。
    #[must_use]
    pub const fn new(source: CombatantId, card: CardInstanceId, target: Option<CombatantId>) -> Self {
        Self {
            source,
            card,
            target,
        }
    }
}''',
     '''    pub target: Option<CombatantId>,
    /// §241：**强制落区**（`Havoc`："Play the top card of your draw pile and **Exhaust** it."）。
    ///
    /// `None` = 听内容的 `PlayedCardDestinationZone`。这是"谁在出牌"的事，不是内容的事 ——
    /// 同一张 `Strike` 平时进弃牌堆，被 `Havoc` 打出去就进消耗堆，而它的 CARD 行不能有两个值。
    pub override_destination: Option<CardZone>,
}

impl PlayRequest {
    /// 常用形状：给一个人、一张卡、一个目标。
    #[must_use]
    pub const fn new(source: CombatantId, card: CardInstanceId, target: Option<CombatantId>) -> Self {
        Self {
            source,
            card,
            target,
            override_destination: None,
        }
    }

    /// §241：同上，但强制落区（`Havoc`）。
    #[must_use]
    pub const fn to_zone(
        source: CombatantId,
        card: CardInstanceId,
        target: Option<CombatantId>,
        zone: CardZone,
    ) -> Self {
        Self {
            source,
            card,
            target,
            override_destination: Some(zone),
        }
    }
}'''),
    ('''    let destination = played_card_destination(&card)?;''',
     '''    let destination = match req.override_destination {
        Some(zone) => zone,
        None => played_card_destination(&card)?,
    };'''),
])

# ------------------------------------------------------------ state.rs：请求变体
patch('state.rs', [
    ('''    /// §240：**造一张随机牌**''',
     '''    /// §241：**强制打出抽牌堆顶那张，然后把它消耗掉**（`Havoc`）。
    ///
    /// 为什么是一条请求而不是若干节点：出牌本身是 `play.rs` 的事（受理校验五条 + 费用 + 节目），
    /// 而"从抽牌堆顶打一张"只是**选哪张**与**打完落哪儿**的差别 —— 中间那条路必须走同一个
    /// `play_card`，否则"打出去的牌"会有两套语义（触发器的 `CardPlayed`、`cards_played_this_turn`、
    /// 每副本价格的消费……全都要写第二遍）。
    PlayTopCardOfDrawPile {
        /// 谁在打。
        owner: CombatantId,
    },
    /// §240：**造一张随机牌**'''),
])

# ------------------------------------------------------------ ir.rs：新节点
patch('ir.rs', [
    ('''    CreateRandomCardInstance,''',
     '''    CreateRandomCardInstance,
    /// §241：**把抽牌堆顶那张打出去，然后消耗**（`Havoc`）。零字段。
    PlayTopCardOfDrawPile,'''),
    ('''        const ALL: [NodeKind; 33] = [''', '''        const ALL: [NodeKind; 34] = ['''),
    ('''            NodeKind::CreateRandomCardInstance,''',
     '''            NodeKind::CreateRandomCardInstance,
            NodeKind::PlayTopCardOfDrawPile,'''),
    ('''            NodeKind::CreateRandomCardInstance => "node.createRandomCardInstance",''',
     '''            NodeKind::CreateRandomCardInstance => "node.createRandomCardInstance",
            NodeKind::PlayTopCardOfDrawPile => "node.playTopCardOfDrawPile",'''),
])
print('done')

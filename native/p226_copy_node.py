"""§226 (part 4): `node.chooseCards` —— ir.rs 的词表 + exec.rs 的实体/预检/分发。"""
import io

IR = 'kernel/rd-core/src/ir.rs'
EXEC = 'kernel/rd-core/src/exec.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


rewrite(IR, [
    ('''    /// `node.selectCards` —— **挑卡并搬卡**（§195.4，本内核自己的节点）。''',
     '''    /// `node.chooseCards` —— **问玩家要哪几张牌，然后复制它们**（§226，本内核自己的节点）。
    ///
    /// StS 的 `Dual Wield`（"选一张 Attack 或 Power 牌，造一份/两份副本"）此前**没有载体**：
    /// `selectCards` 是内核自己按稀有度/顺序挑（不问人，而且它**搬**牌），而 `PendingChoice`
    /// 只有药水那三条路（运行层发起，`then` 是消耗/弃抽/拿进手牌）。缺的是
    /// **"玩家的选择" × "复制"** 这个组合。
    ChooseCards,
    /// `node.selectCards` —— **挑卡并搬卡**（§195.4，本内核自己的节点）。'''),
    ('''            NodeKind::SelectCards => "node.selectCards",''',
     '''            NodeKind::ChooseCards => "node.chooseCards",
            NodeKind::SelectCards => "node.selectCards",'''),
    ('''        const ALL: [NodeKind; 23] = [''', '''        const ALL: [NodeKind; 24] = ['''),
    ('''            NodeKind::SelectCards,
            NodeKind::Repeat,
        ];''',
     '''            NodeKind::SelectCards,
            // §226：问玩家要哪几张牌，然后复制（Dual Wield）。
            NodeKind::ChooseCards,
            NodeKind::Repeat,
        ];'''),
])

rewrite(EXEC, [
    # 预检：没有孩子
    ('''        // §195.4：`selectCards`（挑卡 + 搬卡）。没有孩子，预检只登记它。
        | NodeKind::SelectCards''',
     '''        // §195.4：`selectCards`（挑卡 + 搬卡）。没有孩子，预检只登记它。
        | NodeKind::SelectCards
        // §226：`chooseCards`（问玩家 + 复制）。同上，只有字段没有孩子。
        | NodeKind::ChooseCards'''),

    # 常量
    ('''/// §195.4：`node.selectCards` 一次最多搬几张（与 `Count` 的上限是同一个数）。''',
     '''/// §226：`node.chooseCards` 一次最多造几份副本（`Copies` 的上限）。
///
/// 取 4 而不是 99：StS 里复制牌的牌最多要 3 份（`Nightmare`），4 留一格；而"一次造几十份"
/// 若真被写进内容，它撞的是手牌容量（`MAX_CARDS_PER_ZONE`）—— 两条界线都在，宁可在**内容**
/// 这一层就说出"这个数不像话"，而不是让它到运行期变成一次容量拒绝。
pub const MAX_COPIES_PER_CHOICE: usize = 4;

/// §195.4：`node.selectCards` 一次最多搬几张（与 `Count` 的上限是同一个数）。'''),
])

# 实体：插在 select_cards_node 的实体之后（`shuffle_candidates` 之前）
src = io.open(EXEC, encoding='utf-8').read()
anchor = '''/// 一次抽签 = 一次完整置换，然后推进 `random_step`（与洗牌/掷骰同一条账）。
fn shuffle_candidates('''
assert src.count(anchor) == 1
node_impl = '''/// §226：`node.chooseCards` 的实体 —— **问玩家要哪几张牌，然后复制**。
///
/// 字段：`{OwnerSelector, FromZone, Min, Max, Copies, RequireAnyTag?}`。
///
/// 与 `selectCards` 的两条分工（别合并这两个节点）：
/// * 那个**内核挑**（`Order`: `First`/`Random`/`HighestRarity`）并且**搬**牌；
/// * 这个**问玩家**（`PendingChoice`，`then = Copy`）并且**造**牌 —— 原件留在原处。
///
/// `RequireAnyTag` 是**一个 tag 的集合**（"Attack 或 Power"）：过滤要读卡定义的 tag 表，而它
/// 只在内容镜像里，所以在这里算好、把**收窄后的实例清单**塞进问句（`PendingChoice::candidates`）
/// —— 状态层没有 `Content`，这样它也不必去读内容就能守住"哪些选项合法"。
///
/// 三条"不问"的情形都是**空操作**，不是错误（一个答不出来的问句会把这局钉死）：
/// 解不出 owner、没有候选、候选比 `Min` 还少。
///
/// ⚠️ `begin_choice` 的失败借 [`ExecError::Modifier`] 桶（冻结的 `ExecError` 没有"选牌"变体，
/// 理由同 `forEachCardInZone` 的 `MaxIterations`）。可达的只有"已经有一个待决问句"
/// （`AlreadyPending`）—— 那是**嵌套提问**，本内核明确不支持。
fn choose_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let from_name = node.str_field("FromZone")?.ok_or(IrError::Missing("FromZone"))?;
    let from_zone = zone_from_wire_name(from_name).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    // 今天只有手牌来源的问句（Dual Wield）。别的牌区需要一个"从那儿选牌"的 UI 语义，
    // 而那件事没被任何内容要求过 —— 响亮拒绝，不许悄悄当成手牌。
    let source = match from_zone {
        CardZone::Hand => crate::state::ChoiceSource::Hand,
        CardZone::DiscardPile => crate::state::ChoiceSource::DiscardPile,
        _ => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    let min = node.int_field("Min")?.ok_or(IrError::Missing("Min"))?;
    let max = node.int_field("Max")?.ok_or(IrError::Missing("Max"))?;
    let copies = node.int_field("Copies")?.ok_or(IrError::Missing("Copies"))?;
    if !(0..=MAX_SELECTED_CARDS as i32).contains(&min)
        || !(1..=MAX_SELECTED_CARDS as i32).contains(&max)
        || min > max
    {
        return Err(ExecError::Ir(IrError::Missing("Min")));
    }
    if !(1..=MAX_COPIES_PER_CHOICE as i32).contains(&copies) {
        return Err(ExecError::Ir(IrError::Missing("Copies")));
    }

    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };

    // `RequireAnyTag` 缺席 ⇒ 不过滤。空数组也当"不过滤"（与 `selectCards` 的 `RequireTag`
    // 对空串的处理同一条理由：一个空集合当过滤条件，等于"一张都挑不到"）。
    let mut tag_cells = [0u16; MAX_SELECTED_CARDS];
    let tag_count = node.str_list_field("RequireAnyTag", &mut tag_cells)?;

    let mut candidates = crate::state::Bounded::new();
    for card in ctx.state.zone_cards(&owner, from_zone) {
        if tag_count > 0 {
            // 没有内容 ⇒ 不知道这张牌有什么 tag。**不许**当成"没有 tag"（那会让
            // "只复制攻击牌"把技能牌也列出来）。响亮失败，与 `forEachCardInZone` 的
            // `TagFilter` 同一条线。
            let Some(content) = ctx.content else {
                return Err(ExecError::Ir(IrError::Missing("content")));
            };
            let mut matched = false;
            for cell in tag_cells.iter().take(tag_count) {
                let Some(tag) = content.string(*cell) else {
                    continue;
                };
                if content
                    .card_has_tag(card.definition_id.as_str(), tag)
                    .unwrap_or(false)
                {
                    matched = true;
                    break;
                }
            }
            if !matched {
                continue;
            }
        }
        if candidates
            .push(card.id, crate::state::Container::ChoiceOptions)
            .is_err()
        {
            return Err(ExecError::Capacity(crate::state::CapacityError::Full(
                crate::state::Container::ChoiceOptions,
            )));
        }
    }
    let available = candidates.len();
    // 候选不够 `Min` 张 ⇒ 这个问句永远答不出来。不问（空操作）。
    if available < min as usize {
        return resume_later(ctx.state, frame, slot);
    }
    let question = crate::state::PendingChoice {
        chooser: owner,
        source,
        min: u8::try_from(min).map_err(|_| ExecError::Ir(IrError::Missing("Min")))?,
        // 上限也要夹到实际候选数：问句承诺"最多 N 张"，而 N 比能选的还多时，
        // 页面的计数和内核的判据就会各说一套。
        max: u8::try_from(max as usize).map_err(|_| ExecError::Ir(IrError::Missing("Max")))?
            .min(u8::try_from(available).unwrap_or(u8::MAX)),
        then: crate::state::ChoiceThen::Copy,
        offered: crate::state::Bounded::new(),
        copies: u8::try_from(copies).map_err(|_| ExecError::Ir(IrError::Missing("Copies")))?,
        candidates,
    };
    if ctx.state.begin_choice(question).is_err() {
        return Err(ExecError::Modifier);
    }
    resume_later(ctx.state, frame, slot)
}

/// 一次抽签 = 一次完整置换，然后推进 `random_step`（与洗牌/掷骰同一条账）。
fn shuffle_candidates('''
src = src.replace(anchor, node_impl)
io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)
print('ok ir+exec')

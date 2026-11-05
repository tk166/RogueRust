"""§227 (part 2): `node.chooseCards` 学会三种 `Then`。"""
import io

EXEC = 'kernel/rd-core/src/exec.rs'

src = io.open(EXEC, encoding='utf-8').read()


def sub(old, new):
    global src
    assert src.count(old) == 1, (src.count(old), old[:70])
    src = src.replace(old, new)


# ── 字段解析：Then / Copies / ToZone ──────────────────────────────────────────
sub('''    let min = node.int_field("Min")?.ok_or(IrError::Missing("Min"))?;
    let max = node.int_field("Max")?.ok_or(IrError::Missing("Max"))?;
    let copies = node.int_field("Copies")?.ok_or(IrError::Missing("Copies"))?;''',
    '''    let min = node.int_field("Min")?.ok_or(IrError::Missing("Min"))?;
    let max = node.int_field("Max")?.ok_or(IrError::Missing("Max"))?;
    // §227：`Then` 决定"选完做什么"，所以它先被解析，再决定**哪些字段是必须的** ——
    // "Copies 只在 Copy 上有意义"这条规则写在解析里，比写在注释里靠得住。
    let then_name = node.str_field("Then")?.ok_or(IrError::Missing("Then"))?;
    let then = match then_name {
        "Copy" => {
            let copies = node.int_field("Copies")?.ok_or(IrError::Missing("Copies"))?;
            if !(1..=MAX_COPIES_PER_CHOICE as i32).contains(&copies) {
                return Err(ExecError::Ir(IrError::Missing("Copies")));
            }
            // `ToZone` 缺席 ⇒ 手牌（Dual Wield 的语义）。副本进手牌是**最常见**的那一种，
            // 但 Nightmare 要的是"先放进一边、下一回合再拿进手牌"，所以这个字段必须存在。
            let into = match node.str_field("ToZone")? {
                Some(name) => zone_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?,
                None => CardZone::Hand,
            };
            crate::state::ChoiceThen::Copy {
                copies: u8::try_from(copies).map_err(|_| ExecError::Ir(IrError::Missing("Copies")))?,
                into,
            }
        }
        // §227：Armaments —— 选一张原地升级。候选会被下面收窄到"有 `+` 行"的牌。
        "Upgrade" => crate::state::ChoiceThen::Upgrade,
        // §227：Warcry —— 选一张放到抽牌堆顶。
        "ToDrawPileTop" => crate::state::ChoiceThen::ToDrawPileTop,
        _ => return Err(ExecError::Ir(IrError::UnknownKind)),
    };''')

sub('''    if !(1..=MAX_COPIES_PER_CHOICE as i32).contains(&copies) {
        return Err(ExecError::Ir(IrError::Missing("Copies")));
    }

''', '''''')

# ── 候选过滤：加"能不能升级"这一条 ────────────────────────────────────────────
sub('''    let mut candidates = crate::state::Bounded::new();
    for card in ctx.state.zone_cards(&owner, from_zone) {
        if tag_count > 0 {''',
    '''    let mut candidates = crate::state::Bounded::new();
    for card in ctx.state.zone_cards(&owner, from_zone) {
        // §227：`Upgrade` 的候选收窄是**自动**的，不是内容声明的：一张牌能不能升级，
        // 问的是"内容里有没有它的 `+` 行"（`upgrade_cards_node` 用的同一条规则、同一个
        // `state::upgraded_id` 拼法）。已经带 `+` 的牌与没有 `+` 行的牌都不进候选 ——
        // 于是页面根本不会给玩家一个"点了什么都不发生"的选项。
        if matches!(then, crate::state::ChoiceThen::Upgrade) {
            let Some(content) = ctx.content else {
                return Err(ExecError::Ir(IrError::Missing("content")));
            };
            let definition = card.definition_id.as_str();
            let Some(upgraded) = crate::state::upgraded_id(definition) else {
                continue;
            };
            if content
                .lookup_in(upgraded.as_str(), crate::content::EK_CARD)
                .is_none()
            {
                continue;
            }
        }
        if tag_count > 0 {''')

# ── 问句构造 ─────────────────────────────────────────────────────────────────
sub('''        then: crate::state::ChoiceThen::Copy,
        offered: crate::state::Bounded::new(),
        copies: u8::try_from(copies).map_err(|_| ExecError::Ir(IrError::Missing("Copies")))?,
        candidates,
    };''',
    '''        then,
        offered: crate::state::Bounded::new(),
        candidates,
    };''')

io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)
print('ok exec')

"""§226 (part 1): 区分"自己"与"整手牌"（Second Wind / Fiend Fire）。

做法：**不动 `forEachCardInZone` 的快照**（那会改每一步哈希里的牌区计数，直接打破与 C# oracle
的逐字节契约 —— `archive_the_evidence` 就靠"循环能看见打出的那张"），而是把
"这一趟的牌是不是正在结算的那一张"作为**迭代事实位**写进 `event_flags`（§225 已经在那里填
卡牌 tag 位），内容用 `event.bool: card.isResolving` 自己决定跳过。只读，不改任何状态。
"""
import io
import json

EXPR = 'kernel/rd-core/src/expr.rs'
EXEC = 'kernel/rd-core/src/exec.rs'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'


def patch_exec():
    src = io.open(EXEC, encoding='utf-8').read()

    old = '''pub const CARD_HAS_TAG_ATTACK: u8 = 1 << 0;
pub const CARD_HAS_TAG_SKILL: u8 = 1 << 1;
pub const CARD_HAS_TAG_POWER: u8 = 1 << 2;
pub const CARD_HAS_TAG_STATUS: u8 = 1 << 3;'''
    new = '''pub const CARD_HAS_TAG_ATTACK: u8 = 1 << 0;
pub const CARD_HAS_TAG_SKILL: u8 = 1 << 1;
pub const CARD_HAS_TAG_POWER: u8 = 1 << 2;
pub const CARD_HAS_TAG_STATUS: u8 = 1 << 3;

/// §226：这一趟迭代的牌**是不是正在结算的那一张**（`forEachCardInZone` 填，`event.bool` 读）。
///
/// 为什么需要它：StS 里"打出的牌已经不在手牌"是**结构性**的（它当时在 in-play 区），所以
/// `Second Wind` / `Fiend Fire` 这类"消耗手牌里的牌"天然**不含自己**。参考引擎把打出的牌留在
/// 手里直到终态回调（落区在 `onTerminal`），于是循环快照里会看到它 —— 那不是内容的错，是
/// 参考与本模型的共同形状。
///
/// 两条被否掉的做法，都留在这里当**反面证据**：
/// * 出牌时就把牌搬离手牌 ⇒ 改变每一步哈希里的牌区计数，`CARD_DIFF` / `FIGHT_DIFF` 当场红。
/// * `forEachCardInZone` 的快照里跳过它 ⇒ `archive_the_evidence`（参考契约里的那张 scenario 卡，
///   节目就是 `sequence[forEachCardInZone, gainBlock]`，靠"循环能看见自己"把**自己**搬进消耗堆）
///   立刻红，而且那是**参考**的行为，不是我们的 bug（§225 被挡回的那条修法）。
///
/// ⇒ 内核只提供**事实**，跳不跳过由内容说。没有正在结算的牌时这一位恒 0（状态/遗物/敌人招式
/// 的节目里"没有哪张牌是自己"）。
pub const CARD_IS_RESOLVING: u8 = 1 << 5;'''
    assert src.count(old) == 1
    src = src.replace(old, new)

    old = '''            ctx.iteration_card = Some(card.id);
            ctx.event_flags = match ctx.content {
                Some(content) => content.card_tag_bits(card.definition_id.as_str()),
                // 没有内容 ⇒ 不知道这张牌有什么 tag。**不许**当成"没有 tag"：那会让
                // "非攻击牌"把攻击牌也算进去。响亮失败。
                None => return Err(ExecError::Ir(IrError::Missing("content"))),
            };'''
    new = '''            ctx.iteration_card = Some(card.id);
            ctx.event_flags = match ctx.content {
                Some(content) => content.card_tag_bits(card.definition_id.as_str()),
                // 没有内容 ⇒ 不知道这张牌有什么 tag。**不许**当成"没有 tag"：那会让
                // "非攻击牌"把攻击牌也算进去。响亮失败。
                None => return Err(ExecError::Ir(IrError::Missing("content"))),
            };
            // §226：这一趟的牌**是不是正在结算的那一张**。用槽位比（同一份身份），不用定义 id
            // 比 —— 手牌里可能有两张同名牌，而只有其中一张在结算。
            if ctx.resolving_card == Some(card_slot) {
                ctx.event_flags |= CARD_IS_RESOLVING;
            }'''
    assert src.count(old) == 1
    src = src.replace(old, new)
    io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)


def patch_expr():
    src = io.open(EXPR, encoding='utf-8').read()
    old = '''                "card.hasTag.status" => crate::exec::CARD_HAS_TAG_STATUS,'''
    new = '''                "card.hasTag.status" => crate::exec::CARD_HAS_TAG_STATUS,
                // §226: "this iterated card is the one being resolved right now". The kernel
                // answers the *fact*; whether to skip it is the content's call (see
                // `exec::CARD_IS_RESOLVING` for the two rejected alternatives).
                "card.isResolving" => crate::exec::CARD_IS_RESOLVING,'''
    assert src.count(old) == 1
    src = src.replace(old, new)
    io.open(EXPR, 'w', encoding='utf-8', newline='\n').write(src)


def not_resolving():
    return {
        "kind": "not",
        "value": {"Condition": {"kind": "event.bool", "value": {"FieldKey": "card.isResolving"}}},
    }


def patch_content():
    raw = io.open(CONTENT, encoding='utf-8').read()
    data = json.loads(raw)
    touched = []

    for card in data['Cards']:
        cid = card['Id']
        root = card['Program']['Root']
        if cid.startswith('second_wind') and root['kind'] == 'node.forEachCardInZone':
            cond = root['value']['Body']['value']['Condition']
            assert cond['kind'] == 'not', cond['kind']
            assert cond['value']['Condition']['value']['FieldKey'] == 'card.hasTag.attack'
            root['value']['Body']['value']['Condition'] = {
                "kind": "and",
                "value": {"Left": not_resolving(), "Right": cond},
            }
            touched.append(cid)
        elif cid.startswith('fiend_fire') and root['kind'] == 'node.forEachCardInZone':
            body = root['value']['Body']
            assert body['kind'] == 'node.sequence', body['kind']
            root['value']['Body'] = {
                "kind": "node.conditional",
                "value": {"Condition": not_resolving(), "Then": body, "Else": None},
            }
            touched.append(cid)

    assert sorted(touched) == ['fiend_fire', 'fiend_fire+', 'second_wind', 'second_wind+'], touched
    out = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    assert out != raw
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(out)
    print('touched:', touched)


patch_exec()
patch_expr()
patch_content()
print('ok')

"""§225 A: `card.hasTag.*` also reads the **iterated** card (the carrier Second Wind needs).

Today `event.bool: card.hasTag.attack` reads `ctx.event_flags`, which only a *trigger* dispatch fills
(`CardPlayed`). Inside `forEachCardInZone` there is no event, so the fact reads "false" -- and
"exhaust all **non-Attack** cards" (Second Wind) needs exactly that fact about the card being iterated.

Reference behaviour (`EffectProgramExpressions.cs:... CardTagExpression`): a card-tag expression reads
the **card in the evaluation context**; the trigger event is just one way that card gets bound. So:

* if `ctx.iteration_card` is bound -> read that instance's definition tags from the content image;
* otherwise -> the event flag (the old path, unchanged);
* content missing while a card is bound -> **loud** (`IrError::Missing("content")`), because "no content"
  would silently answer "false" for every tag -- and Second Wind would exhaust Attack cards too.
"""
import io

EXPR = 'kernel/rd-core/src/expr.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


one(EXPR, """        "event.bool" => {
            let name = node
                .str_field("FieldKey")?
                .ok_or(IrError::Missing("FieldKey"))?;
            let bit = match name {
                "card.hasTag.attack" => crate::exec::CARD_HAS_TAG_ATTACK,
                "card.hasTag.skill" => crate::exec::CARD_HAS_TAG_SKILL,
                "card.hasTag.power" => crate::exec::CARD_HAS_TAG_POWER,
                "card.hasTag.status" => crate::exec::CARD_HAS_TAG_STATUS,
                // §208: the receiving side's fact (see `DAMAGE_IS_ATTACK`'s doc).
                "damage.isAttack" => crate::exec::DAMAGE_IS_ATTACK,
                _ => return Err(ExprError::UnsupportedKind),
            };
            Ok(ctx.event_flags & bit != 0)
        }""",
    """        "event.bool" => {
            let name = node
                .str_field("FieldKey")?
                .ok_or(IrError::Missing("FieldKey"))?;
            // §225：**迭代卡优先**。`forEachCardInZone` 的循环体里没有"事件"，只有"这一趟的卡" ——
            // 而"消耗所有**非攻击**牌"（Second Wind）问的正是这张卡的 tag。参考里的 card-tag
            // 表达式读的是**求值上下文里的那张卡**，触发事件只是它的一种绑定方式。
            if let Some(tag) = name.strip_prefix("card.hasTag.") {
                if let Some(card_id) = ctx.iteration_card {
                    let content = ctx.content.ok_or(IrError::Missing("content"))?;
                    let definition = ctx
                        .state
                        .card(crate::state::CardSlot::from_index(card_id.index()))
                        .map(|card| card.definition_id)
                        .ok_or(IrError::Missing("card instance"))?;
                    return content
                        .card_has_tag(definition.as_str(), tag)
                        .ok_or(ExprError::UnsupportedKind);
                }
            }
            let bit = match name {
                "card.hasTag.attack" => crate::exec::CARD_HAS_TAG_ATTACK,
                "card.hasTag.skill" => crate::exec::CARD_HAS_TAG_SKILL,
                "card.hasTag.power" => crate::exec::CARD_HAS_TAG_POWER,
                "card.hasTag.status" => crate::exec::CARD_HAS_TAG_STATUS,
                // §208: the receiving side's fact (see `DAMAGE_IS_ATTACK`'s doc).
                "damage.isAttack" => crate::exec::DAMAGE_IS_ATTACK,
                _ => return Err(ExprError::UnsupportedKind),
            };
            Ok(ctx.event_flags & bit != 0)
        }""",
    'iteration card tags')

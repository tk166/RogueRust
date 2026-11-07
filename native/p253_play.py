"""§253 内核（2/2）：`play.rs::play_card_from_program` —— 出牌通道的**唯一**实现。

参考（`Cards/PlayCardEffects.cs:26-96`）的判据顺序，以及我们**多出来**的那一格：

| # | 条件 | 参考的行为 | 我们 |
|---|---|---|---|
| 1 | 玩家不在 / 已倒 | no-op | 同（`Ok(false)`） |
| 2 | 那一份不在主人的牌区里 | no-op | 同 |
| 3 | **不在手牌** | no-op | 同（`plan_play` 也要求手牌） |
| 4 | 付不起费用 | no-op | 同（`play_card` 返回 `Refused(CannotAfford)` ⇒ 我们转成 no-op） |
| 5 | 卡带 `unplayable` | **no-op**（注释："An unplayable card (a curse) is never played"） | **`IgnoreUnplayable` 时放行**；否则同 |
| 6 | `stun` / 法令 / `PlayCondition` | 仍然拒绝 | 同 —— `Wish` 只推翻"这张牌天生不可打出"，不推翻"这一回合不许出牌" |

第 5 行是**我们**的扩展，理由在 wiki 的 `Become Almighty` 正文里（"It can only be obtained and
**played** through Watcher's Wish"）。默认 `false` ⇒ 与参考逐字相同。

## 为什么第 5 格必须在这里、而不是"绕过整个受理校验"

`unplayable` 是**卡自己的属性**（`CARD.tags` 里那个 tag），与 `stun`/法令/`PlayCondition`
（都是"现在不许出牌"）不是一类。既然要的只是前者的例外，就只掀前者那一道门 ——
`plan_play` 的其余四道校验全部照旧跑。造一个"跳过全部校验"的开关会让 `stun` 也能被绕过，
那是把"Wish 能打诅咒"解释成"Wish 能在被击晕时出牌"。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'

CODE = r'''
/// §253：**由效果节目打出一张牌**（`node.playCard`；`Wish` 的三个选项就是这么被打出来的）。
///
/// 返回 `Ok(true)` = 真的打出去了，`Ok(false)` = 参考那种"安静什么都不做"（六种情形见
/// `port-plan.md` §253 的表）。只有**内容坏了**（那一份实例在内容里找不到定义）才 `Err`。
///
/// 参数 `ignore_unplayable` 是本内核多出来的一格：StS 的 `Wish` 会打出 `unplayable` 的牌，
/// 而参考的 `playCard` 对它是 no-op（`PlayCardEffects.cs:54-58`）。默认调用方传 `false`
/// ⇒ 与参考逐字相同。它**只**掀 `unplayable` 这一道门：`stun` / 法令 / `PlayCondition` 全照旧。
pub(crate) fn play_card_from_program(
    state: &mut CombatState,
    content: &crate::content::Content<'_>,
    player: &CombatantId,
    card: &crate::state::CardInstanceId,
    target: Option<CombatantId>,
    ignore_unplayable: bool,
) -> Result<bool, ExecError> {
    // 1. 玩家在不在、倒没倒。
    let alive = state
        .combatant(player)
        .is_some_and(|combatant| combatant.health_current > 0);
    if !alive {
        return Ok(false);
    }
    // 2. 那一份在不在这个人的牌区里。
    let Some((zone, slot)) = state.find_card(player, card) else {
        return Ok(false);
    };
    // 3. 只在手牌里打。参考在同一条路上用 `cardInstance.Zone != Hand` 判，`plan_play` 也会判；
    //    这里先判一次是为了"不在手牌 ⇒ 什么都不发生"，而不是"报一个拒绝"。
    if zone != CardZone::Hand {
        return Ok(false);
    }
    let Some(definition) = state.card(slot).map(|card| card.definition_id) else {
        return Ok(false);
    };
    // 5. `unplayable` 那道门（默认照参考关着）。
    if !ignore_unplayable
        && content.card_has_tag(definition.as_str(), "unplayable") == Some(true)
    {
        return Ok(false);
    }
    // 4. 付不起 / 6. 被 `stun`/法令/`PlayCondition` 拒 ⇒ 参考都是 no-op，不是错误。
    let request = PlayRequest::new(*player, *card, target);
    match play_card(state, Some(content), &request) {
        Ok(_) => Ok(true),
        Err(PlayError::Refused(_)) => Ok(false),
        // `SourceUnavailable` / `CardNotInHand` 这些在第 1~3 步已经排除了；走到了说明状态自相矛盾，
        // **不许当成 no-op** —— 那会让一个真 bug 安静地变成"这张牌没打出去"。
        Err(error) => Err(ExecError::Ir(crate::ir::IrError::Missing(match error {
            PlayError::SourceUnavailable => "source",
            PlayError::CardNotInHand => "card",
            PlayError::Effect(_) => "program",
            PlayError::Refused(_) => "refusal",
        }))),
    }
}
'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert 'fn play_card_from_program' not in src, 'already patched'
    anchor = 'pub fn play_card(\n    state: &mut CombatState,'
    assert src.count(anchor) == 1
    src = src.replace(anchor, CODE.lstrip('\n') + '\n' + anchor)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src)
    print('play.rs: play_card_from_program added')


main()

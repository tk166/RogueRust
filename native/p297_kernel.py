"""§297 A4：`velvet_choker`（每回合最多 6 张）+ `runic_dome`（看不见意图）。

## `velvet_choker`：照 `Entangled` 加一条校验器

`Refusal::DecreeMaxCardsPerTurn` 已经存在，但它属于**法令**（`CombatRules`），而本内容的
`CombatRules` 全是 `ABSENT16` 且 `refuse_if_any_decree` 一票否决 —— 借它表达"遗物限制"
会让"法令"与"遗物"两件事共用一个名字。所以新增：

* `Refusal::CardLimitReached { cap, played }`（与 `DecreeMaxCardsPerTurn` 同形，但**不是**法令）；
* `Validator::CardLimit`（Priority 200，id `standard.card_limit_validator` —— 与
  `one_attack_per_turn` 同一个优先级档，按 id 字节序排在它**前面**）；
* 规则：来源身上有 `standard.velvet_choker` 且 `cards_played_this_turn >= 6` ⇒ 拒。

⚠️ **上限（6）是 wiki 的常量，住在内核**（与 `THE_BOOT` / `CHEMICAL_X` 同族）：
`standard.card_limit_delta` 这类"内容给数"的机制**不存在**，而 `velvet_choker` 是唯一用户。
哪天有第二件同类遗物，再把它变成内容给的数（那时才是"第二份合同"）。

## `runic_dome`：把意图变成 unknown

"敌人意图"是**观测**里的东西（`refresh_intents` 每次重算）。要"看不见"，就该在**观测**
里就没有 —— 页面因此不可能画出来（不是"画了再藏"，那种做法会漏：`?debug`、测试、
截图都能看见）。条件用**战斗里那条状态**（`standard.runic_dome`）而不是运行层遗物：
这本来就是一场战斗内的规则，而状态就是它的载体。
"""
import io

PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
BATTLE = 'D:/Vibe/sts-tui/kernel/rd-core/src/battle.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── ① `Refusal::CardLimitReached`
    patch(PLAY, '''    /// 同名法令的**第二条**规则：不许拿一张带 `tag` 的牌接续"上一张也带这个 tag"的牌''',
                '''    /// §297：`velvet_choker` —— "You cannot play more than 6 cards per turn"。
    ///
    /// 与 [`Self::DecreeMaxCardsPerTurn`] 同形但**不是法令**：那一条来自 `CombatRules`
    /// （本内容 23/23 全是 `ABSENT16`，而 `refuse_if_any_decree` 一票否决），借它表达
    /// "遗物限制"会让"法令"与"遗物"两件事共用一个名字 —— 而页面要把原因显示给玩家看。
    CardLimitReached {
        /// 上限（`VELVET_CHOKER_CAP`）。
        cap: i32,
        /// 本回合已经出了几张。
        played: i32,
    },
    /// 同名法令的**第二条**规则：不许拿一张带 `tag` 的牌接续"上一张也带这个 tag"的牌''')

    # ── ② 常量 + 校验器
    patch(PLAY, '''/// §196：Red Slaver 的 `Entangled` —— "本回合不能打出 Attack"。''',
                '''/// §297：`velvet_choker` 的每回合出牌上限（wiki: "You cannot play more than 6 cards per turn"）。
///
/// 数字住在内核（与 `exec::THE_BOOT` / `exec::CHEMICAL_X` 同族）：它是**这件遗物的定义**，
/// 不是"能力值"，而且今天只有它一个用户。有第二件同类遗物时再改成内容给的数。
pub const VELVET_CHOKER_CAP: i32 = 6;
/// `velvet_choker` 在身上时挂的那条状态（`rd-run` 的开战加成挂它，规则在这里）。
pub const VELVET_CHOKER_STATUS: &str = "standard.velvet_choker";
/// §196：Red Slaver 的 `Entangled` —— "本回合不能打出 Attack"。''')

    patch(PLAY, '''    PlayCondition,
    OneAttackPerTurn,
    Unplayable,
}''', '''    PlayCondition,
    OneAttackPerTurn,
    CardLimit,
    Unplayable,
}''')

    patch(PLAY, '''            Validator::OneAttackPerTurn | Validator::Unplayable => 200,''',
                '''            Validator::OneAttackPerTurn | Validator::CardLimit | Validator::Unplayable => 200,''')
    patch(PLAY, '''            Validator::OneAttackPerTurn => "standard.one_attack_per_turn_validator",''',
                '''            Validator::OneAttackPerTurn => "standard.one_attack_per_turn_validator",
            // §297：`card_limit` 按 id 字节序排在 `one_attack_per_turn` **前**（同是 200）。
            Validator::CardLimit => "standard.card_limit_validator",''')
    patch(PLAY, '''const VALIDATOR_ORDER: [Validator; 6] = [
    Validator::Stun,
    Validator::Decree,
    Validator::Entangled,
    Validator::PlayCondition,
    Validator::OneAttackPerTurn,
    Validator::Unplayable,
];''', '''const VALIDATOR_ORDER: [Validator; 7] = [
    Validator::Stun,
    Validator::Decree,
    Validator::Entangled,
    Validator::PlayCondition,
    // §297：`standard.card_limit_validator` < `standard.one_attack_per_turn_validator`
    // （同优先级 200，按 id 字节序）—— 顺序是语义，所以它排在这里而不是末尾。
    Validator::CardLimit,
    Validator::OneAttackPerTurn,
    Validator::Unplayable,
];''')
    patch(PLAY, '''            Validator::OneAttackPerTurn => one_attack_per_turn_validator(state, card),''',
                '''            Validator::CardLimit => card_limit_validator(state, card),
            Validator::OneAttackPerTurn => one_attack_per_turn_validator(state, card),''')

    patch(PLAY, '''fn one_attack_per_turn_validator(''',
                '''/// §297 `card_limit`（Priority 200，`standard.card_limit_validator`）—— `velvet_choker`。
///
/// "You cannot play more than 6 cards per turn"：**任意**牌都受限（不分攻击/技能），
/// 所以这条校验器不看 `card.is_attack`。计数用 `CombatState::cards_played_this_turn`
/// （内核自己的账，`CardPlayed` 触发器与"每次掉血减 1 费"读的是同一个数）。
///
/// 没有那条状态 ⇒ 放行（绝大多数战斗走这一支，所以它必须**最便宜**的早退）。
fn card_limit_validator(state: &CombatState, card: &CardOnTable<'_>) -> Result<(), PlayError> {
    let source = source_of(state, &card.source)?;
    if !has_status(source, VELVET_CHOKER_STATUS) {
        return Ok(());
    }
    // `>=` 而不是 `>`：这一张就是第 7 张（`played` 是**已经**打出的张数）。
    if state.cards_played_this_turn >= VELVET_CHOKER_CAP {
        return Err(PlayError::Refused(Refusal::CardLimitReached {
            cap: VELVET_CHOKER_CAP,
            played: state.cards_played_this_turn,
        }));
    }
    Ok(())
}

fn one_attack_per_turn_validator(''')

    # ── ③ 拒绝码（ABI 上的数 + 名字）
    patch(BATTLE, '''            crate::play::Refusal::OneAttackPerTurn => 10,''',
                  '''            crate::play::Refusal::OneAttackPerTurn => 10,
            // §297：`velvet_choker` 的每回合出牌上限。
            crate::play::Refusal::CardLimitReached { .. } => 19,''')
    patch(BATTLE, '''        10 => "Refused(OneAttackPerTurn)",''',
                  '''        10 => "Refused(OneAttackPerTurn)",
        19 => "Refused(CardLimitReached)",''')

    # ── ④ `runic_dome`：观测里就没有意图
    patch(WASM, '''            // §2.4 fork 3: the reference asks the selector about dead enemies too (`EnemyIntentRules`''',
                 '''            // §297：`runic_dome` —— "You can no longer see enemy intents"。
            // 在**观测**里就把它变成 unknown（不是"画了再藏"：后者会漏 —— `?debug`、测试、
            // 截图都能看见，而玩家看不见的规则就等于不存在）。
            // 判据用**战斗里那条状态**（`rd-run` 开战挂它），不用运行层遗物：这本来就是一场
            // 战斗内的规则，而状态是它的载体（与 `chemical_x` 同一个理由）。
            if crate::carries_status(&self.state, &id, RUNIC_DOME_STATUS) {
                intents.push(Intent::unknown("runic_dome：看不穿敌人的意图"));
                continue;
            }
            // §2.4 fork 3: the reference asks the selector about dead enemies too (`EnemyIntentRules`''')
    print('kernel + wasm')


main()

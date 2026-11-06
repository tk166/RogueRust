"""§250 内核（3/3）：`play.rs` 的出牌上限 + `host.rs` 的 `CardPlayedInHand` 生命周期。

## 1. `CardPlayedInHand`（`pain`："While in hand, lose 1 HP when other cards are played."）

生命周期键本来就是**卡**的触发器（`TurnEndInHand` / `Drawn` / `Exhausted`），但缺一个
"我在手上、别人打出牌时"的键。加它比"发明一个状态"干净：状态是**按持有者**的，
而这张诅咒的语义就是"**这一张牌在手上**这件事本身"。

派发点放在 `run_card_played_triggers` 的**末尾**（状态触发器之后）：pain 的节目是"掉 1 血"，
它不该插在别人的触发器中闁 —— 顺序由 `CardPlayed` 的既有顺序决定，这里只加"同一批里的最后一段"。

## 2. 出牌上限（`normality`："You cannot play more than 3 cards this turn."）

`Refusal::DecreeMaxCardsPerTurn { cap, played }` **早就存在**（`CombatDecrees.cs:150-158`），
它的文档写着"本内容无法令 ⇒ 恒不触发"。`normality` 就是那条法令，所以这里给它一个**来源**：
`.stun` 的先例（`play.rs:431` 的 `STUN_STATUS` —— 内核认识一个**固定的状态 id**）说明这是
本内核既有的做法，不是新发明。

上限读的是**战斗员计数器** `card_play_cap`（`node.setCombatantCounter`，`Relative = false`
= 覆盖写），所以内容侧可以：`Drawn` 时设 3、`TurnEndInHand` 时清 0（0 = 没有上限）。
计数器而不是状态，是因为它**幂等**：每回合抽到再设一次不会翻倍（状态层数是累加的）。
"""
import io

PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'

PLAY_PATCHES = [
    # 常量
    ('''const STUN_STATUS: &str = "standard.stun";''',
     '''const STUN_STATUS: &str = "standard.stun";

/// §250：**每回合出牌上限**的计数器名（`normality`："cannot play more than 3 cards this turn"）。
///
/// 为什么是一个**战斗员计数器**而不是状态：上限要**幂等**。`normality` 每回合都会被抽到一次
/// （它不可打出、回合末进弃牌堆），若用状态的层数表达上限，抽到第二次就变成 6 层 —— 那会让
/// "最多 3 张"在第 2 回合悄悄放宽。计数器用 `Relative = false` 覆盖写，重复设置无害。
///
/// 0 / 缺席 = 没有上限（不是"一张也不许出"）：`0` 是"清掉这条法令"的唯一写法，
/// 内容在 `TurnEndInHand` 里用它 —— 与"上限为 0"撞在一起是不可能的（想禁止出牌的内容
/// 会写 1，而 1 的语义是明确的）。
const CARD_PLAY_CAP_COUNTER: &str = "card_play_cap";'''),
    # 法令校验里读计数器
    ('''fn refuse_if_any_decree(state: &CombatState, card: &CardOnTable<'_>) -> Result<(), PlayError> {
    let Ok(combatant) = source_of(state, &card.source) else {
        return Ok(());
    };''',
     '''fn refuse_if_any_decree(state: &CombatState, card: &CardOnTable<'_>) -> Result<(), PlayError> {
    let Ok(combatant) = source_of(state, &card.source) else {
        return Ok(());
    };
    // §250：`normality` 那条法令 —— 上限来自内容写的计数器（见 `CARD_PLAY_CAP_COUNTER`）。
    //
    // 与参考的对照：`CombatDecrees.cs:150-158` 是 `played >= cap` ⇒ 拒绝，消息里带两个数；
    // 这里逐字相同，只是 `cap` 的**来源**是内容而不是 C# 里注册的一张表。
    if let Some(cap) = combatant_counter(combatant, CARD_PLAY_CAP_COUNTER) {
        let played = state.cards_played_this_turn;
        if cap > 0 && played >= cap {
            return Err(PlayError::Refused(Refusal::DecreeMaxCardsPerTurn {
                cap,
                played,
            }));
        }
    }'''),
]

HOST_PATCHES = [
    # 键名表
    ('''const TURN_END_IN_HAND: &str = "TurnEndInHand";''',
     '''const TURN_END_IN_HAND: &str = "TurnEndInHand";

/// §250：**这张牌在手上、别人打出一张牌**时跑的生命周期节目（`pain`）。
///
/// 与 `TurnEndInHand` 同一条路（同一张 `LifecyclePrograms` 字典、同一个 `execute_program`），
/// 只是派发点在 `CardPlayed` 而不是回合末。
const CARD_PLAYED_IN_HAND: &str = "CardPlayedInHand";'''),
    # 派发体
    ('''    fn hand_turn_end_lifecycle(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError> {''',
     '''    /// §250：跑**手上每一张**的 `CardPlayedInHand` 节目（`pain`）。
    ///
    /// 快照手牌**槽位**再跑（节目会掉血，也会搬牌；`CardSlot` 是牌池下标，所以不漂）——
    /// 与 [`Self::try_hand_turn_end_lifecycle`] 同一个手法，只是键不同、`sel` 绑定不同：
    /// 这里 `sel.source` / `sel.eventTarget` 都是**出牌的人**（`pain` 让"我"掉血）。
    fn try_hand_card_played_lifecycle(
        &mut self,
        state: &mut CombatState,
        owner: &CombatantId,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        if state.result != CombatResult::Ongoing {
            return Ok(());
        }
        let mut hand: [Option<CardSlot>; MAX_CARDS_PER_ZONE] = [None; MAX_CARDS_PER_ZONE];
        let count = {
            let Some(zones) = state.card_zones(owner) else {
                return Ok(());
            };
            let mut count = 0usize;
            for index in 0..zones.count(CardZone::Hand) {
                let Some(slot) = zones.slot_at(CardZone::Hand, index) else {
                    continue;
                };
                let Some(cell) = hand.get_mut(count) else {
                    return Err(self.record(HostError::Capacity(CapacityError::Full(
                        crate::state::Container::CardsInZone(CardZone::Hand),
                    ))));
                };
                *cell = Some(slot);
                count += 1;
            }
            count
        };
        let mut programs: [Option<LifecycleProgram<'_>>; MAX_CARDS_PER_ZONE] =
            [None; MAX_CARDS_PER_ZONE];
        let mut runs = 0usize;
        for index in 0..count {
            let Some(Some(slot)) = hand.get(index).copied() else {
                continue;
            };
            let Some(instance) = state.card(slot) else {
                continue;
            };
            let definition = instance.definition_id;
            let decoded = card_lifecycle_program_by_key(
                self.content,
                definition.as_str(),
                CARD_PLAYED_IN_HAND,
            )
            .map_err(|error| self.record(HostError::Exec(error)))?;
            if let Some(program) = decoded {
                if let Some(cell) = programs.get_mut(index) {
                    *cell = Some(program);
                }
                runs += 1;
            }
        }
        if runs == 0 {
            // 真实内容的日常路径：一格状态都不动、不发号、不建链。
            return Ok(());
        }
        let chain = state
            .adopt_root_chain()
            .map_err(|e| self.record(HostError::Capacity(e)))?;
        let saved = state.current_chain();
        state.set_current_chain(chain);
        let mut failure: Option<HostError> = None;
        for index in 0..count {
            if state.result != CombatResult::Ongoing {
                break;
            }
            let Some(Some(program)) = programs.get(index).copied() else {
                continue;
            };
            let outcome = execute_program(
                state,
                self.content,
                program.root,
                Some(*owner),
                Some(*owner),
                program.max_steps,
            );
            if let Err(e) = outcome {
                failure = Some(self.record(HostError::Exec(e)));
                break;
            }
        }
        state.set_current_chain(saved);
        state.release_chain(chain);
        match failure {
            Some(e) => Err(e),
            None => Ok(()),
        }
    }

    fn hand_turn_end_lifecycle(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError> {'''),
    # 在 CardPlayed 那一段末尾接上
    ('''        let flags = card_definition_of(state, card)
            .map_or(0, |definition| card_tag_flags(self.content, definition));''',
     '''        let flags = card_definition_of(state, card)
            .map_or(0, |definition| card_tag_flags(self.content, definition));
        // §250：出牌之后跑"手牌里的 `CardPlayedInHand`"（`pain`）。
        //
        // 放在**这里**（状态触发器之前）而不是末尾：`pain` 掉的血是"这次出牌的代价"，
        // 而状态触发器（如 `juggernaut`）看的是"这次出牌**造成**了什么"。参考的实现里
        // 这张诅咒也是登记在出牌事件的最前面（`CardPlayed` 的注册序）。
        // ⚠️ 递归：这段节目自己也可能出牌（`playTopCardOfDrawPile`），而那条路径会重新进
        // 这里 —— 引擎的出牌深度上限（`MAX_PROGRAM_DEPTH` 之外的 `play` 预算）守着它。
        self.try_hand_card_played_lifecycle(state, owner)?;'''),
]

# `lifecycle_name_matches` 是**穷尽**表：加一个键时它必须能回答"这个键是不是我要的"。
HOST_KEY_PATCH = (
    '''        TURN_END_IN_HAND | TURN_END_IN_HAND_ORDINAL => Some(None),''',
    '''        TURN_END_IN_HAND | TURN_END_IN_HAND_ORDINAL => Some(None),
        // §250：`pain` 的键。没有"序数拼法"这个歧义（镜像里从未出现过该键，唯一来源是我们
        // 自己的内容），所以只认这一个名字。
        CARD_PLAYED_IN_HAND => Some(None),''')


HELPER = (
    '''fn refuse_if_any_decree(state: &CombatState, card: &CardOnTable<'_>) -> Result<(), PlayError> {''',
    '''/// §250：读一个**战斗员计数器**的当前值（`node.setCombatantCounter` 写的那一格）。
///
/// 缺席 => `None`（"这个计数器根本不存在"，与"值是 0"分开：0 是内容显式清掉法令的写法）。
fn combatant_counter(combatant: &Combatant, id: &str) -> Option<i32> {
    combatant
        .counters()
        .iter()
        .find(|counter| counter.key.as_str() == id)
        .map(|counter| counter.value)
}

fn refuse_if_any_decree(state: &CombatState, card: &CardOnTable<'_>) -> Result<(), PlayError> {''')


def main():
    src = io.open(PLAY, encoding='utf-8').read()
    for old, new in list(PLAY_PATCHES) + [HELPER]:
        assert src.count(old) == 1, ('play', old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(PLAY, 'w', encoding='utf-8', newline='\n').write(src)
    print('play.rs patched (%d edits)' % len(PLAY_PATCHES))

    src = io.open(HOST, encoding='utf-8').read()
    for old, new in list(HOST_PATCHES) + [HOST_KEY_PATCH]:
        assert src.count(old) == 1, ('host', old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(HOST, 'w', encoding='utf-8', newline='\n').write(src)
    print('host.rs patched (%d edits)' % (len(HOST_PATCHES) + 1))


main()

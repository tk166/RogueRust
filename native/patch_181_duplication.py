"""§181: Duplication Potion -- "This turn, your next card is played twice."

The mechanism is a **status** on the player (`standard.duplication`, `UsesCharges: true`) plus one
hook in the card program's terminal callback: when the program **completes** and the player still
carries a charge, spend one and run the program again.

Why the terminal callback and not "play the card twice":
* StS pays for the card **once** and counts it as **one** card played -- only the effects happen
  twice. Re-entering `play_card` would charge energy twice and bump `cards_played_this_turn` twice.
* The second run must start **after** the first finishes, so the hook (which is synchronous, see
  `state.rs`'s note on why it is not a `Continuation`) is the one place that has both the finished
  program and the chain context the first run used.

The charge is spent **before** the second `begin`, so the second run's own terminal callback finds
nothing to duplicate -- otherwise "played twice" would mean "played forever".
"""
import io

STATE = "kernel/rd-core/src/state.rs"
PLAY = "kernel/rd-core/src/play.rs"

# ---------------------------------------------------------------- state.rs: the hook carries what a re-run needs

STATE_OLD = """    /// 出牌节目的落区回调（`Cards/CardPlay.cs:245-263`）。
    CardPlay {
        /// 谁打的。
        player: CombatantId,
        /// 哪一张实例。
        card: CardInstanceId,
        /// 落哪个区（`PlayedCardDestination`，`:298-302`）。
        destination: CardZone,
    },"""

STATE_NEW = """    /// 出牌节目的落区回调（`Cards/CardPlay.cs:245-263`）。
    CardPlay {
        /// 谁打的。
        player: CombatantId,
        /// 哪一张实例。
        card: CardInstanceId,
        /// 落哪个区（`PlayedCardDestination`，`:298-302`）。
        destination: CardZone,
        /// §181: 这个节目在镜像里的根（`term` 号）。**只有"再打一遍"的路径读它** ——
        /// Duplication Potion 要在第一遍**跑完之后**把同一个节目再跑一遍，而那时
        /// `plan` 已经不在了，帧上只剩这些数据。
        program: u16,
        /// 出牌时瞄的目标（`PlayRequest.target`）。第二遍必须瞄同一个，
        /// 否则"打两次"会变成"打两个不同的目标"。
        target: Option<CombatantId>,
        /// X 费的 `X`（第一遍付了多少遍，第二遍就一样多）。
        x_cost: i32,
        /// 步数预算（第二遍用同一个，否则同一个节目会有两种预算）。
        max_steps: u32,
    },"""

# ---------------------------------------------------------------- play.rs: pass it, then use it

PLAY_CALL_OLD = """    let hook = ProgramTerminalHook::CardPlay {
        player: plan.source,
        card,
        destination: plan.destination,
    };"""

PLAY_CALL_NEW = """    let hook = ProgramTerminalHook::CardPlay {
        player: plan.source,
        card,
        destination: plan.destination,
        program: root.id().get(),
        target: plan.target,
        x_cost: plan.x_cost,
        max_steps: plan.max_steps,
    };"""

PLAY_TERMINAL_OLD = """        ProgramTerminalHook::CardPlay {
            player,
            card,
            destination,
        } => card_program_terminal(state, player, card, destination, outcome),"""

PLAY_TERMINAL_NEW = """        ProgramTerminalHook::CardPlay {
            player,
            card,
            destination,
            program,
            target,
            x_cost,
            max_steps,
        } => card_program_terminal(
            state,
            CardPlayTerminalContext {
                player,
                card,
                destination,
                program,
                target,
                x_cost,
                max_steps,
            },
            outcome,
        ),"""

SIG_OLD = """fn card_program_terminal(
    state: &mut CombatState,
    player: CombatantId,
    card: CardInstanceId,
    destination: CardZone,
    outcome: ProgramFrameState,
) -> Result<(), ExecError> {"""

SIG_NEW = """/// 一次出牌节目终态时需要的全部数据（§181 从 `ProgramTerminalHook` 里原样传下来）。
struct CardPlayTerminalContext {
    player: CombatantId,
    card: CardInstanceId,
    destination: CardZone,
    /// 节目在镜像里的根（`term` 号）。
    program: u16,
    target: Option<CombatantId>,
    x_cost: i32,
    max_steps: u32,
}

/// `standard.duplication` —— Duplication Potion 留下的那一层（§181）。
///
/// `UsesCharges: true` 的内容侧写法让"下一张牌"是**消耗一层**而不是"这一回合都算"：
/// 层数就是"还能打几次两遍"。
const DUPLICATION_STATUS: &str = "standard.duplication";

fn card_program_terminal(
    state: &mut CombatState,
    ctx: CardPlayTerminalContext,
    outcome: ProgramFrameState,
) -> Result<(), ExecError> {
    let CardPlayTerminalContext {
        player,
        card,
        destination,
        program,
        target,
        x_cost,
        max_steps,
    } = ctx;"""

# The duplicate tail: placed right before the function's closing brace. We anchor on the function's
# own tail (the Faulted arm) to stay inside it.
TAIL_OLD = """            ProgramFrameState::Faulted => {"""

TAIL_NEW = """            ProgramFrameState::Faulted => {
                // A faulted program is **not** re-run: it did not complete, so "played twice" has
                // nothing to double (and re-running a fault would double the error, not the effect)."""


def patch(path, edits):
    text = io.open(path, encoding="utf-8").read()
    for old, new in edits:
        assert text.count(old) == 1, (path, text.count(old), old[:70])
        text = text.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("patched", path)


patch(STATE, [(STATE_OLD, STATE_NEW)])
patch(PLAY, [
    (PLAY_CALL_OLD, PLAY_CALL_NEW),
    (PLAY_TERMINAL_OLD, PLAY_TERMINAL_NEW),
    (SIG_OLD, SIG_NEW),
    (TAIL_OLD, TAIL_NEW),
])

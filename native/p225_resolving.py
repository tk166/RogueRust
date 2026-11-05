"""§225 D: the card being resolved is **not part of your hand** while its program runs.

Found by `Second Wind`: it exhausts every non-Attack card in hand, and the snapshot included **the
Second Wind itself** (its zone move happens in `onTerminal`, after the program). Result: 10 Block
instead of 5, and the card "exhausted itself twice".

Why not simply move the card out of the hand when the program starts: that changes the zone counts in
every per-step hash, i.e. it breaks the byte-for-byte contract with the C# oracle that `CARD_DIFF` /
`FIGHT_DIFF` pin. So the card **stays** where it is, and the *program* is told which card is resolving:

* `ExecContext::resolving_card: Option<CardSlot>` — set by `play.rs` when it starts the card program;
* `ProgramExecutionFrame::resolving_card` — persisted, so continuations see it too (same reason
  `iteration_card` is on the frame);
* `forEachCardInZone` skips that slot in its **snapshot** (the snapshot is what the body sees).
"""
import io

EXEC = 'kernel/rd-core/src/exec.rs'
STATE = 'kernel/rd-core/src/state.rs'
PLAY = 'kernel/rd-core/src/play.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


# ── ① ExecContext 字段 ─────────────────────────────────────────────────────────────────────────
one(EXEC, """    pub iteration_card: Option<CardInstanceId>,""",
    """    pub iteration_card: Option<CardInstanceId>,
    /// §225：**正在结算的那张牌**（出牌时由 `play.rs` 填）。
    ///
    /// 为什么需要：`Second Wind` 的循环快照里会看到**它自己** —— 打出的牌要到终态回调才离开手牌
    /// （参考的落区也是在 `onTerminal`），而循环在结算期间跑。参考语义里"打出的牌已经不在手牌"，
    /// 所以这里让程序**知道**是哪一张，`forEachCardInZone` 的快照把它跳过。
    ///
    /// ⚠️ 不改成"打出时就把牌搬走"：那会改变每一步哈希里的牌区计数，直接打破与 C# oracle 的
    /// 逐字节契约（`CARD_DIFF` / `FIGHT_DIFF`）。牌留在原处，只是程序看得见它。
    pub resolving_card: Option<CardSlot>,""", 'context field')

# 构造器默认 None
one(EXEC, """            iteration_card: None,""",
    """            iteration_card: None,
            resolving_card: None,""", 'context default')

# ── ② 帧字段 ──────────────────────────────────────────────────────────────────────────────────
one(STATE, """    pub iteration_card: Option<CardInstanceId>,
    /// §225：`event_flags` 的帧内副本。""",
    """    pub iteration_card: Option<CardInstanceId>,
    /// §225：正在结算的那张牌（`play.rs` 出牌时填）—— 续延重建上下文时要拿得回来。
    pub resolving_card: Option<CardSlot>,
    /// §225：`event_flags` 的帧内副本。""", 'frame field')

one(STATE, """        iteration_card: None,
        event_flags: 0,""",
    """        iteration_card: None,
        resolving_card: None,
        event_flags: 0,""", 'frame EMPTY')

# ── ③ frame_context 读它 ──────────────────────────────────────────────────────────────────────
one(EXEC, """    ctx.iteration_card = record.iteration_card;
    ctx.event_flags = record.event_flags;""",
    """    ctx.iteration_card = record.iteration_card;
    ctx.resolving_card = record.resolving_card;
    ctx.event_flags = record.event_flags;""", 'frame_context')

# ── ④ 建帧时带上 ──────────────────────────────────────────────────────────────────────────────
one(EXEC, """        iteration_card: ctx.iteration_card,
        event_flags: ctx.event_flags,""",
    """        iteration_card: ctx.iteration_card,
        resolving_card: ctx.resolving_card,
        event_flags: ctx.event_flags,""", 'frame alloc')

# ── ⑤ forEachCardInZone 的快照跳过它 ─────────────────────────────────────────────────────────
one(EXEC, """            let definition_id = card.definition_id;
            let mut matches = true;""",
    """            // §225：**正在结算的那张牌不算"在手里"** —— 否则 `Second Wind` 会把自己也算进
            // "消耗所有非攻击牌"，多给一份格挡（实测 10 而不是 5）。
            if ctx.resolving_card == Some(card_slot) {
                continue;
            }
            let definition_id = card.definition_id;
            let mut matches = true;""", 'snapshot skip')

# ── ⑥ play.rs 出牌时填它 ─────────────────────────────────────────────────────────────────────
one(PLAY, """            let mut ctx = ExecContext::new(
                state,
                Some(plan.source),
                plan.target,
                None,
                plan.max_steps,
            )
            .with_content(plan.content)
            .with_x_cost(plan.x_cost);""",
    """            let mut ctx = ExecContext::new(
                state,
                Some(plan.source),
                plan.target,
                None,
                plan.max_steps,
            )
            .with_content(plan.content)
            .with_x_cost(plan.x_cost);
            // §225：这一次结算的是**哪一张牌**（`forEachCardInZone` 的快照要跳过它）。
            ctx.resolving_card = plan.slot;""", 'play fills it')

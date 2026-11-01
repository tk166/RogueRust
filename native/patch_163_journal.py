"""§163.2: the journal, the replay, and the `fight_end` tail extracted so both can share it.

Shape:
  * `RunSession.journal: Vec<Rec>` — one record per **mutating** run call: kind, two ints, an optional
    string (the upgraded card id), and the run hash *after* the call;
  * `finish()` fills the hash, so no export has to remember to;
  * `rd_run_script_len/into` dump it as **one line** (`;`-separated), `rd_run_replay_from` re-executes
    it from the recorded seed and compares the hash step by step, returning the **first** divergent
    step (that index is the whole point: "they differ" is useless, "step 17" is a bug report).

A fight is not replayed: `CombatState` has no deserializer, and a fight is decided by the player's
card play, not by the run layer. So the journal records the fight's **outcome** (hero HP + tier) and
the replay applies it — `apply_fight_outcome` is the shared tail, extracted from `rd_run_fight_end`.
That is stated here rather than discovered later.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"


def main():
    text = io.open(PATH, encoding="utf-8").read()

    def sub(old, new, count=1):
        nonlocal text
        assert text.count(old) == count, (text.count(old), old[:70])
        text = text.replace(old, new)

    # ---- 1. the session gains a journal and the replay's bookkeeping ------------------------
    sub(
        """    /// Is a fight **in progress** right now? (§161.10)""",
        """    /// §163: the recorded run calls, oldest first. **Not** part of game state (it is the host's
    /// action log), so `run_hash` does not include it and the archive does not carry it.
    journal: Vec<Rec>,
    /// Replaying right now? Then calls must not be recorded again (they would double the log).
    replaying: bool,
    /// How many steps the last replay verified (evidence for the gate).
    replay_checked: usize,
    /// Where the last replay diverged (`0` = it did not).
    replay_diverged: i32,
    /// Is a fight **in progress** right now? (§161.10)""",
    )
    text = text.replace(
        """        boss_fight: false,
        in_fight: false,""",
        """        boss_fight: false,
        in_fight: false,
        journal: Vec::new(),
        replaying: false,
        replay_checked: 0,
        replay_diverged: 0,""",
    )

    # ---- 2. the record type + the journal helpers ------------------------------------------
    anchor = "static mut RUN: Option<RunSession> = None;"
    assert text.count(anchor) == 1
    sub(
        anchor,
        """/// 一次**会改运行层状态**的调用（§163）。
#[derive(Clone, Debug)]
struct Rec {
    kind: u8,
    a: i32,
    b: i32,
    /// 只有 `smith` / `grant_potion` 用得上（升级后的牌 id / 药水 id）。
    text: String,
    /// 调用**之后**的 `run_hash` 前 8 字节。回放逐步比这一格。
    hash: u64,
}

/// 记录的种类。数值是**脚本的文本**（写在 `kind` 那一列），所以改它就改了存档/脚本的兼容性。
const K_STEP: u8 = 1;
const K_BEGIN: u8 = 2;
const K_REST: u8 = 3;
const K_SMITH: u8 = 4;
const K_CHEST: u8 = 5;
const K_LEAVE: u8 = 6;
const K_BUY_CARD: u8 = 7;
const K_BUY_RELIC: u8 = 8;
const K_REMOVE: u8 = 9;
const K_TAKE_CARD: u8 = 10;
const K_SKIP: u8 = 11;
const K_TAKE_POTION: u8 = 12;
const K_TAKE_RELIC: u8 = 13;
const K_CHOOSE: u8 = 14;
const K_EVENT_CARD: u8 = 15;
const K_CHOOSE_START: u8 = 16;
const K_BLESSING_CARD: u8 = 17;
const K_DROP_POTION: u8 = 18;
const K_FIGHT_END: u8 = 19;

const fn kind_name(kind: u8) -> &'static str {
    match kind {
        K_STEP => "step",
        K_BEGIN => "begin",
        K_REST => "rest",
        K_SMITH => "smith",
        K_CHEST => "chest",
        K_LEAVE => "leave",
        K_BUY_CARD => "buy_card",
        K_BUY_RELIC => "buy_relic",
        K_REMOVE => "remove",
        K_TAKE_CARD => "take_card",
        K_SKIP => "skip",
        K_TAKE_POTION => "take_potion",
        K_TAKE_RELIC => "take_relic",
        K_CHOOSE => "choose",
        K_EVENT_CARD => "event_card",
        K_CHOOSE_START => "choose_start",
        K_BLESSING_CARD => "blessing_card",
        K_DROP_POTION => "drop_potion",
        K_FIGHT_END => "fight_end",
        _ => "?",
    }
}

fn kind_from_name(name: &str) -> Option<u8> {
    Some(match name {
        "step" => K_STEP,
        "begin" => K_BEGIN,
        "rest" => K_REST,
        "smith" => K_SMITH,
        "chest" => K_CHEST,
        "leave" => K_LEAVE,
        "buy_card" => K_BUY_CARD,
        "buy_relic" => K_BUY_RELIC,
        "remove" => K_REMOVE,
        "take_card" => K_TAKE_CARD,
        "skip" => K_SKIP,
        "take_potion" => K_TAKE_POTION,
        "take_relic" => K_TAKE_RELIC,
        "choose" => K_CHOOSE,
        "event_card" => K_EVENT_CARD,
        "choose_start" => K_CHOOSE_START,
        "blessing_card" => K_BLESSING_CARD,
        "drop_potion" => K_DROP_POTION,
        "fight_end" => K_FIGHT_END,
        _ => return None,
    })
}

/// `run_hash` 的前 8 字节 —— 逐步比对用。整条 64 字符的十六进制只留在错误信息里。
fn hash_prefix(state: &rd_run::state::RunState) -> Option<u64> {
    let digest = rd_run::hash::run_hash(state)?;
    Some(u64::from_be_bytes([
        digest[0], digest[1], digest[2], digest[3], digest[4], digest[5], digest[6], digest[7],
    ]))
}

impl RunSession {
    /// 记下这次调用（回放时不记）。`finish` 会在调用之后把哈希填进最后一条。
    fn log(&mut self, kind: u8, a: i32, b: i32, text: &str) {
        if self.replaying {
            return;
        }
        self.journal.push(Rec {
            kind,
            a,
            b,
            text: text.to_string(),
            hash: 0,
        });
    }

    /// 把**当前**状态的哈希写进最后一条记录（`finish` 调它）。
    fn stamp(&mut self) {
        if self.replaying {
            return;
        }
        let Some(last) = self.journal.last_mut() else {
            return;
        };
        last.hash = hash_prefix(&self.state).unwrap_or(0);
    }
}

static mut RUN: Option<RunSession> = None;""",
    )

    # ---- 3. `finish` stamps the hash ------------------------------------------------------
    sub(
        """fn finish(session: &mut RunSession, result: Result<i32, RunError>) -> i32 {
    match result {""",
        """fn finish(session: &mut RunSession, result: Result<i32, RunError>) -> i32 {
    // §163: one line here is what keeps every export from having to remember to stamp the hash.
    session.stamp();
    match result {""",
    )

    # ---- 4. `fight_end`'s tail becomes a shared function ----------------------------------
    old_tail = """    // The fight is over: the run's health becomes the hero's.
    let delta = hero_hp - session.state.health();
    session.state.adjust_health(delta);
    // `inv:§5`: the tier follows what was fought, and it moves gold and rarity together.
    // `inv:§4.3`: a boss pays 95-105 and its reward is always rare.
    let fight_kind = if boss_fight {"""
    assert text.count(old_tail) == 1
    text = text.replace(
        old_tail,
        """    // §163: the tail is `apply_fight_outcome` so the replay can apply a **recorded** fight
    // without a combat session (a fight is not replayed; its outcome is).
    session.log(K_FIGHT_END, hero_hp, i32::from(boss_fight) << 1 | i32::from(elite_fight), "");
    let verdict = apply_fight_outcome(session, hero_hp, result, elite_fight, boss_fight);
    session.stamp();
    return verdict;
}

/// The run-layer effect of a finished fight (extracted from `rd_run_fight_end`, §163).
fn apply_fight_outcome(
    session: &mut RunSession,
    hero_hp: i32,
    result: i32,
    elite_fight: bool,
    boss_fight: bool,
) -> i32 {
    // The fight is over: the run's health becomes the hero's.
    let delta = hero_hp - session.state.health();
    session.state.adjust_health(delta);
    // `inv:§5`: the tier follows what was fought, and it moves gold and rarity together.
    // `inv:§4.3`: a boss pays 95-105 and its reward is always rare.
    let fight_kind = if boss_fight {""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("journal + replay scaffolding + fight_end tail extracted")


if __name__ == "__main__":
    main()

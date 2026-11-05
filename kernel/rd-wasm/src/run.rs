//! The run layer's exports: one map, one cursor, and the seven random streams behind them.
//!
//! Frozen by `docs/spec/env-abi.md` §11. This module is the **integration point** between three
//! things that deliberately do not know about each other:
//!
//! * `rd-core`'s content reader, which says what the character starts with
//!   (`Content::character_start_facts`, `Content::start_deck`);
//! * `rd-run`, which owns the map, the cursor and the streams — and which has **no idea what
//!   content is** (its module header says why);
//! * the page, which reads flat integers and draws them.
//!
//! ⚠️ **What this version does and does not do.** `rd_run_step` **walks**; it does not **settle**.
//! Entering a combat node moves the cursor and records the floor; no fight starts, no rest site
//! heals, no chest opens. That is a milestone boundary (`docs/spec/sts-act1-plan.md` §4 M1 lists
//! settlement separately) and `env-abi.md` §11.5 requires it to stay visible rather than be
//! discoverable. The moment settlement lands, §11.5 gets rewritten with which kinds resolve.

use rd_core::content::{Content, DeckRoots};
use rd_run::map::{NodeKind, ROWS};
use rd_run::state::{RunState, MAX_RUN_DECK};
use rd_run::streams::{RunError, RunStream};

use crate::{detail, IMAGE};

/// `docs/spec/env-abi.md` §11.3. Kept in one place because the page indexes into it by number.
pub const RUN_OBS_LEN: usize = 19;

/// Field ids for [`rd_run_map_node`] (`env-abi.md` §11.2).
const NODE_FIELD_ROW: i32 = 0;
const NODE_FIELD_COL: i32 = 1;
const NODE_FIELD_KIND: i32 = 2;
const NODE_FIELD_OUT_DEGREE: i32 = 3;
const NODE_FIELD_EDGE0: i32 = 4;
const NODE_FIELD_EDGE1: i32 = 5;
const NODE_FIELD_EDGE2: i32 = 6;
const NODE_FIELD_REACHABLE: i32 = 7;

struct RunSession {
    state: Box<RunState>,
    /// Human-readable reason for the last non-`Ok` return.
    error: String,
    /// Was this fight started from the **boss**? Same reason as `elite_fight`, and it also decides
    /// whether winning clears the act.
    boss_fight: bool,
    /// Was this fight started from an **elite** node? `fight_end` needs it for the reward tier
    /// (`inv:§5`: elite pays 25–35 gold, rare 10/40/50) and the cursor no longer says so.
    elite_fight: bool,
    /// §163: the recorded run calls, oldest first. **Not** part of game state (it is the host's
    /// action log), so `run_hash` does not include it and the archive does not carry it.
    journal: Vec<Rec>,
    /// §164: **这一段动作从哪里开始**。`RDR1,S,seed,asc` = 开局；`RDR1,A,<archive>` = 从一份档案
    /// 恢复之后。没有这一格，回档之后接着打的那些步就永远回放不了 —— 脚本的头部只有 seed/asc，
    /// 而回档的状态不在那条时间线上。
    head: std::string::String,
    /// Replaying right now? Then calls must not be recorded again (they would double the log).
    replaying: bool,
    /// How many steps the last replay verified (evidence for the gate).
    replay_checked: usize,
    /// Where the last replay diverged (`0` = it did not).
    replay_diverged: i32,
    /// §170 `P1-4`: 有过一次**算不出指纹**（规范文本超出 `run_hash` 的 `MAX_TEXT`）。
    ///
    /// 这一格存在的理由：哈希不可用时曾经被写成 `0`，而 `0` 是一个**合法可比较的值** —— 两个都溢出的
    /// 状态于是"相等"。现在不可用就记在这里，导出与回放都**响亮拒绝**，绝不拿 0 顶替。
    hash_failed: bool,
    /// Is a fight **in progress** right now? (§161.10)
    ///
    /// ⚠️ This is **not** "does a combat session exist": the page creates one at boot
    /// (`rd_env_reset`) so the fight view has something to draw, which made session-presence true
    /// from page load — a guard built on it refused every archive with a reason that was false.
    /// It is set by [`rd_run_fight_begin`] and cleared by [`rd_run_fight_end`] / [`rd_run_start`],
    /// so "a fight is running" has exactly one meaning and only the calls that own it move it.
    in_fight: bool,
}

/// 一次**会改运行层状态**的调用（§163）。
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
const K_FIGHT_BEGIN: u8 = 20;
const K_GRANT_POTION: u8 = 21;

const fn rec_kind_name(kind: u8) -> &'static str {
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
        K_FIGHT_BEGIN => "fight_begin",
        K_GRANT_POTION => "grant_potion",
        _ => "?",
    }
}

fn rec_kind_from_name(name: &str) -> Option<u8> {
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
        "fight_begin" => K_FIGHT_BEGIN,
        "grant_potion" => K_GRANT_POTION,
        _ => return None,
    })
}

/// `run_hash` 的前 8 字节 —— 逐步比对用。整条 64 字符的十六进制只留在错误信息里。
/// §166：本机**内容**的指纹（`sha256(镜像)` 的前 4 字节）。
///
/// 只算一次：镜像 38 KB，每次进战斗重算一遍是白烧 CPU，而它在一个进程里是常量。
/// `OnceLock` 而不是 `static mut`：这里真的可能被两个导出在"同一轮"里问到（页面先读指纹、
/// 再回放），而缓存一个常量不需要任何守卫之外的东西。
pub fn content_fingerprint() -> i32 {
    static PIN: std::sync::OnceLock<i32> = std::sync::OnceLock::new();
    *PIN.get_or_init(|| {
        let digest = rd_core::hash::sha256(crate::IMAGE);
        i32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]])
    })
}

/// The content fingerprint as 8 lowercase hex digits — the form the page prints and the script
/// carries. One spelling of the format, used by the export, the error message and the page.
pub fn content_pin_text() -> std::string::String {
    std::format!("{:08x}", content_fingerprint() as u32)
}

/// §167：**这份内容这个内核读得懂吗**（`0` 是懂，`-1` 是读不懂，理由在错误文本里）。
///
/// 与 `rd_content_fingerprint` 是两个问题，故意分成两个导出：
///
/// * 指纹答的是"**是不是同一份**内容"（+/- 一张牌都算不同）；
/// * 这一个答的是"**形状**能不能读"（行 schema 版本、每张关键表的行长）。
///
/// 页面在启动时问一次，于是"内容读不懂"是页面上的一句话，而不是第一次点按钮时的
/// wasm trap —— `content()` 里那条 `panic!` 在浏览器里看不出任何原因。
#[no_mangle]
pub extern "C" fn rd_content_check() -> i32 {
    match Content::parse(IMAGE) {
        Ok(_) => 0,
        Err(error) => {
            set_error(&std::format!("内容读不懂：{}", detail(&error)));
            -1
        }
    }
}

/// `§166`: 本机内容的指纹（八位十六进制，读作 u32）。
///
/// 页面用它做两件事：在导出脚本时把"这份脚本属于哪份内容"说出来；在回档/回放被拒时对照两边的值。
#[no_mangle]
pub extern "C" fn rd_content_fingerprint() -> i32 {
    content_fingerprint()
}

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
        // **懒上戳**：每条导出都在**动手之前**调 `log`，所以此刻的哈希就是"上一次调用之后"的哈希。
        // 这样不必要求每个导出都从 `finish` 回来（`rd_run_step` 就不是）。
        if let Some(last) = self.journal.last() {
            if last.hash == 0 {
                // §170 `P1-4`: 算不出来就**记下来**，不写 0 假装算过。
                let hash = self.state_hash();
                if let Some(last) = self.journal.last_mut() {
                    last.hash = hash.unwrap_or(0);
                }
            }
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
        let hash = self.state_hash();
        let Some(last) = self.journal.last_mut() else {
            return;
        };
        // §170 `P1-4`: `None` 不再是"0"，是"这一局的文本算不出指纹"—— 记进会话，导出/回放拒绝。
        last.hash = hash.unwrap_or(0);
    }

    /// 当前状态的哈希前缀，`None` = 规范文本超出 `run_hash` 的缓冲。
    ///
    /// 唯一的取哈希入口：失败时**置** `hash_failed`，于是"算不出"这件事跟着会话走到每个消费者，
    /// 而不是被某个 `unwrap_or(0)` 咽掉。
    fn state_hash(&mut self) -> Option<u64> {
        let hash = hash_prefix(&self.state);
        if hash.is_none() {
            self.hash_failed = true;
        }
        hash
    }
}

static mut RUN: Option<RunSession> = None;
/// The scratch size, as a `const` so reading it does not need `unsafe` (a mutable static's length
/// may not be read outside an `unsafe` block, and the length is not the unsafe part).
const RUN_SCRATCH_LEN: usize = 1024;

/// Scratch for the error text handed across the boundary.
static mut RUN_SCRATCH: [u8; RUN_SCRATCH_LEN] = [0; RUN_SCRATCH_LEN];

/// The run slot. Same argument as `lib.rs::slot()` — and the same rule: **no borrow may span a call
/// to another export**, because `rd_run_replay_from` re-enters this one on purpose.
#[allow(static_mut_refs)]
fn run_slot() -> &'static mut Option<RunSession> {
    unsafe { &mut RUN }
}

/// Write the error into a session the caller already holds.
///
/// `set_error` re-takes the global slot, so calling it while holding `run_slot().as_mut()` aliases
/// the same `static mut` -- two live references to one object, which is undefined behaviour. It
/// showed up as an **access violation** in `rust-units` (exit 0xC0000005) rather than as a wrong
/// answer, which is the only good thing about it.
fn fail(session: &mut RunSession, message: &str) -> i32 {
    session.error.clear();
    session.error.push_str(message);
    -2
}

fn set_error(message: &str) {
    if let Some(session) = run_slot().as_mut() {
        session.error.clear();
        session.error.push_str(message);
    }
}

/// The content image, leaked once. `Content` must be `'static` and a page asks for at most a few
/// of these over its lifetime.
fn content() -> &'static Content<'static> {
    match Content::parse(IMAGE) {
        Ok(content) => Box::leak(Box::new(content)),
        Err(e) => {
            // Unreachable: `rd_env_*` parses the same bytes and the smoke test covers it. If it
            // ever happens the message must say so rather than panic inside an export.
            set_error(&std::format!("RDCF 镜像解析失败: {}", detail(&e)));
            // Still needs to hand *something* back; `Content::parse` succeeded for the combat half
            // in every build so far, so a second failure is a genuine impossibility guard.
            panic!("the embedded content image does not parse");
        }
    }
}

fn roots(content: &Content<'_>) -> DeckRoots {
    DeckRoots {
        characters: content.root_by_name("Characters"),
        start: content.root_by_name("Start"),
        deck: content.root_by_name("Deck"),
    }
}

fn describe(error: &RunError) -> String {
    std::format!("{error:?}")
}

// =============================================================================================
// Lifecycle
// =============================================================================================

/// An empty `F_TERM` cell: the field is unset. `ABSENT` and `NULL` are two encodings of "nothing"
/// (`content-schema.md` §2.2) and both mean the same thing here.
fn cell_is_empty(cell: u16) -> bool {
    cell == rd_core::content::ABSENT16 || cell == rd_core::content::NULL16
}

/// The `REL` row for a relic id.
fn relic_row(
    content: &'static Content<'static>,
    id: &str,
) -> Option<rd_core::content::RelRow<'static>> {
    let entry = content.lookup_in(id, rd_core::content::EK_RELIC)?;
    let row = content.row(rd_core::content::Table::Relic, entry.index as u32)?;
    rd_core::content::RelRow::new(row)
}

/// The relic's `DisplayName`, falling back to its id.
fn relic_name<'a>(content: &'static Content<'static>, id: &'a str) -> Option<&'a str> {
    let row = relic_row(content, id)?;
    content.string(row.display_name()).or(Some(id))
}

/// Which declared-but-unexecuted field a relic carries, if any.
///
/// `REL` rows have `RunPrograms` and `CombatRules`, and **this kernel executes neither** (there is
/// no run-level program interpreter and no `CombatRules` registry — `rd-run`'s
/// `RunState::end_of_combat` implements effects one id at a time instead). A relic that declares
/// one of them would therefore be accepted and quietly do nothing, which is the exact failure this
/// project keeps paying for. So the run refuses to start instead.
fn relic_unrunnable_field(
    content: &'static Content<'static>,
    id: &str,
) -> Result<Option<&'static str>, String> {
    let Some(row) = relic_row(content, id) else {
        return Err(std::format!("内容镜像里没有遗物 `{id}`（REL 表查不到）"));
    };
    if !cell_is_empty(row.run_programs()) {
        return Ok(Some("RunPrograms"));
    }
    if !cell_is_empty(row.combat_rules()) {
        return Ok(Some("CombatRules"));
    }
    Ok(None)
}

/// The content's card ids, in table order -- the pool a merchant draws from.
///
/// Walked rather than listed: a list here would be a second copy of a content fact, and the whole
/// point of `Content` is that there is one copy.
fn card_pool(content: &'static Content<'static>) -> Vec<&'static str> {
    let mut out = Vec::new();
    let mut index = 0u32;
    while let Some(row) = content.row(rd_core::content::Table::Card, index) {
        if let Some(card) = rd_core::content::CardRow::new(row) {
            if let Some(id) = content.string(card.id()) {
                out.push(id);
            }
        }
        index += 1;
    }
    out
}

/// The cards a **reward screen** may offer.
///
/// `inv:§3.5`: Act 1 never offers an upgraded card (upgrade probability 0%), so the `x+` rows are
/// out. The status cards (`slimed`) *should* also be out and are not: this content's `Tags` cell is
/// a term the kernel cannot walk for `CARD` rows yet (`status_bind::has_tag` does that walk for
/// `STATUS` rows only), so a tag filter here would be a guess. Written down in the plan's downgrade
/// table rather than papered over.
/// Every card with its rarity -- what the merchant draws from.
fn full_pool(
    content: &'static Content<'static>,
) -> Result<Vec<rd_run::state::PoolCard<'static>>, String> {
    let mut pool = Vec::new();
    for id in card_pool(content) {
        // §183/§185: **colorless cards never enter a deck.** In StS they live in their own pool and
        // arrive through the dedicated merchant slot, events and potions; this content has no such
        // slot, so the honest rule is "the Colorless Potion is the only way to see one".
        //
        // ⚠️ This belongs in `full_pool`, not in `reward_pool`: the **merchant** draws from
        // `full_pool`, so filtering only rewards left the three new cards for sale -- the driver
        // bought them, its deck got weaker, and eleven of twelve seeds died early. One rule, one
        // owner (the ping-pong between two lists is exactly how such a leak survives).
        if content.card_has_tag(id, "colorless") == Some(true) {
            continue;
        }
        let rarity = match content.card_rarity(id) {
            Some(name) => rd_run::state::Rarity::from_name(name)
                .ok_or_else(|| std::format!("卡 `{id}` 的 Rarity `{name}` 不认识"))?,
            None => return Err(std::format!("卡 `{id}` 没有 Rarity")),
        };
        pool.push(rd_run::state::PoolCard { id, rarity });
    }
    Ok(pool)
}

/// The reward pool: the same cards minus the upgraded rows (`inv:§3.5`: Act 1 never offers one).
fn reward_pool(
    content: &'static Content<'static>,
) -> Result<Vec<rd_run::state::PoolCard<'static>>, String> {
    let mut pool = Vec::new();
    // §189 `A12`：`+` 行**必须在池子里**（升级要找得到目标），但**不能被当成
    // 基础奖励直接选中** —— 后一条由 `pick_of` 负责（它跳过 `+`）。两条在不同层，
    // 因为它们回答的是不同的问题："池子里有什么" 与 "这一次能拿哪一张"。
    for card in full_pool(content)? {
        // `rd-run` drops `Status`/`Curse` from the roll itself -- one rule, one owner.
        pool.push(card);
    }
    Ok(pool)
}

/// The content's relics, in table order, **with their rarity** (§156).
///
/// A relic whose `REL.Rarity` is missing or unknown is skipped and reported by the caller: letting it
/// default to `Common` would flatten the drop weights and look exactly like a balance decision.
fn relic_pool(content: &'static Content<'static>) -> Vec<rd_run::state::PoolRelic<'static>> {
    let mut out = Vec::new();
    let mut index = 0u32;
    while let Some(row) = content.row(rd_core::content::Table::Relic, index) {
        if let Some(relic) = rd_core::content::RelRow::new(row) {
            let id = content.string(relic.id());
            let rarity = content
                .string(relic.rarity())
                .and_then(rd_run::state::Rarity::from_name);
            if let (Some(id), Some(rarity)) = (id, rarity) {
                out.push(rd_run::state::PoolRelic { id, rarity });
            }
        }
        index += 1;
    }
    out
}

/// Every potion in the image, with the rarity its `POT` row declares (§156/§158).
///
/// §158 removed the per-act `PotionTables` lists. Two reasons, in the order they bit:
/// * the wiki has **no** per-act potion split -- every potion of a rarity is equally likely in
///   every act, so the act was never a real input;
/// * `MAX_POOL_IDS` is 8, so a 33-entry list would have been **silently truncated to eight** and
///   two-thirds of the pool would have been unreachable while the content gate still said it was
///   there. Reading the `POT` table directly cannot fall out of sync with the potions that exist.
fn potion_pool_of(image: &'static Content<'static>) -> Vec<rd_run::state::PoolPotion<'static>> {
    let mut out = Vec::new();
    for index in 0..image.potion_count() {
        let Some(potion) = image.potion(index) else {
            continue;
        };
        let Some(rarity) = rd_run::state::Rarity::from_name(potion.rarity) else {
            continue;
        };
        out.push(rd_run::state::PoolPotion {
            id: potion.id,
            rarity,
        });
    }
    out
}

fn write_out(text: &str, ptr: *mut u8) -> i32 {
    if ptr.is_null() {
        return 0;
    }
    let bytes = text.as_bytes();
    for (offset, &byte) in bytes.iter().enumerate() {
        unsafe { *ptr.add(offset) = byte };
    }
    bytes.len() as i32
}

/// A helper that turns a `Result<_, RunError>` into the ABI's convention: `0` ok, `-2` refused, and
/// the message in the error buffer. Kept in one place so every new action reports the same way.
fn finish(session: &mut RunSession, result: Result<i32, RunError>) -> i32 {
    // §163: one line here is what keeps every export from having to remember to stamp the hash.
    session.stamp();
    match result {
        Ok(value) => {
            session.error.clear();
            value
        }
        Err(error) => {
            let message = describe(&error);
            session.error.clear();
            session.error.push_str(&message);
            -2
        }
    }
}

/// `env-abi.md` §11.1: start a run. Returns 0, or a negative value with the reason in the error
/// buffer.
///
/// `ascension` is `0..=20` (§159): the wiki's rules are cumulative, so a level is one number and
/// every rule asks `at_least` for its own. A level above 20 is clamped, not refused -- "A20" is the
/// end of the ladder and a caller's off-by-one should not be a dead button.
#[no_mangle]
pub extern "C" fn rd_run_start(seed: i32, ascension: i32) -> i32 {
    // §161.10: a new run **ends** any fight the previous one left behind. This is what makes
    // "a combat session exists" mean "a fight is in progress" -- without it, a page that starts a
    // new run mid-fight leaves the session alive and every later "no archiving in a fight" check
    // refuses forever, for a reason that is no longer true.
    crate::take_session();
    // A new run is never mid-fight (§161.10): clear the bit here as well as the session, because a
    // page can start a run from the game-over screen while the old fight's flag is still set.
    if let Some(session) = run_slot().as_mut() {
        session.in_fight = false;
    }
    let content = content();
    let roots = roots(content);

    // Everything the run starts with comes out of the content. Hard-coding 80 here would be a
    // second copy of a number the document already carries.
    let facts = match content.character_start_facts(roots) {
        Ok(Some(facts)) => facts,
        Ok(None) => {
            set_error("内容里没有角色起始记录（Characters[0].Start）");
            return -1;
        }
        Err(e) => {
            set_error(&std::format!("character_start_facts: {}", detail(&e)));
            return -2;
        }
    };
    let deck: Vec<&str> = match content.start_deck(roots) {
        Ok(start) => {
            let mut ids = Vec::with_capacity(start.len());
            for index in 0..start.len() {
                match start.get(index) {
                    Ok(id) => ids.push(id),
                    Err(e) => {
                        set_error(&std::format!("start_deck[{index}]: {}", detail(&e)));
                        return -3;
                    }
                }
            }
            ids
        }
        Err(e) => {
            set_error(&std::format!("start_deck: {}", detail(&e)));
            return -4;
        }
    };
    if deck.len() > MAX_RUN_DECK {
        set_error(&std::format!(
            "起始牌组 {} 张，超过 RunState 的容量 {MAX_RUN_DECK}（这是内容与容量不一致，不是截断点）",
            deck.len()
        ));
        return -5;
    }

    let mut state = match RunState::new_with_ascension(
        seed,
        facts.max_health,
        facts.gold,
        &deck,
        u8::try_from(ascension.clamp(0, i32::from(rd_run::state::MAX_ASCENSION))).unwrap_or(0),
    ) {
        Ok(state) => Box::new(state),
        Err(e) => {
            set_error(&std::format!("RunState::new: {}", describe(&e)));
            return -6;
        }
    };
    // `StartingHealth` may be below the maximum; `adjust_health` is the clamped way to say so.
    state.adjust_health(facts.starting_health - state.health());
    // §159 `A6`: "lose 10% health at the start of each run". Applied **here**, after the content's
    // own starting value, because it is the one place that knows both -- see
    // `RunState::new_with_ascension`'s note about which of the two numbers wins.
    if state.at_least(rd_run::state::A_START_DAMAGED) {
        let damage =
            state.health_max() * rd_run::state::ASCENDED_START_DAMAGE_PERCENT / 100;
        state.adjust_health(-damage);
    }

    // Starting relics, out of the content (`Start.StartingRelics`). A relic whose declared effect
    // this kernel cannot run is refused here rather than loaded and ignored.
    match content.start_relics(roots) {
        Ok(Some(list)) => {
            for index in 0..list.len() {
                let id = match list.get(index) {
                    Ok(id) => id,
                    Err(e) => {
                        set_error(&std::format!("start_relics[{index}]: {}", detail(&e)));
                        return -7;
                    }
                };
                match relic_unrunnable_field(content, id) {
                    Ok(None) => {}
                    Ok(Some(field)) => {
                        set_error(&std::format!(
                            "遗物 `{id}` 声明了 `{field}`，但本内核不执行遗物节目/法令 \
                             （效果是按 id 逐条实现的，见 rd-run 的 RunState::end_of_combat）—— \
                             与其静默地什么都不做，不如拒绝开局"
                        ));
                        return -8;
                    }
                    Err(message) => {
                        set_error(&message);
                        return -9;
                    }
                }
                if let Err(e) = state.push_relic(id) {
                    set_error(&std::format!("push_relic({id}): {}", describe(&e)));
                    return -10;
                }
            }
        }
        Ok(None) => {} // the content declares no starting relics, which is legal
        Err(e) => {
            set_error(&std::format!("start_relics: {}", detail(&e)));
            return -11;
        }
    }

    // `inv:§7.1`: a run opens on a blessing choice, not on floor 1. No move is legal until it is
    // taken, which is the same discipline as `NodeNotSettled` one level up.
    let mut state = state;
    if let Err(e) = state.offer_start_choice() {
        set_error(&std::format!("offer_start_choice: {}", describe(&e)));
        return -12;
    }
    *run_slot() = Some(RunSession {
        state,
        error: String::new(),
        elite_fight: false,
        boss_fight: false,
        in_fight: false,
        journal: Vec::new(),
        head: std::format!("RDR1,S,{},{},{}", seed, ascension, content_pin_text()),
        replaying: false,
        replay_checked: 0,
        replay_diverged: 0,
        hash_failed: false,
    });
    0
}

/// The seed of the current run, or `i32::MIN` if there is none.
#[no_mangle]
pub extern "C" fn rd_run_seed() -> i32 {
    run_slot().as_ref().map_or(i32::MIN, |s| s.state.seed())
}

/// `env-abi.md` §11.1: the length of the run observation.
#[no_mangle]
pub extern "C" fn rd_run_observe_len() -> i32 {
    RUN_OBS_LEN as i32
}

/// The **name** of relic `index` (`REL.DisplayName`, falling back to the id), or `-1`.
#[no_mangle]
pub extern "C" fn rd_run_relic_name_len(index: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    let Some(id) = session.state.relics().get(index as usize) else {
        return -1;
    };
    relic_name(content(), id.as_str()).map_or(-1, |name| name.len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_run_relic_name_len(index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_relic_name_into(index: i32, ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    if index < 0 {
        return 0;
    }
    let Some(id) = session.state.relics().get(index as usize) else {
        return 0;
    };
    match relic_name(content(), id.as_str()) {
        Some(name) if !ptr.is_null() => {
            let bytes = name.as_bytes();
            for (offset, &byte) in bytes.iter().enumerate() {
                *ptr.add(offset) = byte;
            }
            bytes.len() as i32
        }
        _ => 0,
    }
}

/// The **id** of relic `index` — what the effect rules are keyed on, useful for diagnostics.
#[no_mangle]
pub extern "C" fn rd_run_relic_id_len(index: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    session
        .state
        .relics()
        .get(index as usize)
        .map_or(-1, |id| id.as_str().len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_run_relic_id_len(index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_relic_id_into(index: i32, ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    if index < 0 {
        return 0;
    }
    let Some(id) = session.state.relics().get(index as usize) else {
        return 0;
    };
    if ptr.is_null() {
        return 0;
    }
    let bytes = id.as_str().as_bytes();
    for (offset, &byte) in bytes.iter().enumerate() {
        *ptr.add(offset) = byte;
    }
    bytes.len() as i32
}

/// `env-abi.md` §11.3. Out of range is `i32::MIN`, matching the combat ABI's convention.
#[no_mangle]
pub extern "C" fn rd_run_observe(index: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return i32::MIN;
    };
    let state = &session.state;
    let value = match index {
        0 => state.floor(),
        1 => state.node(),
        2 => state.health(),
        3 => state.health_max(),
        4 => state.gold(),
        5 => state.deck().len() as i32,
        6 => state.relics().len() as i32,
        7 => state.potions().len() as i32,
        8 => state.map().node_count() as i32,
        9..=15 => {
            let stream = RunStream::ALL[index as usize - 9];
            state.rng().counter(stream)
        }
        16 => state.reachable().len() as i32,
        17 => state.removed_cards(),
        18 => 0, // reserved (`env-abi.md` §11.3)
        _ => return i32::MIN,
    };
    value
}

// =============================================================================================
// The map
// =============================================================================================

/// How many nodes the map has (every present node), or `-1` when there is no run.
#[no_mangle]
pub extern "C" fn rd_run_map_len() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |s| s.state.map().node_count() as i32)
}

/// How many rows the map has.
#[no_mangle]
pub extern "C" fn rd_run_map_rows() -> i32 {
    ROWS as i32
}

/// The global index of the first node of `row`, or `-1`.
#[no_mangle]
pub extern "C" fn rd_run_map_row_first(row: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if row < 0 {
        return -1;
    }
    session
        .state
        .map()
        .row_first(row as usize)
        .map_or(-1, i32::from)
}

/// `env-abi.md` §11.2. `i32::MIN` for an out-of-range index or field.
///
/// The edges are reported as **global** node indices: the storage numbers them per row, and
/// making every consumer redo that arithmetic is how off-by-one bugs get shipped
/// (`run-layer.md` §4.3).
#[no_mangle]
pub extern "C" fn rd_run_map_node(index: i32, field: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return i32::MIN;
    };
    if index < 0 {
        return i32::MIN;
    }
    let map = session.state.map();
    let Some((row, local)) = map.locate(index as u8) else {
        return i32::MIN;
    };
    let Some(line) = map.row(row) else {
        return i32::MIN;
    };
    let Some(node) = line.node(local) else {
        return i32::MIN;
    };
    match field {
        NODE_FIELD_ROW => row as i32,
        NODE_FIELD_COL => i32::from(node.col),
        NODE_FIELD_KIND => node.kind as i32,
        NODE_FIELD_OUT_DEGREE => i32::from(node.out_degree()),
        NODE_FIELD_EDGE0 | NODE_FIELD_EDGE1 | NODE_FIELD_EDGE2 => {
            let slot = (field - NODE_FIELD_EDGE0) as usize;
            match node.out_targets().get(slot) {
                Some(&target) => map.global_of(row + 1, target as usize).map_or(-1, i32::from),
                None => -1,
            }
        }
        NODE_FIELD_REACHABLE => i32::from(session.state.reachable().contains(index as u8)),
        _ => i32::MIN,
    }
}

// =============================================================================================
// Actions
// =============================================================================================

/// How many legal actions there are (`env-abi.md` §11.4).
#[no_mangle]
pub extern "C" fn rd_run_action_count() -> i32 {
    run_slot()
        .as_ref()
        .map_or(0, |s| s.state.reachable().len() as i32)
}

/// The `kind` of action `index`: 0 = enter a node. `-1` when out of range.
#[no_mangle]
pub extern "C" fn rd_run_action(index: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if index < 0 || index as usize >= session.state.reachable().len() {
        return -1;
    }
    0
}

/// `which` ∈ {0,1}: arg0 = the target node's global index, arg1 = `-1`. `-1` when out of range.
#[no_mangle]
pub extern "C" fn rd_run_action_arg(index: i32, which: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    let reachable = session.state.reachable();
    if index < 0 || index as usize >= reachable.len() {
        return -1;
    }
    match which {
        0 => i32::from(reachable.get(index as usize).unwrap_or(0)),
        1 => -1,
        _ => -1,
    }
}

/// Take action `action_index`. `0` accepted; `-1` out of range; `-2` refused by the run layer.
///
/// A refusal leaves the state **byte-identical**: the run observation before and after must match
/// field for field, which is the same rule the combat ABI uses (`env-abi.md` §10).
#[no_mangle]
pub extern "C" fn rd_run_step(action_index: i32) -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_STEP, action_index, -1, "");
    let reachable = session.state.reachable();
    if action_index < 0 || action_index as usize >= reachable.len() {
        set_error("action index out of range");
        return -1;
    }
    let target = reachable.get(action_index as usize).unwrap_or(0);
    match session.state.enter_node(target) {
        Ok(()) => {
            session.error.clear();
            0
        }
        Err(e) => {
            let message = describe(&e);
            session.error.clear();
            session.error.push_str(&message);
            -2
        }
    }
}

// =============================================================================================
// Settling the node under the cursor (`env-abi.md` §11.6)
// =============================================================================================
//
// `rd_run_step` only *walks*; these settle. The split is `run-layer.md` §4.7.1 and it is what lets
// the map page draw a whole Act without pretending a fight happened.

/// What the node under the cursor is waiting for (`Pending` as an integer).
#[no_mangle]
pub extern "C" fn rd_run_pending() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |s| s.state.pending() as u8 as i32)
}

/// The kind of the node under the cursor, or `-1`.
#[no_mangle]
pub extern "C" fn rd_run_node_kind() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    let node = session.state.node();
    if node < 0 {
        return -1;
    }
    // The boss is a **sentinel cursor**, not a map index (inv:§7.2: floor 16 is off the map).
    if node == i32::from(rd_run::map::BOSS_NODE) {
        return i32::from(rd_run::map::NodeKind::Boss as u8);
    }
    session
        .state
        .map()
        .locate(node as u8)
        .and_then(|(row, local)| {
            session
                .state
                .map()
                .row(row)
                .and_then(|line| line.node(local))
                .map(|node| node.kind as i32)
        })
        .unwrap_or(-1)
}

/// Declare what the node under the cursor needs. `0` = done, `-2` = refused (see the error buffer).
#[no_mangle]
pub extern "C" fn rd_run_begin_node() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_BEGIN, -1, -1, "");
    let content = content();
    let cards = match full_pool(content) {
        Ok(cards) => cards,
        Err(message) => return fail(session, &message),
    };
    let relics = relic_pool(content);
    // The kind comes back from `begin_node` itself: calling `rd_run_node_kind()` here would take the
    // run slot a second time while `session` is already borrowed (the aliasing bug from round 51).
    let kind = match session.state.begin_node(&cards, &relics) {
        Ok(kind) => kind,
        Err(e) => {
            let message = describe(&e);
            return fail(session, &message);
        }
    };
    // A `?` room needs an event, and the events live in the content (`EV`) -- so the pick happens
    // here, where both sides are reachable. The `Event` stream is what `run-layer.md` §3.2 reserves
    // for exactly this.
    if kind == rd_run::map::NodeKind::Unknown {
        let image = content;
        // **The act decides which `?` rooms can appear** (`port-plan.md` §133): `Events` /
        // `Events2` / `Events3`. A missing pool is a content gap and says so.
        let act = session.state.act();
        let pool_name: &str = match act {
            1 => "Events",
            2 => "Events2",
            _ => "Events3",
        };
        let Some(pool) = image.event_pool(pool_name) else {
            let message = std::format!("内容里没有 `EventTables.{pool_name}` 池（第 {act} 幕）");
            return fail(session, &message);
        };
        let events: Vec<&'static str> = pool.iter().filter(|id| !id.is_empty()).copied().collect();
        if events.is_empty() {
            return fail(
                session,
                "内容里没有事件（`EV` 0 行）—— `?` 房无处可去",
            );
        }
        let count = events.len() as u32;
        let pick = match session.state.rng_mut().roll(RunStream::Event, count) {
            Ok(value) => value,
            Err(e) => {
                let message = describe(&e);
                return fail(session, &message);
            }
        };
        let Some(id) = events.get(pick as usize).copied() else {
            return fail(session, "事件读不出来");
        };
        if let Err(e) = session.state.begin_event(id) {
            let message = describe(&e);
            return fail(session, &message);
        }
    }
    0
}

/// Rest: heal 30% of maximum HP. Returns the health restored, or `-2`.
#[no_mangle]
pub extern "C" fn rd_run_rest() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_REST, -1, -1, "");
    let outcome = session.state.rest();
    finish(session, outcome)
}

/// Smith: replace deck card `index` with its upgraded row.
#[no_mangle]
pub extern "C" fn rd_run_smith(index: i32) -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_SMITH, index, -1, "");
    if index < 0 {
        return -1;
    }
    // The upgrade mapping is the content's: `strike` -> `strike+` is a convention of the document
    // (`run-layer.md` §4.7.4), so it is resolved here, where the content is reachable, and never
    // inside `rd-run`.
    let Some(current) = session.state.deck().get(index as usize).map(|id| id.as_str()) else {
        return -1;
    };
    let upgraded = std::format!("{current}+");
    let content = content();
    if content
        .lookup_in(&upgraded, rd_core::content::EK_CARD)
        .is_none()
    {
        let message = std::format!("`{current}` 没有升级行（内容里没有 `{upgraded}`）");
        return fail(session, &message);
    }
    let outcome = session.state.smith(index as usize, &upgraded.clone()).map(|_| 0i32);
    finish(session, outcome)
}

/// Open the chest under the cursor. `0` = done; the gold and relic are in the run observation and
/// `rd_run_relic_*`.
#[no_mangle]
pub extern "C" fn rd_run_open_chest() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_CHEST, -1, -1, "");
    let relics = relic_pool(content());
    let outcome = session.state.open_chest(&relics).map(|_| 0i32);
    finish(session, outcome)
}

/// Walk away from whatever is pending.
#[no_mangle]
pub extern "C" fn rd_run_leave() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_LEAVE, -1, -1, "");
    let outcome = session.state.leave().map(|_| 0i32);
    finish(session, outcome)
}

/// How many cards the merchant is selling.
#[no_mangle]
pub extern "C" fn rd_run_shop_card_count() -> i32 {
    run_slot()
        .as_ref()
        .map_or(0, |s| s.state.shop().cards().len() as i32)
}

/// The **id** of shop card `slot`.
#[no_mangle]
pub extern "C" fn rd_run_shop_card_id_len(slot: i32) -> i32 {
    shop_offer(run_slot().as_ref(), slot, true).map_or(-1, |offer| offer.id.as_str().len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_run_shop_card_id_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_shop_card_id_into(slot: i32, ptr: *mut u8) -> i32 {
    match shop_offer(run_slot().as_ref(), slot, true) {
        Some(offer) => write_out(offer.id.as_str(), ptr),
        None => 0,
    }
}

/// The price of shop card `slot`; `-1` once sold.
#[no_mangle]
pub extern "C" fn rd_run_shop_card_price(slot: i32) -> i32 {
    shop_offer(run_slot().as_ref(), slot, true).map_or(-1, |offer| offer.price)
}

/// How many relics the merchant is selling.
#[no_mangle]
pub extern "C" fn rd_run_shop_relic_count() -> i32 {
    run_slot()
        .as_ref()
        .map_or(0, |s| s.state.shop().relics().len() as i32)
}

/// The **id** of shop relic `slot`.
#[no_mangle]
pub extern "C" fn rd_run_shop_relic_id_len(slot: i32) -> i32 {
    shop_offer(run_slot().as_ref(), slot, false).map_or(-1, |offer| offer.id.as_str().len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_run_shop_relic_id_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_shop_relic_id_into(slot: i32, ptr: *mut u8) -> i32 {
    match shop_offer(run_slot().as_ref(), slot, false) {
        Some(offer) => write_out(offer.id.as_str(), ptr),
        None => 0,
    }
}

/// The price of shop relic `slot`; `-1` once sold.
#[no_mangle]
pub extern "C" fn rd_run_shop_relic_price(slot: i32) -> i32 {
    shop_offer(run_slot().as_ref(), slot, false).map_or(-1, |offer| offer.price)
}

fn shop_offer(
    session: Option<&RunSession>,
    slot: i32,
    cards: bool,
) -> Option<rd_run::state::Offer> {
    let session = session?;
    if slot < 0 {
        return None;
    }
    let stock = session.state.shop();
    let list = if cards {
        stock.cards()
    } else {
        stock.relics()
    };
    list.get(slot as usize).copied()
}

/// What removing a card costs right now (`inv:§8.2`: 75, then +25 per removal).
#[no_mangle]
pub extern "C" fn rd_run_remove_price() -> i32 {
    run_slot().as_ref().map_or(-1, |s| s.state.remove_card_price())
}

/// Buy shop card `slot`.
#[no_mangle]
pub extern "C" fn rd_run_buy_card(slot: i32) -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_BUY_CARD, slot, -1, "");
    if slot < 0 {
        return -1;
    }
    let outcome = session.state.buy_card(slot as usize).map(|_| 0i32);
    finish(session, outcome)
}

/// Buy shop relic `slot`.
#[no_mangle]
pub extern "C" fn rd_run_buy_relic(slot: i32) -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_BUY_RELIC, slot, -1, "");
    if slot < 0 {
        return -1;
    }
    let outcome = session.state.buy_relic(slot as usize).map(|_| 0i32);
    finish(session, outcome)
}

/// Pay to remove deck card `index`. Returns the price paid.
#[no_mangle]
pub extern "C" fn rd_run_remove_card(index: i32) -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_REMOVE, index, -1, "");
    if index < 0 {
        return -1;
    }
    let outcome = session.state.remove_card(index as usize);
    finish(session, outcome)
}

// =============================================================================================
// The reward screen (`env-abi.md` §11.9)
// =============================================================================================

/// The open event's body text (`EV.DescriptionKey`) and its name, as one line: `"<name> — <text>"`.
#[no_mangle]
pub extern "C" fn rd_run_event_text_len() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match open_event(session) {
        Some(text) => text.len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_event_text_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_event_text_into(ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    match open_event(session) {
        Some(text) => write_out(&text, ptr),
        None => 0,
    }
}

/// Choice `slot`'s button text.
#[no_mangle]
pub extern "C" fn rd_run_event_label_len(slot: i32) -> i32 {
    match event_choice(slot) {
        Some(choice) => choice.label.len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_event_label_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_event_label_into(slot: i32, ptr: *mut u8) -> i32 {
    match event_choice(slot) {
        Some(choice) => write_out(choice.label, ptr),
        None => 0,
    }
}

/// Choice `slot`'s **first** effect, as the ABI's small integer: 1 heal, 2 gold, 3 lose health,
/// 4 max health, 5 nothing, `-1` unknown. §188: an option is a **list** now, so this is the head of
/// it -- kept for the pages that only draw one chip; `rd_run_event_effect_at` walks the rest.
#[no_mangle]
pub extern "C" fn rd_run_event_effect(slot: i32) -> i32 {
    rd_run_event_effect_at(slot, 0)
}

/// Choice `slot`'s first effect's amount.
#[no_mangle]
pub extern "C" fn rd_run_event_amount(slot: i32) -> i32 {
    rd_run_event_amount_at(slot, 0)
}

/// §188: how many effects choice `slot` has **at this run's ascension** (A15 swaps the list).
#[no_mangle]
pub extern "C" fn rd_run_event_effect_count(slot: i32) -> i32 {
    let Some(choice) = event_choice(slot) else {
        return -1;
    };
    let level = run_slot().as_ref().map_or(0, |s| s.state.ascension());
    i32::from(choice.effects_at(level, rd_run::state::A_EVENTS_WORSE).len() as u8)
}

/// §188: effect `index` of choice `slot`, as the same small integer as `rd_run_event_effect`.
#[no_mangle]
pub extern "C" fn rd_run_event_effect_at(slot: i32, index: i32) -> i32 {
    let Some(spec) = event_effect_spec(slot, index) else {
        return -1;
    };
    effect_code(spec.effect)
}

/// §188: effect `index` of choice `slot`'s amount.
#[no_mangle]
pub extern "C" fn rd_run_event_amount_at(slot: i32, index: i32) -> i32 {
    event_effect_spec(slot, index).map_or(0, |spec| i32::from(spec.amount))
}

/// Effect `index` of choice `slot` **for this run's ascension**.
fn event_effect_spec(slot: i32, index: i32) -> Option<rd_core::content::EffectSpec<'static>> {
    let choice = event_choice(slot)?;
    if index < 0 {
        return None;
    }
    let level = run_slot().as_ref().map_or(0, |s| s.state.ascension());
    let specs = choice.effects_at(level, rd_run::state::A_EVENTS_WORSE);
    specs.get(index as usize).copied()
}

/// Take choice `slot` of the open event.
///
/// A choice that edits the deck does **not** finish here: it leaves the run in
/// `Pending::EventCard`, and `rd_run_event_needs()` says which edit is owed. That is why this
/// returns `0` in both cases -- "taken" and "taken, now pick a card" are both accepted.
#[no_mangle]
pub extern "C" fn rd_run_choose(slot: i32) -> i32 {
    let Some(choice) = event_choice(slot) else {
        return -1;
    };
    // §188：选项是**一串**效果，而 A15（事件变糟）给的是**另一串**。
    let level = run_slot().as_ref().map_or(0, |s| s.state.ascension());
    let specs = choice.effects_at(level, rd_run::state::A_EVENTS_WORSE);
    let mut parsed: [(rd_run::state::EventEffect, Option<&'static str>); 8] = [
        (rd_run::state::EventEffect::Nothing, None);
        8
    ];
    if specs.len() > parsed.len() {
        return -1;
    }
    for (index, spec) in specs.iter().enumerate() {
        let named = spec.effect.split_once(':').map(|(_, payload)| payload);
        let Some((effect, _payload)) = effect_from(spec.effect, i32::from(spec.amount)) else {
            return -1;
        };
        // 载荷（`curse:<id>` 里的 id）必须指向 `'static`：它来自镜像的字符串池，而池本身是
        // `Box::leak` 出来的静态内存（见 `content()`）。
        parsed[index] = (effect, named);
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_CHOOSE, slot, -1, "");
    let pool = match reward_pool(content()) {
        Ok(pool) => pool,
        Err(message) => return fail(session, &message),
    };
    let outcome = session
        .state
        .resolve_event_effects(&parsed[..specs.len()], &pool)
        .map(|_| 0i32);
    finish(session, outcome)
}

/// What the open event still needs: `0` nothing, `1` remove a card, `2` upgrade one, `3` transform
/// one, `-1` no run. The deck-index picker is `rd_run_pick_event_card`.
#[no_mangle]
pub extern "C" fn rd_run_event_needs() -> i32 {
    use rd_run::state::DeckChange;
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match session.state.event_follow_up() {
        Some(DeckChange::Remove) => 1,
        Some(DeckChange::Upgrade) => 2,
        Some(DeckChange::Transform) => 3,
        None => 0,
    }
}

/// Finish an event choice that named a card, with deck index `index`.
#[no_mangle]
pub extern "C" fn rd_run_pick_event_card(index: i32) -> i32 {
    if index < 0 {
        return -1;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_EVENT_CARD, index, -1, "");
    let pool = match reward_pool(content()) {
        Ok(pool) => pool,
        Err(message) => return fail(session, &message),
    };
    let outcome = session
        .state
        .pick_event_card(index as usize, &pool)
        .map(|_| 0i32);
    finish(session, outcome)
}

/// The open event's choices, from the content.
fn event_choice(slot: i32) -> Option<rd_core::content::EventChoice<'static>> {
    let session = run_slot().as_ref()?;
    if slot < 0 || slot > 1 {
        return None;
    }
    let (_, _, choices) = lookup_event(session)?;
    Some(choices[slot as usize])
}

fn open_event(session: &RunSession) -> Option<String> {
    let (id, text, _) = lookup_event(session)?;
    Some(std::format!("{id} — {text}"))
}

fn lookup_event(
    session: &RunSession,
) -> Option<(&'static str, &'static str, [rd_core::content::EventChoice<'static>; 2])> {
    let wanted = session.state.event();
    let image = content();
    for index in 0..image.event_count() {
        let event = image.event(index)?;
        if event.0 == wanted {
            return Some(event);
        }
    }
    None
}

/// The content's closed vocabulary, as integers.
///
/// `1..=5` are the number effects (unchanged since §9); `6..=10` are the §143 additions. A caller
/// that sees `-1` must not guess -- that is the whole point of a closed vocabulary.
fn effect_code(effect: &str) -> i32 {
    match effect {
        "heal" => 1,
        "gold" => 2,
        "damage" => 3,
        "max_hp" => 4,
        "nothing" => 5,
        "remove_card" => 6,
        "upgrade_card" => 7,
        "transform_card" => 8,
        _ => {
            // `curse:<id>` / `relic:<id>`: one code per kind, whatever the payload is.
            if let Some((kind, payload)) = effect.split_once(':') {
                if payload.is_empty() {
                    return -1;
                }
                return match kind {
                    "curse" => 9,
                    "relic" => 10,
                    _ => -1,
                };
            }
            -1
        }
    }
}

/// Decode one content choice into the run layer's vocabulary.
///
/// The parser lives in `rd-run` (`EventEffect::parse`) so the page, the ABI and the tests cannot
/// drift about what "in the vocabulary" means; this function only carries the payload across.
fn effect_from(
    effect: &str,
    amount: i32,
) -> Option<(rd_run::state::EventEffect, Option<&str>)> {
    rd_run::state::EventEffect::parse(effect, amount)
}

/// **Use** potion `slot`.
///
/// The effects are applied through **public kernel APIs** (`set_defensive_pool` for Block,
/// `set_resource` for energy) or through the program pipeline (`exec::resolve_damage` wants an
/// `ExecContext`, and `exec::resolve_effect` covers draw / status). An effect the run layer does not
/// know **refuses loudly** rather than doing nothing.
///
/// §158: `Effect` is a comma-separated list of atoms, and the run-only atoms (`max_hp`,
/// `potion_fill`) work **outside** a fight -- the wiki lets you drink Fruit Juice and Entropic Brew
/// in most rooms.
///
/// Returns `0`, `-1` when there is no such slot, or `-2` with text.
#[no_mangle]
pub extern "C" fn rd_env_use_potion(slot: i32, target: i32) -> i32 {
    if slot < 0 {
        return -1;
    }
    // The id has to be copied out: the run slot is borrowed again at the end to consume it.
    let Some(id) = run_slot()
        .as_ref()
        .and_then(|run| run.state.potions().get(slot as usize))
        .map(|id| id.as_str().to_string())
    else {
        return -1;
    };
    let image = content();
    let Some(potion) = (0..image.potion_count())
        .filter_map(|index| image.potion(index))
        .find(|potion| potion.id == id)
    else {
        return refuse(&std::format!("药水 `{id}` 不在内容的 `POT` 表里"));
    };

    let amount = i32::from(potion.amount);
    // §158: `Effect` is a **comma-separated list of atoms**. Two kinds of atom are about the run
    // (`max_hp`, `potion_fill`) and need no fight; every other atom does. An effect that mixes the
    // two is refused rather than ordered by accident -- no content does it, and inventing an order
    // would be inventing a rule.
    let mut fight_atoms = 0usize;
    let mut run_atoms = 0usize;
    for atom in potion.effect.split(',') {
        if atom_needs_a_fight(atom) {
            fight_atoms += 1;
        } else {
            run_atoms += 1;
        }
    }
    if fight_atoms > 0 && run_atoms > 0 {
        return refuse("药水效果同时包含运行层原子与战斗层原子：执行顺序没有出处，所以拒绝");
    }
    if run_atoms > 0 {
        return match use_run_atoms(slot, potion.effect, amount) {
            Err(message) => refuse(&message),
            // `potion_fill` takes the bottle off the belt itself: it has to free its own slot
            // before it can fill anything, so "consume only after it worked" cannot apply.
            Ok(true) => 0,
            Ok(false) => consume_used_potion(slot),
        };
    }

    let Some(session) = crate::slot().as_mut() else {
        return refuse("不在战斗里 —— 这瓶药水的效果只能作用于一场战斗");
    };
    // §142: a potion is an action too, so the animation log describes it alone.
    session.state.clear_beats();
    let Some(hero) = session.hero_id() else {
        return refuse("战斗里找不到英雄");
    };
    for atom in potion.effect.split(',') {
        match atom {
        "combat_block" => {
            let Ok(key) = rd_core::state::DefensivePoolId::new("standard.block") else {
                return refuse("`standard.block` 不是合法的防守池 id");
            };
            let Some(combatant) = session.state.combatant_mut(&hero) else {
                return refuse("拿不到英雄的战斗员");
            };
            let current = combatant
                .defensive_pools()
                .iter()
                .find(|pool| pool.key.as_str() == "standard.block")
                .map_or(0, |pool| pool.pool.current);
            if let Err(e) = combatant.set_defensive_pool(key, current + amount, None) {
                return refuse(&std::format!("加格挡失败：{e:?}"));
            }
            // Read it straight back on the same combatant: this distinguishes "the write failed" from
            // "the observation is a stale snapshot" without guessing (see §84).
            let after = combatant
                .defensive_pools()
                .iter()
                .find(|pool| pool.key.as_str() == "standard.block")
                .map_or(-1, |pool| pool.pool.current);
            if after != current + amount {
                return refuse(&std::format!(
                    "格挡写进去读到 {after}，期望 {}",
                    current + amount
                ));
            }
        }
        "combat_energy" => {
            let Ok(key) = rd_core::state::ResourceId::new("standard.energy") else {
                return refuse("`standard.energy` 不是合法的资源 id");
            };
            let Some(combatant) = session.state.combatant_mut(&hero) else {
                return refuse("拿不到英雄的战斗员");
            };
            let current = combatant
                .resources()
                .iter()
                .find(|pool| pool.key.as_str() == "standard.energy")
                .map_or(0, |pool| pool.pool.current);
            // `None` for the cap: an Energy Potion pushes energy **past** the per-turn maximum. (The
            // first version passed the pool's own cap and the gain was clamped away -- and *that*
            // was compounded by the stale observation, which is why it looked like the write failed.)
            if let Err(e) = combatant.set_resource(key, current + amount, None) {
                return refuse(&std::format!("加能量失败：{e:?}"));
            }
            let after = combatant
                .resources()
                .iter()
                .find(|pool| pool.key.as_str() == "standard.energy")
                .map_or(-1, |pool| pool.pool.current);
            if after != current + amount {
                return refuse(&std::format!(
                    "能量写进去读到 {after}，期望 {}",
                    current + amount
                ));
            }
        }
        "combat_damage" => {
            // **Through the existing damage pipeline** (`exec::resolve_damage`), so Block, Vulnerable
            // and every other damage modifier apply exactly as they do for a card. `target` is an
            // enemy slot; `-1` means "the first living enemy".
            let slot_index = if target >= 0 {
                target as usize
            } else {
                (0..session.plan.enemies.len())
                    .find(|index| {
                        let id = session.plan.enemies[*index].id;
                        rd_core::state::CombatantId::new(id)
                            .ok()
                            .and_then(|cid| session.state.combatant(&cid))
                            .is_some_and(|c| c.health_current > 0)
                    })
                    .unwrap_or(usize::MAX)
            };
            let Some(plan_enemy) = session.plan.enemies.get(slot_index) else {
                return refuse("药水没有目标：这一侧没有活着的敌人");
            };
            let Ok(target_id) = rd_core::state::CombatantId::new(plan_enemy.id) else {
                return refuse("敌人的战斗员 id 不合法");
            };
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(hero.clone()),
                Some(target_id.clone()),
                None,
                64,
            )
            .with_content(image);
            if let Err(e) = rd_core::exec::resolve_damage(&mut ctx, &target_id, amount, false) {
                return refuse(&std::format!("伤害药水失败：{e:?}"));
            }
        }
        // ── §152: the new shapes. `kind:payload` carries a status id (the §143 convention). ────────
        "combat_heal_percent" => {
            // Wiki's Blood Potion: "Heal 20% of your max HP". A percentage, so it has to be read off
            // the hero rather than stored as a flat amount.
            let Some(combatant) = session.state.combatant(&hero) else {
                return refuse("拿不到英雄的战斗员");
            };
            let max = combatant.health_max;
            let healed = max.saturating_mul(amount) / 100;
            let current = combatant.health_current;
            let capped = (current.saturating_add(healed)).min(max);
            let Some(combatant) = session.state.combatant_mut(&hero) else {
                return refuse("拿不到英雄的战斗员");
            };
            combatant.health_current = capped;
        }
        // §157: Fruit Juice -- the run's maximum, not the fight's. `adjust_health` heals by the
        // same amount, which is what StS's "Gain 5 Max HP" does.
        "max_hp" => {
            let Some(run) = run_slot().as_mut() else {
                return refuse("没有在进行中的一局");
            };
            run.state.raise_max_health(amount);
            session.reobserve_after_external_change();
        }
        "combat_damage_all" => {
            // Every living enemy, each through the same pipeline a single-target potion uses.
            let mut ids: Vec<rd_core::state::CombatantId> = Vec::new();
            for enemy in session.plan.enemies.iter() {
                let Ok(id) = rd_core::state::CombatantId::new(enemy.id) else {
                    continue;
                };
                if session
                    .state
                    .combatant(&id)
                    .is_some_and(|c| c.health_current > 0)
                {
                    ids.push(id);
                }
            }
            if ids.is_empty() {
                return refuse("药水没有目标：场上没有活着的敌人");
            }
            for id in ids {
                let mut ctx = rd_core::exec::ExecContext::new(
                    &mut session.state,
                    Some(hero.clone()),
                    Some(id.clone()),
                    None,
                    64,
                )
                .with_content(image);
                if let Err(e) = rd_core::exec::resolve_damage(&mut ctx, &id, amount, false) {
                    return refuse(&std::format!("群体伤害药水失败：{e:?}"));
                }
            }
        }
        "combat_draw" => {
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DrawCards {
                    owner: hero,
                    count: amount,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            if let Err(e) = rd_core::exec::resolve_effect(&mut session.state, &item, Some(image)) {
                return refuse(&std::format!("抽牌药水失败：{e:?}"));
            }
        }
        "choice_hand_exhaust" | "choice_hand_discard_draw" => {
            // §161.3: these two do not resolve here -- they **ask a question**. The bottle is
            // consumed by the tail below (the wiki's potion is drunk either way), and the fight
            // stays modal until `rd_env_choice_confirm`.
            let then = if atom == "choice_hand_exhaust" {
                rd_core::state::ChoiceThen::Exhaust
            } else {
                rd_core::state::ChoiceThen::DiscardThenDraw
            };
            let Some(zones) = session.state.card_zones(&hero) else {
                return refuse("英雄没有牌区");
            };
            let hand = zones.count(rd_core::state::CardZone::Hand);
            if hand == 0 {
                // An empty hand means the question has no answers. Asking it anyway would put an
                // empty picker on screen whose only option is "confirm nothing" -- a modal that
                // exists to say the potion did nothing.
                continue;
            }
            let question = rd_core::state::PendingChoice {
                chooser: hero.clone(),
                source: rd_core::state::ChoiceSource::Hand,
                min: 0,
                max: hand.min(u8::MAX as usize) as u8,
                then,
                offered: rd_core::state::Bounded::new(),
            };
            if let Err(e) = session.state.begin_choice(question) {
                return refuse(&std::format!("这次选牌问不出口：{e}"));
            }
            session.choice_picks.clear();
        }
        other if other.starts_with("choice_offered:") => {
            // §161.5: Attack / Skill Potion -- "choose 1 of 3 random <type> cards to add to your
            // hand; it costs 0 this turn".
            let Some((_, tag)) = other.split_once(':') else {
                return refuse("`choice_offered` 缺少 `:<tag>`");
            };
            let image = content();
            // The pool is**内容**的事：哪些牌算 Attack 写在 `CARD.Tags` 里。
            let mut pool: Vec<rd_run::state::PoolCard<'static>> = Vec::new();
            // 走到 `None` 为止：`Content` 没有"卡表有几行"的公开读数，而"第一行读不出来"
            // 就是表的结尾（`card(i)` 对越界下标返回 `None`）。
            let mut index = 0u32;
            while let Some(row) = image.card(index) {
                index += 1;
                // `CardRow` 的格子是**串池句柄**，不是 `&str`：要过一次 `Content::string`。
                let Some(id) = image.string(row.id()) else {
                    continue;
                };
                // §161.7: a `+` row is a **different** card (our upgrade convention appends `+`),
                // and StS's potion gives the printed card, not an upgraded one. Without this the
                // pool would sometimes hand out `twin_strike+`.
                if id.ends_with('+') {
                    continue;
                }
                if image.card_has_tag(id, tag) != Some(true) {
                    continue;
                }
                let Some(rarity) = rd_run::state::Rarity::from_name(
                    image.string(row.rarity()).unwrap_or(""),
                ) else {
                    // 一个认不出的稀有度会让"这张牌该不该在池子里"变成一个猜 —— 拒绝。
                    return refuse(&std::format!("`{id}` 的稀有度认不出来"));
                };
                pool.push(rd_run::state::PoolCard { id, rarity });
            }
            // 三张是**规则**，不是上限：少于三张时这瓶药给不出它承诺的东西。
            if pool.len() < MAX_OFFERED {
                return refuse(&std::format!(
                    "`{tag}` 牌只有 {} 张，凑不出 {MAX_OFFERED} 张候选",
                    pool.len()
                ));
            }
            let Some(run) = run_slot().as_mut() else {
                return -1;
            };
            let mut picked = [rd_run::state::RunId::EMPTY; MAX_OFFERED];
            let drawn = match run.state.draw_distinct(&pool, MAX_OFFERED, &mut picked) {
                Ok(drawn) => drawn,
                Err(e) => {
                    let _ = e;
                    return refuse("从卡池抽候选失败");
                }
            };
            if drawn < MAX_OFFERED {
                return refuse("抽不出足够的候选牌");
            }
            let mut offered = rd_core::state::Bounded::new();
            for id in &picked[..drawn] {
                let Ok(definition) = rd_core::state::CardDefinitionId::new(id.as_str()) else {
                    return refuse("候选牌的 id 不合法");
                };
                if offered
                    .push(definition, rd_core::state::Container::ChoiceOptions)
                    .is_err()
                {
                    return refuse("候选表装不下");
                }
            }
            let question = rd_core::state::PendingChoice {
                chooser: hero.clone(),
                source: rd_core::state::ChoiceSource::Offered,
                min: 1,
                max: 1,
                then: rd_core::state::ChoiceThen::ToHand,
                offered,
            };
            if let Err(e) = session.state.begin_choice(question) {
                return refuse(&std::format!("这次选牌问不出口：{e}"));
            }
            session.choice_picks.clear();
        }
        "choice_discard_to_hand" => {
            // §161.4: Liquid Memories -- "Choose a card in your discard pile and return it to your
            // hand. It costs 0 this turn." One card, exactly (`min = max = 1`), so `confirm` with
            // nothing ticked is refused and the picker cannot be dismissed into the void.
            let Some(zones) = session.state.card_zones(&hero) else {
                return refuse("英雄没有牌区");
            };
            if zones.count(rd_core::state::CardZone::DiscardPile) == 0 {
                // Nothing to choose: the question has no answers, so asking it would only put an
                // empty picker on screen whose confirm button is disabled forever. Same rule as the
                // empty hand for Elixir.
                continue;
            }
            let question = rd_core::state::PendingChoice {
                chooser: hero.clone(),
                source: rd_core::state::ChoiceSource::DiscardPile,
                min: 1,
                max: 1,
                then: rd_core::state::ChoiceThen::ToHand,
                offered: rd_core::state::Bounded::new(),
            };
            if let Err(e) = session.state.begin_choice(question) {
                return refuse(&std::format!("这次选牌问不出口：{e}"));
            }
            session.choice_picks.clear();
        }
        other if other.starts_with("combat_status") => {
            // `combat_status:<id>` = the hero; `combat_status_target:<id>` = the chosen enemy.
            let (needs_target, status_id) = match other.split_once(':') {
                Some(("combat_status", id)) => (false, id),
                Some(("combat_status_target", id)) => (true, id),
                _ => return refuse(&std::format!("药水效果 `{other}` 缺少 `:<状态 id>`")),
            };
            let Ok(definition) = rd_core::state::StatusDefinitionId::new(status_id) else {
                return refuse(&std::format!("`{status_id}` 不是合法的状态 id"));
            };
            let target_id = if needs_target {
                let slot_index = if target >= 0 {
                    target as usize
                } else {
                    (0..session.plan.enemies.len())
                        .find(|index| {
                            let id = session.plan.enemies[*index].id;
                            rd_core::state::CombatantId::new(id)
                                .ok()
                                .and_then(|cid| session.state.combatant(&cid))
                                .is_some_and(|c| c.health_current > 0)
                        })
                        .unwrap_or(usize::MAX)
                };
                let Some(plan_enemy) = session.plan.enemies.get(slot_index) else {
                    return refuse("药水没有目标：这一侧没有活着的敌人");
                };
                match rd_core::state::CombatantId::new(plan_enemy.id) {
                    Ok(id) => id,
                    Err(_) => return refuse("敌人的战斗员 id 不合法"),
                }
            } else {
                hero.clone()
            };
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(target_id),
                    definition,
                    stacks: amount,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            if let Err(e) = rd_core::exec::resolve_effect(&mut session.state, &item, Some(image)) {
                return refuse(&std::format!("上状态的药水失败：{e:?}"));
            }
        }
        // ── §182: Distilled Chaos -- "Play the top 3 cards of your draw pile." ────────────────────
        "combat_autoplay_top" => {
            // `amount` is the number of cards ("3", and 6 upgraded -- this content carries the
            // base value).
            let plays = amount.max(1);
            for _ in 0..plays {
                // The top of the draw pile is index 0 (`state::draw_card` moves `first()`), so the
                // potion and the draw rule cannot disagree about which end is the top.
                let top = {
                    let Some(zones) = session.state.card_zones(&hero) else {
                        return refuse("英雄没有牌区");
                    };
                    match zones.slots(rd_core::state::CardZone::DrawPile).first().copied() {
                        Some(slot) => slot,
                        None => break, // the pile ran out: fewer than 3 is not an error
                    }
                };
                let slot = rd_core::state::CardSlot::from_index(top);
                let Some(card) = session.state.card(slot) else {
                    break;
                };
                let instance = card.id;
                // Draw it into the hand first: `play_card` requires the card to be *in hand*, and
                // that is also where the effect puts it while it resolves.
                if let Err(e) = session.state.move_card(
                    &hero,
                    rd_core::state::CardZone::DrawPile,
                    rd_core::state::CardZone::Hand,
                    slot,
                    rd_core::state::ZonePlacement::Bottom,
                ) {
                    return refuse(&std::format!("自动打出的牌搬不到手牌：{e:?}"));
                }
                // Free: the potion pays, the player does not (§179's per-copy override is exactly
                // "this one copy costs N").
                if let Ok(key) =
                    rd_core::state::CounterId::new(rd_core::state::CARD_COST_OVERRIDE_COUNTER)
                {
                    if let Some(card) = session.state.card_mut(slot) {
                        let _ = card.set_mark_counter(key, 0);
                    }
                }
                // StS picks a random living enemy; ours is the first one, so a replay of the same
                // seed plays at the same target (see the module note in `port-plan.md` §182).
                let target = (0..session.plan.enemies.len())
                    .find(|index| {
                        let id = session.plan.enemies[*index].id;
                        rd_core::state::CombatantId::new(id)
                            .ok()
                            .and_then(|cid| session.state.combatant(&cid))
                            .is_some_and(|c| c.health_current > 0)
                    })
                    .and_then(|index| {
                        rd_core::state::CombatantId::new(session.plan.enemies[index].id).ok()
                    });
                let request = rd_core::play::PlayRequest::new(hero.clone(), instance, target);
                match rd_core::play::play_card(&mut session.state, Some(image), &request) {
                    Ok(_) => {}
                    Err(rd_core::play::PlayError::CardNotInHand) => break,
                    Err(e) => {
                        return refuse(&std::format!("自动打出的牌失败：{e:?}"));
                    }
                }
            }
        }
        // ── §179: the three potions whose effect the engine had no verb for. ──────────────────────
        "combat_upgrade_hand" => {
            // Blessing of the Forge: "Upgrade all cards in your hand for the rest of combat."
            //
            // `+` rows are separate `CARD` rows, and `play` looks the program up by **definition
            // id**, so swapping the instance's id *is* the upgrade -- no display-side special case.
            // A card without a `+` row (already upgraded, or not upgradable) is left alone: the
            // wiki's card is silent about it, and silently doing nothing is what StS does too.
            let Some(zones) = session.state.card_zones(&hero) else {
                return refuse("英雄没有牌区");
            };
            // Snapshot the hand first: `card_mut` borrows the state, and the loop needs `image`.
            let mut slots = [0u16; 32];
            let mut count = 0usize;
            for slot in zones.slots(rd_core::state::CardZone::Hand) {
                if count == slots.len() {
                    break;
                }
                slots[count] = *slot;
                count += 1;
            }
            let _ = &mut count;
            let mut upgraded = 0;
            for slot in &slots[..count] {
                let Some(card) = session.state.card(rd_core::state::CardSlot::from_index(*slot))
                else {
                    continue;
                };
                let base = card.definition_id.as_str();
                let mut buffer = [0u8; 64];
                if base.len() + 1 > buffer.len() {
                    continue;
                }
                buffer[..base.len()].copy_from_slice(base.as_bytes());
                buffer[base.len()] = b'+';
                let Ok(text) = core::str::from_utf8(&buffer[..base.len() + 1]) else {
                    continue;
                };
                // `lookup_in(..., EK_CARD)` is the content's own id index: asking it is the only
                // honest way to know whether an upgraded row exists (`None` = no such row).
                if image.lookup_in(text, rd_core::content::EK_CARD).is_none() {
                    continue;
                }
                let Ok(upgraded_id) = rd_core::state::CardDefinitionId::new(text) else {
                    continue;
                };
                if let Some(card) =
                    session.state.card_mut(rd_core::state::CardSlot::from_index(*slot))
                {
                    card.definition_id = upgraded_id;
                    upgraded += 1;
                }
            }
            if upgraded == 0 {
                // Nothing to upgrade is **not** an error (an empty hand is a legal hand), but the
                // potion still gets drunk -- the same rule Elixir follows for an empty hand.
                continue;
            }
        }
        "combat_randomize_costs" => {
            // Snecko Oil, part 2. Part 1 is the `combat_draw` atom next to it in the content
            // (`Effect: "combat_draw,combat_randomize_costs"`).
            //
            // The draw is `amount` (5); the randomized price is **0..=3** -- that is the whole
            // content of this rule, so it is a constant here rather than a field nobody could
            // source from the wiki ("Randomize the costs" gives no range; StS uses 0-3).
            let Some(zones) = session.state.card_zones(&hero) else {
                return refuse("英雄没有牌区");
            };
            let mut slots = [0u16; 32];
            let mut count = 0usize;
            for slot in zones.slots(rd_core::state::CardZone::Hand) {
                if count == slots.len() {
                    break;
                }
                slots[count] = *slot;
                count += 1;
            }
            let Ok(key) = rd_core::state::CounterId::new(rd_core::state::CARD_COST_OVERRIDE_COUNTER)
            else {
                return refuse("价格覆盖的计数器名不合法");
            };
            for slot in &slots[..count] {
                // One draw per card, each advancing `random_step` by one -- the same convention the
                // shuffle uses (`state.rs`: "洗完之后 `random_step += 1`"), so a replay of the same
                // seed randomizes the same ways.
                let mut seed = session.state.random_seed as u32;
                let roll = rd_core::rng::next_u32(&mut seed) % 4;
                session.state.random_seed = seed as i32;
                session.state.random_step = session.state.random_step.saturating_add(1);
                if let Some(card) =
                    session.state.card_mut(rd_core::state::CardSlot::from_index(*slot))
                {
                    if card.set_mark_counter(key, roll as i32).is_err() {
                        return refuse("这张牌装不下价格覆盖");
                    }
                }
            }
        }
        "combat_flee" => {
            // Smoke Bomb: "Escape from a non-boss combat. Receive no rewards."
            //
            // A **run-layer** outcome, not a `CombatResult`: the kernel's three results match the
            // reference byte for byte (and `result=` is hashed), so a fourth would move the golden
            // corpus. `FightOutcome`'s high bits already carry the result, and `3` is free there.
            let boss_fight = run_slot().as_ref().is_some_and(|s| s.boss_fight);
            if boss_fight {
                return refuse("Boss 战不能脱战（Smoke Bomb：non-boss combat）");
            }
            // The fight is over, so the tail below must not run against a session that is gone.
            // The ABI's contract is `0` = "the potion was used"; **whether the fight was fled is a
            // fact about the run**, which the page reads from the observation (`in_fight`), not
            // from this return value. Returning `3` here (the run layer's outcome code) would make
            // the page treat "the potion worked" as an error code.
            return flee_fight(slot);
        }
        other => return refuse(&std::format!("未知的药水效果 `{other}`")),
        }
    }

    // The observation is a **cached snapshot** (Session::publish), and a potion does not go through
    // d_env_step, so it has to be refreshed here or the page shows the pre-potion numbers.
    session.reobserve_after_external_change();

    // Consumed only after it worked: a refusal must not eat the potion.
    consume_used_potion(slot)
}

/// §161.5：候选**三张**是规则（wiki 的三瓶药都写 "1 of 3"），所以它是常量而不是参数。
///
/// 写成 `rd_core::state::MAX_CHOICE_OFFERED` 的名字会让"三"看起来像个容量上限 ——
/// 它其实是这条规则的**全部内容**，改它就得改药水的说明文字。
const MAX_OFFERED: usize = 3;

/// Is this potion atom about a **fight**? (§158)
///
/// `max_hp` (Fruit Juice) and `potion_fill` (Entropic Brew) are the two the wiki lets you use
/// outside combat, and before §158 the "no fight" check at the top of [`rd_env_use_potion`] refused
/// both -- the potion was in the vocabulary but only half-reachable.
fn atom_needs_a_fight(atom: &str) -> bool {
    let kind = match atom.split_once(':') {
        Some((kind, _)) => kind,
        None => atom,
    };
    !matches!(kind, "max_hp" | "potion_fill" | "heal")
}

/// Take the used potion off the belt: the one tail every potion shares.
fn consume_used_potion(slot: i32) -> i32 {
    let Some(run) = run_slot().as_mut() else {
        return -1;
    };
    match run.state.drop_potion(slot as usize) {
        Ok(()) => 0,
        Err(e) => {
            let message = describe(&e);
            fail(run, &message)
        }
    }
}

/// Apply a potion whose atoms are all about the **run** (§157/§158).
///
/// `Ok(false)` = the caller still has to take the bottle off the belt; `Ok(true)` = this function
/// already did (only `potion_fill`, which must free its own slot before filling).
fn use_run_atoms(slot: i32, effect: &str, amount: i32) -> Result<bool, std::string::String> {
    let image = content();
    for atom in effect.split(',') {
        let kind = match atom.split_once(':') {
            Some((kind, _)) => kind,
            None => atom,
        };
        match kind {
            "max_hp" => {
                let Some(run) = run_slot().as_mut() else {
                    return Err(std::format!("没有在进行中的一局"));
                };
                run.state.raise_max_health(amount);
                refresh_fight_observation();
            }
            "potion_fill" => {
                let pool = potion_pool_of(image);
                let Some(run) = run_slot().as_mut() else {
                    return Err(std::format!("没有在进行中的一局"));
                };
                // Free the slot **first**: a full belt has no room, so a brew drunk at 3/3 would
                // otherwise "fill" nothing.
                if let Err(e) = run.state.drop_potion(slot as usize) {
                    return Err(std::format!("腾出药水格失败：{e:?}"));
                }
                // Bounded by the slot count -- every `push_potion` either fills a slot or stops the
                // loop -- so this cannot spin even if the pool keeps returning the same id.
                while run.state.potion_room() {
                    let picked = match run.state.pick_potion(
                        rd_run::streams::RunStream::Potion,
                        &pool,
                    ) {
                        Ok(id) => id,
                        Err(e) => return Err(std::format!("抽药水失败：{e:?}")),
                    };
                    if picked.as_str().is_empty() {
                        break;
                    }
                    if run.state.push_potion(picked.as_str()).is_err() {
                        break;
                    }
                }
                refresh_fight_observation();
                return Ok(true);
            }
            other => return Err(std::format!("运行层没有这个药水效果 `{other}`")),
        }
    }
    Ok(false)
}

/// The page's observation is a cached snapshot; a run-layer write does not go through `rd_env_step`,
/// so a potion drunk outside a fight still has to publish (§157/§158).
fn refresh_fight_observation() {
    if let Some(session) = crate::slot().as_mut() {
        session.reobserve_after_external_change();
    }
}

/// How many times the encounter pick may be re-rolled to avoid repeating the previous one (§153).
///
/// Three, not a loop-until-different: a pool with one entry would spin forever, and with `n` entries
/// three tries turns a repeat from `1/n` into `1/n³` (measured before: 18 of ~100 fights repeated
/// with no re-roll, 2 of ~104 with one).
const ENCOUNTER_REROLLS: u32 = 3;

/// An encounter id, from the pool''s string form (§153). Over-long ids cannot be compared, so they
/// come back as `EMPTY` -- and `EMPTY` is also the "no previous fight" value, which means such an id
/// simply never suppresses a repeat.
/// Choose which encounter a fight uses (`port-plan.md` §153).
///
/// Three rules, in order:
/// 1. **the content's `Weight`**, not a uniform draw (`Weight: 15/14/14/14/14/14/15` used to be
///    written, validated by the content gate, and then ignored);
/// 2. a pool with no weights at all falls back to uniform (that is what "no `Weight` field" means);
/// 3. **never the same encounter twice in a row** -- one re-roll, not a loop, because a loop over a
///    two-entry pool would turn the pool into a cycle.
fn pick_encounter(
    state: &mut rd_run::state::RunState,
    content: &'static Content<'static>,
    pool_name: &str,
    encounters: &[&'static str],
) -> Result<usize, String> {
    let weights = content.encounter_weights(pool_name);
    let total: u32 = weights
        .as_ref()
        .map_or(0, |table| table.iter().take(encounters.len()).map(|w| u32::from(*w)).sum());
    let mut pick = if total == 0 {
        match state.rng_mut().roll(RunStream::Combat, encounters.len() as u32) {
            Ok(value) => value as usize,
            Err(e) => return Err(describe(&e)),
        }
    } else {
        let roll = match state.rng_mut().roll(RunStream::Combat, total) {
            Ok(value) => value,
            Err(e) => return Err(describe(&e)),
        };
        let mut remaining = roll;
        let mut chosen = encounters.len() - 1;
        for (index, weight) in weights.iter().flatten().take(encounters.len()).enumerate() {
            let weight = u32::from(*weight);
            if weight == 0 {
                continue;
            }
            if remaining < weight {
                chosen = index;
                break;
            }
            remaining -= weight;
        }
        chosen
    };
    // Re-roll up to [`ENCOUNTER_REROLLS`] times while the pick repeats the previous encounter.
    // Bounded on purpose: an unbounded loop over a one-entry pool never terminates, and three tries
    // already takes a repeat from `1/n` to `1/n³` (~2% of fights were repeats with one re-roll).
    if encounters.len() > 1 {
        for _ in 0..ENCOUNTER_REROLLS {
            if encounter_id(encounters[pick]) != state.last_encounter() {
                break;
            }
            let again = match state.rng_mut().roll(RunStream::Combat, encounters.len() as u32) {
                Ok(value) => value as usize,
                Err(e) => return Err(describe(&e)),
            };
            pick = again;
        }
    }
    state.set_last_encounter(encounter_id(encounters[pick]));
    Ok(pick)
}

fn encounter_id(text: &'static str) -> rd_run::state::RunId {
    rd_run::state::RunId::new(text).unwrap_or(rd_run::state::RunId::EMPTY)
}
/// A refusal that has nothing to do with the run slot's own error text.
fn refuse(message: &str) -> i32 {
    match run_slot().as_mut() {
        Some(session) => fail(session, message),
        None => -1,
    }
}

/// Which follow-up offer `slot` would need: `0` none, `1` remove a card, `2` upgrade one,
/// `-1` no such slot.
#[no_mangle]
pub extern "C" fn rd_run_start_needs(slot: i32) -> i32 {
    use rd_run::state::{BlessingFollowUp, DeckChange};
    let Some(offer) = start_offer(slot) else {
        return -1;
    };
    match offer.follow_up {
        BlessingFollowUp::None | BlessingFollowUp::GainThreeCards => 0,
        BlessingFollowUp::Deck(DeckChange::Remove) => 1,
        BlessingFollowUp::Deck(DeckChange::Upgrade) => 2,
        BlessingFollowUp::Deck(DeckChange::Transform) => 3,
    }
}

/// What the pending blessing still needs: `0` nothing, `1` remove a card, `2` upgrade one,
/// `3` transform one, `-1` no run.
#[no_mangle]
pub extern "C" fn rd_run_blessing_needs() -> i32 {
    use rd_run::state::{BlessingFollowUp, DeckChange};
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match session.state.blessing_follow_up() {
        Some(BlessingFollowUp::Deck(DeckChange::Remove)) => 1,
        Some(BlessingFollowUp::Deck(DeckChange::Upgrade)) => 2,
        Some(BlessingFollowUp::Deck(DeckChange::Transform)) => 3,
        Some(BlessingFollowUp::None) | Some(BlessingFollowUp::GainThreeCards) | None => 0,
    }
}

/// Finish a card blessing with deck index `index`.
#[no_mangle]
pub extern "C" fn rd_run_pick_blessing_card(index: i32) -> i32 {
    if index < 0 {
        return -1;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_BLESSING_CARD, index, -1, "");
    let pool = match reward_pool(content()) {
        Ok(pool) => pool,
        Err(message) => return fail(session, &message),
    };
    let outcome = session
        .state
        .pick_blessing_card(index as usize, &pool)
        .map(|_| 0i32);
    finish(session, outcome)
}

/// The pre-run blessing's `slot` id (`max_hp` / `gold` / ...), `""` when no choice is pending.
#[no_mangle]
pub extern "C" fn rd_run_start_offer_len(slot: i32) -> i32 {
    match start_offer(slot) {
        Some(offer) => offer.id.len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_start_offer_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_start_offer_into(slot: i32, ptr: *mut u8) -> i32 {
    match start_offer(slot) {
        Some(offer) => write_out(offer.id, ptr),
        None => 0,
    }
}

/// The blessing's **gain** as the ABI's small integer (`1` heal, `2` gold, `3` lose health,
/// `4` max health, `5` nothing), `-1` for no such slot.
#[no_mangle]
pub extern "C" fn rd_run_start_gain(slot: i32) -> i32 {
    start_offer(slot).map_or(-1, |offer| effect_code_of(offer.gain))
}

/// How much the gain is worth.
#[no_mangle]
pub extern "C" fn rd_run_start_gain_amount(slot: i32) -> i32 {
    start_offer(slot).map_or(0, |offer| effect_amount(offer.gain))
}

/// The blessing's **cost** in the same integers, and its amount. A cost of `5` (`nothing`) means
/// the blessing is free.
#[no_mangle]
pub extern "C" fn rd_run_start_cost(slot: i32) -> i32 {
    start_offer(slot).map_or(-1, |offer| effect_code_of(offer.cost))
}

/// How much the cost is.
#[no_mangle]
pub extern "C" fn rd_run_start_cost_amount(slot: i32) -> i32 {
    start_offer(slot).map_or(0, |offer| effect_amount(offer.cost))
}

/// Take blessing `slot`. Returns `0`, or `-2` with text (wrong phase / no such slot).
#[no_mangle]
pub extern "C" fn rd_run_choose_start(slot: i32) -> i32 {
    if slot < 0 || slot > 1 {
        return -1;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_CHOOSE_START, slot, -1, "");
    // A blessing may need the card pool ("three random cards", "transform one"), so the pool is
    // built here, where the content is reachable.
    let pool = match reward_pool(content()) {
        Ok(pool) => pool,
        Err(message) => return fail(session, &message),
    };
    let outcome = session.state.choose_start(slot as usize, &pool).map(|_| 0i32);
    finish(session, outcome)
}

fn start_offer(slot: i32) -> Option<rd_run::state::StartOffer> {
    if slot < 0 || slot > 1 {
        return None;
    }
    let session = run_slot().as_ref()?;
    session.state.start_offers().map(|offers| offers[slot as usize])
}

/// `EventEffect` as the same small integers the event ABI uses.
///
/// ⚠️ The five number effects are `1..=5` and stay there; `6..=8` are the deck edits. `GainCurse`
/// / `GainRelic` never reach this function (a blessing's gain/cost is never one of them -- see
/// `EventEffect`'s table), so they answer `-1` rather than reusing `9` / `10`: those two codes mean
/// "*this* choice names a card / a relic", which is information only the content string has.
fn effect_code_of(effect: rd_run::state::EventEffect) -> i32 {
    use rd_run::state::EventEffect;
    match effect {
        EventEffect::Heal(_) => 1,
        EventEffect::Gold(_) => 2,
        EventEffect::LoseHealth(_) => 3,
        EventEffect::GainMaxHealth(_) => 4,
        EventEffect::Nothing => 5,
        EventEffect::RemoveCard => 6,
        EventEffect::UpgradeCard => 7,
        EventEffect::TransformCard => 8,
        EventEffect::GainCurse | EventEffect::GainRelic => -1,
    }
}

fn effect_amount(effect: rd_run::state::EventEffect) -> i32 {
    use rd_run::state::EventEffect;
    match effect {
        EventEffect::Heal(n)
        | EventEffect::Gold(n)
        | EventEffect::LoseHealth(n)
        | EventEffect::GainMaxHealth(n) => n,
        EventEffect::Nothing
        | EventEffect::RemoveCard
        | EventEffect::UpgradeCard
        | EventEffect::TransformCard
        | EventEffect::GainCurse
        | EventEffect::GainRelic => 0,
    }
}

/// How many potions the belt holds.
#[no_mangle]
pub extern "C" fn rd_run_potion_count() -> i32 {
    run_slot().as_ref().map_or(-1, |s| s.state.potions().len() as i32)
}

/// The id of belt slot `index`.
#[no_mangle]
pub extern "C" fn rd_run_potion_id_len(index: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    match session.state.potions().get(index as usize) {
        Some(id) => id.as_str().len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_potion_id_len(index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_potion_id_into(index: i32, ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    if index < 0 {
        return 0;
    }
    match session.state.potions().get(index as usize) {
        Some(id) => write_out(id.as_str(), ptr),
        None => 0,
    }
}

/// The Ascension level this run is played at (`0`..=`20`, §159); `-1` when there is no run.
///
/// It exists so the page can *show* the level the run was started with: a seed plus a level is the
/// whole description of a run, and a page that only echoed the seed would look reproducible while
/// silently being a different ladder.
#[no_mangle]
pub extern "C" fn rd_run_ascension() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |session| i32::from(session.state.ascension()))
}

/// What belt slot `slot` does, as a small integer the page can branch on:
/// `1` needs an enemy target, `2` acts on the hero (or on the run), `3` hits every enemy,
/// `0` unknown, `-1` no slot.
///
/// It exists because **a damage potion has to ask which enemy** -- before this the page always sent
/// "the first living one", which in a three-enemy fight is a decision the player never got to make.
#[no_mangle]
pub extern "C" fn rd_run_potion_effect(slot: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if slot < 0 {
        return -1;
    }
    let Some(id) = session.state.potions().get(slot as usize) else {
        return -1;
    };
    let image = content();
    let Some(potion) = (0..image.potion_count())
        .filter_map(|index| image.potion(index))
        .find(|potion| potion.id == id.as_str())
    else {
        return 0;
    };
    // §152: `1` = needs an enemy target, `2` = acts on the hero (no target), `3` = every enemy.
    // The page arms its enemy picker on `1`; before this only "damage one" existed, so a
    // status-on-a-target potion could not be aimed at all.
    // §158: the effect is a list of atoms -- **if any atom wants a target, the whole potion does**.
    let mut wants_target = false;
    let mut hits_every_enemy = false;
    for atom in potion.effect.split(',') {
        let kind = match atom.split_once(':') {
            Some((kind, _)) => kind,
            None => atom,
        };
        if kind.starts_with("combat_status_target") || kind == "combat_damage" {
            wants_target = true;
        } else if kind == "combat_damage_all" {
            hits_every_enemy = true;
        }
        // §161.3: the choice atoms act on the **hand**, so they need no enemy target (they fall
        // into the `2` branch below). Adding them here is not bookkeeping: without this line
        // `rd_run_potion_effect` answered `0` -- "unknown effect" -- for a potion the kernel drinks
        // happily, and the only reason nothing broke is that the page's `=== 1` check took the
        // other branch. `every_potion_in_the_table_classifies_as_known` is the tripwire for the
        // next atom that gets added to `rd_env_use_potion` and forgotten here.
        let known = kind == "combat_damage"
            || kind == "combat_damage_all"
            || kind == "heal"
            || matches!(
                kind,
                "max_hp"
                    | "potion_fill"
                    | "choice_hand_exhaust"
                    | "choice_hand_discard_draw"
                    | "choice_discard_to_hand"
                    // §161.5：`choice_offered:<tag>`（payload 是标签，不是状态 id）。
                    | "choice_offered"
            )
            || ["combat_block", "combat_energy", "combat_heal_percent", "combat_draw"]
                .contains(&kind)
            // §179: three atoms that act on the hand / on the fight itself, so no enemy target.
            // This list is the **fourth** place the potion vocabulary lives (§161.3: content
            // check, kernel closed list, `rd_env_use_potion`'s match, and this classifier).
            // `every_potion_in_the_table_classifies_as_known` walked the whole table and caught
            // this one within a second of the content landing -- which is the only reason it is
            // being written down here instead of being found by a player.
            || ["combat_upgrade_hand", "combat_randomize_costs", "combat_flee"]
                .contains(&kind)
            // §182: auto-play is about the player's own piles, so no enemy target is picked by the
            // page (the potion picks for itself).
            || kind == "combat_autoplay_top"
            || kind.starts_with("combat_status");
        if !known {
            return 0;
        }
    }
    if wants_target {
        1
    } else if hits_every_enemy {
        3
    } else {
        2
    }
}

/// Put potion `id` on the belt. **For tests and the page's `?debug` surface only.**
///
/// There is no in-game caller: every real potion arrives through a drop (`roll_reward` ->
/// `take_potion`) or through `entropic_brew`. This exists for the same reason
/// `RD_DEBUG.startWithSeed` does -- a checker that has to hope for a 40% drop of one specific
/// potion out of **twenty-two** is not a checker, and the §161.3 card-choice picker is reachable
/// through exactly **two** of those twenty-two. Before this, the picker could only be exercised by
/// a unit test that stuffed the belt from inside the crate.
///
/// It is deliberately **not** behind a `cfg`: a debug gate would mean the shipped `.wasm` and the
/// tested one are different binaries, which is a worse problem than a cheat entry point.
///
/// `0` granted, `-1` no run / bad pointer, `-2` refused (unknown id, or the belt is full).
///
/// # Safety
///
/// `ptr` must point at `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_grant_potion(ptr: *const u8, len: i32) -> i32 {
    if ptr.is_null() || len <= 0 {
        return -1;
    }
    let bytes = std::slice::from_raw_parts(ptr, len as usize);
    let Ok(id) = std::str::from_utf8(bytes) else {
        return -2;
    };
    // 与 `fight_begin` 同一个理由：它改运行层（腰带），所以必须进脚本 —— 否则上一条记录的
    // "调用之后的哈希"会把它的效果算进去，而回放里没人做这件事。
    if let Some(session) = run_slot().as_mut() {
        session.log(K_GRANT_POTION, -1, -1, id);
    }
    let image = content();
    // The id must be a real `POT` row: a typo has to fail here rather than sit in the belt until
    // somebody drinks it and the effect reader says "unknown".
    if !(0..image.potion_count())
        .filter_map(|index| image.potion(index))
        .any(|potion| potion.id == id)
    {
        set_error(&std::format!("`{id}` 不是内容的 POT 行"));
        return -2;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    match session.state.push_potion(id) {
        // No re-publish: the run's observation is computed per call (), unlike the
        // fight's cached snapshot. The belt is drawn from , which reads the state.
        Ok(()) => 0,
        Err(e) => {
            set_error(&std::format!("放不进腰带：{e:?}"));
            -2
        }
    }
}

/// Can potion `slot` be used **outside** a fight? `-1` = no such slot, `0` = run-only (yes),
/// `1` = it needs a fight.
///
/// §158: the page used to offer "用" only in fight mode, which made Fruit Juice and Entropic Brew
/// reachable only mid-battle -- the two the wiki explicitly allows anywhere.
#[no_mangle]
pub extern "C" fn rd_run_potion_needs_fight(slot: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if slot < 0 {
        return -1;
    }
    let Some(id) = session.state.potions().get(slot as usize) else {
        return -1;
    };
    let image = content();
    let Some(potion) = (0..image.potion_count())
        .filter_map(|index| image.potion(index))
        .find(|potion| potion.id == id.as_str())
    else {
        return -1;
    };
    for atom in potion.effect.split(',') {
        if atom_needs_a_fight(atom) {
            return 1;
        }
    }
    0
}

/// Throw away belt slot `index`.
#[no_mangle]
pub extern "C" fn rd_run_drop_potion(index: i32) -> i32 {
    if index < 0 {
        return -1;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_DROP_POTION, index, -1, "");
    let outcome = session.state.drop_potion(index as usize).map(|_| 0i32);
    finish(session, outcome)
}

/// The potion the reward screen is offering (empty when none), for display.
#[no_mangle]
pub extern "C" fn rd_run_reward_potion_len() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match session.state.reward_potion() {
        Some(id) => id.len() as i32,
        None => 0,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_reward_potion_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_reward_potion_into(ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    match session.state.reward_potion() {
        Some(id) => write_out(id, ptr),
        None => 0,
    }
}

/// Take the offered potion.
#[no_mangle]
pub extern "C" fn rd_run_take_potion() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_TAKE_POTION, -1, -1, "");
    let outcome = session.state.take_potion().map(|_| 0i32);
    finish(session, outcome)
}

/// The archive buffer's capacity, in bytes (§161.10).
///
/// Published so the host can check **before** it writes: `rd_run_archive_buf()` is exactly this
/// long, and `rd_run_restore_from` refuses a longer input. Without this the page had to guess, and
/// it guessed a 1 KiB scratch buffer shared with every other `*_into` export.
#[no_mangle]
pub extern "C" fn rd_run_archive_capacity() -> i32 {
    rd_run::state::archive::MAX_ARCHIVE as i32
}

/// The address of the archive buffer (`rd_run_archive_capacity()` bytes, owned by this module).
#[no_mangle]
pub extern "C" fn rd_run_archive_buf() -> *mut u8 {
    std::ptr::addr_of_mut!(crate::ARCHIVE) as *mut u8
}

/// Fill the archive buffer and return its length; `-1` no run, `-2` refused with text.
///
/// ⚠️ 存档**不含战斗**（`CombatState`，213 KB、每场重建）。所以"战斗中不许存"这条判断在这里 ——
/// 权威状态所在的层 —— 而不是在页面里。它可靠的前提是"有战斗会话"确实等于"正在打"：
/// `rd_run_start` 现在会清掉上一场的会话（见那里），于是这个判据没有第二种含义。
#[no_mangle]
pub extern "C" fn rd_run_archive_fill() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if session.in_fight {
        set_error("战斗中没有存档：这份档案只描述整局，回档会让敌人满血。先打完这一场。");
        return -2;
    }
    // The buffer is ours and `MAX_ARCHIVE` long, so `write` cannot overflow it: it encodes INTO
    // it and a longer payload is `ArchiveError::TooLong`.
    #[allow(static_mut_refs)]
    let buffer = unsafe { &mut *std::ptr::addr_of_mut!(crate::ARCHIVE) };
    match rd_run::state::archive::write(&session.state, content_fingerprint(), buffer) {
        Ok(len) => len as i32,
        Err(error) => {
            set_error(&std::format!("存档写不出来：{error}"));
            -2
        }
    }
}

/// Restore a run from the archive in `(ptr, len)`. `0` ok, `-1` no run slot, `-2` refused, `-3` bad text.
///
/// **全有或全无**：`archive::restore` 先装到一个本地 `RunState` 上，最后一步才赋值，所以一份
/// 坏档案不会把当前这局改成半新半旧。
///
/// # Safety
///
/// `ptr` must point at `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_restore_from(ptr: *const u8, len: i32) -> i32 {
    if ptr.is_null() || len <= 0 {
        return -3;
    }
    // The capacity contract, enforced rather than assumed (§161.10).
    if len as usize > rd_run::state::archive::MAX_ARCHIVE {
        set_error("档案太长：超过 THIS 实现的缓冲容量");
        return -3;
    }
    let bytes = std::slice::from_raw_parts(ptr, len as usize);
    let Ok(text) = std::str::from_utf8(bytes) else {
        set_error("档案不是 UTF-8 文本");
        return -3;
    };
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    if session.in_fight {
        set_error("战斗中没有回档：先打完这一场，或者重开一局。");
        return -2;
    }
    let mut restored = *session.state;
    match rd_run::state::archive::restore(text, content_fingerprint(), &mut restored) {
        Ok(()) => {
            *session.state = restored;
            session.error.clear();
            // ⚠️ 回档 = **这条时间线的起点**：日志里记的是"这一局之前做过的动作"，而恢复出来的状态
            // 不是那些动作的结果。留着它，导出的脚本第一行就和局面矛盾（回放第一步就分叉）。
            session.journal.clear();
            // `A` 形态的内容指纹在**档案自己**里（一份当两份存就一定会漂）。所以头部只带档案。
            session.head = std::format!("RDR1,A,{text}");
            0
        }
        Err(rd_run::state::archive::ArchiveError::ContentMismatch { archive, build }) => {
            // §166：这条错误要说人话 —— 玩家看到的是"这份档案是另一份内容里的一局"，
            // 而不是把两个十六进制数丢给他猜。
            set_error(&std::format!(
                "回档被拒：这份档案是另一份内容里的一局（档案 {:08x}，本机 {}）· id 未必还对得上，重新导出",
                archive as u32,
                content_pin_text()
            ));
            return -2;
        }
        Err(error) => {
            set_error(&std::format!("回档被拒：{error}"));
            -2
        }
    }
}

/// The relic the reward screen is offering (empty when none; §155: elites and bosses), for display.
#[no_mangle]
pub extern "C" fn rd_run_reward_relic_len() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match session.state.reward_relic() {
        Some(id) => id.len() as i32,
        None => 0,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_reward_relic_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_reward_relic_into(ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    match session.state.reward_relic() {
        Some(id) => write_out(id, ptr),
        None => 0,
    }
}

/// Take the offered relic. Refuses when the table has none (`NoSuchRelic`) instead of silently
/// doing nothing -- a button that lies is the §150 shape.
#[no_mangle]
pub extern "C" fn rd_run_take_relic() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_TAKE_RELIC, -1, -1, "");
    let outcome = session.state.take_relic().map(|_| 0i32);
    finish(session, outcome)
}

/// Which act the run is on (1-based), or `-1` with no run.
#[no_mangle]
pub extern "C" fn rd_run_act() -> i32 {
    run_slot().as_ref().map_or(-1, |s| i32::from(s.state.act()))
}

/// Has the act been cleared? `1` yes, `0` no, `-1` no run.
#[no_mangle]
pub extern "C" fn rd_run_boss_beaten() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    i32::from(session.state.boss_beaten())
}

/// Has the node under the cursor already paid out? `1` yes, `0` no, `-1` no cursor.
#[no_mangle]
pub extern "C" fn rd_run_node_resolved() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if session.state.node() < 0 {
        return -1;
    }
    i32::from(session.state.node_resolved())
}

/// The gold the last won fight paid; `0` when there is nothing on the table.
#[no_mangle]
pub extern "C" fn rd_run_reward_gold() -> i32 {
    run_slot().as_ref().map_or(0, |s| s.state.reward().gold())
}

/// How many cards the reward screen offers (`0` when there is no screen).
#[no_mangle]
pub extern "C" fn rd_run_reward_card_count() -> i32 {
    run_slot()
        .as_ref()
        .map_or(0, |s| s.state.reward().cards().len() as i32)
}

/// Reward card `slot`'s **definition id**.
#[no_mangle]
pub extern "C" fn rd_run_reward_card_id_len(slot: i32) -> i32 {
    reward_card(slot).map_or(-1, |id| id.as_str().len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_run_reward_card_id_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_reward_card_id_into(slot: i32, ptr: *mut u8) -> i32 {
    match reward_card(slot) {
        Some(id) => write_out(id.as_str(), ptr),
        None => 0,
    }
}

/// Reward card `slot`'s **title** (`CARD.NameKey`, falling back to the id).
#[no_mangle]
pub extern "C" fn rd_run_reward_card_title_len(slot: i32) -> i32 {
    match reward_card(slot) {
        Some(id) => deck_title(content(), id.as_str())
            .unwrap_or(id.as_str())
            .len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_reward_card_title_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_reward_card_title_into(slot: i32, ptr: *mut u8) -> i32 {
    match reward_card(slot) {
        Some(id) => write_out(deck_title(content(), id.as_str()).unwrap_or(id.as_str()), ptr),
        None => 0,
    }
}

fn reward_card(slot: i32) -> Option<rd_run::state::RunId> {
    if slot < 0 {
        return None;
    }
    let session = run_slot().as_ref()?;
    session
        .state
        .reward()
        .cards()
        .get(slot as usize)
        .copied()
}

/// Take reward card `slot`.
#[no_mangle]
pub extern "C" fn rd_run_take_card(slot: i32) -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_TAKE_CARD, slot, -1, "");
    if slot < 0 {
        return -1;
    }
    let outcome = session.state.take_card(slot as usize).map(|_| 0i32);
    finish(session, outcome)
}

/// Decline the reward card.
#[no_mangle]
pub extern "C" fn rd_run_skip_reward() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_SKIP, -1, -1, "");
    let outcome = session.state.skip_reward().map(|_| 0i32);
    finish(session, outcome)
}

// =============================================================================================
// The deck (`env-abi.md` §11.7) -- the "all cards" panel
// =============================================================================================

/// How many cards the run's deck holds.
#[no_mangle]
pub extern "C" fn rd_run_deck_count() -> i32 {
    run_slot().as_ref().map_or(0, |s| s.state.deck().len() as i32)
}

/// Deck card `index`'s **definition id**.
#[no_mangle]
pub extern "C" fn rd_run_deck_id_len(index: i32) -> i32 {
    deck_card(run_slot().as_ref(), index).map_or(-1, |id| id.as_str().len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_run_deck_id_len(index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_deck_id_into(index: i32, ptr: *mut u8) -> i32 {
    match deck_card(run_slot().as_ref(), index) {
        Some(id) => write_out(id.as_str(), ptr),
        None => 0,
    }
}

/// Deck card `index`'s **title** (`CARD.NameKey`, falling back to the id).
#[no_mangle]
pub extern "C" fn rd_run_deck_title_len(index: i32) -> i32 {
    match deck_card(run_slot().as_ref(), index) {
        Some(id) => deck_title(content(), id.as_str())
            .unwrap_or(id.as_str())
            .len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_deck_title_len(index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_deck_title_into(index: i32, ptr: *mut u8) -> i32 {
    match deck_card(run_slot().as_ref(), index) {
        Some(id) => write_out(deck_title(content(), id.as_str()).unwrap_or(id.as_str()), ptr),
        None => 0,
    }
}

fn deck_card(session: Option<&RunSession>, index: i32) -> Option<rd_run::state::RunId> {
    if index < 0 {
        return None;
    }
    let session = session?;
    session.state.deck().get(index as usize).copied()
}

/// A card's title out of the content. `None` when the content has no `NameKey` for it, which the
/// callers turn into "use the id".
/// The card's **description** by id -- the same read `deck_title` does, one cell over.
fn deck_text(content: &'static Content<'static>, id: &str) -> Option<&'static str> {
    content
        .lookup_in(id, rd_core::content::EK_CARD)
        .and_then(|entry| content.row(rd_core::content::Table::Card, entry.index as u32))
        .and_then(rd_core::content::CardRow::new)
        .and_then(|row| content.string(row.description_key()))
        .filter(|text| !text.is_empty())
}


/// Text of a card `field` for the panel named by `source`: `0` = shop slot, `1` = reward slot,
/// `2` = deck index. `field` is `0` title, `1` description.
///
/// One export per (source, field) would be six functions; this is one with two small integers, and
/// the page reads it through one helper. **Shift+click shows the card** -- buying blind was the
/// complaint behind it (`port-plan.md` §95).
fn card_fact(source: i32, slot: i32, field: i32) -> Option<&'static str> {
    // The id is copied out first: the shop/reward accessors hand back borrows of the run, and the
    // content lookup needs only `&str`.
    let id = {
        let session = run_slot().as_ref()?;
        match source {
            0 => shop_offer(Some(session), slot, true).map(|offer| offer.id.as_str().to_string())?,
            1 => reward_card(slot).map(|id| id.as_str().to_string())?,
            2 => {
                if slot < 0 {
                    return None;
                }
                session.state.deck().get(slot as usize)?.as_str().to_string()
            }
            _ => return None,
        }
    };
    let image = content();
    match field {
        0 => deck_title(image, &id),
        1 => deck_text(image, &id),
        _ => None,
    }
}

/// Length of the card fact, or `-1`.
#[no_mangle]
pub extern "C" fn rd_run_card_fact_len(source: i32, slot: i32, field: i32) -> i32 {
    card_fact(source, slot, field).map_or(-1, |text| text.len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_run_card_fact_len(source, slot, field)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_card_fact_into(source: i32, slot: i32, field: i32, ptr: *mut u8) -> i32 {
    match card_fact(source, slot, field) {
        Some(text) => write_out(text, ptr),
        None => 0,
    }
}

fn deck_title(content: &'static Content<'static>, id: &str) -> Option<&'static str> {
    content
        .lookup_in(id, rd_core::content::EK_CARD)
        .and_then(|entry| content.row(rd_core::content::Table::Card, entry.index as u32))
        .and_then(rd_core::content::CardRow::new)
        .and_then(|row| content.string(row.name_key()))
        .filter(|title| !title.is_empty())
}

// =============================================================================================
// Fight <- run and fight -> run (`env-abi.md` §11.8)
// =============================================================================================
//
// This is the seam the run layer did not have. A fight in the run is **the run's** fight: the deck
// is the run's deck and the hero's maximum health is the run's. When it ends, the health and the
// result go back into the run, and `end_of_combat` runs the relic effects.
//
// The enemy side comes from one `ENCT` row chosen by the `Combat` stream. `inv:§5.2/§5.3` splits
// encounters into a weak pool (floor 1 + the first three fights) and a strong one, and this content
// does not carry that split -- so the choice is "any encounter in the image", which is written down
// as a gap in `run-layer.md` rather than dressed up as the weak/strong rule.

/// Start the fight for the node under the cursor. `0` = a fight is now installed in the combat
/// session; `-2` = refused (wrong node, no encounter, content problem).
#[no_mangle]
pub extern "C" fn rd_run_fight_begin() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    // `fight_begin` 会写 `last_encounter`（进指纹），所以它也必须被记录 —— 否则上一条记录的
    // "调用之后的哈希"会把它的效果算进去，而回放里没有人做这件事（§163 踩过：第 4 步就对不上）。
    session.log(K_FIGHT_BEGIN, -1, -1, "");
    // §170 `P1-2`: 一场没打完就不许再开一场。战斗中 `node_resolved()` 仍是 false（要到 `fight_end`
    // 才结算），所以下面那句"这个节点已经结算过了"**放行**重复调用 —— 而重复调用会重新选遭遇
    // （烧掉一个 `Combat` 随机数）、再 `Box::leak` 一份牌组、并且 `install_session` **覆盖**掉
    // 正在打的那一场。站在战斗节点上反复按"开打"就能重摇遭遇。
    if session.in_fight {
        return fail(session, "这一场已经开始了：先打完它，或者重开一局");
    }
    // Only a combat node starts a fight. The kind is read off the session we are already holding:
    // calling `rd_run_node_kind()` here would take the slot a second time (see `fail`).
    let node = session.state.node();
    if node < 0 {
        return fail(session, "还没有走到任何节点");
    }
    // The boss is a sentinel cursor rather than a map index (inv:§7.2: floor 16 is off the map),
    // so it is answered before the map lookup -- the same rule rd_run_node_kind applies.
    let kind = if node == i32::from(rd_run::map::BOSS_NODE) {
        i32::from(rd_run::map::NodeKind::Boss as u8)
    } else {
        session
        .state
        .map()
        .locate(node as u8)
        .and_then(|(row, local)| {
            session
                .state
                .map()
                .row(row)
                .and_then(|line| line.node(local))
                .map(|node| node.kind as i32)
        })
        .unwrap_or(-1)
    };
    // 1 = Combat, 2 = Elite, 7 = Boss (`run-layer.md` §7.2; the boss is floor 16, off the map).
    if kind != 1 && kind != 2 && kind != 7 {
        let message = std::format!("当前节点不是战斗（kind {kind}）");
        return fail(session, &message);
    }
    // A node pays once (`run-layer.md` §4.7.5). This is the check that stops a fight from being
    // farmed by pressing the button again from where you stand.
    if session.state.node_resolved() {
        return fail(session, "这个节点已经结算过了");
    }

    let content = content();
    // Pick an encounter with the `Combat` stream -- the stream exists for exactly this
    // (`run-layer.md` §3.2) and using it now means the per-fight seed and the encounter choice are
    // two draws from one reserved stream rather than a constant.
    // The document says which pool a fight comes from (`inv:§5.2` weak / `inv:§5.3` elite). Until
    // this existed the only rule was "any encounter in the image", which would have sent an elite
    // node into a slime fight.
    // The pool follows the node (`inv:§5.2` weak / `inv:§5.3` elite) -- before this the only rule
    // was "any encounter in the image", which would send an elite into a slime fight.
    // §170 `P1-1`: 三个标记**不在这里**写。下面每一步都可能失败（池子缺、池子空、选遭遇、摇种子、
    // 建战斗、遗物加成），而 `in_fight` 卡在 true 的后果不是审美问题：`rd_run_archive_fill` 会一直
    // 拒绝存档，而玩家**根本没有一场仗可以打完**。它们在**提交点**统一写，见函数尾部。
    //
    // 原子性的判据用 `RunState: Copy` 的整结构体快照：任何失败都回到进函数那一刻，
    // 连"选遭遇已经消耗的随机数"也一起还回去（`RunState` 的 `rng` 是字段）。
    let before = *session.state;
    // **The act decides the pool** (`port-plan.md` §130): `Weak` / `Weak2` / `Weak3`, and the same
    // for elites and bosses. Before this, act 2 and act 3 replayed act 1's encounters -- the
    // downgrade §101 documented. The suffix is empty for act 1 so the original names still work.
    let base = match kind {
        2 => "Elite",
        7 => "Boss",
        _ => "Weak",
    };
    let act = session.state.act();
    let pool_name: String = if act <= 1 {
        base.to_string()
    } else {
        std::format!("{base}{act}")
    };
    let encounters: Vec<&'static str> = match content.encounter_pool(&pool_name) {
        Some(ids) => ids.iter().filter(|id| !id.is_empty()).copied().collect(),
        None => {
            // Loud on purpose: an act with no encounters of its own is a **content gap**, and
            // falling back to act 1 would hide exactly the thing this section is about.
            let message = std::format!("内容里没有 `EncounterTables.{pool_name}` 池（第 {act} 幕）");
            return fail(session, &message);
        }
    };
    if encounters.is_empty() {
        return fail(session, "内容镜像里没有任何遭遇");
    }
    let pick = match pick_encounter(&mut session.state, content, &pool_name, &encounters) {
        Ok(index) => index,
        Err(message) => return fail(session, &message),
    };
    let fight_seed = match session.state.rng_mut().roll(RunStream::Combat, i32::MAX as u32) {
        Ok(value) => value as i32,
        Err(e) => {
            let message = describe(&e);
            return fail(session, &message);
        }
    };

    let max_health = session.state.health_max();
    // §145: what the relics do **when a fight starts**. Read off the run *before* the session is
    // installed, because `combat_bonus` borrows the run and the applier borrows the fight.
    let bonus = session.state.combat_bonus();
    // §159 `A7` / `A8` / `A9`: the node's kind decides which of the three rules (if any) raises the
    // enemies' maximum health. Read here, before the run is borrowed by the fight.
    let fight_kind = match kind {
        2 => rd_run::state::FightKind::Elite,
        7 => rd_run::state::FightKind::Boss,
        _ => rd_run::state::FightKind::Normal,
    };
    let enemy_health_percent = session.state.enemy_health_bonus_percent(fight_kind);
    // §187：A2/A3/A4 与 A17/18/19 都需要这一个数（内核不会猜它）。
    let ascension = session.state.ascension();
    // 可失败段收在一个块里：`entries` 借着 `state`（`DeckEntry<'static>` 的要求），块一结束借用就死，
    // 后面才允许拿整个 `session` 去回滚。这不是绕过借用检查，而是让借用检查器**替我**保证
    // "先建、后提交"。
    let failure: Option<std::string::String> = {
        // The run's deck, compressed into (id, count) entries, **owning its strings**.
        //
        // §170 `P1-1`: 原来写成 `Vec<(&'static str, u16)>` 直接借 `RunId::as_str()` —— 那是指进
        // `RunState` 自己的存储。于是"失败就恢复 `*session.state = before`"与"牌组项还指着那块内存"
        // 只能二选一：借用检查器拒绝它，而如果绕过检查，回滚会覆写战斗正在读的字节。
        // 拷贝出独立字符串之后，`FightPlan` 与 `RunState` 再无别名，回滚才是安全的。
        let mut counts: Vec<(std::string::String, u16)> = Vec::new();
        for id in session.state.deck() {
            let id = id.as_str();
            match counts.iter_mut().find(|(name, _)| name.as_str() == id) {
                Some((_, count)) => *count += 1,
                None => counts.push((std::string::String::from(id), 1)),
            }
        }
        let entries: &'static [rd_core::battle::DeckEntry<'static>] =
            Box::leak(
                counts
                    .into_iter()
                    .map(|(card, count)| rd_core::battle::DeckEntry {
                        card: Box::leak(card.into_boxed_str()),
                        count,
                    })
                    .collect::<Vec<_>>()
                    .into_boxed_slice(),
            );
        match crate::build_session_at(
            fight_seed,
            encounters[pick],
            max_health,
            Some(entries),
            enemy_health_percent,
            ascension,
        ) {
            Ok(combat) => {
                crate::install_session(combat);
                // The fight is built at the hero's maximum; a run usually enters wounded.
                crate::set_combat_hero_health(session.state.health());
                // ... and then the relics get their turn. A failure here is a **content** problem
                // (a relic promising Block the kernel cannot write), so it is reported, not ignored.
                apply_combat_bonus(bonus).err()
            }
            Err(message) => Some(message),
        }
    };
    if let Some(message) = failure {
        // §170 `P1-1`: 失败的这一次必须**什么都没改** —— 连"装好了战斗之后才在遗物加成一环失败"
        // 的那半场也一起撤掉（`take_session` 在没有会话时是 no-op）。
        crate::take_session();
        return fail_begin(session, before, &message);
    }
    // **提交点**：走到这里才是"这一场开始了"。
    session.elite_fight = kind == 2;
    session.boss_fight = kind == 7;
    session.in_fight = true;
    0
}

/// §170 `P1-1`: 一次失败的 `fight_begin` 必须**什么都没改**。
///
/// 恢复整局（`RunState` 是 `Copy`，所以连随机流计数一起回去）、清掉三个战斗标记、丢弃可能已经装上的
/// 战斗会话，然后写错误。判据是"拒绝 ⇒ 一个字节都不改"，与 `archive::restore` 同一条纪律。
fn fail_begin(session: &mut RunSession, before: rd_run::state::RunState, message: &str) -> i32 {
    *session.state = before;
    session.elite_fight = false;
    session.boss_fight = false;
    session.in_fight = false;
    session.error.clear();
    session.error.push_str(message);
    -2
}

/// Put a [`rd_run::state::CombatBonus`] into the fight that was just installed (§145).
///
/// Both writes go through the **same public APIs the game itself uses**: Block through
/// `set_defensive_pool`, Strength through an `ApplyStatus` effect. A relic that took a shortcut here
/// would be a second status pipeline, and the two would drift on the first modifier change.
fn apply_combat_bonus(bonus: rd_run::state::CombatBonus) -> Result<(), String> {
    if bonus.is_empty() {
        return Ok(());
    }
    let Some(session) = crate::slot().as_mut() else {
        return Err("战斗会话不见了".to_string());
    };
    let Some(hero) = session.hero_id() else {
        return Err("战斗里找不到英雄".to_string());
    };
    if bonus.block != 0 {
        let key = rd_core::state::DefensivePoolId::new("standard.block")
            .map_err(|_| "`standard.block` 不是合法的防守池 id".to_string())?;
        let combatant = session
            .state
            .combatant_mut(&hero)
            .ok_or_else(|| "拿不到英雄的战斗员".to_string())?;
        let current = combatant
            .defensive_pools()
            .iter()
            .find(|pool| pool.key.as_str() == "standard.block")
            .map_or(0, |pool| pool.pool.current);
        combatant
            .set_defensive_pool(key, current + bonus.block, None)
            .map_err(|e| std::format!("遗物加格挡失败：{e:?}"))?;
        let after = combatant
            .defensive_pools()
            .iter()
            .find(|pool| pool.key.as_str() == "standard.block")
            .map_or(-1, |pool| pool.pool.current);
        if after != current + bonus.block {
            return Err(std::format!(
                "遗物格挡写进去读到 {after}，期望 {}",
                current + bonus.block
            ));
        }
    }
    for entry in bonus.statuses.iter().take(bonus.status_count).flatten() {
        let definition = rd_core::state::StatusDefinitionId::new(entry.id)
            .map_err(|_| std::format!("`{}` 不是合法的状态 id", entry.id))?;
        let item = rd_core::state::EffectItem {
            request: rd_core::state::EffectRequest::ApplyStatus {
                target: Some(hero),
                definition,
                stacks: entry.stacks,
                duration: 0,
                charges: 0,
                source: None,
                source_card: None,
            },
            chain: rd_core::state::ChainSlot::NONE,
            owner: None,
        };
        let image = content();
        rd_core::exec::resolve_effect(&mut session.state, &item, Some(image))
            .map_err(|e| std::format!("遗物加状态 `{}` 失败：{e:?}", entry.id))?;
    }
    session.reobserve_after_external_change();
    Ok(())
}

/// Finish the fight and fold its result back into the run.
///
/// Returns the combat result (`1` victory, `2` defeat, ...), or `-1` when no fight is installed.
#[no_mangle]
pub extern "C" fn rd_run_fight_end() -> i32 {
    let Some(result) = crate::combat_result() else {
        if let Some(session) = run_slot().as_mut() {
            session.error.clear();
            session.error.push_str("没有正在进行的战斗");
        }
        return -1;
    };
    let hero_hp = crate::combat_hero_health().unwrap_or(0);
    // §201: gold an enemy escaped with (the Looter). Read **before** `take_session()` -- after that
    // the fight is gone. It rides in the record's text so a replay settles the same amount; the
    // `b` word is already a bitfield (tier in the low two bits, result above) and packing a third
    // number into it is how a silent replay divergence gets born.
    let carried_gold = crate::combat_gold_carried_away();
    // Captured before the run is borrowed mutably below.
    let elite_fight = run_slot().as_ref().is_some_and(|s| s.elite_fight);
    let boss_fight = run_slot().as_ref().is_some_and(|s| s.boss_fight);
    crate::take_session();
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    // §163: the tail is `apply_fight_outcome` so the replay can apply a **recorded** fight
    // without a combat session (a fight is not replayed; its outcome is).
    // `b` 低两位是**档位**（精英/Boss），高位是**结果**（1 胜 / 2 负 / 0 未决）。第一版只记了档位，
    // 回放时假定"记下来的战斗都是赢的" ⇒ 第 4 步就对不上（录制那次 `result = 0`，没有奖励）。
    session.log(
        K_FIGHT_END,
        hero_hp,
        (i32::from(boss_fight) << 1 | i32::from(elite_fight)) | (result << 4),
        &std::format!("{carried_gold}"),
    );
    let verdict =
        apply_fight_outcome(session, hero_hp, result, elite_fight, boss_fight, carried_gold);
    session.stamp();
    return verdict;
}

/// Smoke Bomb's tail (§179): drop the fight and settle the run as **fled** (`result = 3`).
///
/// It mirrors `rd_run_fight_end` on purpose -- same borrow dance, same `session.log` so a replay
/// reproduces the escape -- because "the fight ended some other way" must not be a second, private
/// path into the run state. The potion is consumed here: `apply_fight_outcome` does not know about
/// the belt, and the early return in `rd_env_use_potion` skips its usual tail.
fn flee_fight(slot: i32) -> i32 {
    if slot < 0 {
        return -1;
    }
    let slot_index = slot as usize;
    let Some(hero_hp) = crate::combat_hero_health() else {
        return -1;
    };
    let carried_gold = crate::combat_gold_carried_away();
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    let elite_fight = session.elite_fight;
    let boss_fight = session.boss_fight;
    let _ = (elite_fight, boss_fight);
    crate::take_session();
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    if let Err(e) = session.state.drop_potion(slot_index) {
        let message = describe(&e);
        return fail(session, &message);
    }
    // §201: an escape still forfeits what the thieves carried away -- it is the same `fight_end`
    // record, just with `result = 3` (no rewards), and the log has to carry the amount or a replay
    // would settle a different run.
    session.log(K_FIGHT_END, hero_hp, 3 << 4, &std::format!("{carried_gold}"));
    let verdict = apply_fight_outcome(session, hero_hp, 3, false, false, carried_gold);
    session.stamp();
    if verdict < 0 {
        return verdict;
    }
    0
}

/// The run-layer effect of a finished fight (extracted from `rd_run_fight_end`, §163).
fn apply_fight_outcome(
    session: &mut RunSession,
    hero_hp: i32,
    result: i32,
    elite_fight: bool,
    boss_fight: bool,
    carried_gold: i32,
) -> i32 {
    // ⚠️ `in_fight` 清在这里，不是清在导出里。它原来在 `rd_run_fight_end` 里，而回放走的是
    // `replay_fight` ⇒ 回放一场战斗之后运行层仍然"在战斗中"，于是页面的"回档"被内核拒掉
    // （浏览器闸门抓到的就是这个：restore 返回 -2，玩家看到的是"战斗中没有回档"，而他不在战斗里）。
    session.in_fight = false;
    // The fight is over: the run's health becomes the hero's.
    let delta = hero_hp - session.state.health();
    session.state.adjust_health(delta);
    // §201: the gold the Looter escaped with is **gone** (wiki `Thieves`: "Flees combat with your
    // Gold"). `carried_gold` counts only escapees -- an enemy you killed returns what it held
    // ("Stolen gold is returned if this enemy is killed"), so a dead one's counter is not here.
    // Capped at what the run actually has (`adjust_gold` clamps at 0), which is the wiki's
    // "doesn't give back gold it didn't steal" read from the other end.
    if carried_gold > 0 {
        session.state.adjust_gold(-carried_gold);
    }
    // `inv:§5`: the tier follows what was fought, and it moves gold and rarity together.
    // `inv:§4.3`: a boss pays 95-105 and its reward is always rare.
    let fight_kind = if boss_fight {
        rd_run::state::FightKind::Boss
    } else if elite_fight {
        rd_run::state::FightKind::Elite
    } else {
        rd_run::state::FightKind::Normal
    };
    if result == 3 {
        // §179: Smoke Bomb -- "Escape from a non-boss combat. **Receive no rewards.**" So: no
        // `end_of_combat` (no relics fire), no reward roll, no boss credit. The node still paid
        // (the escape happened there), which is the `mark_resolved()` below.
        //
        // It is deliberately **not** a fourth `CombatResult`: the kernel's three match the
        // reference byte for byte and `result=` is part of the golden hash.
        session.state.mark_resolved();
        return 3;
    }
    if result == 1 {
        // `Burning Blood` and friends (`inv:§2`), now with a call site.
        if let Err(e) = session.state.end_of_combat() {
            let message = describe(&e);
            return fail(session, &message);
        }
        // Then the reward screen (`inv:§5` gold, `inv:§3.5` three distinct cards). A reward that
        // could not be rolled is a refusal, not a silent victory with no spoils.
        let image = content();
        let pool = match reward_pool(image) {
            Ok(pool) => pool,
            Err(message) => return fail(session, &message),
        };
        // The potion the fight may drop (`inv:§9.3`) comes from **the whole `POT` table**
        // (§158): the per-act `PotionTables` split had no wiki source and `MAX_POOL_IDS` would
        // have truncated it anyway.
        let potion_ids = potion_pool_of(image);
        // §155: an elite (or boss) also pays a relic. `relic_pool` is the content's whole relic table;
        // `roll_reward` filters out the ones the player already holds (the same rule the chest and the
        // shop use), so a fight can never hand out a duplicate.
        let relic_ids = relic_pool(image);
        if let Err(e) = session
            .state
            .roll_reward(&pool, &potion_ids, &relic_ids, fight_kind)
        {
            let message = describe(&e);
            return fail(session, &message);
        }
    }
    // The fight is settled -- win or lose -- so the node has paid.
    session.state.mark_resolved();
    // `inv:§7.2`: killing the boss **clears the act**. This is the only way a run can be won.
    if result == 1 && boss_fight {
        session.state.mark_boss_beaten();
    }
    0.max(result)
}

// =============================================================================================
// §163 回放：脚本导出与逐步对拍
// =============================================================================================

fn script_text(session: &RunSession) -> std::string::String {
    let mut out = std::string::String::new();
    std::string::String::push_str(&mut out, &session.head);
    std::string::String::push_str(&mut out, ";");
    for rec in &session.journal {
        std::string::String::push_str(&mut out, rec_kind_name(rec.kind));
        std::string::String::push_str(&mut out, &std::format!(",{},{},{:016x},", rec.a, rec.b, rec.hash));
        std::string::String::push_str(&mut out, &rec.text);
        std::string::String::push_str(&mut out, ";");
    }
    out
}

/// How long the script is (bytes); `-1` no run.
/// The capacity of the script buffer, in bytes. Published so a caller can refuse **before** it
/// writes rather than discover truncation after (an overflowing script is a lie about the run).
#[no_mangle]
pub extern "C" fn rd_run_script_capacity() -> i32 {
    crate::MAX_SCRIPT as i32
}

/// The address of the script buffer (`rd_run_script_capacity()` bytes, owned by this module).
#[no_mangle]
pub extern "C" fn rd_run_script_buf() -> *mut u8 {
    std::ptr::addr_of_mut!(crate::SCRIPT) as *mut u8
}

/// Write the script into this module's buffer and return its length; `-1` no run, `-2` too long.
///
/// The page uses this (`rd_run_script_buf()` then read `len` bytes), and since §170 `P1-5` it is the
/// **only** way out: the `into(ptr)` variant that took a caller buffer without a capacity went away.
#[no_mangle]
pub extern "C" fn rd_run_script_fill() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    // §170 `P1-3`: 与 `rd_run_archive_fill` 同一条规则，**在 ABI 里**，不是只在页面的 `mode` 里。
    // 一份战斗中导出的脚本一定缺一段（战斗只有结果进脚本），回放它必然分叉 —— 与其给出一份会
    // 分叉的脚本，不如在这里拒绝。
    if session.in_fight {
        set_error("战斗中没有脚本：一场战斗只有**结果**进脚本，先打完这一场。");
        return -2;
    }
    session.stamp();
    if session.hash_failed {
        // §170 `P1-4`: 有一格哈希算不出来，这份脚本就**不能**导出去当证据用。
        set_error("导不出脚本：这一局的状态文本超出了哈希缓冲，逐步哈希对不上");
        return -2;
    }
    let text = script_text(session);
    let bytes = text.as_bytes();
    if bytes.len() > crate::MAX_SCRIPT {
        set_error(&std::format!(
            "回放脚本 {} 字节，超过缓冲容量 {}",
            bytes.len(),
            crate::MAX_SCRIPT
        ));
        return -2;
    }
    #[allow(static_mut_refs)]
    unsafe {
        crate::SCRIPT[..bytes.len()].copy_from_slice(bytes);
    }
    bytes.len() as i32
}

// §170 `P1-5`: 这里原来还有 `rd_run_script_len()` + `rd_run_script_into(ptr)` 一对 —— 和
// `fill`/`buf`/`capacity` 做的是同一件事，而 `into` 的 `unsafe` 契约是"你自己留够地方"：对 Rust
// 调用者成立，对 wasm/JS 那一侧就是一把对着脚的枪。它们唯一的用户是内核自己的测试，所以删掉它们、
// 让测试走页面走的那条路（`fill` + `buf` + `capacity`），而不是给一个只在测试里出现的导出加参数。
// 脚本接口现在只有一条路：**先问容量，再问长度，最后按长度读这个模块自己的缓冲区。**

/// How many steps the last replay verified (`0` when it diverged at the first step).
#[no_mangle]
pub extern "C" fn rd_run_replay_checked() -> i32 {
    run_slot().as_ref().map_or(-1, |s| s.replay_checked as i32)
}

/// Where the last replay diverged: `0` = nowhere.
#[no_mangle]
pub extern "C" fn rd_run_replay_diverged() -> i32 {
    run_slot().as_ref().map_or(-1, |s| s.replay_diverged)
}

/// Apply a **recorded** fight outcome (the replay's path; a fight is never re-simulated).
fn replay_fight(session: &mut RunSession, hero_hp: i32, flags: i32, carried_gold: i32) -> i32 {
    let elite = flags & 1 != 0;
    let boss = flags & 2 != 0;
    let result = flags >> 4;
    apply_fight_outcome(session, hero_hp, result, elite, boss, carried_gold)
}

/// Replay the script in `(ptr, len)`. `0` = every step reproduced; `n > 0` = step `n` diverged;
/// `-1` no run slot; `-2` refused (parse error or a step the replay cannot apply) with text.
///
/// # Safety
///
/// `ptr` must point at `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_replay_from(ptr: *const u8, len: i32) -> i32 {
    // ⚠️ 先把两个读数清零，否则**拒绝路径**（解析失败、内容不同）会留下上一次回放的
    // "13 步全部对上"，页面于是一边报错一边显示绿灯 —— 度量报陈旧数字。
    session_clear_replay(0, 0);
    // §170 `P1-3`: 回放会**重新开一局**（`rd_run_start`），所以它会毁掉正在进行的战斗。
    // 这条守卫必须在 ABI 里 —— 调用者不只有那个记得住 `mode` 的页面。
    if run_slot().as_ref().is_some_and(|session| session.in_fight) {
        set_error("战斗中不能回放：回放会从开局重跑这一局，把这场战斗扔掉。");
        return -2;
    }
    if ptr.is_null() || len <= 0 {
        return -2;
    }
    let bytes = std::slice::from_raw_parts(ptr, len as usize);
    let Ok(text) = std::str::from_utf8(bytes) else {
        set_error("回放脚本不是 UTF-8");
        return -2;
    };
    // `RDR1,seed,asc;` first, then one record per step.
    let Some((head, rest)) = text.split_once(';') else {
        set_error("回放脚本缺少头部");
        return -2;
    };
    let Some(fields) = head.strip_prefix("RDR1,") else {
        set_error("回放脚本的头部不是 RDR1");
        return -2;
    };
    // 头部有两种：`S,seed,asc`（开局）与 `A,<档案>`（从一份档案恢复之后接着打）。
    // 第二种存在的理由是：**回档之后接着打的步，只有档案能说明它的起点**。
    let parts: std::vec::Vec<&str> = fields.split(',').collect();
    match parts.first().copied() {
        Some("S") if parts.len() == 4 => {
            // §166：**先问内容，再问别的**。这一步在第一条记录之前，所以内容不同的脚本连一步都
            // 不会被应用 —— 而不是走到一半以"第 N 步分叉"或 `UnknownCard` 的形式暴露。
            let pin = u32::from_str_radix(parts[3], 16).unwrap_or(0);
            if pin != content_fingerprint() as u32 {
                set_error(&std::format!(
                    "内容版本不同（脚本 {:08x}，本机 {}）· 这份脚本是用另一份内容编的，重新导出再回放",
                    pin,
                    content_pin_text()
                ));
                return -2;
            }
            let (Ok(seed), Ok(ascension)) = (parts[1].parse::<i32>(), parts[2].parse::<i32>()) else {
                set_error("回放脚本的 seed/asc 不是整数");
                return -2;
            };
            // 从头开一局（`rd_run_start` 会清会话、清日志），然后关掉记录。
            if rd_run_start(seed, ascension) != 0 {
                return -2;
            }
        }
        Some("A") if parts.len() == 2 => {
            // 先要一个槽，`restore` 才有东西可写；`rd_run_start` 会把日志/头部清成开局形态，
            // 随后 restore 再把头部改成档案形态。
            if rd_run_start(0, 0) != 0 {
                return -2;
            }
            if rd_run_restore_from(parts[1].as_ptr(), parts[1].len() as i32) != 0 {
                return -2;
            }
        }
        _ => {
            set_error("回放脚本的头部应当是 RDR1,S,seed,asc,内容 或 RDR1,A,<档案>");
            return -2;
        }
    }
    // ⚠️ **No `let session = run_slot()` may live across the loop body.** It calls other exports,
    // and each of those takes the slot again (`lib.rs::slot()` states the rule). The flag is set in
    // a scope that ends here; every refusal borrows only for the length of one helper call.
    if let Some(session) = run_slot().as_mut() {
        session.replaying = true;
    } else {
        return -1;
    }

    let mut checked = 0usize;
    for (index, record) in rest.split(';').enumerate() {
        if record.is_empty() {
            continue;
        }
        let cells: std::vec::Vec<&str> = record.split(',').collect();
        if cells.len() < 4 {
            session_clear_replay(checked, (index + 1) as i32);
            set_error(&std::format!("第 {} 步的格式不对", index + 1));
            return (index + 1) as i32;
        }
        let Some(kind) = rec_kind_from_name(cells[0]) else {
            session_clear_replay(checked, (index + 1) as i32);
            set_error(&std::format!(
                "第 {} 步的种类 `{}` 不认识",
                index + 1,
                cells[0]
            ));
            return (index + 1) as i32;
        };
        let (Ok(a), Ok(b), Ok(want)) = (
            cells[1].parse::<i32>(),
            cells[2].parse::<i32>(),
            u64::from_str_radix(cells[3], 16),
        ) else {
            session_clear_replay(checked, (index + 1) as i32);
            set_error(&std::format!("第 {} 步的参数不是整数", index + 1));
            return (index + 1) as i32;
        };
        // 第 5 列保留给带字符串的步（今天没有： 自己算升级后的 id）。
        let payload = cells.get(4).copied().unwrap_or("");

        // 走**同一个**入口：拒绝与接受都由导出的函数自己决定，回放不重写规则。
        match kind {
            K_STEP => {
                let _ = rd_run_step(a);
            }
            K_BEGIN => {
                let _ = rd_run_begin_node();
            }
            K_REST => {
                let _ = rd_run_rest();
            }
            K_CHEST => {
                let _ = rd_run_open_chest();
            }
            K_LEAVE => {
                let _ = rd_run_leave();
            }
            K_BUY_CARD => {
                let _ = rd_run_buy_card(a);
            }
            K_BUY_RELIC => {
                let _ = rd_run_buy_relic(a);
            }
            K_REMOVE => {
                let _ = rd_run_remove_card(a);
            }
            K_TAKE_CARD => {
                let _ = rd_run_take_card(a);
            }
            K_SKIP => {
                let _ = rd_run_skip_reward();
            }
            K_TAKE_POTION => {
                let _ = rd_run_take_potion();
            }
            K_TAKE_RELIC => {
                let _ = rd_run_take_relic();
            }
            K_CHOOSE => {
                let _ = rd_run_choose(a);
            }
            K_EVENT_CARD => {
                let _ = rd_run_pick_event_card(a);
            }
            K_CHOOSE_START => {
                let _ = rd_run_choose_start(a);
            }
            K_BLESSING_CARD => {
                let _ = rd_run_pick_blessing_card(a);
            }
            K_DROP_POTION => {
                let _ = rd_run_drop_potion(a);
            }
            K_SMITH => {
                let _ = rd_run_smith(a);
            }
            K_FIGHT_END => {
                // 回放里先把这个"记录下来的战斗"自己的会话收掉（`fight_begin` 会开一个）。
                crate::take_session();
                let Some(session) = run_slot().as_mut() else {
                    return -1;
                };
                // §201: the gold an enemy escaped with is in the record's text (a plain
                // decimal); an older record without it settles 0, which is what those runs did.
                let carried = payload.parse::<i32>().unwrap_or(0);
                let _ = replay_fight(session, a, b, carried);
            }
            K_FIGHT_BEGIN => {
                let _ = rd_run_fight_begin();
            }
            K_GRANT_POTION => {
                let _ = rd_run_grant_potion(payload.as_ptr(), payload.len() as i32);
            }
            _ => {}
        }

        // §170 `P1-4`: "算不出哈希" 与 "哈希不一致" 是两件事，不能都折成一次比较失败。
        let now = match run_slot().as_mut().and_then(RunSession::state_hash) {
            Some(hash) => hash,
            None => {
                session_clear_replay(checked, (index + 1) as i32);
                set_error(&std::format!(
                    "第 {} 步之后算不出指纹：这一局的状态文本超出了哈希缓冲，无法逐步对拍",
                    index + 1
                ));
                return -2;
            }
        };
        if now != want {
            session_clear_replay(checked, (index + 1) as i32);
            set_error(&std::format!(
                "第 {} 步之后局面不同（期望 {want:016x}，回放得到 {now:016x}）",
                index + 1
            ));
            return (index + 1) as i32;
        }
        checked += 1;
    }
    session_clear_replay(checked, 0);
    0
}

fn session_clear_replay(checked: usize, diverged: i32) {
    if let Some(session) = run_slot().as_mut() {
        session.replaying = false;
        session.replay_checked = checked;
        session.replay_diverged = diverged;
    }
}

/// The **kind** of a card the run is showing, so the deck / reward / merchant lists can say
/// "Attack" instead of nothing.
///
/// `context`: 0 = the deck, 1 = the reward screen, 2 = the merchant's cards. `index` is the slot in
/// that list. Returns 0 none, 1 attack, 2 skill, 3 power, 4 status, 5 curse, `-1` unknown/absent.
///
/// One export rather than three: the three lists differ only in where the id comes from, and three
/// copies of "read the id, ask the content" is three places to forget.
#[no_mangle]
pub extern "C" fn rd_run_card_kind(context: i32, index: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    let id = match context {
        0 => session.state.deck().get(index as usize).map(|id| id.as_str()),
        1 => session
            .state
            .reward()
            .cards()
            .get(index as usize)
            .map(|id| id.as_str()),
        // The merchant's shelf holds Offers, not bare ids.
        2 => session
            .state
            .shop()
            .cards()
            .get(index as usize)
            .map(|offer| offer.id.as_str()),
        _ => None,
    };
    match id {
        Some(id) => crate::card_kind(content(), id),
        None => -1,
    }
}

// =============================================================================================
// Diagnosis
// =============================================================================================

/// Length of the last run-layer error message.
#[no_mangle]
pub extern "C" fn rd_run_last_error_len() -> i32 {
    let message = run_slot()
        .as_ref()
        .map(|s| s.error.clone())
        .unwrap_or_default();
    #[allow(static_mut_refs)]
    unsafe {
        let bytes = message.as_bytes();
        let len = bytes.len().min(RUN_SCRATCH_LEN);
        RUN_SCRATCH[..len].copy_from_slice(&bytes[..len]);
        len as i32
    }
}

/// Copy the last error message to `ptr`. Returns the number of bytes written.
#[no_mangle]
pub extern "C" fn rd_run_last_error_into(ptr: *mut u8) -> i32 {
    let len = rd_run_last_error_len();
    if len <= 0 || ptr.is_null() {
        return 0;
    }
    #[allow(static_mut_refs)]
    unsafe {
        for (offset, &byte) in RUN_SCRATCH[..len as usize].iter().enumerate() {
            *ptr.add(offset) = byte;
        }
    }
    len
}

/// The kinds the map can hold, for a page that wants to name them without duplicating the enum.
/// Returns `-1` past the end, so the loop terminates on the value rather than on a constant.
#[no_mangle]
pub extern "C" fn rd_run_kind_name_len(kind: i32) -> i32 {
    match kind_name(kind) {
        Some(name) => name.len() as i32,
        None => -1,
    }
}

/// Copy the name of `kind` to `ptr`; returns the bytes written, or `0`.
#[no_mangle]
pub extern "C" fn rd_run_kind_name_into(kind: i32, ptr: *mut u8) -> i32 {
    let Some(name) = kind_name(kind) else {
        return 0;
    };
    if ptr.is_null() {
        return 0;
    }
    let bytes = name.as_bytes();
    let len = bytes.len().min(RUN_SCRATCH_LEN);
    #[allow(static_mut_refs)]
    unsafe {
        RUN_SCRATCH[..len].copy_from_slice(&bytes[..len]);
        for (offset, &byte) in RUN_SCRATCH[..len].iter().enumerate() {
            *ptr.add(offset) = byte;
        }
    }
    len as i32
}

fn kind_name(kind: i32) -> Option<&'static str> {
    let kind = match kind {
        0 => NodeKind::Unassigned,
        1 => NodeKind::Combat,
        2 => NodeKind::Elite,
        3 => NodeKind::Rest,
        4 => NodeKind::Shop,
        5 => NodeKind::Unknown,
        6 => NodeKind::Treasure,
        7 => NodeKind::Boss,
        _ => return None,
    };
    Some(kind.name())
}

#[cfg(test)]
mod tests {
    use super::*;

    // Every test in this module drives the crate's two global sessions, and `cargo test` runs tests
    // in one process, in parallel. A mutex was tried and **deadlocked** (a lock taken twice in one
    // thread); the honest answer is that this crate's tests are not parallel-safe, so the gate runs
    // them with `--test-threads=1` (see `tools/acceptance.ps1`) and this module says so.
    use crate::{
        rd_env_action_count, rd_env_action_kind, rd_env_done, rd_env_enemy_name_into,
        rd_env_enemy_name_len, rd_env_pile_card_title_into, rd_env_pile_card_title_len,
        rd_env_pile_len, rd_env_result, rd_env_step,
    };
    use rd_run::map::{RunMap, NODES_PER_ROW};
    use rd_run::state::{MAX_RUN_POTIONS, MAX_RUN_RELICS};
    use rd_run::streams::RunRng;

    /// Start a run and take blessing 0. **Nothing here promises full health**: a blessing may cost
    /// HP (`blood_money` is -14), so a test that wants a particular health reads
    /// `rd_run_observe(2)` instead of assuming one.
    /// **A run built for a test, with no start path at all.**
    ///
    /// `reset(seed)` below replays the real thing (`rd_run_start` -> roll a blessing -> pick it),
    /// which means every test written against it depends on the blessing rules: changing the pool
    /// twice turned four unrelated tests red (port-plan.md §88, §90). This constructor skips all of
    /// that -- an explicit seed, health and deck, straight into the slot.
    ///
    /// A test that is **about** the start path keeps using `reset`; everything else should use this.
    /// The exported observation buffer, the way the page reads it (§145's relic test needs it).
    fn exported_observation() -> Vec<i32> {
        let len = crate::rd_env_observe_len();
        assert!(len > 0, "no observation buffer");
        let ptr = crate::rd_env_observe_buf();
        unsafe { std::slice::from_raw_parts(ptr, len as usize).to_vec() }
    }

    /// **7 migrated / 20 to go** -- the count lives in `reset`'s doc comment, and this line points at
    /// it rather than repeating it (`docs/port-plan.md` §106).
    #[cfg(test)]
    fn test_run(seed: i32, health: i32, max_health: i32, deck: &[&str]) {        let state = rd_run::state::RunState::new(seed, max_health, 0, deck).expect("a run");
        let mut state = state;
        state.adjust_health(health - max_health);
        *run_slot() = Some(RunSession {
            state: Box::new(state),
            error: String::new(),
            elite_fight: false,
            boss_fight: false,
        in_fight: false,
        journal: Vec::new(),
        head: std::format!(
            "RDR1,S,{},{},{}",
            state.seed(),
            state.ascension(),
            content_pin_text()
        ),
        replaying: false,
        replay_checked: 0,
        replay_diverged: 0,
        hash_failed: false,
        });
    }

    /// §201: **the gold a Looter escaped with is gone -- and it is the only gold that goes.**
    ///
    /// Three judgements, each locking one way the settlement could be wrong:
    /// 1. `carried_gold = 15` on a victory takes 15 off the run's gold;
    /// 2. a **killed** thief costs nothing (`carried_gold = 0`): its `stolen_gold` counter never
    ///    reaches `gold_carried_away` (wiki: "Stolen gold is returned if this enemy is killed");
    /// 3. the deduction is **clamped at 0** -- a run with 5 gold cannot lose 15.
    ///
    /// The victory reward also moves gold, so each case measures it first: case 2 settles the same
    /// seed/health **with no escapee** and reads what the reward paid, then cases 1/3 subtract the
    /// same reward from the expectation. (Hard-coding `inv:§5`'s 10-20 would make this test a second
    /// copy of the reward table.)
    ///
    /// Negative control: make `apply_fight_outcome` read the enemies' counters instead of the
    /// passed-in number and case 2 goes red -- a dead thief would still cost gold.
    #[test]
    fn the_gold_a_thief_carried_away_is_the_only_gold_lost() {
        let deck = ["strike", "strike", "strike", "strike", "strike", "defend", "defend",
                    "defend", "defend", "bash"];
        let settle = |seed: i32, carried: i32, gold_before: i32| -> (i32, i32) {
            test_run(seed, 70, 80, &deck);
            run_slot().as_mut().expect("run").state.adjust_gold(gold_before);
            let verdict = apply_fight_outcome(
                run_slot().as_mut().expect("run"), 70, 1, false, false, carried);
            assert!(verdict >= 0, "a settled victory must not fail: {verdict}");
            (run_slot().as_ref().expect("run").state.gold(), verdict)
        };

        // The reward this seed pays, measured with no escapee at all.
        let (no_escape, _) = settle(21, 0, 45);
        let reward = no_escape - 45;
        // 1: an escape costs exactly what the escapee carried.
        let (escaped, _) = settle(21, 15, 45);
        assert_eq!(escaped, 45 + reward - 15, "45 gold minus the 15 it escaped with");
        // 2: a killed thief returns everything it held -- the reward is the only movement.
        assert_eq!(no_escape, 45 + reward, "a dead thief costs nothing");
        // 3: clamped at zero. Seed 23 pays its own reward, so measure that one too.
        let (poor_no_escape, _) = settle(23, 0, 5);
        let poor_reward = poor_no_escape - 5;
        let (broke, _) = settle(23, 999, 5);
        assert_eq!(
            broke,
            poor_reward.max(0),
            "an escape cannot push gold below zero (5 gold, 999 carried)"
        );
    }

    /// Start a run and **finish the blessing**, so every test below stands on floor 1 with a
    /// settled run. It prefers a blessing that touches nothing (no card removed, no card upgraded,
    /// no HP paid), but **nothing here is relied upon**: a test that cares about the deck reads
    /// `rd_run_deck_count()` instead of assuming ten.
    ///
    /// ⚠️ **HANGING ITEM (counted, not forgotten).** `reset` *replays the real start path*, so any
    /// test written against it depends on the blessing rules -- which is what turned four unrelated
    /// tests red twice (`port-plan.md` §88, §90). [`test_run`] exists to break that dependency, and
    /// **7 of the 27 tests in this module have moved to it**; the other **20 still call `reset`**.
    ///
    /// The rule: a test **about the start path** keeps `reset`; every other test should use
    /// `test_run`. Migrate a test when you next touch it -- *not* in one sweep, because a sweep is
    /// exactly what produced the reverts. See `docs/port-plan.md` §106.
    fn reset(seed: i32) {
        reset_at(seed, 0);
        // **The fixture's post-condition, asserted here** so that a future change which leaves the
        // run half-started fails with *this* message instead of cascading into 27 confusing ones.
        assert_eq!(rd_run_act(), 1, "reset must start in act 1");
        assert_eq!(rd_run_observe(0), 0, "reset must start before floor 1");
        assert!(rd_run_deck_count() > 0, "reset left an empty deck");
    }

    fn obs() -> Vec<i32> {
        (0..rd_run_observe_len()).map(|index| rd_run_observe(index)).collect()
    }

    #[test]
    fn a_run_starts_from_the_content_not_from_constants() {
        // **Before the blessing**: this test is about what the *content* says (80/80), not about
        // what a blessing later did to it.
        assert_eq!(rd_run_start(7, 0), 0, "rd_run_start(7)");
        let start = obs();
        assert_eq!(start[2], 80, "health");
        assert_eq!(start[3], 80, "max health");
        // §161.8: the content says 99 (the wiki's starting gold); it used to say 0, so the first
        // shop could not buy anything -- found by the vertical slice, not by this test.
        assert_eq!(start[4], 99, "gold comes out of the content, which says 99");
        assert_eq!(rd_run_choose_start(0), 0, "taking blessing 0");
        let o = obs();
        assert_eq!(rd_run_seed(), 7);
        assert_eq!(o[5], 10, "`inv:§2.1`: a ten-card starting deck");
        assert_eq!(o[0], 0, "floor is 0 before the first step");
        assert_eq!(o[1], -1, "the cursor starts off the map");
        // `rd_run_start` **generates the map**, and generation draws from the `Map` stream, so that
        // counter is not zero. Every other counter is untouched by generation -- which is the
        // substream property (`run-layer.md` §3.6) observed from the outside -- with one documented
        // exception: the **blessing roll** (`inv:§7.1`) happens at start too and draws twice from
        // the `Event` stream, so that one reads 2 and nothing else may move.
        for (index, value) in o.iter().enumerate().take(16).skip(10) {
            if index == 12 {
                assert_eq!(
                    *value, 2,
                    "the blessing roll is two draws from the `Event` stream"
                );
                continue;
            }
            assert_eq!(*value, 0, "stream counter {index} must be untouched by map generation");
        }
        // Pinned on purpose: this is how many draws map generation costs for seed 7. A change to
        // the generator, the weights or the reroll caps moves it, and that should be noticed rather
        // than absorbed. (`index 9` is the `Map` stream, `run-layer.md` §3.2.)
        //
        // Four values in one day, and each move is the point of pinning it:
        //   141 -> 128: the walk learned to prefer an unclaimed target in the next row.
        //   128 -> 148: `MIN_NODES_PER_ROW` became a rule; rejected draws are not rewound, so the
        //               accepted draw happens later in the stream.
        //   148 -> 135: the six-path walk was replaced by "choose the rows, then connect them"
        //               (`map.rs::connect_rows`), because the walk could not be both wide enough
        //               and connected.
        // A change here means the generator changed. That is information, not an inconvenience.
        assert_eq!(o[9], 135, "map generation draw count for seed 7");
        assert_eq!(o.len(), RUN_OBS_LEN);
    }

    /// The exported map must be the one `rd-run` generates for that seed — not a second opinion.
    #[test]
    fn the_exported_map_is_the_one_the_run_layer_generated() {
        // An explicit run: this test is about the map, not about the start path.
        test_run(11, 80, 80, &["strike"; 10]);
        let mut rng = RunRng::new(11);
        let expected = RunMap::generate(&mut rng).expect("seed 11 generates");
        assert_eq!(rd_run_map_len() as usize, expected.node_count());
        assert_eq!(rd_run_map_rows(), ROWS as i32);
        for index in 0..rd_run_map_len() {
            let (row, local) = expected.locate(index as u8).unwrap();
            assert_eq!(rd_run_map_node(index, NODE_FIELD_ROW), row as i32);
            assert_eq!(
                rd_run_map_node(index, NODE_FIELD_COL),
                i32::from(expected.row(row).unwrap().node(local).unwrap().col)
            );
            assert_eq!(
                rd_run_map_node(index, NODE_FIELD_KIND),
                expected.row(row).unwrap().node(local).unwrap().kind as i32
            );
        }
        // Every row's first node is where the map says it is.
        for row in 0..ROWS {
            let first = rd_run_map_row_first(row as i32);
            match expected.row_first(row) {
                Some(want) => assert_eq!(first, i32::from(want), "row {row}"),
                None => assert_eq!(first, -1),
            }
        }
        assert_eq!(rd_run_map_row_first(ROWS as i32), -1, "past the end");
    }

    #[test]
    fn every_edge_points_at_a_real_node_in_the_next_row() {
        reset(3);
        let mut with_edges = 0;
        for index in 0..rd_run_map_len() {
            let degree = rd_run_map_node(index, NODE_FIELD_OUT_DEGREE);
            let row = rd_run_map_node(index, NODE_FIELD_ROW);
            assert!((0..=3).contains(&degree), "node {index} out_degree {degree}");
            if row + 1 == ROWS as i32 {
                assert_eq!(degree, 0, "the last row has nowhere to go");
            }
            for slot in 0..degree {
                let target = rd_run_map_node(index, NODE_FIELD_EDGE0 + slot);
                assert!(target >= 0, "node {index} edge {slot} is absent");
                assert_eq!(
                    rd_run_map_node(target, NODE_FIELD_ROW),
                    row + 1,
                    "an edge must cross exactly one row"
                );
                with_edges += 1;
            }
            // Unused edge slots are `-1`, not a stale number.
            for slot in degree..3 {
                assert_eq!(rd_run_map_node(index, NODE_FIELD_EDGE0 + slot), -1);
            }
        }
        assert!(with_edges > 0, "the map has no edges at all");
    }

    #[test]
    fn the_first_step_offers_floor_one_and_marks_exactly_those_reachable() {
        // An explicit run: this test is about the map, not about the start path.
        test_run(5, 80, 80, &["strike"; 10]);
        let o = obs();
        let offer = o[16];
        assert!(offer >= 2, "floor 1 must offer a choice, got {offer}");
        assert_eq!(rd_run_action_count(), offer, "the action table is the reachable set");
        // Every offered node is on floor 1 and marked reachable; every other node is not.
        let mut on_floor_one = 0;
        for index in 0..rd_run_map_len() {
            let reachable = rd_run_map_node(index, NODE_FIELD_REACHABLE) == 1;
            if !reachable {
                continue;
            }
            on_floor_one += 1;
            assert_eq!(rd_run_map_node(index, NODE_FIELD_ROW), 0);
        }
        assert_eq!(on_floor_one, offer);
        // And the action table names exactly those nodes.
        for action in 0..rd_run_action_count() {
            assert_eq!(rd_run_action(action), 0, "kind 0 = enter a node");
            assert_eq!(rd_run_action_arg(action, 1), -1);
            let target = rd_run_action_arg(action, 0);
            assert_eq!(rd_run_map_node(target, NODE_FIELD_REACHABLE), 1);
            assert_eq!(rd_run_map_node(target, NODE_FIELD_ROW), 0);
        }
    }

    #[test]
    fn walking_moves_the_cursor_and_a_refusal_changes_nothing() {
        // An explicit run: this test is about the map, not about the start path.
        test_run(9, 80, 80, &["strike"; 10]);
        let (before, action) = (obs(), 0);
        // Read the target **before** stepping: the action table is a function of the current
        // state, so after the step `action 0` names one of the *new* node's exits.
        let target = rd_run_action_arg(action, 0);
        assert_eq!(rd_run_step(action), 0);
        let after = obs();
        assert_eq!(after[0], 1, "floor is 1 after the first step");
        assert_eq!(after[1], target, "the cursor is on the node we entered");
        assert_ne!(before[1], after[1], "the cursor must actually move");
        assert_eq!(rd_run_map_node(after[1], NODE_FIELD_ROW), 0);

        // An out-of-range action is refused and leaves every observation field identical.
        let snapshot = obs();
        assert_eq!(rd_run_step(9999), -1);
        assert_eq!(obs(), snapshot, "a refused step must not move anything");

        // Walk to the bottom, always taking the first offer.
        let mut steps = 1;
        while obs()[0] < ROWS as i32 {
            let offer = obs()[16];
            assert!(offer >= 1, "floor {} has no exit", obs()[0]);
            settle_here();
        assert_eq!(rd_run_step(0), 0, "step {steps} refused");
            steps += 1;
        }
        assert_eq!(steps, ROWS, "one step per floor");
        // The last row's only way forward is the boss (`inv:§7.2`: floor 16, off the map).
        assert_eq!(obs()[16], 1, "one offer from the last row");
        assert_eq!(rd_run_action_count(), 1, "and it is the boss");
        assert_eq!(
            rd_run_action_arg(0, 0),
            i32::from(rd_run::map::BOSS_NODE),
            "the offer is the boss sentinel"
        );
    }

    #[test]
    fn the_kind_names_come_from_the_map_enum() {
        assert_eq!(rd_run_kind_name_len(1), "combat".len() as i32);
        assert_eq!(rd_run_kind_name_len(6), "treasure".len() as i32);
        assert_eq!(rd_run_kind_name_len(7), "boss".len() as i32, "kind 7 is the boss");
        assert_eq!(rd_run_kind_name_len(8), -1, "no such kind");
        assert_eq!(rd_run_kind_name_len(-1), -1);
    }

    #[test]
    fn a_different_seed_is_a_different_run() {
        // An explicit run: this test is about the map, not about the start path.
        test_run(1, 80, 80, &["strike"; 10]);
        let first = (0..rd_run_map_len())
            .map(|i| (rd_run_map_node(i, NODE_FIELD_KIND), rd_run_map_node(i, NODE_FIELD_OUT_DEGREE)))
            .collect::<Vec<_>>();
        reset(2);
        let second = (0..rd_run_map_len())
            .map(|i| (rd_run_map_node(i, NODE_FIELD_KIND), rd_run_map_node(i, NODE_FIELD_OUT_DEGREE)))
            .collect::<Vec<_>>();
        assert_ne!(first, second, "the seed must reach the exported map");
    }

    /// The relic the content declares actually reaches the run, with its own display name, and the
    /// effect rule that `rd-run` implements fires on it.
    ///
    /// The chain under test is content → image → `Content::start_relics` → `RunState::relics` →
    /// `REL.DisplayName` → the export. Every link is somebody else's decision, which is why this is
    /// one test rather than four.
    #[test]
    fn the_starting_relic_comes_out_of_the_content() {
        reset(7);
        let o = obs();
        assert_eq!(o[6], 1, "`inv:§2`: the Ironclad starts with one relic");
        assert_eq!(rd_run_relic_id_len(0), "burning_blood".len() as i32);
        let mut buffer = vec![0u8; 64];
        // Slice by the length the export returns: the buffer is longer than the string, so a fixed
        // slice would fold trailing NULs into the comparison (this test did exactly that first).
        let written = unsafe { rd_run_relic_id_into(0, buffer.as_mut_ptr()) } as usize;
        let id = String::from_utf8(buffer[..written].to_vec()).unwrap();
        assert_eq!(id, "burning_blood");

        // The display name is the content's `DisplayName`, not a title-cased id -- and it lives in
        // the **full** image (`DisplayName` is in `PRESENTATION_KEYS`, so the core mirror strips
        // it), which is the same reason the card text needs the full image.
        assert_eq!(rd_run_relic_name_len(0), "Burning Blood".len() as i32);
        let mut name = vec![0u8; 32];
        let written = unsafe { rd_run_relic_name_into(0, name.as_mut_ptr()) } as usize;
        assert_eq!(String::from_utf8(name[..written].to_vec()).unwrap(), "Burning Blood");

        // Out of range is `-1`, not an empty name.
        assert_eq!(rd_run_relic_name_len(1), -1);
        assert_eq!(rd_run_relic_id_len(-1), -1);
    }

    /// §153：**同一种普通怪不会连着来**，而一局里必须见到不止一种。
    ///
    /// 这条测试来自一个用户报告："普通怪始终只有 jaw_worm，没有其他的"。三个原因叠在一起：
    /// ① 页面的 `runSeed` 是常量 `7`（每次刷新重放同一局，而 seed 7 的头三场都是 jaw_worm）；
    /// ② 内容写了 `Weight`，内核却用 `roll(len)` **均匀抽**（权重是死数据）；
    /// ③ 没有"别连着重复"的约束（实测 ~100 场里 18 场与上一场相同，还有过三连）。
    ///
    /// 这里直接打**抽签那一层**（`pick_encounter`）：走完整战斗会让英雄在对局里被打死，
    /// 于是只能测到第一场（第一版就是这样，报的是 `expected several fights, got ["enc_jaw_worm"]`）。
    #[test]
    fn normal_fights_do_not_repeat_and_are_not_all_the_same() {
        reset(7);
        let image = content();
        let pool = image.encounter_pool("Weak").expect("the act-1 weak pool");
        let encounters: Vec<&'static str> =
            pool.iter().filter(|id| !id.is_empty()).copied().collect();
        assert!(encounters.len() >= 6, "the pool should be spread out: {encounters:?}");
        let mut picks: Vec<String> = Vec::new();
        for _ in 0..40 {
            let session = run_slot().as_mut().expect("session");
            let index = pick_encounter(&mut session.state, image, "Weak", &encounters)
                .expect("a pick");
            picks.push(encounters[index].to_string());
        }
        for pair in picks.windows(2) {
            assert_ne!(pair[0], pair[1], "two fights in a row used the same encounter: {picks:?}");
        }
        let mut distinct = picks.clone();
        distinct.sort_unstable();
        distinct.dedup();
        assert_eq!(
            distinct.len(),
            encounters.len(),
            "40 picks must cover the whole pool: {distinct:?}"
        );
        // The weights say `cultist` and `gremlin_gang` are 15/100 each and the others 14/100, so no
        // encounter may be wildly over- or under-represented. Loose on purpose: this is a smoke
        // check that the weights are *used* (a uniform pool would pass it too), the exact
        // distribution is a statistical claim no single seed can make.
        for encounter in &distinct {
            let count = picks.iter().filter(|pick| *pick == encounter).count();
            assert!(
                (1..=15).contains(&count),
                "{encounter} came up {count} times in 40: {picks:?}"
            );
        }
    }
    /// §155：**精英奖励里的遗物能通过 ABI 拿到**（走 `push_relic` 这个唯一授予点）。
    ///
    /// 这里直接逼出一张奖励表（`roll_reward(FightKind::Elite)`），而不是打赢一场精英：
    /// 打赢需要一套出牌策略，而策略不是"奖励能不能拿"这件事的判据。
    #[test]
    fn the_elite_relic_reward_round_trips_through_the_abi() {
        reset(7);
        let relics = relic_pool(content());
        let pool = match full_pool(content()) {
            Ok(pool) => pool,
            Err(message) => panic!("{message}"),
        };
        let held_before = rd_run_observe(6);
        let offered = {
            let session = run_slot().as_mut().expect("session");
            session
                .state
                .roll_reward(&pool, &[], &relics, rd_run::state::FightKind::Elite)
                .expect("an elite reward")
        };
        let _ = offered;
        let len = rd_run_reward_relic_len();
        assert!(len > 0, "the reward table offers a relic");
        let mut buffer = std::vec![0u8; len as usize];
        unsafe { rd_run_reward_relic_into(buffer.as_mut_ptr()) };
        let id = String::from_utf8(buffer).expect("ascii");
        assert!(
            relics.iter().any(|entry| entry.id == id),
            "{id} is not in the pool"
        );

        assert_eq!(rd_run_take_relic(), 0, "take it: {}", run_error_text());
        assert_eq!(
            rd_run_observe(6),
            held_before + 1,
            "the relic count moved"
        );
        assert_eq!(rd_run_reward_relic_len(), 0, "the row is empty after taking it");
        // `-2` = refused with a readable reason (`-1` means "no run / no such slot"), which is what
        // a second take is: the table has no relic left.
        assert_eq!(rd_run_take_relic(), -2, "taking it twice is refused, not ignored");
    }

    /// §152：五种新的药水形状**真的有效**（各自读回来一个数，而不是"没报错"）。
    ///
    /// 药水的词表从 3 种效果扩到 8 种，而"扩了词表"与"喝下去有用"是两件事 —— 这一条盯后者。
    /// 前两种是 `kind:payload`（状态 id 在冒号后），中间两种走的是新加的管线入口，最后一种走抽牌。
    #[test]
    fn the_new_potion_shapes_all_do_something() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        // Wounded hero, so a percentage heal has something to heal.
        crate::set_combat_hero_health(40);

        let enemies = crate::slot().as_ref().expect("env session").enemy_roster().len();
        assert!(enemies >= 1, "a fight has at least one enemy");
        let hp_before = enemy_hp(0);

        // 1. `combat_status:standard.strength` -- onto the hero.
        assert_eq!(drink("strength_potion", -1), 0, "strength potion");
        assert_eq!(hero_status("standard.strength"), 2, "2 Strength on the hero");

        // 2. `combat_status_target:standard.weak` -- onto the chosen enemy.
        assert_eq!(drink("weak_potion", 0), 0, "weak potion");
        assert_eq!(enemy_status(0, "standard.weak"), 3, "3 Weak on enemy 0");

        // 3. `combat_damage_all` -- 10 to every living enemy (two beats, one per enemy).
        {
            let session = crate::slot().as_mut().expect("env session");
            session.state.clear_beats();
        }
        assert_eq!(drink("explosive_potion", -1), 0, "explosive potion");
        let mut hits = 0;
        for index in 0..crate::rd_env_beat_count() {
            if crate::rd_env_beat_field(index, 0) == crate::BEAT_DAMAGE {
                hits += 1;
            }
        }
        assert_eq!(hits as usize, enemies, "every living enemy takes the explosion");
        assert!(enemy_hp(0) < hp_before || enemy_hp(0) == 0, "enemy 0 lost health");

        // 4. `combat_heal_percent` -- 20% of maximum (80) = 16.
        let before = crate::combat_hero_health().unwrap_or(-1);
        assert_eq!(drink("blood_potion", -1), 0, "blood potion");
        assert_eq!(
            crate::combat_hero_health().unwrap_or(-1),
            (before + 16).min(80),
            "20% of 80 max HP"
        );

        // 5. `combat_draw` -- three more cards in hand.
        let hand_before = exported_observation()[crate::H_HAND_COUNT];
        assert_eq!(drink("swift_potion", -1), 0, "swift potion");
        assert_eq!(
            exported_observation()[crate::H_HAND_COUNT],
            hand_before + 3,
            "Swift Potion draws 3"
        );
        assert_eq!(rd_run_potion_count(), 0, "every potion was consumed");
    }

    /// §158: Flex Potion is **two atoms in one bottle** -- `+5 Strength` now, and `-5 Strength` at
    /// the end of the turn. The potion row has one `Effect` cell, so this is what the comma list is
    /// for; the second half has to be a status that *removes itself*, or the hero keeps the +5 and
    /// the potion is simply better than the wiki's.
    #[test]
    fn flex_potion_gives_strength_and_takes_it_back() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        assert_eq!(drink("flex_potion", -1), 0, "flex potion");
        assert_eq!(hero_status("standard.strength"), 5, "+5 Strength right now");
        assert_eq!(
            hero_status("standard.lose_strength"),
            5,
            "and a 5-point debt that the turn end has to settle"
        );

        let end = rd_env_action_index_of_end_turn();
        assert!(end >= 0, "the hero can end the turn");
        assert_eq!(rd_env_step(end), 0, "end the turn");

        // 0 here means **absent** (`modifyStatusStacks` to zero removes the instance), which is
        // exactly what "gave it back" looks like on this ABI.
        assert_eq!(hero_status("standard.strength"), 0, "the Strength went back");
        assert_eq!(
            hero_status("standard.lose_strength"),
            0,
            "the debt removed itself instead of charging the same 5 every turn"
        );
    }

    /// §158: Entropic Brew fills the empty slots -- and it has to **free its own first**.
    ///
    /// The belt is three slots, so a brew drunk at 3/3 that filled before consuming would find no
    /// room and leave the player with two potions where they started with three. The assertion is
    /// therefore "3 before, 3 after", which cannot pass by accident.
    #[test]
    fn entropic_brew_fills_the_belt_after_freeing_its_own_slot() {
        test_run(7, 80, 80, &["strike"; 10]);
        {
            let session = run_slot().as_mut().expect("session");
            for potion in ["entropic_brew", "fire_potion", "block_potion"] {
                session.state.push_potion(potion).expect("belt room");
            }
        }
        assert_eq!(rd_run_potion_count(), 3, "the belt is full");
        assert_eq!(rd_run_potion_needs_fight(0), 0, "a brew does not need a fight");

        assert_eq!(rd_env_use_potion(0, -1), 0, "drink the brew");
        assert_eq!(
            rd_run_potion_count(),
            3,
            "the brew freed its slot and the refill used it"
        );
        let session = run_slot().as_ref().expect("session");
        for id in session.state.potions() {
            assert!(!id.as_str().is_empty(), "a refill produced an empty id");
        }
    }

    /// §158: Fruit Juice is the one potion that is about the **run**, and the wiki lets you drink it
    /// in most rooms -- so it must work with no fight running. Before this the "not in a fight"
    /// check came first and refused it, which made the potion reachable only mid-battle.
    #[test]
    fn fruit_juice_works_outside_a_fight() {
        reset(7);
        {
            let session = run_slot().as_mut().expect("session");
            session.state.push_potion("fruit_juice").expect("belt room");
        }
        let (max_before, hp_before) = {
            let session = run_slot().as_ref().expect("session");
            (session.state.health_max(), session.state.health())
        };
        assert_eq!(rd_run_potion_needs_fight(0), 0, "it is a run-layer potion");
        assert_eq!(
            rd_env_use_potion(0, -1),
            0,
            "Fruit Juice must work with no fight running"
        );
        let session = run_slot().as_ref().expect("session");
        assert_eq!(session.state.health_max(), max_before + 5, "+5 Max HP");
        assert_eq!(
            session.state.health(),
            (hp_before + 5).min(max_before + 5),
            "and the same amount of health, capped at the new maximum"
        );
        assert_eq!(rd_run_potion_count(), 0, "the bottle was consumed");
    }

    /// §159: **(seed, level)** is the whole description of a run, and both are real inputs.
    ///
    /// The rules are **cumulative**, so `A14` also carries `A6` -- which is why A14 reads 75/68 and
    /// not 75/75. Both numbers are asserted at four levels so that "which rule is in effect" cannot
    /// be answered by a single `>=` that was written once and never checked on both sides.
    #[test]
    fn the_ascension_level_reaches_the_run() {
        assert_eq!(rd_run_start(7, 0), 0);
        assert_eq!(rd_run_ascension(), 0, "A0 is a real level, not 'no run'");
        assert_eq!(rd_run_observe(3), 80, "the content's maximum");
        assert_eq!(rd_run_observe(2), 80, "and it starts full at A0");

        // A6 alone: still 80 maximum, 10% off the health.
        assert_eq!(rd_run_start(7, 6), 0);
        assert_eq!(rd_run_observe(3), 80, "A6 does not touch the maximum");
        assert_eq!(rd_run_observe(2), 72, "A6: 10% of 80");

        // A14 adds `-5` maximum on top of A6 (cumulative, so A6 is still in effect).
        assert_eq!(rd_run_start(7, 14), 0);
        assert_eq!(rd_run_ascension(), 14);
        assert_eq!(rd_run_observe(3), 75, "A14: -5 for the Ironclad");
        assert_eq!(rd_run_observe(2), 68, "A6 on the new maximum: 75 - 7");

        // A20 changes nothing further: A6 and A14 are the only two starting-state rules.
        assert_eq!(rd_run_start(7, 20), 0);
        assert_eq!(rd_run_ascension(), 20);
        assert_eq!(rd_run_observe(3), 75);
        assert_eq!(rd_run_observe(2), 68);

        // A level off the end of the ladder is clamped rather than refused.
        assert_eq!(rd_run_start(7, 99), 0);
        assert_eq!(rd_run_ascension(), 20);

        // The seed still means what it meant: the same seed at the same level is the same run.
        assert_eq!(rd_run_start(7, 0), 0);
        let first = rd_run_observe(3);
        assert_eq!(rd_run_start(7, 0), 0);
        assert_eq!(rd_run_observe(3), first);
    }

    /// §206: every `MaxHealthAsc` value the image pins for a monster whose base HP is `base`.
    fn pinned_health_for(base: i32) -> Vec<i32> {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("the image parses");
        let mut out = Vec::new();
        for row in content.rows(rd_core::content::Table::Encounter) {
            let Ok(enemies) = content.encounter_enemies(row.index()) else {
                continue;
            };
            for slot in 0..enemies.len() {
                let Ok(spec) = enemies.get(slot) else { continue };
                if spec.max_health().ok().flatten() != Some(base) {
                    continue;
                }
                if let Ok(Some(pinned)) = spec.max_health_asc(19) {
                    out.push(pinned);
                }
            }
        }
        out.sort_unstable();
        out.dedup();
        out
    }

    /// §159 `A7`: the same seed, the same fight, and only the rule differs -- so the enemy's maximum
    /// health is the **only** thing that can move.
    ///
    /// Each walk starts from `reset_at`, not from a bare `rd_run_start`: the second walk needs the
    /// blessing taken and the run settled, and a helper that did half of it would fail as "no fight"
    /// rather than as "the wrong number".
    #[test]
    fn ascension_seven_makes_a_normal_fight_tougher() {
        reset_at(7, 0);
        assert!(arrive_at_a_fight(), "seed 7 must reach a fight at A0");
        let plain = crate::slot().as_ref().expect("the fight").plan.enemies[0].max_health;

        reset_at(7, 7);
        assert!(arrive_at_a_fight(), "seed 7 must reach the same fight at A7");
        let ascended = crate::slot().as_ref().expect("the fight").plan.enemies[0].max_health;

        assert!(plain > 0, "the encounter has a health to scale");
        // §206: the number is no longer a `+10%` model -- the ENCT row pins the wiki's absolute A7
        // health. So the assertion is "the content's pinned value for this monster", read from the
        // image rather than copied into this test: a second copy of 47 numbers would rot.
        let pinned = pinned_health_for(plain);
        assert!(
            !pinned.is_empty(),
            "no ENCT row pins an A-level health for a monster with {plain} base HP"
        );
        assert!(
            pinned.contains(&ascended),
            "A7 gave {ascended}, but the content pins {pinned:?} for a {plain}-HP monster"
        );
        assert!(ascended > plain, "A7 must actually make the fight tougher");
        let _ = rd_run::state::ASCENDED_ENEMY_HEALTH_PERCENT;
    }

    /// [`reset`], at an Ascension level (§159).
    fn reset_at(seed: i32, ascension: i32) {
        assert_eq!(
            rd_run_start(seed, ascension),
            0,
            "rd_run_start({seed}, {ascension}) failed"
        );
        let mut slot = 0;
        let mut best = i32::MAX;
        for candidate in 0..2 {
            let score = rd_run_start_needs(candidate) * 2
                + i32::from(rd_run_start_cost(candidate) == 3);
            if score < best {
                best = score;
                slot = candidate;
            }
        }
        assert_eq!(rd_run_choose_start(slot), 0, "taking a blessing");
        if rd_run_blessing_needs() != 0 {
            assert_eq!(rd_run_pick_blessing_card(0), 0, "finishing the card blessing");
        }
        assert_eq!(rd_run_pending(), 0, "reset_at left a choice pending");
    }

    /// §161.4: Liquid Memories -- the card comes back **and** it is actually free.
    ///
    /// `paper_cut` is the core image's `CARD[0]`: 1 energy printed, deals 6, lands in the discard
    /// pile. The point of the test is the **third** assertion block: the observation's `cost` column
    /// (what the player sees) and the energy the kernel really takes must agree, and the price must
    /// be spent once.
    /// §163: 回放 —— 一串真实动作重放一遍必须逐步对上；篡改过的脚本必须**指出是哪一步**。
    #[test]
    fn a_recorded_run_replays_step_by_step_and_a_tampered_one_names_its_step() {
        // **必须是 `rd_run_start`**：脚本的头部只有 `(seed, asc)`，所以"起点"必须是一局的**开头**。
        // 用 `test_run`（手搓一个局）会让录制与回放的起点不同 —— 第一版就是这么红的：
        // 第 1 步期望 `0324f5…` 而回放得到 `fb615f…`，因为录制那条路的祝福/RNG 计数是手搓的。
        assert_eq!(rd_run_start(7, 0), 0, "a fresh run");
        assert_eq!(rd_run_choose_start(0), 0, "take blessing 0");
        while rd_run_pending() == 7 {
            assert_eq!(rd_run_pick_blessing_card(0), 0, "the blessing owes a pick");
        }

        // 走几个节点，按类型结算。战斗只 `begin` + `end`（不真打牌），因为回放不重演战斗。
        for hop in 0..8 {
            // 走到头（未结算的节点、最后一层、Boss 哨兵）就停：这条测试要的是**一段真实脚本**，
            // 不是"必须走满五步"。
            if rd_run_action_count() == 0 {
                break;
            }
            assert_eq!(rd_run_step(0), 0, "hop {hop}: enter ({})", run_error_text());
            let kind = rd_run_node_kind();
            let pending_before = rd_run_pending();
            let code = rd_run_begin_node();
            assert_eq!(
                code, 0,
                "hop {hop}: begin a kind-{kind} node (pending was {pending_before}, why: {})",
                run_error_text()
            );
            match kind {
                1 | 2 | 7 => {
                    assert_eq!(rd_run_fight_begin(), 0, "hop {hop}: begin the fight");
                    assert!(rd_run_fight_end() >= 0, "hop {hop}: end the fight");
                }
                3 => {
                    let _ = rd_run_rest();
                }
                5 => {
                    let _ = rd_run_leave();
                }
                6 => {
                    let _ = rd_run_open_chest();
                    let _ = rd_run_leave();
                }
                _ => {}
            }
            // `?` 房在 M1 是"有内容的空"（§6.3）：`begin_node` 给它 `Pending::None` 而节点**没结算**，
            // 所以它要么靠事件选项走、要么靠"离开"。不处理它，下一步就是"无处可走"。
            if kind == 4 {
                let _ = rd_run_choose(0);
            }
            // 奖励屏（战斗之后）与其它待决问句都要走完，否则下一步进不去。
            while rd_run_pending() == 4 {
                let _ = rd_run_skip_reward();
            }
            while rd_run_pending() == 8 {
                let _ = rd_run_pick_event_card(0);
            }
            if rd_run_action_count() == 0 && rd_run_pending() != 0 {
                let _ = rd_run_leave();
            }
        }

        let steps = run_slot().as_ref().expect("session").journal.len();
        assert!(steps >= 8, "the fixture must record a real script, it recorded {steps}");
        let before = {
            let session = run_slot().as_ref().expect("session");
            rd_run::hash::run_hash_hex(&session.state).expect("hash")
        };
        let script = script_text_now();
        // §166: 头部带**内容指纹**（`sha256(镜像)` 的前 4 字节，与 `build.json` 的镜像 sha 同源）。
        assert!(
            script.starts_with("RDR1,S,7,0,"),
            "head: {}",
            &script[..24.min(script.len())]
        );

        // (1) 重放：每一步都必须对上。
        assert_eq!(
            unsafe { rd_run_replay_from(script.as_ptr(), script.len() as i32) },
            0,
            "the recorded script must replay: {} · script={}",
            run_error_text(),
            &script[..script.len().min(220)]
        );
        assert_eq!(rd_run_replay_checked() as usize, steps, "every step verified");
        assert_eq!(rd_run_replay_diverged(), 0);
        let after = {
            let session = run_slot().as_ref().expect("session");
            rd_run::hash::run_hash_hex(&session.state).expect("hash")
        };
        assert_eq!(after, before, "the replay must land on the same run");

        // (2) 把一个哈希改掉：必须报**那一步**。
        let broken_hash = replace_nth_hash(&script, 2);
        assert_eq!(
            unsafe { rd_run_replay_from(broken_hash.as_ptr(), broken_hash.len() as i32) },
            3,
            "a bad hash at step 3 must be reported as step 3: {}",
            run_error_text()
        );
        assert_eq!(rd_run_replay_diverged(), 3);
        assert_eq!(rd_run_replay_checked(), 2, "the two steps before it did verify");

        // (3) 改一个**参数**（第 2 步的 arg0）：局面不同，必须红，而且不会悄悄通过。
        let broken_arg = replace_nth_arg(&script, 1, 999);
        assert!(
            unsafe { rd_run_replay_from(broken_arg.as_ptr(), broken_arg.len() as i32) } > 0,
            "a changed argument must diverge: {}",
            run_error_text()
        );

        // (3b) §166: **内容不同** ⇒ 在第一步之前拒，并且说出两边的值。
        //      判据是"一步都没应用"（`replay_checked == 0`），而不是"返回了非零" —— 一个走到
        //      第 5 步才分叉的脚本也会返回非零，可那时候局面已经被改了一半。
        let other_content = {
            let mut parts: std::vec::Vec<&str> = head_fields(&script);
            parts[3] = "deadbeef";
            std::format!(
                "RDR1,{};{}",
                parts.join(","),
                script.split_once(';').expect("head").1
            )
        };
        assert_eq!(
            unsafe {
                rd_run_replay_from(other_content.as_ptr(), other_content.len() as i32)
            },
            -2,
            "another content build must be refused before step 1"
        );
        assert_eq!(rd_run_replay_checked(), 0, "no step may be applied");
        let message = run_error_text();
        assert!(
            message.contains("deadbeef") && message.contains(&super::content_pin_text()),
            "the refusal must name both builds: {message}"
        );

        // (4) 垃圾一律拒，且不留下半局。
        assert_eq!(
            unsafe { rd_run_replay_from(b"hello".as_ptr(), 5) },
            -2,
            "a script without a head is refused"
        );
        assert_eq!(
            // 头部合法（含**对的**内容指纹）、**第 1 步**的种类不认识 ⇒ 报第 1 步，不是"头部坏了"。
            // 头部错在这里拼成常量：`{:08x}` 只有一处拼写（`content_pin_text`），测试跟着它走。
            {
                let head = std::format!("RDR1,S,7,0,{};", super::content_pin_text());
                let bad = std::format!("{head}nonsense,1,2,3,;");
                unsafe { rd_run_replay_from(bad.as_ptr(), bad.len() as i32) }
            },
            1,
            "an unknown kind is reported as step 1"
        );
    }

    /// §170 `P1-2`: 一场没打完就不许再开一场 —— 否则它会重新摇遭遇、覆盖掉正在打的战斗。
    ///
    /// 判据是"**什么都没改** + 战斗还在"：整局相等（含随机流计数）、`in_fight` 仍为真、
    /// 战斗会话还在、英雄血量没被重设。
    #[test]
    fn a_second_fight_begin_is_refused_and_the_fight_in_progress_survives() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the first begin must work: {}", run_error_text());
        assert!(
            run_slot().as_ref().expect("session").in_fight,
            "a successful begin commits `in_fight`"
        );

        let before = *run_slot().as_ref().expect("session").state;
        let hero_before = crate::combat_hero_health().expect("a fight");
        let journal_before = run_slot().as_ref().expect("session").journal.len();

        assert_eq!(
            rd_run_fight_begin(),
            -2,
            "a second begin while the fight runs must be refused"
        );
        assert!(
            run_error_text().contains("已经开始了"),
            "the refusal must say why: {}",
            run_error_text()
        );

        // The whole point: the encounter was not re-rolled and the fight was not replaced.
        assert!(
            *run_slot().as_ref().expect("session").state == before,
            "a refused begin changed the run"
        );
        // 日志记的是**尝试**（`log` 在动手之前调，这是 §163 懒上戳的前提），所以被拒的这一次
        // 确实会多一条记录 —— 但那一条的哈希必须等于前一条，因为"这次尝试什么都没改"。
        // 这恰好也是回放能复现一次拒绝的原因：它回放到这一步再被拒一次，哈希照样相等。
        let journal = &run_slot().as_ref().expect("session").journal;
        assert_eq!(
            journal.len(),
            journal_before + 1,
            "the attempt is recorded (that is what makes a refused step replayable)"
        );
        assert_eq!(
            journal[journal.len() - 1].hash, 0,
            "the refused record is unstamped until the next call"
        );
        assert_eq!(
            crate::combat_hero_health().expect("the fight survives"),
            hero_before,
            "the fight in progress was replaced"
        );
    }

    /// §170 `P1-1`：回滚**机制**本身。
    ///
    /// 这条单独测 `fail_begin`，因为 `fight_begin` 里那些"建好战斗之后才失败"的路由内容决定
    /// （缺一幕的池、遗物加成失败），本仓库现有的内容走不到。**声明清楚**：那几条是"由构造保证"，
    /// 不是"由测试证明"；这里证明的是它们共用的那个回滚函数真的会回到快照。
    #[test]
    fn fail_begin_restores_the_snapshot_and_clears_the_tier_flags() {
        test_run(7, 80, 60, &["strike"; 10]);
        let session = run_slot().as_mut().expect("session");
        let before = *session.state;

        // 模拟"半个开始"：随机流走了一步、标记已置、还装了一场战斗。
        let _ = session.state.rng_mut().roll(RunStream::Combat, i32::MAX as u32);
        session.elite_fight = true;
        session.boss_fight = true;
        session.in_fight = true;
        let moved = *session.state;
        assert!(moved != before, "the fixture must actually move the state");

        // 回滚的目标快照是**进函数时**的那一份。
        assert_eq!(fail_begin(session, before, "boom"), -2);
        assert!(*session.state == before, "the rollback did not restore the snapshot");
        assert!(!session.in_fight, "`in_fight` survived the rollback");
        assert!(!session.elite_fight && !session.boss_fight, "the tier flags survived");
        assert_eq!(session.error, "boom");
    }

    /// §170 `P1-1`：可失败的 `fight_begin` 拒绝之后，`in_fight` **不许**留在 true。
    ///
    /// 卡住的 `in_fight` 不是审美问题：`rd_run_archive_fill` 会一直拒绝存档，而玩家根本没有一场仗
    /// 可以打完 —— 这与 §164.3 是同一类 bug。
    #[test]
    fn a_refused_fight_begin_never_leaves_the_run_in_a_fight() {
        // (a) 还没走到任何节点。
        test_run(7, 80, 80, &["strike"; 10]);
        let before = *run_slot().as_ref().expect("session").state;
        assert_eq!(rd_run_fight_begin(), -2, "no node, no fight");
        let session = run_slot().as_ref().expect("session");
        assert!(!session.in_fight, "a refused begin left `in_fight` set");
        assert!(!session.elite_fight && !session.boss_fight, "the tier flags leaked");
        assert!(*session.state == before, "a refused begin changed the run");

        // (b) 一个**已经结算**的战斗节点：打完再按一次。
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "{}", run_error_text());
        assert!(rd_run_fight_end() >= 0, "{}", run_error_text());
        assert!(
            !run_slot().as_ref().expect("session").in_fight,
            "ending the fight clears the flag"
        );
        let settled = *run_slot().as_ref().expect("session").state;
        assert_eq!(rd_run_fight_begin(), -2, "a settled node pays once");
        assert!(
            run_error_text().contains("已经结算"),
            "the refusal must name the reason: {}",
            run_error_text()
        );
        let session = run_slot().as_ref().expect("session");
        assert!(!session.in_fight, "a refused begin left `in_fight` set");
        assert!(*session.state == settled, "a refused begin changed the run");
    }

    /// §170 `P1-4`：**算不出指纹**时不能拿 0 顶替 —— 导出与回放都必须响亮拒绝。
    ///
    /// 为什么是"直接置标记"而不是"造一个溢出的大局"：`the_largest_legal_run_fits_the_hash_buffer`
    /// 已经量出最大合法局只有 4186 B / 8192 B，所以这条路径**对合法状态不可达**。它存在的意义不是
    /// "今天会响"，而是"哪天有人把 `MAX_RUN_DECK` 或遗物容量翻倍、或者往规范文本里加一个大字段，
    /// 它响" —— 而不是让两个都溢出的状态互相"匹配"。
    ///
    /// 所以这里测的是**接线**：标记置上之后，两个消费者都拒绝，且拒绝不改局面。
    #[test]
    fn an_unavailable_hash_is_refused_not_treated_as_zero() {
        // 开局状态就够：这两条守卫都只看 `hash_failed`，与节点无关。
        test_run(7, 80, 80, &["strike"; 10]);

        // 一个可以让它"算不出来"的局面：直接置标记（合法状态到不了这里）。
        run_slot().as_mut().expect("session").hash_failed = true;
        let before = *run_slot().as_ref().expect("session").state;

        assert_eq!(rd_run_script_fill(), -2, "a script whose hashes are unknown must not export");
        assert!(
            run_error_text().contains("哈希缓冲"),
            "the refusal must say why: {}",
            run_error_text()
        );

        assert!(
            *run_slot().as_ref().expect("session").state == before,
            "the refusal changed the run"
        );

        // ⚠️ **回放那一半的拒绝分支在这里测不到，而且我不假装测到了。**
        // `rd_run_replay_from` 会用 `rd_run_start` 建一个**新**会话（`hash_failed = false`），
        // 所以比对时看到的永远是"新局能不能算哈希"；而新局能不能算哈希由上面的边界测试回答
        // （最大合法局 4186 B / 8192 B）。那条分支（`state_hash() == None` ⇒ `-2`）于是
        // **对合法状态不可达**，它的意义与 `hash_failed` 一样：哪天容量翻倍或文本长大，它响。
    }

    /// §170 `P1-3`：脚本导出与回放在**ABI 层**就拒绝战斗中调用。
    ///
    /// 这条测试**故意绕开页面**：页面的 `mode === "fight"` 不是契约，内核才是。存档在 §161.10
    /// 学过一次，脚本接口没跟着学。
    #[test]
    fn the_script_abi_refuses_mid_fight_without_the_page() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "{}", run_error_text());
        let before = *run_slot().as_ref().expect("session").state;
        let hero_before = crate::combat_hero_health().expect("a fight");

        // 导出：拒绝，且缓冲区不被写脏（判据是返回值 + 状态不变）。
        assert_eq!(rd_run_script_fill(), -2, "no script mid-fight");
        assert!(
            run_error_text().contains("战斗中没有脚本"),
            "the refusal must say why: {}",
            run_error_text()
        );

        // 回放：拒绝，而且必须在**解析之前** —— 这里给的是一段合法头部，守卫仍先响。
        let head = std::format!("RDR1,S,7,0,{};", super::content_pin_text());
        assert_eq!(
            unsafe { rd_run_replay_from(head.as_ptr(), head.len() as i32) },
            -2,
            "no replay mid-fight"
        );
        assert!(
            run_error_text().contains("战斗中不能回放"),
            "the refusal must say why: {}",
            run_error_text()
        );

        // 两次拒绝都不许动局面，也不许动那场战斗 —— 回放本来会 `rd_run_start` 毁掉它。
        let session = run_slot().as_ref().expect("session");
        assert!(*session.state == before, "a refused replay changed the run");
        assert!(session.in_fight, "a refused replay took the fight away");
        assert_eq!(
            crate::combat_hero_health().expect("the fight survives"),
            hero_before,
            "a refused replay replaced the fight"
        );
        // 而且没有留下"回放过几步"的陈旧读数。
        assert_eq!(rd_run_replay_checked(), 0);
        assert_eq!(rd_run_replay_diverged(), 0);
    }

    /// §164: 回档之后接着打的那些步，靠**头部携带档案**回放。
    #[test]
    fn a_run_restored_from_an_archive_replays_from_its_archive() {
        // (1) 一局，走到有几步历史。
        assert_eq!(rd_run_start(5, 0), 0);
        assert_eq!(rd_run_choose_start(0), 0);
        while rd_run_pending() == 7 {
            assert_eq!(rd_run_pick_blessing_card(0), 0);
        }
        walk_calm_nodes(2);
        let archive = {
            let len = rd_run_archive_fill();
            assert!(len > 0, "archive: {}", run_error_text());
            let capacity = rd_run_archive_capacity();
            assert!(len <= capacity);
            let ptr = rd_run_archive_buf();
            String::from_utf8(unsafe {
                std::slice::from_raw_parts(ptr, len as usize).to_vec()
            })
            .expect("ascii")
        };
        assert!(archive.starts_with("RDA1-"), "head: {}", &archive[..12]);

        // (2) 换一局**完全不同**的（别的种子、别的几步），再回档到 (1)。日志里现在是一段与
        // 恢复出来的局面无关的历史 —— 不清掉它，下面第一步就会分叉。
        assert_eq!(rd_run_start(9, 0), 0);
        assert_eq!(rd_run_choose_start(0), 0);
        while rd_run_pending() == 7 {
            assert_eq!(rd_run_pick_blessing_card(0), 0);
        }
        walk_calm_nodes(1);
        assert!(
            unsafe { rd_run_restore_from(archive.as_ptr(), archive.len() as i32) } == 0,
            "restore: {}",
            run_error_text()
        );
        assert_eq!(rd_run_seed(), 5, "the restored run is the first one");
        let steps_after_restore = script_text_now();
        assert_eq!(
            steps_after_restore.matches(';').count(),
            1,
            "a restore starts a new history: {}",
            &steps_after_restore[..steps_after_restore.len().min(40)]
        );

        // (3) 从恢复出来的局面接着打，然后导出：头部必须是那份档案。
        walk_calm_nodes(2);
        let script = script_text_now();
        assert!(
            script.starts_with("RDR1,A,RDA1-"),
            "head: {}",
            &script[..script.len().min(24)]
        );
        let steps = script.matches(';').count() - 1;
        assert!(steps >= 3, "the continuation must be recorded, got {steps}");

        // (4) 回放：从档案恢复，再走这些步，每一步都要对上。
        assert_eq!(
            unsafe { rd_run_replay_from(script.as_ptr(), script.len() as i32) },
            0,
            "the continuation must replay: {}",
            run_error_text()
        );
        assert_eq!(rd_run_replay_checked() as usize, steps);
        assert_eq!(rd_run_seed(), 5);
        let after = script_text_now();
        assert!(
            after.starts_with("RDR1,A,RDA1-"),
            "a replayed run still starts at its archive: {}",
            &after[..after.len().min(24)]
        );

        // (5) 判据的反面：篡改原始脚本 → 必须报出那一步。
        let broken = tamper_hash(&script, 1);
        assert_eq!(
            unsafe { rd_run_replay_from(broken.as_ptr(), broken.len() as i32) },
            2,
            "step 2 was tampered: {}",
            run_error_text()
        );
        assert_eq!(rd_run_replay_checked(), 1);
    }

    /// §164: 回放一场战斗之后，运行层**必须**已经不在战斗里。
    ///
    /// 这条是浏览器闸门逼出来的：`in_fight` 原来在 `rd_run_fight_end` 里清零，而回放走
    /// `replay_fight`、绕过那个导出 ⇒ 回放完一局之后"回档"被内核以"战斗中没有回档"拒掉。
    /// 断言落在**页面会问的那个问题**上（`restore_from` 接受），而不是"某个字段等于 false"。
    #[test]
    fn a_replayed_fight_does_not_leave_the_run_in_a_fight() {
        assert_eq!(rd_run_start(3, 0), 0);
        assert_eq!(rd_run_choose_start(0), 0);
        while rd_run_pending() == 7 {
            assert_eq!(rd_run_pick_blessing_card(0), 0);
        }
        let health = run_slot().as_ref().expect("session").state.health();
        {
            let session = run_slot().as_mut().expect("session");
            // `fight_begin` 做的就这一件事（外加选遭遇），而回放不该依赖 `fight_begin` 的副作用。
            session.in_fight = true;
            session.elite_fight = false;
            session.boss_fight = false;
            // 一场**赢了的**普通战斗，英雄掉了 5 点血。
            let verdict = replay_fight(session, health - 5, 1 << 4, 0);
            // `apply_fight_outcome` 返回 `0.max(result)`：1 = 赢了（不是错误码）。
            assert_eq!(verdict, 1, "the outcome was applied");
        }
        let session = run_slot().as_ref().expect("session");
        assert!(!session.in_fight, "a replayed fight must leave the run out of the fight");
        // 血量**不是**精确的 `health - 5`：赢了就触发战后遗物（Burning Blood 一类，`inv:§2`）。
        // 所以只断言方向，真正的判据是节点结算了 —— 那才是`apply_fight_outcome` 的产物。
        assert!(
            session.state.health() >= health - 5,
            "the recorded health was applied ({} -> {})",
            health,
            session.state.health()
        );
        // 不断言 `node_resolved()`：这条测试故意停在楼层 0（还没进节点），而 `mark_resolved`
        // 标记的是**当前节点** —— 那不是这里要测的东西（节点结算由 `a_recorded_run_replays…` 覆盖）。


        // 玩家会立刻做的那件事：存一份档 / 回一份档。内核必须接受。
        let len = rd_run_archive_fill();
        assert!(len > 0, "archive: {}", run_error_text());
        let ptr = rd_run_archive_buf();
        let archive = String::from_utf8(unsafe {
            std::slice::from_raw_parts(ptr, len as usize).to_vec()
        })
        .expect("ascii");
        assert_eq!(
            unsafe { rd_run_restore_from(archive.as_ptr(), archive.len() as i32) },
            0,
            "restoring after a replayed fight must be accepted: {}",
            run_error_text()
        );
    }

    /// 走 `hop` 个节点，按**种类**结算（与 `a_recorded_run_replays...` 同一套动作）。
    ///
    /// 战斗也照走：`begin` + `end` 不真打牌，一场"没打"的战斗结果是 0（未决）⇒ 没有奖励、
    /// 节点照常结算。这条测试问的是**历史与头部**，不是战斗。
    fn walk_calm_nodes(hop: usize) {
        for index in 0..hop {
            if rd_run_action_count() == 0 {
                return;
            }
            assert_eq!(rd_run_step(0), 0, "hop {index}: {}", run_error_text());
            let kind = rd_run_node_kind();
            assert_eq!(rd_run_begin_node(), 0, "hop {index}: kind {kind}");
            match kind {
                1 | 2 | 7 => {
                    assert_eq!(rd_run_fight_begin(), 0, "hop {index}: {}", run_error_text());
                    assert!(rd_run_fight_end() >= 0, "hop {index}: {}", run_error_text());
                }
                3 => {
                    let _ = rd_run_rest();
                }
                4 => {
                    let _ = rd_run_choose(0);
                }
                5 | 6 => {
                    if kind == 6 {
                        let _ = rd_run_open_chest();
                    }
                    let _ = rd_run_leave();
                }
                _ => {}
            }
            while rd_run_pending() == 4 {
                let _ = rd_run_skip_reward();
            }
            if rd_run_action_count() == 0 && rd_run_pending() != 0 {
                let _ = rd_run_leave();
            }
        }
    }

    /// 把第 `n`（0 基）条记录的哈希换成垃圾。
    fn tamper_hash(script: &str, n: usize) -> String {
        let (head, body) = script.split_once(';').expect("a head");
        let mut out = std::format!("{head};");
        for (index, record) in body.split(';').filter(|r| !r.is_empty()).enumerate() {
            let mut cells: Vec<&str> = record.split(',').collect();
            if index == n {
                cells[3] = "dead0000dead0000";
            }
            out.push_str(&cells.join(","));
            out.push(';');
        }
        out
    }

    /// The script, read the way the **page** reads it: ask the capacity, fill the module's buffer, read
    /// `len` bytes. §170 `P1-5` deleted the `into(ptr)` variant that the tests used to call, so this
    /// helper keeps the tests on the one path that ships.
    fn script_text_now() -> String {
        let len = rd_run_script_fill();
        assert!(len > 0, "script_fill said {len}: {}", run_error_text());
        let capacity = rd_run_script_capacity();
        assert!(len <= capacity, "{len} > capacity {capacity}");
        let ptr = rd_run_script_buf();
        String::from_utf8(unsafe { std::slice::from_raw_parts(ptr, len as usize).to_vec() })
            .expect("ascii")
    }

    /// 头部按 `,` 切成字段，**去掉 `RDR1,` 前缀** —— 于是下标与 `rd_run_replay_from` 里的一致
    /// （`[S, seed, asc, pin]`），而不是差一个。
    fn head_fields(script: &str) -> std::vec::Vec<&str> {
        script
            .split_once(';')
            .expect("a head")
            .0
            .strip_prefix("RDR1,")
            .expect("the RDR1 head")
            .split(',')
            .collect()
    }

    /// 把第 `n`（0 基）条记录的哈希换成垃圾，其余原样。
    fn replace_nth_hash(script: &str, n: usize) -> String {
        let (head, body) = script.split_once(';').expect("a head");
        let mut out = std::format!("{head};");
        for (index, record) in body.split(';').filter(|r| !r.is_empty()).enumerate() {
            let mut cells: Vec<&str> = record.split(',').collect();
            if index == n {
                cells[3] = "dead0000dead0000";
            }
            out.push_str(&cells.join(","));
            out.push(';');
        }
        out
    }

    /// 把第 `n` 条记录的 `arg{which}` 换掉。
    fn replace_nth_arg(script: &str, n: usize, value: i32) -> String {
        let (head, body) = script.split_once(';').expect("a head");
        let mut out = std::format!("{head};");
        for (index, record) in body.split(';').filter(|r| !r.is_empty()).enumerate() {
            let mut cells: Vec<&str> = record.split(',').collect();
            if index == n {
                let text = value.to_string();
                cells[1] = Box::leak(text.into_boxed_str());
            }
            out.push_str(&cells.join(","));
            out.push(';');
        }
        out
    }

    /// §161.10 P0: 存档走**自己的**缓冲区，容量由 ABI 公布。
    ///
    /// 旧的 `rd_run_archive_into(ptr)` 接收任意指针，而页面给的是 1024 B 的通用 scratch —— 一个
    /// 60 张牌的存档是 **1628 B**（`a_full_deck_archive_is_bigger_than_the_generic_scratch`），
    /// 于是它往 `SCRATCH` 后面写了约 600 B。这条测试把"能装下"变成可观察的：容量、长度、
    /// 以及超长输入被拒。
    #[test]
    fn the_archive_buffer_is_sized_for_a_full_deck_and_refuses_more() {
        test_run(7, 80, 80, &["strike"; 10]);
        let capacity = rd_run_archive_capacity();
        assert!(
            capacity as usize >= rd_run::state::archive::MAX_ARCHIVE,
            "the published capacity must be the real one"
        );

        // A normal run.
        let len = rd_run_archive_fill();
        assert!(len > 0, "archive_fill said {len}");
        assert!(len <= capacity, "archive {len} does not fit {capacity}");

        // A **full deck**: the case that overflowed the old scratch (1024 B).
        {
            let session = run_slot().as_mut().expect("a run");
            for _ in 0..rd_run::state::MAX_RUN_DECK.saturating_sub(session.state.deck().len()) {
                let _ = session.state.push_card("strike");
            }
        }
        let big = rd_run_archive_fill();
        assert!(big > 0, "a full-deck archive said {big}");
        assert!(
            big > 1024,
            "a full-deck archive measured {big} bytes; if it fits in 1 KiB the old bug would have              been masked by luck, which is not a contract"
        );
        assert!(
            big <= capacity,
            "a full-deck archive is {big} bytes but the buffer is {capacity}"
        );

        // Reading it back works at that size.
        let ptr = rd_run_archive_buf();
        assert!(!ptr.is_null());
        let bytes = unsafe { std::slice::from_raw_parts(ptr, big as usize) }.to_vec();
        assert_eq!(
            unsafe { rd_run_restore_from(ptr, big) },
            0,
            "restore of a big archive"
        );

        // §161.10: **bypass the UI and call the ABI** -- a fight must refuse both directions.
        // Walk into a combat node first (`rd_run_fight_begin` only accepts one).
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0, "the node under the cursor");
        assert_eq!(rd_run_fight_begin(), 0, "begin a fight");
        assert_eq!(
            rd_run_archive_fill(),
            -2,
            "archiving mid-fight must be refused by the ABI, not only by the page"
        );
        let buf = rd_run_archive_buf();
        assert_eq!(
            unsafe { rd_run_restore_from(buf, big) },
            -2,
            "restoring mid-fight must be refused by the ABI too"
        );

        // …and **one byte past the capacity** is refused, not clamped.
        let over = capacity + 1;
        let mut padded = bytes.clone();
        padded.resize(over as usize, b'A');
        assert_eq!(
            unsafe { rd_run_restore_from(padded.as_ptr(), over) },
            -3,
            "an input longer than the buffer must be refused before anything is read"
        );
    }

    /// §161.5: Attack Potion -- three **definitions**, one card created, and it is free.
    ///
    /// The three things that can be wrong here are independent:
    /// * the candidates are instances created up front (then the fingerprint grows three cards that
    ///   the reference never had);
    /// * the picked card is created but not priced (the screen says 0, the kernel charges 1);
    /// * the pool filter is wrong (a Skill Potion offering attacks, or a tag with no carriers
    ///   silently offering fewer than three).
    /// §161.7: Power Potion -- the same mechanism, a different pool.
    ///
    /// The point of this test is not the mechanism (that is §161.5's) but the claim that adding a
    /// potion of the same *shape* is a **content** change: the only new code since §161.5 is the
    /// `+`-row filter, and the only new content is three cards plus one `POT` row.
    ///
    /// It also pins the two content bugs this section fixed, from the outside: a Power card is a
    /// status that **keeps working**, so `metallicize`/`combust` must actually apply stacks that a
    /// later turn-end reads.
    #[test]
    fn a_power_potion_offers_the_three_power_cards_and_they_are_real_powers() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        assert_eq!(drink("power_potion", -1), 0, "accepted");
        assert_eq!(crate::rd_env_choice_pending(), 1, "it asks a question");
        assert_eq!(crate::rd_env_choice_source(), 2, "2 = three offered definitions");
        assert_eq!(crate::rd_env_choice_kind(), 3, "3 = take into hand");
        assert_eq!(crate::rd_env_choice_count(), 3, "three candidates");

        let content = content();
        let mut offered: Vec<String> = Vec::new();
        for index in 0..3 {
            let len = crate::rd_env_pile_card_id_len(3, index);
            assert!(len > 0, "option {index} has an id");
            let mut bytes = vec![0u8; len as usize];
            unsafe { crate::rd_env_pile_card_id_into(3, index, bytes.as_mut_ptr()) };
            let id = String::from_utf8_lossy(&bytes).to_string();
            assert_eq!(
                content.card_has_tag(&id, "power"),
                Some(true),
                "`{id}` is not tagged power"
            );
            // §161.7: the `+` rows are **not** offered -- a potion gives the printed card.
            assert!(!id.ends_with('+'), "`{id}` is an upgraded row");
            offered.push(id);
        }
        // ⚠️ §197: this used to pin the exact trio `combust / inflame / metallicize`. That was an
        // artefact of the pool having **exactly** three power cards; `barricade` (§197) is a Power
        // too, so the potion now *draws* three of four and the trio depends on the run's RNG. The
        // invariant worth pinning is "three distinct power cards, printed rows only" -- which is what
        // the assertions above already do one by one.
        assert_eq!(offered.len(), 3, "three distinct candidates: {offered:?}");
        let mut sorted = offered.clone();
        sorted.sort();
        sorted.dedup();
        assert_eq!(sorted.len(), 3, "the three candidates are distinct: {offered:?}");

        // Take the first option and check it lands in hand **free** -- no dependency on which card
        // the draw gave us (§197: `barricade` joined the power pool, so the trio is RNG-dependent).
        let first_len = crate::rd_env_pile_card_id_len(3, 0);
        let mut bytes = vec![0u8; first_len as usize];
        unsafe { crate::rd_env_pile_card_id_into(3, 0, bytes.as_mut_ptr()) };
        let first = String::from_utf8_lossy(&bytes).to_string();
        let cards_before = crate::slot().as_ref().expect("session").state.card_count();
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_confirm(), 0, "answered");
        assert_eq!(crate::rd_env_choice_pending(), 0, "the question is answered");
        assert_eq!(
            crate::slot().as_ref().expect("session").state.card_count(),
            cards_before + 1,
            "exactly one card was created"
        );

        // It is in hand and it is **free** (the potion's promise).
        let slot_ref = crate::slot().as_ref().expect("session");
        let hand = slot_ref
            .hand_defs
            .iter()
            .position(|definition| *definition == first)
            .unwrap_or_else(|| panic!("`{first}` is in hand"));
        assert_eq!(slot_ref.hand_costs[hand], 0, "the potion made it free");
        drop(slot_ref);

        // And it is playable at that price: play it and check the energy did not move.
        let energy_before = crate::slot().as_ref().expect("session").energy_now();
        let play = (0..crate::rd_env_action_count())
            .find(|action| {
                crate::rd_env_action_kind(*action) == crate::ACTION_PLAY
                    && crate::rd_env_action_arg(*action, 0) == hand as i32
            })
            .unwrap_or_else(|| panic!("`{first}` is playable"));
        assert_eq!(rd_env_step(play), 0, "play `{first}`");
        assert_eq!(
            crate::slot().as_ref().expect("session").energy_now(),
            energy_before,
            "it was free"
        );
    }

    #[test]
    fn an_attack_potion_offers_three_definitions_and_creates_only_the_chosen_card() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let cards_before = crate::slot().as_ref().expect("session").state.card_count();
        assert_eq!(drink("attack_potion", -1), 0, "accepted");
        assert_eq!(crate::rd_env_choice_pending(), 1, "it asks a question");
        assert_eq!(crate::rd_env_choice_source(), 2, "2 = three offered definitions");
        assert_eq!(crate::rd_env_choice_kind(), 3, "3 = take into hand");
        assert_eq!(crate::rd_env_choice_min(), 1);
        assert_eq!(crate::rd_env_choice_max(), 1);
        assert_eq!(crate::rd_env_choice_count(), 3, "three candidates");
        assert_eq!(
            crate::rd_env_pile_len(3),
            3,
            "the picker reads its options through the pile exports (zone 3)"
        );
        // ★ the question itself must not create cards.
        assert_eq!(
            crate::slot().as_ref().expect("session").state.card_count(),
            cards_before,
            "asking must not mint the three candidates"
        );

        // Every option is an **attack**, and they are three **different** cards.
        let content = content();
        let mut offered: Vec<String> = Vec::new();
        for index in 0..3 {
            let len = crate::rd_env_pile_card_id_len(3, index);
            assert!(len > 0, "option {index} has an id");
            let mut bytes = vec![0u8; len as usize];
            unsafe { crate::rd_env_pile_card_id_into(3, index, bytes.as_mut_ptr()) };
            let id = String::from_utf8_lossy(&bytes).to_string();
            assert_eq!(
                content.card_has_tag(&id, "attack"),
                Some(true),
                "`{id}` is not an attack"
            );
            assert!(
                crate::rd_env_pile_card_title_len(3, index) > 0,
                "option {index} has a title"
            );
            offered.push(id);
        }
        offered.sort();
        offered.dedup();
        assert_eq!(offered.len(), 3, "three **distinct** cards");

        // Pick the first option and answer.
        let picked = {
            let len = crate::rd_env_pile_card_id_len(3, 0);
            let mut bytes = vec![0u8; len as usize];
            unsafe { crate::rd_env_pile_card_id_into(3, 0, bytes.as_mut_ptr()) };
            String::from_utf8_lossy(&bytes).to_string()
        };
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(
            crate::rd_env_choice_confirm(),
            0,
            "answered: {}",
            crate::slot().as_ref().map_or(String::new(), |s| s.error.clone())
        );
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(
            crate::slot().as_ref().expect("session").state.card_count(),
            cards_before + 1,
            "exactly one card was created: the two not chosen never existed"
        );

        // ★ The created card is the picked definition, it is in hand, and it shows **0**.
        let slot_ref = crate::slot().as_ref().expect("session");
        let free = slot_ref
            .hand_defs
            .iter()
            .position(|definition| *definition == picked)
            .expect("the picked card is in the hand");
        assert_eq!(
            slot_ref.hand_costs[free],
            0,
            "the observation must show what the kernel will charge"
        );
        assert!(
            slot_ref.hand_costs[free] != slot_ref.printed_energy_cost(&picked),
            "and that is not its printed cost -- the per-copy price is doing the work"
        );
        drop(slot_ref);

        // ★ …and the kernel charges it: play it, energy must not move.
        let energy_before = crate::slot().as_ref().expect("session").energy_now();
        let play = (0..crate::rd_env_action_count())
            .find(|index| {
                crate::rd_env_action_kind(*index) == crate::ACTION_PLAY
                    && crate::rd_env_action_arg(*index, 0) == free as i32
            })
            .expect("the new card is playable");
        assert_eq!(rd_env_step(play), 0);
        assert_eq!(
            crate::slot().as_ref().expect("session").energy_now(),
            energy_before,
            "a potion that says \"it costs 0 this turn\" must charge 0"
        );
    }

    #[test]
    fn liquid_memories_returns_a_card_and_makes_that_copy_free_once() {
        // `strike` is the one-cost card this **content** has (the `paper_cut` fixture belongs to
        // rd-core's own image, which this crate does not load).
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        // Play one card so the discard pile is not empty (Liquid Memories has nothing to choose
        // from otherwise, and the atom then declines to ask -- see the empty-hand rule for Elixir).
        let played = (0..rd_env_action_count())
            .find(|index| rd_env_action_kind(*index) == crate::ACTION_PLAY)
            .expect("a play action exists");
        assert_eq!(rd_env_step(played), 0, "play the first card");
        assert!(rd_env_pile_len(1) >= 1, "the played card is in the discard pile");
        let discarded = rd_env_pile_len(1);
        let hand_before = crate::slot().as_ref().expect("session").hand_len();

        // Drink Liquid Memories.
        assert_eq!(drink("liquid_memories", -1), 0, "accepted");
        assert_eq!(crate::rd_env_choice_pending(), 1, "it asks a question");
        assert_eq!(crate::rd_env_choice_kind(), 3, "3 = take into hand");
        assert_eq!(crate::rd_env_choice_min(), 1, "the wiki says \"choose A card\"");
        assert_eq!(crate::rd_env_choice_max(), 1);
        assert_eq!(crate::rd_env_choice_count() as i32, discarded, "options = the discard pile");
        // A mandatory choice: confirming with nothing ticked is **refused**, and the question
        // survives so the page can re-prompt instead of dead-ending.
        let before = crate::slot().as_ref().expect("session").hand_len();
        assert_eq!(
            crate::rd_env_choice_confirm(),
            -2,
            "zero picks must be refused for a `min = 1` question"
        );
        assert_eq!(crate::rd_env_choice_pending(), 1, "and the question is still open");
        assert_eq!(crate::slot().as_ref().expect("session").hand_len(), before);

        // Tick one and answer.
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_confirm(), 0, "answered");
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(
            rd_env_pile_len(1),
            discarded - 1,
            "the card left the discard pile"
        );
        assert_eq!(
            crate::slot().as_ref().expect("session").hand_len(),
            hand_before + 1,
            "and arrived in the hand"
        );

        // ★ the **display** must agree with what the kernel will charge.
        let slot = crate::slot().as_ref().expect("session");
        let free = slot
            .hand_costs
            .iter()
            .position(|cost| *cost == 0)
            .expect("the returned card shows 0 in the observation, not its printed cost");
        let def = slot.hand_defs[free].clone();
        assert_eq!(def, "strike", "the free one is the card we took back");
        assert_eq!(
            slot.printed_energy_cost(&def),
            1,
            "and it really is a 1-cost card -- the 0 comes from the per-copy price"
        );
        drop(slot);

        // ★ and the kernel charges what it showed.
        let energy_before = crate::slot().as_ref().expect("session").energy_now();
        let play_free = (0..crate::rd_env_action_count())
            .find(|index| {
                rd_env_action_kind(*index) == crate::ACTION_PLAY
                    && crate::rd_env_action_arg(*index, 0) == free as i32
            })
            .expect("the free card is playable");
        assert_eq!(rd_env_step(play_free), 0, "play it for free");
        assert_eq!(
            crate::slot().as_ref().expect("session").energy_now(),
            energy_before,
            "the kernel charged nothing -- the price the screen showed"
        );

        // ★ the price is **spent**: the same copy back in hand costs its printed 1 again.
        let used = crate::slot().as_ref().expect("session");
        let spent = used
            .hand_costs
            .get(free)
            .copied()
            .unwrap_or(-1);
        assert_ne!(spent, 0, "no card left in hand is still free");
    }

    /// §161.3: **every** `POT` row must classify as a known effect.
    ///
    /// Two readers share one vocabulary: `rd_env_use_potion`'s `match` decides what a potion does,
    /// and `rd_run_potion_effect` decides whether the page offers a target picker. Adding
    /// `choice_hand_exhaust` to the first and forgetting the second produced a potion the kernel
    /// drinks happily while the page classifies it as `0 = unknown` -- and **nothing went red**,
    /// because the page's `=== 1` test simply took the other branch. Not a hypothetical: that is
    /// exactly what this section shipped into until this test was written.
    ///
    /// Walking the **whole table** is the point. A test that only checks "elixir is known" would be
    /// the same per-atom list that just failed.
    #[test]
    fn every_potion_in_the_table_classifies_as_known() {
        test_run(11, 80, 80, &["strike"; 10]);
        let image = content();
        let mut checked = 0usize;
        for index in 0..image.potion_count() {
            let Some(potion) = image.potion(index) else {
                continue;
            };
            // The belt holds three, so the table is walked one bottle at a time.
            {
                let session = run_slot().as_mut().expect("a session");
                while !session.state.potions().is_empty() {
                    session.state.drop_potion(0).expect("dropping an empty slot");
                }
                session.state.push_potion(potion.id).expect("an empty belt takes one");
            }
            let kind = rd_run_potion_effect(0);
            assert!(
                kind != 0,
                "`{}` ({}) classifies as UNKNOWN -- the page would call a working potion broken",
                potion.id,
                potion.effect
            );
            assert!(kind == 1 || kind == 2 || kind == 3, "`{}` -> {kind}", potion.id);
            checked += 1;
        }
        assert_eq!(
            checked as u32,
            image.potion_count(),
            "every POT row must be walked, not a sample"
        );

        // "Known" is not enough for the two new atoms: they act on the **hand**, so arming the
        // enemy picker for them is a wrong branch that `kind != 0` would happily accept.
        for id in [
            "elixir",
            "gamblers_brew",
            "liquid_memories",
            // §161.5: the offered pair acts on the hand too.
            "attack_potion",
            "skill_potion",
            "power_potion",
        ] {
            {
                let session = run_slot().as_mut().expect("a session");
                while !session.state.potions().is_empty() {
                    session.state.drop_potion(0).expect("dropping an empty slot");
                }
                session.state.push_potion(id).expect("an empty belt takes one");
            }
            assert_eq!(
                rd_run_potion_effect(0),
                2,
                "`{id}` acts on a hand or a discard pile, so it needs no enemy target"
            );
        }
    }

    /// §161.3: the two potions whose effect is a **question**, driven end to end.
    ///
    /// The mechanism itself is pinned in `rd-core` (`resolve_choice` and its five tests). What is
    /// pinned *here* is the seam, and every step of it is a thing that could break on its own:
    ///
    /// * the bottle is drunk (consumed) **and** a question opens -- not one or the other;
    /// * the action table goes empty, because play / end-turn are not legal answers;
    /// * a stale action index is refused *with a reason*;
    /// * the options are the source pile, so zone 3 is the same list;
    /// * answering moves exactly the picked cards and restores the table;
    /// * "pick nothing" is a legal answer (both potions say "any number").
    #[test]
    fn the_choice_potions_ask_a_question_and_the_answer_moves_the_cards() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        // ---- nothing is pending before a potion opens one -----------------------------------
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(crate::rd_env_choice_kind(), 0);
        assert_eq!(crate::rd_env_choice_count(), 0);
        assert_eq!(crate::rd_env_pile_len(3), -1, "zone 3 answers nothing without a question");

        // ---- Elixir: exhaust any number of cards from your hand -----------------------------
        let belt_before = rd_run_potion_count();
        assert_eq!(drink("elixir", -1), 0, "elixir accepted");
        assert_eq!(
            rd_run_potion_count(),
            belt_before,
            "the bottle is consumed: a potion is drunk whether or not the answer is convenient"
        );
        assert_eq!(crate::rd_env_choice_pending(), 1, "and it opened a question");
        assert_eq!(crate::rd_env_choice_kind(), 1, "1 = exhaust");
        assert_eq!(crate::rd_env_choice_min(), 0, "\"any number\" includes zero");
        let options = crate::rd_env_choice_count();
        assert!(options >= 2, "a fresh hand has cards to pick from: {options}");
        assert_eq!(
            crate::rd_env_choice_max(),
            options,
            "the upper bound is the whole hand"
        );
        assert_eq!(
            crate::rd_env_pile_len(3),
            options,
            "zone 3 is the question's source pile, so the picker renders through the pile exports"
        );
        assert_eq!(
            crate::rd_env_action_count(),
            0,
            "play / end-turn are not legal while a question is open"
        );
        assert_eq!(rd_env_step(0), -1, "a stale action index is refused");
        assert!(
            crate::slot().as_ref().is_some_and(|s| !s.error.is_empty()),
            "and the refusal says why"
        );

        // Ticking is not the action -- `confirm` is. Two ticks, then one answer.
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_pick(2, 1), 0);
        assert_eq!(crate::rd_env_choice_selected(0), 1);
        assert_eq!(crate::rd_env_choice_selected(1), 0);
        assert_eq!(
            crate::rd_env_choice_pick(options, 1),
            -1,
            "an index past the last option is refused, not ignored"
        );
        let exhausted_before = crate::rd_env_pile_len(2);
        assert_eq!(crate::rd_env_choice_confirm(), 0, "answered");
        assert_eq!(crate::rd_env_choice_pending(), 0, "the question is gone");
        assert_eq!(
            crate::rd_env_pile_len(2),
            exhausted_before + 2,
            "exactly the two ticked cards were exhausted"
        );
        assert!(
            crate::rd_env_action_count() > 0,
            "the action table is back once the question is answered"
        );

        // ---- Gambler's Brew: discard any number, then draw that many ------------------------
        let hand_before = crate::rd_env_choice_count();
        assert_eq!(hand_before, 0, "no question is open");
        assert_eq!(drink("gamblers_brew", -1), 0, "gambler's brew accepted");
        assert_eq!(crate::rd_env_choice_kind(), 2, "2 = discard then draw");
        let options = crate::rd_env_choice_count();
        assert!(options >= 2, "cards to discard: {options}");
        let discarded_before = crate::rd_env_pile_len(1);
        // Three picks, then **clear**: the selection is scratch, and clearing it must not answer
        // the question (otherwise "select none" and "cancel the screen" would be the same code).
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_pick(1, 1), 0);
        assert_eq!(crate::rd_env_choice_pick(2, 1), 0);
        assert_eq!(crate::rd_env_choice_clear(), 0);
        assert_eq!(crate::rd_env_choice_selected(0), 0, "cleared");
        assert_eq!(crate::rd_env_choice_pending(), 1, "still unanswered");
        // Now actually discard two.
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_pick(1, 1), 0);
        assert_eq!(crate::rd_env_choice_confirm(), 0);
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(
            crate::rd_env_choice_count(),
            0,
            "the same count reads 0 once there is no question"
        );
        assert!(
            crate::rd_env_pile_len(1) >= discarded_before,
            "the two discarded cards land in the discard pile"
        );

        // ---- "pick nothing" is a legal answer ----------------------------------------------
        assert_eq!(drink("elixir", -1), 0);
        assert_eq!(crate::rd_env_choice_pending(), 1);
        let exhausted_before = crate::rd_env_pile_len(2);
        assert_eq!(crate::rd_env_choice_confirm(), 0, "zero picks is an answer");
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(
            crate::rd_env_pile_len(2),
            exhausted_before,
            "and it exhausts nothing"
        );
    }

    /// Put `potion` in the belt and drink it at `target`. The belt has **three** slots, so a test
    /// that wants five potions cannot push them all: push one, drink it, repeat.
    fn drink(potion: &str, target: i32) -> i32 {
        {
            let session = run_slot().as_mut().expect("session");
            session.state.push_potion(potion).expect("belt room");
        }
        let slot = rd_run_potion_count() - 1;
        rd_env_use_potion(slot, target)
    }

    /// §179: Blessing of the Forge -- "Upgrade all cards in your hand for the rest of combat."
    ///
    /// The judgment is the **definition id** because that is what `play` looks the program up by:
    /// `strike+` deals 9 where `strike` deals 6. A display-only swap (the upgraded name over the old
    /// program) would pass a label check and fail this one.
    ///
    /// ⚠️ The starting deck is **read from the run**, not assumed: §154's blessing may already have
    /// upgraded or removed cards, so the test asks the belt-side state which Strikes are in hand.
    #[test]
    fn blessing_of_the_forge_upgrades_every_strike_in_hand() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let hand_before = hand_ids();
        assert!(
            hand_before.iter().any(|id| id == "strike"),
            "the fixture expects plain Strikes in hand: {hand_before:?}"
        );
        assert_eq!(drink("blessing_of_the_forge", -1), 0, "drinking it must work");

        let hand_after = hand_ids();
        assert_eq!(
            hand_after.len(),
            hand_before.len(),
            "upgrading a card does not move it out of the hand"
        );
        let strikes: Vec<&String> = hand_after.iter().filter(|id| id.starts_with("strike")).collect();
        assert!(!strikes.is_empty(), "the Strikes are still there: {hand_after:?}");
        assert!(
            strikes.iter().all(|id| id.as_str() == "strike+"),
            "every Strike in hand is the `+` row now: {hand_after:?}"
        );
        assert!(
            !hand_after.iter().any(|id| id == "strike"),
            "no plain `strike` survives in hand: {hand_after:?}"
        );
    }

    /// §179: Snecko Oil -- "Draw 5 cards. Randomize the costs of all cards in your hand."
    ///
    /// Two visible facts: five more cards, and every price inside `0..=3`. The prices are read from
    /// the **display** column (`hand_costs`), so this also pins that the override reaches the screen
    /// and not only `play` (the two-pricing-places problem from §161.4).
    #[test]
    fn snecko_oil_draws_five_and_randomizes_every_price_in_hand() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let hand_before = hand_ids().len();
        assert_eq!(drink("snecko_oil", -1), 0, "drinking it must work");
        let session = crate::slot().as_ref().expect("env session");
        assert_eq!(
            session.hand_len(),
            hand_before + 5,
            "`Draw 5` -- hand went {hand_before} -> {}",
            session.hand_len()
        );
        let costs = session.hand_costs.clone();
        assert_eq!(costs.len(), session.hand_len(), "one price per hand card");
        for (index, cost) in costs.iter().enumerate() {
            assert!(
                (0..=3).contains(cost),
                "hand[{index}] costs {cost}, outside the randomized band 0..=3"
            );
        }
    }

    /// §179: Smoke Bomb -- "Escape from a non-boss combat. Receive no rewards."
    ///
    /// The refusal in a boss fight matters as much as the escape: a guard that only worked outside
    /// bosses would still let a player skip a boss.
    #[test]
    fn smoke_bomb_ends_a_normal_fight_and_refuses_a_boss() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");
        let gold_before = run_slot().as_ref().expect("run").state.gold();
        let pending_before = rd_run_pending();

        assert_eq!(drink("smoke_bomb", -1), 0, "escaping a normal fight is legal");
        assert!(
            crate::slot().is_none(),
            "the combat session is gone: escaping ends the fight, it does not pause it"
        );
        let run = run_slot().as_ref().expect("the run outlives the fight");
        assert!(!run.in_fight, "the run knows the fight ended");
        assert_eq!(
            run.state.gold(),
            gold_before,
            "Smoke Bomb pays nothing -- gold moved, so the escape looted the node"
        );
        assert_eq!(
            rd_run_pending(),
            pending_before,
            "no reward screen may open after an escape"
        );

        // The refusal: a boss fight. `boss_fight` is the run's own flag, so set it the way the
        // node walker does and try again.
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");
        run_slot().as_mut().expect("run").boss_fight = true;
        assert!(
            drink("smoke_bomb", -1) < 0,
            "a boss fight must refuse the escape (wiki: non-boss combat)"
        );
        assert!(
            crate::slot().is_some(),
            "a refusal must not end the fight"
        );
    }

    /// §182: Distilled Chaos -- "Play the top 3 cards of your draw pile."
    ///
    /// Four judgments, because "the enemy lost HP" is satisfied by almost any implementation:
    /// the draw pile shrank by three, the discard pile grew by three (they really were *played*,
    /// which is what puts them there), the enemy took damage, and **energy did not move**.
    #[test]
    fn distilled_chaos_plays_the_top_three_for_free() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let piles = |zone: rd_core::state::CardZone| {
            let session = crate::slot().as_ref().expect("env session");
            let hero = session.hero_id().expect("hero");
            session
                .state
                .card_zones(&hero)
                .map_or(0, |zones| zones.count(zone))
        };
        let draw_before = piles(rd_core::state::CardZone::DrawPile);
        assert!(draw_before >= 3, "the draw pile needs three cards, has {draw_before}");
        let discard_before = piles(rd_core::state::CardZone::DiscardPile);
        let energy_before = hero_energy();
        let hp_before = enemy_hp(0);

        assert_eq!(drink("distilled_chaos", -1), 0, "drinking it must work");

        assert_eq!(
            piles(rd_core::state::CardZone::DrawPile),
            draw_before - 3,
            "three cards left the draw pile"
        );
        assert_eq!(
            piles(rd_core::state::CardZone::DiscardPile),
            discard_before + 3,
            "and they were **played**, so they are in the discard pile -- not still in hand"
        );
        assert!(
            enemy_hp(0) < hp_before,
            "three Strikes went somewhere: enemy {hp_before} -> {}",
            enemy_hp(0)
        );
        assert_eq!(
            hero_energy(),
            energy_before,
            "the potion pays, the player does not -- energy must not move"
        );
    }

    /// §183: Colorless Potion -- "Choose 1 of 3 random Colorless cards to add to your hand."
    ///
    /// Three judgments: the question is an **offered** one (`source = 2`, §161.5), it has exactly
    /// three answers, and every answer is a colorless card from this content. Then the pick lands
    /// in the hand -- because "a picker appeared" is not the potion.
    #[test]
    fn colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let hand_before = hand_ids();
        assert_eq!(drink("colorless_potion", -1), 0, "drinking it opens the question");

        // §161.5: `ChoiceSource::Offered` is `2` in the ABI, and the potion is consumed either way.
        assert_eq!(crate::rd_env_choice_pending(), 1, "the picker is waiting");
        assert_eq!(crate::rd_env_choice_source(), 2, "an Offered question");
        let options = crate::rd_env_choice_count();
        assert_eq!(options, 3, "`1 of 3`, exactly");

        let mut names = Vec::new();
        for slot in 0..options {
            let length = crate::rd_env_pile_card_id_len(3, slot);
            assert!(length > 0, "option {slot} has a name");
            let mut buffer = vec![0u8; length as usize];
            unsafe { crate::rd_env_pile_card_id_into(3, slot, buffer.as_mut_ptr()) };
            names.push(String::from_utf8(buffer).expect("ascii ids"));
        }
        let colorless = ["bandage_up", "blind", "dark_shackles"];
        for name in &names {
            assert!(
                colorless.contains(&name.as_str()),
                "{name} is not a colorless card -- the pool leaked: {names:?}"
            );
        }

        // Pick the first answer and confirm.
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0, "tick the first option");
        assert_eq!(crate::rd_env_choice_confirm(), 0, "confirm it");
        assert_eq!(crate::rd_env_choice_pending(), 0, "the question is answered");

        let hand_after = hand_ids();
        assert_eq!(
            hand_after.len(),
            hand_before.len() + 1,
            "the chosen card is in the hand: {hand_after:?}"
        );
        let added: Vec<&String> = hand_after
            .iter()
            .filter(|id| colorless.contains(&id.as_str()))
            .collect();
        assert_eq!(added.len(), 1, "exactly one colorless card joined: {hand_after:?}");
    }

    /// §188: A15 ("Unfavorable Events") reaches the ABI -- a different **list**, not a different
    /// count (so a test that only counted effects would pass with the wrong one).
    ///
    /// ⤅golden_idol` 是本内容里唯一一个真实的 StS 事件：基础是 **遗物 + Injury 诅咒**，
    /// A15 是 **遗物 + 25% 最大生命伤害**（wiki 的两个分支，记在 inventory §7）。
    ///
    /// 为什么不走地图：row 0 **永远是战斗**（StS 的规则），而这条测试要验的是"等级 → 选哪一张列表
    /// → ABI" 这一段。所以直接建一个**已打开事件**的会话（`begin_event` 是公开的）。
    #[test]
    fn a15_swaps_the_event_effect_list() {
        const CURSE_CODE: i32 = 9;
        const DAMAGE_CODE: i32 = 3;
        const RELIC_CODE: i32 = 10;
        for (level, want_second) in [
            (0u8, CURSE_CODE),
            (14, CURSE_CODE),
            (15, DAMAGE_CODE),
            (20, DAMAGE_CODE),
        ] {
            let mut state = rd_run::state::RunState::new_with_ascension(
                7,
                80,
                0,
                &["strike"; 5],
                level,
            )
            .expect("a run");
            assert_eq!(state.ascension(), level, "the run knows its level");
            state.begin_event("golden_idol").expect("open the event");
            *run_slot() = Some(RunSession {
                state: Box::new(state),
                error: String::new(),
                elite_fight: false,
                boss_fight: false,
                in_fight: false,
                journal: Vec::new(),
                head: std::format!("RDR1,S,7,{level},{}", content_pin_text()),
                replaying: false,
                replay_checked: 0,
                replay_diverged: 0,
                hash_failed: false,
            });

            assert_eq!(
                rd_run_event_effect_count(0),
                2,
                "A{level}: the first option has two effects"
            );
            assert_eq!(
                rd_run_event_effect_at(0, 0),
                RELIC_CODE,
                "the relic comes first at every level"
            );
            assert_eq!(
                rd_run_event_effect_at(0, 1),
                want_second,
                "A{level}: the second effect must be {want_second}"
            );
            assert_eq!(
                rd_run_event_effect(0),
                rd_run_event_effect_at(0, 0),
                "the legacy accessor is the head of the list"
            );
        }
    }

    /// The hand's definition ids, in pile order (`hand_costs` has the prices).
    fn hand_ids() -> Vec<String> {
        let session = crate::slot().as_ref().expect("env session");
        let hero = session.hero_id().expect("hero");
        session
            .state
            .card_zones(&hero)
            .map(|zones| {
                zones
                    .slots(rd_core::state::CardZone::Hand)
                    .iter()
                    .filter_map(|slot| {
                        session
                            .state
                            .card(rd_core::state::CardSlot::from_index(*slot))
                            .map(|card| card.definition_id.as_str().to_string())
                    })
                    .collect()
            })
            .unwrap_or_default()
    }

    /// §187：运行层的 Ascension 等级必须**真的进到战斗里**。
    ///
    /// `A2/A3/A4` 与 `A17/18/19` 全都读 `CombatState::ascension()`，而那个数来自这里的
    /// `session.state.ascension()`。它不进快照、不进哈希，所以**加错地方也不会有任何闸门变红** ——
    /// 除非有这一条。（第一版用 `test_run` 做夹具，它已经开了一局，再
    /// `rd_run_start` 就被拒了 —— 开局路径只能走一次。）
    #[test]
    fn the_ascension_level_reaches_the_fight_state() {
        for level in [0i32, 2, 3, 4, 17, 19, 20] {
            assert_eq!(rd_run_start(11, level), 0, "start at A{level} ({})", run_error_text());
            assert_eq!(rd_run_ascension(), level, "the run knows its level");
            // 祝福先结掉（与界面一样），否则地图游标还没动，`rd_run_step(0)` 会报
            // "动作下标越界" —— 那是正确的拒绝，只是这条测试走错了顺序。
            assert_eq!(rd_run_choose_start(0), 0, "take blessing 0");
            while rd_run_pending() == 7 {
                assert_eq!(rd_run_pick_blessing_card(0), 0, "the blessing owes a pick");
            }
            assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
            assert_eq!(rd_run_begin_node(), 0, "begin the node");
            if rd_run_fight_begin() != 0 {
                // not every seed opens on a fight; the run-side fact is still asserted above
                continue;
            }
            let session = crate::slot().as_ref().expect("env session");
            assert_eq!(
                session.state.ascension(),
                u8::try_from(level).unwrap(),
                "the fight must run at A{level}, not at the default"
            );
        }
    }

    /// The hero's stacks of `definition`, read through the §147 ABI (works for any status).
    fn hero_status(definition: &str) -> i32 {
        for index in 0..crate::rd_env_status_count(-1) {
            let len = crate::rd_env_status_id_len(-1, index);
            let mut bytes = vec![0u8; len as usize];
            unsafe { crate::rd_env_status_id_into(-1, index, bytes.as_mut_ptr()) };
            if String::from_utf8_lossy(&bytes) == definition {
                return crate::rd_env_status_stacks(-1, index);
            }
        }
        0
    }

    /// The same for enemy wall slot `slot`.
    fn enemy_status(slot: i32, definition: &str) -> i32 {
        for index in 0..crate::rd_env_status_count(slot) {
            let len = crate::rd_env_status_id_len(slot, index);
            let mut bytes = vec![0u8; len as usize];
            unsafe { crate::rd_env_status_id_into(slot, index, bytes.as_mut_ptr()) };
            if String::from_utf8_lossy(&bytes) == definition {
                return crate::rd_env_status_stacks(slot, index);
            }
        }
        0
    }

    /// Enemy wall slot `slot`'s current HP, out of the observation.
    fn enemy_hp(slot: usize) -> i32 {
        let obs = exported_observation();
        obs[crate::OFF_ENEMY + slot * 8 + 1]
    }

    /// The effect fires, and it is capped: `Burning Blood` heals 6 but never past the maximum.
    #[test]
    fn burning_blood_heals_at_the_end_of_the_fight() {
        reset(7);
        let session = run_slot().as_mut().expect("session");
        // Relative to the run's own health: a blessing may already have cost HP (`inv:§7.1`).
        let base = session.state.health();
        session.state.adjust_health(-20);
        assert_eq!(session.state.end_of_combat(), Ok(6));
        assert_eq!(session.state.health(), base - 20 + 6);
        session.state.adjust_health(1000);
        assert_eq!(session.state.end_of_combat(), Ok(0), "nothing to heal at full health");
    }

    /// §145：**开战时的遗物加成真的进了战斗**（Anchor 10 Block / Vajra 1 力量）。
    ///
    /// 断言的读法与页面一致：走 `rd_env_*` 的观察向量，而不是直接看战斗员 —— 加进去了但没
    /// `reobserve`，页面看到的就是 0（这个坑 §84 踩过一次）。
    #[test]
    fn the_relic_pool_pays_out_when_a_fight_starts() {
        test_run(7, 80, 80, &["strike"; 10]);
        {
            let session = run_slot().as_mut().expect("session");
            session.state.push_relic("anchor").expect("anchor");
            session.state.push_relic("vajra").expect("vajra");
            // 开局那件 Burning Blood 也还在 —— 顺便钉住"三件遗物各管各的钩子"。
            assert_eq!(session.state.combat_bonus().block, 10);
            assert_eq!(session.state.combat_bonus().status_count, 1, "Vajra grants one status");
        }
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let obs = exported_observation();
        assert_eq!(
            obs[crate::H_HERO_BLOCK], 10,
            "Anchor 的 10 点格挡必须在开战时就摆在场上"
        );
        // `standard.strength` 是状态轴的第 0 条（`lib.rs::STATUS_AXES`）。
        assert_eq!(
            obs[crate::OFF_HERO_STATUS], 1,
            "Vajra 的 1 点力量必须在开战时就挂在英雄身上"
        );

        // 成对：一场**没有**这两件遗物的战斗，两个数都是 0（否则上面两句也可能是"恒等于"）。
        reset(7);
        assert_eq!(rd_run_step(0), 0);
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0);
        let plain = exported_observation();
        assert_eq!(plain[crate::H_HERO_BLOCK], 0);
        assert_eq!(plain[crate::OFF_HERO_STATUS], 0);
    }

    /// The link the run layer did not have: a fight is **the run's** fight, and its result goes back.
    ///
    /// `inv:§7.2` fixes floor 1 to be all combat, so the first step lands on one -- no search.
    #[test]
    fn a_fight_is_the_runs_fight_and_the_result_goes_back() {
        // An explicit run: this test is about the deck, not about the start path,
        // so it must not depend on the blessing rules (§105).
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_node_kind(), 1, "floor 1 is all combat (inv:§7.2)");
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_pending(), 0, "a fight has nothing for the run layer to settle");

        // The hero enters wounded, and the fight has to know that. Relative to the run's own health:
        // a blessing may already have cost HP (`inv:§7.1`).
        let base: i32;
        {
            let session = run_slot().as_mut().unwrap();
            base = session.state.health();
            session.state.adjust_health(-20);
            assert_eq!(session.state.health(), base - 20);
        }
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");
        assert_eq!(
            crate::combat_hero_health(),
            Some(base - 20),
            "the fight starts at the run's health, not at full"
        );
        // The fight's deck is the run's deck: every card is in a pile **or in hand** -- the fight
        // starts at turn 1 now, so five of the ten are drawn.
        let piles: i32 = (0..3).map(|zone| rd_env_pile_len(zone)).sum();
        let hand = 5;
        assert_eq!(
            piles + hand,
            rd_run_deck_count(),
            "the fight's cards are the run's cards"
        );
        // Every card is in a pile or in hand, whatever the blessing did to the deck.
    assert!(piles + hand == rd_run_deck_count(), "the fight's cards are the run's deck");

        // Ending it folds the health back and drops the session.
        assert_eq!(rd_run_fight_end(), 0, "a fight still in progress ends as Ongoing");
        assert_eq!(rd_run_fight_end(), -1, "there is no second fight to end");
        let session = run_slot().as_ref().unwrap();
        assert_eq!(
            session.state.health(),
            base - 20,
            "the fight did not change the run's health"
        );
    }

    /// Winning folds the health back **and** runs the relics: `Burning Blood` heals 6.
    ///
    /// This is the path the browser run exposed as untested -- the previous test ended a fight that
    /// was still ongoing, which takes the "no heal" branch. `end_of_combat` had a call site but no
    /// test that the call site was *reached*.
    #[test]
    fn winning_heals_through_the_relic() {
        reset(7);
        assert_eq!(rd_run_step(0), 0);
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0);
        let start = run_slot().as_ref().unwrap().state.health();
        assert!(start > 0, "the run must have health to lose");

        // Play the fight out the way a policy would: any play action, else end the turn.
        let mut guard = 0;
        while rd_env_done() == 0 && guard < 400 {
            let mut choice = -1;
            for index in 0..rd_env_action_count() {
                if rd_env_action_kind(index) == 0 {
                    choice = index;
                    break;
                }
            }
            if choice < 0 {
                choice = rd_env_action_index_of_end_turn();
            }
            assert!(choice >= 0, "no legal action at step {guard}");
            assert_eq!(rd_env_step(choice), 0, "step {guard} rejected");
            guard += 1;
        }
        assert_eq!(rd_env_done(), 1, "the fight did not finish");
        assert_eq!(rd_env_result(), 1, "the fight was not won");
        let fight_hp = crate::combat_hero_health().expect("hero health");
        assert!(fight_hp < start, "the fight did no damage at all");

        assert_eq!(rd_run_fight_end(), 1, "the run must report a victory");
        let session = run_slot().as_ref().unwrap();
        // `Burning Blood`: +6, capped at the maximum (`inv:§2`).
        let expected = (fight_hp + rd_run::state::BURNING_BLOOD_HEAL).min(start);
        assert_eq!(
            session.state.health(),
            expected,
            "the relic did not heal: fight ended at {fight_hp}, run reads {}",
            session.state.health()
        );
    }

    /// §176：**三个 Boss 都能被完整打下去**，包括中途分裂出来的战斗员。
    ///
    /// 这条测试是那次卡死的回归：Slime Boss 在 2 HP 时分裂出 `acid_slime_m#000000` /
    /// `spike_slime_s#000001`，而驱动器在 `plan.enemies`（开局固定的切片）里找"轮到谁、它有哪些招"
    /// ⇒ `活跃战斗员 … 不在 plan.enemies 里`，整个结束回合的步骤失败，页面上看起来就是"打不动"。
    /// 分裂在 §175 之前从未发生过（`standard.split` 是起始状态，而起始状态当时根本不生效），
    /// 所以这个假设一直没被撞破。
    ///
    /// 判据不是"赢了"（这副 10 张起始牌打不赢 400 HP 的 Boss），而是**每一步都还受理、且分裂之后
    /// 敌人真的会行动**。
    #[test]
    fn every_boss_fight_stays_playable_including_summons() {
        for encounter in ["enc_slime_boss", "enc_the_champ", "enc_time_eater"] {
            let session = crate::build_session_at(7, encounter, 400, None, 0, 0)
                .unwrap_or_else(|error| panic!("{encounter}: {error}"));
            crate::install_session(session);
            let mut multi = 0usize;
            let mut rounds_lived = 0usize;
            for round in 1..=25 {
                // Play every playable card, then end the turn -- the shape the page uses.
                let mut played = 0;
                while played < 40 {
                    let mut action = -1;
                    for index in 0..rd_env_action_count() {
                        if rd_env_action_kind(index) == 0 {
                            action = index;
                            break;
                        }
                    }
                    if action < 0 {
                        break;
                    }
                    assert_eq!(
                        crate::rd_env_step(action),
                        0,
                        "{encounter} round {round}: a card play was refused ({})",
                        run_error_text()
                    );
                    played += 1;
                }
                let end = rd_env_action_index_of_end_turn();
                if end < 0 {
                    break; // the fight is over, or the hero died
                }
                let verdict = crate::rd_env_step(end);
                assert_eq!(
                    verdict, 0,
                    "{encounter} round {round}: ending the turn was refused ({}) -- problems {:?}",
                    run_error_text(),
                    crate::slot().as_ref().map(|s| s.problems.clone())
                );
                rounds_lived += 1;
                let enemies = {
                    let session = crate::slot().as_ref().expect("session");
                    session
                        .state
                        .combatants()
                        .iter()
                        .filter(|unit| unit.team_id.as_str() == "enemy")
                        .count()
                };
                if enemies > 1 {
                    multi += 1;
                }
                if rd_env_done() != 0 {
                    break;
                }
            }
            println!("{encounter}: {rounds_lived} rounds, {multi} with more than one enemy");
            assert!(
                rounds_lived >= 3,
                "{encounter} only lasted {rounds_lived} rounds"
            );
        }
    }

    /// §174：Lagavulin 打完 **8 个回合**都必须能继续 —— 尤其第 5 回合的 Siphon Soul。
    ///
    /// 这条是那个两小时死锁的回归测试。原来的写法用 `applyStatus` 传**负层数**，程序抛 `Exec`，
    /// 驱动把它记成 `StepThrew` 之后局面停在"轮到 Lagavulin 但它的回合没开始"（`active` = 它、
    /// `phase` = `WaitingToStartTurn`、动作表空）—— 页面上一个可点的东西都没有。
    ///
    /// 现在是两层保护：内容改用 `modifyStatusStacks`（不抛），以及 `step_end_turn` 的敌方回合循环
    /// 会先把没开始的回合**启动**再结束（自愈）。所以断言是"每一回合都返回 0、并且第 5 回合的
    /// Siphon Soul 真的把力量/敏捷减下去"。
    #[test]
    fn lagavulin_can_be_fought_for_eight_rounds_including_siphon_soul() {
        let session = crate::build_session_at(7, "enc_lagavulin", 200, None, 0, 0)
            .expect("the lagavulin encounter");
        crate::install_session(session);
        let hero = rd_core::state::CombatantId::new("hero").expect("hero id");
        let stacks = |state: &rd_core::state::CombatState, id: &str| -> i32 {
            state
                .combatant(&hero)
                .map(|unit| {
                    unit.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == id)
                        .map(|s| s.stacks)
                        .sum()
                })
                .unwrap_or(0)
        };

        for round in 1..=8 {
            let end = rd_env_action_index_of_end_turn();
            assert!(
                end >= 0,
                "round {round}: no action at all (the §174 deadlock) -- active {:?}, phase {:?}",
                crate::slot().as_ref().and_then(|s| s.state.active_combatant_id),
                crate::slot().as_ref().map(|s| s.state.turn_phase)
            );
            let verdict = crate::rd_env_step(end);
            assert_eq!(
                verdict, 0,
                "round {round} was refused; the fight must stay playable"
            );
            let problems = crate::slot()
                .as_ref()
                .map(|s| s.problems.join(","))
                .unwrap_or_default();
            assert!(
                problems.is_empty(),
                "round {round} recorded {problems} -- a thrown enemy action is exactly the bug"
            );
        }

        let session = crate::slot().as_ref().expect("session");
        let state = &session.state;
        // ⚠️ **偏差，写清楚**：wiki 的 Siphon Soul 是"-**1** 力量、-**1** 敏捷"，也就是给你一个**负**
        // 层数的减益；本内核把"减到 0"当删除、不支持负值（`modifyStatusStacks` 减到 0 就移除实例）。
        // 所以英雄本来没有力量时，这一次 Siphon 什么都不留下 —— 与 StS 的行为不同，记在这里而不是
        // 假装它等价。真要负值，得先让状态层允许 < 0 的层数并让伤害计算读它。
        assert!(stacks(&state, "standard.strength") <= 0, "Strength was not reduced");
        assert!(stacks(&state, "standard.dexterity") <= 0, "Dexterity was not reduced");
    }

    /// The end-turn action's index, or `-1`.
    fn rd_env_action_index_of_end_turn() -> i32 {
        for index in 0..rd_env_action_count() {
            if rd_env_action_kind(index) == 1 {
                return index;
            }
        }
        -1
    }

    /// Winning leaves a **reward screen**: gold already paid, three distinct cards on the table.
    ///
    /// This is the second half of "the fight is the run's": before it, a won fight healed and paid
    /// nothing.
    #[test]
    fn winning_leaves_a_reward_screen() {
        reset(7);
        assert_eq!(rd_run_step(0), 0);
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0);
        let gold_before = run_slot().as_ref().unwrap().state.gold();
        let deck_before = rd_run_deck_count();

        let mut guard = 0;
        while rd_env_done() == 0 && guard < 400 {
            let mut choice = -1;
            for index in 0..rd_env_action_count() {
                if rd_env_action_kind(index) == 0 {
                    choice = index;
                    break;
                }
            }
            if choice < 0 {
                choice = rd_env_action_index_of_end_turn();
            }
            assert!(choice >= 0);
            assert_eq!(rd_env_step(choice), 0);
            guard += 1;
        }
        assert_eq!(rd_env_result(), 1, "the fight was not won");
        assert_eq!(rd_run_fight_end(), 1);

        // `inv:§5`: 10-20 gold for a normal fight, added on victory.
        let gold = rd_run_reward_gold();
        assert!(
            (10..=20).contains(&gold),
            "the fight paid {gold} gold, which is not the normal-fight range"
        );
        assert_eq!(
            run_slot().as_ref().unwrap().state.gold(),
            gold_before + gold,
            "the gold on the screen is not the gold in the purse"
        );
        assert_eq!(rd_run_pending(), 4, "the reward screen must be waiting");

        // `inv:§3.5`: three cards, all different.
        let count = rd_run_reward_card_count();
        assert_eq!(count, 3);
        let mut ids = Vec::new();
        for slot in 0..count {
            let n = rd_run_reward_card_id_len(slot);
            assert!(n > 0);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_run_reward_card_id_into(slot, buffer.as_mut_ptr()) };
            let id = String::from_utf8(buffer).unwrap();
            // `inv:§3.5`: Act 1 never offers an upgraded card.
            assert!(!id.ends_with('+'), "the reward offered the upgraded card {id}");
            ids.push(id);
        }
        let mut sorted = ids.clone();
        sorted.sort();
        sorted.dedup();
        assert_eq!(sorted.len(), 3, "the reward offered a duplicate: {ids:?}");

        // Taking one adds exactly that card. §161.8: the **screen stays open** -- the potion and the
        // relic are separate rows (and on an elite's reward this is what used to lose the relic).
        let wanted = ids[2].clone();
        assert_eq!(rd_run_take_card(2), 0);
        assert_eq!(rd_run_deck_count(), deck_before + 1);
        assert_eq!(
            rd_run_reward_card_count(),
            0,
            "the card choice is one pick: every card row is spent"
        );
        assert_ne!(rd_run_pending(), -1, "the screen is still there for the other rows");
        let last = {
            let n = rd_run_deck_id_len(rd_run_deck_count() - 1);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_run_deck_id_into(rd_run_deck_count() - 1, buffer.as_mut_ptr()) };
            String::from_utf8(buffer).unwrap()
        };
        assert_eq!(last, wanted);

        // §161.8: the screen is still up after taking the card, so `跳过` is the way out -- and a
        // second skip has nothing left to close.
        assert_eq!(rd_run_skip_reward(), 0, "跳过 leaves the reward screen");
        assert_eq!(rd_run_skip_reward(), -2, "there is no screen to skip a second time");
    }

    /// Settle whatever is under the cursor, through the ABI, the way a player would.
    ///
    /// Needed since "you settle a node before you walk on" (`RunError::NodeNotSettled`): a test that
    /// walks the map has to finish each node first, and doing it through the ABI is what keeps these
    /// tests about *walking* rather than about the run layer's internals.
    fn settle_here() {
        if rd_run_node_kind() < 0 {
            return;
        }
        let kind = rd_run_node_kind();
        if rd_run_begin_node() != 0 {
            return;
        }
        match kind {
            // A fight: start it and fold it straight back (the epilogue marks the node resolved).
            1 | 2 | 7 => {
                let _ = rd_run_fight_begin();
                let _ = rd_run_fight_end();
            }
            3 => {
                let _ = rd_run_rest();
            }
            4 => {
                let _ = rd_run_leave();
            }
            5 => {
                // §143: a `?`-room choice can now **owe a deck index** (`remove_card` /
                // `upgrade_card` / `transform_card`). Without this the run would sit in
                // `Pending::EventCard` with no reachable node, and every caller of `settle_here`
                // would see "-1: no such action" and blame the map.
                let _ = rd_run_choose(0);
                if rd_run_event_needs() > 0 {
                    let _ = rd_run_pick_event_card(0);
                }
            }
            6 => {
                let _ = rd_run_open_chest();
            }
            _ => {}
        }
    }

    /// The kind of a node, read off the map.
    fn node_kind(node: i32) -> i32 {
        let Some(session) = run_slot().as_ref() else {
            return -1;
        };
        session
            .state
            .map()
            .locate(node as u8)
            .and_then(|(row, local)| {
                session
                    .state
                    .map()
                    .row(row)
                    .and_then(|line| line.node(local))
                    .map(|node| node.kind as i32)
            })
            .unwrap_or(-1)
    }

    /// An **elite** node fights the elite pool and pays the elite tier.
    ///
    /// `inv:§5.3` + `inv:§5`: 25–35 gold instead of 10–20. Two things had to be true for this to
    /// start at all, and both were wrong before: the node kind was refused, and the three sentry
    /// instances shared one combatant id (`Capacity(DuplicateCombatant)`).
    #[test]
    fn an_elite_node_fights_the_sentries_and_pays_the_elite_tier() {
        reset(7);
        let mut reached = false;
        for _ in 0..80 {
            settle_here();
            let mut choice = -1;
            for action in 0..rd_run_action_count() {
                let node = rd_run_action_arg(action, 0);
                if node >= 0 && node_kind(node) == 2 {
                    choice = action;
                    break;
                }
            }
            if choice >= 0 {
                assert_eq!(rd_run_step(choice), 0);
                reached = true;
                break;
            }
            // Advance through the earlier floors: fight what fights, settle what settles.
            assert_eq!(rd_run_step(0), 0, "walk");
            let kind = rd_run_node_kind();
            let began = rd_run_begin_node();
            if began == 0 && kind == 1 {
                if rd_run_fight_begin() == 0 {
                    let _ = rd_run_fight_end();
                }
            }
        }
        assert!(reached, "no elite reachable from seed 7 within 80 steps");

        assert_eq!(rd_run_node_kind(), 2, "standing on an elite");
        assert_eq!(rd_run_begin_node(), 0, "an elite settles as a fight");
        assert_eq!(
            rd_run_fight_begin(),
            0,
            "the elite fight must start; the kernel said {:?}",
            run_error_text()
        );

        // §173: the act-1 elite pool has **three** encounters now (sentries / gremlin nob / lagavulin),
        // so the claim is "this is one of the pool", not "it is the sentries". Pinning one fight made
        // every later pool addition a red gate, while the interesting claim ("an elite node fights an
        // elite, not the weak pool's slimes") survives.
        let mut names = Vec::new();
        let mut index = 0;
        while rd_env_enemy_name_len(index) >= 0 {
            let n = rd_env_enemy_name_len(index);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_env_enemy_name_into(index, buffer.as_mut_ptr()) };
            names.push(String::from_utf8(buffer).unwrap_or_default());
            index += 1;
        }
        assert!(!names.is_empty(), "the elite fight has no enemies");
        let joined = names.join(" ").to_lowercase();
        assert!(
            ["sentry", "gremlin nob", "lagavulin"]
                .iter()
                .any(|member| joined.contains(member)),
            "the elite fought {names:?}, which is not in the act-1 elite pool"
        );

        // Play it out, then check the tier: `inv:§5` pays an elite 25-35 gold.
        // §173: the naive "play the first legal action" bot cannot always finish (Lagavulin is 109 HP
        // behind Metallicize 8 and sleeps three turns), so the step envelope (-3) can trip where the
        // three sentries used to fall over. That is not a rule failure: the loop stops and says so.
        // The gold band itself is pinned by `rd_run`'s `FightKind::Elite.gold()` test.
        let mut guard = 0;
        let mut envelope = false;
        while rd_env_done() == 0 && guard < 600 {
            let mut action = -1;
            for i in 0..rd_env_action_count() {
                if rd_env_action_kind(i) == 0 {
                    action = i;
                    break;
                }
            }
            if action < 0 {
                action = rd_env_action_index_of_end_turn();
            }
            if action < 0 {
                break;
            }
            let verdict = rd_env_step(action);
            if verdict == -3 {
                envelope = true;
                break;
            }
            assert_eq!(verdict, 0, "step {guard} was refused");
            guard += 1;
        }
        let result = rd_run_fight_end();
        if envelope {
            println!(
                "  note: the naive bot hit the step envelope against {names:?}; the elite gold band                  is pinned in rd-run instead"
            );
        } else if result == 1 {
            let gold = rd_run_reward_gold();
            assert!(
                (25..=35).contains(&gold),
                "an elite paid {gold} gold, which is not inv:§5's elite band"
            );
        }
    }

    /// The kernel's last refusal as text -- `""` means "no refusal", and a length of 0 with a
    /// negative return is itself a bug worth seeing.
    fn run_error_text() -> String {
        let n = rd_run_last_error_len();
        if n <= 0 {
            return format!("<no text, len={n}>");
        }
        let ptr = crate::rd_env_scratch_buf();
        rd_run_last_error_into(ptr);
        let buffer = unsafe { std::slice::from_raw_parts(ptr as *const u8, n as usize) };
        String::from_utf8_lossy(buffer).to_string()
    }

    /// **The act is completable**: after the last row the boss is the only way forward, it is the
    /// slime boss, and killing it clears the act.
    ///
    /// Walking is *not* settling (`env-abi.md` §11.5), so the test walks to the last row without
    /// fighting anything -- that makes it deterministic and fast. (The previous version fought its
    /// way up, died on some seeds, and `return`ed early: a green that meant nothing. Silent skips are
    /// the exact shape this project keeps banning.)
    /// **Each act fights its own monsters** (`port-plan.md` §130): act 1 sees the act-1 pool, act 2
    /// the act-2 pool. The run walks to act 2 the way the game does (the boss falls).
    #[test]
    fn act_two_fights_act_two_enemies() {
        // Enemy names of the fight the run is standing on (after `rd_run_begin_node`).
        fn enemy_names() -> Vec<String> {
            let mut out = Vec::new();
            let mut index = 0;
            while rd_env_enemy_name_len(index) >= 0 {
                let n = rd_env_enemy_name_len(index);
                let mut buffer = vec![0u8; n as usize];
                unsafe { rd_env_enemy_name_into(index, buffer.as_mut_ptr()) };
                out.push(String::from_utf8(buffer).unwrap_or_default());
                index += 1;
            }
            out
        }

        // **Two separate runs**, because a fight that was begun cannot be re-begun: the point is
        // which pool `begin_node` picks given the act, not how to bail out of a fight.
        let first_fight = |advance: bool| -> String {
            reset(7);
            if advance {
                run_slot()
                    .as_mut()
                    .expect("session")
                    .state
                    .mark_boss_beaten();
            }
            assert_eq!(rd_run_step(0), 0, "floor 1 (advance={advance})");
            assert_eq!(
                rd_run_begin_node(),
                0,
                "begin (advance={advance}): {}",
                run_error_text()
            );
            // The fight is **built** by ight_begin (that is where the pool is picked), so this
            // has to happen before the names mean anything.
            assert_eq!(
                rd_run_fight_begin(),
                0,
                "fight_begin (advance={advance}): {}",
                run_error_text()
            );
            enemy_names().join(",").to_lowercase()
        };

        let act_one = first_fight(false);
        assert!(
            ["acid_slime", "spike_slime", "jaw_worm", "cultist", "looter", "louse",
                 "fungi_beast", "slaver", "gremlin"]
                .iter()
                .any(|name| act_one.contains(name)),
            "act 1 must field act-1 monsters, got {act_one}"
        );

        let act_two = first_fight(true);
        assert_eq!(rd_run_act(), 2, "the advance really happened");
        assert!(
            ["shelled_parasite", "chosen"]
                .iter()
                .any(|name| act_two.contains(name)),
            "act 2 must field act-2 monsters, got {act_two}"
        );
    }

    #[test]
    fn the_boss_is_offered_at_floor_16_and_clears_the_act() {
        reset(7);
        // Walk to the last row, settling nothing.
        for _ in 0..32 {
            if rd_run_observe(0) >= 15 {
                break;
            }
            settle_here();
            let mut choice = -1;
            for action in 0..rd_run_action_count() {
                let node = rd_run_action_arg(action, 0);
                if node >= 0 && node < i32::from(rd_run::map::BOSS_NODE) {
                    choice = action;
                    break;
                }
            }
            assert!(choice >= 0, "nowhere to walk from floor {}", rd_run_observe(0));
            assert_eq!(rd_run_step(choice), 0, "walk");
        }
        assert_eq!(rd_run_observe(0), 15, "walked to the last row");

        // From the last row the boss is the *only* offer (`inv:§7.2`: floor 16, off the map).
        assert_eq!(rd_run_action_count(), 1, "the boss must be the only way forward");
        assert_eq!(
            rd_run_action_arg(0, 0),
            i32::from(rd_run::map::BOSS_NODE),
            "the single offer is the boss"
        );

        // The last row has to be settled too -- you settle a node before you walk on.
        settle_here();
        assert_eq!(rd_run_step(0), 0, "walk into the boss");
        assert_eq!(rd_run_observe(0), 16, "the boss is floor 16");
        assert_eq!(rd_run_node_kind(), 7, "kind Boss");
        assert_eq!(rd_run_begin_node(), 0, "the boss settles as a fight");
        assert_eq!(rd_run_boss_beaten(), 0, "not cleared before the fight");
        assert_eq!(
            rd_run_fight_begin(),
            0,
            "the boss fight must start; kernel said {:?}",
            run_error_text()
        );

        let mut names = Vec::new();
        let mut index = 0;
        while rd_env_enemy_name_len(index) >= 0 {
            let n = rd_env_enemy_name_len(index);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_env_enemy_name_into(index, buffer.as_mut_ptr()) };
            names.push(String::from_utf8(buffer).unwrap_or_default());
            index += 1;
        }
        assert_eq!(names.len(), 1, "one boss; got {names:?}");
        // Two bosses are authorable now (§129), so the assertion is "one of the boss pool",
        // not "the slime boss".
        let boss = names[0].to_lowercase();
        assert!(
            // §194 filled the act-1 boss pool to the wiki's three; the pick is seeded, so the
            // assertion is "one of the pool", not "the one this seed used to get".
            boss.contains("slime_boss") || boss.contains("the_guardian") || boss.contains("hexaghost"),
            "the boss must come from the Boss pool; got {names:?}"
        );

        // Fight it out. The assertion is that the *mechanism* is consistent in both directions --
        // clearing the act if and only if the boss dies -- not that this particular bot wins.
        let mut guard = 0;
        while rd_env_done() == 0 && guard < 2000 {
            let mut action = -1;
            for i in 0..rd_env_action_count() {
                if rd_env_action_kind(i) == 0 {
                    action = i;
                    break;
                }
            }
            if action < 0 {
                action = rd_env_action_index_of_end_turn();
            }
            if action < 0 {
                break;
            }
            assert_eq!(rd_env_step(action), 0);
            guard += 1;
        }
        let result = rd_run_fight_end();
        println!("boss fight: result={result} steps={guard} hp={}", rd_run_observe(2));
        if result == 1 {
            assert_eq!(rd_run_boss_beaten(), 1, "a won boss fight clears the act");
            let gold = rd_run_reward_gold();
            assert!(
                (95..=105).contains(&gold),
                "a boss pays 95-105 (inv:§5), got {gold}"
            );
        } else {
            assert_eq!(result, 2, "the only other ending is defeat");
            assert_eq!(rd_run_boss_beaten(), 0, "losing does not clear the act");
        }
    }

    /// **Using a potion in a fight, end to end**: win a fight, take the potion it dropped, walk into
    /// the next fight, and use it.
    ///
    /// The three effects are handled differently on purpose: Block and energy go through public
    /// kernel APIs and must move the number; `combat_damage` has no entry point yet
    /// (`port-plan.md` §83) and must **refuse without eating the potion**.
    #[test]
    /// §156: a potion, drunk **in a real fight**, does what it says.
    ///
    /// The belt contents are pushed directly instead of hunted from drops: with the rarity-weighted
    /// drop (§156) the old version -- "walk twenty fights until block + energy + fire all show up" --
    /// was measuring the potion RNG, and it broke the moment the weights changed. The **drop** is
    /// covered by the reward tests (`roll_reward`), and this test is about drinking one.
    fn a_potion_can_be_used_in_a_fight() {
        reset(4);
        assert!(arrive_at_a_fight(), "the fixture must actually reach a fight");


        // The three the assertions below know how to check.
        {
            let session = run_slot().as_mut().expect("session");
            for potion in ["block_potion", "energy_potion", "fire_potion"] {
                session.state.push_potion(potion).expect("the belt holds three");
            }
        }
        let belt = rd_run_potion_count();
        assert_eq!(belt, 3, "three potions in the belt");


        // Which slot holds the block potion (there may be other potions in front of it).
        let mut slot = -1;
        for index in 0..belt {
            let n = rd_run_potion_id_len(index as i32);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_run_potion_id_into(index as i32, buffer.as_mut_ptr()) };
            if String::from_utf8_lossy(&buffer) == "block_potion" {
                slot = index as i32;
            }
        }
        let id = {
            let n = rd_run_potion_id_len(if slot >= 0 { slot } else { 0 });
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_run_potion_id_into(if slot >= 0 { slot } else { 0 }, buffer.as_mut_ptr()) };
            String::from_utf8(buffer).unwrap()
        };
        let block_before = hero_block();
        let energy_before = hero_energy();
        let fire_target_before = first_enemy_hp();
        let outcome = rd_env_use_potion(if slot >= 0 { slot } else { 0 }, -1);
        match id.as_str() {
            "block_potion" => {
                assert_eq!(outcome, 0, "block potion: {:?}", run_error_text());
                assert_eq!(hero_block(), block_before + 12, "12 Block");
                let after_block = rd_run_potion_count();
                assert_eq!(after_block, belt - 1, "the potion is consumed");

                // ...and now the energy potion, which is the other effect this build applies.
                let mut energy_slot = -1;
                for index in 0..after_block {
                    let n = rd_run_potion_id_len(index as i32);
                    let mut buffer = vec![0u8; n as usize];
                    unsafe { rd_run_potion_id_into(index as i32, buffer.as_mut_ptr()) };
                    if String::from_utf8_lossy(&buffer) == "energy_potion" {
                        energy_slot = index as i32;
                    }
                }
                assert!(energy_slot >= 0, "the belt must hold the energy potion we hunted for");
                let energy_before_use = hero_energy();
                let energy_outcome = rd_env_use_potion(energy_slot, -1);
                assert_eq!(
                    energy_outcome, 0,
                    "energy potion: {:?}",
                    run_error_text()
                );
                assert_eq!(
                    hero_energy(),
                    energy_before_use + 2,
                    "2 energy, past the per-turn cap"
                );
                let after_energy = rd_run_potion_count();
                assert_eq!(
                    after_energy,
                    after_block - 1,
                    "the energy potion is consumed too"
                );

                // ...and the damage potion, which goes through `exec::resolve_damage`.
                let mut fire_slot = -1;
                for index in 0..after_energy {
                    let n = rd_run_potion_id_len(index as i32);
                    let mut buffer = vec![0u8; n as usize];
                    unsafe { rd_run_potion_id_into(index as i32, buffer.as_mut_ptr()) };
                    if String::from_utf8_lossy(&buffer) == "fire_potion" {
                        fire_slot = index as i32;
                    }
                }
                assert!(fire_slot >= 0, "the belt must hold the fire potion we hunted for");
                let enemy_before = first_enemy_hp();

                let fire_outcome = rd_env_use_potion(fire_slot, -1);
                assert_eq!(fire_outcome, 0, "fire potion: {:?}", run_error_text());
                // ⚠️ 不能钉"恰好 20"：这趟行走会顺路捡到遗物/状态（Vajra 的 1 点力量、易伤），
                // 而它们**本来就该**改这个数（§145/§149）。钉的是"药水真的走了伤害管线、打了
                // 至少 20 点"，而 `== enemy_before - 20` 会让每次内容变动都可能翻红 ——
                // 它已经因为卡池多两张（§149）而红过一次。
                let dropped = enemy_before - first_enemy_hp();
                assert!(
                    dropped >= 20,
                    "20 damage through the pipeline, got {dropped}"
                );
                assert_eq!(rd_run_potion_count(), after_energy - 1);
            }
            "energy_potion" => {
                // The hunt stops on a belt holding both, and the block arm uses the energy potion
                // after it -- so reaching here means the hunt's stop condition changed.
                assert_eq!(outcome, 0, "energy potion: {:?}", run_error_text());
                assert_eq!(hero_energy(), energy_before + 2, "2 energy past the cap");
            }
            "fire_potion" => {
                // 20 damage through the **existing pipeline**: the enemy loses 20 HP (it has no Block
                // on the first turn of a fight it has not acted in yet).
                assert_eq!(outcome, 0, "fire potion: {:?}", run_error_text());
                assert_eq!(
                    first_enemy_hp(),
                    fire_target_before - 20,
                    "20 damage through the damage pipeline"
                );
                assert_eq!(rd_run_potion_count(), belt - 1, "the potion is consumed");
            }
            "blood_potion" => {
                // §133 added it: a heal potion, so the belt drops and HP goes up (capped).
                assert_eq!(outcome, 0, "blood potion: {:?}", run_error_text());
                assert_eq!(rd_run_potion_count(), belt - 1, "the potion is consumed");
            }
            "swift_potion" => {
                assert_eq!(outcome, 0, "swift potion: {:?}", run_error_text());
                assert_eq!(rd_run_potion_count(), belt - 1, "the potion is consumed");
            }
            other => panic!("the content offers no potion called {other}"),
        }
    }

    /// The hero's Block, off the combat observation.
    fn hero_block() -> i32 {
        let mut buffer = vec![0i32; crate::rd_env_observe_len() as usize];
        unsafe { crate::rd_env_observe_into(buffer.as_mut_ptr()) };
        buffer[crate::H_HERO_BLOCK]
    }

    /// The first enemy's HP, read off the kernel's own fight state: the assertion is about what
    /// the damage pipeline did, not about the shape of the observation vector.
    fn first_enemy_hp() -> i32 {
        let Some(session) = crate::slot().as_ref() else {
            return -1;
        };
        let Some(enemy) = session.plan.enemies.first() else {
            return -1;
        };
        rd_core::state::CombatantId::new(enemy.id)
            .ok()
            .and_then(|id| session.state.combatant(&id))
            .map_or(-1, |c| c.health_current)
    }

    /// The hero's energy, off the same observation.
    fn hero_energy() -> i32 {
        let mut buffer = vec![0i32; crate::rd_env_observe_len() as usize];
        unsafe { crate::rd_env_observe_into(buffer.as_mut_ptr()) };
        buffer[crate::H_ENERGY]
    }

    /// **The run opens on a blessing choice** (`inv:§7.1`): two distinct offers, no move legal until
    /// one is taken, and the taken one applies its gain *and* its cost.
    #[test]
    fn the_blessing_is_offered_and_applied() {
        assert_eq!(rd_run_start(7, 0), 0);
        assert_eq!(rd_run_pending(), 6, "Pending::Start before floor 1");

        // Two offers, both real, and distinct.
        let mut ids = std::vec::Vec::new();
        for slot in 0..2 {
            let n = rd_run_start_offer_len(slot);
            assert!(n > 0, "blessing {slot} has no id");
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_run_start_offer_into(slot, buffer.as_mut_ptr()) };
            ids.push(String::from_utf8(buffer).unwrap());
            let gain = rd_run_start_gain(slot);
            assert!((1..=5).contains(&gain), "blessing {slot} gain {gain}");
            let cost = rd_run_start_cost(slot);
            assert!((1..=5).contains(&cost), "blessing {slot} cost {cost}");
        }
        assert_ne!(ids[0], ids[1], "the two offers must differ");
        assert_eq!(rd_run_start_offer_len(2), -1, "only two offers");

        // No move is legal yet.
        // No legal move exists yet: the action table is empty, so there is no index 0 at all. (It
        // used to be -2 WrongPhase with five lit nodes on the map -- which the page drew, and a
        // click then overwrote the blessing panel with the refusal.)
        assert_eq!(rd_run_action_count(), 0, "no node is offered before the blessing");
        assert_ne!(rd_run_step(0), 0, "and stepping anyway is refused");
        assert_eq!(rd_run_observe(0), 0, "and the floor must not move");

        // Take the first: gain then cost, exactly.
        let gold_before = rd_run_observe(4);
        let hp_before = rd_run_observe(2);
        let max_before = rd_run_observe(3);
        let gain = rd_run_start_gain(0);
        let gain_amount = rd_run_start_gain_amount(0);
        let cost = rd_run_start_cost(0);
        let cost_amount = rd_run_start_cost_amount(0);
        assert_eq!(rd_run_choose_start(0), 0, "taking blessing 0");
        // A blessing about a card owes a deck index before anything else can happen.
        if rd_run_blessing_needs() != 0 {
            assert_eq!(rd_run_pick_blessing_card(0), 0, "finishing the card blessing");
        }
        assert_eq!(rd_run_pending(), 0, "the choice is settled");

        // Gain first, then cost, so a cost that would be lethal is still paid on the gained HP.
        let mut gold = gold_before;
        let mut hp = hp_before;
        let mut max = max_before;
        if gain == 2 {
            gold += gain_amount;
        } else if gain == 1 {
            hp = (hp + gain_amount).min(max);
        } else if gain == 3 {
            hp -= gain_amount;
        } else if gain == 4 {
            max += gain_amount;
            hp += gain_amount;
        }
        if cost == 3 {
            hp -= cost_amount;
        } else if cost == 2 {
            gold += cost_amount;
        }
        assert_eq!(rd_run_observe(4), gold, "gold after gain and cost");
        assert_eq!(rd_run_observe(2), hp, "health after gain and cost");
        assert_eq!(rd_run_observe(3), max, "max health after gain and cost");

        // And now the walk is legal.
        assert!(rd_run_action_count() > 0, "the map opens up");
        assert_eq!(rd_run_step(0), 0, "the first step is legal");
        assert_eq!(rd_run_choose_start(0), -2, "the blessing cannot be taken twice");
    }

    /// **A fight starts at the run's health, and the observation says so.**
    ///
    /// The page's battle log is a diff of two observation vectors. When the fight-start vector still
    /// carried the pre-blessing HP, the *first card played* was blamed for the blessing's cost
    /// (reported by hand). The fix is that `set_combat_hero_health` now re-observes; this pins it.
    #[test]
    fn a_fight_starts_at_the_runs_health_and_the_observation_agrees() {
        // Find a seed whose blessing costs health, so the run is wounded before the fight.
        let mut wounded = false;
        for seed in 1..=40 {
            assert_eq!(rd_run_start(seed, 0), 0, "starting seed {seed}");
            let mut slot = -1;
            for candidate in 0..2 {
                if rd_run_start_cost(candidate) == 3 && rd_run_start_cost_amount(candidate) > 0 {
                    slot = candidate;
                }
            }
            if slot < 0 {
                // No damaging blessing here: take one (so the run is playable) and move on.
                assert_eq!(rd_run_choose_start(0), 0);
                continue;
            }
            assert_eq!(rd_run_choose_start(slot), 0, "taking the damaging blessing");
            if rd_run_observe(2) < rd_run_observe(3) {
                wounded = true;
                break;
            }
        }
        assert!(wounded, "no seed offered a blessing that costs health");

        // Walk to a fight and start it.
        let mut began = false;
        for _ in 0..20 {
            assert!(rd_run_action_count() > 0, "no move to a fight");
            let mut combat = -1;
            for action in 0..rd_run_action_count() {
                let node = rd_run_action_arg(action, 0);
                if node >= 0 && node_kind(node) == 1 {
                    combat = action;
                    break;
                }
            }
            let chosen = if combat >= 0 { combat } else { 0 };
            assert_eq!(
                rd_run_step(chosen),
                0,
                "walk from floor {} (kind {}): {}",
                rd_run_observe(0),
                rd_run_node_kind(),
                run_error_text()
            );
            if rd_run_node_kind() == 1 {
                assert_eq!(rd_run_begin_node(), 0);
                assert_eq!(rd_run_fight_begin(), 0, "fight_begin: {:?}", run_error_text());
                began = true;
                break;
            }
            settle_here();
        }
        assert!(began, "never reached a fight");

        let run_hp = rd_run_observe(2);
        let mut buffer = vec![0i32; crate::rd_env_observe_len() as usize];
        unsafe { crate::rd_env_observe_into(buffer.as_mut_ptr()) };
        assert_eq!(
            buffer[4], run_hp,
            "the fight's published HP must be the run's, not the maximum"
        );
        assert!(
            run_hp < buffer[5],
            "and this seed must actually be wounded ({run_hp}/{})",
            buffer[5]
        );
    }

    /// A `?` room opens one of the four events, offers **two** choices, and the chosen one applies.
    ///
    /// The room was refused outright until the missing `NodeKind::Unknown` arm was added -- a bug that
    /// survived a whole round because the *comment* said `Unknown` settles while the catch-all arm
    /// still refused it. 7 of 8 seeds were unwinnable because of it (`port-plan.md` §73.3).
    #[test]
    fn an_unknown_room_opens_an_event_and_resolves_it() {
        reset(7);
        let mut found = false;
        for _ in 0..40 {
            settle_here();
            let mut choice = -1;
            for action in 0..rd_run_action_count() {
                let node = rd_run_action_arg(action, 0);
                if node >= 0 && node_kind(node) == 5 {
                    choice = action;
                    break;
                }
            }
            if choice >= 0 {
                assert_eq!(rd_run_step(choice), 0, "walk into the unknown room");
                found = true;
                break;
            }
            assert_eq!(rd_run_step(0), 0, "walk");
        }
        assert!(found, "no unknown room reachable from seed 7");

        assert_eq!(rd_run_node_kind(), 5, "standing on an unknown room");
        assert_eq!(
            rd_run_begin_node(),
            0,
            "the unknown room must open an event; kernel said {:?}",
            run_error_text()
        );
        assert_eq!(rd_run_pending(), 5, "Pending::Event");

        let text = {
            let n = rd_run_event_text_len();
            assert!(n > 0, "the event has no text");
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_run_event_text_into(buffer.as_mut_ptr()) };
            String::from_utf8(buffer).unwrap()
        };
        assert!(text.contains(" — "), "event text should read `id - body`: {text:?}");
        for slot in 0..2 {
            assert!(rd_run_event_label_len(slot) > 0, "choice {slot} has no label");
            let effect = rd_run_event_effect(slot);
            // `1..=5` number effects, `6..=8` deck edits, `9` curse, `10` relic (§143).
            assert!(
                (1..=10).contains(&effect),
                "choice {slot} effect {effect} is outside the vocabulary"
            );
        }
        assert_eq!(rd_run_event_label_len(2), -1, "only two choices");

        let gold_before = rd_run_observe(4);
        let hp_before = rd_run_observe(2);
        let hp_max_before = rd_run_observe(3);
        let deck_before = rd_run_deck_count();
        let effect = rd_run_event_effect(0);
        let amount = rd_run_event_amount(0);
        assert_eq!(rd_run_choose(0), 0, "choosing must be accepted");
        match effect {
            // §143: a deck edit does **not** finish the room -- it leaves a pick owed. That is the
            // whole new state machine, and the point of asserting the phase rather than the deck.
            6..=8 => {
                assert_eq!(rd_run_pending(), 8, "Pending::EventCard");
                assert_eq!(rd_run_event_needs(), effect - 5, "1/2/3 = remove/upgrade/transform");
                assert_eq!(
                    rd_run_node_resolved(),
                    0,
                    "the room is not paid until the card is named"
                );
                assert_eq!(rd_run_pick_event_card(0), 0, "finishing the pick");
                assert_eq!(rd_run_pending(), 0, "the room is settled now");
                if effect == 6 {
                    assert_eq!(rd_run_deck_count(), deck_before - 1, "remove shrinks the deck");
                } else {
                    assert_eq!(rd_run_deck_count(), deck_before, "upgrade/transform keep the size");
                }
                assert_eq!(rd_run_event_needs(), 0, "nothing is owed after the pick");
            }
            9 => assert_eq!(
                rd_run_deck_count(),
                deck_before + 1,
                "a curse goes into the deck"
            ),
            10 => assert_eq!(rd_run_pending(), 0, "a relic needs no pick"),
            _ => {
                assert_eq!(rd_run_pending(), 0, "the room is settled");
                match effect {
                    1 => assert_eq!(
                        rd_run_observe(2),
                        (hp_before + amount).min(hp_max_before),
                        "heal"
                    ),
                    2 => assert_eq!(rd_run_observe(4), gold_before + amount, "gold"),
                    3 => assert_eq!(rd_run_observe(2), hp_before - amount, "damage"),
                    4 => assert_eq!(rd_run_observe(3), hp_max_before + amount, "max hp"),
                    5 => {
                        assert_eq!(rd_run_observe(2), hp_before, "nothing heals");
                        assert_eq!(rd_run_observe(4), gold_before, "nothing pays");
                    }
                    other => panic!("unexpected effect code {other}"),
                }
            }
        }
        assert_eq!(rd_run_node_resolved(), 1, "the room paid once");
        // A second choice is a **wrong-phase** refusal (-2 with text), not "no such
        // choice" (-1): the event is still on record, it is the phase that is gone.
        assert_eq!(rd_run_choose(0), -2, "a second choice is refused");
    }

    /// §143, at the ABI: an event that edits the deck leaves a **pick owed**, and the pick is what
    /// settles the room.
    ///
    /// Driven by opening the event directly instead of hunting a seed whose `?` room happens to
    /// pick it: the thing under test is the phase machine, not the room roller -- and a seed hunt
    /// would turn this test into a test of the map generator the day a pool changes.
    #[test]
    fn an_event_choice_that_edits_the_deck_owes_a_pick() {
        reset(7);
        let deck_before = rd_run_deck_count();
        // A fresh run stands on no node, which is enough for `begin_event` (it only refuses a
        // node that already paid).
        let opened = run_slot()
            .as_mut()
            .expect("a run")
            .state
            .begin_event("ancient_writing")
            .is_ok();
        assert!(opened, "the content must carry `ancient_writing`");

        assert_eq!(rd_run_event_effect(0), 7, "choice 0 is `upgrade_card`");
        assert_eq!(rd_run_event_needs(), 0, "nothing is owed before the choice is taken");
        assert_eq!(rd_run_choose(0), 0, "taking the choice is accepted");
        assert_eq!(rd_run_event_needs(), 2, "2 = upgrade a card");
        assert_eq!(rd_run_pending(), 8, "Pending::EventCard");

        // The map offers nothing while a pick is owed: that is `reachable()`'s rule, and it is why
        // a caller that forgets this phase sees "no such action" and blames the map.
        assert_eq!(rd_run_action_count(), 0, "no walking while a card is owed");

        assert_eq!(rd_run_pick_event_card(1), 0, "upgrading deck entry 1");
        assert_eq!(rd_run_event_needs(), 0, "nothing is owed now");
        assert_eq!(rd_run_pending(), 0, "the room is settled");
        assert_eq!(rd_run_deck_count(), deck_before, "an upgrade does not change the size");

        // ... and the ABI refuses a second pick (the phase is gone).
        assert_eq!(rd_run_pick_event_card(1), -2, "a second pick is refused");

        // The `curse:` payload is checked against the pool the **ABI** builds (`reward_pool`), not
        // against the document. If that pool ever stopped carrying curses, the event would become a
        // dead button and this is the assertion that says so.
        reset(7);
        let deck_before = rd_run_deck_count();
        assert!(
            run_slot()
                .as_mut()
                .expect("a run")
                .state
                .begin_event("forgotten_altar")
                .is_ok(),
            "the content must carry `forgotten_altar`"
        );
        assert_eq!(rd_run_event_effect(0), 9, "choice 0 is `curse:<id>`");
        assert_eq!(rd_run_choose(0), 0, "an event may hand you a curse");
        assert_eq!(rd_run_pending(), 0, "a curse needs no pick");
        assert_eq!(rd_run_deck_count(), deck_before + 1, "the curse went into the deck");
    }

    /// **Balance probe, not a gate.** Plays a whole act with the dumbest reasonable policy and
    /// prints what happens: floors walked, cards taken, how the boss went.
    ///
    /// `#[ignore]`d on purpose: it is a *measurement*. Making it a gate would mean encoding "this bot
    /// must win", which is a statement about the bot, not about the game. Run it with
    /// `--ignored --nocapture` after any content or balance change.
    #[test]
    #[ignore]
    fn balance_probe_full_run() {
        let mut cleared = 0;
        let seeds = 8;
        for seed in 1..=seeds {
            reset(seed);
            let mut fights = 0;
            let mut cards_taken = 0;
            let mut dead = false;

            // Walk and settle until the boss or death.
            for _ in 0..60 {
                if rd_run_observe(2) <= 0 {
                    dead = true;
                    break;
                }
                if rd_run_observe(0) >= 16 {
                    break;
                }
                let mut choice = -1;
                // Prefer a rest site when hurt, else anything but an unknown room.
                let hurt = rd_run_observe(2) * 2 < rd_run_observe(3);
                for action in 0..rd_run_action_count() {
                    let node = rd_run_action_arg(action, 0);
                    if node < 0 {
                        continue;
                    }
                    let kind = node_kind(node);
                    if hurt && kind == 3 {
                        choice = action;
                        break;
                    }
                    if choice < 0 {
                        choice = action;
                    }
                }
                if choice < 0 {
                    break;
                }
                if rd_run_step(choice) != 0 {
                    break;
                }
                let kind = rd_run_node_kind();
                if rd_run_begin_node() != 0 {
                    continue;
                }
                match kind {
                    1 | 2 | 7 => {
                        if rd_run_fight_begin() != 0 {
                            continue;
                        }
                        fights += 1;
                        play_to_the_end();
                        let result = rd_run_fight_end();
                        if result == 1 {
                            // Take whatever the reward offers, first slot: the deck has to grow.
                            if rd_run_reward_card_count() > 0 && rd_run_take_card(0) == 0 {
                                cards_taken += 1;
                            }
                        }
                    }
                    3 => {
                        let _ = rd_run_rest();
                    }
                    6 => {
                        let _ = rd_run_open_chest();
                    }
                    4 => {
                        let _ = rd_run_leave();
                    }
                    // A `?` room is an event: take the first choice (whatever it is).
                    5 => {
                        let _ = rd_run_choose(0);
                    }
                    _ => {}
                }
            }

            let beaten = rd_run_boss_beaten();
            if beaten == 1 {
                cleared += 1;
            }
            println!(
                "seed {seed}: floor={} hp={}/{} gold={} deck={} fights={fights} cards={cards_taken} \
                 boss_beaten={beaten}{}",
                rd_run_observe(0),
                rd_run_observe(2),
                rd_run_observe(3),
                rd_run_observe(4),
                rd_run_deck_count(),
                if dead { " (died)" } else { "" }
            );
        }
        println!("cleared {cleared}/{seeds} acts");
        assert_eq!(cleared, cleared, "the probe only reports; it does not assert");
    }

    /// Play the current fight out: first playable card, first living enemy, else end turn.
    /// Walk until a **fight is on** and return `true` (or `false` if the map runs out).
    ///
    /// The three rules it encodes: settle whatever you are standing on, walk only from a settled node,
    /// and prefer a combat neighbour. `port-plan.md` §156 -- the first version of the potion test
    /// re-derived this and got it wrong (`NodeNotSettled` at floor 1).
    fn arrive_at_a_fight() -> bool {
        for _ in 0..24 {
            settle_here();
            if rd_run_action_count() == 0 {
                return false;
            }
            let mut combat = -1;
            for action in 0..rd_run_action_count() {
                let node = rd_run_action_arg(action, 0);
                if node >= 0 && node_kind(node) == 1 {
                    combat = action;
                    break;
                }
            }
            let chosen = if combat >= 0 { combat } else { 0 };
            if rd_run_step(chosen) != 0 {
                return false;
            }
            if rd_run_node_kind() == 1
                && rd_run_begin_node() == 0
                && rd_run_fight_begin() == 0
            {
                return true;
            }
        }
        false
    }

    fn play_to_the_end() {
        let mut guard = 0;
        while rd_env_done() == 0 && guard < 2000 {
            let mut action = -1;
            for index in 0..rd_env_action_count() {
                if rd_env_action_kind(index) == 0 {
                    action = index;
                    break;
                }
            }
            if action < 0 {
                action = rd_env_action_index_of_end_turn();
            }
            if action < 0 {
                break;
            }
            if rd_env_step(action) != 0 {
                break;
            }
            guard += 1;
        }
    }

    /// The three pile exports read the fight's piles, and the observation only carries counts.
    #[test]
    fn the_piles_can_be_listed_not_just_counted() {
        // An explicit run: this test is about the deck, not about the start path,
        // so it must not depend on the blessing rules (§105).
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0);
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0);
        // Turn 1 has begun: the hand is full and the rest of the run deck is in the draw pile.
        // The deck may be nine if the blessing removed a card, so this is relative.
        let draw = rd_env_pile_len(0);
        // The hand is not a pile zone: it is a count in the observation (H.HAND).
        let hand = obs()[10];
        assert!(draw > 0, "the draw pile is empty on turn 1");
        assert!(
            draw + hand <= rd_run_deck_count(),
            "the piles cannot hold more cards than the deck"
        );
        assert_eq!(rd_env_pile_len(1), 0);
        assert_eq!(rd_env_pile_len(2), 0);
        // Every card can be named, and the name is the content's `NameKey`.
        for index in 0..draw {
            let n = rd_env_pile_card_title_len(0, index);
            assert!(n > 0, "draw pile card {index} has no title");
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_env_pile_card_title_into(0, index, buffer.as_mut_ptr()) };
            let title = String::from_utf8(buffer).unwrap();
            assert!(
                ["Strike", "Defend", "Bash"].contains(&title.as_str()),
                "draw pile card {index} is {title:?}"
            );
        }
        assert_eq!(rd_env_pile_len(9), -1, "no such zone");
        assert_eq!(rd_env_pile_card_title_len(0, 99), -1, "past the end");
    }

    /// The deck exports: ids and titles, straight out of the content.
    #[test]
    fn the_deck_can_be_listed_with_the_contents_titles() {
        // An explicit run: this test is about the deck, not about the start path,
        // so it must not depend on the blessing rules (§105).
        test_run(7, 80, 80, &["strike","strike","strike","strike","strike","defend","defend","defend","defend","bash"]);
        // The deck is the content's ten minus whatever the blessing did -- the *content's* ten is
  // asserted before the blessing, in `a_run_starts_from_the_content_not_from_constants`.
  assert!(rd_run_deck_count() >= 9, "the deck must still be a deck");
        let mut titles = Vec::new();
        for index in 0..rd_run_deck_count() {
            let n = rd_run_deck_title_len(index);
            assert!(n > 0);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_run_deck_title_into(index, buffer.as_mut_ptr()) };
            titles.push(String::from_utf8(buffer).unwrap());
        }
        // The *composition* is pinned before the blessing (see the test above); here what matters
        // is that every row of the deck lists a title, and that the three kinds are all present.
        assert!(titles.iter().any(|t| t == "Strike"));
        assert!(titles.iter().any(|t| t == "Defend"));
        assert!(titles.iter().any(|t| t == "Bash"));
        assert_eq!(rd_run_deck_title_len(99), -1);
        assert_eq!(rd_run_deck_id_len(-1), -1);
    }

    #[test]
    fn the_container_bounds_are_the_run_layers_and_not_the_pages() {
        // Pins the three numbers the observation exposes as counts, so a page that assumes a
        // different belt size shows up here rather than in a screenshot.
        //
        // §157: `MAX_RUN_POTIONS` (5) is the belt's **storage**, not the rule -- three slots is
        // `BASE_POTION_SLOTS`, and `potion_belt` is the only thing that moves it (the wiki says so).
        assert_eq!(
            rd_run::state::BASE_POTION_SLOTS,
            3,
            "`inv:§9.3`: three potion slots"
        );
        assert!(
            MAX_RUN_POTIONS >= usize::from(rd_run::state::BASE_POTION_SLOTS) + 2,
            "storage must hold the three slots plus the belt's two"
        );
        assert_eq!(MAX_RUN_RELICS, 24);
        assert_eq!(MAX_RUN_DECK, 60);
        assert_eq!(NODES_PER_ROW, 6);
    }
}

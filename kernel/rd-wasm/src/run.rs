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
}

static mut RUN: Option<RunSession> = None;
/// The scratch size, as a `const` so reading it does not need `unsafe` (a mutable static's length
/// may not be read outside an `unsafe` block, and the length is not the unsafe part).
const RUN_SCRATCH_LEN: usize = 1024;

/// Scratch for the error text handed across the boundary.
static mut RUN_SCRATCH: [u8; RUN_SCRATCH_LEN] = [0; RUN_SCRATCH_LEN];

/// The run slot. Same argument as `lib.rs::slot()`: single-threaded wasm, no export re-enters
/// another export, the value lives in BSS for the module's lifetime.
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
    for card in full_pool(content)? {
        let id = card.id;
        if id.ends_with('+') {
            continue;
        }
        // `rd-run` drops `Status`/`Curse` from the roll itself -- one rule, one owner.
        pool.push(card);
    }
    Ok(pool)
}

/// The content's relic ids, in table order.
fn relic_pool(content: &'static Content<'static>) -> Vec<&'static str> {
    let mut out = Vec::new();
    let mut index = 0u32;
    while let Some(row) = content.row(rd_core::content::Table::Relic, index) {
        if let Some(relic) = rd_core::content::RelRow::new(row) {
            if let Some(id) = content.string(relic.id()) {
                out.push(id);
            }
        }
        index += 1;
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
#[no_mangle]
pub extern "C" fn rd_run_start(seed: i32) -> i32 {
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

    let mut state = match RunState::new(seed, facts.max_health, facts.gold, &deck) {
        Ok(state) => Box::new(state),
        Err(e) => {
            set_error(&std::format!("RunState::new: {}", describe(&e)));
            return -6;
        }
    };
    // `StartingHealth` may be below the maximum; `adjust_health` is the clamped way to say so.
    state.adjust_health(facts.starting_health - facts.max_health);

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

    *run_slot() = Some(RunSession {
        state,
        error: String::new(),
        elite_fight: false,
        boss_fight: false,
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
        let count = image.event_count();
        if count == 0 {
            return fail(
                session,
                "内容里没有事件（`EV` 0 行）—— `?` 房无处可去",
            );
        }
        let pick = match session.state.rng_mut().roll(RunStream::Event, count) {
            Ok(value) => value,
            Err(e) => {
                let message = describe(&e);
                return fail(session, &message);
            }
        };
        let Some((id, _, _)) = image.event(pick) else {
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
    let outcome = session.state.rest();
    finish(session, outcome)
}

/// Smith: replace deck card `index` with its upgraded row.
#[no_mangle]
pub extern "C" fn rd_run_smith(index: i32) -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
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

/// Choice `slot`'s effect, as the ABI's small integer: 1 heal, 2 gold, 3 lose health, 4 max health,
/// 5 nothing, `-1` unknown. A caller that sees `-1` must not guess.
#[no_mangle]
pub extern "C" fn rd_run_event_effect(slot: i32) -> i32 {
    let Some(choice) = event_choice(slot) else {
        return -1;
    };
    effect_code(choice.effect)
}

/// Choice `slot`'s amount.
#[no_mangle]
pub extern "C" fn rd_run_event_amount(slot: i32) -> i32 {
    event_choice(slot).map_or(0, |choice| i32::from(choice.amount))
}

/// Take choice `slot` of the open event.
#[no_mangle]
pub extern "C" fn rd_run_choose(slot: i32) -> i32 {
    let Some(choice) = event_choice(slot) else {
        return -1;
    };
    let Some(effect) = effect_from(choice.effect, i32::from(choice.amount)) else {
        return -1;
    };
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    let outcome = session.state.resolve_event(effect).map(|_| 0i32);
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
fn effect_code(effect: &str) -> i32 {
    match effect {
        "heal" => 1,
        "gold" => 2,
        "damage" => 3,
        "max_hp" => 4,
        "nothing" => 5,
        _ => -1,
    }
}

fn effect_from(effect: &str, amount: i32) -> Option<rd_run::state::EventEffect> {
    use rd_run::state::EventEffect;
    Some(match effect {
        "heal" => EventEffect::Heal(amount),
        "gold" => EventEffect::Gold(amount),
        "damage" => EventEffect::LoseHealth(amount),
        "max_hp" => EventEffect::GainMaxHealth(amount),
        "nothing" => EventEffect::Nothing,
        _ => return None,
    })
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
    let outcome = session.state.take_potion().map(|_| 0i32);
    finish(session, outcome)
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
    session.elite_fight = kind == 2;
    session.boss_fight = kind == 7;
    let pool_name = match kind {
        2 => "Elite",
        7 => "Boss",
        _ => "Weak",
    };
    let encounters: Vec<&'static str> = match content.encounter_pool(pool_name) {
        Some(ids) => ids.iter().filter(|id| !id.is_empty()).copied().collect(),
        None => {
            let message = std::format!("内容里没有 `EncounterTables.{pool_name}` 池");
            return fail(session, &message);
        }
    };
    if encounters.is_empty() {
        return fail(session, "内容镜像里没有任何遭遇");
    }
    let pick = match session.state.rng_mut().roll(RunStream::Combat, encounters.len() as u32) {
        Ok(value) => value as usize,
        Err(e) => {
            let message = describe(&e);
            return fail(session, &message);
        }
    };
    let fight_seed = match session.state.rng_mut().roll(RunStream::Combat, i32::MAX as u32) {
        Ok(value) => value as i32,
        Err(e) => {
            let message = describe(&e);
            return fail(session, &message);
        }
    };

    // The run's deck, compressed into (id, count) entries. Leaked because `FightPlan` borrows them
    // for the session's lifetime -- one small slice per fight, same trade as `build_session`.
    let mut counts: Vec<(&'static str, u16)> = Vec::new();
    for id in session.state.deck() {
        let id = id.as_str();
        match counts.iter_mut().find(|(name, _)| *name == id) {
            Some((_, count)) => *count += 1,
            None => counts.push((id, 1)),
        }
    }
    let entries: &'static [rd_core::battle::DeckEntry<'static>] =
        Box::leak(
            counts
                .into_iter()
                .map(|(card, count)| rd_core::battle::DeckEntry { card, count })
                .collect::<Vec<_>>()
                .into_boxed_slice(),
        );

    let max_health = session.state.health_max();
    match crate::build_session_with(fight_seed, encounters[pick], max_health, Some(entries)) {
        Ok(combat) => {
            crate::install_session(combat);
            // The fight is built at the hero's maximum; a run usually enters wounded.
            crate::set_combat_hero_health(session.state.health());
            0
        }
        Err(message) => {
            session.error.clear();
            session.error.push_str(&message);
            -2
        }
    }
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
    // Captured before the run is borrowed mutably below.
    let elite_fight = run_slot().as_ref().is_some_and(|s| s.elite_fight);
    let boss_fight = run_slot().as_ref().is_some_and(|s| s.boss_fight);
    crate::take_session();
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    // The fight is over: the run's health becomes the hero's.
    let delta = hero_hp - session.state.health();
    session.state.adjust_health(delta);
    // `inv:§5`: the tier follows what was fought, and it moves gold and rarity together.
    // `inv:§4.3`: a boss pays 95-105 and its reward is always rare.
    let fight_kind = if boss_fight {
        rd_run::state::FightKind::Boss
    } else if elite_fight {
        rd_run::state::FightKind::Elite
    } else {
        rd_run::state::FightKind::Normal
    };
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
        // The potion the fight may drop (`inv:§9.3`) is one of the image's own potions. A package
        // without a `POT` table simply never offers one.
        let mut potion_ids = std::vec::Vec::new();
        for index in 0..image.potion_count() {
            if let Some(potion) = image.potion(index) {
                potion_ids.push(potion.id);
            }
        }
        if let Err(e) = session
            .state
            .roll_reward(&pool, &potion_ids, fight_kind)
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

    fn reset(seed: i32) {
        assert_eq!(rd_run_start(seed), 0, "rd_run_start({seed}) failed");
    }

    fn obs() -> Vec<i32> {
        (0..rd_run_observe_len()).map(|index| rd_run_observe(index)).collect()
    }

    #[test]
    fn a_run_starts_from_the_content_not_from_constants() {
        reset(7);
        let o = obs();
        assert_eq!(rd_run_seed(), 7);
        // `Characters[0].Start` in the sts package says MaxHealth/StartingHealth 80 and gold 0.
        assert_eq!(o[2], 80, "health");
        assert_eq!(o[3], 80, "max health");
        assert_eq!(o[4], 0, "gold comes out of the content, which says 0");
        assert_eq!(o[5], 10, "`inv:§2.1`: a ten-card starting deck");
        assert_eq!(o[0], 0, "floor is 0 before the first step");
        assert_eq!(o[1], -1, "the cursor starts off the map");
        // `rd_run_start` **generates the map**, and generation draws from the `Map` stream, so that
        // counter is not zero. The other six are untouched -- which is the substream property
        // (`run-layer.md` §3.6) observed from the outside.
        for (index, value) in o.iter().enumerate().take(16).skip(10) {
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
        reset(11);
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
        reset(5);
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
        reset(9);
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
        reset(1);
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

    /// The effect fires, and it is capped: `Burning Blood` heals 6 but never past the maximum.
    #[test]
    fn burning_blood_heals_at_the_end_of_the_fight() {
        reset(7);
        let session = run_slot().as_mut().expect("session");
        session.state.adjust_health(-20);
        assert_eq!(session.state.end_of_combat(), Ok(6));
        assert_eq!(session.state.health(), 66);
        session.state.adjust_health(1000);
        assert_eq!(session.state.end_of_combat(), Ok(0), "nothing to heal at full health");
    }

    /// The link the run layer did not have: a fight is **the run's** fight, and its result goes back.
    ///
    /// `inv:§7.2` fixes floor 1 to be all combat, so the first step lands on one -- no search.
    #[test]
    fn a_fight_is_the_runs_fight_and_the_result_goes_back() {
        reset(7);
        assert_eq!(rd_run_step(0), 0, "floor 1");
        assert_eq!(rd_run_node_kind(), 1, "floor 1 is all combat (inv:§7.2)");
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_pending(), 0, "a fight has nothing for the run layer to settle");

        // The hero enters wounded, and the fight has to know that.
        {
            let session = run_slot().as_mut().unwrap();
            session.state.adjust_health(-20);
            assert_eq!(session.state.health(), 60);
        }
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");
        assert_eq!(
            crate::combat_hero_health(),
            Some(60),
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
        assert_eq!(piles + hand, 10, "inv:§2.1: a ten-card starting deck");

        // Ending it folds the health back and drops the session.
        assert_eq!(rd_run_fight_end(), 0, "a fight still in progress ends as Ongoing");
        assert_eq!(rd_run_fight_end(), -1, "there is no second fight to end");
        let session = run_slot().as_ref().unwrap();
        assert_eq!(session.state.health(), 60, "the fight did not change the run's health");
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
        assert_eq!(start, 80);

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

        // Taking one adds exactly that card and closes the screen.
        let wanted = ids[2].clone();
        assert_eq!(rd_run_take_card(2), 0);
        assert_eq!(rd_run_deck_count(), deck_before + 1);
        assert_eq!(rd_run_pending(), 0);
        let last = {
            let n = rd_run_deck_id_len(rd_run_deck_count() - 1);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_run_deck_id_into(rd_run_deck_count() - 1, buffer.as_mut_ptr()) };
            String::from_utf8(buffer).unwrap()
        };
        assert_eq!(last, wanted);

        // And skipping is a way out of the screen, not a stuck state.
        assert_eq!(rd_run_skip_reward(), -2, "there is no screen to skip");
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
                let _ = rd_run_choose(0);
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

        // Three sentries, not the weak pool's slimes.
        let mut names = Vec::new();
        let mut index = 0;
        while rd_env_enemy_name_len(index) >= 0 {
            let n = rd_env_enemy_name_len(index);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_env_enemy_name_into(index, buffer.as_mut_ptr()) };
            names.push(String::from_utf8(buffer).unwrap_or_default());
            index += 1;
        }
        assert_eq!(names.len(), 3, "3 sentries; got {names:?}");
        assert!(
            names.iter().all(|name| name.to_lowercase().contains("sentry")),
            "the elite fought {names:?}"
        );

        // Play it out, then check the tier: `inv:§5` pays an elite 25-35 gold.
        let mut guard = 0;
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
            assert_eq!(rd_env_step(action), 0);
            guard += 1;
        }
        let result = rd_run_fight_end();
        if result == 1 {
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
        assert!(
            names[0].to_lowercase().contains("slime_boss"),
            "the boss is the slime boss; got {names:?}"
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
            assert!((1..=5).contains(&effect), "choice {slot} effect {effect}");
        }
        assert_eq!(rd_run_event_label_len(2), -1, "only two choices");

        let gold_before = rd_run_observe(4);
        let hp_before = rd_run_observe(2);
        let hp_max_before = rd_run_observe(3);
        let effect = rd_run_event_effect(0);
        let amount = rd_run_event_amount(0);
        assert_eq!(rd_run_choose(0), 0, "choosing must be accepted");
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
        assert_eq!(rd_run_node_resolved(), 1, "the room paid once");
        // A second choice is a **wrong-phase** refusal (-2 with text), not "no such
        // choice" (-1): the event is still on record, it is the phase that is gone.
        assert_eq!(rd_run_choose(0), -2, "a second choice is refused");
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
        reset(7);
        assert_eq!(rd_run_step(0), 0);
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0);
        // Turn 1 has begun, so five cards are in hand and five are still in the draw pile.
        let draw = rd_env_pile_len(0);
        assert_eq!(draw, 5, "five drawn, five left");
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
        reset(7);
        assert_eq!(rd_run_deck_count(), 10);
        let mut titles = Vec::new();
        for index in 0..rd_run_deck_count() {
            let n = rd_run_deck_title_len(index);
            assert!(n > 0);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_run_deck_title_into(index, buffer.as_mut_ptr()) };
            titles.push(String::from_utf8(buffer).unwrap());
        }
        assert_eq!(titles.iter().filter(|t| *t == "Strike").count(), 5, "inv:§2.1");
        assert_eq!(titles.iter().filter(|t| *t == "Defend").count(), 4);
        assert_eq!(titles.iter().filter(|t| *t == "Bash").count(), 1);
        assert_eq!(rd_run_deck_title_len(99), -1);
        assert_eq!(rd_run_deck_id_len(-1), -1);
    }

    #[test]
    fn the_container_bounds_are_the_run_layers_and_not_the_pages() {
        // Pins the three numbers the observation exposes as counts, so a page that assumes a
        // different belt size shows up here rather than in a screenshot.
        assert_eq!(MAX_RUN_POTIONS, 3, "`inv:§9.3`: three potion slots");
        assert_eq!(MAX_RUN_RELICS, 24);
        assert_eq!(MAX_RUN_DECK, 60);
        assert_eq!(NODES_PER_ROW, 6);
    }
}

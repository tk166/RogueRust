//! The run's state: where you are, what you carry, and the counters that decide what happens next.
//!
//! Frozen shape: `docs/spec/run-layer.md` §4. Two things about it are decisions rather than
//! transcription, and both are written down because they are the kind that becomes a hidden
//! assumption:
//!
//! 1. **It has no idea what content is.** Starting health, the starting deck, relic ids and potion
//!    ids all come from the content document, and this struct only stores what it is handed
//!    ([`RunState::new`] takes them as arguments). The alternative — teaching this crate to read a
//!    content image — would duplicate the content layer and give the run two places where a card's
//!    identity is decided.
//! 2. **Every capacity fails loudly.** `deck`, `relics` and `potions` are fixed arrays, and pushing
//!    past the end is [`RunError::Capacity`], never a dropped push. `run-layer.md` §4.4 spells out
//!    why: StS decks can exceed sixty cards in the late game, so the bound is a capacity and *not*
//!    a budget to be squeezed — it must only ever be visible as a red.
//!
//! Its size is checked against a **tripwire** (not a target) in
//! [`state_fits_the_tripwire`], for the same reason `CombatState` has one.

use rd_core::state::{Ident, ID_CAP};

use crate::map::{RunMap, NODES_PER_ROW, ROWS};
use crate::streams::{RunError, RunRng, RunStream};

/// The most cards a run's deck may hold. See the module docs: exceeding it is an error, never a
/// truncation.
pub const MAX_RUN_DECK: usize = 60;
/// The most relics a run may hold. `inv:§6` has 140 obtainable, but a single run sees on the order
/// of a dozen; twenty-four is "what a run needs", not "what a budget allows".
pub const MAX_RUN_RELICS: usize = 24;
/// The potion belt (`inv:§9.3`: hold at most 3).
/// How many acts a run has. Killing the boss of an act before the last one **advances**; killing the
/// last one wins the run.
pub const MAX_ACT: u8 = 3;

pub const MAX_RUN_POTIONS: usize = 3;
/// `inv:§9.3`: a potion drops from 40% of fights (the act-1 reset value; the ±10% per act is not
/// modelled because there is one act).
pub const POTION_DROP_PERCENT: u32 = 40;

/// `Burning Blood`: "At the end of combat, heal 6 HP" (`inv:§2`).
pub const BURNING_BLOOD_HEAL: i32 = 6;

/// Card slots a merchant shows (`inv:§8.2`: five coloured cards; the two colourless ones are not
/// modelled -- this content has no colourless pool).
pub const MAX_SHOP_CARDS: usize = 5;
/// Relic slots a merchant shows (`inv:§8.2`: three).
pub const MAX_SHOP_RELICS: usize = 3;
/// What a card costs by rarity (`inv:§8.2`): Common 45–55, Uncommon 68–82, Rare 135–165.
///
/// `Basic` / `Status` / `Curse` are not things a merchant sells; if one reaches the shelf it is
/// priced in the Common band, which is the closest thing to a documented answer.
#[must_use]
pub const fn card_price_band(rarity: Rarity) -> (i32, i32) {
    match rarity {
        Rarity::Common | Rarity::Basic | Rarity::Status | Rarity::Curse => (45, 55),
        Rarity::Uncommon => (68, 82),
        Rarity::Rare => (135, 165),
    }
}

/// Card-removal price the first time (`inv:§8.2`).
pub const SHOP_REMOVE_BASE: i32 = 75;
/// ...and how much it grows per use, across shops in the same run (`inv:§8.2`).
pub const SHOP_REMOVE_STEP: i32 = 25;
/// `inv:§8.1`: a rest site heals 30% of maximum HP, rounded down.
pub const REST_HEAL_PERCENT: i32 = 30;
/// `inv:§3.5`: a reward screen shows three cards, all different.
pub const MAX_REWARD_CARDS: usize = 3;
/// `inv:§5`: a normal fight pays 10–20 gold (elite 25–35, boss 95–105).
pub const NORMAL_FIGHT_GOLD: (i32, i32) = (10, 20);
/// `inv:§3.5`: the pity offset starts at −5%, ticks +1% per non-rare roll, resets on a rare.
pub const RARITY_OFFSET_START: i32 = -5;
/// ...and its ceiling.
pub const RARITY_OFFSET_CAP: i32 = 40;
/// The pools a shop or a chest draws from are caller-supplied (this crate knows no content), so the
/// walk below needs a bound. Exceeding it is [`RunError::EmptyPool`]'s sibling: a loud error.
pub const MAX_POOL: usize = 64;

/// What the node under the cursor is waiting for.
///
/// A node is not settled by walking onto it (`env-abi.md` §11.5): walking sets the cursor, and
/// [`RunState::begin_node`] declares what the node then needs. Keeping the two apart is what lets
/// the map page walk a whole Act without pretending a fight happened.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
#[repr(u8)]
pub enum Pending {
    /// Nothing to settle: a fight the caller is running, or a node already dealt with.
    #[default]
    None = 0,
    /// [`RunState::rest`] or [`RunState::smith`].
    Rest = 1,
    /// [`RunState::buy_card`] / [`RunState::buy_relic`] / [`RunState::remove_card`] / [`RunState::leave`].
    Shop = 2,
    /// [`RunState::open_chest`].
    Chest = 3,
    /// [`RunState::take_card`] or [`RunState::skip_reward`] -- the screen after a won fight.
    Reward = 4,
    /// [`RunState::resolve_event`] -- a `?` room, waiting for a choice.
    Event = 5,
    /// [`RunState::choose_start`] -- the pre-run blessing, before floor 1.
    Start = 6,
    /// [`RunState::pick_blessing_card`] -- a blessing that needs a deck index.
    BlessingCard = 7,
}

/// The pre-run choice (StS's Neow, `inv:§7.1`): the player picks one blessing from a rolled pair.
///
/// A blessing is a **gain and a cost**, both from [`EventEffect`]'s closed vocabulary -- that is how
/// "swap 10% of your max HP for 100 gold" is expressible without a program interpreter.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct StartOffer {
    /// The id (`max_hp`, `gold`, ...), for the UI and for the run hash.
    pub id: &'static str,
    /// Whether the blessing needs a card pick after it is taken.
    pub follow_up: BlessingFollowUp,
    /// What the player gets.
    pub gain: EventEffect,
    /// What it costs. [`EventEffect::Nothing`] for the free blessings.
    pub cost: EventEffect,
}

/// Neow's pool for act 1. Four entries so a pair is always available and distinct.
///
/// ⚠️ **This is not the wiki's pool**: StS draws from eight or so blessings with rarity weights.
/// Four, unweighted, is what this content can honour -- recorded in `inv:§7.1` rather than implied.
/// What a blessing still needs after it is picked. `None` finishes immediately; the other two need
/// a **deck index**, which is why they leave the run in `Pending::BlessingCard`.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum BlessingFollowUp {
    /// Nothing: the gain and the cost were the whole blessing.
    None,
    /// Remove deck card `N` (Neow's "remove a card").
    RemoveCard,
    /// Upgrade deck card `N`.
    UpgradeCard,
    /// Replace deck card `N` with a random one from the pool ("transform").
    TransformCard,
    /// Add three random cards, no pick needed -- it is finished the moment it is taken.
    GainThreeCards,
}

pub const START_OFFERS: [StartOffer; 8] = [
    StartOffer {
        id: "max_hp",
        gain: EventEffect::GainMaxHealth(8),
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::None,
    },
    StartOffer {
        id: "gold",
        gain: EventEffect::Gold(100),
        cost: EventEffect::LoseHealth(7),
        follow_up: BlessingFollowUp::None,
    },
    StartOffer {
        id: "heal",
        gain: EventEffect::Heal(25),
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::None,
    },
    StartOffer {
        id: "blood_money",
        gain: EventEffect::Gold(150),
        cost: EventEffect::LoseHealth(14),
        follow_up: BlessingFollowUp::None,
    },
    // The two blessings that are about the deck rather than a number (wiki `Neow`).
    StartOffer {
        id: "remove_card",
        gain: EventEffect::Nothing,
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::RemoveCard,
    },
    StartOffer {
        id: "upgrade_card",
        gain: EventEffect::Nothing,
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::UpgradeCard,
    },
    StartOffer {
        id: "transform_card",
        gain: EventEffect::Nothing,
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::TransformCard,
    },
    StartOffer {
        id: "three_cards",
        gain: EventEffect::Nothing,
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::GainThreeCards,
    },
];

/// What an event's choice does. The vocabulary is **closed** and comes from the content
/// (`EV.Effect0` / `EV.Effect1`); anything else is [`RunError::UnsupportedEventEffect`].
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum EventEffect {
    /// Restore HP, capped at the maximum.
    Heal(i32),
    /// Add gold.
    Gold(i32),
    /// Lose HP -- an event can hurt.
    LoseHealth(i32),
    /// Raise the maximum, and the current HP with it.
    GainMaxHealth(i32),
    /// Nothing at all -- a real, declared choice, not a missing one.
    Nothing,
}

/// A card's rarity (`inv:§3.5`; the six buckets StS uses).
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
#[repr(u8)]
pub enum Rarity {
    /// The starting deck's cards. Never offered by StS as a reward, but this content has nothing
    /// else, so the reward screen does offer them (see the fall-through in `roll_reward`).
    Basic = 0,
    /// ...
    Common = 1,
    /// ...
    Uncommon = 2,
    /// ...
    Rare = 3,
    /// Junk cards (`slimed`).
    Status = 4,
    /// Not in this content.
    Curse = 5,
}

impl Rarity {
    /// The name the content carries in `CARD.Rarity`.
    #[must_use]
    pub fn from_name(name: &str) -> Option<Self> {
        match name {
            "Basic" => Some(Self::Basic),
            "Common" => Some(Self::Common),
            "Uncommon" => Some(Self::Uncommon),
            "Rare" => Some(Self::Rare),
            "Status" => Some(Self::Status),
            "Curse" => Some(Self::Curse),
            _ => None,
        }
    }

    fn index(self) -> usize {
        self as u8 as usize
    }
}

/// A card as the reward roll sees it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolCard<'a> {
    /// The definition id.
    pub id: &'a str,
    /// Its rarity, from the content.
    pub rarity: Rarity,
}

/// Which fight paid. `inv:§5` / `inv:§3.5` differ per kind in **both** gold and rarity.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum FightKind {
    /// A normal fight: 10–20 gold, rare base 3%, uncommon band 37%.
    Normal,
    /// An elite: 25–35 gold, rare base 10%, uncommon band 40%.
    Elite,
    /// A boss: 95–105 gold, **always rare**.
    Boss,
}

impl FightKind {
    /// The gold range `inv:§5`.
    #[must_use]
    pub const fn gold(self) -> (i32, i32) {
        match self {
            Self::Normal => (10, 20),
            Self::Elite => (25, 35),
            Self::Boss => (95, 105),
        }
    }

    /// `base rare%` at offset 0 (`inv:§3.5`; wiki `Card Rewards`).
    #[must_use]
    pub const fn rare_base(self) -> i32 {
        match self {
            Self::Normal => 3,
            Self::Elite => 10,
            Self::Boss => 100,
        }
    }

    /// The uncommon band's **fixed width** (`inv:§3.5`: 37% normal, 40% elite).
    ///
    /// It is a width, not a probability: the band sits directly on top of the rare band, so it moves
    /// with it. See [`reward_bands`].
    #[must_use]
    pub const fn uncommon_width(self) -> i32 {
        match self {
            Self::Normal => 37,
            Self::Elite => 40,
            Self::Boss => 0,
        }
    }
}

/// The two band edges for one card roll, out of one 0–99 roll.
///
/// # This is the part a naive implementation gets wrong
///
/// The three rarities are **not** three independent chances. One number is rolled and checked
/// against bands stacked in order: rare first, then uncommon on top, then common gets the rest.
///
/// * the rare band is `base + offset`, **floored at 0**;
/// * the uncommon band is a fixed width that sits on top of it -- so when the rare band is
///   *negative*, the part of the uncommon band below 0 is clipped off and **goes to common**, not
///   to uncommon.
///
/// At a fresh normal-fight reset (`base 3 + offset -5 = -2`) that gives rare 0%, uncommon 35%,
/// common 65% -- the wiki states exactly that ("Actual at reset (offset -5%)"). An implementation
/// that clamps the rare band to 0 *and keeps uncommon at 37%* would quietly hand the 2% to uncommon.
#[must_use]
pub fn reward_bands(kind: FightKind, offset: i32) -> (i32, i32) {
    // A boss reward is rare at 100% and **does not read the offset** -- but it does *reset* it
    // (wiki `Card Rewards`, the "What doesn't update the pity counter" table: boss reads `no`,
    // updates `yes`). Applying the offset here would make a boss hand out a 95% rare roll.
    if kind == FightKind::Boss {
        return (100, 100);
    }
    let banded = kind.rare_base() + offset;
    let rare_top = banded.max(0);
    let uncommon_top = banded.max(0) + kind.uncommon_width() - (-banded).max(0);
    (rare_top, uncommon_top)
}

/// What a won fight pays (`inv:§5`): gold already granted, plus the cards on offer.
///
/// The three cards are **mutually distinct** (`inv:§3.5`: rolled one at a time, a later roll never
/// repeats an earlier one). The rarity weights of `inv:§3.5` are not applied: this content carries
/// no rarity, so every card in the pool is treated as one bucket -- the same `[推断]` the merchant's
/// prices carry, and it is recorded in `sts-act1-plan.md`'s downgrade table.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Reward {
    gold: i32,
    cards: [RunId; MAX_REWARD_CARDS],
    cards_len: u8,
    /// The potion this fight dropped, if any (`inv:§9.3`: 40% of fights, and a full belt simply
    /// means the offer cannot be taken).
    potion: RunId,
}

impl Reward {
    /// Nothing on the table.
    #[must_use]
    pub const fn empty() -> Self {
        Self {
            gold: 0,
            cards: [RunId::EMPTY; MAX_REWARD_CARDS],
            cards_len: 0,
            potion: RunId::EMPTY,
        }
    }

    /// The gold this fight paid (already added to the run).
    #[must_use]
    pub const fn gold(&self) -> i32 {
        self.gold
    }

    /// The cards on offer.
    #[must_use]
    pub fn cards(&self) -> &[RunId] {
        &self.cards[..self.cards_len as usize]
    }
}

/// One thing a merchant is selling. `price < 0` means "already sold".
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Offer {
    /// The card or relic id.
    pub id: RunId,
    /// Price in gold, or `-1` once bought.
    pub price: i32,
}

impl Offer {
    const EMPTY: Self = Self {
        id: RunId::EMPTY,
        price: -1,
    };
}

/// A merchant's stock. Fixed size: five cards and three relics (`inv:§8.2`).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct ShopStock {
    cards: [Offer; MAX_SHOP_CARDS],
    cards_len: u8,
    relics: [Offer; MAX_SHOP_RELICS],
    relics_len: u8,
}

impl ShopStock {
    /// An empty shelf.
    #[must_use]
    pub const fn empty() -> Self {
        Self {
            cards: [Offer::EMPTY; MAX_SHOP_CARDS],
            cards_len: 0,
            relics: [Offer::EMPTY; MAX_SHOP_RELICS],
            relics_len: 0,
        }
    }

    /// The card offers.
    #[must_use]
    pub fn cards(&self) -> &[Offer] {
        &self.cards[..self.cards_len as usize]
    }

    /// The relic offers.
    #[must_use]
    pub fn relics(&self) -> &[Offer] {
        &self.relics[..self.relics_len as usize]
    }
}

/// What opening a chest gave.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct ChestOutcome {
    /// 0 small, 1 medium, 2 large (`inv:§8.3`).
    pub chest: u8,
    /// Gold, or 0 when the roll declined to give any (`inv:§8.3` has a per-chest chance).
    pub gold: i32,
    /// The relic, if the pool had one.
    pub relic: Option<RunId>,
}
/// The most nodes one step can offer: the first floor is chosen freely among a whole row.
pub const MAX_STEP_TARGETS: usize = NODES_PER_ROW;

/// A tripwire, not a budget. Measured value lives in [`RunState::size_bytes`]; this bound is here so
/// that adding a field cannot quietly double the run's memory. `CombatState`'s equivalent has the
/// same job (`rd-core/src/state.rs::state_fits_the_sram_plan`).
pub const RUN_STATE_TRIPWIRE_BYTES: usize = 8 * 1024;

/// A deck/relic/potion id. `Ident<ID_CAP>` is 41 bytes (`ID_CAP` 40 + a length byte).
pub type RunId = Ident<ID_CAP>;

/// Where the cursor can legally go next. At most one row's worth of nodes.
///
/// Holds **global** node indices, because that is what every consumer wants: the internal storage
/// numbering (row, row-local index) is an implementation choice, and forcing each caller to
/// recompute the row offsets is how off-by-one bugs get shipped.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Reachable {
    slots: [u8; MAX_STEP_TARGETS],
    len: u8,
}

impl Reachable {
    /// How many nodes can be entered.
    #[must_use]
    pub const fn len(&self) -> usize {
        self.len as usize
    }

    /// Always false (a run always has somewhere to go until it is over); present so clippy's
    /// `len_without_is_empty` stays honest instead of suppressed.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// The `index`-th reachable node's global index.
    #[must_use]
    pub fn get(&self, index: usize) -> Option<u8> {
        if index < self.len() {
            Some(self.slots[index])
        } else {
            None
        }
    }

    /// Whether `global` is reachable from here.
    #[must_use]
    pub fn contains(&self, global: u8) -> bool {
        self.slots[..self.len()].contains(&global)
    }

    fn push(&mut self, global: u8) {
        // The caller bounds this by construction (at most one row of nodes); the assert makes a
        // future caller that breaks that assumption loud instead of silently dropping a target.
        assert!(
            (self.len as usize) < MAX_STEP_TARGETS,
            "more than {MAX_STEP_TARGETS} reachable nodes: the caller is not a single row"
        );
        self.slots[self.len as usize] = global;
        self.len += 1;
    }
}

/// One run. `Copy`, POD, no allocation — the same discipline as `CombatState`, so it can be
/// snapshotted and (later) relocated.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct RunState {
    seed: i32,
    floor: i32,
    health: i32,
    health_max: i32,
    gold: i32,
    /// `-1` before the first step (`run-layer.md` §6.2 invariant 1).
    node: i32,
    removed_cards: i32,
    deck: [RunId; MAX_RUN_DECK],
    deck_len: u8,
    relics: [RunId; MAX_RUN_RELICS],
    relics_len: u8,
    potions: [RunId; MAX_RUN_POTIONS],
    potions_len: u8,
    map: RunMap,
    /// See [`RunState::map_generation_failed`].
    map_generation_failed: bool,
    rng: RunRng,
    /// `?` room cumulative odds (`inv:§7.5`), three counters, reset at the start of an act.
    unknown: [i32; 3],
    /// What the node under the cursor is waiting for.
    pending: Pending,
    /// The merchant's stock while standing in a shop.
    shop: ShopStock,
    /// The card choice after a won fight.
    reward: Reward,
    /// Has the act been **cleared**? Set when the boss dies (`inv:§7.2`: the boss is the end of the
    /// act). Until this existed a run could not be won, only lost.
    boss_beaten: bool,
    /// Which nodes have paid out. A node settles **once** -- a second visit is an error, which is
    /// what stops a fight from being farmed and a campfire from healing on every click.
    resolved: [u64; 2],
    /// Which act this run is on (1-based). Killing an act's boss advances it.
    act: u8,
    /// The `?`-room event under the cursor, while `Pending::Event`.
    event: RunId,
    /// Which two blessings were rolled, as indices into [`START_OFFERS`].
    start_offers: [u8; 2],
    /// The picked blessing's follow-up, while [`Pending::BlessingCard`] waits for a deck index.
    blessing_follow: Option<BlessingFollowUp>,
    /// The rare-card pity offset (`inv:§3.5`): starts at −5%, +1% per non-rare reward roll, reset to
    /// −5% on a rare, capped at +40%. Only **combat reward** rolls move it.
    rarity_offset: i32,
}

impl RunState {
    /// Start a run: generate the map from the `Map` stream, and take the content-derived starting
    /// facts as arguments (see the module docs).
    ///
    /// `starting_deck` is the deck **in order** — deck order is observable (`run-layer.md` §5.2),
    /// so it is not sorted here or anywhere else.
    pub fn new(
        seed: i32,
        health_max: i32,
        gold: i32,
        starting_deck: &[&str],
    ) -> Result<Self, RunError> {
        let mut rng = RunRng::new(seed);
        let map = RunMap::generate(&mut rng)?;
        let mut state = Self {
            seed,
            floor: 0,
            health: health_max,
            health_max,
            gold,
            node: -1,
            removed_cards: 0,
            deck: [RunId::EMPTY; MAX_RUN_DECK],
            deck_len: 0,
            relics: [RunId::EMPTY; MAX_RUN_RELICS],
            relics_len: 0,
            potions: [RunId::EMPTY; MAX_RUN_POTIONS],
            potions_len: 0,
            map,
            map_generation_failed: false,
            rng,
            unknown: [0; 3],
            pending: Pending::None,
            shop: ShopStock::empty(),
            reward: Reward::empty(),
            boss_beaten: false,
            act: 1,
            event: RunId::EMPTY,
            // Rolled by `offer_start_choice`; until then the pair is not a choice anyone can take.
            start_offers: [0, 1],
            blessing_follow: None,
            resolved: [0; 2],
            rarity_offset: RARITY_OFFSET_START,
        };
        for id in starting_deck {
            state.push_card(id)?;
        }
        state.check_invariants()?;
        Ok(state)
    }

    // ---- reads -----------------------------------------------------------------------------

    /// The run seed.
    #[must_use]
    pub const fn seed(&self) -> i32 {
        self.seed
    }
    /// 0 before the first step, then 1..=ROWS.
    #[must_use]
    pub const fn floor(&self) -> i32 {
        self.floor
    }
    /// Health, always in `0..=health_max`.
    #[must_use]
    pub const fn health(&self) -> i32 {
        self.health
    }
    /// Maximum health.
    #[must_use]
    pub const fn health_max(&self) -> i32 {
        self.health_max
    }
    /// Gold.
    #[must_use]
    pub const fn gold(&self) -> i32 {
        self.gold
    }
    /// The current node's global index, or `-1` before the first step.
    #[must_use]
    pub const fn node(&self) -> i32 {
        self.node
    }
    /// Cards removed by shops (`inv:§8.2`). Unused until M2b; carried so the field exists.
    #[must_use]
    pub const fn removed_cards(&self) -> i32 {
        self.removed_cards
    }
    /// The map.
    #[must_use]
    pub const fn map(&self) -> &RunMap {
        &self.map
    }
    /// The random streams.
    #[must_use]
    pub const fn rng(&self) -> &RunRng {
        &self.rng
    }
    /// Mutable access to the streams, for the settlement code that lands next.
    pub fn rng_mut(&mut self) -> &mut RunRng {
        &mut self.rng
    }
    /// The deck, in acquisition order.
    #[must_use]
    pub fn deck(&self) -> &[RunId] {
        &self.deck[..self.deck_len as usize]
    }
    /// The relics, in acquisition order.
    #[must_use]
    pub fn relics(&self) -> &[RunId] {
        &self.relics[..self.relics_len as usize]
    }
    /// The potions, in belt order.
    #[must_use]
    pub fn potions(&self) -> &[RunId] {
        &self.potions[..self.potions_len as usize]
    }
    /// The `?` room odds (`inv:§7.5`).
    #[must_use]
    pub const fn unknown_odds(&self) -> [i32; 3] {
        self.unknown
    }

    /// The measured size, for the tripwire and for anyone printing a memory table.
    #[must_use]
    pub const fn size_bytes() -> usize {
        core::mem::size_of::<Self>()
    }

    // ---- writes ----------------------------------------------------------------------------

    /// Add a card to the deck. Past [`MAX_RUN_DECK`] this is an **error**, never a dropped push.
    pub fn push_card(&mut self, definition_id: &str) -> Result<(), RunError> {
        let id = RunId::new(definition_id).map_err(|_| RunError::BadId)?;
        let slot = self.deck_len as usize;
        if slot >= MAX_RUN_DECK {
            return Err(RunError::Capacity);
        }
        self.deck[slot] = id;
        self.deck_len += 1;
        Ok(())
    }

    /// Add a relic. Past [`MAX_RUN_RELICS`] this is an error.
    pub fn push_relic(&mut self, relic_id: &str) -> Result<(), RunError> {
        let id = RunId::new(relic_id).map_err(|_| RunError::BadId)?;
        let slot = self.relics_len as usize;
        if slot >= MAX_RUN_RELICS {
            return Err(RunError::Capacity);
        }
        self.relics[slot] = id;
        self.relics_len += 1;
        Ok(())
    }

    /// Add a potion. Past [`MAX_RUN_POTIONS`] this is an error (the belt has three slots).
    pub fn push_potion(&mut self, potion_id: &str) -> Result<(), RunError> {
        let id = RunId::new(potion_id).map_err(|_| RunError::BadId)?;
        let slot = self.potions_len as usize;
        if slot >= MAX_RUN_POTIONS {
            return Err(RunError::Capacity);
        }
        self.potions[slot] = id;
        self.potions_len += 1;
        Ok(())
    }

    /// Throw away belt slot `index`. The survivors keep their order (the belt is a list, not a set).
    ///
    /// Dropping is how the player makes room when the belt is full and a fight offers another one --
    /// which is also what makes [`RunState::take_potion`]'s `Capacity` error actionable instead of a
    /// dead end.
    pub fn drop_potion(&mut self, index: usize) -> Result<(), RunError> {
        if index >= self.potions_len as usize {
            return Err(RunError::NoSuchPotion);
        }
        let last = self.potions_len as usize - 1;
        for slot in index..last {
            self.potions[slot] = self.potions[slot + 1];
        }
        self.potions[last] = RunId::EMPTY;
        self.potions_len -= 1;
        Ok(())
    }

    /// What the relics do when a fight ends.
    ///
    /// # The design, stated once
    ///
    /// A relic's effect is **not** data in this kernel: `REL.RunPrograms` and `REL.CombatRules` are
    /// never executed (there is no run-level program interpreter and no `CombatRules` registry), so
    /// every effect is an explicit rule here, keyed on the id. That is a real limitation and it is
    /// made loud instead of quiet: an id this function does not know is
    /// [`RunError::UnsupportedRelic`], never "a relic that does nothing".
    ///
    /// Returns the health actually restored, so a caller can show "+6".
    pub fn end_of_combat(&mut self) -> Result<i32, RunError> {
        let mut healed = 0i32;
        for slot in 0..self.relics_len as usize {
            let id = self.relics[slot].as_str();
            match id {
                // `inv:§2`: "At the end of combat, heal 6 HP." The heal is capped at the maximum,
                // so `heal_after_combat` is the right primitive (it clamps).
                "burning_blood" => {
                    let before = self.health;
                    self.heal_after_combat(BURNING_BLOOD_HEAL);
                    healed += self.health - before;
                }
                _ => {
                    return Err(RunError::UnsupportedRelic {
                        index: slot as u8,
                    })
                }
            }
        }
        Ok(healed)
    }

    /// Take the `Burning Blood` heal (`inv:§2`: +6 HP at the end of combat). **Capped at the
    /// maximum**, never above it. This is M1's only relic effect and it is deliberate: without it
    /// every fight would end with the wrong HP, and HP is the number the whole run walks on.
    pub fn heal_after_combat(&mut self, amount: i32) {
        self.health = (self.health + amount).min(self.health_max);
    }

    /// Adjust health (damage negative). Clamped to `0..=health_max`; the floor matters because a
    /// run at 0 HP is over, not negative.
    pub fn adjust_health(&mut self, delta: i32) {
        self.health = (self.health + delta).clamp(0, self.health_max);
    }

    /// Add or spend gold, clamped at 0.
    pub fn adjust_gold(&mut self, delta: i32) {
        self.gold = (self.gold + delta).max(0);
    }

    // ---- walking the map -------------------------------------------------------------------

    /// Where the cursor can go next.
    ///
    /// Before the first step, that is **every node on floor 1** (`inv:§7.2`: the player picks a
    /// start). Afterwards, it is the current node's out-edges.
    #[must_use]
    pub fn reachable(&self) -> Reachable {
        let mut out = Reachable::default();
        // **Nothing is legal while a choice is pending** -- the pre-run blessing (inv:§7.1), a won
        // fight's reward, a shop, a campfire, an event. Offering steps here is what let a map click
        // overwrite the choice panel with a refusal, which left the player with no way forward at
        // all (found by hand, 2026-10-22: "第一个节点就点不进去").
        if self.pending != Pending::None {
            return out;
        }
        if self.node < 0 {
            let Some(first) = self.map.row_first(0) else {
                return out;
            };
            let count = self.map.row(0).map_or(0, |row| row.len());
            for local in 0..count {
                out.push(first + local as u8);
            }
            return out;
        }
        let target_row = self.floor as usize; // 0-based row *after* the current one
        if target_row >= ROWS {
            // Floor 15 is the last row. `inv:§7.2` puts the boss at floor 16 -- off the map, so it
            // is offered as the sentinel rather than as an edge. It is the **only** way forward,
            // which is what makes an act completable.
            // Not while standing on it: the boss is the end of the walk, and offering it again
            // would let a caller walk into the fight it is already in.
            if !self.boss_beaten && self.node != i32::from(crate::map::BOSS_NODE) {
                out.push(crate::map::BOSS_NODE);
            }
            return out;
        }
        let Some(row) = self.map.row(target_row - 1) else {
            return out;
        };
        let Some((row_index, local)) = self.map.locate(self.node as u8) else {
            return out;
        };
        let Some(source) = row.node(local) else {
            return out;
        };
        for &edge in source.out_targets() {
            if let Some(global) = self.map.global_of(row_index + 1, edge as usize) {
                out.push(global);
            }
        }
        out
    }

    /// Move the cursor to `target`. **Walking only**: nothing is settled here (see
    /// `docs/spec/env-abi.md` §11.5), and a target that is not reachable is an error rather than a
    /// silent stay-put.
    pub fn enter_node(&mut self, target: u8) -> Result<(), RunError> {
        if !self.reachable().contains(target) {
            return Err(RunError::NotReachable);
        }
        // **You settle a node before you walk on.** A fight is settled by `mark_resolved()` when it
        // ends (the caller does that), an event by `resolve_event`, a rest/shop/chest by their own
        // actions -- so this one check covers all of them, and it is what stops "step onto a fight,
        // then step straight onto the next node" from being a legal move.
        if self.node >= 0 && !self.node_resolved() {
            return Err(RunError::NodeNotSettled);
        }
        // Nothing is legal before the pre-run blessing is chosen (`inv:§7.1`).
        if self.pending == Pending::Start {
            return Err(RunError::WrongPhase);
        }
        if target == crate::map::BOSS_NODE {
            // `inv:§7.2`: the boss is floor 16, one row past the map's last.
            self.node = i32::from(target);
            self.floor = ROWS as i32 + 1;
            return self.check_invariants();
        }
        let Some((row, _)) = self.map.locate(target) else {
            return Err(RunError::BadNode);
        };
        self.node = i32::from(target);
        self.floor = row as i32 + 1;
        self.check_invariants()
    }

    // ---- settling a node -------------------------------------------------------------------

    /// Which act this run is on (1-based).
    #[must_use]
    pub const fn act(&self) -> u8 {
        self.act
    }

    /// Has the **last** act been cleared (the run is won)?
    #[must_use]
    pub const fn boss_beaten(&self) -> bool {
        self.boss_beaten
    }

    /// Record the act clear. Called by the fight epilogue when the boss falls -- the fight is
    /// settled outside this crate, so the caller has to say so (same shape as `mark_resolved`).
    pub fn mark_boss_beaten(&mut self) {
        self.mark_resolved();
        if self.act >= MAX_ACT {
            // The last act's boss: the run is won.
            self.boss_beaten = true;
            return;
        }
        // **Advance to the next act**: the walk starts over from the first row, with the hero's
        // health, deck and relics carried across (the fight already folded the health back).
        self.act += 1;
        self.node = -1;
        self.floor = 0;
        self.pending = Pending::None;
        self.resolved = [0; 2];
        self.boss_beaten = false;

        // **A new act gets a new map** (`port-plan.md` §131). The seed is derived from the run seed
        // and the act number, so the map is deterministic for a given run -- the same discipline the
        // opening map follows (`RunMap::generate` on the run's own RNG).
        //
        // ⚠️ A map that failed to generate here would be catastrophic (the run would have no walk),
        // so the old map is kept on failure and `map_generation_failed` is raised -- the caller sees
        // it instead of walking a stale map by accident.
        let previous = self.map;
        let seed = self.act_seed();
        let mut rng = RunRng::new(seed);
        match RunMap::generate(&mut rng) {
            Ok(map) => {
                self.map = map;
                self.map_generation_failed = false;
            }
            Err(_) => {
                self.map = previous;
                self.map_generation_failed = true;
            }
        }
    }

    /// The map seed for the **current** act: the run seed folded with the act number.
    ///
    /// Act 1 keeps the original seed (so a run's first map is exactly what it always was); later acts
    /// get their own, and the fold is a fixed constant so the whole thing stays reproducible.
    #[must_use]
    pub const fn act_seed(&self) -> i32 {
        // ct - 1, so act 1 is **exactly** the opening seed and act 2 is the first fold.
        self.seed
            .wrapping_add(((self.act - 1) as i32).wrapping_mul(0x9E37_79B9u32 as i32))
    }

    /// Did the act-change map generation fail? (It cannot today -- `RunMap::generate` retries and the
    /// generator is total -- but a silent fallback would be exactly the kind of "quietly wrong" this
    /// project keeps banning, so the flag exists and the UI can say so.)
    #[must_use]
    pub const fn map_generation_failed(&self) -> bool {
        self.map_generation_failed
    }

    /// Has the node under the cursor already paid out?
    #[must_use]
    pub fn node_resolved(&self) -> bool {
        let node = self.node;
        if node < 0 {
            return false;
        }
        let bit = node as usize;
        self.resolved[bit / 64] & (1u64 << (bit % 64)) != 0
    }

    /// Mark the node under the cursor as settled. Called by every action that finishes one **and**
    /// by the fight's epilogue (`rd_run_fight_end`), because a fight is settled outside this crate.
    pub fn mark_resolved(&mut self) {
        let node = self.node;
        if node < 0 {
            return;
        }
        let bit = node as usize;
        if bit < 128 {
            self.resolved[bit / 64] |= 1u64 << (bit % 64);
        }
    }

    /// What the node under the cursor is waiting for.
    #[must_use]
    pub const fn pending(&self) -> Pending {
        self.pending
    }

    /// The merchant's stock (empty unless [`Pending::Shop`]).
    #[must_use]
    pub const fn shop(&self) -> &ShopStock {
        &self.shop
    }

    /// What a rest would restore: 30% of maximum HP, rounded down (`inv:§8.1`).
    #[must_use]
    pub const fn rest_heal(&self) -> i32 {
        self.health_max * REST_HEAL_PERCENT / 100
    }

    /// What removing a card costs right now: 75, then +25 per removal already made this run
    /// (`inv:§8.2` -- "此后每次使用时 +25，跨店累计").
    #[must_use]
    pub const fn remove_card_price(&self) -> i32 {
        SHOP_REMOVE_BASE + SHOP_REMOVE_STEP * self.removed_cards
    }

    /// Declare what the node under the cursor needs. `card_pool` / `relic_pool` are the content's
    /// candidate ids -- this crate reads no content, so the caller supplies them.
    ///
    /// Returns the node's kind so a caller can branch without re-reading the map.
    pub fn begin_node(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[&str],
    ) -> Result<crate::map::NodeKind, RunError> {
        if self.node < 0 {
            return Err(RunError::WrongPhase);
        }
        if self.node_resolved() {
            return Err(RunError::NodeResolved);
        }
        if self.node == i32::from(crate::map::BOSS_NODE) {
            // A fight like the others; the caller knows it must use the boss pool.
            self.pending = Pending::None;
            return Ok(crate::map::NodeKind::Boss);
        }
        let Some((row, local)) = self.map.locate(self.node as u8) else {
            return Err(RunError::BadNode);
        };
        let Some(kind) = self
            .map
            .row(row)
            .and_then(|line| line.node(local))
            .map(|node| node.kind)
        else {
            return Err(RunError::BadNode);
        };
        use crate::map::NodeKind;
        self.pending = match kind {
            // A fight is the caller's business: it runs the combat session and calls
            // `end_of_combat` when it is done. Nothing to settle here.
            NodeKind::Combat => Pending::None,
            NodeKind::Rest => Pending::Rest,
            NodeKind::Treasure => Pending::Chest,
            NodeKind::Shop => {
                self.stock_shop(card_pool, relic_pool)?;
                Pending::Shop
            }
            // An elite is a fight like any other: what differs is the pool it draws from and what
            // it pays (`inv:§5.3`), and both live in the caller -- nothing to settle here.
            NodeKind::Elite => Pending::None,
            // A `?` room is an **event** (`inv:§7.3`). The run layer reads no content, so the caller
            // picks which event (`EV`) and then calls `begin_event` -- nothing to settle here.
            NodeKind::Unknown => Pending::None,
            // Nothing is left that M1 refuses; the arm stays so a new kind cannot be silently
            // accepted.
            other => return Err(RunError::NodeNotSettleable(other as u8)),
        };
        Ok(kind)
    }

    /// Rest at a rest site: heal 30% of maximum HP and leave.
    ///
    /// Returns the health actually restored (a run at 79/80 gains 1, not 24).
    pub fn rest(&mut self) -> Result<i32, RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        let before = self.health;
        self.heal_after_combat(self.rest_heal());
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(self.health - before)
    }

    /// Smith at a rest site: replace a deck card with its upgraded row.
    ///
    /// `upgraded_id` comes from the caller: in this content an upgrade is **another CARD row**
    /// (`sts-act1-plan.md` §6.5-2), and which row is the caller's mapping (`strike` → `strike+`).
    /// This crate owns no content, so it does not guess a `+` suffix.
    pub fn smith(&mut self, card: usize, upgraded_id: &str) -> Result<(), RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if card >= self.deck_len as usize {
            return Err(RunError::BadCard(card as u8));
        }
        let id = RunId::new(upgraded_id).map_err(|_| RunError::BadId)?;
        // Already upgraded? Then the "upgrade" is a no-op the caller should not have asked for.
        if self.deck[card] == id {
            return Err(RunError::BadCard(card as u8));
        }
        self.deck[card] = id;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// Open the chest under the cursor.
    ///
    /// Chest type and gold follow `inv:§8.3` exactly (50/33/17 by type; a per-type chance of gold;
    /// the ranges 23–27 / 45–55 / 68–82). The relic is drawn from the caller's pool.
    pub fn open_chest(&mut self, relic_pool: &[&str]) -> Result<ChestOutcome, RunError> {
        if self.pending != Pending::Chest {
            return Err(RunError::WrongPhase);
        }
        let roll = self.rng.roll(RunStream::Chest, 100)?;
        let (chest, gold_chance, low, high) = match roll {
            0..=49 => (0u8, 50u32, 23, 27),   // 50%
            50..=82 => (1, 35, 45, 55),       // 33%
            _ => (2, 50, 68, 82),             // 17%
        };
        let mut gold = 0;
        if self.rng.roll(RunStream::Chest, 100)? < gold_chance {
            let span = (high - low + 1) as u32;
            gold = low + self.rng.roll(RunStream::Chest, span)? as i32;
        }
        self.adjust_gold(gold);
        // A chest always holds a relic in `inv:§8.3`; an empty pool is a content problem, not "an
        // empty chest".
        let relic = if relic_pool.is_empty() {
            None
        } else {
            let index = self.rng.roll(RunStream::Chest, relic_pool.len() as u32)? as usize;
            let id = RunId::new(relic_pool[index]).map_err(|_| RunError::BadId)?;
            self.push_relic(relic_pool[index])?;
            Some(id)
        };
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(ChestOutcome { chest, gold, relic })
    }

    /// Fill the merchant's shelves. Prices are `[推断]`: the content carries no rarity, so every
    /// card is priced in the Common band and every relic likewise (`inv:§8.2`'s ranges are by
    /// rarity, and this content does not have one to look at).
    fn stock_shop(&mut self, card_pool: &[PoolCard<'_>], relic_pool: &[&str]) -> Result<(), RunError> {
        if card_pool.is_empty() {
            return Err(RunError::EmptyPool("cards"));
        }
        self.shop = ShopStock::empty();
        let mut order = [0u8; MAX_POOL];
        let n = card_pool.len().min(MAX_POOL);
        for (index, slot) in order.iter_mut().take(n).enumerate() {
            *slot = index as u8;
        }
        self.rng.shuffle(RunStream::Shop, &mut order[..n]);
        let cards = MAX_SHOP_CARDS.min(n);
        for slot in 0..cards {
            let card = card_pool[order[slot] as usize];
            // `inv:§8.2`: the band follows the card's rarity.
            let (low, high) = card_price_band(card.rarity);
            let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
            self.shop.cards[slot] = Offer {
                id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
                price,
            };
        }
        self.shop.cards_len = cards as u8;

        let relics = MAX_SHOP_RELICS.min(relic_pool.len());
        for (slot, source) in relic_pool.iter().take(relics).enumerate() {
            // Common 143–157.
            let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;
            self.shop.relics[slot] = Offer {
                id: RunId::new(source).map_err(|_| RunError::BadId)?,
                price,
            };
        }
        self.shop.relics_len = relics as u8;
        Ok(())
    }

    /// Buy the card in `slot`. The id stays readable through [`RunState::shop`].
    pub fn buy_card(&mut self, slot: usize) -> Result<(), RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        let offer = *self
            .shop
            .cards()
            .get(slot)
            .ok_or(RunError::EmptyOffer(slot as u8))?;
        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        self.adjust_gold(-offer.price);
        self.push_card(offer.id.as_str())?;
        self.shop.cards[slot].price = -1;
        Ok(())
    }

    /// Buy the relic in `slot`.
    pub fn buy_relic(&mut self, slot: usize) -> Result<(), RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        let offer = *self
            .shop
            .relics()
            .get(slot)
            .ok_or(RunError::EmptyOffer(slot as u8))?;
        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        self.adjust_gold(-offer.price);
        self.push_relic(offer.id.as_str())?;
        self.shop.relics[slot].price = -1;
        Ok(())
    }

    /// Pay to remove a card from the deck. Returns the price paid.
    pub fn remove_card(&mut self, card: usize) -> Result<i32, RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        if card >= self.deck_len as usize {
            return Err(RunError::BadCard(card as u8));
        }
        let price = self.remove_card_price();
        if self.gold < price {
            return Err(RunError::NotEnoughGold {
                price,
                gold: self.gold,
            });
        }
        self.adjust_gold(-price);
        // Shift the tail down; deck order is observable, so the order of the survivors is kept.
        for index in card..(self.deck_len as usize - 1) {
            self.deck[index] = self.deck[index + 1];
        }
        self.deck_len -= 1;
        self.removed_cards += 1;
        Ok(price)
    }

    /// Roll the pre-run pair and enter [`Pending::Start`].
    ///
    /// Called by the driver right after the run is created: **no move is legal until the blessing is
    /// chosen**, which is the same rule as `NodeNotSettled` one level up.
    pub fn offer_start_choice(&mut self) -> Result<(), RunError> {
        // **Only blessings that are choices.** Two rules, both from reading the panel:
        //   1. no `heal` while the hero is at full health (it would change nothing);
        //   2. at least one of the two offers must be free -- otherwise the opening move of the game
        //      is "lose HP", which is not a choice either.
        let mut pool = [0u8; START_OFFERS.len()];
        let mut pool_len = 0usize;
        for (index, offer) in START_OFFERS.iter().enumerate() {
            if self.blessing_is_meaningful(offer) {
                pool[pool_len] = index as u8;
                pool_len += 1;
            }
        }
        if pool_len < 2 {
            // The rule, not the content, would be wrong here; fail loudly rather than offer one.
            return Err(RunError::Invariant("fewer than two meaningful blessings"));
        }

        let first_slot = self.rng.roll(RunStream::Event, pool_len as u32)? as usize;
        let mut second_slot = self.rng.roll(RunStream::Event, pool_len as u32 - 1)? as usize;
        if second_slot >= first_slot {
            second_slot += 1;
        }
        let mut pair = [pool[first_slot], pool[second_slot]];

        // Rule 2: force one free offer in when the roll produced none.
        let is_free = |slot: u8| matches!(START_OFFERS[slot as usize].cost, EventEffect::Nothing);
        if !is_free(pair[0]) && !is_free(pair[1]) {
            for candidate in 0..pool_len {
                if is_free(pool[candidate]) {
                    pair[1] = pool[candidate];
                    break;
                }
            }
            if !is_free(pair[1]) {
                return Err(RunError::Invariant("no free blessing exists"));
            }
        }

        self.start_offers = pair;
        self.pending = Pending::Start;
        Ok(())
    }

    /// Would this blessing change anything **right now**? Today: healing a hero who is already at
    /// full health changes nothing. The list is deliberately short -- it grows only when a blessing
    /// is shown to be a non-choice.
    #[must_use]
    fn blessing_is_meaningful(&self, offer: &StartOffer) -> bool {
        let gain_does_something = match offer.gain {
            // Healing a hero already at full health changes nothing.
            EventEffect::Heal(_) => self.health < self.health_max,
            _ => true,
        };
        // A deck blessing on an empty deck has nothing to act on.
        let deck_does_something = match offer.follow_up {
            BlessingFollowUp::RemoveCard
            | BlessingFollowUp::UpgradeCard
            | BlessingFollowUp::TransformCard => self.deck_len > 0,
            BlessingFollowUp::None | BlessingFollowUp::GainThreeCards => true,
        };
        gain_does_something && deck_does_something
    }

    /// The two rolled blessings, or `None` when no choice is pending.
    #[must_use]
    pub fn start_offers(&self) -> Option<[StartOffer; 2]> {
        if self.pending != Pending::Start {
            return None;
        }
        Some([
            START_OFFERS[self.start_offers[0] as usize],
            START_OFFERS[self.start_offers[1] as usize],
        ])
    }

    /// Take blessing `slot` (`0` or `1`): its gain, then its cost.
    pub fn choose_start(
        &mut self,
        slot: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::Start {
            return Err(RunError::WrongPhase);
        }
        let Some(offers) = self.start_offers() else {
            return Err(RunError::WrongPhase);
        };
        let Some(offer) = offers.get(slot) else {
            return Err(RunError::NoSuchOffer);
        };
        // `three_cards` is finished right here: it needs the pool, not a pick.
        if matches!(offer.follow_up, BlessingFollowUp::GainThreeCards) {
            self.grant_random_cards(3, pool)?;
            self.blessing_follow = None;
            self.pending = Pending::None;
            return Ok(());
        }
        self.apply_event_effect(offer.gain)?;
        self.apply_event_effect(offer.cost)?;
        // A blessing that names a card is not finished until the card is named.
        self.blessing_follow = match offer.follow_up {
            BlessingFollowUp::None => None,
            other => Some(other),
        };
        self.pending = if self.blessing_follow.is_some() {
            Pending::BlessingCard
        } else {
            Pending::None
        };
        Ok(())
    }

    /// What the pending blessing still needs, for a picker.
    #[must_use]
    pub const fn blessing_follow_up(&self) -> Option<BlessingFollowUp> {
        self.blessing_follow
    }

    /// Splice deck entry `index` out. **Not** `remove_card`: that action belongs to the shop and
    /// refuses outside it; this is the same list move it performs.
    fn remove_at(&mut self, index: usize) {
        let last = self.deck_len as usize - 1;
        for slot in index..last {
            self.deck[slot] = self.deck[slot + 1];
        }
        self.deck[last] = RunId::EMPTY;
        self.deck_len -= 1;
    }

    /// Add `count` random non-Status/Curse cards from the pool, on the run's own stream.
    fn grant_random_cards(&mut self, count: usize, pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        let mut eligible = [0usize; MAX_POOL];
        let mut eligible_len = 0usize;
        for index in 0..pool.len().min(MAX_POOL) {
            if !matches!(pool[index].rarity, Rarity::Status | Rarity::Curse) {
                eligible[eligible_len] = index;
                eligible_len += 1;
            }
        }
        if eligible_len == 0 {
            return Err(RunError::PoolTooSmall { pool: 0, need: 1 });
        }
        for _ in 0..count {
            let picked = self.rng.roll(RunStream::Event, eligible_len as u32)? as usize;
            let id = pool[eligible[picked]].id;
            self.push_card(id)?;
        }
        Ok(())
    }

    /// Finish a blessing that named a card: remove or upgrade deck entry `index`.
    pub fn pick_blessing_card(
        &mut self,
        index: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::BlessingCard {
            return Err(RunError::WrongPhase);
        }
        let Some(follow_up) = self.blessing_follow else {
            return Err(RunError::WrongPhase);
        };
        if index >= self.deck_len as usize {
            return Err(RunError::BadNode);
        }
        match follow_up {
            BlessingFollowUp::RemoveCard => {
                self.remove_at(index);
            }
            BlessingFollowUp::UpgradeCard => {
                // Already upgraded is not an error: the blessing simply has nothing to do.
                if !self.deck[index].as_str().ends_with('+') {
                    let mut buffer = [0u8; 64];
                    let mut len = 0usize;
                    for byte in self.deck[index].as_str().as_bytes() {
                        if len < buffer.len() - 1 {
                            buffer[len] = *byte;
                            len += 1;
                        }
                    }
                    buffer[len] = b'+';
                    len += 1;
                    let upgraded =
                        core::str::from_utf8(&buffer[..len]).map_err(|_| RunError::BadId)?;
                    self.deck[index] = RunId::new(upgraded).map_err(|_| RunError::BadId)?;
                }
            }
            BlessingFollowUp::TransformCard => {
                self.remove_at(index);
                self.grant_random_cards(1, pool)?;
            }
            BlessingFollowUp::None | BlessingFollowUp::GainThreeCards => {
                return Err(RunError::WrongPhase);
            }
        }
        self.blessing_follow = None;
        self.pending = Pending::None;
        Ok(())
    }

    /// Open event `id` in the `?` room under the cursor.
    pub fn begin_event(&mut self, id: &str) -> Result<(), RunError> {
        if self.node_resolved() {
            return Err(RunError::NodeResolved);
        }
        let id = RunId::new(id).map_err(|_| RunError::NoSuchEvent)?;
        self.event = id;
        self.pending = Pending::Event;
        Ok(())
    }

    /// The event under the cursor (empty until [`RunState::begin_event`]).
    #[must_use]
    pub fn event(&self) -> &str {
        self.event.as_str()
    }

    /// Take one choice of the open event.
    ///
    /// `effect` is what the **content** declared for that choice; the run layer applies it and
    /// refuses anything it does not know. Every choice is answerable, including "nothing".
    pub fn resolve_event(&mut self, effect: EventEffect) -> Result<(), RunError> {
        if self.pending != Pending::Event {
            return Err(RunError::WrongPhase);
        }
        self.apply_event_effect(effect)?;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// One closed-vocabulary effect. Shared by `?` rooms and by the pre-run blessing, so the two
    /// cannot drift.
    fn apply_event_effect(&mut self, effect: EventEffect) -> Result<(), RunError> {
        match effect {
            EventEffect::Heal(n) => self.heal_after_combat(n),
            EventEffect::Gold(n) => self.adjust_gold(n),
            EventEffect::LoseHealth(n) => self.adjust_health(-n),
            EventEffect::GainMaxHealth(n) => {
                self.health_max += n;
                self.adjust_health(n);
            }
            EventEffect::Nothing => {}
        }
        Ok(())
    }

    /// What a won fight is offering.
    #[must_use]
    pub const fn reward(&self) -> &Reward {
        &self.reward
    }

    /// Roll the reward for a won fight: gold now (`inv:§5`: 10–20 for a normal fight), then three
    /// **distinct** cards from `card_pool` (`inv:§3.5`).
    ///
    /// Gold is granted here rather than on "take" because `inv:§5` gives it on victory -- there is
    /// no way to decline it, so a `take_gold` action would be a button that is always pressed.
    pub fn roll_reward(
        &mut self,
        card_pool: &[PoolCard<'_>],
        potion_pool: &[&str],
        kind: FightKind,
    ) -> Result<(), RunError> {
        // Status and curse cards are never a reward (`inv:§3.5`; `slimed` is a Status).
        let mut eligible = [0usize; MAX_POOL];
        let mut eligible_len = 0usize;
        for index in 0..card_pool.len().min(MAX_POOL) {
            if !matches!(card_pool[index].rarity, Rarity::Status | Rarity::Curse) {
                eligible[eligible_len] = index;
                eligible_len += 1;
            }
        }
        if eligible_len < MAX_REWARD_CARDS {
            return Err(RunError::PoolTooSmall {
                pool: eligible_len,
                need: MAX_REWARD_CARDS,
            });
        }
        let eligible = &eligible[..eligible_len];
        let (low, high) = kind.gold();
        let span = (high - low + 1).max(1) as u32;
        let paid = low + self.rng.roll(RunStream::Reward, span)? as i32;
        self.adjust_gold(paid);

        // `inv:§9.3`: a potion drops from 40% of fights, on the `Potion` stream.
        let drop = self.rng.roll(RunStream::Potion, 100)? < POTION_DROP_PERCENT;

        let mut used = [false; MAX_POOL];
        let mut cards = [RunId::EMPTY; MAX_REWARD_CARDS];
        for slot in 0..MAX_REWARD_CARDS {
            // One roll, banded -- see `reward_bands`.
            let (rare_top, uncommon_top) = reward_bands(kind, self.rarity_offset);
            let roll = self.rng.roll(RunStream::Reward, 100)? as i32;
            let band = if roll < rare_top {
                Rarity::Rare
            } else if roll < uncommon_top {
                Rarity::Uncommon
            } else {
                Rarity::Common
            };
            // A band with no cards falls through: first to `Basic` (this image's only populated
            // bucket), then to anything left. It is a *documented* deviation -- StS would never
            // offer a Basic card -- and it disappears the moment the content has Common+ cards.
            let mut picked = self.pick_of(card_pool, eligible, &used, Some(band))?;
            if picked.is_none() {
                picked = self.pick_of(card_pool, eligible, &used, Some(Rarity::Basic))?;
            }
            if picked.is_none() {
                picked = self.pick_of(card_pool, eligible, &used, None)?;
            }
            let Some(index) = picked else {
                return Err(RunError::PoolTooSmall {
                    pool: eligible_len,
                    need: MAX_REWARD_CARDS,
                });
            };
            used[index] = true;
            cards[slot] = RunId::new(card_pool[index].id).map_err(|_| RunError::BadId)?;
            // `inv:§3.5`: the pity offset moves after **every** roll -- reset on a rare, +1%
            // otherwise (the wiki says "otherwise", not "on a common": an uncommon also ticks it).
            if band == Rarity::Rare {
                self.rarity_offset = RARITY_OFFSET_START;
            } else {
                self.rarity_offset = (self.rarity_offset + 1).min(RARITY_OFFSET_CAP);
            }
        }
        // Which potion: the content's own list, picked on the same stream. `potion_pool` is empty
        // when the image declares none (roguedeck), and then no potion is offered at all.
        let potion = if drop && !potion_pool.is_empty() {
            let index = self.rng.roll(RunStream::Potion, potion_pool.len() as u32)? as usize;
            RunId::new(potion_pool[index]).map_err(|_| RunError::BadId)?
        } else {
            RunId::EMPTY
        };
        self.reward = Reward {
            gold: paid,
            cards,
            cards_len: MAX_REWARD_CARDS as u8,
            potion,
        };
        self.pending = Pending::Reward;
        Ok(())
    }

    /// The potion this fight dropped, or `None`.
    #[must_use]
    pub fn reward_potion(&self) -> Option<&str> {
        let id = self.reward.potion.as_str();
        if id.is_empty() {
            None
        } else {
            Some(id)
        }
    }

    /// Take the potion off the reward table. A **full belt is an error**, not a silent discard:
    /// dropping what the player was just offered without telling them is the kind of quiet loss
    /// this project keeps banning.
    pub fn take_potion(&mut self) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let id = self.reward.potion;
        if id.as_str().is_empty() {
            return Err(RunError::NoSuchPotion);
        }
        self.push_potion(id.as_str())?;
        self.reward.potion = RunId::EMPTY;
        Ok(())
    }

    /// The current pity offset (`inv:§3.5`). Exposed because a UI may want to show it, and because a
    /// test that only checks the odds cannot see a counter that never moves.
    #[must_use]
    pub const fn rarity_offset(&self) -> i32 {
        self.rarity_offset
    }

    /// A uniformly chosen **unused** card of `wanted`, or `None` when that bucket has none left.
    fn pick_of(
        &mut self,
        pool: &[PoolCard<'_>],
        eligible: &[usize],
        used: &[bool; MAX_POOL],
        wanted: Option<Rarity>,
    ) -> Result<Option<usize>, RunError> {
        let mut count = 0u32;
        for index in eligible {
            if used[*index] {
                continue;
            }
            let rarity = pool[*index].rarity;
            let ok = match wanted {
                Some(rarity_wanted) => rarity == rarity_wanted,
                None => true,
            };
            if ok {
                count += 1;
            }
        }
        if count == 0 {
            return Ok(None);
        }
        let mut target = self.rng.roll(RunStream::Reward, count)? as u32;
        for index in eligible {
            if used[*index] {
                continue;
            }
            let rarity = pool[*index].rarity;
            let ok = match wanted {
                Some(rarity_wanted) => rarity == rarity_wanted,
                None => true,
            };
            if !ok {
                continue;
            }
            if target == 0 {
                return Ok(Some(*index));
            }
            target -= 1;
        }
        Ok(None)
    }

    /// Take card `slot` from the reward screen and leave it.
    pub fn take_card(&mut self, slot: usize) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let Some(id) = self.reward.cards().get(slot).copied() else {
            return Err(RunError::EmptyOffer(slot as u8));
        };
        if id == RunId::EMPTY {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        self.push_card(id.as_str())?;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// Decline the card (gold is already in hand; `inv:§3.5` says a reward can be skipped).
    pub fn skip_reward(&mut self) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// Walk away from whatever is pending.
    pub fn leave(&mut self) -> Result<(), RunError> {
        if self.pending == Pending::None {
            return Err(RunError::WrongPhase);
        }
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// The per-step invariants from `run-layer.md` §6.2. A **real** check: the release build is what
    /// runs on the device, and a `debug_assert!` would leave the device unchecked.
    pub fn check_invariants(&self) -> Result<(), RunError> {
        self.map.check().map_err(|_| RunError::MapGeneration)?;
        // The boss lives at floor `ROWS + 1` (`inv:§7.2`: floor 16), off the map -- so the ceiling is
        // one higher when the cursor is on it.
        let at_boss = self.node == i32::from(crate::map::BOSS_NODE);
        let top_floor = if at_boss { ROWS as i32 + 1 } else { ROWS as i32 };
        if self.floor < 0 || self.floor > top_floor {
            return Err(RunError::Invariant("floor out of range"));
        }
        if self.health < 0 || self.health > self.health_max {
            return Err(RunError::Invariant("health outside 0..=max"));
        }
        if self.deck_len as usize > MAX_RUN_DECK
            || self.relics_len as usize > MAX_RUN_RELICS
            || self.potions_len as usize > MAX_RUN_POTIONS
        {
            return Err(RunError::Invariant("a container is over capacity"));
        }
        if self.node < 0 {
            if self.floor != 0 {
                return Err(RunError::Invariant("floor set before the first step"));
            }
        } else if at_boss {
            // The sentinel has no map row; its floor is fixed.
            if self.floor != ROWS as i32 + 1 {
                return Err(RunError::Invariant("the boss is floor ROWS + 1"));
            }
        } else {
            let Some((row, _)) = self.map.locate(self.node as u8) else {
                return Err(RunError::BadNode);
            };
            if row as i32 + 1 != self.floor {
                return Err(RunError::Invariant("floor does not match the node's row"));
            }
        }
        Ok(())
    }
}

/// The tripwire. Prints the measured size and its headroom so the number in a memory table never
/// has to be transcribed by hand (discipline: one source, and it points rather than copies).
#[must_use]
pub fn state_fits_the_tripwire() -> (usize, usize) {
    let bytes = RunState::size_bytes();
    assert!(
        bytes <= RUN_STATE_TRIPWIRE_BYTES,
        "RunState is {bytes} B, over the {RUN_STATE_TRIPWIRE_BYTES} B tripwire. \
         Raise the tripwire **in both places** and say in the commit what the extra bytes buy \
         -- and if the growth is a capacity, check first whether enlarging it changes behaviour, \
         because then it is semantics and not a budget (port-plan.md §45.4)."
    );
    (bytes, RUN_STATE_TRIPWIRE_BYTES - bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::map::NodeKind;

    fn ironclad() -> RunState {
        let deck = [
            "strike", "strike", "strike", "strike", "strike",
            "defend", "defend", "defend", "defend",
            "bash",
        ];
        RunState::new(7, 80, 99, &deck).expect("a run must start")
    }

    #[test]
    fn a_new_run_is_before_the_map_with_a_known_start() {
        let run = ironclad();
        assert_eq!(run.floor(), 0, "floor is 0 before the first step");
        assert_eq!(run.node(), -1, "the cursor starts off the map");
        assert_eq!(run.health(), 80);
        assert_eq!(run.health_max(), 80);
        assert_eq!(run.gold(), 99);
        assert_eq!(run.deck().len(), 10);
        // `inv:§2.1`: 5 strike + 4 defend + 1 bash, **in that order** (deck order is observable).
        let names: Vec<&str> = run.deck().iter().map(RunId::as_str).collect();
        assert_eq!(names[0], "strike");
        assert_eq!(names[9], "bash");
        assert_eq!(run.check_invariants(), Ok(()));
    }

    /// The first step is a **free choice among floor 1**, not a single entry point (`inv:§7.2`).
    #[test]
    fn the_first_step_may_enter_any_floor_one_node_and_nothing_else() {
        let run = ironclad();
        let reachable = run.reachable();
        let floor_one = run.map().row(0).unwrap().len();
        assert_eq!(reachable.len(), floor_one);
        assert!(reachable.len() >= 2, "floor 1 must offer a choice");
        for index in 0..reachable.len() {
            let node = reachable.get(index).unwrap();
            assert_eq!(run.map().locate(node).unwrap().0, 0);
        }
        // A floor-2 node is not reachable yet.
        if let Some(first_row_two) = run.map().row_first(1) {
            assert!(!reachable.contains(first_row_two));
        }
    }

    #[test]
    fn walking_follows_edges_and_never_teleports() {
        let mut run = ironclad();
        let start = run.reachable().get(0).unwrap();
        run.enter_node(start).unwrap();
        assert_eq!(run.floor(), 1);
        assert_eq!(run.node(), i32::from(start));
        assert_eq!(run.check_invariants(), Ok(()));

        // One legal step per floor, all the way down, always taking the first option.
        let mut steps = 1;
        while run.floor() < ROWS as i32 {
            let reachable = run.reachable();
            assert!(!reachable.is_empty(), "floor {} has no exit", run.floor());
            let next = reachable.get(0).unwrap();
            // **You settle before you walk on**, so this test settles the way a finished fight does.
            // (`the_cheat_of_skipping_a_node` below is what pins the rule itself.)
            run.mark_resolved();
            run.enter_node(next).unwrap();
            steps += 1;
            assert_eq!(run.floor() as usize, steps);
            assert_eq!(run.check_invariants(), Ok(()));
        }
        assert_eq!(run.floor(), ROWS as i32);
        // The last row leads to the boss (inv:§7.2: floor 16, off the map) and to nothing else.
        let tail = run.reachable();
        assert_eq!(tail.len(), 1, "the last row has exactly one exit");
        assert_eq!(tail.get(0), Some(crate::map::BOSS_NODE), "and it is the boss");
    }

    #[test]
    fn entering_a_node_that_is_not_an_edge_is_an_error_and_changes_nothing() {
        let mut run = ironclad();
        let mut ids: Vec<u8> = Vec::new();
        for row in 0..ROWS {
            if let Some(first) = run.map().row_first(row) {
                for local in 0..run.map().row(row).unwrap().len() {
                    ids.push(first + local as u8);
                }
            }
        }
        let before = run;
        // A node on floor 7 is not an edge out of "before the map".
        let far = ids.iter().copied().find(|id| run.map().locate(*id).unwrap().0 == 6).unwrap();
        assert_eq!(run.enter_node(far), Err(RunError::NotReachable));
        assert_eq!(run, before, "a rejected step must leave the run byte-identical");

        // And from a real node, a sibling that is not one of its targets is refused too.
        let start = run.reachable().get(0).unwrap();
        run.enter_node(start).unwrap();
        let snapshot = run;
        let sibling = (0..run.map().row(1).unwrap().len() as u8)
            .map(|local| run.map().global_of(1, local as usize).unwrap())
            .find(|id| !run.reachable().contains(*id))
            .expect("floor 2 has at least one node that is not an edge");
        assert_eq!(run.enter_node(sibling), Err(RunError::NotReachable));
        assert_eq!(run, snapshot);
    }

    #[test]
    fn capacity_is_an_error_not_a_truncation() {
        let mut run = ironclad();
        let mut pushed = 10;
        loop {
            match run.push_card("strike") {
                Ok(()) => pushed += 1,
                Err(e) => {
                    assert_eq!(e, RunError::Capacity);
                    break;
                }
            }
            assert!(pushed <= MAX_RUN_DECK, "the push must stop at the capacity");
        }
        assert_eq!(pushed, MAX_RUN_DECK, "a full deck must be reachable exactly");
        assert_eq!(run.deck().len(), MAX_RUN_DECK);
        // The same for relics, whose bound is smaller than the content pool.
        for _ in 0..MAX_RUN_RELICS {
            run.push_relic("burning_blood").unwrap();
        }
        assert_eq!(run.push_relic("burning_blood"), Err(RunError::Capacity));
        // Potions: the belt is three slots (`inv:§9.3`).
        for _ in 0..MAX_RUN_POTIONS {
            run.push_potion("fire_potion").unwrap();
        }
        assert_eq!(run.push_potion("fire_potion"), Err(RunError::Capacity));
        // An id longer than the id capacity is refused, not silently shortened.
        assert_eq!(run.push_card(&"x".repeat(ID_CAP + 1)), Err(RunError::BadId));
        assert_eq!(run.deck().len(), MAX_RUN_DECK);
    }

    #[test]
    fn health_and_gold_are_clamped_and_the_blood_heal_never_overheals() {
        let mut run = ironclad();
        run.adjust_health(-30);
        assert_eq!(run.health(), 50);
        run.heal_after_combat(6);
        assert_eq!(run.health(), 56);
        // At full health the heal does nothing rather than overflowing.
        run.adjust_health(1000);
        assert_eq!(run.health(), 80);
        run.heal_after_combat(6);
        assert_eq!(run.health(), 80);
        // Zero is the floor: a run at 0 is over, not negative.
        run.adjust_health(-1000);
        assert_eq!(run.health(), 0);
        run.adjust_gold(-1000);
        assert_eq!(run.gold(), 0);
        run.adjust_gold(25);
        assert_eq!(run.gold(), 25);
    }

    /// `Burning Blood` heals 6 at the end of a fight, capped at the maximum, and reports what it
    /// actually restored. The cap matters: a run at 78/80 gains 2, and a caller that prints "+6"
    /// there would be lying.
    #[test]
    fn burning_blood_heals_six_at_the_end_of_a_fight() {
        let mut run = ironclad();
        run.push_relic("burning_blood").unwrap();
        run.adjust_health(-20);
        assert_eq!(run.health(), 60);
        assert_eq!(run.end_of_combat(), Ok(6));
        assert_eq!(run.health(), 66);
        // No second heal from one call, and none when the fight did not end.
        assert_eq!(run.health(), 66);
        // At the cap it restores only what fits, and still reports the truth.
        run.adjust_health(1000);
        assert_eq!(run.health(), 80);
        run.adjust_health(-1);
        assert_eq!(run.end_of_combat(), Ok(1));
        assert_eq!(run.health(), 80);
    }

    /// A relic whose effect this kernel cannot run is an **error**, not a no-op. This is the loud
    /// boundary of the whole relic system: `REL.RunPrograms`/`CombatRules` are not executed, so an
    /// unknown id must fail rather than quietly do nothing.
    #[test]
    fn a_relic_with_no_implemented_effect_is_an_error() {
        let mut run = ironclad();
        run.push_relic("vajra").unwrap(); // a real StS relic, whose effect is not implemented
        assert_eq!(
            run.end_of_combat(),
            Err(RunError::UnsupportedRelic { index: 0 }),
            "a relic with no rule must not be silently inert"
        );
        // And a run with no relics has nothing to do, which is not an error.
        let mut bare = ironclad();
        assert_eq!(bare.end_of_combat(), Ok(0));
        assert_eq!(bare.health(), 80);
    }

    // ---- settling a node ---------------------------------------------------------------------

    /// Walk the cursor to some node of `want`, breadth-first over the map's upward edges.
    ///
    /// A test that wants to be *in* a shop has to actually walk there: `enter_node` only accepts
    /// edges, and the map's kinds are the generator's. This also proves the map is traversable to
    /// every kind a test needs.
    fn walk_to(run: &mut RunState, want: NodeKind) -> bool {
        const CAP: usize = 128;
        let n = run.map().node_count();
        assert!(n < CAP);
        let mut seen = [false; CAP];
        let mut parent = [usize::MAX; CAP];
        let mut queue = [0u8; CAP];
        let mut head = 0usize;
        let mut tail = 0usize;
        // Start where the cursor is; a fresh run has none, so start at floor 1.
        let cursor = run.node();
        if cursor >= 0 {
            seen[cursor as usize] = true;
            queue[tail] = cursor as u8;
            tail += 1;
        } else {
            for (index, is_seen) in seen.iter_mut().enumerate().take(n) {
                let (row, _) = run.map().locate(index as u8).unwrap();
                if row == 0 {
                    *is_seen = true;
                    queue[tail] = index as u8;
                    tail += 1;
                }
            }
        }
        let mut target = usize::MAX;
        while head < tail {
            let current = queue[head] as usize;
            head += 1;
            let (row, local) = run.map().locate(current as u8).unwrap();
            let node = run.map().rows()[row].nodes()[local];
            if node.kind == want {
                target = current;
                break;
            }
            for &edge in node.out_targets() {
                let next = run.map().global_of(row + 1, edge as usize).unwrap() as usize;
                if !seen[next] {
                    seen[next] = true;
                    parent[next] = current;
                    queue[tail] = next as u8;
                    tail += 1;
                }
            }
        }
        if target == usize::MAX {
            return false;
        }
        let mut path = [0u8; CAP];
        let mut len = 0usize;
        let mut at = target;
        while parent[at] != usize::MAX {
            path[len] = at as u8;
            len += 1;
            at = parent[at];
        }
        path[len] = at as u8;
        len += 1;
        // The node the cursor is on must be settled before the first hop (the new rule).
        if cursor >= 0 {
            run.mark_resolved();
        }
        for step in (0..len).rev() {
            // The last element is the seed, and the seed may be the node we are standing on --
            // entering that again is not an edge, so it is skipped.
            if cursor >= 0 && step == len - 1 {
                continue;
            }
            run.mark_resolved();
            run.enter_node(path[step]).unwrap();
        }
        true
    }

    // Seven, like the content after the three upgraded rows were added: a pool smaller than
    // MAX_SHOP_CARDS would leave the cap untested (the shop shows min(pool, 5)).
    const CARDS: [&str; 7] = [
        "strike", "defend", "bash", "slimed", "strike+", "defend+", "bash+",
    ];
    const RELICS: [&str; 1] = ["burning_blood"];
    /// The starting deck (inv:§2.1), in order.
    const DECK: [&str; 10] = [
        "strike", "strike", "strike", "strike", "strike",
        "defend", "defend", "defend", "defend",
        "bash",
    ];

    #[test]
    fn a_rest_site_heals_thirty_percent_and_then_it_is_done() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Rest), "the map has no rest site");
        assert_eq!(run.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Rest));
        assert_eq!(run.pending(), Pending::Rest);
        // 30% of 80, rounded down (`inv:§8.1`).
        assert_eq!(run.rest_heal(), 24);
        run.adjust_health(-40);
        assert_eq!(run.health(), 40);
        assert_eq!(run.rest(), Ok(24));
        assert_eq!(run.health(), 64);
        assert_eq!(run.pending(), Pending::None);
        // A second rest from the same site is an out-of-order action, not a free heal.
        assert_eq!(run.rest(), Err(RunError::WrongPhase));
        assert_eq!(run.health(), 64);
    }

    #[test]
    fn smithing_replaces_the_card_with_its_upgraded_row() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Rest));
        run.begin_node(&basic_pool(), &RELICS).unwrap();
        // The deck's first card is a `strike`; the upgrade is another CARD row, and the mapping is
        // the caller's (`sts-act1-plan.md` §6.5-2 -- this crate owns no content).
        assert_eq!(run.deck()[0].as_str(), "strike");
        run.smith(0, "strike+").unwrap();
        assert_eq!(run.deck()[0].as_str(), "strike+");
        assert_eq!(run.pending(), Pending::None);
        // Bad index, and "upgrading" to what is already there.
        run.pending = Pending::Rest;
        assert_eq!(run.smith(99, "strike+"), Err(RunError::BadCard(99)));
        assert_eq!(run.smith(0, "strike+"), Err(RunError::BadCard(0)));
        assert_eq!(run.pending(), Pending::Rest, "a refused smith must not consume the node");
    }

    #[test]
    fn a_chest_gives_gold_in_range_and_a_relic() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Treasure), "the map has no treasure room");
        let gold_before = run.gold();
        assert_eq!(run.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Treasure));
        assert_eq!(run.pending(), Pending::Chest);
        let outcome = run.open_chest(&RELICS).unwrap();
        // `inv:§8.3`: the three chest types and their gold ranges.
        let (low, high) = match outcome.chest {
            0 => (23, 27),
            1 => (45, 55),
            _ => (68, 82),
        };
        assert!(
            outcome.gold == 0 || (outcome.gold >= low && outcome.gold <= high),
            "chest {} gave {} gold, which is not in its range",
            outcome.chest,
            outcome.gold
        );
        assert_eq!(run.gold(), gold_before + outcome.gold);
        assert_eq!(
            outcome.relic.map(|id| id.as_str().to_string()),
            Some("burning_blood".to_string())
        );
        assert_eq!(run.relics().len(), 1);
        assert_eq!(run.pending(), Pending::None);
        assert_eq!(run.open_chest(&RELICS), Err(RunError::WrongPhase));
    }

    #[test]
    fn a_shop_stocks_five_cards_and_three_relics_with_prices_in_range() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Shop), "the map has no merchant");
        run.adjust_gold(500);
        assert_eq!(run.begin_node(&common_pool(), &RELICS), Ok(NodeKind::Shop));
        assert_eq!(run.pending(), Pending::Shop);
        assert_eq!(run.shop().cards().len(), MAX_SHOP_CARDS);
        assert_eq!(run.shop().relics().len(), MAX_SHOP_RELICS.min(RELICS.len()));
        for offer in run.shop().cards() {
            // All five are Commons, so they sit in the Common band (`inv:§8.2`) -- no more
            // `[推断]`: the band now comes from the card's rarity.
            let (low, high) = card_price_band(Rarity::Common);
            assert!(
                (low..=high).contains(&offer.price),
                "card {} costs {}",
                offer.id.as_str(),
                offer.price
            );
            assert!(common_pool().iter().any(|card| card.id == offer.id.as_str()));
        }
        for offer in run.shop().relics() {
            assert!((143..=157).contains(&offer.price), "relic price {}", offer.price);
        }
    }

    #[test]
    fn buying_and_removing_are_paid_for_and_never_silent() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Shop));
        run.adjust_gold(120);
        run.begin_node(&basic_pool(), &RELICS).unwrap();

        // A purchase moves gold one way and a card the other.
        // Owned, not borrowed: the next call takes `&mut run`.
        let (id, price) = {
            let offer = run.shop().cards()[0];
            (offer.id.as_str().to_string(), offer.price)
        };
        let deck_before = run.deck().len();
        let gold_before = run.gold();
        assert_eq!(run.buy_card(0), Ok(()));
        assert_eq!(run.gold(), gold_before - price);
        assert_eq!(run.deck().len(), deck_before + 1);
        assert_eq!(run.deck()[deck_before].as_str(), id);
        // The same slot twice is an empty offer, not a second card.
        assert_eq!(run.buy_card(0), Err(RunError::EmptyOffer(0)));
        assert_eq!(run.deck().len(), deck_before + 1);

        // Removal: 75 the first time (`inv:§8.2`), and the deck keeps its order.
        let gold_before = run.gold();
        let second = run.deck()[1].as_str().to_string();
        assert_eq!(run.remove_card_price(), 75);
        assert_eq!(run.remove_card(0), Ok(75));
        assert_eq!(run.gold(), gold_before - 75);
        assert_eq!(run.deck().len(), deck_before);
        assert_eq!(run.deck()[0].as_str(), second, "the survivors keep their order");
        assert_eq!(run.remove_card_price(), 100, "+25 per use, across shops");

        // And the price has to be payable: an empty purse refuses and changes nothing.
        run.adjust_gold(-9999);
        assert_eq!(run.gold(), 0);
        let deck_now: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert!(matches!(
            run.remove_card(0).unwrap_err(),
            RunError::NotEnoughGold { price: 100, gold: 0 }
        ));
        let deck_after: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(deck_now, deck_after, "a refused purchase must not change the deck");
    }

    #[test]
    fn the_nodes_m1_does_not_settle_are_loud() {
        // `Elite` and `Unknown` are named as "not in M1" (`sts-act1-plan.md` §4). Walking onto one
        // must be an error, not a silent no-op -- that is the promise `env-abi.md` §11.5 makes.
        // Elite settles as a fight since the sentries exist (inv:§4.2); only Unknown is left.
        // Every kind M1 knows settles: `Elite` since the sentries (`inv:§4.2`), `Unknown` since the events
        // (`inv:§7.3`). Nothing is refused for being the wrong *kind* any more -- what must stay loud
        // is an action in the wrong *phase*.
        let mut run = ironclad();
        if walk_to(&mut run, NodeKind::Unknown) {
            assert_eq!(
                run.begin_node(&basic_pool(), &RELICS),
                Ok(NodeKind::Unknown),
                "a `?` room settles as an event now"
            );
            assert_eq!(run.pending(), Pending::None, "the caller picks the event");
        }
                // A fight is the caller's business: no error, nothing pending.
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Combat));
        assert_eq!(run.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Combat));
        assert_eq!(run.pending(), Pending::None);
        // And every settling action refuses when nothing is pending.
        assert_eq!(run.rest(), Err(RunError::WrongPhase));
        assert_eq!(run.open_chest(&RELICS), Err(RunError::WrongPhase));
        assert_eq!(run.buy_card(0), Err(RunError::WrongPhase));
        assert_eq!(run.leave(), Err(RunError::WrongPhase));
    }

    /// `inv:§5` + `inv:§3.5`: gold in range, three cards, **all different**.
    ///
    /// Distinctness is the property worth a test: rolling three cards from a pool with a duplicate
    /// is easy to write and hard to notice -- the screen would look fine and simply offer the same
    /// card twice.
    #[test]
    fn a_reward_pays_gold_in_range_and_three_different_cards() {
        for seed in 0..25 {
            let mut run = RunState::new(seed, 80, 0, &DECK).expect("a run");
            let gold_before = run.gold();
            run.roll_reward(&basic_pool(), &[], FightKind::Normal).expect("a reward");
            let reward = run.reward();
            let (low, high) = FightKind::Normal.gold();
            assert!(
                reward.gold() >= low && reward.gold() <= high,
                "seed {seed}: {} gold is outside {low}..={high}",
                reward.gold()
            );
            assert_eq!(run.gold(), gold_before + reward.gold(), "seed {seed}");
            let cards: Vec<&str> = reward.cards().iter().map(RunId::as_str).collect();
            assert_eq!(cards.len(), MAX_REWARD_CARDS);
            let mut sorted = cards.clone();
            sorted.sort_unstable();
            sorted.dedup();
            assert_eq!(sorted.len(), cards.len(), "seed {seed}: {cards:?} has a repeat");
            for card in &cards {
                assert!(CARDS.contains(card), "seed {seed}: {card} is not in the pool");
            }
            assert_eq!(run.pending(), Pending::Reward);
        }
    }

    /// Taking a card adds exactly one and leaves the phase; skipping adds none. Both are one-shot.
    #[test]
    fn taking_and_skipping_a_reward() {
        let mut run = RunState::new(3, 80, 0, &DECK).expect("a run");
        run.roll_reward(&basic_pool(), &[], FightKind::Normal).unwrap();
        let wanted = run.reward().cards()[1].as_str().to_string();
        let deck_before = run.deck().len();
        run.take_card(1).expect("take the second card");
        assert_eq!(run.deck().len(), deck_before + 1);
        assert_eq!(run.deck()[deck_before].as_str(), wanted);
        assert_eq!(run.pending(), Pending::None);
        // A second take from the same screen is an out-of-order action.
        assert_eq!(run.take_card(0), Err(RunError::WrongPhase));

        // Skipping takes nothing.
        run.roll_reward(&basic_pool(), &[], FightKind::Normal).unwrap();
        let deck_before = run.deck().len();
        run.skip_reward().expect("skip");
        assert_eq!(run.deck().len(), deck_before);
        assert_eq!(run.pending(), Pending::None);
        assert_eq!(run.skip_reward(), Err(RunError::WrongPhase));
    }

    /// A pool too small to fill three distinct slots is an **error**, not a short or repeating
    /// screen.
    #[test]
    fn a_pool_too_small_for_three_distinct_cards_is_loud() {
        let mut run = RunState::new(3, 80, 0, &DECK).expect("a run");
        let two: [PoolCard<'_>; 2] = [
            PoolCard { id: "strike", rarity: Rarity::Basic },
            PoolCard { id: "defend", rarity: Rarity::Basic },
        ];
        assert_eq!(
            run.roll_reward(&two, &[], FightKind::Normal),
            Err(RunError::PoolTooSmall { pool: 2, need: 3 })
        );
        assert_eq!(run.pending(), Pending::None, "a refused roll leaves no phase behind");
        assert_eq!(run.gold(), 0, "and pays no gold");
    }

    /// This image's pool: three Basics plus the junk card (which must be filtered out).
    fn basic_pool() -> [PoolCard<'static>; 4] {
        [
            PoolCard { id: "strike", rarity: Rarity::Basic },
            PoolCard { id: "defend", rarity: Rarity::Basic },
            PoolCard { id: "bash", rarity: Rarity::Basic },
            PoolCard { id: "slimed", rarity: Rarity::Status },
        ]
    }

    /// Five Commons: a full shelf, all in one price band.
    fn common_pool() -> [PoolCard<'static>; 5] {
        [
            PoolCard { id: "c1", rarity: Rarity::Common },
            PoolCard { id: "c2", rarity: Rarity::Common },
            PoolCard { id: "c3", rarity: Rarity::Common },
            PoolCard { id: "c4", rarity: Rarity::Common },
            PoolCard { id: "c5", rarity: Rarity::Common },
        ]
    }

    /// A pool with all three rarities, for the band arithmetic the real content cannot exercise yet.
    fn mixed_pool() -> [PoolCard<'static>; 6] {
        [
            PoolCard { id: "c1", rarity: Rarity::Common },
            PoolCard { id: "c2", rarity: Rarity::Common },
            PoolCard { id: "u1", rarity: Rarity::Uncommon },
            PoolCard { id: "u2", rarity: Rarity::Uncommon },
            PoolCard { id: "r1", rarity: Rarity::Rare },
            PoolCard { id: "r2", rarity: Rarity::Rare },
        ]
    }

    /// The band arithmetic, pinned to the table the wiki prints (`Card Rewards`, "Actual at reset"
    /// and the "next-slot rare chance after a rare hit" rows).
    ///
    /// The subtle one is `(0, 35)` for a normal fight at a fresh reset: the rare band is
    /// `3 + (−5) = −2`, so it floors to 0 **and the 2% it lost is taken off the bottom of the
    /// uncommon band**, not handed to it. An implementation that clamps rare to 0 and keeps
    /// uncommon at 37% would pass every "roughly 3/37/60" test and be wrong.
    #[test]
    fn the_reward_bands_are_the_wikis() {
        // Normal fight: rare base 3, uncommon width 37.
        assert_eq!(reward_bands(FightKind::Normal, -5), (0, 35), "fresh reset");
        assert_eq!(reward_bands(FightKind::Normal, 0), (3, 40), "offset back to 0");
        assert_eq!(reward_bands(FightKind::Normal, 40), (43, 80), "offset capped at +40");

        // Elite: rare base 10, uncommon width 40. After a rare resets to −5 the next slot's rare
        // chance is 10 − 5 = 5%, which is the wiki's "Elite reward, second/third slot: 5%" row.
        assert_eq!(reward_bands(FightKind::Elite, -5), (5, 45));
        assert_eq!(reward_bands(FightKind::Elite, 0), (10, 50));

        // Boss: always rare, whatever the offset says.
        for offset in [-5, 0, 40] {
            assert_eq!(reward_bands(FightKind::Boss, offset), (100, 100));
        }

        // `inv:§5` gold, all three tiers.
        assert_eq!(FightKind::Normal.gold(), (10, 20));
        assert_eq!(FightKind::Elite.gold(), (25, 35));
        assert_eq!(FightKind::Boss.gold(), (95, 105));
    }

    /// The pity offset ticks **once per card rolled** -- including the ones a player skips, because
    /// the screen is generated up front -- and a rare resets it.
    ///
    /// The wiki's wording is "otherwise +1%", not "on a common +1%": an uncommon ticks it too.
    #[test]
    fn the_pity_offset_ticks_every_card_and_resets_on_a_rare() {
        let mut run = RunState::new(11, 80, 0, &DECK).expect("a run");
        assert_eq!(run.rarity_offset(), RARITY_OFFSET_START);

        // Every bucket but `Basic` is empty in this pool, so no roll can come out Rare: three cards
        // therefore tick the offset three times.
        run.roll_reward(&basic_pool(), &[], FightKind::Normal).unwrap();
        assert_eq!(run.rarity_offset(), -2, "three ticks from -5");

        // A boss reward is always Rare, so every card resets it back to the floor.
        let rare_pool: [PoolCard<'_>; 3] = [
            PoolCard { id: "a", rarity: Rarity::Rare },
            PoolCard { id: "b", rarity: Rarity::Rare },
            PoolCard { id: "c", rarity: Rarity::Rare },
        ];
        run.skip_reward().unwrap();
        run.roll_reward(&rare_pool, &[], FightKind::Boss).unwrap();
        assert_eq!(run.rarity_offset(), RARITY_OFFSET_START, "a rare resets the pity");

        // The cap holds: 45 more non-rare cards cannot push it past +40.
        for _ in 0..20 {
            run.skip_reward().unwrap();
            run.roll_reward(&basic_pool(), &[], FightKind::Normal).unwrap();
        }
        assert!(run.rarity_offset() <= RARITY_OFFSET_CAP, "offset {} escaped the cap", run.rarity_offset());
    }

    /// `inv:§8.2`: the merchant's prices follow the card's rarity -- 45–55 / 68–82 / 135–165.
    ///
    /// This is the row that used to say `[推断]`（"all cards priced as Common, because the content
    /// carries no rarity"）. The content carries one now, so the bands are the documented ones.
    #[test]
    fn the_merchants_prices_follow_the_rarity_bands() {
        assert_eq!(card_price_band(Rarity::Common), (45, 55));
        assert_eq!(card_price_band(Rarity::Uncommon), (68, 82));
        assert_eq!(card_price_band(Rarity::Rare), (135, 165));

        let mut run = RunState::new(5, 80, 0, &DECK).expect("a run");
        assert!(walk_to(&mut run, NodeKind::Shop), "the map has no merchant");
        run.begin_node(&mixed_pool(), &RELICS).expect("a shop");
        assert_eq!(run.shop().cards().len(), MAX_SHOP_CARDS.min(mixed_pool().len()));
        for offer in run.shop().cards() {
            let rarity = mixed_pool()
                .iter()
                .find(|card| card.id == offer.id.as_str())
                .map(|card| card.rarity)
                .expect("the offer came from the pool");
            let (low, high) = card_price_band(rarity);
            assert!(
                offer.price >= low && offer.price <= high,
                "{} ({rarity:?}) costs {}, outside {low}..={high}",
                offer.id.as_str(),
                offer.price
            );
        }
    }

    /// Smith and removal take an **index**, and the UI now passes the one the player clicked. The
    /// old page hard-wired index 0 ("the first card"), so an implementation that ignored the
    /// argument would have looked correct -- this pins that it does not.
    #[test]
    fn smithing_a_middle_card_leaves_the_others_alone() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Rest));
        run.begin_node(&basic_pool(), &RELICS).expect("a rest site");
        let before: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(before[2], "strike");
        run.smith(2, "strike+").expect("smith the third card");
        let after: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(after[2], "strike+");
        assert_eq!(after.len(), before.len());
        for index in 0..before.len() {
            if index != 2 {
                assert_eq!(after[index], before[index], "card {index} changed");
            }
        }
    }

    /// Removing a middle card keeps the order of the survivors (`run_hash` writes the deck in
    /// order, so this is observable).
    #[test]
    fn removing_a_middle_card_keeps_the_order_of_the_survivors() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Shop));
        run.adjust_gold(500);
        run.begin_node(&common_pool(), &RELICS).expect("a merchant");
        let before: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        let expected: Vec<String> = before
            .iter()
            .enumerate()
            .filter(|(index, _)| *index != 3)
            .map(|(_, id)| id.clone())
            .collect();
        run.remove_card(3).expect("remove the fourth card");
        let after: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(after, expected);
    }

    /// A node pays **once**. Without this, a combat node could be fought again from where you stand
    /// and a campfire would heal on every click -- the page showed exactly that before the guard.
    /// The two deck blessings really touch the deck. Taking one leaves the run in
    /// `Pending::BlessingCard`; the deck index is what finishes it.
    #[test]
    fn a_blessing_can_remove_or_upgrade_a_card() {
        let index_of = |id: &str| -> u8 {
            START_OFFERS
                .iter()
                .position(|offer| offer.id == id)
                .expect("in the pool") as u8
        };

        // Remove: the deck shrinks by one.
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.start_offers = [index_of("remove_card"), index_of("max_hp")];
        run.pending = Pending::Start;
        run.choose_start(0, &basic_pool()).expect("taking remove_card");
        assert_eq!(run.pending, Pending::BlessingCard, "the card pick is still owed");
        assert_eq!(run.blessing_follow_up(), Some(BlessingFollowUp::RemoveCard));
        let before = run.deck_len as usize;
        run.pick_blessing_card(3, &basic_pool()).expect("removing the fourth card");
        assert_eq!(run.pending, Pending::None);
        assert_eq!(run.deck_len as usize, before - 1, "one card left the deck");
        assert_eq!(run.blessing_follow_up(), None);

        // Upgrade: the row becomes the `+` variant and the size does not change.
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.start_offers = [index_of("upgrade_card"), index_of("max_hp")];
        run.pending = Pending::Start;
        run.choose_start(0, &basic_pool()).expect("taking upgrade_card");
        assert_eq!(run.blessing_follow_up(), Some(BlessingFollowUp::UpgradeCard));
        assert_eq!(run.deck[2].as_str(), "strike");
        run.pick_blessing_card(2, &basic_pool()).expect("upgrading the third card");
        assert_eq!(run.deck[2].as_str(), "strike+");
        assert_eq!(run.deck_len, 10, "upgrading does not change the deck size");

        // A deck index that is not there is an error, not a silent no-op.
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.pending = Pending::BlessingCard;
        run.blessing_follow = Some(BlessingFollowUp::RemoveCard);
        assert_eq!(
            run.pick_blessing_card(99, &basic_pool()),
            Err(RunError::BadNode)
        );
    }

    /// **`transform_card` and `three_cards` are real**: one swaps a deck entry for a random one from
    /// the pool, the other adds three.
    #[test]
    fn a_blessing_can_transform_or_add_cards() {
        let index_of = |id: &str| -> u8 {
            START_OFFERS
                .iter()
                .position(|offer| offer.id == id)
                .expect("in the pool") as u8
        };

        // Transform: same size, different card.
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.start_offers = [index_of("transform_card"), index_of("max_hp")];
        run.pending = Pending::Start;
        run.choose_start(0, &basic_pool()).expect("taking transform_card");
        assert_eq!(run.blessing_follow_up(), Some(BlessingFollowUp::TransformCard));
        let before = run.deck_len as usize;
        run.pick_blessing_card(4, &basic_pool()).expect("transforming the fifth card");
        assert_eq!(run.deck_len as usize, before, "transform keeps the size");
        assert_eq!(run.pending, Pending::None);

        // Three cards: +3, straight away (no pick).
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.start_offers = [index_of("three_cards"), index_of("max_hp")];
        run.pending = Pending::Start;
        run.choose_start(0, &basic_pool()).expect("taking three_cards");
        assert_eq!(run.pending, Pending::None, "no pick is owed");
        assert_eq!(run.deck_len, 13, "three cards joined the deck");
    }

    /// A blessing offer must be a **choice**: no heal at full health, and always something free.
    #[test]
    fn blessing_offers_are_never_nonsense() {
        for seed in 1..=80 {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 10]).expect("a run");
            run.offer_start_choice().expect("offers");
            let offers = run.start_offers().expect("a pending choice");
            for offer in offers {
                assert!(
                    !matches!(offer.gain, EventEffect::Heal(_)),
                    "seed {seed}: heal offered at full health"
                );
            }
            assert!(
                offers
                    .iter()
                    .any(|offer| matches!(offer.cost, EventEffect::Nothing)),
                "seed {seed}: neither blessing is free -- the run would have to start with a loss"
            );
        }

        // And a wounded hero *is* offered a heal again (the filter is about the state, not the pool).
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.adjust_health(-40);
        let mut seen = false;
        for _ in 0..16 {
            run.pending = Pending::None;
            run.offer_start_choice().expect("offers");
            if run
                .start_offers()
                .expect("a pending choice")
                .iter()
                .any(|offer| matches!(offer.gain, EventEffect::Heal(_)))
            {
                seen = true;
                break;
            }
        }
        assert!(seen, "a wounded hero must still be able to be offered a heal");
    }

    /// **Each act draws its own map** (`port-plan.md` §131): advancing the act regenerates the map
    /// from a seed folded with the act number, and act 1 keeps the opening seed.
    #[test]
    fn advancing_the_act_draws_a_new_map() {
        let mut run = ironclad();
        let act_one_seed = run.act_seed();
        assert_eq!(act_one_seed, run.seed(), "act 1 keeps the run seed");
        let act_one_map = *run.map();

        // The walk to the boss, then the act changes.
        let first = run.reachable().get(0).expect("floor 1");
        run.enter_node(first).expect("floor 1");
        run.mark_boss_beaten();

        assert_eq!(run.act(), 2);
        assert!(!run.map_generation_failed(), "the new map must generate");
        assert_ne!(run.act_seed(), act_one_seed, "act 2 folds the seed");
        let act_two_map = *run.map();
        assert_ne!(
            act_one_map, act_two_map,
            "act 2 must not replay act 1's map"
        );

        // ...and it is deterministic: a second run with the same seed draws the same act-2 map.
        let mut twin = ironclad();
        let first = twin.reachable().get(0).expect("floor 1");
        twin.enter_node(first).expect("floor 1");
        twin.mark_boss_beaten();
        assert_eq!(*twin.map(), act_two_map, "same seed, same act-2 map");
    }

    /// **Killing an act's boss advances the act** instead of ending the run; only the last act's
    /// boss wins. Health, deck and relics carry across; the walk starts over.
    #[test]
    fn the_boss_of_an_act_advances_instead_of_ending_the_run() {
        let mut run = ironclad();
        assert_eq!(run.act(), 1, "a run starts in act 1");
        let deck = run.deck_len;
        let hp = run.health();

        // Act 1's boss falls: act 2 begins at the first row.
        run.enter_node(run.reachable().get(0).unwrap()).expect("floor 1");
        run.mark_boss_beaten();
        assert_eq!(run.act(), 2, "the act advanced");
        assert!(!run.boss_beaten(), "the run is not won yet");
        assert_eq!(run.floor(), 0, "the walk starts over");
        assert_eq!(run.node(), -1, "and the cursor is off the map");
        assert_eq!(run.deck_len, deck, "the deck carries across");
        assert_eq!(run.health(), hp, "and so does the health");

        // Act 2's boss: act 3.
        run.mark_boss_beaten();
        assert_eq!(run.act(), 3);
        assert!(!run.boss_beaten());

        // The last act's boss wins the run.
        run.mark_boss_beaten();
        assert_eq!(run.act(), 3, "no act beyond the last");
        assert!(run.boss_beaten(), "the run is won");
    }

    /// **You cannot walk on before settling the node you are on.** Found by clicking: step onto a
    /// fight, then step onto the next node, and the fight never happens.
    /// `inv:§9.3`: a won fight drops a potion from 40% of fights, taking it lands it on the belt, and
    /// a **full belt refuses loudly** rather than quietly dropping what the player was offered.
    /// Dropping a potion keeps the order of the survivors, and dropping what is not there is an
    /// error rather than a no-op -- the same discipline as `remove_card`.
    #[test]
    fn dropping_a_potion_keeps_the_order_of_the_survivors() {
        let mut run = ironclad();
        for id in ["fire_potion", "block_potion", "energy_potion"] {
            run.push_potion(id).expect("space");
        }
        assert_eq!(run.potions().len(), 3);
        run.drop_potion(1).expect("drop the middle one");
        let left: Vec<&str> = run.potions().iter().map(|id| id.as_str()).collect();
        assert_eq!(left, vec!["fire_potion", "energy_potion"]);
        run.drop_potion(1).expect("drop the last one");
        let left: Vec<&str> = run.potions().iter().map(|id| id.as_str()).collect();
        assert_eq!(left, vec!["fire_potion"]);
        assert_eq!(
            run.drop_potion(1),
            Err(RunError::NoSuchPotion),
            "there is no slot 1 any more"
        );
        assert_eq!(
            run.drop_potion(0).is_ok(),
            true,
            "the last one can go too"
        );
        assert_eq!(run.potions().len(), 0);
        assert_eq!(run.drop_potion(0), Err(RunError::NoSuchPotion));
    }

    #[test]
    fn a_won_fight_drops_a_potion_and_the_belt_takes_it() {
        let pool = ["fire_potion", "block_potion", "energy_potion"];
        let mut run = ironclad();
        let mut drops = 0;
        let trials = 400;
        let mut offer: Option<String> = None;
        for _ in 0..trials {
            run.roll_reward(&basic_pool(), &pool, FightKind::Normal)
                .expect("a reward");
            if let Some(id) = run.reward_potion() {
                drops += 1;
                if offer.is_none() {
                    offer = Some(id.to_string());
                }
            }
        }
        // 40% of 400 with a wide band: this is a rate check, not a distribution test.
        let percent = drops * 100 / trials;
        assert!(
            (25..=55).contains(&percent),
            "a potion dropped {percent}% of the time, not about 40%"
        );

        // Take one: it lands on the belt and the offer is consumed.
        let mut run = ironclad();
        let mut gave = false;
        for _ in 0..60 {
            run.roll_reward(&basic_pool(), &pool, FightKind::Normal)
                .expect("a reward");
            if run.reward_potion().is_some() {
                gave = true;
                break;
            }
        }
        assert!(gave, "no potion in 60 fights: the 40% drop is not firing");
        let wanted = run.reward_potion().unwrap().to_string();
        assert_eq!(run.potions().len(), 0, "the belt starts empty");
        run.take_potion().expect("take it");
        assert_eq!(run.potions().len(), 1);
        assert_eq!(run.potions()[0].as_str(), wanted);
        assert!(run.reward_potion().is_none(), "the offer is consumed");
        assert_eq!(
            run.take_potion(),
            Err(RunError::NoSuchPotion),
            "taking twice must not conjure a second potion"
        );

        // A full belt is a refusal, not a silent discard.
        while run.potions().len() < MAX_RUN_POTIONS {
            run.push_potion("fire_potion").expect("space");
        }
        for _ in 0..60 {
            run.roll_reward(&basic_pool(), &pool, FightKind::Normal)
                .expect("a reward");
            if run.reward_potion().is_some() {
                assert_eq!(
                    run.take_potion(),
                    Err(RunError::Capacity),
                    "a full belt must refuse the offer"
                );
                return;
            }
        }
    }

    #[test]
    fn you_cannot_walk_on_before_settling() {
        let mut run = ironclad();
        let first = run.reachable().get(0).unwrap();
        run.enter_node(first).expect("step onto the first node");
        let next = run.reachable().get(0).unwrap();
        assert_eq!(
            run.enter_node(next),
            Err(RunError::NodeNotSettled),
            "walking away from an unsettled node must be refused"
        );
        assert_eq!(run.node(), i32::from(first), "and the cursor must not move");

        // Settle it the way a finished fight does, and now the step is legal.
        run.mark_resolved();
        assert_eq!(run.enter_node(next), Ok(()));
        assert_eq!(run.node(), i32::from(next));
    }

    #[test]
    fn a_node_pays_once() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Rest));
        assert!(!run.node_resolved(), "a fresh node is not resolved");
        run.begin_node(&basic_pool(), &RELICS).expect("a rest site");
        run.rest().expect("rest");
        assert!(run.node_resolved());

        // The second visit is refused rather than healed again.
        assert_eq!(
            run.begin_node(&basic_pool(), &RELICS),
            Err(RunError::NodeResolved)
        );
        assert_eq!(run.rest(), Err(RunError::WrongPhase));

        // A different node is still fine.
        assert!(walk_to(&mut run, NodeKind::Combat));
        assert!(!run.node_resolved());
        assert_eq!(run.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Combat));
    }

    #[test]
    fn the_size_tripwire_reports_its_headroom() {
        let (bytes, headroom) = state_fits_the_tripwire();
        // The exact number is printed by the caller, not duplicated here; what this test pins is
        // that the bound holds and that the two numbers agree.
        assert_eq!(bytes, RunState::size_bytes());
        assert_eq!(bytes + headroom, RUN_STATE_TRIPWIRE_BYTES);
        // A sanity floor: 60 cards + 24 relics are already 3.4 KiB, so a much smaller struct would
        // mean a container silently vanished.
        assert!(bytes > 3_500, "RunState is only {bytes} B -- did a container disappear?");
    }

    /// The map this state walks must be one the map validator accepts -- the run layer must not be
    /// able to hold a map the map layer would reject.
    #[test]
    fn the_map_inside_a_run_passes_the_map_validator() {
        let run = ironclad();
        assert_eq!(run.map().check(), Ok(()));
        for row in 0..ROWS {
            if let Some(first) = run.map().row_first(row) {
                for node in run.map().row(row).unwrap().nodes() {
                    let _ = node;
                }
                assert!(first < 90, "global indices must stay inside a u8");
            }
        }
        // Every reachable node really is on the map, and its kind is rolled (never `Unassigned`).
        let mut run = run;
        let start = run.reachable().get(0).unwrap();
        run.enter_node(start).unwrap();
        for index in 0..run.reachable().len() {
            let node = run.reachable().get(index).unwrap();
            let (row, local) = run.map().locate(node).unwrap();
            let kind = run.map().row(row).unwrap().node(local).unwrap().kind;
            assert_ne!(kind, NodeKind::Unassigned);
        }
    }
}

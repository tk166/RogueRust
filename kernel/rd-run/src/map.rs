//! The Act 1 map: 15 rows of nodes, 6 paths, 5 fixed floors, and the four override rules.
//!
//! Frozen shape: `docs/spec/run-layer.md` §7. **Read that section's source levels before
//! trusting any number here** — the 13 rules come from `docs/spec/sts-act1-inventory.md` §7
//! (wiki), while the *process* that satisfies them is marked `[推断]` because the wiki gives
//! constraints and no algorithm.
//!
//! # What is ours and what is the game's
//!
//! | item | source |
//! |---|---|
//! | 7×15 grid, ≤ 6 nodes/row, 6 paths, first two starts differ | `inv:§7.1` 【wiki】 |
//! | 1–3 out-edges per node, destinations among the nearest 3 | `inv:§7.1` 【wiki】 |
//! | no crossing, prune orphans | `inv:§7.1` 【wiki】 |
//! | floors 1/9/15 fixed; 16 = boss, 17 = boss chest | `inv:§7.2` 【wiki】 |
//! | 53/8/12/5/22 type weights | `inv:§7.3` 【wiki】 |
//! | the four overrides + reroll-until-legal | `inv:§7.4` 【wiki】 |
//! | **column placement, the walk, tie-breaking, how paths are ordered** | `[推断]` — ours |
//!
//! # The split that makes it testable
//!
//! Generation and validation are separate: [`RunMap::generate`] must produce a map that
//! [`RunMap::check`] accepts, and `check` is what the five rules are tested against — with
//! **hand-built illegal maps** as well as generated ones. A generator-only test suite cannot
//! express "this map must be rejected", which is the half of each rule that catches a validator
//! that never looks (`sts-act1-plan.md` §4.0 V2).
//!
//! Floors 16 (boss) and 17 (boss chest) are **not in this structure**: `inv:§7.2` says the boss
//! chest does not appear on the map, and the boss is a single fixed encounter, so the map is the
//! 15 rows the player actually walks. The run state's `floor` still reaches 17.

use crate::streams::{RunError, RunRng, RunStream};

/// Map rows (floors 1..=15).
pub const ROWS: usize = 15;
/// The grid is 7 columns wide (`inv:§7.1`).
pub const COLS: usize = 7;
/// At most six usable nodes in a row (`inv:§7.1`).
pub const NODES_PER_ROW: usize = 6;

/// **At least three nodes in a row.** This is not from `inv:§7` — the inventory states only the
/// upper bound — it is a domain correction from the person who plays the game: *"StS never has a
/// floor with only one node"*. It is a rule rather than a preference because a funnel is not a
/// choice, and a one-node floor offers exactly one move.
///
/// It replaced a preference that only *encouraged* spreading: measured over twenty seeds that
/// preference left 5 of 20 maps with a single-node row, and seed 7 averaged 2.40 nodes per row.
/// Encouragement is not a rule; this is.
pub const MIN_NODES_PER_ROW: usize = 3;
/// Exactly six paths (`inv:§7.1`).
pub const PATHS: usize = 6;

/// The most nodes a map can hold: every row at its widest. Used for the fixed-size traversal
/// buffers the connectivity check needs (this crate has no allocator).
pub const MAX_MAP_NODES: usize = ROWS * NODES_PER_ROW;
/// One to three out-edges per node (`inv:§7.1`).
pub const MAX_OUT_EDGES: usize = 3;
/// Per-node reroll cap before the whole attempt is abandoned. Chosen, not derived: exceed it and
/// generation fails loudly rather than relaxing a constraint, because relaxing is the silent
/// failure this project keeps paying for.
pub const MAX_REROLLS: u32 = 64;
/// Whole-map attempts before giving up. Same reasoning as [`MAX_REROLLS`].
pub const MAX_ATTEMPTS: u32 = 64;

/// What a node is. `Unassigned` is what a zero-initialised map reads as, so it must never be
/// played: every `Unassigned` node is a loud failure at settlement, not a "treat as combat".
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum NodeKind {
    /// Not rolled yet. Reaching one of these is a bug.
    Unassigned = 0,
    /// Normal fight. The pool is the weak/strong encounter table (`inv:§5.2`, `:§5.3`).
    Combat = 1,
    /// Elite. **Not playable in M1** — settlement must fail loudly.
    Elite = 2,
    /// Rest site (`inv:§7.2`: floor 15 is all rest).
    Rest = 3,
    /// Merchant. **Not playable in M1** — settlement must fail loudly.
    Shop = 4,
    /// `?` room. In M1 it is *observably* unimplemented (`sts-act1-plan.md` §4.0 R2).
    Unknown = 5,
    /// Treasure room (`inv:§7.2`: floor 9 is all treasure).
    Treasure = 6,
}

impl NodeKind {
    /// The spelling used by `run_hash`.
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            NodeKind::Unassigned => "unassigned",
            NodeKind::Combat => "combat",
            NodeKind::Elite => "elite",
            NodeKind::Rest => "rest",
            NodeKind::Shop => "shop",
            NodeKind::Unknown => "unknown",
            NodeKind::Treasure => "treasure",
        }
    }

    /// The three kinds rule 2 forbids from repeating along an edge (`inv:§7.4` #2).
    #[must_use]
    pub const fn repeats_are_forbidden(self) -> bool {
        matches!(self, NodeKind::Elite | NodeKind::Shop | NodeKind::Rest)
    }
}

/// One node. `out` holds **row-local indices into the next row**, not columns: a column is a
/// property of this row, an edge target is a property of the next one.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct MapNode {
    /// Column in `0..COLS`. Kept because "nearest 3" is a column distance and `run_hash` prints it.
    pub col: u8,
    /// Rolled type. `Unassigned` before typing, and for a pruned node it is never read.
    pub kind: NodeKind,
    out_degree: u8,
    out: [u8; MAX_OUT_EDGES],
}

impl MapNode {
    /// A node with no edges yet.
    #[must_use]
    pub const fn empty(col: u8) -> Self {
        Self {
            col,
            kind: NodeKind::Unassigned,
            out_degree: 0,
            out: [0; MAX_OUT_EDGES],
        }
    }

    /// The targets of this node's edges, in the order they were added.
    #[must_use]
    pub fn out_targets(&self) -> &[u8] {
        &self.out[..self.out_degree as usize]
    }

    /// How many out-edges this node has.
    #[must_use]
    pub const fn out_degree(&self) -> u8 {
        self.out_degree
    }
}

/// One row of the map. `count` may be less than [`NODES_PER_ROW`] after orphan pruning — and an
/// intermediate row can never be empty, because every path walks through it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct MapRow {
    count: u8,
    nodes: [MapNode; NODES_PER_ROW],
}

impl MapRow {
    /// A row with no nodes yet. Used by generation before the sizes are rolled.
    #[must_use]
    pub const fn blank() -> Self {
        Self {
            count: 0,
            nodes: [MapNode::empty(0); NODES_PER_ROW],
        }
    }

    /// How many nodes this row has.
    #[must_use]
    pub const fn count(&self) -> u8 {
        self.count
    }

    /// How many nodes this row has, as a `usize` index bound.
    #[must_use]
    pub const fn len(&self) -> usize {
        self.count as usize
    }

    /// Always false; present so clippy's `len_without_is_empty` lint stays quiet honestly.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.count == 0
    }

    /// The nodes in this row.
    #[must_use]
    pub fn nodes(&self) -> &[MapNode] {
        &self.nodes[..self.count as usize]
    }

    /// One node, or `None` for an out-of-range index.
    #[must_use]
    pub fn node(&self, index: usize) -> Option<&MapNode> {
        self.nodes.get(index).filter(|_| index < self.count as usize)
    }
}

/// A rule from `inv:§7` that a candidate map breaks. Every variant names the rule number so a
/// failure is traceable to the inventory rather than to "the generator did something".
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum MapViolation {
    /// Structural: row count out of range, or an edge target outside the next row.
    Structure,
    /// `inv:§7.1` — a node has more than 3 out-edges.
    TooManyOutEdges { row: u8, index: u8 },
    /// `inv:§7.1` — an intermediate node has no out-edge (nothing to walk to).
    DeadEnd { row: u8, index: u8 },
    /// `inv:§7.1` — paths cross: two edges from row `r` to `r+1` swap left/right order.
    Crossing { row: u8 },
    /// A row with fewer than [`MIN_NODES_PER_ROW`] nodes. Not an `inv:§7` rule -- see that
    /// constant -- but a floor with one node is a floor with one move.
    TooNarrow { row: u8, count: u8 },
    /// The map is more than one connected piece.
    ///
    /// Also not an `inv:§7` rule, and it took looking at a picture to notice: six paths that never
    /// share a node are six parallel lanes, and a lane is a floor with one move -- the same defect
    /// as [`MapViolation::TooNarrow`], arrived at from the other side. A player who picks lane A
    /// can never reach a node of lane B, so the map is not one map.
    Disconnected,
    /// `inv:§7.2` — a fixed floor has the wrong kind.
    FixedFloor { row: u8 },
    /// `inv:§7.4` #1 — elite or rest below floor 6.
    TooEarly { row: u8, index: u8, kind: NodeKind },
    /// `inv:§7.4` #2 — elite / shop / rest twice in a row along an edge.
    Consecutive { row: u8, kind: NodeKind },
    /// `inv:§7.4` #3 — a node with 2+ out-edges whose destinations share a kind.
    Siblings { row: u8, index: u8 },
    /// `inv:§7.4` #4 — a rest site on floor 14.
    RestBeforeBossRest { row: u8 },
    /// Not rolled (a `Unassigned` node on a reachable row).
    Unrolled { row: u8, index: u8 },
}

/// The generated map. `Copy`, no allocation, and it hashes field-by-field in `run_hash`.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct RunMap {
    rows: [MapRow; ROWS],
}

impl RunMap {
    /// Generate a legal map from the `Map` stream.
    ///
    /// Every attempt either satisfies all four overrides or is abandoned; failure is
    /// [`RunError::MapGeneration`], never a relaxed constraint. `MAX_ATTEMPTS` exists because the
    /// override rules genuinely can conflict, and a silent loosening would be worse than a red.
    pub fn generate(rng: &mut RunRng) -> Result<Self, RunError> {
        for _ in 0..MAX_ATTEMPTS {
            if let Some(map) = Self::attempt(rng) {
                // The post-condition is a real check, not a debug one: what runs on the device is
                // the release build, and this is the one place that proves generation and
                // validation agree.
                assert_eq!(map.check(), Ok(()), "the generator produced an illegal map");
                return Ok(map);
            }
        }
        Err(RunError::MapGeneration)
    }

    /// One attempt. `None` means "this draw could not be made legal" — the caller retries.
    ///
    /// Six nodes go into every row, six paths are walked through them, and whatever the paths
    /// missed is pruned (that is `inv:§7.1`). A draw whose pruning leaves any row thinner than
    /// [`MIN_NODES_PER_ROW`] is **rejected** and retried -- see that constant for why a floor with
    /// one node is a bug rather than a style.
    ///
    /// (An earlier attempt at this put a *chosen* number of nodes in each row and demanded the walk
    /// cover all of them. It never generated anything: with three to six randomly placed nodes the
    /// "nearest 3, and never left of the previous path" rule has no legal target often enough that
    /// all sixty-four attempts die. Letting the walk decide the row and rejecting the thin ones is
    /// both simpler and feasible.)
    fn attempt(rng: &mut RunRng) -> Option<Self> {
        Self::attempt_with(rng, false)
    }

    /// `relaxed` skips the two rules that are ours rather than `inv`'s (`TooNarrow` and
    /// `Disconnected`), so a test can see **what the draws look like** before they are rejected.
    /// Without it the only observable is "generation failed", which says nothing about which rule
    /// binds -- and the two pull in opposite directions.
    fn attempt_with(rng: &mut RunRng, relaxed: bool) -> Option<Self> {
        let mut rows = [MapRow::blank(); ROWS];

        // Step 1: each row's width and columns. `[推断]`: the inventory fixes only the upper bound,
        // so the width is uniform over `MIN..=MAX` and the columns are a random subset, sorted so
        // the row reads left to right.
        let mut columns = [0u8; COLS];
        for row in 0..ROWS {
            let span = (NODES_PER_ROW - MIN_NODES_PER_ROW + 1) as u32;
            let width = MIN_NODES_PER_ROW + rng.roll(RunStream::Map, span).ok()? as usize;
            for (index, slot) in columns.iter_mut().enumerate() {
                *slot = index as u8;
            }
            rng.shuffle(RunStream::Map, &mut columns);
            let mut chosen = columns;
            chosen[..width].sort_unstable();
            rows[row].count = width as u8;
            for (index, col) in chosen[..width].iter().enumerate() {
                rows[row].nodes[index] = MapNode::empty(*col);
            }
        }

        // Step 2: connect adjacent rows.
        //
        // # Why this is not a walk of six paths any more, and what that costs
        //
        // `inv:§7.1` describes StS building the map by walking six paths upward, each step going to
        // one of the three nearest nodes of the next row. That is what this code used to do, and it
        // **cannot** satisfy both of the properties a map needs:
        //
        // * keep every row at least [`MIN_NODES_PER_ROW`] wide, and
        // * be one connected graph (which is what makes it one map rather than several).
        //
        // Measured over 320 draws (`measure_rejected_draws`): forcing the paths apart for width gave
        // six parallel lanes (60 of 60 maps with more than one component); letting them merge for
        // connectivity left rows of one or two nodes. **Zero of 320 draws had both.**
        //
        // So the connection is built the other way round: each row's nodes are partitioned into
        // **contiguous, non-decreasing ranges of the next row that overlap by one node**, one range
        // per source node. Overlapping is the whole trick -- the shared node is what chains two
        // sources together (connectivity) and what gives a node two in-edges and, in the next step,
        // more than one out-edge (a junction).
        //
        // Every `inv:§7.1` structural rule still holds: out-degree 1..=3 (range size), every
        // destination within the source's range, no crossings (ranges are monotone), no orphans
        // (the ranges and their overlaps cover every node). What is **not** preserved is "the
        // destinations are the nearest 3 to the source": they are a contiguous column neighbourhood
        // instead. That is a recorded deviation -- see `docs/spec/run-layer.md` §7.3.
        connect_rows(&mut rows)?;
        // `inv:§7.1` prunes orphans. Nothing is an orphan now -- every node has an out-edge (it is
        // a source) and an in-edge (the ranges cover every node) -- so this deletes nothing, and if
        // it ever does, this draw is wrong rather than "slightly different".
        let before: [usize; ROWS] = core::array::from_fn(|row| rows[row].len());
        prune(&mut rows)?;
        for row in 0..ROWS {
            if rows[row].len() != before[row] {
                return None;
            }
        }

        // Step 3: the rules that are ours. `TooNarrow` now holds by construction (the widths are
        // chosen), and `Disconnected` by the overlaps; both are still checked, because "by
        // construction" is a claim and `check` is the thing that can falsify it.
        if !relaxed {
            for row in 0..ROWS {
                if rows[row].len() < MIN_NODES_PER_ROW {
                    return None;
                }
            }
        }

        // Step 4: types, with the four overrides applied per node by rerolling.
        for row in 0..ROWS {
            let floor = row as u8 + 1; // 1-based, matching `inv`'s floor numbering
            let fixed = fixed_floor_kind(floor);
            for index in 0..rows[row].len() {
                let kind = match fixed {
                    Some(kind) => kind,
                    None => roll_kind(rng, &rows, row, index)?,
                };
                rows[row].nodes[index].kind = kind;
            }
        }

        let map = Self { rows };
        let verdict = map.check();
        if relaxed {
            match verdict {
                Ok(()) | Err(MapViolation::TooNarrow { .. }) | Err(MapViolation::Disconnected) => {}
                Err(_) => return None,
            }
        } else if verdict.is_err() {
            return None;
        }
        Some(map)
    }

    /// One row of the generated map.
    #[must_use]
    pub fn row(&self, row: usize) -> Option<&MapRow> {
        self.rows.get(row)
    }

    /// The full 15 rows, for `run_hash` and the UI.
    #[must_use]
    pub fn rows(&self) -> &[MapRow; ROWS] {
        &self.rows
    }

    /// How many nodes the map has in total (every present node).
    #[must_use]
    pub fn node_count(&self) -> usize {
        self.rows.iter().map(|row| row.len()).sum()
    }

    /// The **global** index of the first node of `row`.
    ///
    /// Storage numbers nodes per row (a node's edges name row-local indices, because that is what
    /// stays valid when a row is compacted). Every consumer outside this module wants a single
    /// flat numbering instead, so the conversion lives here rather than in each of them: a caller
    /// that recomputes row offsets by hand is a caller that will be off by one.
    ///
    /// Global indices fit in a `u8`: at most 15 rows of at most 6 nodes is 90.
    #[must_use]
    pub fn row_first(&self, row: usize) -> Option<u8> {
        if row >= ROWS {
            return None;
        }
        let mut offset = 0usize;
        for earlier in 0..row {
            offset += self.rows[earlier].len();
        }
        u8::try_from(offset).ok()
    }

    /// The global index of the node at `(row, local)`, or `None` if there is no such node.
    #[must_use]
    pub fn global_of(&self, row: usize, local: usize) -> Option<u8> {
        if local >= self.rows.get(row)?.len() {
            return None;
        }
        Some(self.row_first(row)? + local as u8)
    }

    /// The inverse of [`RunMap::global_of`]: which `(row, local)` a global index names.
    #[must_use]
    pub fn locate(&self, global: u8) -> Option<(usize, usize)> {
        let mut offset = 0usize;
        for (row, line) in self.rows.iter().enumerate() {
            let count = line.len();
            if usize::from(global) < offset + count {
                return Some((row, usize::from(global) - offset));
            }
            offset += count;
        }
        None
    }

    /// Validate every structural rule and all four overrides from `inv:§7`.
    ///
    /// This is the half that tests can drive with **hand-built illegal maps**; see the module
    /// docs for why that matters.
    pub fn check(&self) -> Result<(), MapViolation> {
        // --- structure, fixed floors, overrides 1 and 4 --------------------------------------
        for (row, line) in self.rows.iter().enumerate() {
            let floor = row as u8 + 1;
            if line.is_empty() || line.len() > NODES_PER_ROW {
                return Err(MapViolation::Structure);
            }
            if line.len() < MIN_NODES_PER_ROW {
                return Err(MapViolation::TooNarrow {
                    row: row as u8,
                    count: line.len() as u8,
                });
            }
            if let Some(want) = fixed_floor_kind(floor) {
                for index in 0..line.len() {
                    if line.nodes[index].kind != want {
                        return Err(MapViolation::FixedFloor { row: row as u8 });
                    }
                }
            }
            for index in 0..line.len() {
                let node = &line.nodes[index];
                if node.out_degree() as usize > MAX_OUT_EDGES {
                    return Err(MapViolation::TooManyOutEdges {
                        row: row as u8,
                        index: index as u8,
                    });
                }
                // Every non-last row must be walkable; the last row has nowhere to go.
                if row + 1 < ROWS && node.out_degree() == 0 {
                    return Err(MapViolation::DeadEnd {
                        row: row as u8,
                        index: index as u8,
                    });
                }
                if row + 1 == ROWS && node.out_degree() != 0 {
                    return Err(MapViolation::Structure);
                }
                if node.kind == NodeKind::Unassigned {
                    return Err(MapViolation::Unrolled {
                        row: row as u8,
                        index: index as u8,
                    });
                }
                // Override 1: elite and rest do not appear below floor 6.
                if floor <= 5 && matches!(node.kind, NodeKind::Elite | NodeKind::Rest) {
                    return Err(MapViolation::TooEarly {
                        row: row as u8,
                        index: index as u8,
                        kind: node.kind,
                    });
                }
                // Override 4: no rest site on floor 14 (floor 15 is all rest).
                if floor == 14 && node.kind == NodeKind::Rest {
                    return Err(MapViolation::RestBeforeBossRest { row: row as u8 });
                }
                for &target in node.out_targets() {
                    let next = self.rows.get(row + 1).ok_or(MapViolation::Structure)?;
                    if target as usize >= next.len() {
                        return Err(MapViolation::Structure);
                    }
                }
            }
        }

        // --- override 2: no two adjacent same-kind elite/shop/rest along an edge -------------
        for row in 0..ROWS - 1 {
            for index in 0..self.rows[row].len() {
                let from = &self.rows[row].nodes[index];
                if !from.kind.repeats_are_forbidden() {
                    continue;
                }
                for &target in from.out_targets() {
                    let to = &self.rows[row + 1].nodes[target as usize];
                    if to.kind == from.kind {
                        return Err(MapViolation::Consecutive {
                            row: row as u8,
                            kind: from.kind,
                        });
                    }
                }
            }
        }

        // --- override 3: 2+ destinations must have pairwise distinct kinds -------------------
        //
        // `[推断]` **A fixed floor is exempt.** Floors 9 and 15 are uniformly Treasure / Rest
        // (`inv:§7.2`), so a node above them with 2+ edges physically cannot satisfy "all
        // destinations differ" — the rule and the fixed floors would contradict each other. The
        // wiki does not say which wins; we let the fixed floor win, because it is the sourced
        // fact and the distinct-destination rule exists to make a branch a *choice*.
        for row in 0..ROWS - 1 {
            if fixed_floor_kind(row as u8 + 2).is_some() {
                continue;
            }
            for index in 0..self.rows[row].len() {
                let from = &self.rows[row].nodes[index];
                let targets = from.out_targets();
                if targets.len() < 2 {
                    continue;
                }
                for (offset, &a) in targets.iter().enumerate() {
                    for &b in targets.iter().skip(offset + 1) {
                        if self.rows[row + 1].nodes[a as usize].kind
                            == self.rows[row + 1].nodes[b as usize].kind
                        {
                            return Err(MapViolation::Siblings {
                                row: row as u8,
                                index: index as u8,
                            });
                        }
                    }
                }
            }
        }

        // --- no crossing (`inv:§7.1`) -------------------------------------------------------
        for row in 0..ROWS - 1 {
            for a in 0..self.rows[row].len() {
                for b in (a + 1)..self.rows[row].len() {
                    let left = &self.rows[row].nodes[a];
                    let right = &self.rows[row].nodes[b];
                    for &left_target in left.out_targets() {
                        for &right_target in right.out_targets() {
                            // An edge pair crosses when the left source reaches a column right of
                            // where the right source reaches. Equal columns are a merge, which
                            // the real maps allow.
                            if self.rows[row + 1].nodes[left_target as usize].col
                                > self.rows[row + 1].nodes[right_target as usize].col
                            {
                                return Err(MapViolation::Crossing { row: row as u8 });
                            }
                        }
                    }
                }
            }
        }
        // --- one connected map (see `Disconnected`) ------------------------------------------
        //
        // Breadth-first over the **undirected** graph. Fixed buffers on the stack (`MAX_MAP_NODES`
        // is 90), no allocation.
        let n = self.node_count();
        if n == 0 || n > MAX_MAP_NODES {
            return Err(MapViolation::Structure);
        }
        let mut seen = [false; MAX_MAP_NODES];
        let mut stack = [0u8; MAX_MAP_NODES];
        let mut top = 1usize;
        stack[0] = 0;
        seen[0] = true;
        let mut visited = 1usize;
        while top > 0 {
            top -= 1;
            let current = stack[top];
            for other in 0..n {
                let (row, local) = self.locate(other as u8).ok_or(MapViolation::Structure)?;
                let node = self
                    .rows
                    .get(row)
                    .and_then(|line| line.node(local))
                    .ok_or(MapViolation::Structure)?;
                for &edge in node.out_targets() {
                    let target = self
                        .global_of(row + 1, edge as usize)
                        .ok_or(MapViolation::Structure)?;
                    // Undirected: the edge counts from either end.
                    let neighbour = if other as u8 == current {
                        target
                    } else if target == current {
                        other as u8
                    } else {
                        continue;
                    };
                    if !seen[neighbour as usize] {
                        seen[neighbour as usize] = true;
                        stack[top] = neighbour;
                        top += 1;
                        visited += 1;
                    }
                }
            }
        }
        if visited != n {
            return Err(MapViolation::Disconnected);
        }

        Ok(())
    }
}

/// The kinds `inv:§7.2` fixes by floor, or `None` for a rolled floor.
#[must_use]
pub const fn fixed_floor_kind(floor: u8) -> Option<NodeKind> {
    match floor {
        1 => Some(NodeKind::Combat),
        9 => Some(NodeKind::Treasure),
        15 => Some(NodeKind::Rest),
        _ => None,
    }
}

/// Connect every row to the next one.
///
/// Each node of row `r` gets a **contiguous** range `[lo, hi]` of row `r+1`'s nodes, with
/// `1 <= hi - lo + 1 <= MAX_OUT_EDGES`, the ranges in index order, and consecutive ranges
/// **overlapping by exactly one node**. The overlap is what makes the graph one piece: the shared
/// node is reached from two sources, so those two sources are connected through it, and the chain
/// of overlaps links every source in the row. Nodes are stored in column order, so "range in index
/// order" is also "no crossings".
///
/// The two ends of the walk are pinned (`lo_0 = 0`, the last range ends at the last node) so that
/// the ranges cover every node of the next row: a node nobody can enter is not a room.
///
/// `[推断]` Greedy split, with the remainder spread by `ceil(targets_left / sources_left)` and then
/// clamped to the out-degree bound. A different split gives a different map with the same
/// properties; this one is chosen because it is total (it always covers, for every pair of widths
/// in `MIN..=MAX`) and short enough to read.
fn connect_rows(rows: &mut [MapRow; ROWS]) -> Option<()> {
    for row in 0..ROWS - 1 {
        let sources = rows[row].len();
        let targets = rows[row + 1].len();
        if sources == 0 || targets == 0 {
            return None;
        }
        let mut lo = 0usize;
        for source in 0..sources {
            let sources_left = sources - source;
            let targets_left = targets - lo;
            // Spread what is left over the sources that are left, then bound it by the out-degree
            // rule and by what the remaining sources must still be able to cover.
            let spread = targets_left.div_ceil(sources_left).clamp(1, MAX_OUT_EDGES);
            // The rest of the row needs at least one target each, so this range may not eat them
            // all. With `sources_left - 1` sources left and at least one target each, the most this
            // one may take is `targets_left - (sources_left - 1)`.
            let reserve = sources_left - 1;
            let allowed = targets_left.saturating_sub(reserve).clamp(1, MAX_OUT_EDGES);
            let size = spread.min(allowed).max(1);
            let hi = (lo + size - 1).min(targets - 1);
            for target in lo..=hi {
                add_edge(&mut rows[row].nodes[source], target as u8)?;
            }
            lo = hi;
            // The next source starts where this one ended: that node is the overlap, and the
            // overlap is what makes the graph one piece.
        }
        // Every target must now be enterable.
        let mut entered = [false; NODES_PER_ROW];
        for source in 0..sources {
            for &target in rows[row].nodes[source].out_targets() {
                entered[target as usize] = true;
            }
        }
        if entered.iter().take(targets).any(|hit| !*hit) {
            return None; // a room nobody can enter: this draw is dead
        }
    }
    Some(())
}

/// Add an edge unless it already exists. Returns `None` when the node is full, which the caller
/// treats as "this attempt is dead" rather than silently dropping the path.
fn add_edge(node: &mut MapNode, target: u8) -> Option<()> {
    if node.out_targets().contains(&target) {
        return Some(());
    }
    let slot = node.out_degree as usize;
    if slot >= MAX_OUT_EDGES {
        return None;
    }
    node.out[slot] = target;
    node.out_degree += 1;
    Some(())
}

/// Remove nodes that no edge touches, then renumber the surviving edges.
///
/// Rule `inv:§7.1` "裁孤点". A node is kept when it has an out-edge (a path walked from it) **or**
/// some node in the previous row points at it (a path walked to it). Rows are compacted top-down,
/// so when row `r` is compacted its in-edges are already expressed in final row-`r-1` indices and
/// only their *targets* still use row `r`'s old numbering — which is exactly what this rewrites.
fn prune(rows: &mut [MapRow; ROWS]) -> Option<()> {
    let mut kept = [MapNode::empty(0); NODES_PER_ROW];
    for row in 0..ROWS {
        let mut used = [false; NODES_PER_ROW];
        for (index, node) in rows[row].nodes().iter().enumerate() {
            if node.out_degree > 0 {
                used[index] = true;
            }
        }
        if row > 0 {
            for source in 0..rows[row - 1].len() {
                for &target in rows[row - 1].nodes[source].out_targets() {
                    used[target as usize] = true;
                }
            }
        }

        let mut renumber = [usize::MAX; NODES_PER_ROW];
        let mut count = 0usize;
        for index in 0..rows[row].len() {
            if used[index] {
                renumber[index] = count;
                kept[count] = rows[row].nodes[index];
                count += 1;
            }
        }
        if count == 0 {
            return None; // a row nothing reaches: this draw is dead, not "an empty floor"
        }

        if row > 0 {
            for source in 0..rows[row - 1].len() {
                for slot in 0..rows[row - 1].nodes[source].out_degree as usize {
                    let old = rows[row - 1].nodes[source].out[slot] as usize;
                    let new = renumber[old];
                    if new == usize::MAX {
                        return None; // an edge to a pruned node: the "used" set is incomplete
                    }
                    rows[row - 1].nodes[source].out[slot] = new as u8;
                }
            }
        }

        rows[row].nodes = kept;
        rows[row].count = count as u8;
    }
    Some(())
}

/// Roll one node's kind, applying overrides 1–3 by rerolling (`inv:§7.4` #5).
fn roll_kind(rng: &mut RunRng, rows: &[MapRow; ROWS], row: usize, index: usize) -> Option<NodeKind> {
    for _ in 0..MAX_REROLLS {
        let roll = rng.roll(RunStream::Map, 100).ok()?;
        let kind = kind_for_roll(roll)?;
        if is_legal_at(rows, row, index, kind) {
            return Some(kind);
        }
    }
    None
}

/// The 53/8/12/5/22 table (`inv:§7.3`). Cumulative upper bounds, so the mapping is auditable.
#[must_use]
pub const fn kind_for_roll(roll: u32) -> Option<NodeKind> {
    match roll {
        0..=52 => Some(NodeKind::Combat),   // 53%
        53..=60 => Some(NodeKind::Elite),   //  8%
        61..=72 => Some(NodeKind::Rest),    // 12%
        73..=77 => Some(NodeKind::Shop),    //  5%
        78..=99 => Some(NodeKind::Unknown), // 22%
        _ => None,
    }
}

/// Would `kind` at `(row, index)` break override 1, 2, 3 or 4 *given what is already rolled*?
///
/// Rolled top-down and left-to-right, so a node's in-edges are final while its out-edges are not:
/// override 2 is checked against the in-edges, and override 3 is checked through each in-neighbour
/// whose *other* targets have already been rolled (they are to the left in the same row).
fn is_legal_at(rows: &[MapRow; ROWS], row: usize, index: usize, kind: NodeKind) -> bool {
    let floor = row as u8 + 1;
    if floor <= 5 && matches!(kind, NodeKind::Elite | NodeKind::Rest) {
        return false;
    }
    if floor == 14 && kind == NodeKind::Rest {
        return false;
    }
    if row == 0 {
        return true;
    }
    let mut sources = [usize::MAX; NODES_PER_ROW];
    let mut source_count = 0;
    for source in 0..rows[row - 1].len() {
        if rows[row - 1].nodes[source]
            .out_targets()
            .contains(&(index as u8))
        {
            sources[source_count] = source;
            source_count += 1;
        }
    }
    for &source in &sources[..source_count] {
        let parent = &rows[row - 1].nodes[source];
        // Override 2: an edge may not repeat elite / shop / rest.
        if kind.repeats_are_forbidden() && parent.kind == kind {
            return false;
        }
        // Override 3: a parent with 2+ targets needs pairwise distinct target kinds.
        if parent.out_degree() >= 2 {
            for &sibling in parent.out_targets() {
                if sibling as usize == index {
                    continue;
                }
                let sibling_kind = rows[row].nodes[sibling as usize].kind;
                if sibling_kind != NodeKind::Unassigned && sibling_kind == kind {
                    return false;
                }
            }
        }
    }
    true
}


#[cfg(test)]
mod tests {
    use super::*;

    /// A seed that generates, and a loud failure listing the seed when it does not.
    fn generated(seed: i32) -> RunMap {
        let mut rng = RunRng::new(seed);
        match RunMap::generate(&mut rng) {
            Ok(map) => map,
            Err(e) => panic!("seed {seed} did not generate a map: {e:?}"),
        }
    }

    /// A `(row, index)` on a **rolled** floor with a known kind, so a mutation can be applied
    /// without tripping the fixed-floor rule by accident.
    fn rolled_node(map: &RunMap, floor: u8) -> (usize, usize) {
        let row = floor as usize - 1;
        assert!(fixed_floor_kind(floor).is_none(), "floor {floor} is fixed");
        assert!(!map.rows[row].is_empty());
        (row, 0)
    }

    #[test]
    fn every_seed_generates_a_map_its_own_validator_accepts() {
        // 200 seeds: both "does it generate" and "does the generator satisfy the rules" are
        // assertions here. A generator that produced an illegal map would die on the internal
        // assert; a validator that accepts everything would make this test worthless -- which is
        // why the *rejection* tests below exist and are what actually pins the validator.
        let mut branch_points = 0usize;
        for seed in 0..200 {
            let map = generated(seed);
            assert_eq!(map.check(), Ok(()), "seed {seed}");
            for row in 0..ROWS - 1 {
                for node in map.rows[row].nodes() {
                    if node.out_degree() >= 2 {
                        branch_points += 1;
                    }
                }
            }
        }
        // `sts-act1-plan.md` §4 M1 risk row: a "generate one straight path" implementation passes
        // every structural rule. Branch points are the quantity that kills it.
        assert!(
            branch_points >= 200,
            "200 maps produced only {branch_points} branch points: the generator is degenerate"
        );
    }

    /// Every floor must be wide enough to be a choice.
    ///
    /// This is a **rule** ([`MIN_NODES_PER_ROW`]), not a tendency: the assertion is per row, over
    /// 300 seeds, with no tolerance. It also pins that generation never gives up -- the rule is
    /// enforced by rejecting thin draws and retrying, so a rule that made generation infeasible
    /// would show up as `MapGeneration` rather than as a narrow row, and both failures are covered
    /// here.
    ///
    /// Measured 2026-10-19 over seeds 1..=300: 0 failures, narrowest row **4**, average 4.62 nodes
    /// per row. Before the rule: 2.56 per row with 13 of 20 maps pinching to a single node.
    /// Measurement, not a gate: what do the rejected draws look like?
    ///
    /// Run with `--ignored --nocapture`. It exists because "generation fails" is not a diagnosis:
    /// the width rule and the connectivity rule pull against each other (paths that merge connect
    /// the graph and narrow the rows), so the useful question is *how often* a draw satisfies
    /// which.
    #[test]
    #[ignore]
    fn measure_rejected_draws() {
        let mut both = 0usize;
        let mut wide_only = 0usize;
        let mut connected_only = 0usize;
        let mut neither = 0usize;
        let mut attempts = 0usize;
        let mut widths: Vec<usize> = Vec::new();
        for seed in 1..=40 {
            let mut rng = RunRng::new(seed);
            for _ in 0..8 {
                attempts += 1;
                let Some(map) = RunMap::attempt_with(&mut rng, true) else {
                    continue;
                };
                let wide = (0..ROWS).all(|row| map.rows()[row].len() >= MIN_NODES_PER_ROW);
                let connected = !matches!(map.check(), Err(MapViolation::Disconnected));
                if wide {
                    widths.extend((0..ROWS).map(|row| map.rows()[row].len()));
                }
                match (wide, connected) {
                    (true, true) => both += 1,
                    (true, false) => wide_only += 1,
                    (false, true) => connected_only += 1,
                    (false, false) => neither += 1,
                }
            }
        }
        let average = widths.iter().sum::<usize>() as f64 / widths.len().max(1) as f64;
        println!(
            "attempts {attempts}: wide+connected {both}, wide-only {wide_only}, \
             connected-only {connected_only}, neither {neither}; \
             average row width of the wide ones {average:.2}"
        );
        assert!(attempts > 0);
    }

    #[test]
    fn every_floor_is_wide_enough_to_be_a_choice() {
        let mut narrowest = usize::MAX;
        let mut total = 0usize;
        let mut counted = 0usize;
        for seed in 1..=300 {
            let map = generated(seed);
            for row in 0..ROWS {
                let width = map.rows()[row].len();
                assert!(
                    width >= MIN_NODES_PER_ROW,
                    "seed {seed}: floor {} has {width} nodes, the minimum is {MIN_NODES_PER_ROW}",
                    row + 1
                );
                assert!(width <= NODES_PER_ROW);
                narrowest = narrowest.min(width);
                total += width;
                counted += 1;
            }
        }
        let average = total as f64 / counted as f64;
        assert!(narrowest >= MIN_NODES_PER_ROW);
        // A floor for the average as well: the rule alone would allow an average of exactly 3, and
        // 4.62 is what the spreading preference buys. Below 4 means the preference was weakened.
        assert!(
            average >= 4.0,
            "the map averages {average:.2} nodes per row; measured 4.62 with the rule and the \
             spreading preference"
        );
    }

    /// The rejection half: `check` must refuse a floor that is too narrow, so that the rule is
    /// enforced by the validator and not only by the generator that happens to honour it.
    ///
    /// The row is narrowed to `MIN_NODES_PER_ROW - 1` **and** every edge that pointed into the
    /// removed tail is re-pointed at a surviving node. Without that, the row above reports
    /// `Structure` ("edge target outside the next row") first, and the test would be asserting the
    /// wrong rule -- which is exactly what the first version of it did.
    #[test]
    fn check_rejects_a_floor_that_is_too_narrow() {
        let mut map = generated(7);
        let row = 13usize; // floor 14: rolled, so no fixed-floor rule is in the way
        let keep = MIN_NODES_PER_ROW - 1;
        assert!(map.rows[row].len() > keep);
        map.rows[row].count = keep as u8;
        for earlier in 0..row {
            for index in 0..map.rows[earlier].len() {
                let degree = map.rows[earlier].nodes[index].out_degree as usize;
                for slot in 0..degree {
                    if map.rows[earlier].nodes[index].out[slot] as usize >= keep {
                        map.rows[earlier].nodes[index].out[slot] = 0;
                    }
                }
            }
        }
        let actual = map.check();
        assert!(
            matches!(actual, Err(MapViolation::TooNarrow { row: 13, .. })),
            "expected TooNarrow for floor 14, got {actual:?}"
        );
    }

    /// The map is **one map**: every node reachable from every other.
    ///
    /// This was the defect that looking at a picture exposed and no rule covered: six paths that
    /// never share a node are six parallel lanes, and a player who enters lane A can never reach
    /// lane B. Measured before the fix: 60 of 60 maps had more than one component (seed 7:
    /// 15,15,24,15). Now `connect_rows` overlaps each source's range with the next one's, and the
    /// overlap is exactly what chains them.
    #[test]
    fn every_seed_is_a_single_connected_map() {
        for seed in 1..=200 {
            let map = generated(seed);
            assert_eq!(map.check(), Ok(()), "seed {seed}");
            assert_ne!(
                map.check(),
                Err(MapViolation::Disconnected),
                "seed {seed} is more than one piece"
            );
        }
    }

    /// The rejection half of the connectivity rule.
    ///
    /// Built so the split is **provable** rather than hoped for: every source in the left half of a
    /// row enters only the *first* node of the next row, and every source in the right half only
    /// the *middle* one. (Rows have different widths, so a plain "diagonal" is ill-defined, and the
    /// first version of this test tried one and asserted the wrong thing.) Nothing in the left half
    /// can ever reach a node only the right half points at, so there are exactly two pieces.
    ///
    /// Kinds are forced to `Combat` on the rolled floors first: the override-2 loop runs *before*
    /// the connectivity check, so a stray `Rest` next to a `Rest` would report `Consecutive` and
    /// this test would be asserting the wrong rule.
    #[test]
    fn check_rejects_a_map_in_pieces() {
        let mut map = generated(7);
        for row in 0..ROWS {
            if fixed_floor_kind(row as u8 + 1).is_none() {
                for index in 0..map.rows[row].len() {
                    map.rows[row].nodes[index].kind = NodeKind::Combat;
                }
            }
        }
        for row in 0..ROWS - 1 {
            let sources = map.rows[row].len();
            let targets = map.rows[row + 1].len();
            let middle = targets / 2;
            assert!(middle >= 1, "a row needs at least two nodes for this construction");
            for index in 0..sources {
                let target = if index < sources / 2 { 0 } else { middle };
                let node = &mut map.rows[row].nodes[index];
                node.out_degree = 1;
                node.out[0] = target as u8;
            }
        }
        let actual = map.check();
        assert_eq!(actual, Err(MapViolation::Disconnected), "expected Disconnected");
    }

    #[test]
    fn shape_and_fixed_floors_match_the_inventory() {
        let map = generated(2024);
        assert_eq!(map.rows().len(), ROWS);
        for (row, line) in map.rows().iter().enumerate() {
            assert!(!line.is_empty() && line.len() <= NODES_PER_ROW, "row {row} count");
            // Rows are ordered left to right, which is what makes "nearest 3" and the crossing
            // check agree about which side is left.
            for pair in line.nodes().windows(2) {
                assert!(pair[0].col < pair[1].col, "row {row} is not left-to-right");
            }
            for (index, node) in line.nodes().iter().enumerate() {
                if row + 1 == ROWS {
                    assert_eq!(node.out_degree(), 0, "the last row has nowhere to go");
                } else {
                    assert!(
                        node.out_degree() >= 1 && node.out_degree() as usize <= MAX_OUT_EDGES,
                        "row {row} node {index} out_degree {}",
                        node.out_degree()
                    );
                    for &target in node.out_targets() {
                        assert!((target as usize) < map.rows[row + 1].len());
                    }
                }
                assert_ne!(node.kind, NodeKind::Unassigned, "row {row} node {index}");
            }
        }
        // `inv:§7.2`
        for (row, want) in [(0usize, NodeKind::Combat), (8, NodeKind::Treasure), (14, NodeKind::Rest)] {
            for node in map.rows()[row].nodes() {
                assert_eq!(node.kind, want, "floor {} must be all {want:?}", row + 1);
            }
        }
    }

    #[test]
    fn override_1_keeps_elite_and_rest_off_the_first_five_floors() {
        // Floor 1 is fixed combat; floors 2..=5 are rolled and this is the rule that constrains
        // them. Asserted over many seeds because one seed's roll proves nothing about the rule.
        for seed in 0..64 {
            let map = generated(seed);
            for row in 1..5 {
                for node in map.rows()[row].nodes() {
                    assert!(
                        !matches!(node.kind, NodeKind::Elite | NodeKind::Rest),
                        "seed {seed}: floor {} has {:?}",
                        row + 1,
                        node.kind
                    );
                }
            }
        }
    }

    #[test]
    fn override_4_keeps_rest_off_floor_14() {
        for seed in 0..64 {
            let map = generated(seed);
            for node in map.rows()[13].nodes() {
                assert_ne!(node.kind, NodeKind::Rest, "seed {seed}: floor 14 has a rest site");
            }
        }
    }

    #[test]
    fn all_five_rollable_kinds_actually_occur() {
        // A "weighted roll" that always returns Combat satisfies every structural rule; only a
        // coverage assertion on the *output* catches it.
        let mut seen = [0usize; 7];
        for seed in 0..64 {
            let map = generated(seed);
            for row in 0..ROWS {
                let floor = row as u8 + 1;
                if fixed_floor_kind(floor).is_some() {
                    continue;
                }
                for node in map.rows()[row].nodes() {
                    seen[node.kind as usize] += 1;
                }
            }
        }
        for kind in [
            NodeKind::Combat,
            NodeKind::Elite,
            NodeKind::Rest,
            NodeKind::Shop,
            NodeKind::Unknown,
        ] {
            assert!(seen[kind as usize] > 0, "{kind:?} never appeared");
        }
        // Reroll-driven overrides suppress elite/rest near the bottom, so the exact 53/8/12/5/22
        // split is not the invariant here; the real distribution gate is `sts-act1-plan.md` §4
        // M1 criterion 3 and lives at the acceptance level, with fixed seeds and tolerances.
        assert!(seen[NodeKind::Combat as usize] > seen[NodeKind::Shop as usize]);
    }

    #[test]
    fn kind_for_roll_matches_the_weight_table() {
        // `inv:§7.3`: 53 combat / 8 elite / 12 rest / 5 shop / 22 unknown, as cumulative bounds.
        let table = [
            (0u32, NodeKind::Combat),
            (52, NodeKind::Combat),
            (53, NodeKind::Elite),
            (60, NodeKind::Elite),
            (61, NodeKind::Rest),
            (72, NodeKind::Rest),
            (73, NodeKind::Shop),
            (77, NodeKind::Shop),
            (78, NodeKind::Unknown),
            (99, NodeKind::Unknown),
        ];
        for (roll, want) in table {
            assert_eq!(kind_for_roll(roll), Some(want), "roll {roll}");
        }
        assert_eq!(kind_for_roll(100), None, "100 is out of the 0..99 range");
    }

    #[test]
    fn same_seed_same_map_and_a_different_seed_a_different_map() {
        assert_eq!(generated(7), generated(7));
        // Not every seed pair differs, so pick a pair that must: the whole point of consuming the
        // `Map` stream is that the seed reaches the layout.
        assert_ne!(generated(7), generated(8));
        assert_ne!(generated(1), generated(2));
    }

    /// **R1b** (`run-layer.md` §3.6): the generated map does not move when an unrelated stream is
    /// pushed. R1a proves this at the draw layer; this is the version that matters to a player.
    #[test]
    fn r1b_pushing_the_potion_stream_does_not_change_the_map() {
        let mut quiet = RunRng::new(11);
        let expected = RunMap::generate(&mut quiet).unwrap();

        let mut noisy = RunRng::new(11);
        for _ in 0..100 {
            noisy.roll(RunStream::Potion, 100).unwrap();
        }
        assert_eq!(noisy.counter(RunStream::Map), 0, "Potion must not advance Map");
        let actual = RunMap::generate(&mut noisy).unwrap();
        assert_eq!(actual, expected);
    }

    // =========================================================================================
    // The rejection half: every rule gets a hand-built illegal map.
    //
    // A generator-only suite cannot express "this map must be refused", and a validator that
    // never looks passes it. These eight mutations each break exactly one rule.
    // =========================================================================================

    #[test]
    fn check_rejects_a_wrong_fixed_floor() {
        let mut map = generated(7);
        map.rows[0].nodes[0].kind = NodeKind::Unknown; // floor 1 must be all combat
        assert!(matches!(
            map.check(),
            Err(MapViolation::FixedFloor { row: 0 })
        ));
    }

    #[test]
    fn check_rejects_an_elite_on_floor_2() {
        let mut map = generated(7);
        let (row, index) = rolled_node(&map, 2);
        map.rows[row].nodes[index].kind = NodeKind::Elite;
        assert!(matches!(
            map.check(),
            Err(MapViolation::TooEarly {
                row: 1,
                index: 0,
                kind: NodeKind::Elite
            })
        ));
    }

    #[test]
    fn check_rejects_a_rest_on_floor_14() {
        let mut map = generated(7);
        map.rows[13].nodes[0].kind = NodeKind::Rest;
        assert!(matches!(
            map.check(),
            Err(MapViolation::RestBeforeBossRest { row: 13 })
        ));
    }

    #[test]
    fn check_rejects_two_adjacent_rest_sites() {
        let mut map = generated(7);
        // Floors 6 and 7 are both rolled, so the kind can be written freely; the edge between
        // them is what override 2 is about.
        let (row, index) = rolled_node(&map, 6);
        map.rows[row].nodes[index].kind = NodeKind::Rest;
        let target = map.rows[row].nodes[index].out_targets()[0] as usize;
        map.rows[row + 1].nodes[target].kind = NodeKind::Rest;
        assert!(matches!(
            map.check(),
            Err(MapViolation::Consecutive {
                row: 5,
                kind: NodeKind::Rest
            })
        ));
    }

    #[test]
    fn check_rejects_two_identical_siblings() {
        let mut map = generated(7);
        // Find a node above a rolled floor with 2+ destinations, whose own kind does not trigger
        // override 2 (combat never does).
        let mut found = None;
        for row in 0..ROWS - 1 {
            if fixed_floor_kind(row as u8 + 2).is_some() {
                continue;
            }
            for index in 0..map.rows[row].len() {
                let node = map.rows[row].nodes[index];
                if node.out_degree() >= 2 && node.kind == NodeKind::Combat {
                    found = Some((row, index, node.out_targets()[0], node.out_targets()[1]));
                    break;
                }
            }
            if found.is_some() {
                break;
            }
        }
        let (row, _, a, b) = found.expect("no combat branch node in this map");
        // Unknown rather than Shop: shop/rest/elite are the three kinds override 2 forbids from
        // repeating along an edge, so writing Shop twice here could trip *that* rule first and the
        // test would then be asserting the wrong one. Unknown appears in no rule but this one.
        map.rows[row + 1].nodes[a as usize].kind = NodeKind::Unknown;
        map.rows[row + 1].nodes[b as usize].kind = NodeKind::Unknown;
        let actual = map.check();
        assert!(
            matches!(actual, Err(MapViolation::Siblings { .. })),
            "expected Siblings, got {actual:?}"
        );
    }

    #[test]
    fn check_rejects_a_crossing() {
        let mut map = generated(7);
        // Row 0 is all combat (fixed), so rewriting its edges cannot trip another rule: the
        // crossing check is the last one, and nothing in front of it looks at these two edges.
        for node in map.rows[0].nodes.iter_mut() {
            node.out_degree = 1;
        }
        map.rows[0].nodes[0].out[0] = 1; // left source -> right target
        map.rows[0].nodes[1].out[0] = 0; // right source -> left target
        assert!(matches!(map.check(), Err(MapViolation::Crossing { row: 0 })));
    }

    #[test]
    fn check_rejects_a_dead_end() {
        let mut map = generated(7);
        map.rows[3].nodes[0].out_degree = 0;
        assert!(matches!(
            map.check(),
            Err(MapViolation::DeadEnd { row: 3, index: 0 })
        ));
    }

    #[test]
    fn check_rejects_an_unrolled_node() {
        let mut map = generated(7);
        let (row, index) = rolled_node(&map, 10);
        map.rows[row].nodes[index].kind = NodeKind::Unassigned;
        assert!(matches!(
            map.check(),
            Err(MapViolation::Unrolled { row: 9, index: 0 })
        ));
    }

    #[test]
    fn check_rejects_an_edge_target_outside_the_next_row() {
        let mut map = generated(7);
        let next = map.rows[1].len() as u8;
        map.rows[0].nodes[0].out[0] = next; // one past the end
        assert_eq!(map.check(), Err(MapViolation::Structure));
    }
}

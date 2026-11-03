"""§188: event effect **lists** (`UnknownRooms[i].Effects0`) + A15 (`Effects0Asc`).

Two things the run layer could not say before:

* **one option, several effects** -- Golden Idol is the canonical case ("relic + curse"); the gap doc
  has named it since §143 as the thing effect lists would unlock;
* **A15 "Unfavorable Events"** (wiki: *"Many events have less positive outcomes and more severe
  consequences"*) -- the same option, a worse list, from ascension 15 up.

Shape: the four `Effect0/Amount0/Effect1/Amount1` cells become **two term lists per option**
(`Effects0`, `Effects0Asc`, `Effects1`, `Effects1Asc`), so the row keeps 10 cells and its 20-byte
stride; `FORMAT_VERSION` still moves (4 -> 5 was §187) to 6, because the meaning of four cells changed.

An element is a plain object `{"Effect": "<word>[:payload]", "Amount": n}` -- the same closed
vocabulary `EventEffect::parse` already owns, one entry per effect.
"""
import io
import os

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def patch(rel, edits, label):
    path = os.path.join(ROOT, rel)
    text = io.open(path, encoding="utf-8").read()
    for old, new in edits:
        if new in text:
            print("  already applied in", rel + ":", label)
            continue
        assert text.count(old) == 1, (label, text.count(old), old[:70])
        text = text.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("patched", rel)


# ---------------------------------------------------------------- 1) the compiler's schema

patch("tools/contentc/rdcfmt.py", [
    (
        """EV_ROW = [
    ("Id", F_STR, 0), ("NameKey", F_STR, 0), ("DescriptionKey", F_STR, 0),
    # Two choices as **fixed cells** (no TERM walk): the effect is a closed vocabulary word.
    ("Label0", F_STR, 0), ("Effect0", F_STR, 0), ("Amount0", F_INT, 0),
    ("Label1", F_STR, 0), ("Effect1", F_STR, 0), ("Amount1", F_INT, 0),
    ("extra", F_TERM, 0),
]""",
        """EV_ROW = [
    ("Id", F_STR, 0), ("NameKey", F_STR, 0), ("DescriptionKey", F_STR, 0),
    # \u00a7188: \u6bcf\u4e2a\u9009\u9879\u7684\u6548\u679c\u662f\u4e00\u4e2a **term \u5217\u8868**\uff08`{Effect, Amount}` \u5143\u7d20\uff09\uff0c\u800c\u4e0d\u662f
    # "\u4e00\u4e2a\u8bcd + \u4e00\u4e2a\u6570"\u3002`...Asc` \u662f A15\uff08"Unfavorable Events"\uff09\u7684\u53d8\u4f53\u3002
    # \u56db\u683c\u6362\u56db\u683c \u21d2 \u884c\u5bbd\u4ecd\u662f 10 \u683c / 20 B\uff0c\u4f46**\u683c\u7684\u542b\u4e49\u53d8\u4e86** \u21d2 FORMAT_VERSION \u52a8\u3002
    ("Label0", F_STR, 0), ("Effects0", F_TERM, 0), ("Effects0Asc", F_TERM, 0),
    ("Label1", F_STR, 0), ("Effects1", F_TERM, 0), ("Effects1Asc", F_TERM, 0),
    ("extra", F_TERM, 0),
]""",
    ),
    (
        """# 5: `EACT` gained `ProgramAsc` + `AscensionMin` (\u00a7187), so that row's stride moved 16 -> 20.
FORMAT_VERSION = 5""",
        """# 5: `EACT` gained `ProgramAsc` + `AscensionMin` (\u00a7187), so that row's stride moved 16 -> 20.
# 6: `EV` replaced its four `Effect*/Amount*` cells with four effect **lists** (\u00a7188); same stride,
#    different meaning.
FORMAT_VERSION = 6""",
    ),
], "rdcfmt")

# ---------------------------------------------------------------- 2) the kernel: schema + parse

patch("kernel/rd-core/src/content.rs", [
    (
        """        ("Label0", F_STR, 0) => label0 => 3,
        ("Effect0", F_STR, 0) => effect0 => 4,
        ("Amount0", F_INT, 0) => amount0 => 5,
        ("Label1", F_STR, 0) => label1 => 6,
        ("Effect1", F_STR, 0) => effect1 => 7,
        ("Amount1", F_INT, 0) => amount1 => 8,""",
        """        ("Label0", F_STR, 0) => label0 => 3,
        /// `Effects0`\uff08term\uff1a`[{Effect, Amount}]\`\uff0c\u00a7188\uff09\u3002
        ("Effects0", F_TERM, 0) => effects0 => 4,
        /// `Effects0Asc`\uff08term\uff09\uff1aA15 \u7684\u53d8\u4f53\uff08wiki: *Unfavorable Events*\uff09\u3002
        ("Effects0Asc", F_TERM, 0) => effects0_asc => 5,
        ("Label1", F_STR, 0) => label1 => 6,
        ("Effects1", F_TERM, 0) => effects1 => 7,
        ("Effects1Asc", F_TERM, 0) => effects1_asc => 8,""",
    ),
    (
        """pub struct EventChoice<'a> {
    /// What the button says.
    pub label: &'a str,
    /// `heal` / `gold` / `damage` / `max_hp` / `nothing` -- a **closed** vocabulary, because the run
    /// layer has no program interpreter.
    pub effect: &'a str,
    /// How much of it.
    pub amount: i16,
}""",
        """pub struct EventChoice<'a> {
    /// What the button says.
    pub label: &'a str,
    /// The effects, in order (\u00a7188). `heal` / `gold` / `damage` / `max_hp` / `nothing` /
    /// `remove_card` / `upgrade_card` / `transform_card` / `curse:<id>` / `relic:<id>` -- a
    /// **closed** vocabulary, because the run layer has no program interpreter.
    pub effects: [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    /// How many of `effects` are real.
    pub count: u8,
    /// The A15 variant (wiki: *Unfavorable Events*). `asc_count == 0` = none: the base list applies
    /// at every level.
    pub asc: [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    /// How many of `asc` are real.
    pub asc_count: u8,
}

impl<'a> EventChoice<'a> {
    /// The list that applies at `ascension`: the A15 variant when the row has one, else the base.
    #[must_use]
    pub fn effects_at(&self, ascension: u8, a15: u8) -> &[EffectSpec<'a>] {
        if self.asc_count > 0 && ascension >= a15 {
            &self.asc[..usize::from(self.asc_count)]
        } else {
            &self.effects[..usize::from(self.count)]
        }
    }
}

/// One event effect: a closed-vocabulary word (with an optional `:` payload) and its amount.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EffectSpec<'a> {
    pub effect: &'a str,
    pub amount: i16,
}

impl Empty for EffectSpec<'_> {
    const EMPTY: Self = Self {
        effect: "nothing",
        amount: 0,
    };
}""",
    ),
    (
        """        let mut choices = [EventChoice {
            label: "",
            effect: "nothing",
            amount: 0,
        }; 2];
        for (slot, (label_cell, effect_cell, amount_cell)) in [
            (row.label0(), row.effect0(), row.amount0()),
            (row.label1(), row.effect1(), row.amount1()),
        ]
        .into_iter()
        .enumerate()
        {
            choices[slot] = EventChoice {
                label: self.string(label_cell).unwrap_or(""),
                effect: self.string(effect_cell).unwrap_or("nothing"),
                amount: self.amount(amount_cell),
            };
        }
        Some((id, text, choices))""",
        """        let mut choices = [EventChoice {
            label: "",
            effects: [EffectSpec::EMPTY; MAX_EVENT_EFFECTS],
            count: 0,
            asc: [EffectSpec::EMPTY; MAX_EVENT_EFFECTS],
            asc_count: 0,
        }; 2];
        for (slot, (label_cell, base_cell, asc_cell)) in [
            (row.label0(), row.effects0(), row.effects0_asc()),
            (row.label1(), row.effects1(), row.effects1_asc()),
        ]
        .into_iter()
        .enumerate()
        {
            let mut base = [EffectSpec::EMPTY; MAX_EVENT_EFFECTS];
            let count = self.effect_list(base_cell, &mut base)?;
            let mut asc = [EffectSpec::EMPTY; MAX_EVENT_EFFECTS];
            let asc_count = self.effect_list(asc_cell, &mut asc)?;
            choices[slot] = EventChoice {
                label: self.string(label_cell).unwrap_or(""),
                effects: base,
                count,
                asc,
                asc_count,
            };
        }
        Some((id, text, choices))""",
    ),
], "content-event")

print("part 1 done")

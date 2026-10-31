"""§161.3 negative controls. `python native/negctl_161_choice.py <which> [--restore]`.

Three guards, three broken versions. Each broken version is a **plausible** shape, not "delete the
check": deleting a bound turns a refusal into a panic, and a panic proves nothing about the guard.

  vocab    the two choice atoms dropped from `rd_run_potion_effect`'s `known` list
  atomic   `resolve_choice`'s duplicate test moved to *after* the cards are moved
  trunc    `choice_legal` stopping at the buffer instead of refusing
"""
import io
import sys

RUN = "kernel/rd-wasm/src/run.rs"
STATE = "kernel/rd-core/src/state.rs"

# ---- vocab ------------------------------------------------------------------------------------
VOCAB_OK = """                "max_hp"
                    | "potion_fill"
                    | "choice_hand_exhaust"
                    | "choice_hand_discard_draw"
            )"""
VOCAB_BROKEN = """                "max_hp" | "potion_fill"
            )"""

# ---- atomicity --------------------------------------------------------------------------------
ATOMIC_OK = """        // (a) 每张都在来源牌区里，而且不重复。重复直接比 id —— 卡实例 id 在整场里唯一，
        //     所以「同一个 id 出现两次」就是「同一张牌被选了两次」，不需要第二张表。
        let mut slots = [CardSlot::from_index(0); MAX_CARDS_PER_ZONE];
        for (index, id) in picks.iter().enumerate() {
            let Some((zone, slot)) = self.find_card(&choice.chooser, id) else {
                return Err(ChoiceError::NotInSource);
            };
            if zone != source {
                return Err(ChoiceError::NotInSource);
            }
            if picks[..index].iter().any(|earlier| earlier == id) {
                return Err(ChoiceError::Duplicate);
            }
            slots[index] = slot;
        }"""
ATOMIC_BROKEN = """        // (a) **BROKEN CONTROL**: 重复检查被挪到了搬牌之后。这正是「半途而不是拒绝」的形状：
        //     第一张真的动了，然后才报 Duplicate —— 于是这个动作既不是成功也不是拒绝。
        let mut slots = [CardSlot::from_index(0); MAX_CARDS_PER_ZONE];
        for (index, id) in picks.iter().enumerate() {
            let Some((zone, slot)) = self.find_card(&choice.chooser, id) else {
                return Err(ChoiceError::NotInSource);
            };
            if zone != source {
                return Err(ChoiceError::NotInSource);
            }
            slots[index] = slot;
        }"""

ATOMIC_TAIL_OK = """        for &slot in &slots[..picked] {
            self.move_card(&choice.chooser, source, destination, slot, ZonePlacement::Bottom)?;
        }
        self.choice = None;"""
ATOMIC_TAIL_BROKEN = """        for &slot in &slots[..picked] {
            self.move_card(&choice.chooser, source, destination, slot, ZonePlacement::Bottom)?;
        }
        if picks.iter().enumerate().any(|(i, id)| picks[..i].iter().any(|e| e == id)) {
            return Err(ChoiceError::Duplicate);
        }
        self.choice = None;"""

# ---- truncation -------------------------------------------------------------------------------
TRUNC_OK = """            if count == out.len() {
                return Err(ChoiceError::Capacity(CapacityError::Full(
                    Container::ChoiceOptions,
                )));
            }"""
TRUNC_BROKEN = """            if count == out.len() {
                break;
            }"""


def patch(path, old, new, restore):
    text = io.open(path, encoding="utf-8").read()
    a, b = (new, old) if restore else (old, new)
    assert text.count(a) == 1, (path, text.count(a), a[:60])
    io.open(path, "w", encoding="utf-8", newline="").write(text.replace(a, b))


def main():
    which = sys.argv[1]
    restore = "--restore" in sys.argv
    if which == "vocab":
        patch(RUN, VOCAB_OK, VOCAB_BROKEN, restore)
    elif which == "atomic":
        patch(STATE, ATOMIC_OK, ATOMIC_BROKEN, restore)
        patch(STATE, ATOMIC_TAIL_OK, ATOMIC_TAIL_BROKEN, restore)
    elif which == "trunc":
        patch(STATE, TRUNC_OK, TRUNC_BROKEN, restore)
    else:
        raise SystemExit(f"unknown control {which!r}")
    print(f"{which}: {'restored' if restore else 'broken'}")


if __name__ == "__main__":
    main()

"""§163.1: two call-site fixes in `hash.rs` (the `start_offers` shape and the RNG probe)."""
import io

PATH = "kernel/rd-run/src/hash.rs"

OLD_OFFERS = '''    for slot in state.start_offers() {
        writer.str("offer=").u32(u32::from(slot)).str("\\n");
    }'''

NEW_OFFERS = '''    // `start_offers()` 只在**开局祝福**那一段有值（`Option<[StartOffer; 2]>`）—— 所以"没有"要写成
    // `offers=none`，而不是两行零（否则"还没开局"和"祝福是 0 号"会哈希成同一个）。
    match state.start_offers() {
        None => {
            writer.str("offers=none\\n");
        }
        Some(offers) => {
            for slot in offers {
                writer.str("offer=").u32(u32::from(slot)).str("\\n");
            }
        }
    }'''

OLD_RNG = '''        let mut rng = run.rng();
        rng.draw(RunStream::Potion).expect("draw");
        run.set_rng(rng);'''

NEW_RNG = '''        // 走一次真实的随机：`Potion` 那条流推进一步，其余六条不动。
        let mut rng = *run.rng();
        rng.draw(RunStream::Potion);
        run.replace_rng(rng);'''

text = io.open(PATH, encoding="utf-8").read()
assert text.count(OLD_OFFERS) == 1, text.count(OLD_OFFERS)
text = text.replace(OLD_OFFERS, NEW_OFFERS)
assert text.count(OLD_RNG) == 1, text.count(OLD_RNG)
text = text.replace(OLD_RNG, NEW_RNG)
io.open(PATH, "w", encoding="utf-8", newline="").write(text)
print("both call sites fixed")

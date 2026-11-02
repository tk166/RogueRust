"""P1-1 (2): read the ids from the **tables**, not from `IDX`.

`IDX` does not carry every entity kind (potions and events are found through their own lists -- the
same reason `Table::from_entity_kind(EK_EVENT)` is `None`). The first rewrite scanned `IDX` and found
no potion at all, which is the test telling me it was reading the wrong table.

`Content::potion_count()/potion()` and `rows(Table::Relic)` are exactly what `rd-wasm`'s pools use, so
the fixture is built from the same source the game is.
"""
import io

PATH = "kernel/rd-run/src/hash.rs"

OLD = """        // 镜像里最长的卡 / 药水 / 每件遗物：**从内容里取**，不抄字符串（抄的那份会腐烂）。
        let mut longest_card = "";
        let mut longest_potion = "";
        let mut relics: std::vec::Vec<&str> = std::vec::Vec::new();
        for index in 0..content.id_count() {
            let Some(entry) = content.id_entry(index) else {
                continue;
            };
            match entry.entity_kind {
                rd_core::content::EK_CARD if entry.id.len() > longest_card.len() => {
                    longest_card = entry.id;
                }
                rd_core::content::EK_POTION if entry.id.len() > longest_potion.len() => {
                    longest_potion = entry.id;
                }
                rd_core::content::EK_RELIC => {
                    if !relics.contains(&entry.id) && RunState::relic_effect(entry.id).is_some() {
                        relics.push(entry.id);
                    }
                }
                _ => {}
            }
        }
        assert!(!longest_card.is_empty(), "no card in the image");
        assert!(!longest_potion.is_empty(), "no potion in the image");
        assert!(!relics.is_empty(), "no relic in the image that the rule table knows");"""

NEW = """        // 镜像里最长的卡 / 药水 / 每件遗物：**从表里取**，不抄字符串，也不走 `IDX`
        // （`IDX` 不含每种实体 —— 药水与事件各有自己的列表，见 `Table::from_entity_kind`）。
        let mut longest_card = "";
        let mut index = 0u32;
        while let Some(row) = content.row(rd_core::content::Table::Card, index) {
            if let Some(card) = rd_core::content::CardRow::new(row) {
                if let Some(id) = content.string(card.id()) {
                    if id.len() > longest_card.len() {
                        longest_card = id;
                    }
                }
            }
            index += 1;
        }

        let mut longest_potion = "";
        for index in 0..content.potion_count() {
            let Some(potion) = content.potion(index) else {
                continue;
            };
            if potion.id.len() > longest_potion.len() {
                longest_potion = potion.id;
            }
        }

        let mut relics: std::vec::Vec<&str> = std::vec::Vec::new();
        let mut index = 0u32;
        while let Some(row) = content.row(rd_core::content::Table::Relic, index) {
            if let Some(relic) = rd_core::content::RelRow::new(row) {
                if let Some(id) = content.string(relic.id()) {
                    if RunState::relic_effect(id).is_some() && !relics.contains(&id) {
                        relics.push(id);
                    }
                }
            }
            index += 1;
        }

        assert!(!longest_card.is_empty(), "no card in the image");
        assert!(!longest_potion.is_empty(), "no potion in the image");
        assert!(!relics.is_empty(), "no relic in the image that the rule table knows");"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD) == 1, text.count(OLD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(OLD, NEW))
    print("ids come from the tables")


if __name__ == "__main__":
    main()

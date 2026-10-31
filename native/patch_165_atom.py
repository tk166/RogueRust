"""rd-wasm: the `choice_offered:<tag>` atom (Attack / Skill Potion).

The pool is filtered **here** because the tag lives in the content; the three distinct picks come
from the **run** because it owns the streams. If the filtered pool cannot supply three, the potion
is **refused without being consumed** -- a question with two options would be a smaller, quieter
version of the game's own rule, and one with zero would be an unanswerable modal.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """        "choice_discard_to_hand" => {"""

ATOM = '''        other if other.starts_with("choice_offered:") => {
            // §161.5: Attack / Skill Potion -- "choose 1 of 3 random <type> cards to add to your
            // hand; it costs 0 this turn".
            let Some((_, tag)) = other.split_once(':') else {
                return refuse("`choice_offered` 缺少 `:<tag>`");
            };
            let image = content();
            // The pool is**内容**的事：哪些牌算 Attack 写在 `CARD.Tags` 里。
            let mut pool: Vec<rd_run::state::PoolCard<'static>> = Vec::new();
            for index in 0..image.card_count() {
                let Some(row) = image.card(index) else {
                    continue;
                };
                if image.card_has_tag(row.id, tag) != Some(true) {
                    continue;
                }
                let rarity = match rd_run::state::Rarity::from_name(row.rarity) {
                    Some(rarity) => rarity,
                    // 一个认不出的稀有度会让"这张牌该不该在池子里"变成一个猜 —— 拒绝。
                    None => {
                        return refuse(&std::format!("`{}` 的稀有度认不出来", row.id));
                    }
                };
                pool.push(rd_run::state::PoolCard {
                    id: row.id,
                    rarity,
                });
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
        "choice_discard_to_hand" => {'''

CONST = """
/// §161.5：候选**三张**是规则（wiki 的三瓶药都写 "1 of 3"），所以它是常量而不是参数。
///
/// 写成 `rd_core::state::MAX_CHOICE_OFFERED` 的名字会让"三"看起来像个容量上限 ——
/// 它其实是这条规则的**全部内容**，改它就得改药水的说明文字。
const MAX_OFFERED: usize = 3;
"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "choice_offered:" not in text, "already inserted"
    text = text.replace(ANCHOR, ATOM)

    anchor2 = "/// Is this potion atom about a **fight**? (§158)"
    assert text.count(anchor2) == 1
    text = text.replace(anchor2, CONST.strip() + "\n\n" + anchor2)

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("run.rs: choice_offered atom")


if __name__ == "__main__":
    main()

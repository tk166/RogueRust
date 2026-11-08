"""§292：`rd-wasm` 侧的全部改动（幂等重放）。

1. `settle_pickup_debts()` —— 拾取欠账（`calling_bell` / `cauldron`）的兑现点；
2. 三个入口调用它（宝箱 / 取奖励遗物 / 买遗物）；
3. `sacred_bark` 的药水倍率（`rd_env_use_potion` 里那一处 `amount`）；
4. `DeckChange::Duplicate` 的四个 ABI 映射（穷尽 `match`）。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

SETTLE = '''/// §292：兑现拾取时**欠着**的遗物与药水（`calling_bell` 的 3 件、`cauldron` 的 5 瓶）。
///
/// 为什么欠账在 wasm 兑现：`push_relic`（`rd-run`）只拿得到**卡池**（拾取类遗物要看牌的
/// 类型与 `+` 行），而遗物池与药水池都在这一层 —— 它是唯一知道内容镜像的地方。
///
/// 池子空了 / 腰带满了都**不是错误**：欠账留在 `RunState` 上（它进 run hash），下一站再试。
/// ⚠️ 兑现点必须是**所有**会 `push_relic` 的入口，漏一个就是"记了欠账但没人付" ——
/// 症状只有"少了几件遗物"，没有任何东西会报错。
fn settle_pickup_debts() {
    let image = content();
    let relics = relic_pool(image);
    let cards = match full_pool(image, false) {
        Ok(pool) => pool,
        Err(_) => return,
    };
    let potions = potion_pool_of(image);
    // ⚠️ 运行层在 `run_slot()` 里（`session.state` 是**战斗**状态，不是这一局）。
    let Some(run) = run_slot().as_mut() else {
        return;
    };
    while run.state.pickup_relics() > 0 {
        let picked = match run.state.pick_relic(rd_run::streams::RunStream::Chest, &relics) {
            Ok(id) => id,
            Err(_) => break,
        };
        if picked.as_str().is_empty() {
            break;
        }
        match run.state.push_relic(picked.as_str(), &cards) {
            Ok(()) => run.state.take_pickup_relic(),
            // 给不进去（腰带满了 / 内核不认识）⇒ **不递减**：欠账留着。
            Err(_) => break,
        }
    }
    while run.state.pickup_potions() > 0 && run.state.potion_room() {
        let picked = match run.state.pick_potion(rd_run::streams::RunStream::Potion, &potions) {
            Ok(id) => id,
            Err(_) => break,
        };
        if picked.as_str().is_empty() {
            break;
        }
        match run.state.push_potion(picked.as_str()) {
            Ok(()) => run.state.take_pickup_potion(),
            Err(_) => break,
        }
    }
}

'''


def patch(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:100])
    return text.replace(old, new)


def main():
    s = io.open(RUN, encoding='utf-8').read()

    # ── 1. 兑现函数（挂在 `potion_pool_of` 之前：它要用那两个池）
    anchor = '/// Every potion in the image, with the rarity its `POT` row declares'
    assert s.count(anchor) == 1
    s = s.replace(anchor, SETTLE + anchor)

    # ── 2. 三个入口兑现
    s = patch(s, '''    let outcome = session.state.open_chest(&pool, &relics).map(|_| 0i32);
    finish(session, outcome)''', '''    let outcome = session.state.open_chest(&pool, &relics).map(|_| 0i32);
    // §292：宝箱里的遗物可能带欠账（`calling_bell` / `cauldron`）。
    settle_pickup_debts();
    finish(session, outcome)''')

    s = patch(s, '''    let outcome = session.state.take_relic(&pool).map(|_| 0i32);
    finish(session, outcome)''', '''    let outcome = session.state.take_relic(&pool).map(|_| 0i32);
    // §292：同上。
    settle_pickup_debts();
    finish(session, outcome)''')

    s = patch(s, '''    let outcome = session
        .state
        .buy_relic(slot as usize, &pool, &relics)
        .map(|_| 0i32);
    finish(session, outcome)''', '''    let outcome = session
        .state
        .buy_relic(slot as usize, &pool, &relics)
        .map(|_| 0i32);
    // §292：商人卖的遗物也可能带欠账。
    settle_pickup_debts();
    finish(session, outcome)''')

    # ── 3. `sacred_bark`：药水数值倍率（一个 `amount`，两个消费者共用）
    s = patch(s, '''    let amount = i32::from(potion.amount);''', '''    // §292：`sacred_bark` —— "Double the effectiveness of potions"。乘在**这一处**：下面的
    // `use_run_atoms` 与战斗层原子读的都是同一个 `amount`，所以"回 25 血"与"造成 12 伤害"
    // 不会一半被放大、另一半没有。`POT` 行本身不动（引擎不改内容）。
    let percent = run_slot()
        .as_ref()
        .map_or(100, |run| run.state.potion_effect_percent());
    let amount = i32::from(potion.amount) * percent / 100;''')

    # ── 4. `DeckChange::Duplicate` 的 ABI 映射
    s = patch(s, '''        // §274：`astrolabe` 会用到它，但事件从不用它 —— 给一个明确的值而不是 panic。
        Some(DeckChange::TransformAndUpgrade) => 4,
        None => 0,''', '''        // §274：`astrolabe` 会用到它，但事件从不用它 —— 给一个明确的值而不是 panic。
        Some(DeckChange::TransformAndUpgrade) => 4,
        // §292：`dollys_mirror`（只在拾取时用），同上。
        Some(DeckChange::Duplicate) => 5,
        None => 0,''')

    s = patch(s, '''        Some(DeckChange::TransformAndUpgrade) => 4,
    }
}''', '''        Some(DeckChange::TransformAndUpgrade) => 4,
        // §292：`dollys_mirror`。
        Some(DeckChange::Duplicate) => 5,
    }
}''')

    s = patch(s, '''        // §274：恩惠不用它（`astrolabe` 才用），但映射要穷尽。
        BlessingFollowUp::Deck(DeckChange::TransformAndUpgrade) => 4,
    }''', '''        // §274：恩惠不用它（`astrolabe` 才用），但映射要穷尽。
        BlessingFollowUp::Deck(DeckChange::TransformAndUpgrade) => 4,
        // §292：`dollys_mirror`，同上。
        BlessingFollowUp::Deck(DeckChange::Duplicate) => 5,
    }''')

    s = patch(s, '''        // §274：恩惠不用它（`astrolabe` 才用），但映射要穷尽。
        Some(BlessingFollowUp::Deck(DeckChange::TransformAndUpgrade)) => 4,
        Some(BlessingFollowUp::None) | Some(BlessingFollowUp::GainThreeCards) | None => 0,''',
                 '''        // §274：恩惠不用它（`astrolabe` 才用），但映射要穷尽。
        Some(BlessingFollowUp::Deck(DeckChange::TransformAndUpgrade)) => 4,
        // §292：`dollys_mirror`，同上。
        Some(BlessingFollowUp::Deck(DeckChange::Duplicate)) => 5,
        Some(BlessingFollowUp::None) | Some(BlessingFollowUp::GainThreeCards) | None => 0,''')

    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('wasm side replayed')


main()

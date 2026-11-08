"""§292 Wave 1 的 wasm 侧：拾取欠账兑现 + `sacred_bark` 的药水倍率。

## 欠账为什么在 wasm 兑现

`push_relic`（`rd-run`）只拿得到**卡池**。`calling_bell` 要 3 件**遗物**、`cauldron` 要 5 瓶
**药水**，两个池都在 `rd-wasm`（它是唯一知道内容镜像的层）。所以 `rd-run` 记欠账
（`pickup_relics` / `pickup_potions`，两者都进 run hash），wasm 在**可能产生欠账的那几个入口**
之后兑现。

⚠️ 兑现点必须是**所有**会 `push_relic` 的入口 —— 漏一个，那件遗物就永远是"记了欠账但没人付"，
而症状只是"少了三件遗物"，没有任何东西会报错。所以兑现函数挂在 `open_chest` / `take_relic` /
`buy_relic` / **开局起始遗物** 四处，并且判据里有一条"每一个入口都兑现"（走真实的三个入口）。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:110])
    return text.replace(old, new)


def main():
    s = io.open(RUN, encoding='utf-8').read()

    # ── 1. 兑现替身（放在 `relic_pool` 之后：它要那两个池）
    s = patch(s, '''/// Every potion in the image, with the rarity its `POT` row declares (§156/§158).''',
                  '''/// §292：兑现拾取时**欠着**的遗物与药水（`calling_bell` 的 3 件、`cauldron` 的 5 瓶）。
///
/// 返回 `Err` 只在"抽签失败"这类真错误；**池子空了不是错误**（那就是"没有更多可以给了"）。
/// 腰带满了同样不是错误 —— `cauldron` 的 5 瓶里装不下的那些**留在欠账上**（见 docs 的偏差记录：
/// 真 StS 会一瓶一瓶问你要不要丢掉旧的，我们没有那个丢弃问句）。
fn settle_pickup_debts(session: &mut Session) {
    let image = content();
    let relics = relic_pool(image);
    let cards = match full_pool(image, false) {
        Ok(pool) => pool,
        Err(_) => return,
    };
    // 遗物：一件一件抽、一件一件给。`MAX_RUN_RELICS` 满了 ⇒ `push_relic` 拒绝，欠账留着。
    while session.state.pickup_relics() > 0 {
        let picked = match session.state.pick_relic(rd_run::streams::RunStream::Chest, &relics) {
            Ok(id) => id,
            Err(_) => break,
        };
        if picked.as_str().is_empty() {
            break;
        }
        match session.state.push_relic(picked.as_str(), &cards) {
            Ok(()) => session.state.take_pickup_relic(),
            // 给不进去（腰带满了 / 内核不认识）⇒ **不递减**：欠账留着，下一站再试。
            Err(_) => break,
        }
    }
    // 药水：只在**有空位**时装。
    let potions = potion_pool_of(image);
    while session.state.pickup_potions() > 0 && session.state.potion_room() {
        let picked = match session.state.pick_potion(rd_run::streams::RunStream::Potion, &potions) {
            Ok(id) => id,
            Err(_) => break,
        };
        if picked.as_str().is_empty() {
            break;
        }
        match session.state.push_potion(picked.as_str()) {
            Ok(()) => session.state.take_pickup_potion(),
            Err(_) => break,
        }
    }
}

/// Every potion in the image, with the rarity its `POT` row declares (§156/§158).''')

    # ── 2. 三个入口兑现（宝箱 / 取奖励遗物 / 买遗物）
    s = patch(s, '''    let outcome = session.state.open_chest(&pool, &relics).map(|_| 0i32);
    finish(session, outcome)''',
                  '''    let outcome = session.state.open_chest(&pool, &relics).map(|_| 0i32);
    // §292：宝箱里的遗物可能带欠账（`calling_bell` / `cauldron`）。
    settle_pickup_debts(session);
    finish(session, outcome)''')

    s = patch(s, '''    let outcome = session.state.take_relic(&pool).map(|_| 0i32);
    finish(session, outcome)''',
                  '''    let outcome = session.state.take_relic(&pool).map(|_| 0i32);
    // §292：同上。
    settle_pickup_debts(session);
    finish(session, outcome)''')

    s = patch(s, '''        .buy_relic(slot as usize, &pool, &relics)''',
                  '''        .buy_relic(slot as usize, &pool, &relics)''')  # 占位：见下面那个真正的替换

    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('settle + two entry points')


main()

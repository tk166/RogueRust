"""§293：wasm 的 8 个导出 + 三件遗物的内容行。

导出（页面要能画"挑一张加入牌组"、并且能点）：

| 导出 | 作用 |
|---|---|
| `rd_run_pickup_add` | 还欠几张（0 = 不欠，-1 = 没有一局） |
| `rd_run_pickup_offer_count` | 这一手有几张候选 |
| `rd_run_pickup_offer_title_len/into` | 候选的显示名（页面上那一行） |
| `rd_run_pickup_add_card` | 挑第 `slot` 张加进牌组 |
| `rd_run_pickup_add_skip` | 跳过一次 |
| `rd_run_pickup_add_max_hp` | `singing_bowl`：换成 +2 上限 |
| `rd_run_take_max_hp_instead` | `singing_bowl`：奖励屏上不拿牌、改拿 +2 上限 |
"""
import io
import json

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
GATE = 'D:/Vibe/sts-tui/native/sts_content_check.py'
SMOKE = 'D:/Vibe/sts-tui/web/smoke.mjs'

EXPORTS = r'''
/// §293：还欠着几张牌要加进牌组（`orrery` 的 5、`tiny_house` 的 1）。`-1` = 没有一局。
#[no_mangle]
pub extern "C" fn rd_run_pickup_add() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |run| i32::from(run.state.pickup_add()))
}

/// §293：这一手有几张候选（0 = 没有欠账）。
#[no_mangle]
pub extern "C" fn rd_run_pickup_offer_count() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |run| run.state.pickup_offer().len() as i32)
}

/// §293：候选 `slot` 的**显示名**长度（内容里的 `CARD` 行标题）。
#[no_mangle]
pub extern "C" fn rd_run_pickup_offer_title_len(slot: i32) -> i32 {
    if slot < 0 {
        return -1;
    }
    let Some(run) = run_slot().as_ref() else {
        return -1;
    };
    let Some(id) = run.state.pickup_offer().get(slot as usize) else {
        return -1;
    };
    match crate::card_title(content(), id.as_str()) {
        Some(title) => title.len() as i32,
        None => -1,
    }
}

/// §293：把候选 `slot` 的显示名写进 `ptr`（`rd_run_pickup_offer_title_len(slot)` 个字节）。
///
/// # Safety
///
/// `ptr` must point at that many writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_pickup_offer_title_into(slot: i32, ptr: *mut u8) -> i32 {
    if slot < 0 || ptr.is_null() {
        return -1;
    }
    let Some(run) = run_slot().as_ref() else {
        return -1;
    };
    let Some(id) = run.state.pickup_offer().get(slot as usize) else {
        return -1;
    };
    let Some(title) = crate::card_title(content(), id.as_str()) else {
        return -1;
    };
    let bytes = title.as_bytes();
    std::ptr::copy_nonoverlapping(bytes.as_ptr(), ptr, bytes.len());
    bytes.len() as i32
}

/// §293：把候选 `slot` 加进牌组。
#[no_mangle]
pub extern "C" fn rd_run_pickup_add_card(slot: i32) -> i32 {
    if slot < 0 {
        return -1;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_PICKUP_ADD_CARD, slot, -1, "");
    let pool = match full_pool(content(), false) {
        Ok(pool) => pool,
        Err(_) => return -1,
    };
    let outcome = session
        .state
        .pickup_add_card(slot as usize, &pool)
        .map(|_| 0i32);
    finish(session, outcome)
}

/// §293：跳过这一次（`orrery` 的每一次奖励屏都可以跳过）。
#[no_mangle]
pub extern "C" fn rd_run_pickup_add_skip() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_PICKUP_ADD_SKIP, -1, -1, "");
    let outcome = session.state.pickup_add_skip().map(|_| 0i32);
    finish(session, outcome)
}

/// §293：`singing_bowl` —— 把这一次"加牌"换成 +2 上限。
#[no_mangle]
pub extern "C" fn rd_run_pickup_add_max_hp() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_PICKUP_ADD_MAX_HP, -1, -1, "");
    let outcome = session.state.pickup_add_max_hp().map(|_| 0i32);
    finish(session, outcome)
}

/// §293：`singing_bowl` 在**战斗奖励屏**上的那一条 —— 不拿牌，改拿 +2 上限。
#[no_mangle]
pub extern "C" fn rd_run_take_max_hp_instead() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_TAKE_MAX_HP, -1, -1, "");
    let outcome = session.state.take_max_hp_instead().map(|_| 0i32);
    finish(session, outcome)
}
'''

RELICS = {
    'orrery': ('Orrery', 'Shop'),
    'tiny_house': ('Tiny House', 'Boss'),
    'singing_bowl': ('Singing Bowl', 'Uncommon'),
}


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── 1. 日志种类（脚本回放要能记这四次动作）
    s = io.open(RUN, encoding='utf-8').read()
    anchor = '    K_GRANT_POTION => "grant_potion",'
    assert s.count(anchor) == 1, s.count(anchor)
    s = s.replace(anchor, anchor + '''
    // §293：加牌问句的四个动作。它们都改运行层（牌组/上限），所以必须进脚本 ——
    // 否则"调用之后的哈希"会把它们的效果算进去，而回放里没人做这件事。
    K_PICKUP_ADD_CARD => "pickup_add_card",
    K_PICKUP_ADD_SKIP => "pickup_add_skip",
    K_PICKUP_ADD_MAX_HP => "pickup_add_max_hp",
    K_TAKE_MAX_HP => "take_max_hp_instead",''')
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('log kinds')

    # ── 2. 常量（与 K_GRANT_POTION 那一组放一起）
    s = io.open(RUN, encoding='utf-8').read()
    anchor = 'const K_GRANT_POTION: u8 ='
    assert s.count(anchor) == 1, s.count(anchor)
    line_end = s.index('\n', s.index(anchor))
    # 找这一组的最后一行常量（连续 `const K_...: u8 =`）
    tail = s[line_end:].split('\n')
    count = 0
    for line in tail:
        if line.startswith('const K_') and ': u8 =' in line:
            count += 1
        elif line.strip() == '' and count < 2:
            continue
        else:
            break
    insert_at = line_end
    for line in tail[:count]:
        insert_at += len(line) + 1
    block = '''
/// §293：加牌问句的四个动作（见 `LOG_KINDS`）。
const K_PICKUP_ADD_CARD: u8 = 0x5a;
const K_PICKUP_ADD_SKIP: u8 = 0x5b;
const K_PICKUP_ADD_MAX_HP: u8 = 0x5c;
const K_TAKE_MAX_HP: u8 = 0x5d;'''
    s = s[:insert_at] + block + s[insert_at:]
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('log constants')

    # ── 3. 导出本体（挂在 `rd_run_pickup_card` 之后）
    s = io.open(RUN, encoding='utf-8').read()
    anchor = '''/// §274：兑现一次拾取时的牌组编辑（牌组下标 `index`）。'''
    assert s.count(anchor) == 1
    s = s.replace(anchor, EXPORTS + '\n' + anchor)
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('exports')

    # ── 4. 内容三件 + 门的第二意见 + smoke 的导出对账
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    have = {row['Id'] for row in doc['Relics']}
    for relic_id, (name, rarity) in RELICS.items():
        if relic_id in have:
            continue
        doc['Relics'].append({
            'Id': relic_id,
            'DisplayName': name,
            'RunPrograms': None,
            'CombatRules': None,
            'Rarity': rarity,
        })
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content relics', len(doc['Relics']))

    patch(GATE, '''                      "dollys_mirror", "nloths_gift", "sacred_bark",''',
                '''                      "dollys_mirror", "nloths_gift", "sacred_bark",
                      # §293：加牌的三件（`orrery` / `tiny_house` / `singing_bowl`）。
                      "orrery", "tiny_house", "singing_bowl",''')

    patch(SMOKE, '''  "rd_run_pickup_picks", "rd_run_pickup_change", "rd_run_pickup_card",''',
                 '''  "rd_run_pickup_picks", "rd_run_pickup_change", "rd_run_pickup_card",
  // §293
  "rd_run_pickup_add", "rd_run_pickup_offer_count",
  "rd_run_pickup_offer_title_len", "rd_run_pickup_offer_title_into",
  "rd_run_pickup_add_card", "rd_run_pickup_add_skip", "rd_run_pickup_add_max_hp",
  "rd_run_take_max_hp_instead",''')


main()

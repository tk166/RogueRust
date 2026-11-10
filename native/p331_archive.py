"""§331：把遗物候选写进**存档**（`state-fields` 闸门 §308 要求每个字段都进存档与指纹）。

写法照 §320 的卡牌候选：一个长度字节 + 每个候选一个 `RunId`。读回来时验"长度在范围内、
已声明的槽非空"—— 与 `deck` 的尾槽同一条纪律。
"""

import io

PATH = 'kernel/rd-run/src/state/archive.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ① 写侧：紧跟卡牌候选之后。
t = sub(t, """    // §320：事件候选列表（`0` = 没有候选，也是绝大多数时候）。
    writer.byte(state.event_offer_len() as u8)?;
    for slot in 0..state.event_offer_len() {
        let id = state.event_offer_card(slot).unwrap_or("");
        writer.id(RunId::new(id).map_err(|_| ArchiveError::BadField("event_offer"))?)?;
    }""",
        """    // §320：事件候选列表（`0` = 没有候选，也是绝大多数时候）。
    writer.byte(state.event_offer_len() as u8)?;
    for slot in 0..state.event_offer_len() {
        let id = state.event_offer_card(slot).unwrap_or("");
        writer.id(RunId::new(id).map_err(|_| ArchiveError::BadField("event_offer"))?)?;
    }
    // §331：事件掷出的**遗物候选**（`N'loth` 的两件）。与上面同一形状：长度 + 每个一件。
    let relic_offer_len = (0..MAX_EVENT_RELIC_OFFER)
        .filter(|slot| state.event_relic_offer(*slot).is_some())
        .count();
    writer.byte(relic_offer_len as u8)?;
    for slot in 0..relic_offer_len {
        let id = state.event_relic_offer(slot).unwrap_or("");
        writer.id(RunId::new(id).map_err(|_| ArchiveError::BadField("event_relic_offer"))?)?;
    }""",
        'write')

# ② 读侧：紧跟卡牌候选之后。
t = sub(t, """    let mut offer_ids = [RunId::EMPTY; MAX_EVENT_OFFER];
    for slot in offer_ids.iter_mut().take(offer_len as usize) {
        *slot = reader.id()?;
    }""",
        """    let mut offer_ids = [RunId::EMPTY; MAX_EVENT_OFFER];
    for slot in offer_ids.iter_mut().take(offer_len as usize) {
        *slot = reader.id()?;
    }
    // §331：遗物候选（与上面同一条纪律：长度在范围内、已声明的槽非空）。
    let relic_offer_len = reader.byte()?;
    if relic_offer_len as usize > MAX_EVENT_RELIC_OFFER {
        return Err(ArchiveError::BadField("event_relic_offer_len"));
    }
    let mut relic_offer_ids = [RunId::EMPTY; MAX_EVENT_RELIC_OFFER];
    for slot in relic_offer_ids.iter_mut().take(relic_offer_len as usize) {
        *slot = reader.id()?;
    }""",
        'read')

# ③ 读侧回填。
t = sub(t, """    restored.event_offer_len = offer_len as u8;""",
        """    restored.event_offer_len = offer_len as u8;
    // §331：遗物候选。空槽也是合法值（没有掷过），所以长度单独存。
    restored.event_relic_offer_ids = relic_offer_ids;
    restored.event_relic_offer_len = relic_offer_len;""",
        'restore')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('archive: relic offer persisted')

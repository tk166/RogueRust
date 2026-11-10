"""§331 修：批量改名误伤了**卡牌**候选的字段。

`t.replace('self.event_offer_len', 'self.event_relic_offer_len')` 把 §320 卡牌候选
（`event_offer` / `event_offer_len`）的读取也一起改了 —— 于是
`event_offer_len()` 返回的是**遗物**候选的件数（0），
`the_offer_survives_a_save_and_a_hash` 当场红在"two candidates come back: left 0"。

三处必须回到卡牌候选：

* `event_offer_len()` —— 卡牌候选件数；
* `event_offer_card()` —— 越界判断；
* `pick_event_offer()` —— 越界判断 + 取走之后清空。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

t = sub(t, """    pub const fn event_offer_len(&self) -> usize {
        self.event_relic_offer_len as usize
    }""",
        """    pub const fn event_offer_len(&self) -> usize {
        self.event_offer_len as usize
    }""",
        'event_offer_len')

t = sub(t, """    pub fn event_offer_card(&self, slot: usize) -> Option<&str> {
        if slot >= self.event_relic_offer_len as usize {
            return None;
        }""",
        """    pub fn event_offer_card(&self, slot: usize) -> Option<&str> {
        if slot >= self.event_offer_len as usize {
            return None;
        }""",
        'event_offer_card')

t = sub(t, """        if slot >= self.event_relic_offer_len as usize {
            return Err(RunError::EmptyOffer(slot as u8));
        }""",
        """        if slot >= self.event_offer_len as usize {
            return Err(RunError::EmptyOffer(slot as u8));
        }""",
        'pick_event_offer bound')

t = sub(t, """        self.push_card(row)?;
        self.event_offer = [RunId::EMPTY; MAX_EVENT_OFFER];
        self.event_relic_offer_len = 0;""",
        """        self.push_card(row)?;
        self.event_offer = [RunId::EMPTY; MAX_EVENT_OFFER];
        self.event_offer_len = 0;""",
        'pick_event_offer clear')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('card-offer field accesses restored')

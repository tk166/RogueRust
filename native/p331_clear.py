"""§331 修：`resolve_event_effects` 把我刚掷的**遗物候选**清掉了。

现场：`rd_run_choose` 报 `UnsupportedEventEffect`，而候选明明在（调试打印里
`offer0=Some("burning_blood")`）。根因是这一行：

```rust
self.event_offer = [RunId::EMPTY; MAX_EVENT_OFFER];
self.event_relic_offer_len = 0;      // ← 照抄了 §320 的"清卡牌候选"
```

§320 那句话说的是**卡牌**候选（`event_offer`）；遗物候选是 `begin_event` 之后、
**这一段开着的时候**才掷出来的，清掉它等于"按钮一点就报错"。

顺带把"事件收尾时清掉"补上（否则它会漏进下一个事件 —— 虽然 `begin_event` 也会清，
但收尾路径不经过 `begin_event`，例如 `[Leave]` 之后房间就结算了）。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'

OLD = """        // §320：上一轮可能已经有过一段候选（正常情况下没有：取走一张就清空）。
        // 进这一段之前先清，否则"漏清"会表现成"上一段的候选又冒出来"。
        self.event_offer = [RunId::EMPTY; MAX_EVENT_OFFER];
        self.event_relic_offer_len = 0;"""

NEW = """        // §320：上一轮可能已经有过一段候选（正常情况下没有：取走一张就清空）。
        // 进这一段之前先清，否则"漏清"会表现成"上一段的候选又冒出来"。
        //
        // ⚠️ §331：**只清卡牌候选**。遗物候选（`event_relic_offer_*`）是在 `begin_event`
        // 之后、**这一段开着的时候**才掷出来的 —— 在这里清掉它，`relic_lose:@0` 就永远
        // 解析不到候选，玩家点下去只会看到 `UnsupportedEventEffect`（第一版就是这样）。
        self.event_offer = [RunId::EMPTY; MAX_EVENT_OFFER];"""

t = io.open(PATH, encoding='utf-8').read()
assert t.count(OLD) == 1, 'anchor'
t = t.replace(OLD, NEW)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('resolve_event_effects no longer clears the relic candidates')

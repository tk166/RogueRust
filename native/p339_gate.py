"""§339 内容门：补 `relic_count` 漂移，并**开始检查事件级条件**。

## 两件事

### 1. `REQUIRES_KINDS` 少了 `relic_count`（§331 加进 Rust，没加进这份手抄表）

`native/sts_content_check.py` 的注释写着"词表与 `rd-core::run_expr` 的那两张表**必须一致**"，
而 §331 加 `relic_count`（`N'loth` 的"至少 2 件遗物"）时**只改了 Rust 那一份**。
今天它没红，是因为这份表**只用来查选项级** `Requires`，而 `relic_count` 只出现在事件级。

⇒ 两处一起修：词表补齐，并且事件级 `Requires` / `RequiresAny` 也走同一个
`check_requirement_atom`。这样"同一个词表被两处认识就一定漂"（`FACT.md` §4.20）这一条
再犯时，闸门会红。

### 2. 事件级条件原来是**没人查**的

`EventTables.Events*[]` 条目上的 `Requires`（§331）只被 Rust 读，内容门一句话都没说。
于是"写了个词表外的 Kind"只会在**掷到那个事件时**变成 `None` ⇒ **整池拒绝**
（`event_pool_at_with_facts` 的注释：读不出来就 `None`），而屏幕上表现为"`?` 房不出事件"。
静态能查的事不该留到运行时。

`RequiresAny`（§339 的 OR 组）同样查，而且额外要求它**不能为空**（空列表 = "没有这一组"，
写一个空列表是笔误，不是"永不成立"）。
"""

import io

PATH = 'native/sts_content_check.py'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── ① 词表：补 relic_count ────────────────────────────────────────────────────
t = sub(t, '''                  # §321：`floor` —— **本幕内的层号**（`mind_bloom` 的第三个选项按它换）。
                  "floor")''',
        '''                  # §321：`floor` —— **本幕内的层号**（`mind_bloom` 的第三个选项按它换）。
                  "floor",
                  # §331：`relic_count` —— 身上有几件遗物（`N'loth` 的"至少 2 件才出现"）。
                  # ⚠️ 这一条是 §339 补的：§331 只把它加进了 `rd-core::run_expr` 的 `KINDS`，
                  # 这份手抄表漏了。当时没红，是因为这份表只查**选项级** `Requires`，
                  # 而 `relic_count` 只出现在**事件级** —— 见下面第 ② 条。
                  "relic_count")''', 'kinds table')

t = sub(t, '''REQUIRES_NUMERIC = ("gold", "health", "max_health", "health_percent", "deck_count", "ascension",
                    "card_damage", "floor")''',
        '''REQUIRES_NUMERIC = ("gold", "health", "max_health", "health_percent", "deck_count", "ascension",
                    "card_damage", "floor", "relic_count")''', 'numeric table')

# ── ② 事件级条件：和选项级走同一个检查函数 ────────────────────────────────────
t = sub(t, '''            if high and low and high < low:
                fail(where, "MaxFloor %d is below MinFloor %d" % (high, low))''',
        '''            if high and low and high < low:
                fail(where, "MaxFloor %d is below MinFloor %d" % (high, low))
            # ── §339：事件级条件（`Requires` = AND 组，`RequiresAny` = OR 组）────────────
            # 原来这一格**没人查**：写个词表外的 Kind 只会在掷到它时让 `event_pool_at_with_facts`
            # 返回 `None`（整池拒绝），而屏幕上是"`?` 房不出事件"。静态能查的不该留到运行时。
            for req_key in ("Requires", "RequiresAny"):
                atoms = row.get(req_key)
                if atoms is None:
                    continue
                if not isinstance(atoms, list) or not atoms:
                    # 空列表是**笔误**（"没有这一组"应该是**不写这个键**）。OR 组尤其危险：
                    # 空的 OR 组按"没有要求"处理，写的人以为它"永不成立"。
                    fail(where + "." + req_key, "must be a non-empty list, got %r" % (atoms,))
                    continue
                if len(atoms) > REQUIRES_MAX:
                    fail(where + "." + req_key,
                         "%d atoms, the kernel keeps %d" % (len(atoms), REQUIRES_MAX))
                    continue
                check_requirement_atom(atoms, where + "." + req_key, relics, cards, counts)
            if row.get("Requires") and row.get("RequiresAny"):
                # 两组同时出现是**允许**的（AND && OR），但它意味着作者想表达
                # "(A 且 B) 且 (C 或 D)" —— 这种情况值得在评审时看一眼，不是错误。
                counts["both_groups"] += 1''', 'event-level conditions')

# ── ③ 统计里加一格，并在汇总行打印 ───────────────────────────────────────────
t = sub(t, '''    ok("event pools", "act1=%d act2=%d act3=%d"
       % (len(tables.get("Events") or []), len(tables.get("Events2") or []),
          len(tables.get("Events3") or [])))''',
        '''    ok("event pools", "act1=%d act2=%d act3=%d (both groups: %d)"
       % (len(tables.get("Events") or []), len(tables.get("Events2") or []),
          len(tables.get("Events3") or []), counts["both_groups"]))''', 'pools summary')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('sts_content_check: relic_count + event-level conditions')

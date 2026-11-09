"""§320 页面：事件候选列表（`The Library` 的 20 选 1、`Sensory Stone` 的无色牌）。

三处，形状全部照抄 §293 的"加牌候选"（`describePickupAdd` / `pickup_add_card` / snapshot）：
- `index.html::runSnapshot()` 的 `case 9` 读候选（id 与显示名）；
- `ui_panels.js::describeEventOffer()` 出一张表，每个按钮带**内核槽号**；
- `index.html` 的动作表加 `event_offer_take`。
"""

import io

INDEX = 'web/index.html'
PANELS = 'web/ui_panels.js'
SMOKE = 'web/smoke.mjs'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


# ── 1. snapshot ────────────────────────────────────────────────────────────────────
t = io.open(INDEX, encoding='utf-8').read()
t = sub(t, """    /// 与 `pickupPicks` 是**两件事**（那个是"改已有的一张"，这个是"从候选里加一张"）。
    pickupAdd: ex.rd_run_pickup_add(),""",
        """    /// 与 `pickupPicks` 是**两件事**（那个是"改已有的一张"，这个是"从候选里加一张"）。
    pickupAdd: ex.rd_run_pickup_add(),
    /// §320：事件摊开的候选（`Pending::EventOffer` = 9）—— `The Library` 的 20 选 1、
    /// `Sensory Stone` 的无色牌。每一项带**内核槽号**，按钮送回去的就是它。
    eventOffer: [],""",
        'snapshot eventOffer')

t = sub(t, """    case 5:
      snapshot.eventText = eventText();""",
        """    // §320：事件候选列表。与奖励屏/加牌候选同一个形状：数量与显示名都问内核。
    case 9:
      for (let slot = 0, n = ex.rd_run_event_offer_len(); slot < n; slot++) {
        snapshot.eventOffer.push({
          slot,
          id: readText(
            (k) => ex.rd_run_event_offer_id_len(k),
            (ptr, k) => ex.rd_run_event_offer_id_into(k, ptr),
            slot
          ),
          title: readText(
            (k) => ex.rd_run_event_offer_title_len(k),
            (ptr, k) => ex.rd_run_event_offer_title_into(k, ptr),
            slot
          ),
        });
      }
      break;
    case 5:
      snapshot.eventText = eventText();""",
        'snapshot case 9')

t = sub(t, """  pickup_add_card: (a) => act(() => ex.rd_run_pickup_add_card(a.slot), "加牌"),""",
        """  pickup_add_card: (a) => act(() => ex.rd_run_pickup_add_card(a.slot), "加牌"),
  // §320：事件候选 —— 拿这一张（槽号是内核给的，不是数组下标）。
  event_offer_take: (a) => act(() => ex.rd_run_event_offer_take(a.slot), "选牌"),
  /// §320：事件候选面板里的"跳过"（`Sensory Stone` 的 1 张也允许不拿吗？不 —— wiki 是
  /// "add N cards"，所以这里**不提供**跳过；按钮表里没有它。""",
        'action event_offer_take')
io.open(INDEX, 'w', encoding='utf-8', newline='\n').write(t)
print('index.html patched')

# ── 2. panel ──────────────────────────────────────────────────────────────────────
t = io.open(PANELS, encoding='utf-8').read()
t = sub(t, """  function describeIdle(s) {""",
        """  /// §320: an event that offered a **list of new cards** (`Pending::EventOffer` = 9).
  ///
  /// `The Library` 的 `[Read]` 是 20 选 1、`Sensory Stone` 的每次 `[Recall]` 是 3 选 1；
  /// 两者在运行层是同一件事，所以面板也只有这一份 —— 标题只说"从候选里拿一张"，
  /// 具体几张由内核给的 `rows` 决定（页面不写死 3，也不写死 20）。
  function describeEventOffer(s) {
    const rows = (s.eventOffer || []).map((card) => ({
      label: card.title || card.id || `#${card.slot}`,
      sub: "",
      value: "",
      disabled: false,
      button: { label: "拿这张", action: { kind: "event_offer_take", slot: card.slot } },
    }));
    return {
      title: "未知房间 · 从 " + rows.length + " 张里选一张加入牌组",
      lines: [],
      rows,
      buttons: [],
    };
  }

  function describeIdle(s) {""",
        'describeEventOffer')

t = sub(t, """      case 8:
        return describeEventCard(s);""",
        """      case 8:
        return describeEventCard(s);
      // §320：候选列表（事件摊开的新牌）。与 `EventCard` 分开：那一个收**牌组下标**，
      // 这一个收**候选槽号**，两个调用不同。
      case 9:
        return describeEventOffer(s);""",
        'describe case 9')
io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(t)
print('ui_panels.js patched')

# ── 3. smoke 的 REQUIRED（手抄第二份的地方）──────────────────────────────────────
t = io.open(SMOKE, encoding='utf-8').read()
t = sub(t, """const REQUIRED = [""",
        """const REQUIRED = [
  // §320：事件候选列表（`The Library` / `Sensory Stone`）。页面用了这六个，所以在这里抄第二遍。
  "rd_run_event_offer_len", "rd_run_event_offer_id_len", "rd_run_event_offer_id_into",
  "rd_run_event_offer_title_len", "rd_run_event_offer_title_into",
  "rd_run_event_offer_take",""",
        'smoke REQUIRED')
io.open(SMOKE, 'w', encoding='utf-8', newline='\n').write(t)
print('smoke.mjs patched')

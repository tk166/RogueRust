"""runProbe：补 P4 的读取与动作（商店/篝火/宝箱/事件/欠账/药水/牌堆）。"""

import io

P = 'web-next/src/run/runProbe.ts'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''  /** 事件日志。 */
  log(): unknown;''',
    '''  /** 事件日志。 */
  log(): unknown;
  /** P4 的屏（商店/篝火/宝箱/事件/欠账/药水）—— 一次读全，闸门不必逐字段拼。 */
  screens(): unknown;
  /** 战斗中的三个牌堆（没有战斗会话时是空表）。 */
  piles(): unknown;''',
    'probe types',
)

sub(
    '''  settleDefault(): unknown;''',
    '''  settleDefault(): unknown;

  // ── P4 动作（与玩家按钮一一对应）──────────────────────────────────────────
  buy(kind: string, slot: number): unknown;
  leave(): unknown;
  rest(): unknown;
  smith(index: number): unknown;
  toke(index: number): unknown;
  lift(): unknown;
  dig(): unknown;
  recall(): unknown;
  openChest(): unknown;
  chooseEvent(slot: number): unknown;
  takeEventOffer(slot: number): unknown;
  pickEventCard(index: number): unknown;
  pickBlessingCard(index: number): unknown;
  pickupPickCard(index: number): unknown;
  pickupAddCard(slot: number): unknown;
  pickupSkip(): unknown;
  pickupMaxHp(): unknown;
  usePotion(slot: number, target: number): unknown;
  dropPotion(slot: number): unknown;''',
    'probe p4 actions',
)

sub(
    '''    log: () => [...state().log],''',
    '''    log: () => [...state().log],

    screens() {
      const current = state();
      return {
        shop: current.shop,
        rest: current.rest,
        chest: current.chest,
        event: current.event,
        pickup: current.pickup,
        potions: current.potions,
        deck: [...current.deck],
        deckTitles: [...current.deckTitles],
      };
    },

    piles: () => store.piles(),''',
    'probe screens',
)

sub(
    '''    settleDefault() {
      const ok = store.settleDefault();
      return { ok, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },''',
    '''    settleDefault() {
      const ok = store.settleDefault();
      return { ok, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },

    buy(kind: string, slot: number) {
      const code = store.buy(kind as "card" | "relic" | "potion" | "colorless", slot);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    leave() {
      const code = store.leave();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    rest() {
      const code = store.rest();
      return { code, scene: window.__run!.scene(), run: window.__run!.run(), violations: window.__run!.violations() };
    },
    smith(index: number) {
      const code = store.smith(index);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    toke(index: number) {
      const code = store.toke(index);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    lift() {
      const code = store.lift();
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    dig() {
      const code = store.dig();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    recall() {
      const code = store.recall();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    openChest() {
      const code = store.openChest();
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    chooseEvent(slot: number) {
      const code = store.chooseEvent(slot);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    takeEventOffer(slot: number) {
      const code = store.takeEventOffer(slot);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    pickEventCard(index: number) {
      const code = store.pickEventCard(index);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    pickBlessingCard(index: number) {
      const code = store.pickBlessingCard(index);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    pickupPickCard(index: number) {
      const code = store.pickupPickCard(index);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    pickupAddCard(slot: number) {
      const code = store.pickupAddCard(slot);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    pickupSkip() {
      const code = store.pickupSkip();
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    pickupMaxHp() {
      const code = store.pickupMaxHp();
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    usePotion(slot: number, target: number) {
      const code = store.usePotion(slot, target);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    dropPotion(slot: number) {
      const code = store.dropPotion(slot);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },''',
    'probe p4 impl',
)
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('probe: p4')

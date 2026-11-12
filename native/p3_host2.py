"""host.ts：P3 场景层还差的几个读取/动作（祝福、欠账、局终、奖励药水/遗物、结算动作）。"""

import io

P = 'web-next/src/wasm/host.ts'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''  /** 节点 kind 的**内核名字**（`rd_run_kind_name_*`），用于诊断与"未知 kind"兜底。 */''',
    '''  /** 开局祝福的候选（§346：条数由内核给，**不许**写死 `for slot in 0..2`）。 */
  startOffers(): { slot: number; id: string; gain: number; gainAmount: number; cost: number; costAmount: number }[] {
    const call = (name: string) => (this.ex[name] as () => number)();
    const count = call("rd_run_start_offer_count");
    const out: { slot: number; id: string; gain: number; gainAmount: number; cost: number; costAmount: number }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      out.push({
        slot,
        id: this.readText(
          () => (this.ex.rd_run_start_offer_len as (slot: number) => number)(slot),
          (ptr) => (this.ex.rd_run_start_offer_into as (slot: number, ptr: number) => number)(slot, ptr)
        ),
        gain: (this.ex.rd_run_start_gain as (slot: number) => number)(slot),
        gainAmount: (this.ex.rd_run_start_gain_amount as (slot: number) => number)(slot),
        cost: (this.ex.rd_run_start_cost as (slot: number) => number)(slot),
        costAmount: (this.ex.rd_run_start_cost_amount as (slot: number) => number)(slot),
      });
    }
    return out;
  }

  /** 祝福还差什么：0 没有 / 1 删牌 / 2 升级 / 3 变形 / -1 没有局。 */
  blessingNeeds(): number {
    return (this.ex.rd_run_blessing_needs as () => number)();
  }

  /** 遗物欠账：还要改几张牌（`SC-11a`）。 */
  pickupPicks(): number {
    return (this.ex.rd_run_pickup_picks as () => number)();
  }

  /** 遗物欠账：还要加几张牌（`SC-11b`）。 */
  pickupAdd(): number {
    return (this.ex.rd_run_pickup_add as () => number)();
  }

  bossBeaten(): boolean {
    return (this.ex.rd_run_boss_beaten as () => number)() === 1;
  }

  /** 局终原因（`rd_run_over_why` 的一行文字）。 */
  overWhy(): string {
    const len = (this.ex.rd_run_over_why_len as () => number)();
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) => (this.ex.rd_run_over_why_into as (ptr: number) => number)(ptr)
    );
  }

  /** 奖励屏上的药水 id（没有就是空串）。 */
  rewardPotionId(): string {
    const len = (this.ex.rd_run_reward_potion_len as () => number)();
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) => (this.ex.rd_run_reward_potion_into as (ptr: number) => number)(ptr)
    );
  }

  rewardRelicId(): string {
    const len = (this.ex.rd_run_reward_relic_len as () => number)();
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) => (this.ex.rd_run_reward_relic_into as (ptr: number) => number)(ptr)
    );
  }

  takePotion(): number {
    return (this.ex.rd_run_take_potion as () => number)();
  }

  takeRelic(): number {
    return (this.ex.rd_run_take_relic as () => number)();
  }

  /** 离开当前待决屏（商店/宝箱/篝火都认）。 */
  leave(): number {
    return (this.ex.rd_run_leave as () => number)();
  }

  rest(): number {
    return (this.ex.rd_run_rest as () => number)();
  }

  openChest(): number {
    return (this.ex.rd_run_open_chest as () => number)();
  }

  /** 节点 kind 的**内核名字**（`rd_run_kind_name_*`），用于诊断与"未知 kind"兜底。 */''',
    'host p3 extras',
)
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('host: p3 extras')

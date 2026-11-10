"""§342 判据：ABI 级价格一致、遗物补货按稀有度定价、Smiling Mask 硬价。

## 判据 A（rd-wasm，**ABI 级**）`the_page_price_is_the_price_the_kernel_charges`

§338 的判据只测到 `RunState` 层（`buy_*` 的校验/扣款/错误消息三处一个数），于是
**"内核自洽、但它告诉页面的数是另一个"** 这种缺陷没有判据能看见 —— 第九轮 Review P1-1 就是它。

判据形状（四排各一次）：
* `p = 导出价`，`g = 当前金币`；
* `p <= g` ⇒ 买必须成功，且金币**正好少 p**；
* `p > g` ⇒ 买必须被拒（`-2`）—— 页面说买不起，内核也必须说买不起；
* 买完那一格再读，必须是 `-1`（售罄哨兵不过折扣）。

两个方向都能抓 P1-1：若导出价是**挂牌价**而内核按折后价收，则
"p ≤ g" 那支会看到金币少得比 p 少；"p > g" 那支会看到内核**接受**（0 而不是 -2）。

## 判据 B（rd-run）`restocked_relics_are_priced_by_their_own_rarity`

用 C/U/R 各三件的池子，持 Courier 反复买第 0 格，每次断言**补出来的那一件**的价落在
**它自己稀有度**的价带里。硬编码 143-157 的旧实现会让 Uncommon/Rare 落在带外。
另外要求三档**都出现过**（否则"只补 Common"也会绿）。

## 判据 C（rd-run）`smiling_mask_locks_removal_at_fifty_whatever_the_discounts`

2×2×2（Membership Card × Courier × A16）全为 50；对照组（没有 Smiling Mask）：
MC ⇒ 38（`ceil(75*0.5)`）、MC+Courier ⇒ 30（`75*0.4`）。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
STATE = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── 判据 A：rd-wasm ─────────────────────────────────────────────────────────
t = io.open(RUN, encoding='utf-8').read()

ANCHOR_A = '''    /// §336：`fight_begin` 那一条记录的第 5 列是**战斗状态**的 `hash_full`。'''

TEST_A = '''    /// §342（第九轮 Review P1-1）：**页面看到的价格就是内核收的价格**，四排都一样。
    ///
    /// 为什么这条必须住在 ABI 层：§338 的判据 `every_purchase_charges_the_price_the_page_shows`
    /// 只测到 `RunState` —— 它证明了"校验/扣款/错误消息三处一个数"，但**没证明"内核告诉页面的数"
    /// 是那一个数**。无色与药水两排的导出当时返回挂牌价，于是持 Membership Card 时
    /// 页面把买得起的商品**禁用**了（`price > gold` ⇒ disabled），玩家根本点不到。
    ///
    /// 判据的两个方向：
    /// * `p <= g` ⇒ 买必须成功，金币正好少 `p`（抓"显示比实收高"）；
    /// * `p > g` ⇒ 必须被拒（抓"显示比实收低/高到判断反了"）。
    #[test]
    fn the_page_price_is_the_price_the_kernel_charges() {
        // 走到一个商店。商店在随机地图上，所以按种子找第一个能到的。
        let mut reached = false;
        for seed in 0..400 {
            reset(seed);
            for _hop in 0..24 {
                if rd_run_pending() == 2 {
                    reached = true;
                    break;
                }
                if rd_run_step(0) != 0 {
                    break;
                }
                if rd_run_begin_node() != 0 {
                    break;
                }
                match rd_run_pending() {
                    1 => {
                        let _ = rd_run_rest();
                    }
                    3 => {
                        let _ = rd_run_open_chest();
                        let _ = rd_run_leave();
                    }
                    5 => {
                        let _ = rd_run_choose(0);
                    }
                    8 => {
                        let _ = rd_run_pick_event_card(0);
                    }
                    4 => {
                        let _ = rd_run_skip_reward();
                    }
                    _ => {
                        // 战斗节点：开打、立刻收（这条判据不关心战果）。
                        if rd_run_fight_begin() == 0 {
                            let _ = rd_run_fight_end();
                        }
                    }
                }
                while rd_run_pending() == 4 {
                    let _ = rd_run_skip_reward();
                }
            }
            if reached {
                break;
            }
        }
        assert!(reached, "no seed reached a shop within 24 hops");

        // 持 Membership Card：于是"挂牌价"与"实付价"**不相等**，判据才有分辨力。
        assert_eq!(
            rd_run_grant_relic(b"membership_card".as_ptr(), 15),
            0,
            "grant membership_card: {}",
            run_error_text()
        );
        assert_eq!(rd_run_in_fight(), 0, "we are standing in the shop, not in a fight");

        let gold = || rd_run_observe(4);
        let mut checked = 0usize;

        // 四排：(名字, 计数导出, 价格导出, 购买导出)。遗物放最后 —— 它可能带"欠账"改变 pending。
        for (name, count, price, buy) in [
            (
                "cards",
                rd_run_shop_card_count as fn() -> i32,
                rd_run_shop_card_price as fn(i32) -> i32,
                rd_run_buy_card as fn(i32) -> i32,
            ),
            (
                "colorless",
                rd_run_shop_colorless_count as fn() -> i32,
                rd_run_shop_colorless_price as fn(i32) -> i32,
                rd_run_buy_colorless as fn(i32) -> i32,
            ),
            (
                "potions",
                rd_run_shop_potion_count as fn() -> i32,
                rd_run_shop_potion_price as fn(i32) -> i32,
                rd_run_buy_potion as fn(i32) -> i32,
            ),
            (
                "relics",
                rd_run_shop_relic_count as fn() -> i32,
                rd_run_shop_relic_price as fn(i32) -> i32,
                rd_run_buy_relic as fn(i32) -> i32,
            ),
        ] {
            for slot in 0..count() {
                let before = gold();
                let shown = price(slot);
                if shown < 0 {
                    continue; // 那一格本来就空着（池子不够）
                }
                let code = buy(slot);
                if shown <= before {
                    assert_eq!(
                        code, 0,
                        "{name}[{slot}]: the page shows {shown} and we hold {before}, so the \\
                         purchase must succeed (kernel said {code}: {})",
                        run_error_text()
                    );
                    assert_eq!(
                        gold(),
                        before - shown,
                        "{name}[{slot}]: the page shows {shown}, so exactly {shown} must be charged"
                    );
                    checked += 1;
                } else {
                    assert_eq!(
                        code, -2,
                        "{name}[{slot}]: the page shows {shown} but we only hold {before} -- the \\
                         kernel must refuse too (it said {code})"
                    );
                }
                // 买走之后那一格必须是**售罄哨兵**，不是 0（`shop_price` 的 `.max(0)` 曾把它
                // 变成"0 金可买"）。
                if code == 0 {
                    assert_eq!(
                        price(slot),
                        -1,
                        "{name}[{slot}]: a sold slot must read -1, not a price"
                    );
                }
            }
        }
        assert!(
            checked >= 1,
            "the fixture must actually buy something at a discount (checked {checked})"
        );
    }

'''

t = sub(t, ANCHOR_A, TEST_A + ANCHOR_A, 'test A')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)

# ── 判据 B / C：rd-run ──────────────────────────────────────────────────────
t = io.open(STATE, encoding='utf-8').read()

ANCHOR_B = '''    /// §340：补货失败 ⇒ **整笔交易回滚**（金币、牌、货架一起），不留半个提交。'''

TEST_B = '''    /// §342（第九轮 Review P1-2）：补出来的遗物按**它自己的稀有度**定价。
    ///
    /// 旧实现硬编码 Common 档（143-157），于是 Uncommon / Rare 的补货也按 Common 卖。
    /// fandom 的补丁记录写着 "Relics and Potions in the shop now correctly set their prices when
    /// restocked with the Courier" —— 这曾经是**官方**的 bug。
    ///
    /// 判据要求三档**都出现过**：只断言"价带对"的话，一个"永远只补 Common"的实现也会绿。
    #[test]
    fn restocked_relics_are_priced_by_their_own_rarity() {
        let pool: [PoolRelic<'static>; 9] = [
            PoolRelic { id: "anchor", rarity: Rarity::Common },
            PoolRelic { id: "bag_of_prep", rarity: Rarity::Common },
            PoolRelic { id: "blood_vial", rarity: Rarity::Common },
            PoolRelic { id: "blue_candle", rarity: Rarity::Uncommon },
            PoolRelic { id: "darkstone_periapt", rarity: Rarity::Uncommon },
            PoolRelic { id: "meal_ticket", rarity: Rarity::Uncommon },
            PoolRelic { id: "calipers", rarity: Rarity::Rare },
            PoolRelic { id: "ice_cream", rarity: Rarity::Rare },
            PoolRelic { id: "tungsten_rod", rarity: Rarity::Rare },
        ];
        let mut run = ironclad();
        run.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        run.adjust_gold(100_000);
        run.pending = Pending::Shop;
        run.stock_shop(&TYPED_CARDS, &pool, &POTIONS).expect("stock the shop");

        let mut seen_common = false;
        let mut seen_uncommon = false;
        let mut seen_rare = false;
        for round in 0..80 {
            // 第 0 格：买走 ⇒ 立刻补一件。
            if run.shop().relics()[0].price < 0 {
                break;
            }
            let bought = run.shop().relics()[0].id.as_str().to_string();
            run.buy_relic(0, &TYPED_CARDS, &pool).expect("buy the relic");
            let restocked = run.shop().relics()[0];
            if restocked.price < 0 {
                break; // 池子空了：这一格留空是允许的
            }
            let id = restocked.id.as_str().to_string();
            let rarity = pool
                .iter()
                .find(|entry| entry.id == id.as_str())
                .map_or_else(
                    || panic!("round {round}: restocked {:?} is not in the pool", id),
                    |entry| entry.rarity,
                );
            let (low, high) = relic_price_band(rarity);
            assert!(
                (low..=high).contains(&restocked.price),
                "round {round}: {id:?} ({rarity:?}) restocked at {} but its band is {low}..={high} \\
                 (bought {bought:?})",
                restocked.price
            );
            match rarity {
                Rarity::Uncommon => seen_uncommon = true,
                Rarity::Rare => seen_rare = true,
                _ => seen_common = true,
            }
        }
        assert!(
            seen_common && seen_uncommon && seen_rare,
            "the fixture must restock all three rarities (common {seen_common}, \\
             uncommon {seen_uncommon}, rare {seen_rare})"
        );
    }

    /// §342（第九轮 Review P2）：`smiling_mask` 是**硬价 50** —— 既不涨价也不折扣。
    ///
    /// wiki.gg：*"Smiling Mask **overrides** the reduced price of the Card Removal Service to 50
    /// Gold **even with Membership Card**"*；Courier 页：*"Smiling Mask will **negate** The
    /// Courier's price reduction … always locked at a price of 50 gold"*。
    ///
    /// 旧实现 `shop_price(marked_up(50))`：A16 → 55、MC → 25、两件都在 → 20。三条全错，
    /// 而每一条都只是**一个数**，屏幕上毫无异常。
    #[test]
    fn smiling_mask_locks_removal_at_fifty_whatever_the_discounts() {
        // 2×2×2：Membership Card × Courier × A16 ⇒ 全是 50。
        for membership in [false, true] {
            for courier in [false, true] {
                for ascension in [0u8, 16u8] {
                    let mut run = RunState::new_with_ascension(7, 80, 99, &DECK, ascension)
                        .expect("a run");
                    run.push_relic("smiling_mask", &TYPED_CARDS).expect("smiling_mask");
                    if membership {
                        run.push_relic("membership_card", &TYPED_CARDS).expect("membership_card");
                    }
                    if courier {
                        run.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
                    }
                    // 用掉几次，确认"+25/次"对它也失效（wiki: "will no longer increase"）。
                    run.removed_cards = 3;
                    assert_eq!(
                        run.remove_card_price(),
                        SHOP_REMOVE_FLAT,
                        "smiling_mask: mc={membership} courier={courier} a{ascension} must all be 50"
                    );
                }
            }
        }

        // 对照组：**没有** Smiling Mask 时才走折扣（否则上面那 8 格证明不了任何事）。
        let mut plain = ironclad();
        assert_eq!(plain.remove_card_price(), SHOP_REMOVE_BASE, "the base price");
        plain.push_relic("membership_card", &TYPED_CARDS).expect("membership_card");
        assert_eq!(plain.remove_card_price(), 38, "75 * 0.5 = 37.5 -> 38 (ceil)");
        plain.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        assert_eq!(plain.remove_card_price(), 30, "75 * 0.4 = 30 (multiplicative)");
    }

'''

t = sub(t, ANCHOR_B, TEST_B + ANCHOR_B, 'tests B+C')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('§342 tests: ABI prices + relic rarity band + smiling_mask matrix')

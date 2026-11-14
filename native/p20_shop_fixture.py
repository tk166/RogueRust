"""§377 补丁 3：统计测试的**夹具**错了 —— 池子只有 5 张牌，而货架正好 5 个位置。

于是"每家店必然把 5 张全上架" ⇒ Rare 占比恒等于池子占比（1/5 = 20%），**与掷不掷档位无关**。
这是"夹具让被测行为不可达"的经典形状（§4.25）：断言写得对，但它测不到东西。

修法：池子放大到 20 张（12 Common / 6 Uncommon / 2 Rare），每家店从 20 张里挑 5 张，
于是"Rare 的占比"才真的由档位 roll 决定。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''        let pool: [PoolCard<'static>; 5] = [
            PoolCard { id: "strike", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "bash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "twin_strike", rarity: Rarity::Uncommon, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "bludgeon", rarity: Rarity::Rare, kind: CardKind::Attack, upgraded: None, colorless: false },
        ];'''

NEW = '''        // ⚠️ 池子必须**明显大于** 5 个货位。第一版夹具只有 5 张牌，于是每家店必然把 5 张
        // 全部上架 —— Rare 的占比恒等于池子占比（1/5 = 20%），**与掷不掷档位无关**。
        // 那条断言看起来在守"稀有度掷了"，实际上什么也没测到（§4.25 的老形状）。
        let pool: [PoolCard<'static>; 20] = [
            PoolCard { id: "strike", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "bash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "cleave", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "clothesline", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "headbutt", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "heavy_blade", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "iron_wave", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "perfected_strike", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "pommel_strike", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "sword_boomerang", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "thunderclap", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "twin_strike", rarity: Rarity::Uncommon, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "carnage", rarity: Rarity::Uncommon, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "dropkick", rarity: Rarity::Uncommon, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "hemokinesis", rarity: Rarity::Uncommon, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "pummel", rarity: Rarity::Uncommon, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "reckless_charge", rarity: Rarity::Uncommon, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "bludgeon", rarity: Rarity::Rare, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "feed", rarity: Rarity::Rare, kind: CardKind::Attack, upgraded: None, colorless: false },
        ];'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD2 = '''            for offer in run.shop().cards() {
                match offer.id.as_str() {
                    "bludgeon" => rare += 1,
                    "twin_strike" => uncommon += 1,
                    _ => common += 1,
                }
            }'''
NEW2 = '''            for offer in run.shop().cards() {
                // 按**稀有度**归类，不按具体 id：池子里有 12 Common / 6 Uncommon / 2 Rare，
                // 直接查池子才是唯一的真相（写死 `bludgeon` 那种做法加一张牌就漂）。
                let rarity = pool
                    .iter()
                    .find(|entry| entry.id == offer.id.as_str())
                    .map(|entry| entry.rarity);
                match rarity {
                    Some(Rarity::Rare) => rare += 1,
                    Some(Rarity::Uncommon) => uncommon += 1,
                    Some(_) => common += 1,
                    None => {}
                }
            }'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('fixture: 20 张池子（12/6/2）')

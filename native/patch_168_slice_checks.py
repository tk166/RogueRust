"""Rewrite the slice's assertion section as five **sibling** blocks.

The first version nested them (`if (!shop.skipped) { ... const event ... }`), so `--only boss` skipped
every check and the gate passed on a run that never reached the boss. A skipped block must not be
able to hide the next one.
"""
import io

PATH = "web/act1_slice.mjs"
MARK = 'const shop = byName("shop");'
END = "await page.close();"

BODY = '''const shop = byName("shop");
if (!shop.skipped) {
  want(shop.kind === 4, `shop: the cursor is on kind ${shop.kind}, expected 4 (merchant)`);
  want((shop.cards || 0) >= 4, `shop: only ${shop.cards} stock rows`);
  want(shop.hasRemove === true, "shop: no 删一张牌 service");
  // A run starts with **99** gold (wiki), so at a floor-3 shop a player can afford the 75-gold
  // removal **or** a card, not both -- and which one is not ours to promise across seeds.
  want(
    shop.deckAfterRemove === shop.deckBeforeRemove - 1,
    `shop: removing did not shrink the deck (${shop.deckBeforeRemove} -> ${shop.deckAfterRemove})`
  );
  want(shop.goldAfterRemove < shop.goldBeforeRemove, "shop: removing a card did not cost gold");
  if (shop.deckAfterBuy !== shop.deckAfterRemove) {
    want(
      shop.deckAfterBuy === shop.deckAfterRemove + 1,
      `shop: buying a card did not grow the deck (${shop.deckAfterRemove} -> ${shop.deckAfterBuy})`
    );
    want(shop.goldAfterBuy < shop.goldAfterRemove, "shop: buying a card did not cost gold");
  }
}

const event = byName("event");
if (!event.skipped) {
  want(event.kind === 5, `event: the cursor is on kind ${event.kind}, expected 5 (unknown room)`);
  want((event.text || "").length > 4, `event: the room shows no text (${JSON.stringify(event.text)})`);
  want((event.options || []).length >= 2, `event: only ${(event.options || []).length} option(s)`);
  want(
    event.deckAfter !== event.deckBefore || event.hpAfter !== event.hpBefore,
    "event: choosing an option changed neither the deck nor the HP"
  );
}

const rest = byName("rest");
if (!rest.skipped) {
  want(rest.kind === 3, `rest: the cursor is on kind ${rest.kind}, expected 3 (campfire)`);
  want(rest.hasSmith === true, "rest: no 打铁 button");
  want(
    rest.upgraded === rest.upgradedBefore + 1,
    `rest: smithing did not add a + card (${rest.upgradedBefore} -> ${rest.upgraded})`
  );
  want(rest.hpAfter === rest.hpBefore, "rest: smithing must not heal");
  want(
    (rest.deckAfter || []).length === (rest.deckBefore || []).length,
    "rest: smithing changed the deck size"
  );
}

const elite = byName("elite");
if (!elite.skipped) {
  want(elite.kind === 2, `elite: the cursor is on kind ${elite.kind}, expected 2 (elite)`);
  want(elite.won === true, "elite: the fight was not won");
  want(elite.relicOffered === true, "elite: no relic on the reward screen");
  want(
    elite.relicsAfter === (elite.relicsBefore || 0) + 1,
    `elite: the relic was not taken (${elite.relicsBefore} -> ${elite.relicsAfter})`
  );
}

const boss = byName("boss");
if (!boss.skipped) {
  want(boss.kind === 7, `boss: the cursor is on kind ${boss.kind}, expected 7 (boss)`);
  want(boss.started === true, "boss: the fight did not start");
  want(boss.potionGranted === 0, `boss: the debug grant failed (${boss.potionGranted})`);
  want(boss.potionOpened === 1, "boss: the Attack Potion opened no question");
  want(boss.potionSource === 2, `boss: the question's source is ${boss.potionSource}, expected 2`);
  want(boss.potionOptions === 3, `boss: ${boss.potionOptions} candidates, expected 3`);
  want(boss.potionAnswered === true, "boss: the question was not answered");
  want(boss.won === true, "boss: the boss was not beaten");
  want(
    boss.actAfter === (boss.actBefore || 1) + 1,
    `boss: the act did not advance (${boss.actBefore} -> ${boss.actAfter})`
  );
  want(boss.hpAfter === boss.maxHp, `boss: the act-end heal did not fill up (${boss.hpAfter}/${boss.maxHp})`);
  want(boss.mapNodes > 0, "boss: the next act has no map");
}

'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    start = text.index(MARK)
    end = text.index(END, start)
    text = text[:start] + BODY + text[end:]
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("assertion section rewritten as five sibling blocks")


if __name__ == "__main__":
    main()

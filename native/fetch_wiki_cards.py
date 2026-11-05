"""§218: pull the per-card **wikitext** for every card in this content.

Why wikitext and not the rendered page: the upgrade numbers live in a *separate* template field
(`Description` vs `UpgradeDescription`) and the rendered page merges them into one sentence with
superscripts -- exactly the shape that gets transcribed wrong by hand. `blind` already burned us once
(wrong rarity, an Exhaust that is not on the card: §195.9).

Saved under `native/wiki_cards/<id>.txt` so the numbers can be re-checked offline.

Usage:
  python -X utf8 native/fetch_wiki_cards.py            # fetch everything missing
  python -X utf8 native/fetch_wiki_cards.py --only bash
"""
import argparse
import io
import os
import sys
import urllib.request

PROXY = 'http://127.0.0.1:7897'
OUT = os.path.join('native', 'wiki_cards')
BASE = 'https://slaythespire.wiki.gg/wiki/%s?action=raw'

# Card id -> wiki page name. `None` = this content has a card the wiki never had (our own or the
# sample package's); those are recorded so the gap stays visible instead of being quietly skipped.
PAGES = {
    # Ironclad starts
    # ⚠️ `Strike` / `Defend` 是消歧页（#REDIRECT），真正的卡片页带职业后缀。
    'strike': 'Strike_(Ironclad)',
    'defend': 'Defend_(Ironclad)',
    'bash': 'Bash',
    # Ironclad commons/uncommons/rares
    'anger': 'Anger',
    'twin_strike': 'Twin_Strike',
    'iron_wave': 'Iron_Wave',
    'clothesline': 'Clothesline',
    'uppercut': 'Uppercut',
    'sentinel': 'Sentinel',
    'whirlwind': 'Whirlwind',
    'inflame': 'Inflame',
    'metallicize': 'Metallicize',
    'combust': 'Combust',
    'barricade': 'Barricade',
    'blur': 'Blur',
    'berserk': 'Berserk',
    # colorless / event
    'apparition': 'Apparition',
    'buffer': 'Buffer',
    'bandage_up': 'Bandage_Up',
    'blind': 'Blind',
    'dark_shackles': 'Dark_Shackles',
    # status / curse cards
    'slimed': 'Slimed',
    'wound': 'Wound',
    'burn': 'Burn',
    'dazed': 'Dazed',
    'void': 'Void',
    'injury': 'Injury',
    'ascenders_bane': "Ascender's_Bane",
    # §221：这一节新增的 Ironclad 牌
    'cleave': 'Cleave',
    'pommel_strike': 'Pommel_Strike',
    'shrug_it_off': 'Shrug_It_Off',
    'thunderclap': 'Thunderclap',
    'bludgeon': 'Bludgeon',
    'impervious': 'Impervious',
    'pummel': 'Pummel',
    'wild_strike': 'Wild_Strike',
    'ghostly_armor': 'Ghostly_Armor',
    'battle_trance': 'Battle_Trance',
    # §225
    'second_wind': 'Second_Wind',
    'fiend_fire': 'Fiend_Fire',
    # §226：复制载体（Dual Wield）
    'dual_wield': 'Dual_Wield',
    # §227：选牌之后**改**它（Armaments / Warcry）与延后复制（Nightmare）
    'armaments': 'Armaments',
    'warcry': 'Warcry',
    'nightmare': 'Nightmare',
    # §228：随机目标（Sword Boomerang）与"按格挡打伤害"（Body Slam）
    'sword_boomerang': 'Sword_Boomerang',
    'body_slam': 'Body_Slam',
    # §229：per-copy 计数器（Rampage）、可无限升级（Searing Blow）、随机双击（Rip and Tear）
    'rampage': 'Rampage',
    'searing_blow': 'Searing_Blow',
    'rip_and_tear': 'Rip_and_Tear',
    # §230：临时力量（Flex）、力量翻倍（Limit Break）、按牌组数加伤（Perfected Strike）
    'flex': 'Flex',
    'limit_break': 'Limit_Break',
    'perfected_strike': 'Perfected_Strike',
    # §231：格挡 + 随机消耗（True Grit）、打全体并按掉血回血（Reaper）
    'true_grit': 'True_Grit',
    'reaper': 'Reaper',
    # §221：事件给的两张诅咒
    'doubt': 'Doubt',
    'writhe': 'Writhe',
    # 本内容独有（wiki 没有这两张）：留档，不编数字。
    'patient_guard': None,
    'swift_strike': None,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', help='fetch a single card id')
    parser.add_argument('--force', action='store_true', help='refetch even if the file exists')
    args = parser.parse_args()

    os.makedirs(OUT, exist_ok=True)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
    opener.addheaders = [('User-Agent', 'sts-tui-doccheck/1.0 (local research)')]

    todo = {k: v for k, v in PAGES.items() if v}
    if args.only:
        todo = {args.only: PAGES[args.only]}
    ok, skipped, failed = 0, [], []
    for card, page in sorted(todo.items()):
        path = os.path.join(OUT, card + '.txt')
        if os.path.isfile(path) and not args.force and not args.only:
            skipped.append(card)
            continue
        url = BASE % page
        try:
            with opener.open(url, timeout=25) as response:
                text = response.read().decode('utf-8', 'replace')
        except Exception as error:                      # noqa: BLE001 - the report needs the reason
            failed.append((card, str(error)))
            continue
        if '{{Card Infobox' not in text and '{{Card' not in text:
            failed.append((card, 'no card infobox in the response (wrong page?)'))
            continue
        io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
        ok += 1
        print('  fetched %-14s %6d B  %s' % (card, len(text), page))
    print('WIKI_CARDS %d fetched, %d already there, %d failed' % (ok, len(skipped), len(failed)))
    for card, why in failed:
        print('  !! %s: %s' % (card, why))
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()

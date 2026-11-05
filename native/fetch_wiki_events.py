"""§221 events: three more `?` rooms whose effects the closed vocabulary already covers.

The wiki's event pages give the numbers; `EventEffect` (rd-run) accepts only
heal/gold/damage/max_hp/nothing/remove_card/upgrade_card/transform_card/curse:<id>/relic:<id>, and all
three of these stay inside it -- no kernel work, which is why they land in this section rather than a
later one.
"""
import io
import json
import os
import urllib.request

PROXY = 'http://127.0.0.1:7897'
OUT = os.path.join('native', 'wiki_events')
PAGES = {'the_cleric': 'The_Cleric', 'living_wall': 'Living_Wall', 'bonfire_spirits': 'Bonfire_Spirits'}

os.makedirs(OUT, exist_ok=True)
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
opener.addheaders = [('User-Agent', 'sts-tui-doccheck/1.0 (local research)')]
for event, page in PAGES.items():
    path = os.path.join(OUT, event + '.txt')
    if os.path.isfile(path):
        print('have', event)
        continue
    try:
        with opener.open('https://slaythespire.wiki.gg/wiki/%s?action=raw' % page, timeout=25) as r:
            text = r.read().decode('utf-8', 'replace')
    except Exception as error:                       # noqa: BLE001 - the report needs the reason
        print('!! %s: %s' % (event, error))
        continue
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    print('fetched %-16s %5d B  %s' % (event, len(text), page))

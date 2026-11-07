"""§259：把 wiki 的**遗物数据模块**抓下来，作为"信息拉齐"的唯一可信来源。

为什么抓 `Module:Relics/data` 而不是 `Relics List` 页：后者是模板拼出来的表，机器抽取会丢字段；
前者是 Lua 表，每个遗物一段 `["Name"] = { Image, Description, Rarity, Character, Flavor }`，
**稀有度与归属角色都在里面**，这正是"信息"要拉齐的那几格。

存到 `native/wiki_relics/relics_data.lua.txt`（原样，不转写），让离线也能复核。
"""
import io
import os
import urllib.request

PROXY = "http://127.0.0.1:7897"
OUT = 'native/wiki_relics'
TITLE = 'Module:Relics/data'


def main():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'relics_data.lua.txt')
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    )
    opener.addheaders = [("User-Agent", "sts-tui-doccheck/1.0 (local research)")]
    url = "https://slaythespire.wiki.gg/index.php?title=%s&action=raw" % TITLE.replace(' ', '_')
    body = opener.open(url, timeout=40).read().decode('utf-8')
    io.open(path, 'w', encoding='utf-8', newline='\n').write(body)
    print('saved %d B to %s' % (len(body.encode('utf-8')), path))
    print('entries: %d' % body.count('] = {'))


main()

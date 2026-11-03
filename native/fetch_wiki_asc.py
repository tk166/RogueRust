"""§190: pull the per-monster **wikitext** for every monster that still lacks ascension data.

Why raw wikitext and not the rendered page: the rendered table collapses the `×N` of a multi-hit move
into the ascension superscript (`Deals 1×62 damage`), which reads as a different number. The source
`{{Asc|2|12}}` templates cannot be misread.

Saved under `native/wiki_asc/<monster>.txt`, so the numbers can be re-checked offline and the
transcription in the content does not depend on the network being up.
"""
import io
import os
import urllib.request

PROXY = "http://127.0.0.1:7897"
OUT = os.path.join("native", "wiki_asc")

# Page names as the wiki spells them; `None` means "no such page, skip" (recorded in the report).
PAGES = {
    "cultist": "Cultist",
    "jaw_worm": "Jaw_Worm",
    "louse": "Louse",
    "acid_slime": "Acid_Slime",
    "spike_slime": "Spike_Slime",
    "fungi_beast": "Fungi_Beast",
    "byrd": "Byrd",
    "chosen": "Chosen",
    "darkling": "Darkling",
    "maw": "Maw",
    "orb_walker": "Orb_Walker",
    "spiker": "Spiker",
    "spire_growth": "Spire_Growth",
    "shelled_parasite": "Shelled_Parasite",
    "sentry": "Sentry",
    "gremlin_nob": "Gremlin_Nob",
    "gremlin_leader": "Gremlin_Leader",
    "gremlin_wizard": "Gremlin_Wizard",
    "fat_gremlin": "Fat_Gremlin",
    "sneaky_gremlin": "Sneaky_Gremlin",
    "dagger": "Dagger",
    "slime_boss": "Slime_Boss",
    "the_champ": "The_Champ",
    "time_eater": "Time_Eater",
    "giant_head": "Giant_Head",
    "book_of_stabbing": "Book_of_Stabbing",
    "nemesis": "Nemesis",
    "reptomancer": "Reptomancer",
    "slavers": "Slavers",
    "taskmaster": "Taskmaster",
    "lagavulin": "Lagavulin",
}


def main():
    os.makedirs(OUT, exist_ok=True)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    )
    opener.addheaders = [("User-Agent", "sts-tui-doccheck/1.0 (local research)")]
    ok, failed = 0, []
    for key, page in PAGES.items():
        path = os.path.join(OUT, key + ".txt")
        if os.path.exists(path) and os.path.getsize(path) > 200:
            ok += 1
            continue
        # Follow one `#REDIRECT [[Target#Anchor]]` hop: several monsters have no page of their own
        # (`Acid_Slime` -> `Slimes`, `Spiker` -> `Shapes#Spiker`, the gremlins -> `Gremlins`).
        title = page
        body = ""
        for _hop in range(3):
            url = "https://slaythespire.wiki.gg/index.php?title=%s&action=raw" % title
            try:
                body = opener.open(url, timeout=30).read().decode("utf-8")
            except Exception as exc:  # noqa: BLE001 - the report keeps the reason
                failed.append((key, type(exc).__name__))
                body = ""
                break
            redirect = None
            for line in body.splitlines()[:4]:
                match = line.strip().upper()
                if match.startswith("#REDIRECT"):
                    redirect = body.split("[[", 1)[1].split("]]", 1)[0].split("#", 1)[0]
                    break
            if redirect is None:
                break
            title = redirect.replace(" ", "_")
        if not body:
            continue
        if "{{Intents Table" not in body and "Asc|" not in body:
            failed.append((key, "no pattern table"))
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(body)
        ok += 1
    print("saved %d page(s)" % ok)
    for key, why in failed:
        print("  !! %-18s %s" % (key, why))


if __name__ == "__main__":
    main()

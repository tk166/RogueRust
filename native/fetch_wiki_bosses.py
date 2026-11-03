"""§194: pull the wikitext for the six bosses this content does not have yet.

Same reason as §190's fetcher: the rendered page collapses a multi-hit move's `×N` into the ascension
superscript, so only `action=raw` can be transcribed without guessing.
"""
import io
import os
import urllib.request

PROXY = "http://127.0.0.1:7897"
OUT = os.path.join("native", "wiki_asc")

PAGES = {
    "the_guardian": "The_Guardian",
    "hexaghost": "Hexaghost",
    "bronze_automaton": "Bronze_Automaton",
    "the_collector": "The_Collector",
    "awakened_one": "Awakened_One",
    "donu_and_deca": "Donu_and_Deca",
    "bronze_orb": "Bronze_Orb",
    "torch_head": "Torch_Head",
}


def main():
    os.makedirs(OUT, exist_ok=True)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    )
    opener.addheaders = [("User-Agent", "sts-tui-doccheck/1.0 (local research)")]
    for key, page in PAGES.items():
        path = os.path.join(OUT, key + ".txt")
        title = page
        body = ""
        for _hop in range(3):
            url = "https://slaythespire.wiki.gg/index.php?title=%s&action=raw" % title
            try:
                body = opener.open(url, timeout=40).read().decode("utf-8")
            except Exception as exc:  # noqa: BLE001
                print("  !! %-20s %s: %s" % (key, type(exc).__name__, exc))
                body = ""
                break
            redirect = None
            for line in body.splitlines()[:4]:
                if line.strip().upper().startswith("#REDIRECT"):
                    redirect = body.split("[[", 1)[1].split("]]", 1)[0].split("#", 1)[0]
                    break
            if redirect is None:
                break
            title = redirect.replace(" ", "_")
        if not body:
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(body)
        print("  saved %-20s %6d B  (%s)" % (key, len(body.encode("utf-8")), title))


if __name__ == "__main__":
    main()

"""從 AnimGenerator 角色選單（wai_character2 + custom）補進 data/characters.json。

規則：
- tag 命名比照現有：空白改底線（hatsune miku → hatsune_miku）
- 已有 tag 不重複
- 分不出性別 → female
- 確定不是人（寶可夢種族、索尼克動物、卡比、Haro 等）→ 去掉
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAI = Path(r"C:\Users\lanne\my-tool\AnimGenerator\wai")
OUT = ROOT / "data" / "characters.json"

SERIES_ZH = {
    "kantai_collection": "艦隊Collection",
    "touhou": "東方Project",
    "fate_(series)": "Fate",
    "fate/grand_order": "Fate/Grand Order",
    "pokemon": "寶可夢",
    "hololive": "Hololive",
    "blue_archive": "蔚藍檔案",
    "idolmaster": "偶像大師",
    "genshin_impact": "原神",
    "umamusume": "賽馬娘",
    "arknights": "明日方舟",
    "love_live!": "LoveLive!",
    "azur_lane": "碧藍航線",
    "honkai_(series)": "崩壞",
    "honkai:_star_rail": "崩壞：星穹鐵道",
    "honkai_impact_3rd": "崩壞3rd",
    "girls_und_panzer": "少女與戰車",
    "fire_emblem": "聖火降魔錄",
    "danganronpa_(series)": "彈丸論破",
    "nijisanji": "彩虹社",
    "jojo_no_kimyou_na_bouken": "JOJO的奇妙冒險",
    "persona": "女神異聞錄",
    "vocaloid": "VOCALOID",
    "final_fantasy": "Final Fantasy",
    "kemono_friends": "動物朋友",
    "girls'_frontline": "少女前線",
    "bishoujo_senshi_sailor_moon": "美少女戰士",
    "boku_no_hero_academia": "我的英雄學院",
    "mahou_shoujo_madoka_magica": "魔法少女小圓",
    "splatoon_(series)": "斯普拉遁",
    "world_witches_series": "世界魔女",
    "chainsaw_man": "鏈鋸人",
    "one_piece": "航海王",
    "omori": "OMORI",
    "toaru_majutsu_no_index": "魔法禁書目錄",
    "mario_(series)": "超級瑪利歐",
    "granblue_fantasy": "碧藍幻想",
    "guilty_gear": "聖騎士之戰",
    "bang_dream!": "BanG Dream!",
    "project_moon": "Project Moon",
    "touken_ranbu": "刀劍亂舞",
    "zenless_zone_zero": "絕區零",
    "wuthering_waves": "鳴潮",
    "limbus_company": "邊獄公司",
    "alien_stage": "ALIEN STAGE",
    "idoly_pride": "IDOLY PRIDE",
    "precure": "光之美少女",
    "gundam": "鋼彈",
    "code_geass": "反叛的魯路修",
    "spy_x_family": "間諜家家酒",
    "jujutsu_kaisen": "咒術迴戰",
    "naruto": "火影忍者",
    "naruto_(series)": "火影忍者",
    "bleach": "BLEACH",
    "steins;gate": "命運石之門",
    "k-on!": "輕音部",
    "kill_la_kill": "斬服少女",
    "re:zero_kara_hajimeru_isekai_seikatsu": "Re:0",
    "sword_art_online": "刀劍神域",
    "neon_genesis_evangelion": "新世紀福音戰士",
    "fullmetal_alchemist": "鋼之鍊金術師",
    "dragon_ball": "七龍珠",
    "resident_evil": "惡靈古堡",
    "the_legend_of_zelda": "薩爾達傳說",
    "rwby": "RWBY",
}

MALE_SERIES = {
    "touken_ranbu",
    "hypnosis_mic",
    "idolish7",
    "a3!",
    "tsukiuta",
}

# 只比完整 core tag，避免 mika/minato/sunny 誤傷女性
MALE_CORE = {
    "gojou_satoru", "gojo_satoru", "itadori_yuuji", "fushiguro_megumi",
    "nanami_kento", "ryoumen_sukuna", "getou_suguru",
    "cu_chulainn", "gilgamesh", "emiya_shirou", "merlin",
    "napoleon_bonaparte", "uryuu_ryuunosuke",
    "giorno_giovanna", "higashikata_josuke", "johnny_joestar",
    "bruno_bucciarati", "guido_mista", "kishibe_rohan",
    "joseph_joestar", "kujo_jotaro", "dio_brando",
    "kirito", "satou_kazuma", "natsuki_subaru", "okabe_rintarou",
    "lelouch_vi_britannia", "kururugi_suzaku",
    "diluc", "alhaitham", "kaeya", "tighnari", "neuvillette",
    "kaveh", "cyno", "xingqiu", "chongyun", "wriothesley", "lyney",
    "arataki_itto", "thoma", "gorou", "zhongli", "xiao", "venti",
    "tartaglia", "scaramouche", "wanderer", "aether",
    "dan_heng", "blade", "aventurine", "dr._ratio", "phainon", "mydei",
    "caelus", "jing_yuan", "welt", "gepard", "boothill", "argenti",
    "sunday", "gallagher", "jiaoqiu", "moze", "luocha", "yanqing",
    "wise", "lighter", "lycaon", "von_lycaon", "harumasa", "asaba_harumasa",
    "seth_lowell", "anton_ivanov", "billy_kid", "ben_bigger", "hugo_vlad",
    "sol_badguy", "ky_kiske",
    "leon", "raihan", "ethan", "blue_oak", "hilbert", "brendan",
    "n_(pokemon)", "silver_(pokemon)", "james", "florian", "elio",
    "gladion", "hop", "piers", "victor", "calem", "lucas", "bede",
    "nate", "steven_stone", "grusha", "goh", "cheren", "arven", "ingo",
    "kieran", "ash_ketchum",
    "midoriya_izuku", "bakugou_katsuki", "todoroki_shouto",
    "monkey_d._luffy", "roronoa_zoro", "sanji", "trafalgar_law",
    "portgas_d._ace", "uzumaki_naruto", "uchiha_sasuke",
    "son_goku", "son_gohan", "vegeta", "trunks",
    "ikari_shinji", "nagisa_kaworu",
    "denji", "hayakawa_aki",
    "oma_kokichi", "saihara_shuichi", "komaeda_nagito", "hinata_hajime",
    "naegi_makoto", "momota_kaito",
    "cloud_strife", "zack_fair", "sephiroth", "squall_leonhart",
    "ike", "marth", "chrom", "dimitri_alexandre_blaiddyd",
    "claude_von_riegan",
    "link", "toon_link", "luigi", "mario",
    "edward_elric", "alphonse_elric", "roy_mustang",
    "twilight", "loid_forger",
    "kel_(omori)", "hero_(omori)", "basil",
    "narukami_yuu", "yuuki_makoto", "amamiya_ren", "tatsumi_kanji",
    "rimuru_tempest", "rimuru",
    "leon_s._kennedy", "theodore_riddle",
    "p-head_producer", "t-head_admiral", "little_boy_admiral",
    "mikazuki_munechika", "kashuu_kiyomitsu", "yamato-no-kami_yasusada",
    "tsurumaru_kuninaga", "namazuo_toushirou", "honebami_toushirou",
    "midare_toushirou", "izumi-no-kami_kanesada",
    "albedo_(genshin_impact)",
}

FEMALE_CORE = {
    "jougasaki_mika", "kiryu_coco", "yagami_hayate", "sunny_milk",
    "mika_(girls_und_panzer)", "merlin_prismriver", "minato_aqua",
    "kirigaya_suguha", "silver_fox", "baiken", "aki_rosenthal",
    "katou_megumi", "izayoi_aki", "awa_subaru", "malenia_blade_of_miquella",
    "albedo_(overlord)", "saniwa", "yang_xiao_long", "faust_(project_moon)",
}

NON_PERSON_NAME = re.compile(
    r"^(pikachu|eevee|charizard|mewtwo|mew|squirtle|bulbasaur|charmander|"
    r"rowlet|piplup|oshawott|snivy|tepig|mudkip|torchic|chikorita|cyndaquil|"
    r"totodile|treecko|turtwig|chimchar|chespin|fennekin|froakie|litten|"
    r"popplio|grookey|scorbunny|sobble|sprigatito|fuecoco|quaxly|lucario|"
    r"gengar|gardevoir|mega_gardevoir|kirlia|lopunny|sylveon|umbreon|"
    r"glaceon|espeon|flareon|vaporeon|leafeon|jolteon|jigglypuff|mimikyu|"
    r"morpeko|jirachi|meowth|meowscarada|garchomp|braixen|rotom|rotom_phone|"
    r"pichu|kirby|meta_knight|sonic_the_hedgehog|tails|shadow_the_hedgehog|"
    r"blaze_the_cat|rouge_the_bat|amy_rose|knuckles_the_echidna|"
    r"yoshi|bowser|haro)$",
    re.I,
)
NON_PERSON_SERIES = {"sonic_(series)", "kirby_(series)"}
POKEMON_HUMAN_NO_PAREN = {
    "ash_ketchum", "blue_oak", "steven_stone", "professor_oak",
}


def norm_tag(tag: str) -> str:
    t = (tag or "").strip().lower().replace(" ", "_")
    return re.sub(r"_+", "_", t)


def parse_title(title: str) -> tuple[str, str, str, str]:
    parts = [p.strip() for p in title.split(",") if p.strip()]
    if len(parts) >= 3:
        series_tag, char, series_readable = parts[0], ", ".join(parts[1:-1]), parts[-1]
    elif len(parts) == 2:
        series_tag, char, series_readable = parts[0], parts[1], parts[0]
    else:
        series_tag, char, series_readable = "", (parts[0] if parts else title), ""
    return norm_tag(char), series_tag, series_readable, char


def clean_zh(zh: str) -> str:
    zh = (zh or "").strip()
    zh = re.sub(r"\s*\([^)]*\)\s*$", "", zh)
    bits = [p.strip() for p in zh.split(",") if p.strip()]
    if len(bits) == 3 and bits[0] == bits[2]:
        return bits[1]
    return zh


def core_name(tag: str) -> str:
    return re.sub(r"_\([^)]*\)", "", tag).strip("_")


def is_non_person(tag: str, series_tag: str, char: str) -> bool:
    if series_tag in NON_PERSON_SERIES:
        return True
    if NON_PERSON_NAME.match(tag) or NON_PERSON_NAME.match(core_name(tag)):
        return True
    if "non-human" in tag or "non_human" in tag:
        return True
    if series_tag == "pokemon":
        if "(pokemon)" in char.lower():
            return False
        if tag in POKEMON_HUMAN_NO_PAREN:
            return False
        return True
    if tag in {"haro", "rotom_phone", "rotom"}:
        return True
    return False


def gender_of(tag: str, series_tag: str, char: str, existing: dict[str, str]) -> str:
    n = norm_tag(tag)
    core = core_name(n)
    low = f"{tag} {char}".lower()
    if re.search(r"\(female\)|_female\b|\b1girl\b", low):
        return "female"
    if n in FEMALE_CORE or core in FEMALE_CORE:
        return "female"
    if n in existing and existing[n] in {"female", "male"}:
        return existing[n]
    if re.search(r"\(male\)|_male\b|\b1boy\b", low):
        return "male"
    if "saniwa" in n:
        return "female"
    if series_tag in MALE_SERIES:
        return "male"
    if re.search(r"\badmiral\b", low):
        return "male"
    if n in MALE_CORE or core in MALE_CORE:
        return "male"
    return "female"


def series_label(series_tag: str, series_readable: str) -> str:
    if series_tag in SERIES_ZH:
        return SERIES_ZH[series_tag]
    if series_readable:
        return series_readable.strip()
    return series_tag.replace("_", " ")


def load_titles() -> list[str]:
    text = (WAI / "wai_character2.json").read_text(encoding="utf-8")
    titles = re.findall(r'"title":\s*"((?:\\.|[^"\\])*)"', text)
    custom = json.loads((WAI / "custom_character.json").read_text(encoding="utf-8"))
    for k in custom:
        if k and k != "random":
            titles.append(k)
    seen, out = set(), []
    for t in titles:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def load_zh_map() -> dict[str, str]:
    raw = json.loads((WAI / "zh_TW.json").read_text(encoding="utf-8"))
    return {v: clean_zh(k) for k, v in raw.items() if k and v}


def main() -> None:
    blob = json.loads(OUT.read_text(encoding="utf-8"))
    old = [x for x in blob["characters"] if int(x.get("rank") or 0) <= 500]
    existing_gender = {norm_tag(x["tag"]): x["gender"] for x in old}
    existing_tags = {norm_tag(x["tag"]) for x in old}

    zh_map = load_zh_map()
    added, skipped_nonperson = [], []
    skipped_exist = 0

    for title in load_titles():
        tag, series_tag, series_readable, char = parse_title(title)
        if not tag:
            continue
        if is_non_person(tag, series_tag, char):
            skipped_nonperson.append(tag)
            continue
        if norm_tag(tag) in existing_tags:
            skipped_exist += 1
            continue
        g = gender_of(tag, series_tag, char, existing_gender)
        added.append({
            "rank": 500 + len(added) + 1,
            "tag": tag,
            "zh": zh_map.get(title) or "",
            "gender": g,
            "series": series_label(series_tag, series_readable),
            "posts": "",
        })
        existing_tags.add(norm_tag(tag))

    males = [x for x in added if x["gender"] == "male"]
    females = [x for x in added if x["gender"] == "female"]
    print(f"old {len(old)}  add {len(added)}  female {len(females)}  male {len(males)}")
    print(f"skip exist {skipped_exist}  nonperson {len(skipped_nonperson)}")
    print("nonperson:", ", ".join(skipped_nonperson[:40]))
    print("males:")
    for x in males:
        print(f"  {x['tag']:42s} {x['zh']}")

    blob["source"] = "danbooru_top500+wai_character2"
    blob["date"] = "2026-09-21"
    blob["characters"] = old + added
    OUT.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT, "total", len(blob["characters"]))


if __name__ == "__main__":
    main()

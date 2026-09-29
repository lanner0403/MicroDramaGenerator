"""常見成人衣著／場景主題。全部預設為成年角色換裝，不含未成年相關主題。"""
from __future__ import annotations

# key → {label, tags, scene, motion}
# tags：Illustrious 靜態首幀
# scene：場景補充
# motion：LTX 動作描述用的中文環境一句
THEMES: dict[str, dict] = {
    "original": {
        "label": "原作衣著（不換裝）",
        "tags": "",
        "scene": "",
        "motion": "",
    },
    "casual": {
        "label": "一般服裝",
        "tags": "alternate costume, casual clothes, streetwear, t-shirt, skirt, everyday outfit, not a costume, not a uniform",
        "scene": "",
        "motion": "",
    },
    "school": {
        "label": "學校制服",
        "tags": "alternate costume, school uniform, sailor uniform, serafuku, sailor collar, pleated skirt, loafers",
        "scene": "school classroom, desks, blackboard, indoor",
        "motion": "在教室裡",
    },
    "sweater": {
        "label": "毛衣",
        "tags": "alternate costume, sweater, knit sweater, long sleeves, skirt, casual clothes",
        "scene": "",
        "motion": "",
    },
    "hoodie": {
        "label": "帽T",
        "tags": "alternate costume, hoodie, hooded sweatshirt, casual clothes, pants",
        "scene": "",
        "motion": "",
    },
    "office": {
        "label": "辦公室 OL",
        "tags": "alternate costume, office lady, business suit, white blouse, pencil skirt, black stockings, high heels, indoor office",
        "scene": "modern office interior, desk, window blinds",
        "motion": "在辦公室裡",
    },
    "secretary": {
        "label": "秘書",
        "tags": "alternate costume, secretary, tight blouse, unbuttoned shirt, pencil skirt, garter belt, glasses, indoor office",
        "scene": "executive office, leather sofa, city night window",
        "motion": "在主管辦公室裡",
    },
    "maid": {
        "label": "女僕",
        "tags": "alternate costume, maid, maid headdress, frilled apron, black dress, white thighhighs, Mary Janes",
        "scene": "victorian mansion interior, polished floor",
        "motion": "在宅邸客廳裡",
    },
    "bunny": {
        "label": "兔女郎",
        "tags": "alternate costume, playboy bunny, bunny ears, strapless leotard, pantyhose, bowtie, wrist cuffs, high heels",
        "scene": "dim casino lounge, neon lights",
        "motion": "在酒吧卡座旁",
    },
    "nurse": {
        "label": "護士",
        "tags": "alternate costume, nurse, nurse cap, white nurse dress, short dress, white stockings, red cross",
        "scene": "hospital room, white curtains, bed",
        "motion": "在病房裡",
    },
    "swimsuit": {
        "label": "泳裝",
        "tags": "alternate costume, bikini, micro bikini, wet skin, beach",
        "scene": "sunny beach, ocean, bright daylight",
        "motion": "在海邊",
    },
    "sling_bikini": {
        "label": "吊帶比基尼",
        "tags": "alternate costume, slingshot swimsuit, highleg bikini, tan lines, wet body",
        "scene": "private pool, night lights",
        "motion": "在泳池邊",
    },
    "lingerie": {
        "label": "內衣",
        "tags": "alternate costume, lingerie, lace bra, panties, garter belt, stockings, indoor",
        "scene": "bedroom, rumpled sheets, warm lamp",
        "motion": "在臥室裡",
    },
    "sheer": {
        "label": "透明睡衣",
        "tags": "alternate costume, see-through, sheer negligee, no bra, indoors, night",
        "scene": "hotel suite, city night window",
        "motion": "在飯店套房裡",
    },
    "cheongsam": {
        "label": "旗袍",
        "tags": "alternate costume, china dress, cheongsam, high slits, floral print, side slit",
        "scene": "chinese teahouse interior, red lanterns",
        "motion": "在茶樓包廂裡",
    },
    "kimono": {
        "label": "和服／浴衣",
        "tags": "alternate costume, kimono, yukata, sash, floral pattern, bare shoulders",
        "scene": "japanese inn, tatami, paper lantern",
        "motion": "在和室裡",
    },
    "miko": {
        "label": "巫女",
        "tags": "alternate costume, miko, red hakama, white haori, hair ribbon, shrine maiden",
        "scene": "shinto shrine at dusk, torii",
        "motion": "在神社迴廊",
    },
    "nun": {
        "label": "修女",
        "tags": "alternate costume, nun, habit, cross necklace, thighhighs, revealing clothes",
        "scene": "church interior at night, stained glass",
        "motion": "在教堂懺悔室",
    },
    "succubus": {
        "label": "魅魔",
        "tags": "alternate costume, succubus, demon horns, demon tail, bat wings, revealing clothes, pentagram",
        "scene": "dark bedroom, purple candlelight",
        "motion": "在昏暗臥室裡",
    },
    "witch": {
        "label": "魔女",
        "tags": "alternate costume, witch, witch hat, revealing robe, pentacle, magic circle",
        "scene": "candlelit study, grimoire, night window",
        "motion": "在魔法書房裡",
    },
    "vampire": {
        "label": "吸血鬼",
        "tags": "alternate costume, vampire, pale skin, red eyes, gothic dress, fangs, choker",
        "scene": "gothic castle bedroom, moonlight",
        "motion": "在古堡臥室裡",
    },
    "idol": {
        "label": "偶像舞台",
        "tags": "alternate costume, idol, stage costume, microphone, glitter, thighhighs, concert",
        "scene": "concert stage, spotlights, bokeh",
        "motion": "在舞台燈光下",
    },
    "race_queen": {
        "label": "賽車女郎",
        "tags": "alternate costume, race queen, tight bodysuit, zipper, high heels, gloves",
        "scene": "paddock, race car, afternoon sun",
        "motion": "在賽車場後台",
    },
    "yoga": {
        "label": "瑜珈／運動",
        "tags": "alternate costume, yoga pants, sports bra, sweat, toned, gym",
        "scene": "gym studio, mirrors, wooden floor",
        "motion": "在健身房裡",
    },
    "leather": {
        "label": "皮革／束縛風",
        "tags": "alternate costume, black leather, tight clothes, choker, gloves, high heels",
        "scene": "dim lounge, red lighting",
        "motion": "在暗室裡",
    },
    "police": {
        "label": "女警",
        "tags": "alternate costume, police uniform, peaked cap, necktie, miniskirt, handcuffs",
        "scene": "police station office at night",
        "motion": "在警局值班室",
    },
    "flight": {
        "label": "空姐",
        "tags": "alternate costume, flight attendant, neckerchief, pencil skirt, pantyhose, indoor",
        "scene": "first class cabin, night flight",
        "motion": "在客艙走道",
    },
    "bartender": {
        "label": "調酒師",
        "tags": "alternate costume, bartender, vest, white shirt, unbuttoned, bowtie, black shorts",
        "scene": "dim cocktail bar, bottles, neon",
        "motion": "在吧台後",
    },
    "onsen": {
        "label": "溫泉",
        "tags": "alternate costume, onsen, towel, wet skin, steam, completely nude under towel",
        "scene": "outdoor onsen, night, steam, rocks",
        "motion": "在露天溫泉",
    },
    "wedding": {
        "label": "婚紗",
        "tags": "alternate costume, wedding dress, veil, cleavage, white dress, indoor",
        "scene": "hotel bridal suite, roses",
        "motion": "在新娘套房裡",
    },
    "christmas": {
        "label": "聖誕",
        "tags": "alternate costume, santa costume, santa hat, fur trim, red bikini, christmas",
        "scene": "christmas living room, tree, fireplace",
        "motion": "在聖誕客廳裡",
    },
    "halloween": {
        "label": "萬聖節",
        "tags": "alternate costume, halloween costume, pumpkin, black dress, witch hat, night",
        "scene": "halloween party, orange lights",
        "motion": "在萬聖節派對",
    },
    "nude": {
        "label": "全裸",
        "tags": "completely nude, nude, uncensored, nipples, pussy",
        "scene": "bedroom, soft light",
        "motion": "全身赤裸",
    },
    "topless": {
        "label": "上身裸",
        "tags": "topless, nipples, bottom clothes only, uncensored",
        "scene": "indoor, warm light",
        "motion": "上身赤裸",
    },
    "unconscious": {
        "label": "迷姦",
        "tags": "unconscious, asleep, sleeping, closed eyes, limp, sleeping sex",
        "scene": "dingy rental apartment, single bed, indoor, lit room, warm bedside lamp, ceiling light on, not dark",
        "motion": "昏迷不醒地躺在床上",
    },
    "drugged": {
        "label": "藥姦",
        "tags": "drugged, intoxicated, drowsy, flushed, heavy eyelids, unfocused eyes, aphrodisiac",
        "scene": "hotel bedroom, empty glass on the nightstand, indoor, warm lamp, rumpled sheets",
        "motion": "被下藥後癱在床上",
    },
    "black_pantyhose": {
        "label": "黑絲襪",
        "tags": "black pantyhose, sheer black stockings, shiny pantyhose, long legs, indoor",
        "scene": "bedroom, warm lamp",
        "motion": "穿著黑絲襪",
    },
    "white_pantyhose": {
        "label": "白絲襪",
        "tags": "white pantyhose, sheer white stockings, glossy pantyhose, long legs, indoor",
        "scene": "bright bedroom, soft daylight",
        "motion": "穿著白絲襪",
    },
    "bodystocking": {
        "label": "連體絲襪",
        "tags": "bodystocking, sheer bodystocking, see-through, full body pantyhose, indoor",
        "scene": "bedroom, dim warm light",
        "motion": "穿著連體絲襪",
    },
    "black_thighhighs": {
        "label": "黑色過膝襪",
        "tags": "black thighhighs, over-knee socks, zettai ryouiki, long legs, indoor",
        "scene": "indoor, wooden floor",
        "motion": "穿著黑色過膝襪",
    },
    "white_thighhighs": {
        "label": "白色過膝襪",
        "tags": "white thighhighs, over-knee socks, zettai ryouiki, long legs, indoor",
        "scene": "bright indoor",
        "motion": "穿著白色過膝襪",
    },
    "garter_stockings": {
        "label": "吊帶絲襪",
        "tags": "garter belt, garter straps, stockings, black lace, lingerie, indoor",
        "scene": "bedroom, rumpled sheets",
        "motion": "穿著吊帶絲襪",
    },
    "fishnet": {
        "label": "漁網襪",
        "tags": "fishnet stockings, fishnet pantyhose, black fishnets, long legs, indoor",
        "scene": "dim lounge, neon",
        "motion": "穿著漁網襪",
    },
    "sheer_stockings": {
        "label": "透明絲襪",
        "tags": "sheer stockings, translucent pantyhose, glossy legs, indoor",
        "scene": "hotel room, lamp light",
        "motion": "穿著透明絲襪",
    },
    "short_socks": {
        "label": "短襪",
        "tags": "short socks, ankle socks, socks, bare legs, indoor",
        "scene": "indoor, wooden floor",
        "motion": "穿著短襪",
    },
}


# 男角色衣著。只改 partner 參考圖，不改場景。
MALE_THEMES: dict[str, dict] = {
    "original": {
        "label": "原作衣著（不換裝）",
        "tags": "",
    },
    "casual": {
        "label": "一般服裝",
        "tags": "alternate costume, casual clothes, t-shirt, jeans, sneakers, everyday outfit, not a costume, not a uniform",
    },
    "school": {
        "label": "學校制服",
        "tags": "alternate costume, school uniform, gakuran, school blazer, necktie, white shirt, slacks, loafers, male school uniform",
    },
    "suit": {
        "label": "西裝",
        "tags": "alternate costume, business suit, black suit, dress shirt, necktie, leather shoes",
    },
    "office": {
        "label": "襯衫領帶",
        "tags": "alternate costume, white dress shirt, loosened necktie, slacks, indoor office",
    },
    "hoodie": {
        "label": "帽T",
        "tags": "alternate costume, hoodie, hooded sweatshirt, jeans, sneakers, casual",
    },
    "sweater": {
        "label": "毛衣",
        "tags": "alternate costume, sweater, knit sweater, long sleeves, slacks, casual",
    },
    "sports": {
        "label": "運動服",
        "tags": "alternate costume, tracksuit, sportswear, athletic wear, sneakers",
    },
    "tank": {
        "label": "背心短褲",
        "tags": "alternate costume, tank top, shorts, casual, indoor",
    },
    "kimono": {
        "label": "浴衣／和服",
        "tags": "alternate costume, yukata, male kimono, sash, japanese clothes",
    },
    "police": {
        "label": "警察制服",
        "tags": "alternate costume, police uniform, peaked cap, necktie, slacks, male",
    },
    "bartender": {
        "label": "調酒師",
        "tags": "alternate costume, bartender, vest, white shirt, bowtie, black pants",
    },
    "leather": {
        "label": "皮衣",
        "tags": "alternate costume, leather jacket, black pants, boots",
    },
    "nude": {
        "label": "全裸",
        "tags": "completely nude, nude, uncensored",
    },
}


def theme_of(key: str | None) -> dict | None:
    if not key:
        return None
    if key not in THEMES:
        raise ValueError(f"未知主題: {key}（可用: {', '.join(THEMES)}）")
    return THEMES[key]


def theme_labels() -> dict[str, str]:
    return {k: v["label"] for k, v in THEMES.items()}


def male_theme_of(key: str | None) -> dict | None:
    if not key:
        return None
    if key not in MALE_THEMES:
        raise ValueError(f"未知男衣著: {key}（可用: {', '.join(MALE_THEMES)}）")
    return MALE_THEMES[key]


def male_theme_labels() -> dict[str, str]:
    return {k: v["label"] for k, v in MALE_THEMES.items()}


def random_theme_key(rng=None) -> str:
    import random
    rng = rng or random.Random()
    keys = [k for k in THEMES if k != "original"]
    return rng.choice(keys) if keys else "original"


# key → {label, group, tags, motion}
# tags：Illustrious 場景；motion：中文環境一句
# 不指定場景時用主題自帶 scene／motion
SCENES: dict[str, dict] = {
    "hotel": {
        "label": "旅館房間",
        "group": "住宿／房間",
        "tags": "hotel room, double bed, warm lamp, night, indoor, curtains",
        "motion": "在旅館房間裡",
    },
    "love_hotel": {
        "label": "愛情旅館",
        "group": "住宿／房間",
        "tags": "love hotel, red lighting, large bed, mirrors, indoor, night",
        "motion": "在愛情旅館裡",
    },
    "hotel_suite": {
        "label": "飯店套房",
        "group": "住宿／房間",
        "tags": "hotel suite, city night window, king bed, luxury interior",
        "motion": "在飯店套房裡",
    },
    "bedroom": {
        "label": "臥室",
        "group": "住宿／房間",
        "tags": "bedroom, rumpled sheets, warm lamp, indoor, bed",
        "motion": "在臥室裡",
    },
    "room": {
        "label": "房間",
        "group": "住宿／房間",
        "tags": "indoor room, simple furniture, wooden floor, window light",
        "motion": "在房間裡",
    },
    "rental": {
        "label": "出租屋",
        "group": "住宿／房間",
        "tags": "dingy rental apartment, single bed, indoor, lit room, warm bedside lamp, ceiling light on, not dark",
        "motion": "在出租屋裡",
    },
    "living_room": {
        "label": "客廳",
        "group": "住宿／房間",
        "tags": "living room, sofa, TV, indoor, warm light",
        "motion": "在客廳裡",
    },
    "tatami": {
        "label": "和室",
        "group": "住宿／房間",
        "tags": "japanese room, tatami, futon, paper sliding door, indoor",
        "motion": "在和室裡",
    },
    "kitchen": {
        "label": "廚房",
        "group": "住宿／房間",
        "tags": "kitchen, counter, indoor, tiled floor, cabinets",
        "motion": "在廚房裡",
    },
    "balcony": {
        "label": "陽台",
        "group": "住宿／房間",
        "tags": "apartment balcony, night city, railing, outdoor",
        "motion": "在陽台上",
    },
    "classroom": {
        "label": "學校教室",
        "group": "校園",
        "tags": "school classroom, desks, blackboard, empty classroom, afternoon sunlight, indoor",
        "motion": "在教室裡",
    },
    "school_hallway": {
        "label": "學校走廊",
        "group": "校園",
        "tags": "school hallway, lockers, windows, indoor, empty corridor",
        "motion": "在學校走廊",
    },
    "gym_storage": {
        "label": "體育倉庫",
        "group": "校園",
        "tags": "gym storage room, sports equipment, mats, vaulting horse, dim indoor, school gym warehouse",
        "motion": "在體育倉庫裡",
    },
    "gym": {
        "label": "體育館",
        "group": "校園",
        "tags": "school gymnasium, wooden floor, basketball hoops, indoor, high ceiling",
        "motion": "在體育館裡",
    },
    "clubroom": {
        "label": "社團教室",
        "group": "校園",
        "tags": "school clubroom, sofa, posters, indoor, afternoon light",
        "motion": "在社團教室裡",
    },
    "library": {
        "label": "圖書館",
        "group": "校園",
        "tags": "library, bookshelves, reading desks, indoor, quiet",
        "motion": "在圖書館裡",
    },
    "infirmary": {
        "label": "保健室",
        "group": "校園",
        "tags": "school infirmary, white bed, curtains, indoor, medicine cabinet",
        "motion": "在保健室裡",
    },
    "school_rooftop": {
        "label": "學校屋頂",
        "group": "校園",
        "tags": "school rooftop, chain-link fence, blue sky, outdoor",
        "motion": "在學校屋頂",
    },
    "in_pool": {
        "label": "游泳池裡",
        "group": "水邊",
        "tags": "in swimming pool, pool water, wet skin, indoor pool, splashing",
        "motion": "在游泳池裡",
    },
    "poolside": {
        "label": "游泳池邊",
        "group": "水邊",
        "tags": "poolside, swimming pool edge, wet tiles, lounge chair, outdoor",
        "motion": "在游泳池邊",
    },
    "beach": {
        "label": "海邊",
        "group": "水邊",
        "tags": "sunny beach, ocean, bright daylight, sand, outdoor",
        "motion": "在海邊",
    },
    "beach_night": {
        "label": "夜海",
        "group": "水邊",
        "tags": "night beach, moonlight, ocean, wet sand, outdoor",
        "motion": "在夜裡的海邊",
    },
    "onsen_outdoor": {
        "label": "露天溫泉",
        "group": "水邊",
        "tags": "outdoor onsen, rocks, steam, night, lantern, trees",
        "motion": "在露天溫泉",
    },
    "onsen_indoor": {
        "label": "室內溫泉",
        "group": "水邊",
        "tags": "indoor onsen, wooden bath, steam, tiles, lantern light",
        "motion": "在室內溫泉",
    },
    "bath": {
        "label": "浴室",
        "group": "廁所／浴室",
        "tags": "bathroom, bathtub, tiles, steam, indoor, mirror",
        "motion": "在浴室裡",
    },
    "shower": {
        "label": "淋浴間",
        "group": "廁所／浴室",
        "tags": "shower stall, wet tiles, steam, shower head, indoor",
        "motion": "在淋浴間裡",
    },
    "sauna": {
        "label": "三溫暖",
        "group": "廁所／浴室",
        "tags": "sauna, wooden benches, steam, dim warm light, indoor",
        "motion": "在三溫暖裡",
    },
    "locker_room": {
        "label": "更衣室",
        "group": "廁所／浴室",
        "tags": "locker room, metal lockers, wooden bench, indoor, fluorescent light",
        "motion": "在更衣室裡",
    },
    "womens_restroom": {
        "label": "女廁",
        "group": "廁所／浴室",
        "tags": "women's restroom, bathroom stalls, sinks, tiled walls, indoor, fluorescent light",
        "motion": "在女廁裡",
    },
    "mens_restroom": {
        "label": "男廁",
        "group": "廁所／浴室",
        "tags": "men's restroom, urinals, bathroom stalls, tiled walls, indoor, fluorescent light",
        "motion": "在男廁裡",
    },
    "public_toilet": {
        "label": "公廁隔間",
        "group": "廁所／浴室",
        "tags": "public restroom stall, toilet stall, tiled wall, indoor, cramped",
        "motion": "在公廁隔間裡",
    },
    "office": {
        "label": "辦公室",
        "group": "室內其他",
        "tags": "office interior, desks, computer monitors, window blinds, indoor, night",
        "motion": "在辦公室裡",
    },
    "elevator": {
        "label": "電梯",
        "group": "室內其他",
        "tags": "elevator interior, mirrored walls, fluorescent light, indoor, cramped",
        "motion": "在電梯裡",
    },
    "stairwell": {
        "label": "樓梯間",
        "group": "室內其他",
        "tags": "stairwell, concrete stairs, dim light, indoor",
        "motion": "在樓梯間裡",
    },
    "basement": {
        "label": "地下室",
        "group": "室內其他",
        "tags": "basement, dim light, concrete walls, indoor",
        "motion": "在地下室裡",
    },
    "warehouse": {
        "label": "倉庫",
        "group": "室內其他",
        "tags": "warehouse, cardboard boxes, dim indoor, concrete floor",
        "motion": "在倉庫裡",
    },
    "karaoke": {
        "label": "卡拉OK包廂",
        "group": "室內其他",
        "tags": "karaoke booth, sofa, microphone, dim colorful lights, indoor",
        "motion": "在卡拉OK包廂裡",
    },
    "bar": {
        "label": "酒吧",
        "group": "室內其他",
        "tags": "dim cocktail bar, bottles, neon, indoor, night",
        "motion": "在酒吧裡",
    },
    "nightclub": {
        "label": "夜店",
        "group": "室內其他",
        "tags": "nightclub, neon lights, dance floor, dark indoor",
        "motion": "在夜店裡",
    },
    "hospital": {
        "label": "病房",
        "group": "室內其他",
        "tags": "hospital room, white curtains, bed, indoor",
        "motion": "在病房裡",
    },
    "train": {
        "label": "電車廂",
        "group": "室內其他",
        "tags": "train interior, seats, windows, fluorescent light, night",
        "motion": "在電車廂裡",
    },
    "car": {
        "label": "車內",
        "group": "室內其他",
        "tags": "car interior, back seat, night, windows, cramped",
        "motion": "在車裡",
    },
    "alley": {
        "label": "暗巷",
        "group": "室外",
        "tags": "dark alley, narrow brick alley, dim street lamp, night, outdoor",
        "motion": "在暗巷裡",
    },
    "street_night": {
        "label": "夜街",
        "group": "室外",
        "tags": "city street at night, neon signs, wet asphalt, outdoor",
        "motion": "在夜街上",
    },
    "rain_street": {
        "label": "雨夜街頭",
        "group": "室外",
        "tags": "rainy city street at night, neon reflections, wet asphalt, outdoor",
        "motion": "在雨夜街頭",
    },
    "park": {
        "label": "公園",
        "group": "室外",
        "tags": "park, trees, path, benches, outdoor, dusk",
        "motion": "在公園裡",
    },
    "forest": {
        "label": "森林",
        "group": "室外",
        "tags": "forest, trees, dappled light, outdoor, moss",
        "motion": "在森林裡",
    },
    "parking": {
        "label": "停車場",
        "group": "室外",
        "tags": "parking lot, cars, street lamps, night, outdoor",
        "motion": "在停車場",
    },
    "underpass": {
        "label": "橋下",
        "group": "室外",
        "tags": "underpass, concrete pillars, dim light, outdoor, night",
        "motion": "在橋下",
    },
    "rooftop_night": {
        "label": "夜屋頂",
        "group": "室外",
        "tags": "building rooftop at night, city lights, water tank, outdoor",
        "motion": "在夜裡的屋頂",
    },
    "shrine": {
        "label": "神社",
        "group": "室外",
        "tags": "shinto shrine, torii, stone path, dusk, outdoor",
        "motion": "在神社裡",
    },
    "empty_lot": {
        "label": "空地",
        "group": "室外",
        "tags": "empty lot, chain-link fence, night, outdoor, weeds",
        "motion": "在空地上",
    },
    "mountain": {
        "label": "山岳",
        "group": "室外",
        "tags": "mountain peak, rocky cliff, clouds, outdoor, vast sky",
        "motion": "在山岳上",
    },
    "desert": {
        "label": "沙漠",
        "group": "室外",
        "tags": "desert dunes, scorching sun, sand, outdoor, heat haze",
        "motion": "在沙漠裡",
    },
    "snowfield": {
        "label": "雪原",
        "group": "室外",
        "tags": "snow field, falling snow, winter, outdoor, white landscape",
        "motion": "在雪原上",
    },
    "lake": {
        "label": "湖畔",
        "group": "室外",
        "tags": "lakeside, still water, reeds, outdoor, dusk",
        "motion": "在湖畔",
    },
    "cathedral": {
        "label": "大教堂",
        "group": "建築",
        "tags": "gothic cathedral interior, stained glass, high vaulted ceiling, pews, indoor",
        "motion": "在大教堂裡",
    },
    "castle_hall": {
        "label": "城堡大廳",
        "group": "建築",
        "tags": "castle great hall, stone columns, banners, chandelier, indoor",
        "motion": "在城堡大廳裡",
    },
    "palace_corridor": {
        "label": "宮殿迴廊",
        "group": "建築",
        "tags": "palace corridor, marble floor, gold ornaments, tall windows, indoor",
        "motion": "在宮殿迴廊",
    },
    "temple_hall": {
        "label": "寺廟大殿",
        "group": "建築",
        "tags": "temple hall, incense, wooden pillars, statues, indoor",
        "motion": "在寺廟大殿裡",
    },
    "shopping_mall": {
        "label": "購物中心",
        "group": "建築",
        "tags": "shopping mall atrium, glass ceiling, stores, indoor, crowds empty",
        "motion": "在購物中心",
    },
    "subway": {
        "label": "地鐵站",
        "group": "建築",
        "tags": "subway station, tiled walls, platform, fluorescent light, indoor",
        "motion": "在地鐵站裡",
    },
    "museum": {
        "label": "博物館",
        "group": "建築",
        "tags": "museum gallery, exhibits, marble floor, high ceiling, indoor",
        "motion": "在博物館裡",
    },
    "clock_tower": {
        "label": "鐘樓",
        "group": "建築",
        "tags": "clock tower interior, gears, wooden beams, high window, indoor",
        "motion": "在鐘樓裡",
    },
    "abandoned_factory": {
        "label": "廢棄工廠",
        "group": "建築",
        "tags": "abandoned factory, rusted machinery, broken windows, dusty light, indoor",
        "motion": "在廢棄工廠裡",
    },
    "greenhouse": {
        "label": "玻璃溫室",
        "group": "建築",
        "tags": "glass greenhouse, tropical plants, sunlight, mist, indoor",
        "motion": "在溫室裡",
    },
    "skyscraper": {
        "label": "摩天樓大廳",
        "group": "建築",
        "tags": "skyscraper lobby, glass walls, city view, marble, indoor, night",
        "motion": "在摩天樓大廳",
    },
    "bridge": {
        "label": "大橋",
        "group": "建築",
        "tags": "long bridge, city river, night lights, outdoor, wind",
        "motion": "在大橋上",
    },
    "magic_academy": {
        "label": "魔法學院",
        "group": "幻想",
        "tags": "magic academy hall, floating candles, spellbooks, stained glass, indoor",
        "motion": "在魔法學院裡",
    },
    "wizard_tower": {
        "label": "法師塔",
        "group": "幻想",
        "tags": "wizard tower study, crystal ball, star charts, night window, indoor",
        "motion": "在法師塔裡",
    },
    "floating_island": {
        "label": "浮空島",
        "group": "幻想",
        "tags": "floating island, clouds below, ancient ruins, outdoor, sky",
        "motion": "在浮空島上",
    },
    "crystal_cave": {
        "label": "水晶洞窟",
        "group": "幻想",
        "tags": "crystal cave, glowing crystals, underground, reflections, indoor",
        "motion": "在水晶洞窟裡",
    },
    "elven_forest": {
        "label": "精靈森林",
        "group": "幻想",
        "tags": "elven forest, giant trees, glowing flora, moonlight, outdoor",
        "motion": "在精靈森林裡",
    },
    "dragon_lair": {
        "label": "龍巢",
        "group": "幻想",
        "tags": "dragon lair, treasure hoard, volcanic cave, gold, indoor",
        "motion": "在龍巢裡",
    },
    "dungeon": {
        "label": "地下城",
        "group": "幻想",
        "tags": "stone dungeon, torchlight, iron bars, moss, indoor",
        "motion": "在地下城裡",
    },
    "throne_room": {
        "label": "王座廳",
        "group": "幻想",
        "tags": "throne room, red carpet, golden throne, banners, indoor",
        "motion": "在王座廳裡",
    },
    "fairy_glen": {
        "label": "妖精谷",
        "group": "幻想",
        "tags": "fairy glen, mushrooms, fireflies, moss, outdoor, twilight",
        "motion": "在妖精谷裡",
    },
    "demon_castle": {
        "label": "魔族城堡",
        "group": "幻想",
        "tags": "demon castle interior, black stone, crimson light, gargoyles, indoor",
        "motion": "在魔族城堡裡",
    },
    "ancient_ruins": {
        "label": "古代遺跡",
        "group": "幻想",
        "tags": "ancient ruins, broken pillars, vines, moonlight, outdoor",
        "motion": "在古代遺跡",
    },
    "spaceship": {
        "label": "星艦艦橋",
        "group": "科幻",
        "tags": "spaceship bridge, holographic consoles, stars outside, indoor, sci-fi",
        "motion": "在星艦艦橋",
    },
    "space_station": {
        "label": "太空站",
        "group": "科幻",
        "tags": "space station corridor, metal walls, view of Earth, indoor, sci-fi",
        "motion": "在太空站裡",
    },
    "cyberpunk_street": {
        "label": "賽博龐克街",
        "group": "科幻",
        "tags": "cyberpunk street, neon signs, rain, holograms, night, outdoor",
        "motion": "在賽博龐克街上",
    },
    "neon_city": {
        "label": "霓虹都市",
        "group": "科幻",
        "tags": "neon megacity rooftop, flying cars, holographic ads, night, outdoor",
        "motion": "在霓虹都市裡",
    },
    "sci_lab": {
        "label": "未來實驗室",
        "group": "科幻",
        "tags": "futuristic laboratory, glass tubes, holograms, white light, indoor",
        "motion": "在未來實驗室裡",
    },
    "mecha_hangar": {
        "label": "機甲機庫",
        "group": "科幻",
        "tags": "mecha hangar, giant robots, catwalks, industrial lights, indoor",
        "motion": "在機甲機庫裡",
    },
    "hologram_room": {
        "label": "全息室",
        "group": "科幻",
        "tags": "hologram room, grid floor, glowing projections, dark indoor, sci-fi",
        "motion": "在全息室裡",
    },
    "alien_planet": {
        "label": "外星地表",
        "group": "科幻",
        "tags": "alien planet surface, two moons, strange plants, outdoor, sci-fi",
        "motion": "在外星地表",
    },
    "cryo_chamber": {
        "label": "冷凍艙",
        "group": "科幻",
        "tags": "cryo chamber, frost, glass pods, blue light, indoor, sci-fi",
        "motion": "在冷凍艙裡",
    },
    "android_workshop": {
        "label": "仿生工坊",
        "group": "科幻",
        "tags": "android workshop, spare parts, neon workbench, indoor, sci-fi",
        "motion": "在仿生工坊裡",
    },
    "virtual_plaza": {
        "label": "虛擬廣場",
        "group": "科幻",
        "tags": "virtual plaza, glitching architecture, digital sky, sci-fi, outdoor",
        "motion": "在虛擬廣場",
    },
}


def scene_of(key: str | None) -> dict | None:
    if not key:
        return None
    if key not in SCENES:
        raise ValueError(f"未知場景: {key}（可用: {', '.join(SCENES)}）")
    return SCENES[key]


def scene_labels() -> dict[str, str]:
    return {k: v["label"] for k, v in SCENES.items()}


def scene_groups() -> list[dict]:
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for k, v in SCENES.items():
        g = v.get("group") or "其他"
        if g not in groups:
            groups[g] = []
            order.append(g)
        groups[g].append(k)
    return [{"label": g, "keys": groups[g]} for g in order]


def resolved_place(
    theme_key: str | None, scene_key: str | None,
) -> tuple[str, str]:
    """指定場景優先；沒指定就用主題自帶場景。回 (tags, motion)。"""
    if scene_key:
        sc = scene_of(scene_key)
        return (sc.get("tags") or "").strip(), (sc.get("motion") or "").strip()
    th = theme_of(theme_key) if theme_key else None
    if not th:
        return "", ""
    return (th.get("scene") or "").strip(), (th.get("motion") or "").strip()

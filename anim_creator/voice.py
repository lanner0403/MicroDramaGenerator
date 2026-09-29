"""語音：把台詞寫進動作提示詞，模型才會出聲。預設中文。角色自動分配聲線。"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

# 依動作關鍵字備援的短日文台詞（Ollama 失敗或未開時用）
_JA_BY_KEY = [
    (("fellatio", "blowjob", "oral", "deepthroat"), [
        "んむっ…ちゅっ、はぁんっ…おいしいっ…",
        "はぁっ、んむっ…もっと、喉の奥までっ…",
        "んぁあっ、喉の奥っ…苦しいのにっ…",
    ]),
    (("paizuri", "titjob"), [
        "んぁあっ…おっぱいで挟むねっ、熱いっ…",
        "はぁんっ、出してっ…おっぱいにかけてっ…",
    ]),
    (("hand job", "handjob", "foot job"), [
        "んぁっ…気持ちいい？　はぁん、びくびくしてるっ…",
        "こうっ？　あっあっ、出そうなんでしょっ…",
    ]),
    (("doggy", "from behind", "prone"), [
        "あっあっ、後ろからっ…だめぇっ、深いっ…",
        "はぁんっ、当たってるっ…そこっ、激しっ…",
        "んぁあっ、奥までっ…壊れちゃうっ…",
    ]),
    (("anal",), [
        "んぁあっ、お尻っ…変な感じっ、入ってくぅっ…",
        "はぁぁんっ、お尻っ…だめっ、深いっ…",
    ]),
    (("girl on top", "cowgirl", "riding"), [
        "んぁあっ、私が動くっ…はぁんっ、奥までっ…",
        "あっあっ、気持ちいいっ…イっちゃうっ…",
    ]),
    (("after sex", "after", "cum", "creampie"), [
        "はぁっ…はぁっ…まだ頭が真っ白っ…",
        "んぁあっ…出されちゃったっ、中が熱いっ…",
    ]),
    (("masturbation", "solo"), [
        "んぁあっ…ひとりでっ、はぁんっ…だめっ…",
        "あっあっ、そこっ…イっちゃうっ…",
    ]),
    (("kiss", "licking"), [
        "ちゅっ…んぁっ、舌っ…絡めてっ、はぁん…",
        "はぁっ、キスっ…もっと、離さないでっ…",
    ]),
]

_JA_DEFAULT = [
    "はぁんっ…んぁあっ…気持ちいいっ…",
    "あっあっ…そこっ…だめぇっ、もっとっ…",
    "んぁあっ、はぁんっ…好きっ、激しっ…",
    "やぁんっ…熱いっ…んぁあっ…",
    "はぁんっ…んぁあっ…イきそうっ…",
]

_ZH_DEFAULT = [
    "嗯啊啊…那邊…不要停、好深…",
    "哈啊…好激烈…嗯啊啊…",
    "啊啊…那裡…不行、再深一點…",
    "哈啊…熱…嗯啊啊…",
    "嗯啊…要去了…",
]
_EN_DEFAULT = ["Ahh—right there, don't stop…", "Nnh, ahh—it feels too good…"]

# 成年女性聲線（寫進 LTX 動作稿）。全是成人，不含幼齒。
VOICES: dict[str, dict] = {
    "sweet": {
        "label": "甜美軟糯",
        "ja": "甘く柔らかい大人の女性の声、少し高め、激しく甘い喘ぎと荒い吐息が混じる",
        "zh": "甜美軟糯的成年女性聲、略高、激烈甜喘與急促吐息",
        "en": "sweet soft adult female voice, slightly high, intense sweet moans and ragged breath",
        "climax_ja": "甘い高めの声で激しく言葉にならない喘ぎ、絶頂",
        "climax_zh": "甜美高音、激烈到說不出話的高潮呻吟",
        "climax_en": "sweet high adult female, intense wordless orgasm cries",
    },
    "young": {
        "label": "年輕元氣",
        "ja": "若々しい大人の女性、元気で明るい高めの声、激しく喘ぎながら叫ぶ",
        "zh": "年輕成年女性、元氣明亮偏高音、激烈喘息夾雜叫聲",
        "en": "youthful adult female, bright energetic slightly high voice, intense moaning cries",
        "climax_ja": "明るく高い声で激しく喘ぎ叫ぶ、絶頂",
        "climax_zh": "明亮高音的激烈高潮呻吟",
        "climax_en": "bright high youthful adult female, intense orgasm cries",
    },
    "cold": {
        "label": "高冷淡然",
        "ja": "低く落ち着いた大人の女性、冷静が崩れて抑えきれない激しい喘ぎが漏れる",
        "zh": "低沉冷靜的成年女性、克制崩掉後漏出激烈喘息",
        "en": "cool low adult female voice, composure breaking into intense leaked moans",
        "climax_ja": "抑えきれず崩れる低い激しい喘ぎ、絶頂",
        "climax_zh": "克制失守的低沉激烈高潮呻吟",
        "climax_en": "restrained low voice breaking into intense orgasm moans",
    },
    "mature": {
        "label": "成熟低沉",
        "ja": "落ち着いた低めの大人の女性、色気のある艶声で激しく甘い喘ぎ",
        "zh": "成熟低沉的成年女性、艷氣濃、激烈甜喘",
        "en": "mature low adult female voice, sultry, intense sweet moans",
        "climax_ja": "艶のある低い激しい喘ぎ、絶頂",
        "climax_zh": "艷氣低沉的激烈高潮呻吟",
        "climax_en": "sultry low adult female, intense orgasm moans",
    },
    "gyaru": {
        "label": "辣妹輕佻",
        "ja": "ギャルっぽい大人の女性、鼻にかかった甘い声で激しく喘ぎ笑う",
        "zh": "辣妹腔成年女性、帶鼻音、輕佻又激烈地喘",
        "en": "playful gyaru adult female, nasal-sweet, intense moaning laughs",
        "climax_ja": "ギャルっぽい甘い激しい喘ぎ、絶頂",
        "climax_zh": "辣妹腔甜美激烈高潮呻吟",
        "climax_en": "playful gyaru, intense orgasm moans",
    },
    "elegant": {
        "label": "優雅知性",
        "ja": "上品で落ち着いた大人の女性、清楚な中低音が崩れて激しく喘ぐ",
        "zh": "優雅知性的成年女性、清亮中低音崩掉後激烈喘息",
        "en": "elegant composed adult female, clear mid-low voice breaking into intense moans",
        "climax_ja": "上品さが完全に崩れる中低音の激しい喘ぎ、絶頂",
        "climax_zh": "優雅失守的中低音激烈高潮呻吟",
        "climax_en": "composed mid-low voice breaking into intense orgasm moans",
    },
    "shy": {
        "label": "嬌羞小聲",
        "ja": "小さく恥ずかしそうな大人の女性、我慢できず漏れる激しい吐息と喘ぎ",
        "zh": "嬌羞小聲的成年女性、忍不住漏出的急促氣音與激烈喘息",
        "en": "shy quiet adult female, intense leaked gasps and moans she cannot hold back",
        "climax_ja": "小さな声でも激しい吐息混じり喘ぎ、絶頂",
        "climax_zh": "小聲卻激烈的氣音高潮呻吟",
        "climax_en": "quiet but intense breathy orgasm moans",
    },
    "tsundere": {
        "label": "傲嬌",
        "ja": "強がる大人の女性、強めの口調がすぐ崩れて激しく喘ぐ",
        "zh": "傲嬌成年女性、嘴硬立刻崩成激烈喘息",
        "en": "tsundere adult female, stubborn tone quickly breaking into intense moans",
        "climax_ja": "強がりが完全に崩れた激しい喘ぎ、絶頂",
        "climax_zh": "傲嬌徹底失守的激烈高潮呻吟",
        "climax_en": "tsundere voice breaking into intense orgasm moans",
    },
    "husky": {
        "label": "沙啞性感",
        "ja": "かすれた低めの大人の女性、ハスキーで色っぽく激しく喘ぐ",
        "zh": "沙啞低沉的成年女性、性感、喘息激烈",
        "en": "husky low adult female, raspy, sensual, intense moans",
        "climax_ja": "かすれた低い激しい喘ぎ、絶頂",
        "climax_zh": "沙啞低沉的激烈高潮呻吟",
        "climax_en": "husky raspy intense orgasm moans",
    },
    "bright": {
        "label": "清亮高音",
        "ja": "明るく澄んだ高めの大人の女性、通る声で激しく喘ぎ叫ぶ",
        "zh": "清亮偏高的成年女性、聲音透亮、激烈喘息夾叫聲",
        "en": "bright clear high adult female voice, intense moaning cries",
        "climax_ja": "澄んだ高い激しい喘ぎ叫び、絶頂",
        "climax_zh": "清亮高音的激烈高潮呻吟",
        "climax_en": "clear high adult female, intense orgasm cries",
    },
}
DEFAULT_STYLE = "sweet"
DEFAULT_MALE_STYLE = "male_warm"
_TONE = {k: VOICES[DEFAULT_STYLE][k] for k in ("ja", "zh", "en")}

# 男角色聲線（選角時自動分配；短劇對白預設仍是女方出聲）
MALE_VOICES: dict[str, dict] = {
    "male_young": {
        "label": "年輕清爽",
        "ja": "若々しい大人の男性、澄んだやや高めの声",
        "zh": "年輕成年男性、清爽略高的聲音",
        "en": "youthful adult male, clear slightly high voice",
    },
    "male_warm": {
        "label": "溫和低音",
        "ja": "穏やかな低めの大人の男性、柔らかい声",
        "zh": "溫和低沉的成年男性聲",
        "en": "warm low adult male voice, gentle",
    },
    "male_deep": {
        "label": "低沉磁性",
        "ja": "低く落ち着いた大人の男性、低く響く声",
        "zh": "低沉磁性的成年男性聲",
        "en": "deep resonant adult male voice",
    },
    "male_cold": {
        "label": "冷淡平穩",
        "ja": "低く平坦な大人の男性、感情を抑えた声",
        "zh": "冷淡平穩的成年男性聲",
        "en": "cool flat adult male voice, restrained",
    },
    "male_husky": {
        "label": "沙啞粗獷",
        "ja": "かすれた低めの大人の男性、ハスキーな声",
        "zh": "沙啞粗獷的成年男性聲",
        "en": "husky raspy adult male voice",
    },
    "male_bright": {
        "label": "明亮陽光",
        "ja": "明るく通る大人の男性、元気な声",
        "zh": "明亮陽光的成年男性聲",
        "en": "bright energetic adult male voice",
    },
}

_FEMALE_HINTS = (
    (("gyaru", "辣妹"), "gyaru"),
    (("tsundere", "傲嬌"), "tsundere"),
    (("mature", "milf", "熟女"), "mature"),
    (("succubus", "demon", "魅魔", "vampire", "吸血鬼"), "husky"),
    (("miko", "巫女", "reimu", "princess", "queen", "大小姐", "公主"), "elegant"),
    (("vocaloid", "idol", "hatsune", "miku", "kagamine", "初音", "巡音"), "bright"),
    (("cold", "ice", "高冷", "無口"), "cold"),
    (("shy", "嬌羞"), "shy"),
    (("young", "genki", "元氣"), "young"),
)
_MALE_HINTS = (
    (("cold", "ice", "高冷", "無口", "wanderer", "scaramouche"), "male_cold"),
    (("deep", "mature", "zhongli", "diluc"), "male_deep"),
    (("husky", "rough", "beast"), "male_husky"),
    (("young", "boy", "link", "kagamine"), "male_young"),
    (("bright", "genki", "元氣", "陽光"), "male_bright"),
)


def _voice_book() -> dict[str, dict]:
    out = dict(VOICES)
    out.update(MALE_VOICES)
    return out


def _stable_index(text: str, n: int) -> int:
    h = 2166136261
    for ch in (text or "").lower():
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h % n if n else 0


def character_voice_style(
    title: str,
    gender: str | None = None,
    series: str = "",
    zh: str = "",
) -> str:
    """依角色名／作品穩定分配聲線；同類關鍵字走固定對應。"""
    g = (gender or "female").strip().lower()
    blob = f"{title} {series} {zh}".lower()
    if g == "male":
        for keys, style in _MALE_HINTS:
            if any(k in blob for k in keys):
                return style
        keys = list(MALE_VOICES)
        return keys[_stable_index(title or zh or series, len(keys))]
    for keys, style in _FEMALE_HINTS:
        if any(k in blob for k in keys):
            return style
    keys = list(VOICES)
    return keys[_stable_index(title or zh or series, len(keys))]


def voice_label(key: str | None) -> str:
    if not key:
        return ""
    item = _voice_book().get(key)
    return (item or {}).get("label") or key


# 預先做好的參考音（data/sounds/）。VoxCPM 太重，預設用 edge-tts 出 5+5。
VOICE_REFS: dict[str, list[dict]] = {
    "female": [
        {"id": "f1_sweet", "label": "甜美軟糯", "file": "female/f1_sweet.mp3", "style": "sweet",
         "text": "你好，我是這個角色的聲音。從今天起，我會陪你把故事說完。"},
        {"id": "f2_young", "label": "年輕元氣", "file": "female/f2_young.mp3", "style": "young",
         "text": "嘿，別發呆啊。這次換我來帶節奏，跟緊一點。"},
        {"id": "f3_cold", "label": "高冷淡然", "file": "female/f3_cold.mp3", "style": "cold",
         "text": "少廢話。該走的路，我自己知道。"},
        {"id": "f4_mature", "label": "成熟低沉", "file": "female/f4_mature.mp3", "style": "mature",
         "text": "別急。有些話，今晚我會慢慢告訴你。"},
        {"id": "f5_husky", "label": "沙啞性感", "file": "female/f5_husky.mp3", "style": "husky",
         "text": "過來一點。這段聲音，只講給你聽。"},
    ],
    "male": [
        {"id": "m1_young", "label": "年輕清爽", "file": "male/m1_young.mp3", "style": "male_young",
         "text": "別怕。從現在起，我走在你前面。"},
        {"id": "m2_warm", "label": "溫和低音", "file": "male/m2_warm.mp3", "style": "male_warm",
         "text": "慢慢來。我在這裡，不會讓你一個人。"},
        {"id": "m3_deep", "label": "低沉磁性", "file": "male/m3_deep.mp3", "style": "male_deep",
         "text": "聽好。這門婚事，我娶。"},
        {"id": "m4_cold", "label": "冷淡平穩", "file": "male/m4_cold.mp3", "style": "male_cold",
         "text": "再問一次。她是我太太。"},
        {"id": "m5_husky", "label": "沙啞粗獷", "file": "male/m5_husky.mp3", "style": "male_husky",
         "text": "上車。回家再說。"},
    ],
}

_STYLE_TO_REF = {
    "sweet": "f1_sweet",
    "young": "f2_young",
    "cold": "f3_cold",
    "mature": "f4_mature",
    "husky": "f5_husky",
    "gyaru": "f1_sweet",
    "elegant": "f4_mature",
    "shy": "f1_sweet",
    "tsundere": "f2_young",
    "bright": "f2_young",
    "male_young": "m1_young",
    "male_warm": "m2_warm",
    "male_deep": "m3_deep",
    "male_cold": "m4_cold",
    "male_husky": "m5_husky",
    "male_bright": "m1_young",
}


def sounds_dir(root: str | None = None) -> Path:
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    return base / "data" / "sounds"


_CHAR_VOICE_STYLE = {
    "纳西妲": "sweet",
    "琴": "elegant",
    "芙宁娜": "bright",
    "银狼": "cold",
    "散兵": "male_cold",
    "流浪者": "male_cold",
    "空": "male_young",
}
_AUDIO_EXT = {".mp3", ".wav", ".ogg", ".m4a"}


def _style_from_stem(stem: str, gender: str) -> str:
    if stem in _CHAR_VOICE_STYLE:
        return _CHAR_VOICE_STYLE[stem]
    for name, style in _CHAR_VOICE_STYLE.items():
        if name in stem:
            return style
    return "male_warm" if gender == "male" else "sweet"


def list_voice_refs(root: str | None = None) -> dict[str, list[dict]]:
    """內建音色＋voices.json＋資料夾裡多出來的角色音檔。"""
    path = sounds_dir(root) / "voices.json"
    blob = {k: list(v) for k, v in VOICE_REFS.items()}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and (data.get("female") or data.get("male")):
                blob = data
        except (OSError, json.JSONDecodeError):
            pass
    out: dict[str, list[dict]] = {"female": [], "male": []}
    root_dir = sounds_dir(root)
    seen: set[str] = set()
    for gender in ("female", "male"):
        for item in blob.get(gender) or VOICE_REFS[gender]:
            rel = (item.get("file") or "").replace("\\", "/")
            fp = root_dir / rel
            rec = {
                "id": item.get("id") or "",
                "label": item.get("label") or item.get("id") or "",
                "file": rel,
                "style": item.get("style") or "",
                "text": item.get("text") or "",
                "url": f"/sounds/{rel}" if rel else "",
                "ready": fp.is_file(),
            }
            out[gender].append(rec)
            if rel:
                seen.add(rel)
        folder = root_dir / gender
        if not folder.is_dir():
            continue
        extra = []
        for fp in sorted(folder.iterdir(), key=lambda p: p.name):
            if not fp.is_file() or fp.suffix.lower() not in _AUDIO_EXT:
                continue
            rel = f"{gender}/{fp.name}"
            if rel in seen:
                continue
            stem = fp.stem
            extra.append({
                "id": stem,
                "label": stem,
                "file": rel,
                "style": _style_from_stem(stem, gender),
                "text": "",
                "url": f"/sounds/{rel}",
                "ready": True,
            })
            seen.add(rel)
        out[gender].extend(extra)
    return out


def voice_ref_of(ref_id: str | None, root: str | None = None) -> dict | None:
    key = (ref_id or "").strip()
    if not key:
        return None
    pack = list_voice_refs(root)
    for gender in ("female", "male"):
        for item in pack.get(gender) or []:
            if item.get("id") == key or item.get("file") == key:
                return item
    return None


def voice_ref_style(ref_id: str | None, root: str | None = None) -> str:
    item = voice_ref_of(ref_id, root)
    if not item:
        return ""
    style = (item.get("style") or "").strip()
    return style if style in _voice_book() else ""


def resolve_clone_ref(
    ref_id: str | None = None,
    style: str | None = None,
    root: str | None = None,
) -> dict | None:
    """優先用指定參考音；沒有就依聲線對到內建 f1/m1…"""
    item = voice_ref_of(ref_id, root)
    if item and item.get("ready"):
        return item
    preset = _STYLE_TO_REF.get((style or "").strip())
    if preset:
        item = voice_ref_of(preset, root)
        if item and item.get("ready"):
            return item
    return None


def voice_ref_path(item: dict | None, root: str | None = None) -> Path | None:
    if not item:
        return None
    rel = (item.get("file") or "").replace("\\", "/")
    if not rel:
        return None
    fp = sounds_dir(root) / rel
    return fp if fp.is_file() else None


def voice_cfg(cfg: dict) -> dict:
    return cfg.get("voice") or {}


def voice_enabled(cfg: dict, override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    return bool(voice_cfg(cfg).get("enabled", True))


def voice_language(cfg: dict, override: str | None = None) -> str:
    lang = (override or voice_cfg(cfg).get("language") or "zh").lower()
    if lang not in {"ja", "zh", "en"}:
        return "zh"
    return lang


def list_voices(*, gender: str | None = None) -> list[dict]:
    g = (gender or "female").strip().lower()
    src = MALE_VOICES if g == "male" else VOICES
    return [{"key": k, "label": v["label"]} for k, v in src.items()]


def voice_style(cfg: dict | None = None, override: str | None = None) -> str:
    key = (override or "").strip()
    if not key and cfg is not None:
        key = str(voice_cfg(cfg).get("style") or "").strip()
    book = _voice_book()
    if key in book:
        return key
    return DEFAULT_STYLE


def voice_tone(language: str = "zh", style: str | None = None) -> str:
    book = _voice_book()
    key = style if style in book else DEFAULT_STYLE
    lang = language if language in {"ja", "zh", "en"} else "zh"
    return book[key].get(lang) or book[key].get("zh") or ""


def h3_speaker_desc(style: str | None = None) -> str:
    """MiniMax H3 說話者描述用英文聲線。"""
    book = _voice_book()
    key = style if style in book else DEFAULT_STYLE
    return book[key].get("en") or VOICES[DEFAULT_STYLE]["en"]


def climax_tone(language: str = "zh", style: str | None = None) -> str:
    book = _voice_book()
    key = style if style in book else DEFAULT_STYLE
    lang = language if language in {"ja", "zh", "en"} else "zh"
    return book[key].get(f"climax_{lang}") or book[key].get(lang) or book[key].get("zh") or ""


_TALK_KEYS = (
    "hand job", "handjob", "foot job", "footjob", "paizuri", "titjob",
)
_SUCK_KEYS = (
    "fellatio", "blowjob", "oral", "deepthroat", "cunnilingus",
)
_PANT_KEYS = (
    "sex", "doggy", "cowgirl", "girl on top", "missionary", "anal",
    "mating press", "prone bone", "vaginal", "from behind", "standing sex",
    "carrying sex", "creampie", "after sex", "masturbation", "piledriver",
    "pile drive", "back sex",
)


def voice_kind(action: str = "", tags: str = "") -> str:
    """talk=台詞；suck=吸吮聲無台詞；pant=喘息無台詞。"""
    blob = f"{action} {tags}".lower()
    if any(k in blob for k in _SUCK_KEYS):
        return "suck"
    if any(k in blob for k in _TALK_KEYS):
        return "talk"
    if any(k in blob for k in _PANT_KEYS) or re.search(r"\bsex\b", blob):
        return "pant"
    return "talk"


def fallback_dialogue(action: str | None, language: str = "zh",
                      rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    key = (action or "").lower()
    lang = (language or "zh").lower()
    if lang == "ja":
        for keys, lines in _JA_BY_KEY:
            if any(k in key for k in keys):
                return rng.choice(lines)
        return rng.choice(_JA_DEFAULT)
    if lang == "zh":
        return rng.choice(_ZH_DEFAULT)
    return rng.choice(_EN_DEFAULT)


_JA_ZH_MOAN = (
    ("んぁあっ", "嗯啊啊"),
    ("はぁんっ", "哈啊"),
    ("んむっ", "嗯唔"),
    ("んぐっ", "嗯咕"),
    ("はぁっ", "哈啊"),
    ("あっあっ", "啊啊"),
    ("だめぇっ", "不要啊"),
    ("やぁんっ", "呀啊"),
    ("おいしいっ", "好舒服"),
    ("えっ", "咦"),
    ("んっ", "嗯"),
    ("あっ", "啊"),
)


def localize_dialogue(text: str, language: str = "zh") -> str:
    """內建劇本日文台詞在中文語音時改成中文氣音。"""
    text = (text or "").strip()
    if not text:
        return text
    lang = (language or "zh").lower()
    if lang != "zh" or not re.search(r"[\u3040-\u30ff]", text):
        return text
    out = text
    for ja, zh in _JA_ZH_MOAN:
        out = out.replace(ja, zh)
    out = re.sub(r"[\u3040-\u30ff]+", "嗯啊", out)
    return out


def speech_seconds(dialogue: str) -> int:
    """日文／中文約每秒 4 字（含省略號會唸慢一點）。"""
    n = len(re.sub(r"\s+", "", dialogue or ""))
    if n == 0:
        return 0
    return max(3, min(20, (n + 3) // 4))


def fit_duration(duration: int, dialogue: str, vmin: int, vmax: int) -> int:
    need = speech_seconds(dialogue)
    if need:
        duration = max(duration, need + 2)
    return max(vmin, min(vmax, int(duration)))


_CLIMAX_MOAN = {
    "ja": "んぁあっ！はぁんっ、あっあっあっ、イくぅっ…",
    "zh": "嗯啊啊！哈啊、啊啊啊、去了…",
    "en": "Nnh—ahh, ahh ahh, I'm coming—",
}


def attach_climax_voice(motion: str, language: str = "zh",
                        style: str | None = None) -> str:
    """高潮段只出呻吟，不沿用主片台詞。"""
    motion = (motion or "").strip()
    lang = language if language in _CLIMAX_MOAN else "zh"
    moan = _CLIMAX_MOAN[lang]
    tone = climax_tone(lang, style)
    if moan in motion:
        return motion
    if lang == "ja":
        spoken = (
            f"She moans in Japanese ({tone}). "
            f"[sound]: moaning only 「{moan}」, no dialogue."
        )
    elif lang == "zh":
        spoken = (
            f"She moans in Chinese ({tone}). "
            f"[sound]: moaning only 「{moan}」, no dialogue."
        )
    else:
        spoken = (
            f"She moans in English ({tone}). "
            f'[sound]: moaning only "{moan}", no dialogue.'
        )
    if motion and motion[-1:] not in ".!?。！？":
        motion += "."
    return f"{motion} {spoken}".strip()


def attach_voice(motion: str, dialogue: str, language: str = "zh",
                 tone: str = "", english: bool = False) -> str:
    """把台詞嵌進 LTX 動作稿。已含同一句就不再加。"""
    motion = (motion or "").strip()
    dialogue = (dialogue or "").strip().strip("「」『』\"'")
    if not dialogue:
        return motion
    if dialogue in motion:
        return motion
    tone = tone or _TONE.get(language, _TONE["zh"])
    if english:
        if language == "ja":
            spoken = (
                f"She moans in Japanese ({tone}). "
                f"[sound]: Japanese dialogue 「{dialogue}」, lips synced."
            )
        elif language == "zh":
            spoken = (
                f"She moans in Chinese ({tone}). "
                f"[sound]: 「{dialogue}」."
            )
        else:
            spoken = (
                f"She moans in English ({tone}). "
                f'[sound]: "{dialogue}".'
            )
        enders = (".", "!", "?", "。", "！", "？")
    elif language == "ja":
        spoken = (
            f"用日語（{tone}）。"
            f"[sound]: 日本語の台詞「{dialogue}」。口型對準這句日語。"
        )
        enders = ("。", ".", "！", "？")
    elif language == "zh":
        spoken = f"用中文（{tone}）。[sound]: 「{dialogue}」。"
        enders = ("。", ".", "！", "？")
    else:
        spoken = f"moans in English ({tone}). [sound]: \"{dialogue}\"."
        enders = (".", "!", "?", "。", "！", "？")
    if motion and not motion.endswith(enders):
        motion += "." if english else "。"
    return f"{motion} {spoken}".strip() if english else f"{motion}{spoken}"

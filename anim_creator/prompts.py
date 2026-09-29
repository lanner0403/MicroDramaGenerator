"""組首幀提示詞與 LTX 動作提示詞。"""
from __future__ import annotations

import re

from .catalog import strip_lora
from .themes import male_theme_of, resolved_place, theme_of
from .voice import attach_climax_voice, attach_voice, voice_kind

_LORA_RE_ALREADY = strip_lora  # re-export

_NUDE_HINTS = (
    "nude", "naked", "no clothes", "completely nude", "fully nude",
    "undressed", "stripped", "nude,",
)
_CLOTHES_RE = re.compile(
    r"\b(dress|sundress|skirt|panties|panty|bra|pantyhose|stockings?|"
    r"thighhighs?|uniform|maid headdress|maid|blouse|shirt|kimono|"
    r"yukata|bikini|leotard|apron|sweater|jacket|coat|pants|shorts|"
    r"lingerie|negligee|cheongsam|bodysuit|clothes|clothing|outfit|"
    r"costume|pantyhose|school uniform|pantyhose)\b",
    re.I,
)


def looks_nude(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in _NUDE_HINTS)


def strip_clothes_tags(tags: str) -> str:
    parts = [p.strip() for p in (tags or "").split(",") if p.strip()]
    keep = [p for p in parts if not _CLOTHES_RE.search(p)]
    return ", ".join(keep)


def compose_still_prompt(
    cfg: dict,
    character_prompt: str,
    action_tags: str,
    theme_key: str | None,
    extra: str = "",
    *,
    nsfw: bool = True,
    quality: bool = True,
    more_detail: bool = False,
    less_detail: bool = False,
    character_enhance: bool = False,
    nude: bool = False,
    theme_first: bool = False,
    scene_key: str | None = None,
) -> str:
    img = cfg["image"]
    parts: list[str] = []
    prefix = (img.get("quality") if quality else None) or img["quality_prefix"]
    if not nsfw:
        prefix = ", ".join(
            t.strip() for t in prefix.split(",")
            if t.strip().lower() not in {"nsfw", "explicit", "(nsfw:1.4)", "uncensored"}
        )
    act = strip_lora(action_tags) if action_tags else ""
    if nude:
        act = strip_clothes_tags(act)
    th = theme_of(theme_key) if theme_key else None
    if character_prompt:
        parts.append(character_prompt)
    if nude:
        parts.append("nude, completely nude, no clothes")
    elif theme_first and th and th.get("tags"):
        parts.append(th["tags"])
    if act:
        parts.append(act)
    parts.append(prefix)
    if nsfw and img.get("nsfw"):
        parts.append(img["nsfw"])
    if more_detail and img.get("more_detail"):
        parts.append(img["more_detail"])
    if less_detail and img.get("less_detail"):
        parts.append(img["less_detail"])
    if character_enhance and img.get("character_enhance"):
        parts.append(img["character_enhance"])
    if not nude and not theme_first and th and th.get("tags"):
        parts.append(th["tags"])
    place_tags, _ = resolved_place(theme_key, scene_key)
    if place_tags:
        parts.append(place_tags)
    if extra:
        parts.append(extra)
    parts.append("looking at viewer")
    out = []
    quality_text = prefix.strip() if prefix else ""
    for p in parts:
        if not p or not str(p).strip():
            continue
        # 品質前綴照 config 原樣；其餘才清 LoRA、統一逗號
        out.append(p.strip() if p.strip() == quality_text else strip_lora(p))
    return ", ".join(out)


def _quality_prefix(cfg: dict, *, nsfw: bool, quality: bool) -> str:
    img = cfg["image"]
    prefix = (img.get("quality") if quality else None) or img["quality_prefix"]
    if not nsfw:
        prefix = ", ".join(
            t.strip() for t in prefix.split(",")
            if t.strip().lower() not in {"nsfw", "explicit", "(nsfw:1.4)", "uncensored"}
        )
    return prefix or ""


SHEET_QUALITY = "masterpiece, best quality"
REF_SHEET = (
    "(character sheet:1.3), (multiple views:1.3), "
    "front view, side view, back view, full body, standing, arms at sides, "
    "white background"
)


def negative_ref_sheet(cfg: dict) -> str:
    """三視圖不能禁 extra head／simple background，否則只會出單人全身。"""
    drop = ("simple background", "extra head", "conjoined")
    parts = []
    for t in (negative_still(cfg) or "").split(","):
        s = t.strip()
        if not s:
            continue
        low = s.lower()
        if any(d in low for d in drop):
            continue
        parts.append(s)
    parts.append("portrait, close-up, cowboy shot, upper body, cropped, motion lines, motion line, speed lines")
    return ", ".join(parts)


def negative_partner_sheet(cfg: dict) -> str:
    return negative_ref_sheet(cfg) + ", beard, mustache, stubble, goatee, facial hair"


def compose_character_ref_prompt(
    cfg: dict,
    character_prompt: str,
    theme_key: str | None,
    *,
    nsfw: bool = True,
    quality: bool = True,
    nude: bool = False,
    clothing: str | None = None,
    keep_legwear: str | None = None,
) -> str:
    """短篇 R2V 角色圖：三視圖關鍵詞在前（SDXL CLIP 77 token），再接特徵與衣物。

    脫衣段若上一張腳上有襪子／絲襪，keep_legwear 寫進三視圖；沒有則光腳。
    """
    img = cfg["image"]
    th = theme_of(theme_key) if theme_key else None
    parts: list[str] = [REF_SHEET, SHEET_QUALITY]
    if character_prompt:
        parts.append(character_prompt)
    if nude:
        wear_legs = (keep_legwear or "").strip()
        if wear_legs:
            parts.append("nude, no clothes")
            parts.append(wear_legs)
            parts.append("on feet")
        else:
            parts.append("nude, completely nude, no clothes, bare feet")
    else:
        wear = (clothing or "").strip()
        th_tags = ((th or {}).get("tags") or "").strip()
        if th_tags:
            parts.append(th_tags)
        elif wear:
            parts.append(wear)
    if nsfw and img.get("nsfw"):
        parts.append(img["nsfw"])
    out = []
    for p in parts:
        if not p or not str(p).strip():
            continue
        out.append(strip_lora(p))
    return ", ".join(out)


DEFAULT_MALE = "1boy, fat 40-year-old man, beer belly, balding sparse black hair, clean-shaven"
DEFAULT_MALE_CLOTHES = "stained white tank top, open plaid shirt, cargo shorts"


def compose_partner_ref_prompt(
    cfg: dict,
    male_tags: str = "",
    *,
    nsfw: bool = True,
    quality: bool = True,
    nude: bool = False,
    clothing: str | None = None,
    theme_key: str | None = None,
) -> str:
    """短篇 R2V 男方圖：三視圖在前，再接特徵與男衣著。"""
    img = cfg["image"]
    custom = (male_tags or "").strip()
    tags = custom or DEFAULT_MALE
    if "1boy" not in tags.lower() and "1man" not in tags.lower():
        tags = "1boy, " + tags
    parts: list[str] = [REF_SHEET, SHEET_QUALITY, tags]
    if nude:
        parts.append("nude, completely nude, no clothes")
    else:
        wear = (clothing or "").strip()
        th = male_theme_of(theme_key) if theme_key else None
        th_tags = ((th or {}).get("tags") or "").strip()
        if th_tags:
            parts.append(th_tags)
        elif wear:
            parts.append(wear)
        elif not custom:
            parts.append(DEFAULT_MALE_CLOTHES)
    if nsfw and img.get("nsfw"):
        parts.append(img["nsfw"])
    out = []
    for p in parts:
        if not p or not str(p).strip():
            continue
        out.append(strip_lora(p))
    return ", ".join(out)


def compose_visual_prompt(
    cfg: dict,
    character_prompt: str,
    theme_key: str | None,
    scene_text: str,
    look: str,
    *,
    nsfw: bool = True,
    quality: bool = True,
    nude: bool = False,
    clothing: str | None = None,
) -> str:
    """短篇先出的一張 2D 動畫視覺圖：角色在場景裡，不是三視圖、不是空景。"""
    img = cfg["image"]
    prefix = _quality_prefix(cfg, nsfw=nsfw, quality=quality)
    drop_3d = {"glossy material render"}
    prefix = ", ".join(
        t.strip() for t in prefix.split(",")
        if t.strip() and t.strip().lower() not in drop_3d
    )
    th = theme_of(theme_key) if theme_key else None
    style = (
        "2d, anime, anime coloring, cel shading, 2d animation still, "
        "key visual, official art, cinematic composition"
    )
    parts: list[str] = ["1girl"]
    if character_prompt:
        parts.append(character_prompt)
    look = (look or "").strip()
    want_unconscious = bool(re.search(r"\bunconscious\b", look, re.I))
    want_nude = bool(nude) or bool(re.search(r"\bnude\b", look, re.I)) or want_unconscious
    if want_nude:
        parts.append("nude")
    if want_unconscious:
        parts.append("unconscious")
        look = re.sub(r"\bunconscious\s*,?\s*", "", look, flags=re.I)
    if want_nude:
        look = re.sub(r"\bnude\s*,?\s*", "", look, flags=re.I)
    elif not want_nude:
        wear = (clothing or "").strip()
        th_tags = ((th or {}).get("tags") or "").strip()
        if th_tags:
            parts.append(th_tags)
        elif wear:
            parts.append(wear)
    look = look.strip(" ,")
    if look:
        parts.append(look)
    if scene_text:
        parts.append(scene_text)
    if th and th.get("scene"):
        parts.append(th["scene"])
    parts.append(style)
    parts.append(prefix)
    if nsfw and img.get("nsfw"):
        parts.append(img["nsfw"])
    parts.append(
        "single scene, one composition, not a character sheet, "
        "not multiple views, not a turnaround, not an empty background"
    )
    quality_text = prefix.strip() if prefix else ""
    out = []
    for p in parts:
        if not p or not str(p).strip():
            continue
        out.append(p.strip() if p.strip() == quality_text else strip_lora(p))
    return ", ".join(out)


_SCENE_DROP_RE = re.compile(
    r"("
    r"\b(1girl|1boy|1man|girl|boy|woman|man|heroine|people|passengers?)\b|"
    r"\b(face|eyes|hair|portrait|blush)\b|"
    r"close-?up|"
    r"looking at|from behind|from side|"
    r"\b(sex|missionary|cowgirl|fellatio|creampie|orgasm|groping|kissing|"
    r"standing|sitting|kneeling|hugging|walking|struggling|covering|"
    r"disheveled|nude)\b|"
    r"standing sex|clothes pulled|hand under skirt|"
    r"wet (?:clothes|hair|skin)|"
    r"sitting in lap|in water|on (?:her )?back|against lockers|"
    r"trying to stay quiet|other passengers"
    r")",
    re.I,
)


def scene_location_text(scene_text: str) -> str:
    """只留地點／光線／佈景，拿掉人物、動作、鏡頭。"""
    keep = []
    for tok in (scene_text or "").split(","):
        t = tok.strip()
        if not t or _SCENE_DROP_RE.search(t):
            continue
        keep.append(strip_lora(t))
    return ", ".join(keep)


def negative_scene(cfg: dict) -> str:
    """空景不要出人。"""
    base = negative_still(cfg) or ""
    extra = (
        "1girl, 1boy, 1man, girl, boy, woman, man, people, crowd, "
        "portrait, face, eyes, character, multiple views, character sheet"
    )
    return ", ".join(p for p in (base, extra) if p.strip())


def compose_scene_ref_prompt(
    cfg: dict,
    scene_text: str,
    theme_key: str | None,
    *,
    nsfw: bool = True,
    quality: bool = True,
) -> str:
    """短篇 R2V 場景圖：地點／光線／佈景。不要風格套話、人物、動作。"""
    loc = scene_location_text(scene_text)
    if not loc:
        th = theme_of(theme_key) if theme_key else None
        loc = scene_location_text((th or {}).get("scene") or "")
    parts: list[str] = []
    if loc:
        parts.append(loc)
    if quality:
        parts.append("masterpiece, best quality, detailed background")
    parts.append(
        "empty scene, no people, no characters, no portrait, "
        "establishing shot, wide shot of the location"
    )
    out = []
    for p in parts:
        if not p or not str(p).strip():
            continue
        out.append(strip_lora(p))
    return ", ".join(out)


BOUNCE_EN = (
    "Her breasts bounce and jiggle with delayed inertia on every thrust or hip rock, "
    "heavy and obvious. Her buttocks clap and ripple, soft flesh wobbling independently of the hips."
)
BOUNCE_ZH = (
    "每次律動胸部明顯彈跳晃動、帶延遲慣性；臀部跟著拍打晃動，軟肉獨立晃開。"
)
_BOUNCE_HINTS = ("bounce", "jiggle", "wobbl", "ripple", "彈跳", "晃動", "慣性")
_NO_BOUNCE = (
    "hand job", "handjob", "foot job", "footjob",
    "fellatio", "blowjob", "oral", "deepthroat", "cunnilingus",
    "kiss", "licking", "breast sucking",
    "penis awe", "penis on face",
    "masturbation", "object masturbation",
    "after sex", "after anal",
)
_YES_BOUNCE = (
    "paizuri", "titjob", "doggy", "girl on top", "cowgirl",
    "mating press", "anal sex", "carrying sex", "standing sex",
    "back sex", "creampie", "prone bone", "pile drive", "piledriver",
    "vaginal", "thrust", "from behind",
)


def wants_bounce(action_name: str = "", action_tags: str = "") -> bool:
    """插入／騎乘／乳交等才強調胸臀軟體；手交、足交、口交不要。"""
    blob = f"{action_name} {action_tags}".lower()
    if any(k in blob for k in _NO_BOUNCE):
        return False
    if any(k in blob for k in _YES_BOUNCE):
        return True
    # 單獨的 sex（不是 after sex，已在 _NO_BOUNCE）
    return bool(re.search(r"\bsex\b", blob))


_CUM_HINTS = (
    "cumshot", "ejaculat", "creampie", "semen", "bukkake", "facial",
    "cumdrip", "cum in", "cum on", "cum pool", "excessive cum",
    "射精", "內射", "精液", "中出",
)
_NO_PENETRATION = _NO_BOUNCE + ("paizuri", "titjob")
_YES_PENETRATION = (
    "vaginal", "anal sex", "anal,", "penetration", "insertion",
    "missionary", "doggy", "girl on top", "cowgirl",
    "mating press", "carrying sex", "standing sex", "back sex",
    "prone bone", "pile drive", "piledriver", "from behind",
    "thrust", "creampie",
)
_INTENSE_HINTS = (
    "rough", "pounding", "aggressive", "violent", "rapid",
    "hard fuck", "mating press", "piledriver", "pile drive",
    "fucked silly", "ahegao", "orgasm", "climax", "[shot 2]",
    "激烈", "猛烈", "高潮",
)


def _scene_blob(action_name: str = "", action_tags: str = "",
                motion: str = "", extra: str = "") -> str:
    return f"{action_name} {action_tags} {extra} {motion}".lower()


def wants_cumshot(action_name: str = "", action_tags: str = "",
                  motion: str = "", extra: str = "",
                  climax: bool = False) -> bool:
    """射精／內射／精液可見時。第二段高潮且有男方也算。"""
    blob = _scene_blob(action_name, action_tags, motion, extra)
    if any(k in blob for k in _CUM_HINTS) or re.search(r"\bcum\b", blob):
        return True
    if climax and re.search(r"\b(man|men|boy|boys|1boy|1man|male)\b", blob):
        return True
    return False


def wants_penetration(action_name: str = "", action_tags: str = "",
                      motion: str = "", extra: str = "") -> bool:
    """性交／肛交等有插入；口交、手交、乳交不算。"""
    blob = _scene_blob(action_name, action_tags, motion, extra)
    if any(k in blob for k in _NO_PENETRATION):
        return False
    if any(k in blob for k in _YES_PENETRATION):
        return True
    return bool(re.search(r"\b(sex|anal|vaginal|penetrat|insert)\b", blob))


def wants_intense(action_name: str = "", action_tags: str = "",
                  motion: str = "", extra: str = "",
                  climax: bool = False) -> bool:
    """激烈抽插，或第二段高潮 [Shot 2]。"""
    if climax:
        return True
    blob = _scene_blob(action_name, action_tags, motion, extra)
    return any(k in blob for k in _INTENSE_HINTS)


_LEGWEAR_HINTS = (
    "pantyhose", "stockings", "thighhighs", "thighhigh", "hosiery",
    "bodystocking", "fishnet", "tights", "garter",
    "絲襪", "黑絲", "白絲", "吊帶襪", "過膝襪",
)
_SOCK_HINTS = (
    "socks", "kneehighs", "knee highs", "knee socks", "ankle socks",
    "crew socks", "white socks", "black socks",
    "短襪", "長襪", "棉襪", "白襪", "黑襪",
)
_GENITAL_HINTS = (
    "pussy", "vagina", "anus", "spread pussy", "bottomless",
    "nude", "naked", "creampie", "after sex", "after anal",
    "gaping", "labia", "cameltoe",
)
_LEGWEAR_LOCK = (
    "Keep the exact clothing and legwear from the reference: "
    "pantyhose, stockings, and thighhighs stay on, fitted, not removed, torn, or faded."
)


def has_legwear(action_name: str = "", action_tags: str = "",
                motion: str = "", extra: str = "", look: str = "") -> bool:
    blob = _scene_blob(action_name, action_tags, motion, extra) + f" {look}".lower()
    return any(k in blob for k in _LEGWEAR_HINTS)


def extract_legwear(*texts: str) -> str:
    """從三視圖／衣著 prompt 抽出襪子、絲襪、過膝襪。"""
    keys = _LEGWEAR_HINTS + _SOCK_HINTS
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for tok in (text or "").split(","):
            s = tok.strip()
            if not s:
                continue
            low = s.lower()
            if not any(k in low for k in keys):
                continue
            if low in seen:
                continue
            seen.add(low)
            found.append(s)
            if len(found) >= 3:
                return ", ".join(found)
    return ", ".join(found)


def wants_genitals(action_name: str = "", action_tags: str = "",
                   motion: str = "", extra: str = "", look: str = "") -> bool:
    """外陰／裸體特寫才用陰道細節 LoRA；有絲襪的換裝不要。"""
    if has_legwear(action_name, action_tags, motion, extra, look):
        return False
    blob = _scene_blob(action_name, action_tags, motion, extra) + f" {look}".lower()
    return any(k in blob for k in _GENITAL_HINTS)


def lock_legwear(motion: str) -> str:
    """動作稿鎖住參考圖的絲襪／過膝襪。"""
    text = (motion or "").strip()
    if not text:
        return _LEGWEAR_LOCK
    if "stay on" in text.lower() and any(k in text.lower() for k in ("pantyhose", "stockings", "thighhigh", "legwear")):
        return text
    m = re.search(r"(integrated_multimodal_description\s*:\s*)", text, re.I)
    if m:
        return text[:m.end()] + _LEGWEAR_LOCK + " " + text[m.end():]
    if text.endswith((".", "。", "!", "！", "?", "？")):
        return f"{text} {_LEGWEAR_LOCK}"
    return f"{text}. {_LEGWEAR_LOCK}"


def bounce_instruction(action_name: str = "", action_tags: str = "") -> str:
    """給 Ollama／VL 的動作限制。"""
    if wants_bounce(action_name, action_tags):
        return (
            "Soft-body physics is required: breasts bounce and jiggle with delayed "
            "inertia; buttocks clap and ripple on each thrust or hip rock."
        )
    return (
        "Describe ONLY the named action. "
        "Do NOT mention breast bounce, butt bounce, jiggle, clapping flesh, "
        "or hip thrusting."
    )


def _with_bounce(motion: str, english: bool) -> str:
    text = (motion or "").strip()
    low = text.lower()
    if any(h in low or h in text for h in _BOUNCE_HINTS):
        return text
    extra = BOUNCE_EN if english else BOUNCE_ZH
    if text and not text.endswith((".", "。", "!", "！", "?", "？")):
        text += "." if english else "。"
    return f"{text} {extra}".strip()


H3_I2VA_HEADER = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced."
)
H3_STATIC_CAM = "The camera holds a static shot."
_H3_FIELD_RE = re.compile(
    r"integrated_multimodal_description\s*:|overall_soundscape\s*:|non_diegetic_music\s*:",
    re.I,
)
_H3_LANG = {"ja": "Japanese", "zh": "Chinese", "en": "English"}
_LTX_CAM_RE = re.compile(
    r"The camera stays locked on the first-frame framing\.?\s*"
    r"(No zoom, no cut, no angle change\.?)?",
    re.I,
)
_LTX_SOUND_RE = re.compile(
    r"(?:She moans in (?:Japanese|Chinese|English)\s*\([^)]*\)\.\s*)?"
    r"\[sound\]:[^.。]*[.。]?",
    re.I,
)
_LTX_ZH_VOICE_RE = re.compile(
    r"用[日中英][語文]（[^）]*）。(?:\[sound\]:)?[^。]*。(?:口型對準這句日語。)?",
)


def looks_like_h3_prompt(text: str) -> bool:
    return bool(_H3_FIELD_RE.search(text or ""))


def looks_like_r2v_prompt(text: str) -> bool:
    t = text or ""
    if re.search(r"subject_definitions\s*:", t, re.I):
        return True
    return "<Picture 2>" in t and "reference" in t.lower()


def h3_language_tag(language: str) -> str:
    return _H3_LANG.get((language or "zh").lower(), "Chinese")


def h3_speaker_line(dialogue: str, language: str = "zh", tone: str = "") -> str:
    dialogue = (dialogue or "").strip().strip("「」『』\"'")
    if not dialogue:
        return ""
    desc = (tone or "sweet, slightly high adult female voice").strip()
    if re.search(r"[\u3000-\u9fff]", desc):
        desc = "sweet, slightly high adult female voice"
    return (
        f"The adult woman with a {desc} (S1) says: "
        f"<d>[{h3_language_tag(language)}] {dialogue}</d>"
    )


CONTINUE_I2V_SOUNDSCAPE = (
    "Continue the same ambient room tone and foley as the previous shot. "
    "Do not restart music. Keep the same speaker timbre. "
    "New speech only if a spoken line is written for this shot."
)


def default_h3_soundscape(*, nsfw: bool = True, action: str = "",
                          action_tags: str = "") -> str:
    if not nsfw:
        return (
            "Quiet room tone and natural body-movement sounds continue throughout."
        )
    kind = voice_kind(action, action_tags)
    if kind == "suck":
        return (
            "Close-range wet sucking, slurping, saliva, and muffled nasal hums. "
            "No spoken words. Sucking sounds continue throughout."
        )
    if kind == "pant":
        return (
            "Close-range wet skin, flesh impact, fabric rustle, and ragged panting. "
            "Non-verbal gasps and breath only; no spoken words."
        )
    if wants_bounce(action, action_tags):
        return (
            "Close-range wet skin, flesh impact, and fabric rustle. "
            "Heavy panting and non-verbal moans continue throughout."
        )
    return (
        "Close-range body contact, wet skin, and fabric rustle. "
        "Intense panting and non-verbal moans continue throughout."
    )


_SPOKEN_D_RE = re.compile(
    r"(?:The adult woman with a [^.]*? \(S1\) says:\s*)?<d>\[[^\]]+\][^<]*</d>\.?",
    re.I,
)


def strip_spoken_dialogue(text: str) -> str:
    """拿掉 I2VA 裡的 <d> 台詞行。"""
    return " ".join(_SPOKEN_D_RE.sub(" ", text or "").split())


def _strip_ltx_motion(text: str) -> str:
    text = _LTX_SOUND_RE.sub("", text or "")
    text = _LTX_ZH_VOICE_RE.sub("", text)
    text = _LTX_CAM_RE.sub(H3_STATIC_CAM, text)
    return " ".join(text.split()).strip()


def _h3_shot_body(
    motion: str, *, dialogue: str = "", language: str = "ja",
    tone: str = "", static_camera: bool = True,
) -> str:
    text = _strip_ltx_motion(motion)
    if not text.lower().startswith("[shot "):
        text = (
            "[Shot 1] 2D-animated, the adult woman shown in <Picture 1> remains "
            "in the pose, appearance, clothing, and composition established by "
            f"<Picture 1>. {text}"
        ).strip()
    if static_camera and "camera" not in text.lower():
        if text[-1:] not in ".!?":
            text += "."
        text = f"{text} {H3_STATIC_CAM}"
    spoken = h3_speaker_line(dialogue, language, tone)
    raw = (dialogue or "").strip().strip("「」『』\"'")
    if spoken and "<d>" not in text and raw and raw not in text:
        if text[-1:] not in ".!?":
            text += "."
        text = f"{text} {spoken}"
    return " ".join(text.split())


def _inject_h3_dialogue(text: str, dialogue: str, language: str, tone: str) -> str:
    raw = (dialogue or "").strip().strip("「」『』\"'")
    if not raw or raw in text or "<d>" in text:
        return text
    line = h3_speaker_line(dialogue, language, tone)
    if not line:
        return text
    m = re.search(r"\n\s*overall_soundscape\s*:", text, re.I)
    if m:
        head = text[:m.start()].rstrip()
        if head[-1:] not in ".!?":
            head += "."
        return f"{head} {line}{text[m.start():]}"
    return f"{text.rstrip()} {line}"


def wrap_h3_i2va(
    motion: str,
    *,
    dialogue: str = "",
    language: str = "ja",
    tone: str = "",
    soundscape: str | None = None,
    music: str | None = None,
    nsfw: bool = True,
    action: str = "",
    action_tags: str = "",
    static_camera: bool = True,
) -> str:
    """MiniMax H3 I2VA：首幀對齊 + 三欄。預設 non_diegetic_music: N/A。"""
    text = (motion or "").strip()
    music = (music if music is not None else "N/A").strip() or "N/A"
    kind = voice_kind(action, action_tags)
    if kind != "talk" and not (dialogue or "").strip():
        text = strip_spoken_dialogue(text)
        dialogue = ""
    scape = (soundscape or "").strip() or default_h3_soundscape(
        nsfw=nsfw, action=action, action_tags=action_tags)
    if looks_like_h3_prompt(text):
        if "For the target video" not in text:
            text = f"{H3_I2VA_HEADER}\n\n{text}"
        text = _inject_h3_dialogue(text, dialogue, language, tone)
        if not re.search(r"overall_soundscape\s*:", text, re.I):
            text = text.rstrip() + f"\n\noverall_soundscape: {scape}"
        if not re.search(r"non_diegetic_music\s*:", text, re.I):
            text = text.rstrip() + f"\n\nnon_diegetic_music: {music}"
        return text.strip()
    body = _h3_shot_body(
        text, dialogue=dialogue, language=language, tone=tone,
        static_camera=static_camera)
    return (
        f"{H3_I2VA_HEADER}\n\n"
        f"integrated_multimodal_description: {body}\n\n"
        f"overall_soundscape: {scape}\n\n"
        f"non_diegetic_music: {music}"
    )


def compose_motion_prompt(
    character_label: str,
    action_name: str,
    action_tags: str,
    theme_key: str | None,
    extra: str = "",
    ai_motion: str | None = None,
    dialogue: str = "",
    language: str = "ja",
    tone: str = "",
    english: bool = False,
    h3: bool = False,
    scene_key: str | None = None,
) -> str:
    """圖生影動作提示。h3=True 時寫 MiniMax H3 I2VA。"""
    if h3:
        english = True
    if ai_motion and ai_motion.strip():
        motion = ai_motion.strip()
    elif english:
        act = action_name or "the same action"
        extra_bit = f" {extra.strip()}." if extra and extra.strip() else ""
        if wants_bounce(action_name, action_tags):
            motion = (
                f"She stays in the pose from the first frame and continues {act} "
                f"in a continuous rhythm with clear body displacement. "
                f"Her expression changes with each beat. "
                f"The camera stays locked on the first-frame framing; no zoom, no cut, no angle change.{extra_bit}"
            )
        else:
            motion = (
                f"She stays in the pose from the first frame and continues {act} "
                f"in a continuous rhythm. Motion stays in that act only. "
                f"Her expression changes with each beat. "
                f"The camera stays locked on the first-frame framing; no zoom, no cut, no angle change.{extra_bit}"
            )
    else:
        _, where = resolved_place(theme_key, scene_key)
        where = where or "在畫面中央"
        who = character_label or "這名成年女性"
        act = action_name or "動作"
        tags = strip_lora(action_tags)
        extra_bit = f"。{extra.strip()}" if extra and extra.strip() else ""
        if wants_bounce(action_name, action_tags):
            motion = (
                f"{who}{where}持續做「{act}」這個動作，動作連貫、身體有明顯位移與節奏，"
                f"表情隨著動作變化，鏡頭固定。視覺要素：{tags}{extra_bit}"
            )
        else:
            motion = (
                f"{who}{where}持續做「{act}」這個動作，只做這個動作本身，"
                f"表情隨著動作變化，鏡頭固定。視覺要素：{tags}{extra_bit}"
            )
    if wants_bounce(action_name, action_tags):
        motion = _with_bounce(motion, english)
    if h3:
        return wrap_h3_i2va(
            motion, dialogue=dialogue, language=language, tone=tone,
            nsfw=True, action=action_name, action_tags=action_tags)
    if english:
        motion = lock_camera_en(motion)
    return attach_voice(motion, dialogue, language=language, tone=tone, english=english)


_CAM_LOCK = (
    "The camera stays locked on the first-frame framing. "
    "No zoom, no cut, no angle change."
)
_OLD_CAM_LOCK = re.compile(
    r"no pan, tilt, zoom(?:, dolly)?, (?:cut, or angle change|or cut)\.?",
    re.I,
)


def lock_camera_en(motion: str) -> str:
    text = (motion or "").strip()
    if not text:
        return _CAM_LOCK
    text = _OLD_CAM_LOCK.sub("no zoom, no cut, no angle change.", text)
    low = text.lower()
    if "no zoom, no cut, no angle change" in low:
        if "camera stays locked" in low or "camera remains locked" in low:
            return text
    elif "camera stays locked" in low or "camera remains locked" in low:
        if text[-1:] not in ".!?":
            text += "."
        return f"{text} No zoom, no cut, no angle change."
    if text[-1:] not in ".!?":
        text += "."
    return f"{text} {_CAM_LOCK}"


_MALE_RE = re.compile(r"\b(man|men|boy|boys|1boy|1man|male)\b", re.I)
_SHOT2_RE = re.compile(r"\[Shot\s*2\]", re.I)
_SHOT2_BLOCK_RE = re.compile(
    r"\[Shot\s*2\].*?(?=\n\s*overall_soundscape\s*:|\Z)",
    re.I | re.S,
)
_IMD_BODY_RE = re.compile(
    r"integrated_multimodal_description\s*:\s*(.*?)(?=\n\s*overall_soundscape\s*:|\Z)",
    re.I | re.S,
)


def compose_climax_motion(
    action_name: str = "",
    action_tags: str = "",
    language: str = "ja",
    voice_style: str | None = None,
    h3: bool = False,
    seconds: int | None = None,
) -> str:
    """高潮 [Shot 2]：姿勢／鏡頭不變；語音只有呻吟，不沿用主片台詞。有男方才加射精。"""
    n = int(seconds) if seconds else 0
    time_bit = f"the final {n} seconds. " if n > 0 else ""
    motion = (
        f"[Shot 2] 2D-animated, {time_bit}"
        "Continue from [Shot 1] without changing pose, appearance, clothing, or camera. "
        "The camera holds a static shot. "
        "Orgasm face. Female climaxes. "
        "She moans and cries out as she climaxes."
    )
    blob = f"{action_name} {action_tags}"
    if _MALE_RE.search(blob):
        motion += " He ejaculates, semen visible."
    if h3:
        return motion
    return attach_climax_voice(motion, language=language, style=voice_style)


EXTEND_MODES = ("similar", "tweak", "rhythm")
_EXTEND_BODY = {
    "similar": (
        "Continue the same act in the same pose, clothing, and framing. "
        "Same contact and rhythm as a natural continuation. No new camera, no new position."
    ),
    "tweak": (
        "Keep the same pose, clothing, and framing. "
        "Only small adjustments: slightly deeper or shallower motion, a shift of her hands, "
        "or a change of expression. No new camera, no new position."
    ),
    "rhythm": (
        "Keep the same pose, clothing, contact, and framing. "
        "Change only the rhythm: slower then faster, or a brief pause then resume. "
        "No new camera, no new position."
    ),
}


def compose_extend_motion(
    action_name: str = "",
    action_tags: str = "",
    mode: str = "similar",
    seconds: int | None = None,
) -> str:
    """同畫面加長段：類似動作／小調整／變更節奏。無台詞。"""
    key = (mode or "similar").strip().lower()
    if key not in _EXTEND_BODY:
        key = "similar"
    n = int(seconds) if seconds else 0
    time_bit = f"for {n} seconds. " if n > 0 else ""
    act = action_name or "the same act"
    body = (
        f"[Shot 1] 2D-animated, {time_bit}"
        "The adult woman shown in <Picture 1> remains in the pose, appearance, "
        f"clothing, and composition established by <Picture 1>. She continues {act}. "
        f"{_EXTEND_BODY[key]} {H3_STATIC_CAM}"
    )
    return wrap_h3_i2va(
        body, dialogue="", nsfw=True,
        action=action_name, action_tags=action_tags)


def as_climax_shot(text: str, seconds: int | None = None) -> str:
    """把自訂／舊高潮稿收成 [Shot 2] 段落（可從完整 I2VA 抽出）。"""
    text = (text or "").strip()
    if not text:
        return ""
    m = _IMD_BODY_RE.search(text)
    if m:
        text = m.group(1).strip()
    text = re.sub(r"^\[Shot\s*1\]", "[Shot 2]", text, count=1, flags=re.I)
    if not _SHOT2_RE.match(text):
        n = int(seconds) if seconds else 0
        time_bit = f"the final {n} seconds. " if n > 0 else ""
        text = f"[Shot 2] 2D-animated, {time_bit}{text}"
    return text.strip()


def inject_climax_shot(motion: str, shot2: str, seconds: int | None = None) -> str:
    """把 [Shot 2] 接到 I2VA 動作稿裡（overall_soundscape 之前）。"""
    shot2 = as_climax_shot(shot2, seconds=seconds)
    text = (motion or "").strip()
    if not shot2:
        return text
    if _SHOT2_RE.search(text):
        new, n = _SHOT2_BLOCK_RE.subn(lambda _m: shot2, text, count=1)
        if n:
            return new.strip()
    m = re.search(r"\n\s*overall_soundscape\s*:", text, re.I)
    if m:
        return f"{text[:m.start()].rstrip()}\n\n{shot2}{text[m.start():]}"
    return f"{text}\n\n{shot2}".strip()


def negative_still(cfg: dict) -> str:
    return cfg["image"]["negative"]


def slug(text: str, n: int = 40) -> str:
    import re
    s = re.sub(r'[\\/:*?"<>|(),·]+', "", text)
    s = re.sub(r"\s+", "-", s).strip("-., ")
    return (s[:n] or "clip").rstrip("-")

"""短篇模式：可選劇本，拆成不同秒數的片段再合成。"""
from __future__ import annotations

import json
import re
import random
import shutil
import subprocess
import time
from pathlib import Path

from .sequences import family_actions
from .themes import MALE_THEMES, THEMES, scene_of

# duration 夾在 4–12，LTX / MiniMax H3 都能跑。
# NSFW 依段落內容判定；非 NSFW 圖生影預設 MiniMax H3。
# 內建短劇改放 data/preset_stories.json（每篇 ≤180 秒，走到小高潮即停）。
def _load_preset_stories() -> dict[str, dict]:
    path = Path(__file__).resolve().parent.parent / "data" / "preset_stories.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


STORIES: dict[str, dict] = _load_preset_stories()

def _apply_story_links(stories: dict) -> None:
    for story in stories.values():
        prev_key = None
        for i, beat in enumerate(story.get('fragments') or []):
            key = ((beat.get('extra') or '').split(',')[0]).strip()
            if beat.get('link'):
                prev_key = key
                continue
            if i == 0:
                prev_key = key
                continue
            beat['link'] = 'continue' if key and key == prev_key else 'reference'
            prev_key = key


_apply_story_links(STORIES)


_SEX_BEAT_RE = re.compile(
    r"vagina|penis|missionary|doggy|creampie|sex|插入|做愛",
    re.I,
)
_NSFW_RE = re.compile(
    r"sex|sexual|nude|naked|nsfw|explicit|creampie|fellatio|blowjob|"
    r"paizuri|titjob|cunnilingus|hand\s*job|foot\s*job|groping|grope|"
    r"penetration|vaginal|\banal\b|orgasm|climax|\bcum\b|ejaculat|"
    r"insertion|missionary|cowgirl|doggy|mating press|girl on top|"
    r"standing sex|after sex|after anal|\boral\b|deepthroat|"
    r"pussy|penis|\bcock\b|breast sucking|stripped|"
    r"性交|口交|插入|內射|高潮|裸體|癡漢|被摸",
    re.I,
)


def beat_partner_index(beat: dict, n_males: int) -> int | None:
    """這一鏡出鏡的男角，1 起算。沒寫 partner 時用男 1。solo 或沒有男角則沒有人出鏡。"""
    if beat.get("solo") or n_males <= 0:
        return None
    raw = beat.get("partner")
    if raw is None or raw == "":
        return 1
    try:
        idx = int(raw)
    except (TypeError, ValueError):
        return 1
    if idx < 1 or idx > n_males:
        return 1
    return idx


def beat_is_nsfw(beat: dict) -> bool:
    """依段落劇情／標籤判斷要不要 NSFW。可在 beat 上寫 nsfw: true/false 覆寫。"""
    if beat.get("nsfw") is not None:
        return bool(beat["nsfw"])
    if beat.get("nude"):
        return True
    blob = " ".join(
        str(beat.get(k) or "")
        for k in ("title", "action", "tags", "extra", "plot")
    )
    return bool(_NSFW_RE.search(blob))


_REF_HINT = re.compile(
    r"close-?up|doorway|hotel room|under desk|sitting on bench|"
    r"onsen edge|leaning on|from side",
    re.I,
)


def _extra_tokens(beat: dict) -> set[str]:
    return {t.strip().lower() for t in (beat.get("extra") or "").split(",") if t.strip()}


def resolve_beat_link(prev: dict | None, beat: dict) -> str:
    """分鏡接法：cut 新開、reference 用上一段當參考重構圖、continue 直接接尾幀。"""
    explicit = (beat.get("link") or "").strip().lower()
    if explicit in {"cut", "continue", "reference"}:
        return explicit
    if not prev:
        return "cut"
    blob = " ".join(str(beat.get(k) or "") for k in ("title", "tags", "extra", "plot"))
    prev_blob = " ".join(str(prev.get(k) or "") for k in ("title", "tags", "extra", "plot"))
    if bool(prev.get("solo")) != bool(beat.get("solo")):
        return "reference"
    if _REF_HINT.search(blob):
        return "reference"
    prev_close = bool(_REF_HINT.search(prev_blob))
    if prev_close and not _REF_HINT.search(blob):
        return "reference"
    prev_t, cur_t = _extra_tokens(prev), _extra_tokens(beat)
    if prev_t and cur_t:
        overlap = len(prev_t & cur_t) / len(prev_t | cur_t)
        if overlap < 0.22:
            return "reference"
    return "continue"


def beat_dialogue(beat: dict) -> str:
    bits = []
    d = (beat.get("dialogue") or "").strip()
    if d:
        bits.append(d)
    for s in beat.get("shots") or []:
        t = (s.get("dialogue") or "").strip()
        if t and t not in bits:
            bits.append(t)
    return " ".join(bits)


def beat_plot_text(beat: dict) -> str:
    plot = (beat.get("plot") or "").strip()
    if plot:
        return plot
    bits = [str(beat.get("title") or "").strip()]
    if beat.get("tags"):
        bits.append(str(beat["tags"]).strip())
    elif beat.get("action"):
        bits.append(str(beat["action"]).strip())
    if beat.get("extra"):
        bits.append(str(beat["extra"]).strip())
    return ". ".join(b for b in bits if b)


def beat_visual_look(beat: dict) -> str:
    """視覺圖用：出租屋等段標 unconscious + 依姿勢躺／趴。"""
    explicit = (beat.get("visual") or "").strip()
    if explicit:
        return explicit
    blob = f"{beat.get('action') or ''} {beat.get('tags') or ''} {beat.get('plot') or ''}".lower()
    pose = ""
    if any(k in blob for k in ("doggy", "from behind", "prone", "on her knees")):
        pose = "unconscious, lies face down on the bed, prone, 趴着"
    elif any(k in blob for k in ("missionary", "mating press", "on her back", "lies on the bed")):
        pose = "unconscious, lies on her back on the bed, 躺着"
    shots = beat.get("shots") or []
    look = ""
    if shots:
        look = (shots[0].get("plot") or "").strip()
    if not look:
        look = beat_plot_text(beat)
    if pose:
        return f"{pose}. {look}".strip()
    return look


def compose_story_motion(
    beat: dict,
    *,
    character: str = "",
    duration: int | None = None,
    nsfw: bool | None = None,
    link: str = "cut",
    prev_plot: str = "",
    h3: bool = False,
) -> str:
    """依段落劇情寫圖生影動作稿（非鎖定鏡頭的一般動畫模板）。"""
    from .prompts import wrap_h3_i2va

    nsfw = beat_is_nsfw(beat) if nsfw is None else bool(nsfw)
    who = (character or "").strip() or "She"
    plot = beat_plot_text(beat)
    dur = int(duration if duration is not None else beat.get("duration") or 6)
    dur = max(1, dur)
    cam = (
        "The camera may pan or push in with small amplitude at slow speed; no hard cut."
    )
    sex = (
        "Bodies move with the plot, faces change, breathing is audible."
        if nsfw else
        "Natural body language and changing expression. No sexual motion."
    )
    if link == "continue":
        prev = f" Previous beat ended at: {prev_plot}." if prev_plot else ""
        body = (
            f"[Shot 1] 2D-animated, continue from <Picture 1> without resetting pose or framing.{prev} "
            f"Over {dur} seconds the scene becomes: {plot} {sex} {cam}"
        )
    elif link == "reference":
        body = (
            f"[Shot 1] 2D-animated, a new shot of the same people and setting as <Picture 1>. "
            f"{who} acts out this beat for {dur} seconds: {plot} {sex} {cam}"
        )
    else:
        body = (
            f"[Shot 1] 2D-animated, the adult woman shown in <Picture 1> remains "
            f"in the pose, appearance, clothing, and composition established by <Picture 1>. "
            f"Over {dur} seconds, {who} acts out this beat: {plot} {sex} {cam}"
        )
    body = " ".join(body.split())
    if h3:
        return wrap_h3_i2va(body, nsfw=nsfw, static_camera=False)
    return body


def compose_story_i2v(
    beat: dict,
    *,
    duration: int | None = None,
    nsfw: bool | None = None,
    prev_plot: str = "",
    language: str = "zh",
    voice_style: str | None = None,
    dialogue: str | None = None,
    continue_shot: bool = True,
) -> str:
    """MiniMax H3 I2V 鏡頭稿。接尾幀時只認上一段最後一幀，不引用 R2V 的角色／場景圖。"""
    from .prompts import CONTINUE_I2V_SOUNDSCAPE, wrap_h3_i2va
    from .voice import h3_speaker_desc, localize_dialogue

    nsfw = beat_is_nsfw(beat) if nsfw is None else bool(nsfw)
    plot = beat_plot_text(beat)
    dur = max(1, int(duration if duration is not None else beat.get("duration") or 6))
    raw = beat_dialogue(beat) if dialogue is None else dialogue
    dlg = localize_dialogue((raw or "").strip(), language)
    prev_bit = (prev_plot or "").strip().rstrip(".")
    prev = f" Previous beat ended at: {prev_bit}." if prev_bit else ""
    if continue_shot:
        motion = (
            "[Shot 1] 2D-animated, continue the same shot from <Picture 1> "
            "(the last frame of the previous beat). Do not cut, do not reset "
            f"blocking or clothing.{prev} Over {dur} seconds: {plot}"
        )
        scape = CONTINUE_I2V_SOUNDSCAPE
        static = True
    else:
        motion = (
            "[Shot 1] 2D-animated, start from <Picture 1> and keep its "
            "pose, clothing, and framing. Do not cut. "
            f"Over {dur} seconds: {plot}"
        )
        scape = None
        static = False
    return wrap_h3_i2va(
        " ".join(motion.split()),
        dialogue=dlg,
        language=language,
        tone=h3_speaker_desc(voice_style),
        soundscape=scape,
        nsfw=nsfw,
        static_camera=static,
    )


_SCENE_KEYS = (
    "rental apartment", "rental", "alley", "locker", "train", "platform",
    "hotel room", "hotel", "office", "onsen", "street", "eaves", "bed",
    "desk", "doorway", "brick wall", "rain", "pool", "tatami", "lobby",
)


def beat_scene_key(beat: dict) -> str:
    """同一地點共用場景圖；地點變了才重出。"""
    explicit = (beat.get("scene") or "").strip().lower()
    if explicit:
        return explicit
    blob = f"{beat.get('extra') or ''} {beat.get('tags') or ''}".lower()
    for k in _SCENE_KEYS:
        if k in blob:
            return k
    extra = (beat.get("extra") or "").strip().lower()
    toks = [t.strip() for t in extra.split(",") if t.strip()][:2]
    if toks:
        return ", ".join(toks)
    return (beat.get("title") or "scene").strip().lower()


def beat_clothing_key(
    nude: bool, theme: str | None = None, clothing: str | None = None,
) -> str:
    if nude:
        return "nude"
    t = (theme or "").strip().lower()
    if t:
        return t
    raw = (clothing or "").strip()
    if raw:
        return "casual" if "casual" in raw.lower() else raw.split(",")[0].strip().lower()[:40]
    return "original"


def beat_male_clothing_key(nude: bool, male_theme: str | None = None) -> str:
    if nude:
        return "nude"
    return ((male_theme or "").strip().lower() or "original")


def _is_stock_male(male: str) -> bool:
    m = (male or "").strip().lower()
    if not m:
        return True
    return any(k in m for k in ("beer belly", "beer-belly", "fat 40", "obese beer"))


def _partner_lock(male: str) -> dict:
    custom = (male or "").strip()
    if _is_stock_male(custom):
        return {
            "who": custom or "a fat 40-year-old clean-shaven man with sparse balding black hair",
            "face": "fat chubby face, obese beer-belly body, and hair",
            "slim": " Do not slim him down.",
        }
    return {
        "who": custom,
        "face": "face, hair color, hairstyle, and body type",
        "slim": "",
    }


def compose_story_r2v(
    beat: dict,
    *,
    character: str = "",
    duration: int | None = None,
    nsfw: bool | None = None,
    link: str = "cut",
    prev_plot: str = "",
    nude: bool = False,
    male: str = "",
    has_partner: bool | None = None,
    clothing_changed: bool = False,
    scene_changed: bool = False,
    has_pose_ref: bool = False,
    has_motion_clip: bool = False,
    language: str = "zh",
    voice_style: str | None = None,
) -> str:
    """MiniMax H3 Ref2VA。女／男／場景鎖身份與房間。姿勢寫在鏡頭稿，不用另張視覺圖。"""
    from .prompts import default_h3_soundscape

    nsfw = beat_is_nsfw(beat) if nsfw is None else bool(nsfw)
    if has_partner is None:
        has_partner = not bool(beat.get("solo"))
    plock = _partner_lock(male)
    who = (character or "").strip() or "the adult woman"
    plot = beat_plot_text(beat)
    dur = int(duration if duration is not None else beat.get("duration") or 6)
    dur = max(1, dur)
    act = (beat.get("action") or beat.get("tags") or "").strip()
    scene_pic = "<Picture 3>" if has_partner else "<Picture 2>"
    pose_pic = ""
    if has_pose_ref:
        pose_pic = "<Picture 4>" if has_partner else "<Picture 3>"
    act_low = (beat.get("action") or "").strip().lower()
    sex_beat = (
        nsfw
        and act_low not in {"after sex", "after anal"}
        and bool(_SEX_BEAT_RE.search(
            f"{beat.get('action') or ''} {beat.get('tags') or ''} {plot}"))
    )
    if sex_beat:
        clothes = (
            "Use <Picture 1> for her face, hair, and body only. "
            "Do not copy her standing pose or street clothes. "
            "She is undressed on the bed."
        )
    elif nude:
        clothes = (
            "She is nude as shown in <Picture 1>. Do not add clothes, "
            "fabric, or an outfit from a previous beat."
        )
    elif clothing_changed:
        clothes = (
            "Her clothing has changed. Use the exact outfit in <Picture 1>; "
            "do not keep the previous costume."
        )
    else:
        clothes = (
            "Keep the exact clothing from <Picture 1>. Do not undress, "
            "swap, or invent a different outfit unless this beat's plot does."
        )
    his = ""
    if has_partner:
        if sex_beat and has_motion_clip:
            his = (
                f" He is the man from <Picture 2>: same {plock['face']}.{plock['slim']} "
                "Do not copy his standing clothes, idle pose, or extra sheet views. Pants off. "
                "His penis is already fully inserted in her vagina, hilt-deep. "
                "No hand on the penis, no holding the shaft, no aiming. "
                "Match the motion clip's crop: the man may be only partly visible or off-screen. "
                "Do not add a second standing man. Exactly one man. "
                "Hands follow the motion clip. Do not copy her face onto him."
            )
        elif sex_beat:
            his = (
                f" He is the man from <Picture 2>: same {plock['face']}.{plock['slim']} "
                "Do not copy his standing clothes or idle pose. Pants off. "
                "His penis is already fully inserted in her vagina, hilt-deep. "
                "No hand on the penis, no holding the shaft, no aiming. "
                "Do not copy her face onto him."
            )
        elif nude and has_motion_clip:
            his = (
                f" He is the man from <Picture 2>. Keep his {plock['face']}.{plock['slim']} "
                "He is nude if he appears. Do not copy extra sheet views as extra people. "
                "If the motion clip does not show him in frame, keep him off-screen. "
                "Do not add a second standing man. Do not copy her face onto him."
            )
        elif nude:
            his = (
                f" He is the man from <Picture 2>. Keep his {plock['face']}.{plock['slim']} "
                "He is nude in this beat; do not keep the clothes "
                "from <Picture 2>. Do not copy her face onto him."
            )
        elif clothing_changed:
            his = (
                " His clothing has changed to match <Picture 2> exactly. "
                "Do not copy her outfit onto him."
            )
        else:
            his = (
                " Keep the exact clothing from <Picture 2>. "
                "He is a different person from <Picture 1>; do not swap faces."
            )
    if scene_changed:
        place = (
            f"This beat is a NEW location. Architecture, lighting, weather, "
            f"and set dressing must match {scene_pic}, not the previous setting."
        )
    else:
        place = (
            f"Stay in the location from {scene_pic}. Match its lighting and "
            "set dressing. Do not teleport to another environment."
        )
    people = f"{who} from <Picture 1>"
    if has_partner:
        if has_motion_clip:
            people += (
                "; the man from <Picture 2> only as framed by the motion clip "
                "(cropped or off-screen is OK)"
            )
        else:
            people += " and the man from <Picture 2>"
    prev = f" Previous beat ended at: {prev_plot}." if prev_plot else ""
    shot = _r2v_shot_block(
        beat, who=who, people=people, scene_pic=scene_pic, dur=dur,
        link=link, prev=prev, plot=plot,
        language=language, voice_style=voice_style)
    if sex_beat and has_motion_clip:
        sex = (
            " His penis stays fully inside her vagina the whole beat, hilt-deep. "
            "No hand on the penis, no gripping the shaft, no pulling out to the tip. "
            "Thrusting, crop, and hand placement follow the motion clip. "
            "Do not force both hands onto her. "
            "She stays unconscious and limp if the plot says so."
        )
    elif sex_beat:
        sex = (
            " His penis stays fully inside her vagina the whole beat, hilt-deep. "
            "No hand on the penis, no gripping the shaft, no pulling out to the tip. "
            "She stays unconscious and limp if the plot says so."
        )
    elif nsfw:
        sex = " Bodies move with the plot, faces change, breathing is audible."
    else:
        sex = " Natural body language and changing expression. No sexual motion."
    shot_cams = [
        (s.get("camera") or beat.get("camera") or "").strip().lower()
        for s in (beat.get("shots") or [])
    ]
    beat_cam = (beat.get("camera") or "").strip().lower()
    n_static = sum(1 for c in shot_cams if c == "static")
    if shot_cams and 0 < n_static < len(shot_cams):
        cam = (
            " Follow each shot's camera: locked shots stay locked; "
            "later shots may cut to a side view."
        )
    elif beat_cam == "static" or (shot_cams and n_static == len(shot_cams)):
        cam = " The camera holds a locked static shot. No pan, no zoom, no cut."
    else:
        cam = " The camera may pan or push in slowly; no hard cut unless the plot requires one."
    scape = default_h3_soundscape(nsfw=nsfw, action=act, action_tags=act)
    if (beat.get("title") or "") == "夜巷獨行":
        scape = (
            "Quiet alley night tone. A short startled gasp, then muffled struggle "
            "through cloth that weakens over about one second, then silence as she "
            "faints. A small fabric rustle as the handkerchief comes off her face, "
            "then dragging footsteps, heavy male breathing. "
            "She is silent after she slumps."
        )
    if sex_beat:
        defs = [
            f"<Subject 1> is {who} from <Picture 1>. Face, hair color, hairstyle, "
            "and body type match <Picture 1>. Do not copy her standing pose or her street clothes.",
            "<Picture 1> is identity only: face, hair color, hairstyle, body type. "
            "Not a first frame, not her outfit, not her pose, not extra sheet views.",
        ]
        retain = [
            "<Subject 1> (appears in [Shot 1]): fully_preserved - face, hair color, "
            "hairstyle, and body type from <Picture 1>. Clothing and standing pose are discarded.",
            "<Picture 1>: attribute_transfer - identity only, not outfit, not composition.",
        ]
    else:
        defs = [
            f"<Subject 1> is {who} from <Picture 1>. Face, hair color, hairstyle, "
            "body type, and clothing must match <Picture 1>.",
            "<Picture 1> is the woman character reference: identity and current "
            "clothing or nudity. Not a first frame; do not copy its pose or empty background.",
        ]
        retain = [
            "<Subject 1> (appears in [Shot 1]): fully_preserved - face, hair color, "
            "hairstyle, body type, and clothing or nudity from <Picture 1>.",
            "<Picture 1>: attribute_transfer - identity and outfit only, not composition.",
        ]
    if has_partner:
        m = plock["who"]
        if sex_beat:
            defs.append(
                f"<Subject 2> is the adult man from <Picture 2> ({m}). {plock['face'].capitalize()} "
                f"match <Picture 2>.{plock['slim']} Do not copy his standing clothes or idle pose."
            )
            defs.append(
                f"<Picture 2> is identity only: {plock['face']}. "
                "Not a first frame, not his outfit, not a hand-on-penis pose. "
                "Do not swap faces with <Picture 1>."
            )
        else:
            defs.append(
                f"<Subject 2> is the adult man from <Picture 2> ({m}). {plock['face'].capitalize()}, "
                f"and clothing must match <Picture 2>.{plock['slim']}"
            )
            defs.append(
                "<Picture 2> is the man character reference: identity and current "
                "clothing or nudity. Not a first frame. Do not swap faces with <Picture 1>."
            )
        defs.append(
            "Exactly one adult man. Other figures on <Picture 2> are the same person "
            "from other angles; do not put them in the shot as extra people."
        )
        defs.append(
            f"{scene_pic} is the 2D-animated anime environment reference: location, "
            "architecture, lighting, weather, and set dressing in the same 2D anime "
            "style as the video. Not a first frame, not live-action, not 3D."
        )
        if sex_beat and has_motion_clip:
            retain.append(
                f"<Subject 2>: fully_preserved - {plock['face']} from <Picture 2> "
                f"when he is visible.{plock['slim']} "
                "Standing clothes, idle pose, and extra sheet views discarded. "
                "Do not spawn extra bodies. Penis fully inserted; no hand on the shaft."
            )
            retain.append(
                "<Picture 2>: attribute_transfer - identity only, not outfit, not composition."
            )
        elif sex_beat:
            retain.append(
                f"<Subject 2> (appears in [Shot 1]): fully_preserved - {plock['face']} "
                f"from <Picture 2>.{plock['slim']} "
                "Standing clothes and idle pose discarded. "
                "Penis fully inserted; no hand on the shaft."
            )
            retain.append(
                "<Picture 2>: attribute_transfer - identity only, not outfit, not composition."
            )
        else:
            retain.append(
                f"<Subject 2> (appears in [Shot 1]): fully_preserved - {plock['face']}, "
                f"and clothing or nudity from <Picture 2>.{plock['slim']}"
            )
            retain.append(
                "<Picture 2>: attribute_transfer - the man's identity and outfit only, "
                "not composition."
            )
        retain.append(
            f"{scene_pic}: attribute_transfer - scene, lighting, and set only, "
            "not composition."
        )
        if pose_pic:
            defs.append(
                f"{pose_pic} is the pose and blocking still for this beat "
                "(lying or prone, penetration already in). Use it for pose only. "
                f"Discard faces from {pose_pic}; faces come from <Picture 1> and "
                f"<Picture 2>. Do not freeze {pose_pic} as a first frame; the video must move."
            )
            retain.append(
                f"{pose_pic}: partially_preserved - pose, blocking, and penetration. "
                "Discard faces and extra limbs. Not a first-frame lock."
            )
        if sex_beat:
            pose_bit = f" Pose from {pose_pic}." if pose_pic else ""
            summary = (
                f"[reference generation] Place <Subject 1> and <Subject 2> into "
                f"{scene_pic} already in the sex pose of this beat. Identity from "
                f"<Picture 1> and <Picture 2>, location from {scene_pic}.{pose_bit} "
                "Do not preserve street clothes. Penis fully inside; no hand on penis."
            )
        else:
            pose_bit = f" Pose from {pose_pic}." if pose_pic else ""
            summary = (
                f"[reference generation] Place <Subject 1> and <Subject 2> into "
                f"{scene_pic} and act out this beat. Preserve clothing from "
                f"<Picture 1> and <Picture 2>, and the location from {scene_pic}."
                f"{pose_bit}"
            )
    else:
        defs.append(
            "<Picture 2> is the 2D-animated anime environment reference: location, "
            "architecture, lighting, weather, and set dressing in the same 2D anime "
            "style as the video. Not a first frame, not live-action, not 3D."
        )
        retain.append(
            "<Picture 2>: attribute_transfer - scene, lighting, and set only, "
            "not composition."
        )
        if pose_pic:
            defs.append(
                f"{pose_pic} is the pose and blocking still for this beat. "
                "Use it for pose only. Discard faces from it; face from <Picture 1>. "
                f"Do not freeze {pose_pic} as a first frame; the video must move."
            )
            retain.append(
                f"{pose_pic}: partially_preserved - pose and blocking. "
                "Discard faces. Not a first-frame lock."
            )
        summary = (
            "[reference generation] Place <Subject 1> into the setting of "
            "<Picture 2> and act out this beat. Preserve clothing from "
            "<Picture 1> and the location from <Picture 2>."
            + (f" Pose from {pose_pic}." if pose_pic else "")
        )
    body = (
        "subject_definitions:\n"
        + "\n".join(defs) + "\n"
        "\n"
        "summary:\n"
        f"{summary}\n"
        "\n"
        "retention_analysis:\n"
        + "\n".join(retain) + "\n"
        "\n"
        "detailed_description:\n"
        "The target video is 2D-animated anime.\n"
        f"{shot} {clothes}{his} {place}{sex}{cam}\n"
        "\n"
        f"overall_soundscape:\n{scape}\n"
        "\n"
        "non_diegetic_music:\nN/A"
    )
    return lock_r2v_anime_style(body)


def _h3_timecode(sec: float) -> str:
    sec = max(0.0, float(sec))
    m = int(sec) // 60
    s = sec - m * 60
    return f"{m:02d}:{s:06.3f}"


def _r2v_voice(dialogue: str, language: str = "zh", voice_style: str | None = None) -> str:
    from .prompts import h3_speaker_line
    from .voice import h3_speaker_desc, localize_dialogue
    text = localize_dialogue((dialogue or "").strip(), language)
    line = h3_speaker_line(text, language=language, tone=h3_speaker_desc(voice_style))
    return f" {line}" if line else ""


def _r2v_shot_block(
    beat: dict, *, who: str, people: str, scene_pic: str, dur: int,
    link: str, prev: str, plot: str,
    language: str = "zh", voice_style: str | None = None,
) -> str:
    shots = beat.get("shots") or []
    if not shots:
        voice = _r2v_voice(beat.get("dialogue") or "", language, voice_style)
        if link == "continue":
            return (
                f"[Shot 1] 2D-animated, continue the same encounter without resetting "
                f"blocking.{prev} Over {dur} seconds: {plot}{voice}"
            )
        if link == "reference":
            return (
                f"[Shot 1] 2D-animated, a new composition of {people} inside "
                f"{scene_pic}. Over {dur} seconds: {plot}{voice}"
            )
        verb = "are" if not beat.get("solo") else "is"
        return (
            f"[Shot 1] 2D-animated, {people} {verb} placed into {scene_pic}. "
            f"Over {dur} seconds: {plot}{voice}"
        )
    lines = []
    for i, s in enumerate(shots, 1):
        start = float(s.get("start") if s.get("start") is not None else 0)
        end = float(s.get("end") if s.get("end") is not None else dur)
        bit = (s.get("plot") or "").strip()
        voice = _r2v_voice(s.get("dialogue") or "", language, voice_style)
        if (s.get("camera") or beat.get("camera") or "").strip().lower() == "static":
            bit += " The camera holds a locked static shot."
        if i == 1:
            head = (
                f"[Shot 1] 2D-animated, {start:.2f}-{end:.2f}s"
            )
            if link == "continue":
                head += f", continue the same encounter without resetting blocking.{prev}"
            else:
                head += f", {people} in {scene_pic}."
            lines.append(f"{head} {bit}{voice}")
        else:
            lines.append(
                f"[Shot {i}] At {_h3_timecode(start)}, {bit}{voice}"
            )
    return "\n".join(lines)


def attach_pose_ref(motion: str, *, has_partner: bool = True) -> str:
    """視覺圖當姿勢 Picture，不當 I2VA 首幀。"""
    text = (motion or "").strip()
    pic = "<Picture 4>" if has_partner else "<Picture 3>"
    if not text or pic in text:
        return text
    faces = "<Picture 1> and <Picture 2>" if has_partner else "<Picture 1>"
    block = (
        f"{pic} is the pose and blocking still for this beat "
        "(lying or prone, penetration already in). Use it for pose only. "
        f"Discard faces from {pic}; faces come from {faces}. "
        f"Do not freeze {pic} as a first frame; the video must move.\n"
    )
    text, n = re.subn(
        r"\nsummary:\s*\n",
        "\n" + block + "\nsummary:\n",
        text,
        count=1,
        flags=re.I,
    )
    if not n:
        text = text + "\n" + block
    retain = (
        f"{pic}: partially_preserved - pose, blocking, and penetration. "
        "Discard faces. Not a first-frame lock.\n"
    )
    text, n = re.subn(
        r"\ndetailed_description:\s*\n",
        "\n" + retain + "\ndetailed_description:\n",
        text,
        count=1,
        flags=re.I,
    )
    return text.strip()


_MOTION_ONLY_MARK = "motion-only reference"


def beat_motion_clip(
    beat: dict | None = None,
    *,
    story_id: str = "",
    title: str = "",
) -> str:
    """段落動作庫檔名（不含副檔名）。meta 沒寫就回劇本定義。"""
    raw = str((beat or {}).get("motion_clip") or "").strip()
    if raw:
        return Path(raw).stem
    sid = (story_id or "").strip()
    ttl = (title or str((beat or {}).get("title") or "")).strip()
    if not sid or not ttl:
        return ""
    story = STORIES.get(sid)
    if not story:
        return ""
    for b in story.get("fragments") or []:
        if (b.get("title") or "").strip() == ttl:
            return str(b.get("motion_clip") or "").strip()
    return ""


def meta_motion_clip(meta: dict | None = None, item: dict | None = None) -> str:
    """已寫進 meta 的選擇優先（空字串＝不使用）；沒寫才回劇本預設。"""
    meta = meta or {}
    item = item or {}
    plot = meta.get("story_plot") or {}
    if "motion_clip" in meta:
        raw = meta.get("motion_clip")
    elif "motion_clip" in plot:
        raw = plot.get("motion_clip")
    elif "motion_clip" in item:
        raw = item.get("motion_clip")
    else:
        title = plot.get("title") or meta.get("story_beat") or item.get("title") or ""
        return beat_motion_clip(
            {},
            story_id=str(meta.get("story_id") or item.get("story_id") or ""),
            title=str(title),
        )
    raw = str(raw or "").strip()
    return Path(raw).stem if raw else ""


_VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}


def _data_root(root: str | Path | None) -> Path:
    return Path(root) if root else Path(__file__).resolve().parent.parent


def probe_duration(path: Path) -> float | None:
    if not path or not path.is_file():
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        val = float((proc.stdout or "").strip())
    except ValueError:
        return None
    return val if val > 0 else None


def list_video_refs(root: str | Path | None = None) -> list[dict]:
    """data/video 優先，其次 data 根目錄的 mp4。同名只留前面那支。"""
    base = _data_root(root) / "data"
    paths: list[Path] = []
    video_dir = base / "video"
    if video_dir.is_dir():
        paths.extend(
            p for p in video_dir.iterdir()
            if p.is_file() and p.suffix.lower() in _VIDEO_EXT
        )
    if base.is_dir():
        paths.extend(p for p in base.glob("*.mp4") if p.is_file())
    rows = []
    seen: set[str] = set()
    for path in sorted(paths, key=lambda p: p.name.lower()):
        key = path.stem.lower()
        if key in seen:
            continue
        seen.add(key)
        secs = probe_duration(path)
        rows.append({
            "id": path.stem,
            "name": path.stem,
            "file": path.name,
            "folder": "video" if path.parent.name == "video" else "data",
            "seconds": round(secs, 2) if secs else None,
        })
    return rows


def list_motion_clips(root: str | Path) -> list[str]:
    return [row["id"] for row in list_video_refs(root)]


def resolve_motion_clip(name: str, root: str | Path) -> Path | None:
    """data/video、data/*.mp4，或草稿裡上傳的參考片。檔名或 stem，大小寫不拘。"""
    raw = (name or "").strip()
    if not raw:
        return None
    folder = Path(root) / "data"
    if not folder.is_dir():
        return None
    want = Path(raw).stem.lower()
    video_dir = folder / "video"
    hits = []
    if video_dir.is_dir():
        hits = [
            p for p in video_dir.iterdir()
            if p.is_file() and p.suffix.lower() in _VIDEO_EXT and p.stem.lower() == want
        ]
    if not hits:
        hits = [p for p in folder.glob("*.mp4") if p.stem.lower() == want]
    if not hits:
        drafts = Path(root) / "data" / "drafts"
        if drafts.is_dir() and _CARD_ID.fullmatch(Path(raw).stem):
            found = sorted(drafts.glob(f"*/motions/{Path(raw).stem}.mp4"))
            if found:
                return found[0]
        return None
    exact = Path(raw).stem
    for p in hits:
        if p.stem == exact:
            return p
    return hits[0]


def shift_motion_video_tag(
    motion: str, src: str = "<Video 1>", dst: str = "<Video 2>",
) -> str:
    """上一段佔了 <Video 1> 時，把動作庫改成 <Video 2>。"""
    text = motion or ""
    if _MOTION_ONLY_MARK not in text or dst in text:
        return text
    return text.replace(src, dst)


_BOTH_HANDS_RE = re.compile(
    r"Both hands on her (?:body or the bed|hips or the bed|hips, waist, or the bed)\.\s*",
    re.I,
)
_THRUST_BOTH_HANDS_RE = re.compile(
    r"He thrusts with both hands on her body or the bed\.\s*",
    re.I,
)


def attach_extra_cast(motion: str, extras: list[dict] | None) -> str:
    """額外的人寫進 subject_definitions，Picture 編號才對得上上傳的圖。"""
    text = (motion or "").strip()
    defs: list[str] = []
    retain: list[str] = []
    n = _next_subject_n(text)
    for e in extras or []:
        pic = (e.get("pic") or "").strip()
        if not pic:
            continue
        who = "adult woman" if (e.get("gender") or "") == "female" else "adult man"
        name = (e.get("name") or who).strip()
        tag = f"<Subject {n}>"
        n += 1
        defs.append(
            f"{tag} is the {who} {name} from {pic}. Face, hair color, hairstyle, "
            f"body type, and clothing match {pic}."
        )
        defs.append(
            f"{pic} is {name}'s identity and clothing. Not a first frame, not the location. "
            "Do not swap faces with the other Pictures."
        )
        retain.append(
            f"{tag} (appears in [Shot 1]): fully_preserved - face, hair, body, and clothing from {pic}."
        )
        retain.append(
            f"{pic}: attribute_transfer - identity and outfit only, not composition."
        )
    if not defs:
        return text
    block = "\n".join(defs) + "\n"
    text, nsub = re.subn(
        r"\nsummary:\s*\n",
        "\n" + block + "\nsummary:\n",
        text,
        count=1,
        flags=re.I,
    )
    if not nsub:
        text = block + "\n" + text
    text = re.sub(
        r"(Place <Subject 1> into the setting of <Picture 2> and act out this beat\.)",
        r"\1 Also place each extra person above into that same shot, once.",
        text,
        count=1,
    )
    text = re.sub(
        r"(Place <Subject 1> and <Subject 2> into[^\n]*\.)",
        r"\1 Also place each extra person above into that same shot, once.",
        text,
        count=1,
    )
    retain_block = "\n".join(retain) + "\n"
    text, nr = re.subn(
        r"\ndetailed_description:\s*\n",
        "\n" + retain_block + "\ndetailed_description:\n",
        text,
        count=1,
        flags=re.I,
    )
    if not nr:
        text = text + "\n" + retain_block
    return text.strip()


_SFW_DETAIL_HEAD = "Match the full-body dance movement, footwork, timing, and rhythm of"
_NSFW_DETAIL_HEAD = "Match the body motion and sexual rhythm of"


def _attach_motion_clip_sfw(text: str, tag: str) -> str:
    """一般段落的動作參考：只借全身動作／步伐／節奏，沒有性暗示字眼。"""
    video_def = (
        f"{tag} is a {_MOTION_ONLY_MARK}. Copy the full-body dance movement, footwork, "
        "arm and head movement, timing, and rhythm of this clip exactly, and keep its "
        "full-body framing. "
        "Discard faces, hair color, hairstyle, body type, weight, skin tone, age, "
        "clothing, location, lighting, audio, on-screen text, photoreal skin, "
        "live-action look, and 3D CGI from this clip. Redraw that motion as 2D "
        "cel-shaded anime. The character keeps her own appearance and outfit: "
        "identity (face, hair color, hairstyle, body type) and clothing come from "
        "the Pictures; location from the scene Picture. "
        "Only the people in the Pictures; extra sheet views are not extra people.\n"
    )
    if _MOTION_ONLY_MARK in text:
        text = re.sub(
            rf"{re.escape(tag)} is a {_MOTION_ONLY_MARK}\.[^\n]*\n?",
            lambda m: video_def,
            text,
            count=1,
            flags=re.I,
        )
        text = text.replace(_NSFW_DETAIL_HEAD, _SFW_DETAIL_HEAD)
        return text.strip()
    text, n = re.subn(
        r"\nsummary:\s*\n",
        lambda m: "\n" + video_def + "\nsummary:\n",
        text,
        count=1,
        flags=re.I,
    )
    if not n:
        text = text + "\n" + video_def
    text = re.sub(
        r"(summary:\s*\n)(\[reference generation\]|[^\n]*)",
        lambda m: (
            m.group(1)
            + m.group(2)
            + f" Match body motion from {tag} only. "
            + f"Do not copy people, hair, body type, clothes, room, or photoreal look from {tag}."
        ),
        text,
        count=1,
        flags=re.I,
    )
    retain = (
        f"{tag}: attribute_transfer - motion, pose, and rhythm only. "
        "Discard identity, hair color, body type, clothing, scene, audio, "
        "and photoreal or 3D look.\n"
    )
    text, n = re.subn(
        r"\ndetailed_description:\s*\n",
        lambda m: "\n" + retain + "\ndetailed_description:\n",
        text,
        count=1,
        flags=re.I,
    )
    text = re.sub(
        r"(detailed_description:\s*\nThe target video is 2D-animated[^\n]*\n)",
        lambda m: (
            m.group(1)
            + f"{_SFW_DETAIL_HEAD} {tag}. "
            + f"Do not copy faces, hair color, hairstyle, body type, clothes, room, "
            + f"or photoreal look from {tag}. "
            + "Keep hair color, hairstyle, body type, and outfit from the Pictures. "
            + "Redraw the motion as 2D cel-shaded anime. "
        ),
        text,
        count=1,
        flags=re.I,
    )
    return text.strip()


def attach_motion_clip(motion: str, tag: str = "<Video 1>", nsfw: bool = True) -> str:
    """動作庫影片：只借姿勢／節奏／肢體，不借身份、衣著、場景、聲音。

    nsfw=False（一般段落）用中性的舞蹈／動作描述，不帶性暗示字眼。
    """
    text = (motion or "").strip()
    if not text:
        return text
    if not nsfw:
        return _attach_motion_clip_sfw(text, tag)
    text = _THRUST_BOTH_HANDS_RE.sub("He thrusts. ", text)
    text = _BOTH_HANDS_RE.sub("", text)
    video_def = (
        f"{tag} is a {_MOTION_ONLY_MARK}. Copy the sexual position, body rhythm, "
        "thrusting cadence, limb timing, and how much of each person is in frame. "
        "If this clip crops the man or leaves him off-screen, keep that framing; "
        "do not insert a full extra person from the character sheet. "
        "Hand placement follows this clip; do not force both hands onto her. "
        "Discard faces, hair color, hairstyle, body type, weight, skin tone, age, "
        "clothing, location, lighting, audio, photoreal skin, live-action look, "
        "and 3D CGI from this clip. Redraw that motion as 2D cel-shaded anime. "
        "Identity (face, hair color, hairstyle, body type) comes from the Pictures; "
        "location from the scene Picture. "
        "Exactly one woman and at most one man; extra sheet views are not extra people.\n"
    )
    if _MOTION_ONLY_MARK in text:
        text, n = re.subn(
            rf"{re.escape(tag)} is a {_MOTION_ONLY_MARK}\.[^\n]*\n?",
            video_def,
            text,
            count=1,
            flags=re.I,
        )
        if n:
            return text.strip()
    text, n = re.subn(
        r"\nsummary:\s*\n",
        "\n" + video_def + "\nsummary:\n",
        text,
        count=1,
        flags=re.I,
    )
    if not n:
        text = text + "\n" + video_def
    text = re.sub(
        r"(summary:\s*\n)(\[reference generation\]|[^\n]*)",
        lambda m: (
            m.group(1)
            + m.group(2)
            + f" Match body motion from {tag} only. "
            + f"Do not copy people, hair, body type, clothes, room, or photoreal look from {tag}."
        ),
        text,
        count=1,
        flags=re.I,
    )
    retain = (
        f"{tag}: attribute_transfer - motion, pose, and rhythm only. "
        "Discard identity, hair color, body type, clothing, scene, audio, "
        "and photoreal or 3D look.\n"
    )
    text, n = re.subn(
        r"\ndetailed_description:\s*\n",
        "\n" + retain + "\ndetailed_description:\n",
        text,
        count=1,
        flags=re.I,
    )
    text = re.sub(
        r"(detailed_description:\s*\nThe target video is 2D-animated[^\n]*\n)",
        rf"\1Match the body motion and sexual rhythm of {tag}. "
        rf"Do not copy faces, hair color, hairstyle, body type, clothes, room, "
        rf"or photoreal look from {tag}. "
        rf"Keep hair color, hairstyle, and body type from the Pictures. "
        rf"Redraw the motion as 2D cel-shaded anime. ",
        text,
        count=1,
        flags=re.I,
    )
    return text.strip()


_STYLE_LOCK_MARK = "2D anime drawing style of the target video"
_STYLE_SHOT = (
    "The target video is 2D-animated Japanese anime: cel shading, clean lineart, "
    "flat colors, two-tone shadows, limited animation. Not photorealistic, not "
    "live-action, not 3D CGI, no lens blur, no skin pores."
)


def _next_subject_n(text: str) -> int:
    nums = [int(n) for n in re.findall(r"<Subject\s+(\d+)>", text, flags=re.I)]
    return (max(nums) + 1) if nums else 1


def lock_r2v_anime_style(motion: str) -> str:
    """R2V 把 2D 賽璐璐寫成 Subject，避免 hybrid／動作庫把畫面拉成寫實。"""
    text = (motion or "").strip()
    if not text:
        return text
    text = re.sub(
        r"The target video is 2D-animated anime\.",
        _STYLE_SHOT,
        text,
        count=1,
        flags=re.I,
    )
    if _STYLE_LOCK_MARK in text:
        return text
    tag = f"<Subject {_next_subject_n(text)}>"
    style_def = (
        f"{tag} is the {_STYLE_LOCK_MARK}: cel shading, two-tone shadows, "
        "clean dark lineart, flat color, limited-animation timing. "
        "Not photorealistic, not live-action, not 3D CGI.\n"
    )
    text, n = re.subn(
        r"\nsummary:\s*\n",
        "\n" + style_def + "\nsummary:\n",
        text,
        count=1,
        flags=re.I,
    )
    if not n:
        text = text + "\n" + style_def
    text = re.sub(
        r"(summary:\s*\n)(\[reference generation\]|[^\n]*)",
        lambda m: (
            m.group(1)
            + m.group(2)
            + " Render the whole shot as 2D cel-shaded anime. "
            "Do not make skin, lighting, or camera photoreal."
        ),
        text,
        count=1,
        flags=re.I,
    )
    retain = (
        f"{tag} (appears in [Shot 1]): fully_preserved - cel shading, lineart, "
        "and flat 2D color. Reject photoreal skin, 3D lighting, and live-action look.\n"
    )
    text, n = re.subn(
        r"\ndetailed_description:\s*\n",
        "\n" + retain + "\ndetailed_description:\n",
        text,
        count=1,
        flags=re.I,
    )
    text = re.sub(
        r"(detailed_description:\s*\nThe target video is 2D-animated[^\n]*\n)",
        r"\1Redraw people and the room as 2D cel-shaded anime. "
        "Do not photorealize faces, skin, or the set. "
        "If a reference video is used, take motion only and discard its "
        "live-action or 3D look.\n",
        text,
        count=1,
        flags=re.I,
    )
    return text.strip()


_FACE_LOCK_MARK = "close-up identity lock"


def attach_identity_closeups(
    motion: str, *, woman_pic: str = "", man_pic: str = "",
) -> str:
    """動作庫 R2V 多傳的臉部特寫：鎖臉、髮色、髮型，不當首幀。"""
    text = (motion or "").strip()
    if not text or _FACE_LOCK_MARK in text:
        return text
    defs: list[str] = []
    retain: list[str] = []
    extra = ""
    if woman_pic:
        defs.append(
            f"{woman_pic} is a {_FACE_LOCK_MARK} of her face from the character sheet. "
            "Lock face, eye color, hair color, and hairstyle from it. "
            "Not a first frame, not a close-up composition."
        )
        retain.append(
            f"{woman_pic}: attribute_transfer - face, hair color, and hairstyle only. "
            "Not composition."
        )
        extra += f" Her face, hair color, and hairstyle follow {woman_pic}."
    if man_pic:
        defs.append(
            f"{man_pic} is a {_FACE_LOCK_MARK} of his face from the character sheet. "
            "Lock face and hair from it. Not a first frame, not a close-up composition."
        )
        retain.append(
            f"{man_pic}: attribute_transfer - face and hair only. Not composition."
        )
        extra += f" His face and hair follow {man_pic}."
    if not defs:
        return text
    extra += " Do not take hair color or body type from the motion clip."
    block = "\n".join(defs) + "\n"
    text, n = re.subn(
        r"\nsummary:\s*\n",
        "\n" + block + "\nsummary:\n",
        text,
        count=1,
        flags=re.I,
    )
    if not n:
        text = text + "\n" + block
    retain_block = "\n".join(retain) + "\n"
    text, n = re.subn(
        r"\ndetailed_description:\s*\n",
        "\n" + retain_block + "\ndetailed_description:\n",
        text,
        count=1,
        flags=re.I,
    )
    text = re.sub(
        r"(detailed_description:\s*\nThe target video is 2D-animated[^\n]*\n)",
        rf"\1{extra} ",
        text,
        count=1,
        flags=re.I,
    )
    return text.strip()


def detach_motion_clip(motion: str) -> str:
    """拿掉動作庫只借動作的段落。"""
    text = (motion or "").strip()
    if not text or _MOTION_ONLY_MARK not in text:
        return text
    text = re.sub(
        r"<Video \d+> is a motion-only reference\.[^\n]*\n?",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r" ?Match body motion from <Video \d+> only\. "
        r"Do not copy people[^.]*from <Video \d+>\.",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"<Video \d+>: attribute_transfer - motion, pose, and rhythm only\.[^\n]*\n?",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"Match the (?:body motion and sexual rhythm|full-body dance movement, footwork, timing, and rhythm) of <Video \d+>\. "
        r"Do not copy faces[^.]*from <Video \d+>\. "
        r"(?:Keep hair color, hairstyle, (?:and body type|body type, and outfit) from the Pictures\. )?"
        r"(?:Redraw the motion as 2D cel-shaded anime\. )?",
        "",
        text,
        flags=re.I,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def attach_video_continue(motion: str) -> str:
    """把上一段影片標成 <Video 1>：從結尾姿勢接著演，身份仍跟參考圖。"""
    text = (motion or "").strip()
    if not text or "previous beat of this encounter" in text:
        return text
    video_def = (
        "<Video 1> is the previous beat of this encounter. Continue from the "
        "pose, blocking, and motion at the END of <Video 1>. Do not reset to "
        "a new idle pose.\n"
    )
    text, n = re.subn(
        r"\nsummary:\s*\n",
        "\n" + video_def + "\nsummary:\n",
        text,
        count=1,
        flags=re.I,
    )
    if not n:
        text = text + "\n" + video_def
    text = re.sub(
        r"(summary:\s*\n)\[reference generation\]",
        r"\1[video continuation + reference generation]",
        text,
        count=1,
        flags=re.I,
    )
    retain = (
        "<Video 1>: partially_preserved - ending pose, blocking, and motion. "
        "Discard clothing or location if they conflict with the Pictures.\n"
    )
    text, n = re.subn(
        r"\ndetailed_description:\s*\n",
        "\n" + retain + "\ndetailed_description:\n",
        text,
        count=1,
        flags=re.I,
    )
    text = re.sub(
        r"(detailed_description:\s*\nThe target video is 2D-animated anime\.\s*\n)",
        r"\1Pick up exactly from the last moment of <Video 1> without a jump cut. ",
        text,
        count=1,
        flags=re.I,
    )
    return text.strip()


def story_video_key(cfg: dict, nsfw: bool, requested: str | None = None) -> str:
    """非 NSFW 固定 MiniMax H3；NSFW 用 requested 或 config 的短篇 NSFW 模型。"""
    vid = cfg.get("video") or {}
    models = vid.get("models") or {}
    requested = (requested or "").strip() or None
    if nsfw:
        key = requested or (vid.get("story_nsfw") or vid.get("default") or "minimax_h3")
    else:
        key = vid.get("story_sfw") or "minimax_h3"
    key = str(key).strip()
    if models and key not in models:
        if not nsfw and "minimax_h3" in models:
            return "minimax_h3"
        return str(vid.get("default") or next(iter(models)))
    return key


def generated_stories_dir(root: str | Path | None = None) -> Path:
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    return base / "data" / "stories"


def _story_card(sid: str, s: dict, *, source: str) -> dict:
    beats = s.get("fragments") or []
    cast = s.get("cast") or {}
    return {
        "id": sid,
        "title": s.get("title") or sid,
        "summary": s.get("summary") or "",
        "source": source,
        "clothing": s.get("clothing") or "",
        "cast": {
            "female": max(0, min(3, int(cast.get("female") if cast.get("female") is not None else 1))),
            "male": max(0, min(3, int(cast.get("male") if cast.get("male") is not None else 1))),
        },
        "count": len(beats),
        "total": sum(int(b.get("duration") or 0) for b in beats),
        "fragments": [
            {
                "title": b.get("title") or "",
                "duration": int(b.get("duration") or 0),
                "nsfw": beat_is_nsfw(b),
                "link": b.get("link") or "cut",
                "motion_clip": (b.get("motion_clip") or "").strip(),
            }
            for b in beats
        ],
    }


def list_stories(root: str | Path | None = None) -> list[dict]:
    out = [_story_card(sid, s, source="preset") for sid, s in STORIES.items()]
    folder = generated_stories_dir(root)
    if folder.is_dir():
        for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                s = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or path.stem).strip()
            if not sid or sid in STORIES:
                continue
            out.append(_story_card(sid, s, source=s.get("source") or "ollama"))
    return out


def save_story(story: dict, root: str | Path | None = None) -> dict:
    if not isinstance(story, dict):
        raise ValueError("短劇必須是物件")
    frags = story.get("fragments") or []
    if not frags:
        raise ValueError("短劇沒有段落")
    sid = str(story.get("id") or "").strip()
    if not sid:
        raise ValueError("短劇沒有 id")
    if sid in STORIES:
        sid = f"{sid}_ai"
    folder = generated_stories_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    blob = {
        "id": sid,
        "title": story.get("title") or sid,
        "summary": story.get("summary") or "",
        "clothing": story.get("clothing") or "",
        "female": story.get("female") or "",
        "male": story.get("male") or "",
        "source": story.get("source") or "ollama",
        "fragments": list(frags),
    }
    cast = story.get("cast")
    if isinstance(cast, dict):
        blob["cast"] = {
            "female": max(0, min(3, int(cast.get("female") or 0))),
            "male": max(0, min(3, int(cast.get("male") or 0))),
        }
    (folder / f"{sid}.json").write_text(
        json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    return blob


def get_story(story_id: str, root: str | Path | None = None) -> dict:
    sid = (story_id or "").strip()
    if sid in STORIES:
        s = STORIES[sid]
        return {
            "id": sid,
            "title": s["title"],
            "summary": s["summary"],
            "clothing": s.get("clothing") or "",
            "fragments": list(s["fragments"]),
        }
    path = generated_stories_dir(root) / f"{sid}.json"
    if path.is_file():
        s = json.loads(path.read_text(encoding="utf-8"))
        return {
            "id": str(s.get("id") or sid),
            "title": s.get("title") or sid,
            "summary": s.get("summary") or "",
            "clothing": s.get("clothing") or "",
            "fragments": list(s.get("fragments") or []),
        }
    raise ValueError(f"未知短篇: {sid or '（空白）'}")


_DRAFT_ID = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
_CLIP_MODES = {
    "r2v": "r2v", "1": "r2v",
    "i2v": "i2v", "i2v_tail": "i2v", "2": "i2v",
    "i2v_clone": "i2v_clone", "clone": "i2v_clone", "3": "i2v_clone",
}


def _clamp_beat_dur(n) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = 8
    return max(4, min(12, v))


def _pick_indexed(raw, slots: list) -> list:
    out = []
    seen: set[int] = set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        try:
            i = int(item)
        except (TypeError, ValueError):
            continue
        if i < 1 or i > len(slots) or i in seen:
            continue
        seen.add(i)
        out.append(slots[i - 1])
    return out


def beat_cast(beat: dict, fem_slots: list, mal_slots: list) -> dict:
    """這一鏡實際出鏡的人。

    with_females / with_males 是角色卡的 1 起算編號。
    沒寫這兩個欄位時，維持原本：女角全上，男角看 solo / partner。
    """
    use_fems = list(fem_slots)
    if isinstance(beat.get("with_females"), list) and beat.get("with_females"):
        picked = _pick_indexed(beat.get("with_females"), fem_slots)
        if picked:
            use_fems = picked
    if isinstance(beat.get("with_males"), list):
        use_males = _pick_indexed(beat.get("with_males"), mal_slots)
        has_partner = bool(use_males)
        if has_partner:
            partner_i = mal_slots.index(use_males[0]) + 1
            beat_male = use_males[0].get("prompt") or ""
        else:
            partner_i = None
            beat_male = ""
        return {
            "females": use_fems,
            "males": use_males,
            "male_sheets": use_males,
            "partner_i": partner_i,
            "has_partner": has_partner,
            "explicit_partner": True,
            "beat_male": beat_male,
        }
    partner_i = beat_partner_index(beat, len(mal_slots))
    has_partner = partner_i is not None
    explicit_partner = beat.get("partner") not in (None, "")
    beat_male = mal_slots[partner_i - 1].get("prompt") or "" if has_partner else ""
    male_sheets = [] if explicit_partner or not has_partner else list(mal_slots)
    on_males = [mal_slots[partner_i - 1]] if has_partner else []
    return {
        "females": use_fems,
        "males": on_males,
        "male_sheets": male_sheets,
        "partner_i": partner_i,
        "has_partner": has_partner,
        "explicit_partner": explicit_partner,
        "beat_male": beat_male,
    }


def drafts_dir(root: str | Path | None = None) -> Path:
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    return base / "data" / "drafts"


def _check_draft_id(draft_id: str) -> str:
    sid = (draft_id or "").strip()
    if not _DRAFT_ID.fullmatch(sid):
        raise ValueError("非法草稿編號")
    return sid


def _dict_list(raw, limit: int) -> list:
    if not isinstance(raw, list):
        return []
    return [item for item in raw[:limit] if isinstance(item, dict)]


def normalize_draft(raw: dict, draft_id: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("草稿必須是物件")
    sid = _check_draft_id(draft_id or str(raw.get("id") or ""))
    story_id = re.sub(r"[^A-Za-z0-9_\-]", "", str(raw.get("story_id") or ""))[:80]
    pack_id = re.sub(r"[^A-Za-z0-9_\-]", "", str(raw.get("pack_id") or ""))[:120]
    return {
        "id": sid,
        "theme": str(raw.get("theme") or "")[:80],
        "characters": _dict_list(raw.get("characters"), 100),
        "locations": _dict_list(raw.get("locations"), 24),
        "motions": _dict_list(raw.get("motions"), 24),
        "segments": _dict_list(raw.get("segments"), 24),
        "story_id": story_id,
        "pack_id": pack_id,
        "joined": clean_joined(raw.get("joined")),
        "updated": time.time(),
    }


def _merge_newer_card_images(blob: dict, root: str | Path | None) -> None:
    """生成圖寫入後，舊的整份存檔不要把 image 蓋回去。"""
    path = drafts_dir(root) / f"{blob['id']}.json"
    if not path.is_file():
        return
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(old, dict):
        return
    prev: dict[str, dict] = {}
    for key in ("characters", "locations"):
        for card in old.get(key) or []:
            if isinstance(card, dict) and card.get("id"):
                prev[str(card["id"])] = card
    for key in ("characters", "locations"):
        for card in blob.get(key) or []:
            if not isinstance(card, dict):
                continue
            old_card = prev.get(str(card.get("id") or ""))
            if not old_card or not old_card.get("image"):
                continue
            try:
                old_at = float(old_card.get("image_at") or 0)
                new_at = float(card.get("image_at") or 0)
            except (TypeError, ValueError):
                continue
            if old_at > new_at:
                card["image"] = old_card.get("image")
                card["image_key"] = old_card.get("image_key") or ""
                card["image_source"] = old_card.get("image_source") or ""
                card["image_at"] = old_at


def save_draft(raw: dict, root: str | Path | None = None, draft_id: str = "") -> dict:
    blob = normalize_draft(raw, draft_id or (raw.get("id") if isinstance(raw, dict) else ""))
    _merge_newer_card_images(blob, root)
    folder = drafts_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{blob['id']}.json").write_text(
        json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    return blob


def load_draft(draft_id: str, root: str | Path | None = None) -> dict:
    sid = _check_draft_id(draft_id)
    path = drafts_dir(root) / f"{sid}.json"
    if not path.is_file():
        raise ValueError(f"找不到草稿: {sid}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("草稿不是物件")
    data["id"] = sid
    return data


def list_drafts(root: str | Path | None = None) -> list[dict]:
    folder = drafts_dir(root)
    if not folder.is_dir():
        return []
    rows = []
    for path in folder.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        sid = str(data.get("id") or path.stem)
        if not _DRAFT_ID.fullmatch(sid):
            continue
        rows.append({
            "id": sid,
            "theme": str(data.get("theme") or ""),
            "updated": float(data.get("updated") or path.stat().st_mtime),
            "segments": len(data.get("segments") or []),
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def delete_draft(draft_id: str, root: str | Path | None = None) -> None:
    sid = _check_draft_id(draft_id)
    base = drafts_dir(root)
    path = base / f"{sid}.json"
    if path.is_file():
        path.unlink()
    folder = (base / sid).resolve()
    if folder.is_dir() and str(folder).startswith(str(base.resolve())):
        shutil.rmtree(folder)


def _card_gender(card: dict) -> str:
    return "male" if str(card.get("gender") or "").lower() == "male" else "female"


def _card_title(card: dict) -> str:
    return str(card.get("title") or card.get("name") or "").strip()


_CARD_ID = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
_CARD_IMAGE = re.compile(r"^images/[A-Za-z0-9_\-]{1,40}\.png$")


def check_card_id(card_id: str) -> str:
    sid = (card_id or "").strip()
    if not _CARD_ID.fullmatch(sid):
        raise ValueError("非法卡片")
    return sid


def card_image_key(card: dict, kind: str) -> str:
    """圖是用哪組衣著／場地生的。改了就不沿用舊圖。"""
    if kind == "location":
        scene = str(card.get("scene") or "").strip()
        prompt = str(card.get("prompt") or "").strip()
        return f"loc|{scene}|{prompt}"
    gender = _card_gender(card)
    theme = str(card.get("theme") or "original").strip() or "original"
    title = _card_title(card)
    prompt = str(card.get("prompt") or "").strip()
    return f"char|{gender}|{theme}|{title}|{prompt}"


def card_theme_key(card: dict) -> str:
    """空字串＝原作衣著。不認識的鍵當成原作。"""
    key = str(card.get("theme") or "").strip()
    if not key or key.lower() == "original":
        return ""
    table = MALE_THEMES if _card_gender(card) == "male" else THEMES
    return key if key in table else ""


def location_prompt_text(loc: dict) -> str:
    bits = []
    key = str(loc.get("scene") or "").strip()
    if key:
        try:
            sc = scene_of(key)
        except ValueError:
            sc = None
        tags = ((sc or {}).get("tags") or "").strip()
        if tags:
            bits.append(tags)
    extra = str(loc.get("prompt") or "").strip()
    if extra:
        bits.append(extra)
    if not bits:
        name = str(loc.get("name") or "").strip()
        if name:
            bits.append(name)
    return ", ".join(bits)[:500]


def draft_images_dir(draft_id: str, root: str | Path | None = None) -> Path:
    return drafts_dir(root) / _check_draft_id(draft_id) / "images"


def draft_card_image_file(draft_id: str, card: dict, root: str | Path | None = None) -> Path | None:
    rel = str(card.get("image") or "").replace("\\", "/").strip()
    if not _CARD_IMAGE.fullmatch(rel):
        return None
    try:
        folder = drafts_dir(root) / _check_draft_id(draft_id)
    except ValueError:
        return None
    path = (folder / rel).resolve()
    images = (folder / "images").resolve()
    if not str(path).startswith(str(images)):
        return None
    return path if path.is_file() else None


def _ready_card_image(draft_id: str, card: dict, kind: str, root: str | Path | None) -> str:
    path = draft_card_image_file(draft_id, card, root)
    if not path:
        return ""
    source = str(card.get("image_source") or "")
    key = str(card.get("image_key") or "")
    if source == "upload" or key == "upload":
        return str(path)
    if key == card_image_key(card, kind):
        return str(path)
    return ""


def draft_motions_dir(draft_id: str, root: str | Path | None = None) -> Path:
    return drafts_dir(root) / _check_draft_id(draft_id) / "motions"


def draft_motion_file(draft_id: str, motion_id: str, root: str | Path | None = None) -> Path | None:
    try:
        mid = check_card_id(motion_id)
        folder = draft_motions_dir(draft_id, root).resolve()
    except ValueError:
        return None
    path = (folder / f"{mid}.mp4").resolve()
    if not str(path).startswith(str(folder)):
        return None
    return path if path.is_file() else None


def draft_cast_slots(draft: dict, root: str | Path | None = None) -> tuple[list[dict], list[dict]]:
    females, males = [], []
    draft_id = str((draft or {}).get("id") or "")
    for card in draft.get("characters") or []:
        if not isinstance(card, dict):
            continue
        title = _card_title(card)
        if not title:
            continue
        kind = str(card.get("kind") or "")
        slot = {
            "character": title,
            "voice_ref": str(card.get("voice_ref") or card.get("voiceRef") or "").strip(),
            "prompt": str(card.get("prompt") or "").strip() if kind == "custom" else "",
            "theme": card_theme_key(card),
            "image": _ready_card_image(draft_id, card, "character", root),
        }
        (males if _card_gender(card) == "male" else females).append(slot)
    if len(females) > 50 or len(males) > 50:
        raise ValueError("女角色卡、男角色卡各最多 50 張")
    return females, males


def _clip_mode_name(raw) -> str:
    return _CLIP_MODES.get(str(raw or "").strip().lower(), "r2v")


def _safe_clip_folder(folder: str) -> str:
    name = (folder or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return ""
    return name


def clip_output_url(out: Path, folder: str, filename: str) -> str:
    """輸出目錄裡這一段的影片或參考圖。沒有檔案就回空字串。"""
    name = _safe_clip_folder(folder)
    if not name or not filename or "/" in filename or "\\" in filename or ".." in filename:
        return ""
    root = Path(out).resolve()
    path = (root / name / filename).resolve()
    if not str(path).startswith(str(root)) or not path.is_file() or path.stat().st_size <= 0:
        return ""
    return f"/output/{name}/{filename}?v={int(path.stat().st_mtime)}"


def draft_segment_media(draft: dict, out: Path) -> dict:
    """每個段落目前有的動畫或參考圖。只給畫面用，不寫回草稿。"""
    media = {}
    for seg in (draft or {}).get("segments") or []:
        if not isinstance(seg, dict):
            continue
        sid = str(seg.get("id") or "")
        if not sid:
            continue
        folder = str(seg.get("folder") or "")
        video = clip_output_url(out, folder, "animation.mp4")
        image = ""
        for fname in ("scene.png", "character.png", "partner.png", "first_frame.png"):
            image = clip_output_url(out, folder, fname)
            if image:
                break
        media[sid] = {"video": video, "image": image}
    return media


_JOINED = re.compile(r"^(editpack_[A-Za-z0-9_\-]{1,80})/joined\.mp4$")


def clean_joined(raw) -> str:
    text = str(raw or "").replace("\\", "/").strip()
    return text if _JOINED.fullmatch(text) else ""


def draft_joined_url(draft: dict, out: Path) -> str:
    rel = clean_joined((draft or {}).get("joined"))
    match = _JOINED.fullmatch(rel)
    if not match:
        return ""
    return clip_output_url(out, match.group(1), "joined.mp4")


def draft_preview(draft: dict, root: str | Path | None, out: Path) -> dict:
    """主題卡片：優先合併後的整支，其次最後一段動畫，再其次參考圖。"""
    joined = draft_joined_url(draft, out)
    if joined:
        return {"kind": "video", "url": joined}
    media = draft_segment_media(draft, out)
    segs = [s for s in (draft.get("segments") or []) if isinstance(s, dict)]
    for seg in reversed(segs):
        item = media.get(str(seg.get("id") or "")) or {}
        if item.get("video"):
            return {"kind": "video", "url": item["video"]}
    for seg in reversed(segs):
        item = media.get(str(seg.get("id") or "")) or {}
        if item.get("image"):
            return {"kind": "image", "url": item["image"]}
    draft_id = str((draft or {}).get("id") or "")
    for key in ("characters", "locations"):
        for card in (draft or {}).get(key) or []:
            if not isinstance(card, dict):
                continue
            path = draft_card_image_file(draft_id, card, root)
            if not path:
                continue
            try:
                stamp = int(float(card.get("image_at") or path.stat().st_mtime))
            except (TypeError, ValueError):
                stamp = int(path.stat().st_mtime)
            return {
                "kind": "image",
                "url": f"/api/drafts/{draft_id}/images/{path.name}?v={stamp}",
            }
    return {"kind": "", "url": ""}


def draft_to_story(draft: dict, root: str | Path | None = None, segment_id: str = "") -> dict:
    """編輯模式草稿 → 短劇 JSON。角色編號跟 draft_cast_slots 的順序一致。

    segment_id 有值時只組那一段，其他段落沒填完也不擋。
    """
    if not isinstance(draft, dict):
        raise ValueError("草稿必須是物件")
    theme = str(draft.get("theme") or "").strip()
    if not theme:
        raise ValueError("請先填主題")
    cards = [c for c in (draft.get("characters") or []) if isinstance(c, dict) and _card_title(c)]
    females = [c for c in cards if _card_gender(c) != "male"]
    males = [c for c in cards if _card_gender(c) == "male"]
    if not females:
        raise ValueError("請至少一張女角色卡")
    if len(females) > 50 or len(males) > 50:
        raise ValueError("女角色卡、男角色卡各最多 50 張")
    fem_at = {str(c.get("id")): i + 1 for i, c in enumerate(females) if c.get("id")}
    male_at = {str(c.get("id")): i + 1 for i, c in enumerate(males) if c.get("id")}
    locs = {
        str(c.get("id")): c
        for c in (draft.get("locations") or [])
        if isinstance(c, dict) and c.get("id")
    }
    segs = [s for s in (draft.get("segments") or []) if isinstance(s, dict)]
    if segment_id:
        segs = [s for s in segs if str(s.get("id") or "") == segment_id]
        if not segs:
            raise ValueError("找不到這個段落")
    if not segs:
        raise ValueError("請至少一個段落")
    draft_id = _check_draft_id(str(draft.get("id") or "ed_draft"))
    fragments = []
    prev_scene = None
    for i, seg in enumerate(segs[:24]):
        name = str(seg.get("name") or f"{i + 1}").strip()[:40] or str(i + 1)
        char_ids = [str(x) for x in (seg.get("characterIds") or seg.get("character_ids") or [])]
        loc_ids = [str(x) for x in (seg.get("locationIds") or seg.get("location_ids") or []) if str(x) in locs]
        with_females = []
        with_males = []
        for cid in char_ids:
            if cid in fem_at and fem_at[cid] not in with_females:
                with_females.append(fem_at[cid])
            elif cid in male_at and male_at[cid] not in with_males:
                with_males.append(male_at[cid])
        if not with_females:
            raise ValueError(f"段落「{name}」請至少加入一張女角色卡")
        picked_locs = [locs[lid] for lid in loc_ids]
        extra = ", ".join(
            bit for bit in (location_prompt_text(loc) for loc in picked_locs) if bit
        )[:500]
        scene = "loc:" + "-".join(loc_ids) if loc_ids else ""
        scene_image = ""
        for loc in picked_locs:
            scene_image = _ready_card_image(draft_id, loc, "location", root)
            if scene_image:
                break
        dur = _clamp_beat_dur(seg.get("duration") or 8)
        plot = str(seg.get("plot") or "").strip()[:800] or name
        dialogue = str(seg.get("dialogue") or "").strip()[:200]
        link = "cut" if i == 0 else ("continue" if scene and scene == prev_scene else "reference")
        beat = {
            "title": name,
            "tags": str(seg.get("tags") or "").strip()[:300],
            "extra": extra,
            "plot": plot,
            "duration": dur,
            "solo": not with_males,
            "link": link,
            "with_females": with_females,
            "with_males": with_males,
            "clip_mode": _clip_mode_name(seg.get("clipMode") or seg.get("clip_mode")),
            "theme": card_theme_key(females[with_females[0] - 1]),
            "shots": [{
                "start": 0,
                "end": dur,
                "plot": plot,
                "camera": "static",
                "dialogue": dialogue,
            }],
        }
        if dialogue:
            beat["dialogue"] = dialogue
        if scene:
            beat["scene"] = scene
        if with_males:
            beat["partner"] = with_males[0]
            beat["male_theme"] = card_theme_key(males[with_males[0] - 1])
        if scene_image:
            beat["scene_image"] = scene_image
        motion_id = str(seg.get("motionId") or seg.get("motion_id") or "").strip()
        motion_mode = str(seg.get("motionMode") or seg.get("motion_mode") or "motion").strip().lower()
        if motion_mode not in {"motion", "audio"}:
            motion_mode = "motion"
        if beat["clip_mode"] == "r2v" and motion_id:
            motion_path = draft_motion_file(draft_id, motion_id, root)
            if not motion_path:
                motion_path = resolve_motion_clip(motion_id, root or _data_root(None))
            if motion_path:
                beat["motion_clip"] = motion_path.stem
                beat["motion_mode"] = motion_mode
        fragments.append(beat)
        prev_scene = scene or None
    sid = re.sub(r"[^A-Za-z0-9_\-]", "", str(draft.get("story_id") or ""))[:80]
    if not sid:
        sid = ("edit_" + draft_id.lower())[:80]
    return {
        "id": sid,
        "title": theme[:80],
        "summary": theme[:200],
        "clothing": "",
        "source": "editor",
        "cast": {"female": len(females), "male": len(males)},
        "fragments": fragments,
    }


def resolve_beat_action(
    beat: dict, catalog_names: list[str], rng: random.Random,
) -> str:
    family = (beat.get("action") or "").strip()
    if family:
        hits = family_actions(catalog_names, family)
        if hits:
            return rng.choice(hits)
    tags = (beat.get("tags") or family or "1girl, standing").strip()
    return tags

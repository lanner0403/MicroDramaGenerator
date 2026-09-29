"""本機 Ollama：發想角色、動作、秒數、LTX 動作稿。"""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

import requests

from .prompts import bounce_instruction
from .themes import theme_of

CHAR_SYSTEM = """You design ONE original ADULT (18+) anime character as comma-separated English Danbooru tags.
Rules:
- Output ONLY the tag list. No markdown, no quotes, no explanation.
- 12 to 22 lowercase English tags.
- Must include: adult, 20s or older implied by "adult woman" or "adult man".
- Describe hair, eyes, face, body, default outfit, accessories.
- Do NOT include: child, loli, shota, teen, underage, schoolgirl, background, quality tags, 1girl/1boy.
- Exactly one character. Be specific."""

ACTION_SYSTEM = """You invent ONE adult erotic action for an image-to-video model.
Reply with a single JSON object, no markdown:
{"name":"short english action name","tags":"comma-separated danbooru action tags","motion":"English sentence describing continuous motion from the first frame","duration":6}
Rules:
- Adult 18+ only. No minors.
- tags: 8-16 English tags describing pose and sexual act / sensual motion.
- motion: 1-3 English sentences: who + where + what motion, sequential. Camera holds a static shot.
- duration: integer seconds 4-12, enough to finish the motion, never over 15."""

DURATION_SYSTEM = """Given a character, action and theme, pick video duration.
Reply ONLY a JSON object: {"duration":8,"motion":"English motion sentences"}
duration is integer 4-12 (never over 15). motion is 1-3 English sentences for MiniMax H3 i2v."""

MOTION_EN_SYSTEM = """You write ONE MiniMax H3 I2VA [Shot 1] paragraph for image-to-video.
Output ONLY the shot paragraph. No markdown, no JSON, no field names, no quotes around the whole text.
Start with: [Shot 1] 2D-animated,
Rules:
- Adult 18+ only. No minors.
- English, present tense, 4 to 8 flowing sentences.
- <Picture 1> is the first frame. Preserve appearance, pose, clothing, composition, lighting.
- Then describe action onset and continuous development from that frame.
- CAMERA: write exactly: The camera holds a static shot.
- Forbidden: zoom, cut, angle change, [Shot 2], timestamps.
- Do NOT write integrated_multimodal_description, overall_soundscape, or non_diegetic_music.
- Do NOT write dialogue, speaker IDs, or <d> tags.
- Match the given action. Hand job, foot job, oral, kissing and similar: describe ONLY that local motion. No breast bounce, no butt bounce, no hip thrusting.
- Soft-body breast/butt bounce ONLY when the action is thrusting, riding, doggy, paizuri, or similar whole-body sex.
- No Danbooru tags. No comma-separated keyword lists.
- Do not invent a different action than the one given."""

MOTION_VL_SYSTEM = """You look at ONE still image (the first frame) and write a MiniMax H3 I2VA [Shot 1] paragraph.
Output ONLY the shot paragraph. No markdown, no JSON, no field names.
Start with: [Shot 1] 2D-animated,
Rules:
- Adult 18+ only. No minors.
- English, present tense, 4 to 8 flowing sentences.
- <Picture 1> is this image. Preserve appearance, pose, clothing, composition, lighting.
- Describe the motion that continues FROM this exact image: who is where, how the body moves, rhythm, facial change.
- Do NOT invent a different pose, outfit, or camera angle than what you see.
- CAMERA: write exactly: The camera holds a static shot.
- Forbidden: zoom, cut, angle change, [Shot 2], timestamps.
- Do NOT write integrated_multimodal_description, overall_soundscape, or non_diegetic_music.
- Do NOT write dialogue, speaker IDs, or <d> tags.
- Match the given action. Hand job, foot job, oral, kissing and similar: describe ONLY that local motion. No breast bounce, no butt bounce, no hip thrusting.
- Soft-body breast/butt bounce ONLY if the action is thrusting, riding, doggy, paizuri, or similar whole-body sex.
- No Danbooru tags. No comma-separated keyword lists."""

STORY_MOTION_SYSTEM = """You write ONE MiniMax H3 I2VA [Shot 1] paragraph for a short-film beat.
Output ONLY the shot paragraph. No markdown, no JSON, no field names, no quotes around the whole text.
Start with: [Shot 1] 2D-animated,
Rules:
- Adult 18+ only. No minors.
- English, present tense, 3 to 6 flowing sentences.
- <Picture 1> is the first frame. Preserve appearance, pose, clothing, composition.
- Follow THIS beat's plot: what happens in these seconds, in order.
- Describe body motion, expression, environment (rain, steam, crowd, water), and diegetic sound.
- Camera may pan or push in with small amplitude at slow speed if the plot needs it. No hard cuts. Do not add [Shot 2].
- Do NOT write integrated_multimodal_description, overall_soundscape, or non_diegetic_music.
- Do NOT write dialogue, speaker IDs, or <d> tags.
- Do NOT use a locked-camera looping sex template. Only describe sex if the beat is sexual.
- No Danbooru tags. No comma-separated keyword lists.
- Do not invent a different plot than the beat given."""

EXPAND_SYSTEM = """Act as a prompt maker.
- Break keywords by commas.
- Visual elements only. English tags.
- Format: subject, motion, scene, background.
- At most 40 tags. Same line. No enumeration.
- Include the user's words verbatim as the main subject.
- Adult 18+ only."""


class OllamaError(RuntimeError):
    pass


def apply_ollama_model(cfg: dict, model: str | None) -> dict:
    if not model or not str(model).strip():
        return cfg
    out = dict(cfg)
    oc = dict(out.get("ollama") or {})
    oc["model"] = model.strip()
    out["ollama"] = oc
    return out


def list_ollama_models(cfg: dict) -> list[dict]:
    """查本機 Ollama /api/tags，回傳 [{name, size}]。連不上回空清單。"""
    oc = cfg.get("ollama", {})
    url = oc.get("url", "http://127.0.0.1:11434").rstrip("/")
    try:
        r = requests.get(f"{url}/api/tags", timeout=5)
        r.raise_for_status()
    except requests.RequestException:
        return []
    models = []
    for m in (r.json().get("models") or []):
        name = m.get("name") or m.get("model") or ""
        if name:
            models.append({"name": name, "size": m.get("size") or 0})
    models.sort(key=lambda x: x["name"].lower())
    return models


def _chat(cfg: dict, system: str, user: str, seed: int | None = None) -> str:
    oc = cfg.get("ollama", {})
    url = oc.get("url", "http://127.0.0.1:11434").rstrip("/")
    model = oc.get("model")
    if not model:
        raise OllamaError("config.yaml 未設定 ollama.model")
    options = {"temperature": oc.get("temperature", 0.9)}
    if seed is not None:
        options["seed"] = seed
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "options": options,
    }
    try:
        r = requests.post(f"{url}/api/chat", json=payload, timeout=oc.get("timeout", 180))
    except requests.RequestException as e:
        raise OllamaError(f"連不上 Ollama（{url}）：{e}") from e
    if not r.ok:
        raise OllamaError(f"Ollama 錯誤 ({r.status_code}): {r.text[:500]}")
    return r.json().get("message", {}).get("content", "")


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _clean_tags(text: str) -> str:
    text = _strip_think(text).strip().strip("`\"' \n")
    for line in text.splitlines():
        line = line.strip()
        if line and "," in line:
            return ", ".join(t.strip() for t in line.rstrip(".").split(",") if t.strip())
    return ", ".join(t.strip() for t in text.replace("\n", ", ").split(",") if t.strip())


def _parse_json(text: str) -> dict:
    text = _strip_think(text)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise OllamaError(f"Ollama 沒回 JSON：{text[:300]}")
    return json.loads(m.group(0))


def ai_character(cfg: dict, theme: str | None = None, hint: str | None = None,
                 seed: int | None = None) -> dict:
    """回傳 {name, prompt}。"""
    lines = ["Design an adult character."]
    th = theme_of(theme) if theme else None
    if th and th.get("label"):
        lines.append(f"- Outfit theme: {th['label']} ({th.get('tags','')})")
    if hint and hint.strip():
        lines.append(f"- Extra (may be Chinese): {hint.strip()}")
    tags = _clean_tags(_chat(cfg, CHAR_SYSTEM, "\n".join(lines), seed))
    if not tags:
        raise OllamaError("Ollama 回傳空白角色")
    name = ai_name(cfg, theme, tags, seed)
    return {"name": name, "prompt": tags}


def ai_name(cfg: dict, theme: str | None, desc: str, seed: int | None = None) -> str:
    system = (
        "Invent ONE Chinese name (2-4 characters) for this adult anime character. "
        "Output ONLY the name."
    )
    user = f"Theme: {theme or '-'}\nAppearance: {desc[:400]}"
    content = _strip_think(_chat(cfg, system, user, seed))
    name = content.splitlines()[0].strip() if content else ""
    name = re.sub(r'[\\/:*?"<>|.\s]+', "", name).strip("'\"`")[:20]
    if not name:
        raise OllamaError("Ollama 未能生成名稱")
    return name


def ai_action(cfg: dict, theme: str | None = None, character: str | None = None,
              hint: str | None = None, seed: int | None = None) -> dict:
    """回傳 {name, tags, motion, duration}。"""
    lines = ["Invent one adult action."]
    th = theme_of(theme) if theme else None
    if th:
        lines.append(f"- Theme/outfit: {th['label']}")
    if character:
        lines.append(f"- Character: {character}")
    if hint:
        lines.append(f"- Extra: {hint}")
    data = _parse_json(_chat(cfg, ACTION_SYSTEM, "\n".join(lines), seed))
    dur = int(data.get("duration") or 6)
    dur = max(cfg["video"]["duration_min"], min(cfg["video"]["duration_max"], dur))
    return {
        "name": str(data.get("name") or "action").strip(),
        "tags": str(data.get("tags") or "").strip(),
        "motion": str(data.get("motion") or "").strip(),
        "duration": dur,
    }


def ai_motion_paragraph(
    cfg: dict,
    *,
    character: str = "",
    action: str = "",
    action_tags: str = "",
    theme: str | None = None,
    extra: str = "",
    duration: int | None = None,
    seed: int | None = None,
) -> str:
    """Ollama 產 LTX 用英文 motion paragraph。失敗拋 OllamaError。"""
    th = theme_of(theme) if theme else None
    lines = [
        f"Action: {action or '-'}",
        f"Action tags (pose hint only, do not copy as tags): {action_tags or '-'}",
        f"Duration: {duration or cfg['video']['duration_default']} seconds of continuous motion",
        "Camera: The camera holds a static shot. Same framing as <Picture 1>.",
        bounce_instruction(action, action_tags),
    ]
    if character:
        lines.append(f"Character name (do not describe looks): {character}")
    if th:
        where = th.get("motion") or th.get("label") or ""
        if where:
            lines.append(f"Setting hint: {where}")
    if extra and extra.strip():
        lines.append(f"Extra: {extra.strip()}")
    text = _strip_think(_chat(cfg, MOTION_EN_SYSTEM, "\n".join(lines), seed))
    text = text.strip().strip("`\"'")
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    text = " ".join(text.split())
    if len(text) < 40:
        raise OllamaError(f"Ollama 英文動作稿太短：{text[:120]}")
    return text


def _image_b64(path: str | Path, max_side: int = 1024) -> str:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _vision_chat(
    cfg: dict,
    system: str,
    user: str,
    image_path: str | Path,
    *,
    temperature: float | None = None,
    seed: int | None = None,
    fmt: str | None = None,
) -> str:
    oc = cfg.get("ollama") or {}
    url = oc.get("url", "http://127.0.0.1:11434").rstrip("/")
    model = (oc.get("vision_model") or "").strip()
    if not model:
        raise OllamaError("config.yaml 未設定 ollama.vision_model")
    path = Path(image_path)
    if not path.is_file():
        raise OllamaError(f"找不到首幀: {path}")
    options = {"temperature": oc.get("temperature", 0.9) if temperature is None else temperature}
    if seed is not None:
        options["seed"] = seed
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user,
                "images": [_image_b64(path)],
            },
        ],
        "stream": False,
        "think": False,
        "options": options,
    }
    if fmt:
        payload["format"] = fmt
    try:
        r = requests.post(f"{url}/api/chat", json=payload, timeout=oc.get("timeout", 180))
    except requests.RequestException as e:
        raise OllamaError(f"連不上 Ollama（{url}）：{e}") from e
    if not r.ok:
        raise OllamaError(f"Ollama 看圖錯誤 ({r.status_code}): {r.text[:500]}")
    return _strip_think(r.json().get("message", {}).get("content", ""))


def ai_story_motion(
    cfg: dict,
    *,
    beat: dict,
    character: str = "",
    duration: int | None = None,
    nsfw: bool = False,
    seed: int | None = None,
    link: str = "cut",
    prev_plot: str = "",
) -> str:
    """依短篇段落劇情寫圖生影動作稿。失敗拋 OllamaError。"""
    plot = (beat.get("plot") or beat.get("title") or "").strip()
    title = (beat.get("title") or "").strip()
    extra = (beat.get("extra") or "").strip()
    action = (beat.get("action") or "").strip()
    tags = (beat.get("tags") or "").strip()
    lines = [
        f"Beat title: {title or '-'}",
        f"Plot (follow this): {plot or '-'}",
        f"Duration: {duration or cfg['video']['duration_default']} seconds",
        "Write a MiniMax H3 [Shot 1] paragraph for this beat. Not a locked looping sex clip.",
    ]
    if character:
        lines.append(f"Character name (do not describe looks): {character}")
    if extra:
        lines.append(f"Setting: {extra}")
    if action:
        lines.append(f"Action hint: {action}")
    if tags:
        lines.append(f"Pose hint (do not copy as tags): {tags}")
    if link == "continue":
        lines.append(
            "CONTINUATION: the first frame is the last frame of the previous shot. "
            "Keep that pose and framing. Evolve into this beat. Do not reset."
        )
        if prev_plot:
            lines.append(f"Previous beat ended at: {prev_plot}")
    elif link == "reference":
        lines.append(
            "NEW SHOT of the same people/setting. Motion starts from this new framing."
        )
    if nsfw:
        lines.append(
            "This beat is sexual. Describe the act as the plot, not a generic thrust loop."
        )
        if action or tags:
            lines.append(bounce_instruction(action, tags))
    else:
        lines.append(
            "This beat is NOT sexual. No nudity, no sex, no moaning, no thrusting."
        )
    text = _strip_think(_chat(cfg, STORY_MOTION_SYSTEM, "\n".join(lines), seed))
    text = text.strip().strip("`\"'")
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    text = " ".join(text.split())
    if len(text) < 40:
        raise OllamaError(f"短篇動作稿太短：{text[:120]}")
    return text


def ai_motion_from_image(
    cfg: dict,
    image_path: str | Path,
    *,
    action: str = "",
    action_tags: str = "",
    extra: str = "",
    duration: int | None = None,
    seed: int | None = None,
) -> str:
    """用 vision 模型看首幀，產英文 LTX motion。失敗拋 OllamaError。"""
    lines = [
        f"Action name: {action or '-'}",
        f"Action tags (hint only): {action_tags or '-'}",
        f"Duration: {duration or cfg['video']['duration_default']} seconds",
        "Write a MiniMax H3 [Shot 1] paragraph that continues this image. The camera holds a static shot.",
        bounce_instruction(action, action_tags),
    ]
    if extra and extra.strip():
        lines.append(f"Extra: {extra.strip()}")
    text = _vision_chat(cfg, MOTION_VL_SYSTEM, "\n".join(lines), image_path, seed=seed)
    text = text.strip().strip("`\"'")
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    text = " ".join(text.split())
    if len(text) < 40:
        raise OllamaError(f"看圖動作稿太短：{text[:120]}")
    return text


def free_vision(cfg: dict) -> bool:
    """unload Ollama vision_model（keep_alive=0）。沒載入或連不上回 False。"""
    oc = cfg.get("ollama") or {}
    url = oc.get("url", "http://127.0.0.1:11434").rstrip("/")
    model = (oc.get("vision_model") or "").strip()
    if not model:
        return False
    try:
        ps = requests.get(f"{url}/api/ps", timeout=5)
        if ps.ok:
            loaded = False
            for m in (ps.json().get("models") or []):
                n = (m.get("name") or m.get("model") or "").strip()
                if n and (n == model or n.startswith(model) or model.startswith(n)):
                    loaded = True
                    break
            if not loaded:
                return False
        r = requests.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=60,
        )
        return r.ok
    except requests.RequestException:
        return False


def ai_duration_and_motion(cfg: dict, character: str, action: str, theme: str | None,
                           extra: str = "", seed: int | None = None) -> dict:
    lines = [
        f"Character: {character}",
        f"Action: {action}",
        f"Theme: {theme or '-'}",
    ]
    if extra:
        lines.append(f"Extra: {extra}")
    data = _parse_json(_chat(cfg, DURATION_SYSTEM, "\n".join(lines), seed))
    dur = int(data.get("duration") or cfg["video"]["duration_default"])
    dur = max(cfg["video"]["duration_min"], min(cfg["video"]["duration_max"], dur))
    return {"duration": dur, "motion": str(data.get("motion") or "").strip()}


DIALOGUE_SYSTEM = """You write a short spoken line for an adult anime video (the i2v model synthesizes the voice).
Reply with a single JSON object, no markdown:
{"dialogue":"...","tone":"..."}
Rules:
- Adult 18+ only. No minors.
- dialogue: the spoken words ONLY, no quotes around the whole string.
- If language is ja: Japanese (hiragana/katakana/kanji), 10-32 characters, 1-2 short phrases.
- Moans must be INTENSE, not mild: prefer んぁあっ / はぁんっ / あっあっ over plain んっ or はぁ.
- If language is zh: Traditional Chinese, similarly short and intense (嗯啊啊、哈啊).
- If language is en: English, similarly short and intense (ahh—, nnh).
- tone: a few words, intense panting (e.g. 激しく甘い喘ぎ / ragged sweet moan). Do not describe a calm voice.
- Match the action and outfit theme."""


def ai_dialogue(cfg: dict, *, character: str = "", action: str = "",
                theme: str | None = None, extra: str = "",
                language: str = "ja", seed: int | None = None) -> dict:
    """回傳 {dialogue, tone}。"""
    lines = [
        f"Language: {language}",
        f"Character: {character or '-'}",
        f"Action: {action or '-'}",
        f"Theme: {theme or '-'}",
    ]
    if extra:
        lines.append(f"Extra: {extra[:200]}")
    data = _parse_json(_chat(cfg, DIALOGUE_SYSTEM, "\n".join(lines), seed))
    dialogue = str(data.get("dialogue") or "").strip().strip("「」『』\"'")
    tone = str(data.get("tone") or "").strip()
    if not dialogue:
        raise OllamaError("Ollama 回傳空白台詞")
    return {"dialogue": dialogue, "tone": tone}


def ai_expand(cfg: dict, text: str, seed: int | None = None) -> str:
    return _clean_tags(_chat(cfg, EXPAND_SYSTEM, text, seed))


STORY_GEN_SYSTEM = """You write a short adult (18+) anime micro-drama as JSON for a reference-to-video pipeline.
Reply with ONE JSON object, no markdown:
{
  "id": "snake_case_english_id",
  "title": "Chinese title",
  "summary": "one or two Chinese sentences",
  "clothing": "english clothing tags for the woman at the start, not a costume unless asked",
  "fragments": [
    {
      "title": "Chinese beat title",
      "tags": "english danbooru tags for pose and act",
      "extra": "english location, lighting, set dressing only",
      "plot": "English present-tense plot, 2-4 sentences",
      "duration": 8,
      "solo": false,
      "nude": false,
      "link": "cut",
      "shots": [
        {"start": 0, "end": 4, "plot": "English shot action", "camera": "static", "dialogue": ""}
      ]
    }
  ]
}
Rules:
- Adult 18+ only. No minors, no loli, no shota, no schoolchild.
- 4 to 6 fragments. Each duration is an integer 4-12. Total 24-60 seconds.
- extra is place/light/set only: no people, no sex acts, no camera.
- shots cover the beat duration without gaps. 1-3 shots per beat.
- First beat link is always "cut". Same location: "continue" or "reference". New location: "reference".
- solo true only if the man is absent that beat.
- nude true only after clothes come off.
- Optional short Japanese dialogue on a shot (hiragana/katakana), else "".
- Do not name real underage characters as children; treat named cast as adults.
- Plot refers to them as the woman / the man. Do not invent extra people."""


def _clamp_dur(n, lo: int = 4, hi: int = 12) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = 6
    return max(lo, min(hi, v))


def _slug_story_id(raw: str) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", (raw or "").lower()).strip("_")
    return (text[:40] or "micro_drama")


def _normalize_ai_story(data: dict, *, female: str = "", male: str = "") -> dict:
    if not isinstance(data, dict):
        raise OllamaError("短劇不是 JSON 物件")
    title = str(data.get("title") or "未命名短劇").strip()[:80]
    sid = _slug_story_id(str(data.get("id") or title))
    frags_in = data.get("fragments") or data.get("beats") or []
    if not isinstance(frags_in, list):
        raise OllamaError("短劇 fragments 不是陣列")
    out_frags = []
    for i, raw in enumerate(frags_in[:8]):
        if not isinstance(raw, dict):
            continue
        dur = _clamp_dur(raw.get("duration") or 6)
        shots_in = raw.get("shots") or []
        shots = []
        if isinstance(shots_in, list):
            for s in shots_in[:4]:
                if not isinstance(s, dict):
                    continue
                shots.append({
                    "start": float(s.get("start") if s.get("start") is not None else 0),
                    "end": float(s.get("end") if s.get("end") is not None else dur),
                    "plot": str(s.get("plot") or "").strip(),
                    "camera": str(s.get("camera") or "static").strip().lower() or "static",
                    "dialogue": str(s.get("dialogue") or "").strip(),
                })
        if not shots:
            shots = [{"start": 0, "end": dur, "plot": str(raw.get("plot") or "").strip(),
                      "camera": "static", "dialogue": ""}]
        link = str(raw.get("link") or ("cut" if i == 0 else "reference")).strip().lower()
        if link not in {"cut", "continue", "reference"}:
            link = "cut" if i == 0 else "reference"
        beat = {
            "title": str(raw.get("title") or f"第{i+1}段").strip()[:40],
            "tags": str(raw.get("tags") or "").strip(),
            "extra": str(raw.get("extra") or "").strip(),
            "plot": str(raw.get("plot") or "").strip(),
            "duration": dur,
            "solo": bool(raw.get("solo")),
            "nude": bool(raw.get("nude")),
            "link": link,
            "shots": shots,
        }
        if raw.get("action"):
            beat["action"] = str(raw.get("action")).strip()
        if raw.get("clothing"):
            beat["clothing"] = str(raw.get("clothing")).strip()
        if not beat["plot"]:
            beat["plot"] = beat["title"]
        out_frags.append(beat)
    if len(out_frags) < 3:
        raise OllamaError(f"短劇段落不足（得到 {len(out_frags)}，至少 3）")
    return {
        "id": sid,
        "title": title,
        "summary": str(data.get("summary") or "").strip()[:200],
        "clothing": str(data.get("clothing") or "").strip(),
        "female": female,
        "male": male,
        "source": "ollama",
        "fragments": out_frags,
    }


def ai_story(
    cfg: dict,
    *,
    female: str = "",
    male: str = "",
    premise: str = "",
    nsfw: bool = True,
    seed: int | None = None,
) -> dict:
    """用 Ollama 寫一篇短劇 JSON（fragments 格式與內建劇本相同）。"""
    lines = [
        "Write one micro-drama for MiniMax H3 reference-to-video.",
        f"Woman (identity only, do not describe looks): {female or 'an adult anime woman'}",
    ]
    if male:
        lines.append(f"Man (identity only, do not describe looks): {male}")
    else:
        lines.append("Man: optional unnamed adult man. Some beats may be solo.")
    if premise and premise.strip():
        lines.append(f"Premise (may be Chinese): {premise.strip()}")
    else:
        lines.append("Invent a short encounter with a clear beginning, middle, and end.")
    if nsfw:
        lines.append(
            "Adult sexual content is allowed if the premise calls for it. "
            "Keep the first beat as setup unless the premise starts in media res."
        )
    else:
        lines.append(
            "Keep it non-sexual: no nudity, no sex acts, no groping. "
            "Drama, dialogue, and location only."
        )
    data = _parse_json(_chat(cfg, STORY_GEN_SYSTEM, "\n".join(lines), seed))
    return _normalize_ai_story(data, female=female, male=male)

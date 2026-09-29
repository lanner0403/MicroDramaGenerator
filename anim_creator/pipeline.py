"""單支／批次動畫流水線：Diffusers 首幀 → LTX 2.3 圖生影。"""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

from .catalog import Catalog
from .comfy_client import ComfyClient, ComfyUIError
from .config import (
    default_male_image,
    h3_turbo_steps,
    output_dir,
    pick_h3_effect_loras,
    resolve_diffusers_model,
    resolve_video_model,
    video_is_h3,
)
from .diffusers_client import DiffusersClient, DiffusersError, free_pipe, mock_image
from .ollama_gen import (
    OllamaError,
    ai_action,
    ai_character,
    ai_dialogue,
    ai_duration_and_motion,
    ai_motion_from_image,
    ai_motion_paragraph,
    ai_story_motion,
    apply_ollama_model,
    free_vision,
)
from .prompts import (
    DEFAULT_MALE,
    as_climax_shot,
    compose_character_ref_prompt,
    compose_climax_motion,
    compose_extend_motion,
    compose_partner_ref_prompt,
    compose_motion_prompt,
    compose_scene_ref_prompt,
    CONTINUE_I2V_SOUNDSCAPE,
    compose_still_prompt,
    extract_legwear,
    negative_scene,
    inject_climax_shot,
    lock_camera_en,
    lock_legwear,
    has_legwear,
    looks_like_h3_prompt,
    looks_like_r2v_prompt,
    looks_nude,
    negative_partner_sheet,
    negative_ref_sheet,
    negative_still,
    slug,
    strip_spoken_dialogue,
    wrap_h3_i2va,
)
from .sequences import build_sequence_plans
from .stories import (
    attach_extra_cast,
    attach_identity_closeups,
    attach_motion_clip,
    attach_video_continue,
    beat_cast,
    beat_clothing_key,
    beat_dialogue,
    beat_male_clothing_key,
    beat_partner_index,
    beat_is_nsfw,
    beat_motion_clip,
    beat_plot_text,
    beat_scene_key,
    beat_visual_look,
    compose_story_i2v,
    compose_story_motion,
    compose_story_r2v,
    detach_motion_clip,
    draft_cast_slots,
    draft_to_story,
    get_story,
    lock_r2v_anime_style,
    meta_motion_clip,
    probe_duration,
    resolve_beat_action,
    resolve_beat_link,
    resolve_motion_clip,
    shift_motion_video_tag,
    story_video_key,
)
from .themes import male_theme_of, random_theme_key, scene_of, theme_of
from .voice import (
    fallback_dialogue,
    voice_kind,
    fit_duration,
    h3_speaker_desc,
    resolve_clone_ref,
    voice_enabled,
    voice_language,
    voice_ref_path,
    voice_style as resolve_voice_style,
    voice_tone,
    voice_ref_style,
)
from .voxcpm_clone import VoxCPMError, clone_dialogue, free_voxcpm
from .workflows import build_i2v_workflow, build_image_workflow, build_r2v_workflow

_SHEET_BG = 242
_SHEET_DET_W = 512


def _append_extra_cast_refs(refs: list, dest: Path, has_partner: bool) -> None:
    """第二人起：先女角 character_2…，有男主角時再接 partner_2…。編號跟鏡頭稿一致。"""
    for i in range(2, 51):
        path = dest / f"character_{i}.png"
        if path.is_file():
            refs.append(path)
    if not has_partner:
        return
    for i in range(2, 51):
        path = dest / f"partner_{i}.png"
        if path.is_file():
            refs.append(path)


def _runs_1d(dens: list[float], t: float) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    i = 0
    n = len(dens)
    while i < n:
        if dens[i] >= t:
            j = i
            while j < n and dens[j] >= t:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _merge_runs(runs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    if not runs:
        return []
    out = [[runs[0][0], runs[0][1]]]
    for a, b in runs[1:]:
        if a - out[-1][1] <= gap:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _sheet_fg(small: Image.Image) -> list[list[int]]:
    px = small.load()
    w, h = small.size
    fg = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b = px[x, y][:3]
            row.append(1 if r < _SHEET_BG or g < _SHEET_BG or b < _SHEET_BG else 0)
        fg.append(row)
    return fg


def _sheet_regions(fg: list[list[int]]) -> list[tuple[int, int, int, int, int]]:
    h = len(fg)
    w = len(fg[0]) if h else 0
    col = [sum(fg[y][x] for y in range(h)) / h for x in range(w)]
    med = sorted(col)[w // 2] if w else 0.0
    t = max(0.02, med * 0.4)
    xs = _runs_1d(col, t)
    gap = max(2, int(h * 0.006))
    out: list[tuple[int, int, int, int, int]] = []
    for x0, x1 in xs:
        span = max(1, x1 - x0)
        row = [sum(fg[y][x] for x in range(x0, x1)) / span for y in range(h)]
        pos = sorted(v for v in row if v > 0)
        yt = max(0.02, (pos[len(pos) // 2] if pos else 0.02) * 0.25)
        for y0, y1 in _merge_runs(_runs_1d(row, yt), gap):
            out.append((x0, y0, x1, y1, (x1 - x0) * (y1 - y0)))
    return out


def _pad_square(im: Image.Image, fill=(255, 255, 255)) -> Image.Image:
    w, h = im.size
    side = max(w, h)
    out = Image.new("RGB", (side, side), fill)
    out.paste(im, ((side - w) // 2, (side - h) // 2))
    return out


def crop_sheet_identity(src: Path, dest_front: Path, dest_face: Path) -> bool:
    """從角色三視圖切出正面全身與臉部特寫。失敗則 False，呼叫端改傳原圖。"""
    try:
        im = Image.open(src).convert("RGB")
    except OSError:
        return False
    w, h = im.size
    if w < 32 or h < 32:
        return False
    det_w = min(_SHEET_DET_W, w)
    det_h = max(1, int(det_w * h / w))
    small = im.resize((det_w, det_h), Image.BILINEAR)
    regs = _sheet_regions(_sheet_fg(small))
    if not regs:
        return False
    sx = w / det_w
    sy = h / det_h

    def _scale(r: tuple[int, int, int, int, int]) -> tuple[int, int, int, int, int]:
        x0, y0, x1, y1, a = r
        return (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy), a)

    regs_s = [_scale(r) for r in regs]
    tall = [r for r in regs_s if (r[3] - r[1]) >= 0.38 * h]
    if tall:
        max_a = max(r[4] for r in tall)
        cands = [r for r in tall if r[4] >= 0.55 * max_a]
        front = min(cands, key=lambda r: r[0])
    else:
        front = max(regs_s, key=lambda r: r[4])
    fx0, fy0, fx1, fy1, _ = front
    pad = max(4, int((fx1 - fx0) * 0.06))
    box = (
        max(0, fx0 - pad),
        max(0, fy0 - pad),
        min(w, fx1 + pad),
        min(h, fy1 + pad),
    )
    if box[2] - box[0] < 16 or box[3] - box[1] < 16:
        return False
    fig = im.crop(box)
    dest_front.parent.mkdir(parents=True, exist_ok=True)
    _pad_square(fig).save(dest_front)

    heads: list[tuple[tuple[int, int, int, int, int], float]] = []
    for r in regs_s:
        rh = r[3] - r[1]
        rw = r[2] - r[0]
        if rh < 0.10 * h or rh > 0.20 * h or rw < 0.08 * w:
            continue
        aspect = min(rw, rh) / max(rw, rh)
        if aspect < 0.65:
            continue
        if abs(r[0] - fx0) < 8 and abs(r[1] - fy0) < 8:
            continue
        heads.append((r, aspect * r[4]))
    if heads:
        hx0, hy0, hx1, hy1, _ = max(heads, key=lambda x: x[1])[0]
        hpad = max(4, int((hx1 - hx0) * 0.08))
        hbox = (
            max(0, hx0 - hpad),
            max(0, hy0 - hpad),
            min(w, hx1 + hpad),
            min(h, hy1 + hpad),
        )
        face = im.crop(hbox)
    else:
        fh = max(32, int(fig.size[1] * 0.28))
        face = fig.crop((0, 0, fig.size[0], fh))
    _pad_square(face).save(dest_face)
    return dest_front.is_file() and dest_face.is_file()


class Pipeline:
    def __init__(self, cfg: dict, catalog: Catalog, log=print, progress=None):
        self.cfg = cfg
        self.catalog = catalog
        self.log = log
        self.progress = progress or (lambda **kw: None)
        c = cfg["comfyui"]
        self.comfy = ComfyClient(c["url"], c["poll_interval"], c["timeout"])

    def _set_progress(self, **kw):
        try:
            self.progress(**kw)
        except Exception:
            pass

    def resolve_image_backend(self, requested: str | None = None) -> str:
        backend = (requested or self.cfg["image"].get("backend") or "diffusers").lower()
        if backend in {"auto", "a1111"}:
            return "diffusers"
        if backend not in {"diffusers", "comfyui", "mock"}:
            raise ValueError(f"未知首幀後端: {backend}")
        return backend

    def generate_one(
        self,
        *,
        character: str | None = None,
        action: str | None = None,
        theme: str | None = None,
        scene: str | None = None,
        extra: str = "",
        duration: int | None = None,
        seed: int | None = None,
        random_character: bool = False,
        random_action: bool = False,
        ai_character_flag: bool = False,
        ai_action_flag: bool = False,
        nsfw: bool = True,
        quality: bool = True,
        more_detail: bool = False,
        less_detail: bool = False,
        character_enhance: bool = False,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        video_model: str | None = None,
        still_prompt: str | None = None,
        motion_prompt: str | None = None,
        voice: bool | None = None,
        language: str | None = None,
        dialogue: str | None = None,
        ollama_model: str | None = None,
        name: str | None = None,
        image_only: bool = False,
        keep_pipe: bool = False,
        english_motion: bool | None = None,
        climax: bool | None = None,
        extra_meta: dict | None = None,
        nude: bool = False,
        theme_first: bool = False,
        voice_style: str | None = None,
        init_image: str | Path | None = None,
        turbo_steps: int | None = None,
    ) -> dict:
        if ollama_model:
            self.cfg = apply_ollama_model(self.cfg, ollama_model)
        scene = (scene or "").strip() or None
        if scene:
            scene_of(scene)
        vkey, vlabel, vinfo = self._video_info(video_model)
        rng = random.Random(seed)
        char_title, char_prompt, char_label = self._resolve_character(
            character, random_character, ai_character_flag, theme, extra, seed, rng)
        act_name, act_tags, ai_motion, ai_dur = self._resolve_action(
            action, random_action, ai_action_flag, theme, char_label, extra, seed, rng)

        if duration is None:
            if ai_dur:
                duration = ai_dur
            elif ai_action_flag or ai_character_flag:
                try:
                    picked = ai_duration_and_motion(
                        self.cfg, char_label, act_name, theme, extra, seed)
                    duration = picked["duration"]
                    ai_motion = ai_motion or picked.get("motion")
                    self.log(f"  AI 決定時長 {duration}s")
                except OllamaError as e:
                    self.log(f"  AI 時長失敗，改用預設：{e}")
                    duration = self.cfg["video"]["duration_default"]
            else:
                duration = self.cfg["video"]["duration_default"]
        duration = int(duration)
        duration = max(vinfo["duration_min"], min(vinfo["duration_max"], duration))

        still = (still_prompt or "").strip() or compose_still_prompt(
            self.cfg, char_prompt, act_tags, theme, extra,
            nsfw=nsfw, quality=quality, more_detail=more_detail,
            less_detail=less_detail, character_enhance=character_enhance,
            nude=nude, theme_first=theme_first, scene_key=scene)

        use_voice = False if image_only else voice_enabled(self.cfg, voice)
        lang = voice_language(self.cfg, language)
        vstyle = resolve_voice_style(self.cfg, voice_style)
        tone = voice_tone(lang, vstyle)
        spoken = ""
        vkind = voice_kind(act_name, act_tags)
        if use_voice:
            spoken, _dlg_tone = self._resolve_dialogue(
                dialogue, act_name, char_label, theme, extra, lang, seed, rng,
                tags=act_tags)
            if spoken:
                self.log(f"  語音({lang}/{vstyle}): {spoken}")
            elif vkind == "suck":
                self.log("  語音: 吸吮聲（無台詞）")
            elif vkind == "pant":
                self.log("  語音: 喘息（無台詞）")
            if spoken:
                duration = fit_duration(
                    duration, spoken,
                    vinfo["duration_min"], vinfo["duration_max"])
        elif image_only and vkind == "talk":
            spoken = fallback_dialogue(act_name, lang, rng)

        use_en = self._english_motion_on(english_motion)
        h3 = video_is_h3(self.cfg, vkey)
        custom_motion = (motion_prompt or "").strip()
        if use_en and not custom_motion:
            ai_motion = None
        motion = self._build_motion(
            char_label, act_name, act_tags, theme, extra,
            ai_motion=ai_motion, spoken=spoken, lang=lang, tone=tone,
            motion_prompt=custom_motion, use_en=use_en,
            image_only=image_only, duration=duration, seed=seed,
            skip_llm=bool(use_en and not custom_motion and not image_only),
            h3=h3, voice_style=vstyle, scene=scene)
        if not h3:
            if use_voice and spoken and spoken not in motion:
                from .voice import attach_voice
                motion = attach_voice(motion, spoken, language=lang, tone=tone, english=use_en)
            if use_en:
                motion = lock_camera_en(motion)
        use_climax = self._climax_on(climax) and not image_only
        climax_secs = 0
        if use_climax:
            duration, climax_secs = self._climax_budget(duration, vinfo)
            if not climax_secs:
                use_climax = False
        main_duration = duration

        folder = name or self._folder_name(char_label, act_name, theme, scene)
        dest = output_dir(self.cfg) / folder
        dest.mkdir(parents=True, exist_ok=True)
        frame_path = dest / "first_frame.png"
        video_path = dest / "animation.mp4"

        backend = self.resolve_image_backend(image_backend)
        model_key, model_label, _ = self._model_info(diffusers_model)
        self.log(f"▶ {folder}")
        self.log(f"  角色: {char_label}")
        sc_label = (scene_of(scene) or {}).get("label") if scene else ""
        self.log(
            f"  動作: {act_name}　主題: {theme or '（無）'}"
            f"　場景: {sc_label or '（主題）'}　{duration}s")
        self.log(f"  首幀後端: {backend}　模型: {model_label}　尺寸: {self.cfg['image']['width']}x{self.cfg['image']['height']}")
        if not image_only:
            self.log(f"  圖生影: {vlabel}")
            if use_climax:
                self.log(f"  高潮 [Shot 2] {climax_secs}s，總長 {duration + climax_secs}s")

        last_frame_name = None
        climax_motion = None
        try:
            if not keep_pipe:
                self._free_comfy()
            self._set_progress(stage="frame", progress=0, message="生成圖像…")
            self._make_still(
                backend, still, frame_path, seed, diffusers_model,
                init_image=init_image)
            self._set_progress(stage="frame", progress=100, message="圖像完成")
            if not image_only:
                if backend == "diffusers" and free_pipe():
                    self.log(f"  已卸載 Diffusers，釋放 VRAM 給 {vlabel}")
                if use_en and not custom_motion:
                    motion = self._motion_from_frame(
                        frame_path, act_name, act_tags, extra, spoken, lang, tone,
                        duration, seed, h3=h3, voice_style=vstyle)
                motion = self._finalize_motion(
                    motion, video_model=vkey,
                    spoken=spoken if use_voice else "",
                    lang=lang, tone=tone, use_en=use_en,
                    action=act_name, tags=act_tags, nsfw=nsfw,
                    voice_style=vstyle)
                video_motion = motion
                if use_climax:
                    video_motion, climax_motion = self._attach_climax_shot(
                        motion, act_name, act_tags, lang, climax_secs,
                        voice_style=vstyle, video_model=vkey)
                    duration = main_duration + climax_secs
                self._free_vision()
                self._set_progress(stage="video", progress=None, message="生成動畫…")
                self._make_video(frame_path, video_motion, video_path, duration, seed,
                                 video_model=vkey, turbo_steps=turbo_steps,
                                 nsfw=nsfw, climax=use_climax,
                                 action=act_name, tags=act_tags, extra=extra,
                                 look=still)
                self._set_progress(stage="video", progress=100, message="動畫完成")
            elif backend == "diffusers" and not keep_pipe:
                if free_pipe():
                    self.log("  已卸載 Diffusers")
        except Exception:
            if not keep_pipe:
                free_pipe()
            self._free_vision()
            raise

        if image_only:
            motion = self._finalize_motion(
                motion, video_model=vkey,
                spoken=spoken if use_voice else "",
                lang=lang, tone=tone, use_en=use_en,
                action=act_name, tags=act_tags, nsfw=nsfw,
                voice_style=vstyle)

        meta = {
            "folder": folder,
            "character": char_title,
            "character_label": char_label,
            "character_prompt": char_prompt,
            "action": act_name,
            "action_tags": act_tags,
            "theme": theme,
            "scene": scene or "",
            "scene_label": sc_label,
            "extra": extra,
            "duration": duration,
            "main_duration": main_duration,
            "climax": bool(use_climax),
            "climax_seconds": climax_secs if climax_motion else 0,
            "seed": seed,
            "image_backend": backend,
            "diffusers_model": model_key,
            "diffusers_model_label": model_label,
            "video_model": vkey,
            "video_model_label": vlabel,
            "turbo_steps": self._turbo_steps(vkey, turbo_steps),
            "nsfw": bool(nsfw),
            "still_prompt": still,
            "motion_prompt": motion,
            "climax_motion": climax_motion,
            "voice": use_voice,
            "language": lang,
            "voice_style": vstyle,
            "dialogue": spoken,
            "width": self.cfg["image"]["width"],
            "height": self.cfg["image"]["height"],
            "first_frame": "first_frame.png",
            "last_frame": last_frame_name,
            "animation": None if image_only else "animation.mp4",
            "kind": "still" if image_only else "clip",
        }
        if extra_meta:
            meta.update(extra_meta)
        (dest / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"  完成 → {dest}")
        return meta

    def generate_auto(
        self,
        count: int,
        *,
        theme: str | None = None,
        scene: str | None = None,
        character: str | None = None,
        action: str | None = None,
        extra: str = "",
        duration: int | None = None,
        seed: int | None = None,
        nsfw: bool = True,
        quality: bool = True,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        video_model: str | None = None,
        voice: bool | None = None,
        language: str | None = None,
        ollama_model: str | None = None,
        english_motion: bool | None = None,
        climax: bool | None = None,
        voice_style: str | None = None,
        turbo_steps: int | None = None,
    ) -> list[dict]:
        count = max(1, min(10, int(count)))
        vkey, _, vinfo = self._video_info(video_model)
        vmax = int(vinfo["duration_max"])
        default = int(self.cfg["video"]["duration_default"])
        clip_duration = default if duration is None else int(duration)
        clip_duration = max(6, min(vmax, clip_duration))
        if theme:
            theme_of(theme)
        if scene:
            scene_of(scene)
        results = []
        try:
            for i in range(count):
                self.log(f"======== 自動生成 {i + 1}/{count} ========")
                self._set_progress(
                    stage="frame",
                    progress=int(i / count * 100),
                    message=f"自動生成 {i + 1}/{count}",
                )
                clip_seed = None if seed is None else seed + i
                rng = random.Random(clip_seed)
                item_theme = theme or random_theme_key(rng)
                results.append(self.generate_one(
                    character=character,
                    action=action,
                    theme=item_theme,
                    scene=scene,
                    extra=extra,
                    duration=clip_duration,
                    seed=clip_seed,
                    random_character=not character,
                    random_action=not action,
                    nsfw=nsfw,
                    quality=quality,
                    image_backend=image_backend,
                    diffusers_model=diffusers_model,
                    video_model=vkey,
                    voice=voice,
                    language=language,
                    ollama_model=ollama_model,
                    english_motion=english_motion,
                    climax=climax,
                    voice_style=voice_style,
                    turbo_steps=turbo_steps,
                ))
        finally:
            if free_pipe():
                self.log("  自動生成結束，已卸載 Diffusers")
            self._free_comfy()
        return results

    def generate_bulk_images(
        self,
        count: int,
        *,
        theme: str | None = None,
        scene: str | None = None,
        character: str | None = None,
        action: str | None = None,
        extra: str = "",
        seed: int | None = None,
        nsfw: bool = True,
        quality: bool = True,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        ollama_model: str | None = None,
        english_motion: bool | None = None,
    ) -> list[dict]:
        count = max(10, min(100, int(count)))
        if theme:
            theme_of(theme)
        if scene:
            scene_of(scene)
        results = []
        try:
            self._free_comfy()
            for i in range(count):
                self.log(f"======== 大量生圖 {i + 1}/{count} ========")
                self._set_progress(
                    stage="frame",
                    progress=int(i / count * 100),
                    message=f"大量生圖 {i + 1}/{count}",
                )
                clip_seed = None if seed is None else seed + i
                rng = random.Random(clip_seed)
                item_theme = theme or random_theme_key(rng)
                results.append(self.generate_one(
                    character=character,
                    action=action,
                    theme=item_theme,
                    scene=scene,
                    extra=extra,
                    seed=clip_seed,
                    random_character=not character,
                    random_action=not action,
                    nsfw=nsfw,
                    quality=quality,
                    image_backend=image_backend,
                    diffusers_model=diffusers_model,
                    ollama_model=ollama_model,
                    image_only=True,
                    keep_pipe=True,
                    english_motion=english_motion,
                ))
        finally:
            if free_pipe():
                self.log("  批次結束，已卸載 Diffusers")
        return results

    def generate_sequence_stills(
        self,
        *,
        character: str,
        theme: str,
        scene: str | None = None,
        male: str = "",
        extra: str = "",
        set_count: int = 1,
        seed: int | None = None,
        nsfw: bool = True,
        quality: bool = True,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        ollama_model: str | None = None,
        english_motion: bool | None = None,
        voice_style: str | None = None,
    ) -> dict:
        character = (character or "").strip()
        theme = (theme or "").strip()
        if not character:
            raise ValueError("動作串必須指定角色")
        if not theme:
            raise ValueError("動作串必須指定主題")
        theme_of(theme)
        scene = (scene or "").strip() or None
        if scene:
            scene_of(scene)
        rng = random.Random(seed)
        plans = build_sequence_plans(
            self.catalog.action_names(), rng, set_count=set_count)
        male = (male or "").strip()
        extra_bits = [p for p in (male, extra) if p]
        if male and "1boy" not in male.lower():
            extra_bits.insert(0, "1boy")
        joined_extra = ", ".join(extra_bits)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pack = f"seq_{ts}_{slug(character, 16)}_{slug(theme, 12)}"
        dest = output_dir(self.cfg) / pack
        n = 2
        while dest.exists():
            dest = output_dir(self.cfg) / f"{pack}_{n}"
            n += 1
        pack = dest.name
        dest.mkdir(parents=True, exist_ok=True)
        total = sum(len(p) for p in plans)
        done = 0
        sets = []
        try:
            self._free_comfy()
            for si, actions in enumerate(plans, 1):
                self.log(f"======== 動作串 {pack} 套{si} ========")
                clips = []
                nude_on = False
                for ai, action in enumerate(actions, 1):
                    done += 1
                    act_tags = (
                        self.catalog.action_prompt(action)
                        if action in self.catalog.actions else action
                    )
                    if not nude_on and (looks_nude(act_tags) or looks_nude(joined_extra)):
                        nude_on = True
                        self.log(f"  此步起衣著改為 nude，後續跟著（{action}）")
                    self._set_progress(
                        stage="frame",
                        progress=int(done / total * 100),
                        message=f"動作串套{si} {ai}/{len(actions)}　{action}"
                        + ("　nude" if nude_on else ""),
                    )
                    clip_seed = None if seed is None else seed + done
                    meta = self.generate_one(
                        character=character,
                        action=action,
                        theme=theme,
                        scene=scene,
                        extra=joined_extra,
                        seed=clip_seed,
                        nsfw=nsfw,
                        quality=quality,
                        image_backend=image_backend,
                        diffusers_model=diffusers_model,
                        ollama_model=ollama_model,
                        image_only=True,
                        keep_pipe=True,
                        english_motion=english_motion,
                        voice_style=voice_style,
                        nude=nude_on,
                        theme_first=True,
                        extra_meta={
                            "sequence": pack,
                            "sequence_set": si,
                            "sequence_step": ai,
                            "sequence_nude": nude_on,
                        },
                    )
                    if looks_nude(meta.get("still_prompt") or "") or looks_nude(
                            meta.get("action_tags") or ""):
                        nude_on = True
                    clips.append({
                        "folder": meta["folder"],
                        "action": action,
                        "step": ai,
                    })
                sets.append({"index": si, "actions": actions, "clips": clips})
                blob = {
                    "id": pack,
                    "character": character,
                    "theme": theme,
                    "male": male,
                    "extra": extra,
                    "sets": sets,
                }
                (dest / "sequence.json").write_text(
                    json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if free_pipe():
                self.log("  動作串首幀結束，已卸載 Diffusers")
        self.log(f"  動作串完成 → {dest}")
        return {
            "id": pack,
            "character": character,
            "theme": theme,
            "male": male,
            "extra": extra,
            "sets": sets,
        }

    def clone_sequence_stills(
        self,
        pack_id: str,
        *,
        character: str,
        voice_style: str | None = None,
        seed: int | None = None,
        nsfw: bool = True,
        quality: bool = True,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        ollama_model: str | None = None,
        english_motion: bool | None = None,
    ) -> dict:
        """沿用原套動作／主題／首幀提示詞，只換角色與聲線。"""
        character = (character or "").strip()
        if not character:
            raise ValueError("複製動作串必須指定新角色")
        src, _src_dir = self._load_sequence(pack_id)
        src_sets = src.get("sets") or []
        if not src_sets:
            raise ValueError("來源動作串沒有步驟")
        theme = (src.get("theme") or "").strip()
        if theme:
            theme_of(theme)
        male = (src.get("male") or "").strip()
        extra = src.get("extra") or ""
        _, new_prompt, new_label = self._resolve_character(
            character, False, False, theme, extra, seed, random.Random(seed))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pack = f"seq_{ts}_{slug(character, 16)}_{slug(theme or 'copy', 12)}"
        dest = output_dir(self.cfg) / pack
        n = 2
        while dest.exists():
            dest = output_dir(self.cfg) / f"{pack}_{n}"
            n += 1
        pack = dest.name
        dest.mkdir(parents=True, exist_ok=True)
        steps = []
        for s in src_sets:
            for c in s.get("clips") or []:
                folder = c.get("folder") or ""
                meta_path = output_dir(self.cfg) / folder / "meta.json"
                if not meta_path.exists():
                    continue
                info = json.loads(meta_path.read_text(encoding="utf-8"))
                steps.append((s.get("index") or 1, c, info))
        if not steps:
            shutil.rmtree(dest, ignore_errors=True)
            raise FileNotFoundError("來源步驟的 meta.json 都不在了")
        total = len(steps)
        sets_map: dict[int, dict] = {}
        try:
            self._free_comfy()
            for i, (si, src_clip, info) in enumerate(steps, 1):
                action = src_clip.get("action") or info.get("action") or ""
                old_prompt = (info.get("character_prompt") or "").strip()
                still = self._retarget_still(
                    info.get("still_prompt") or "", old_prompt, new_prompt)
                nude_on = bool(info.get("sequence_nude")) or looks_nude(still)
                self._set_progress(
                    stage="frame",
                    progress=int((i - 1) / total * 100),
                    message=f"複製動作串 {i}/{total}　{action}",
                )
                self.log(f"  複製步驟 {i}/{total}: {action} → {new_label}")
                clip_seed = None if seed is None else seed + i
                meta = self.generate_one(
                    character=character,
                    action=action,
                    theme=info.get("theme") or theme or None,
                    scene=info.get("scene") or None,
                    extra=info.get("extra") or extra,
                    seed=clip_seed,
                    nsfw=nsfw,
                    quality=quality,
                    image_backend=image_backend or info.get("image_backend"),
                    diffusers_model=diffusers_model or info.get("diffusers_model"),
                    ollama_model=ollama_model,
                    still_prompt=still or None,
                    image_only=True,
                    keep_pipe=True,
                    english_motion=english_motion,
                    voice_style=voice_style,
                    nude=nude_on,
                    theme_first=True,
                    extra_meta={
                        "sequence": pack,
                        "sequence_set": si,
                        "sequence_step": src_clip.get("step") or i,
                        "sequence_nude": nude_on,
                        "copied_from": pack_id,
                        "copied_clip": src_clip.get("folder") or "",
                    },
                )
                bucket = sets_map.setdefault(int(si), {
                    "index": int(si), "actions": [], "clips": [],
                })
                bucket["actions"].append(action)
                bucket["clips"].append({
                    "folder": meta["folder"],
                    "action": action,
                    "step": len(bucket["clips"]) + 1,
                })
                blob = {
                    "id": pack,
                    "character": character,
                    "theme": theme,
                    "male": male,
                    "extra": extra,
                    "copied_from": pack_id,
                    "voice_style": voice_style or "",
                    "sets": [sets_map[k] for k in sorted(sets_map)],
                }
                (dest / "sequence.json").write_text(
                    json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if free_pipe():
                self.log("  複製動作串結束，已卸載 Diffusers")
        self.log(f"  複製完成 → {dest}")
        return json.loads((dest / "sequence.json").read_text(encoding="utf-8"))

    @staticmethod
    def _retarget_still(still: str, old_prompt: str, new_prompt: str) -> str:
        still = (still or "").strip()
        old_prompt = (old_prompt or "").strip()
        new_prompt = (new_prompt or "").strip()
        if not still:
            return new_prompt
        if old_prompt and still.startswith(old_prompt):
            return (new_prompt + still[len(old_prompt):]).strip(", ")
        if old_prompt and old_prompt in still:
            return still.replace(old_prompt, new_prompt, 1)
        if new_prompt and not still.lower().startswith(new_prompt.lower()):
            return f"{new_prompt}, {still}"
        return still

    def animate_sequence_set(
        self,
        pack_id: str,
        set_index: int,
        *,
        duration: int | None = None,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        video_model: str | None = None,
        voice: bool | None = None,
        language: str | None = None,
        english_motion: bool | None = None,
        ollama_model: str | None = None,
        voice_style: str | None = None,
        turbo_steps: int | None = None,
    ) -> dict:
        blob, pack_dir = self._load_sequence(pack_id)
        target = None
        for s in blob.get("sets") or []:
            if int(s.get("index") or 0) == int(set_index):
                target = s
                break
        if not target:
            raise ValueError(f"沒有套 {set_index}")
        clips = target.get("clips") or []
        n = len(clips)
        if not n:
            raise ValueError("這套沒有首幀")
        out = []
        try:
            for i, item in enumerate(clips, 1):
                folder = item.get("folder") or ""
                video = output_dir(self.cfg) / folder / "animation.mp4"
                self._set_progress(
                    stage="video",
                    progress=int((i - 1) / n * 100),
                    message=f"套{set_index} 動畫 {i}/{n}　{item.get('action') or folder}",
                )
                if video.exists() and video.stat().st_size > 0:
                    self.log(f"  已有動畫，跳過 {folder}")
                    out.append(folder)
                    continue
                use_en = self._english_motion_on(english_motion)
                self.regenerate(
                    folder,
                    redo="video",
                    duration=duration,
                    image_backend=image_backend,
                    diffusers_model=diffusers_model,
                    video_model=video_model,
                    voice=voice,
                    language=language,
                    english_motion=use_en,
                    motion_prompt="" if use_en else None,
                    ollama_model=ollama_model,
                    climax=False,
                    voice_style=voice_style,
                    turbo_steps=turbo_steps,
                )
                out.append(folder)
        finally:
            self._free_comfy()
        return {"id": pack_id, "set": set_index, "folders": out}

    def concat_sequence_set(self, pack_id: str, set_index: int) -> dict:
        blob, pack_dir = self._load_sequence(pack_id)
        target = None
        for s in blob.get("sets") or []:
            if int(s.get("index") or 0) == int(set_index):
                target = s
                break
        if not target:
            raise ValueError(f"沒有套 {set_index}")
        videos = []
        missing = []
        for item in target.get("clips") or []:
            folder = item.get("folder") or ""
            p = output_dir(self.cfg) / folder / "animation.mp4"
            if p.exists() and p.stat().st_size > 0:
                videos.append(p)
            else:
                missing.append(item.get("action") or folder)
        if missing:
            raise ValueError("還有未產動畫的步驟：" + "、".join(missing[:8]))
        if len(videos) < 2:
            raise ValueError("至少要兩支動畫才能合併")
        out = pack_dir / f"set{int(set_index)}_full.mp4"
        self._set_progress(stage="video", progress=None, message=f"合併套{set_index}…")
        if not self._concat_many(videos, out):
            raise RuntimeError("ffmpeg 合併失敗")
        target["joined"] = out.name
        (pack_dir / "sequence.json").write_text(
            json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"  已合併 → {out}")
        return {"id": pack_id, "set": set_index, "joined": out.name}

    def remove_sequence_clip(self, pack_id: str, folder: str) -> dict:
        blob, pack_dir = self._load_sequence(pack_id)
        folder = (folder or "").strip()
        if not folder:
            raise ValueError("沒有指定要刪的段落")
        found = False
        set_index = None
        for s in blob.get("sets") or []:
            clips = list(s.get("clips") or [])
            keep = [c for c in clips if (c.get("folder") or "") != folder]
            if len(keep) == len(clips):
                continue
            found = True
            set_index = s.get("index")
            for i, c in enumerate(keep, 1):
                c["step"] = i
            s["clips"] = keep
            s["actions"] = [c.get("action") for c in keep if c.get("action")]
            s.pop("joined", None)
            joined = pack_dir / f"set{int(set_index or 0)}_full.mp4"
            joined.unlink(missing_ok=True)
            break
        if not found:
            raise FileNotFoundError(f"動作串裡沒有這一段: {folder}")
        blob["sets"] = [s for s in (blob.get("sets") or []) if s.get("clips")]
        clip_dir = output_dir(self.cfg) / folder
        if clip_dir.is_dir() and str(clip_dir.resolve()).startswith(
                str(output_dir(self.cfg).resolve())):
            shutil.rmtree(clip_dir)
        if not blob["sets"]:
            shutil.rmtree(pack_dir)
            return {"id": pack_id, "deleted": folder, "pack_deleted": True}
        (pack_dir / "sequence.json").write_text(
            json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"id": pack_id, "deleted": folder, "set": set_index, "pack_deleted": False}

    def _load_sequence(self, pack_id: str) -> tuple[dict, Path]:
        return self._load_pack(pack_id, "sequence.json", "動作串")

    def _cast_voice(self, character: str, override: str | None = None) -> str:
        if (override or "").strip():
            return resolve_voice_style(self.cfg, override)
        found = self.catalog.get_character(character)
        if found and found.get("voice"):
            return resolve_voice_style(self.cfg, found["voice"])
        return resolve_voice_style(self.cfg, None)

    def _resolve_cast_slots(
        self, raw, *, fallback: str = "", gender: str = "female",
    ) -> list[dict]:
        slots: list[dict] = []
        items = list(raw or [])
        if not items and (fallback or "").strip():
            items = [{"character": fallback}]
        root = self.cfg.get("_root")
        seen: set[str] = set()
        for item in items:
            if isinstance(item, str):
                item = {"character": item}
            title = str((item or {}).get("character") or (item or {}).get("title") or "").strip()
            if not title:
                continue
            found = self.catalog.get_character(title)
            key = (found["title"] if found else title).lower()
            if key in seen:
                continue
            seen.add(key)
            ref = str((item or {}).get("voice_ref") or "").strip()
            style = voice_ref_style(ref, root) if ref else ""
            if not style and found:
                style = found.get("voice") or ""
            custom_prompt = str((item or {}).get("prompt") or "").strip()
            raw_theme = (item or {}).get("theme", None)
            if raw_theme is None:
                theme_key = None
            else:
                theme_key = str(raw_theme).strip()
                if theme_key.lower() == "original":
                    theme_key = ""
            slots.append({
                "title": found["title"] if found else title,
                "prompt": (
                    self.catalog.character_prompt(found["title"]) if found
                    else (custom_prompt or title)
                ),
                "label": self.catalog.display_name(found["title"]) if found else title,
                "voice_ref": ref,
                "voice_style": style,
                "gender": gender,
                "theme": theme_key,
                "image": str((item or {}).get("image") or "").strip(),
            })
            if len(slots) >= 50:
                break
        return slots

    def generate_story_stills(
        self,
        *,
        story_id: str,
        character: str,
        theme: str = "",
        male_theme: str = "",
        male: str = "",
        extra: str = "",
        seed: int | None = None,
        nsfw: bool = True,
        quality: bool = True,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        ollama_model: str | None = None,
        english_motion: bool | None = None,
        voice_style: str | None = None,
        language: str | None = None,
        story_mode: str = "r2v",
        females: list | None = None,
        males: list | None = None,
    ) -> dict:
        character = (character or "").strip()
        fem_slots = self._resolve_cast_slots(females, fallback=character, gender="female")
        mal_slots = self._resolve_cast_slots(males, fallback=male, gender="male")
        if not fem_slots:
            raise ValueError("短劇至少選一名女角色（最多 3 名）")
        character = fem_slots[0]["title"]
        mode = (story_mode or "r2v").strip().lower()
        if mode in {"i2v", "i2va", "story2"}:
            return self._generate_story_i2v_stills(
                story_id=story_id, character=character, theme=theme,
                male_theme=male_theme,
                male=(mal_slots[0]["title"] if mal_slots else male),
                extra=extra, seed=seed, nsfw=nsfw, quality=quality,
                image_backend=image_backend, diffusers_model=diffusers_model,
                ollama_model=ollama_model, english_motion=english_motion,
                voice_style=voice_style, language=language)
        story = get_story(story_id, self.cfg.get("_root"))
        theme = (theme or "").strip()
        if theme:
            theme_of(theme)
        male_theme = (male_theme or "").strip()
        if male_theme.lower() == "original":
            male_theme = ""
        if male_theme:
            male_theme_of(male_theme)
        rng = random.Random(seed)
        names = self.catalog.action_names()
        if mal_slots:
            male = mal_slots[0]["prompt"]
            male_voice = mal_slots[0].get("voice_style") or ""
            self.log(f"  男角色: {mal_slots[0]['label']}"
                     f"　聲線 {male_voice or mal_slots[0].get('voice_ref') or '（自動）'}")
            for i, slot in enumerate(mal_slots[1:], 2):
                self.log(f"  男角{i}: {slot['label']}")
        else:
            male = ""
            male_voice = ""
        for i, slot in enumerate(fem_slots, 1):
            self.log(f"  女角{i}: {slot['label']}"
                     + (f"　聲線參考 {slot['voice_ref']}" if slot.get("voice_ref") else ""))
        extra = extra or ""
        lang = voice_language(self.cfg, language)
        lead_ref_style = fem_slots[0].get("voice_style") or None
        vstyle = self._cast_voice(character, voice_style or lead_ref_style)
        male_voice = male_voice or ""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pack = f"story_{ts}_{slug(character, 16)}_{slug(story['id'], 12)}"
        dest = output_dir(self.cfg) / pack
        n = 2
        while dest.exists():
            dest = output_dir(self.cfg) / f"{pack}_{n}"
            n += 1
        pack = dest.name
        dest.mkdir(parents=True, exist_ok=True)
        beats = story["fragments"]
        total = len(beats)
        clips = []
        nude_on = False
        prev_beat = None
        prev_char = None
        prev_partner = None
        prev_scene = None
        prev_clothing = None
        prev_male_clothing = None
        prev_partner_slot = None
        prev_scene_key = None
        prev_char_title = None
        prev_extra_key = None
        prev_male_extra_key = None
        char_title, char_prompt, char_label = self._resolve_character(
            character, False, False, theme, extra, seed, rng)
        backend = self.resolve_image_backend(image_backend)
        model_key, model_label, _ = self._model_info(diffusers_model)
        try:
            self._free_comfy()
            self.log(f"======== 短篇 {story['title']} {pack} ========")
            self.log("  R2V：女角色圖＋（雙人則男角色圖）＋場景圖；衣著／場景沒變就沿用")
            self.log("  鏡頭稿：每段同時寫 R2V 與 I2V")
            self.log(f"  首幀後端: {backend}　模型: {model_label}")
            self.log(f"  語音: {lang}　女聲線 {vstyle}"
                     + (f"　男聲線 {male_voice}" if male_voice else ""))
            for ai, beat in enumerate(beats, 1):
                action = resolve_beat_action(beat, names, rng)
                cast = beat_cast(beat, fem_slots, mal_slots)
                use_fems = cast["females"] or fem_slots[:1]
                partner_i = cast["partner_i"]
                has_partner = cast["has_partner"]
                explicit_partner = cast["explicit_partner"]
                beat_male = cast["beat_male"]
                male_sheets = cast["male_sheets"]
                b_slot = use_fems[0]
                if beat.get("with_females"):
                    b_title = b_slot.get("title") or char_title
                    b_prompt = b_slot.get("prompt") or char_prompt
                    b_label = b_slot.get("label") or char_label
                    b_voice = self._cast_voice(
                        b_title, voice_style or b_slot.get("voice_style") or None)
                    b_ref = b_slot.get("voice_ref") or ""
                else:
                    b_title, b_prompt, b_label = char_title, char_prompt, char_label
                    b_voice = vstyle
                    b_ref = fem_slots[0].get("voice_ref") or "" if fem_slots else ""
                b_male_voice = male_voice
                if isinstance(beat.get("with_males"), list) and cast["males"]:
                    b_male_voice = cast["males"][0].get("voice_style") or male_voice
                joined_extra = self._story_beat_extra(beat_male, extra, beat)
                beat_nsfw = beat_is_nsfw(beat)
                link = resolve_beat_link(prev_beat, beat)
                if beat.get("nude"):
                    nude_on = True
                if not nude_on and (looks_nude(action) or looks_nude(joined_extra)):
                    nude_on = True
                    self.log(f"  此步起衣著改為 nude（{beat['title']}）")
                dur = int(beat["duration"])
                vkey, vlabel, _ = self._video_info(story_video_key(self.cfg, beat_nsfw))
                story_clothing = (
                    (beat.get("clothing") or story.get("clothing") or "").strip()
                )
                if "theme" in beat:
                    beat_theme = str(beat.get("theme") or "").strip()
                    if beat_theme.lower() == "original":
                        beat_theme = ""
                else:
                    beat_theme = theme
                if "male_theme" in beat:
                    beat_male_theme = str(beat.get("male_theme") or "").strip()
                    if beat_male_theme.lower() == "original":
                        beat_male_theme = ""
                else:
                    beat_male_theme = male_theme
                clothing_key = beat_clothing_key(nude_on, beat_theme, story_clothing)
                male_clothing_key = beat_male_clothing_key(nude_on, beat_male_theme)
                scene_key = beat_scene_key(beat)
                clothing_changed = prev_clothing is not None and clothing_key != prev_clothing
                scene_changed = prev_scene_key is not None and scene_key != prev_scene_key
                clip_name = beat_motion_clip(beat, story_id=story["id"], title=beat["title"])
                prev_plot = beat_plot_text(prev_beat) if prev_beat else ""
                if partner_i:
                    self.log(f"  本段出鏡：男{partner_i}")
                if beat.get("with_females"):
                    self.log(f"  本段女角：{b_label}")
                plot_motion = compose_story_r2v(
                    beat, character=b_label, duration=dur, nsfw=beat_nsfw,
                    link=link,
                    prev_plot=prev_plot,
                    nude=nude_on, male=beat_male, has_partner=has_partner,
                    clothing_changed=clothing_changed,
                    scene_changed=scene_changed,
                    has_pose_ref=False,
                    has_motion_clip=bool(clip_name),
                    language=lang, voice_style=b_voice)
                i2v_motion = compose_story_i2v(
                    beat, duration=dur, nsfw=beat_nsfw, prev_plot=prev_plot,
                    language=lang, voice_style=b_voice,
                    continue_shot=prev_beat is not None)
                extra_has_partner = (
                    has_partner if isinstance(beat.get("with_males"), list)
                    else has_partner and not explicit_partner
                )
                extras = self._extra_cast_meta(
                    use_fems,
                    male_sheets,
                    extra_has_partner,
                )
                plot_motion = attach_extra_cast(plot_motion, extras)
                if clip_name:
                    plot_motion = attach_motion_clip(plot_motion, nsfw=beat_nsfw)
                    self.log(f"  動作參考 {clip_name}（只借動作）")
                mark = "NSFW" if beat_nsfw else "非NSFW"
                self._set_progress(
                    stage="frame",
                    progress=int(ai / total * 100),
                    message=f"短篇 {ai}/{total}　{beat['title']}　{dur}s　{mark}"
                    + ("　nude" if nude_on else ""),
                )
                self.log(
                    f"  {beat['title']}: {mark}　女衣著 {clothing_key}　男衣著 {male_clothing_key}　場景 {scene_key}　"
                    f"{vlabel}　{dur}s")
                clip_seed = None if seed is None else seed + ai
                char_src = self._existing_image(b_slot.get("image"))
                partner_card = None
                if has_partner and cast["males"]:
                    partner_card = self._existing_image(cast["males"][0].get("image"))
                scene_card = self._existing_image(beat.get("scene_image"))
                meta = self._story_write_r2v_clip(
                    character_title=b_title,
                    character_prompt=b_prompt,
                    character_label=b_label,
                    action=action,
                    beat=beat,
                    theme=beat_theme,
                    extra=joined_extra,
                    duration=dur,
                    seed=clip_seed,
                    nsfw=beat_nsfw,
                    quality=quality,
                    image_backend=backend,
                    diffusers_model=model_key,
                    video_model=vkey,
                    scene_src=scene_card,
                    clothing_key=clothing_key,
                    scene_key=scene_key,
                    prev_char=prev_char,
                    prev_char_title=prev_char_title,
                    prev_partner=prev_partner,
                    prev_scene=prev_scene,
                    prev_clothing=prev_clothing,
                    prev_scene_key=prev_scene_key,
                    nude_on=nude_on,
                    male=beat_male,
                    male_theme=beat_male_theme,
                    male_clothing_key=male_clothing_key,
                    prev_male_clothing=prev_male_clothing,
                    has_partner=has_partner,
                    partner_slot=partner_i if explicit_partner else None,
                    prev_partner_slot=prev_partner_slot,
                    motion_prompt=plot_motion,
                    language=lang,
                    voice_style=b_voice,
                    char_src=char_src,
                    partner_card=partner_card,
                    extra_meta={
                        "story": pack,
                        "story_id": story["id"],
                        "story_title": story["title"],
                        "story_set": 1,
                        "story_step": ai,
                        "story_beat": beat["title"],
                        "story_nude": nude_on,
                        "story_nsfw": beat_nsfw,
                        "story_link": link,
                        "story_mode": "r2v",
                        "story_clothing": story_clothing,
                        "motion_clip": clip_name,
                        "i2v_prompt": i2v_motion,
                        "voice_style": b_voice,
                        "voice_ref": b_ref,
                        "male_voice_style": b_male_voice,
                        "clip_mode": self._normalize_clip_mode(str(beat.get("clip_mode") or "r2v")),
                        "language": lang,
                        "story_plot": {
                            "title": beat.get("title") or "",
                            "tags": beat.get("tags") or "",
                            "action": beat.get("action") or "",
                            "extra": beat.get("extra") or "",
                            "plot": beat.get("plot") or beat_plot_text(beat),
                            "nude": bool(beat.get("nude")),
                            "solo": bool(beat.get("solo")),
                            "partner": partner_i,
                            "link": link,
                            "scene": scene_key,
                            "motion_clip": clip_name,
                            "shots": beat.get("shots") or [],
                            "dialogue": beat.get("dialogue") or beat_dialogue(beat),
                        },
                    },
                )
                clips.append({
                    "folder": meta["folder"],
                    "action": beat["title"],
                    "catalog_action": action,
                    "step": ai,
                    "duration": dur,
                    "title": beat["title"],
                    "nsfw": beat_nsfw,
                    "video_model": vkey,
                    "link": link,
                    "motion_clip": clip_name,
                })
                clip_dir = output_dir(self.cfg) / meta["folder"]
                extra_key = tuple(s.get("title") for s in use_fems[1:])
                male_extra_key = tuple(s.get("title") for s in male_sheets[1:])
                self._write_extra_cast_sheets(
                    clip_dir,
                    fem_slots=use_fems,
                    mal_slots=male_sheets,
                    theme=beat_theme,
                    male_theme=beat_male_theme,
                    nude_on=nude_on,
                    nsfw=beat_nsfw,
                    quality=quality,
                    image_backend=backend,
                    diffusers_model=model_key,
                    seed=clip_seed,
                    reuse_char=bool(prev_char) and prev_clothing == clothing_key and prev_extra_key == extra_key,
                    reuse_male=bool(prev_partner) and prev_male_clothing == male_clothing_key and prev_male_extra_key == male_extra_key,
                    prev_dir=prev_char.parent if prev_char else None,
                )
                prev_beat = beat
                prev_clothing = clothing_key
                prev_male_clothing = male_clothing_key
                prev_partner_slot = partner_i if explicit_partner else None
                prev_scene_key = scene_key
                prev_char_title = b_title
                prev_extra_key = extra_key
                prev_male_extra_key = male_extra_key
                clip_dir = output_dir(self.cfg) / meta["folder"]
                if (clip_dir / "character.png").exists():
                    prev_char = clip_dir / "character.png"
                if (clip_dir / "partner.png").exists():
                    prev_partner = clip_dir / "partner.png"
                if (clip_dir / "scene.png").exists():
                    prev_scene = clip_dir / "scene.png"
                blob = {
                    "id": pack,
                    "kind": "story",
                    "story_id": story["id"],
                    "story_title": story["title"],
                    "character": character,
                    "theme": theme,
                    "male_theme": male_theme,
                    "male": male,
                    "females": fem_slots,
                    "males": mal_slots,
                    "extra": extra,
                    "language": lang,
                    "voice_style": vstyle,
                    "male_voice_style": male_voice,
                    "story_mode": "r2v",
                    "sets": [{
                        "index": 1,
                        "actions": [c["action"] for c in clips],
                        "clips": clips,
                    }],
                }
                (dest / "story.json").write_text(
                    json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if free_pipe():
                self.log("  短篇參考圖結束，已卸載 Diffusers")
        self.log(f"  短篇完成 → {dest}")
        return json.loads((dest / "story.json").read_text(encoding="utf-8"))

    def render_editor_segment(
        self,
        draft: dict,
        segment_id: str,
        *,
        diffusers_model: str | None = None,
        ollama_model: str | None = None,
        language: str | None = None,
        turbo_steps: int | None = None,
    ) -> dict:
        """編輯模式：只產這一段。鏡頭稿用目前的劇情、對白、角色卡、場地卡。"""
        root = self.cfg.get("_root")
        if ollama_model:
            self.cfg = apply_ollama_model(self.cfg, ollama_model)
        story = draft_to_story(draft, root, segment_id=segment_id)
        beat = (story.get("fragments") or [None])[0]
        if not isinstance(beat, dict):
            raise ValueError("找不到這個段落")
        fem_raw, mal_raw = draft_cast_slots(draft, root)
        fem_slots = self._resolve_cast_slots(fem_raw, gender="female")
        mal_slots = self._resolve_cast_slots(mal_raw, gender="male")
        if not fem_slots:
            raise ValueError("請至少一張女角色卡")
        segs = [s for s in (draft.get("segments") or []) if isinstance(s, dict)]
        idx = next(
            (i for i, s in enumerate(segs) if str(s.get("id") or "") == segment_id),
            -1,
        )
        if idx < 0:
            raise ValueError("找不到這個段落")
        seg = segs[idx]
        names = self.catalog.action_names()
        rng = random.Random()
        action = resolve_beat_action(beat, names, rng)
        cast = beat_cast(beat, fem_slots, mal_slots)
        use_fems = cast["females"] or fem_slots[:1]
        partner_i = cast["partner_i"]
        has_partner = cast["has_partner"]
        explicit_partner = cast["explicit_partner"]
        beat_male = cast["beat_male"]
        male_sheets = cast["male_sheets"]
        b_slot = use_fems[0]
        b_title = b_slot.get("title") or fem_slots[0]["title"]
        b_prompt = b_slot.get("prompt") or ""
        b_label = b_slot.get("label") or b_title
        b_voice = b_slot.get("voice_style") or ""
        b_ref = b_slot.get("voice_ref") or ""
        b_male_voice = ""
        if isinstance(beat.get("with_males"), list) and cast["males"]:
            b_male_voice = cast["males"][0].get("voice_style") or ""
        lang = voice_language(self.cfg, language)
        beat_nsfw = beat_is_nsfw(beat)
        joined_extra = self._story_beat_extra(beat_male, "", beat)
        nude_on = bool(beat.get("nude")) or looks_nude(action) or looks_nude(joined_extra)
        dur = int(beat["duration"])
        beat_theme = str(beat.get("theme") or "").strip()
        if beat_theme.lower() == "original":
            beat_theme = ""
        beat_male_theme = str(beat.get("male_theme") or "").strip() if "male_theme" in beat else ""
        if beat_male_theme.lower() == "original":
            beat_male_theme = ""
        clothing_key = beat_clothing_key(nude_on, beat_theme, "")
        male_clothing_key = beat_male_clothing_key(nude_on, beat_male_theme)
        scene_key = beat_scene_key(beat)
        clip_name = beat_motion_clip(beat, story_id=story["id"], title=beat["title"])
        motion_mode = "audio" if str(beat.get("motion_mode") or "") == "audio" else "motion"
        if clip_name and motion_mode == "audio":
            ref = resolve_motion_clip(clip_name, self.cfg.get("_root") or "")
            secs = probe_duration(ref) if ref else None
            if secs:
                _, _, vinfo = self._video_info(story_video_key(self.cfg, beat_nsfw))
                vmin = int(vinfo.get("duration_min") or 3)
                vmax = int(vinfo.get("duration_max") or 15)
                matched = max(vmin, min(vmax, int(round(secs))))
                self.log(
                    f"  參考片 {secs:.2f}s，生成長度 {matched}s"
                    + ("" if abs(matched - secs) < 0.6 else "（模型只能整秒，且有上限）")
                )
                dur = matched
                beat["duration"] = matched
                for shot in beat.get("shots") or []:
                    if isinstance(shot, dict):
                        shot["end"] = matched
            else:
                self.log("  讀不到參考片長度，仍用段落秒數")
        prev_plot = ""
        prev_folder = ""
        if idx > 0:
            prev = segs[idx - 1]
            prev_plot = str(prev.get("plot") or "").strip()
            prev_folder = str(prev.get("folder") or "").strip()
        clip_mode = self._normalize_clip_mode(str(beat.get("clip_mode") or "r2v"))
        prev_last = self._clip_last_frame(prev_folder) if prev_folder else None
        has_tail = bool(prev_last and prev_last.is_file())
        link = beat.get("link") or "cut"
        plot_motion = compose_story_r2v(
            beat, character=b_label, duration=dur, nsfw=beat_nsfw,
            link=link, prev_plot=prev_plot, nude=nude_on, male=beat_male,
            has_partner=has_partner, clothing_changed=False, scene_changed=False,
            has_pose_ref=False, has_motion_clip=bool(clip_name),
            language=lang, voice_style=b_voice or None)
        i2v_motion = compose_story_i2v(
            beat, duration=dur, nsfw=beat_nsfw, prev_plot=prev_plot,
            language=lang, voice_style=b_voice or None,
            continue_shot=has_tail and clip_mode in {"i2v", "i2v_clone"})
        extra_has_partner = (
            has_partner if isinstance(beat.get("with_males"), list)
            else has_partner and not explicit_partner
        )
        extras = self._extra_cast_meta(use_fems, male_sheets, extra_has_partner)
        plot_motion = attach_extra_cast(plot_motion, extras)
        if clip_name:
            plot_motion = attach_motion_clip(plot_motion, nsfw=beat_nsfw)
            self.log(f"  動作參考 {clip_name}（只借動作）")
        backend = self.resolve_image_backend("diffusers")
        model_key, model_label, _ = self._model_info(diffusers_model)
        vkey, vlabel, _ = self._video_info(story_video_key(self.cfg, beat_nsfw))
        draft_id = str(draft.get("id") or "")
        pack_id = "editpack_" + draft_id
        step = idx + 1
        folder = str(seg.get("folder") or "").strip()
        reuse = ""
        if folder and "/" not in folder and "\\" not in folder and ".." not in folder:
            if (output_dir(self.cfg) / folder / "meta.json").is_file():
                reuse = folder
        spoken = (beat.get("dialogue") or beat_dialogue(beat) or "").strip()
        self._free_comfy()
        self.log(f"======== 編輯段落 {beat['title']} ========")
        self.log(f"  劇情: {beat_plot_text(beat)[:120]}")
        self.log(f"  對白: {spoken or '（無）'}")
        self.log(f"  角色: {b_label}　衣著 {clothing_key}　聲線 {b_ref or b_voice or '（自動）'}")
        if has_partner:
            self.log(f"  出鏡男角: {beat_male or '（有）'}　衣著 {male_clothing_key}")
        self.log(f"  場地: {scene_key or '（未選）'}")
        self.log(f"  模型: {model_label}　{vlabel}　{dur}s　{clip_mode}")
        self._set_progress(
            stage="frame", progress=15,
            message=f"段落 {beat['title']}　參考圖",
        )
        meta = self._story_write_r2v_clip(
            character_title=b_title,
            character_prompt=b_prompt,
            character_label=b_label,
            action=action,
            beat=beat,
            theme=beat_theme,
            extra=joined_extra,
            duration=dur,
            seed=None,
            nsfw=beat_nsfw,
            quality=True,
            image_backend=backend,
            diffusers_model=model_key,
            video_model=vkey,
            scene_src=self._existing_image(beat.get("scene_image")),
            clothing_key=clothing_key,
            scene_key=scene_key,
            prev_char=None,
            prev_char_title=None,
            prev_partner=None,
            prev_scene=None,
            prev_clothing=None,
            prev_scene_key=None,
            nude_on=nude_on,
            male=beat_male,
            male_theme=beat_male_theme,
            male_clothing_key=male_clothing_key,
            prev_male_clothing=None,
            has_partner=has_partner,
            partner_slot=partner_i if explicit_partner else None,
            prev_partner_slot=None,
            motion_prompt=plot_motion,
            language=lang,
            voice_style=b_voice or None,
            char_src=self._existing_image(b_slot.get("image")),
            partner_card=self._existing_image(
                cast["males"][0].get("image") if has_partner and cast["males"] else ""
            ),
            folder_name=reuse,
            extra_meta={
                "story": pack_id,
                "story_id": story["id"],
                "story_title": story["title"],
                "story_set": 1,
                "story_step": step,
                "story_beat": beat["title"],
                "story_nude": nude_on,
                "story_nsfw": beat_nsfw,
                "story_link": "continue" if has_tail and clip_mode in {"i2v", "i2v_clone"} else link,
                "story_mode": "r2v",
                "story_clothing": "",
                "motion_clip": clip_name,
                "motion_mode": motion_mode if clip_name else "",
                "i2v_prompt": i2v_motion,
                "voice_style": b_voice,
                "voice_ref": b_ref,
                "male_voice_style": b_male_voice,
                "clip_mode": clip_mode,
                "language": lang,
                "dialogue": spoken,
                "editor": True,
                "story_plot": {
                    "title": beat.get("title") or "",
                    "tags": beat.get("tags") or "",
                    "action": beat.get("action") or "",
                    "extra": beat.get("extra") or "",
                    "plot": beat.get("plot") or beat_plot_text(beat),
                    "nude": bool(beat.get("nude")),
                    "solo": bool(beat.get("solo")),
                    "partner": partner_i,
                    "link": link,
                    "scene": scene_key,
                    "motion_clip": clip_name,
                    "shots": beat.get("shots") or [],
                    "dialogue": spoken,
                },
            },
        )
        folder = meta["folder"]
        clip_dir = output_dir(self.cfg) / folder
        if not has_partner:
            (clip_dir / "partner.png").unlink(missing_ok=True)
        self._write_extra_cast_sheets(
            clip_dir,
            fem_slots=use_fems,
            mal_slots=male_sheets,
            theme=beat_theme,
            male_theme=beat_male_theme,
            nude_on=nude_on,
            nsfw=beat_nsfw,
            quality=True,
            image_backend=backend,
            diffusers_model=model_key,
            seed=None,
            reuse_char=False,
            reuse_male=False,
            prev_dir=None,
        )
        if free_pipe():
            self.log("  參考圖結束，已卸載 Diffusers")
        (clip_dir / "animation.mp4").unlink(missing_ok=True)
        self._write_editor_pack(draft, story, pack_id, {segment_id: folder})
        self._set_progress(
            stage="video", progress=40,
            message=f"段落 {beat['title']}　產動畫",
        )
        self.regenerate(
            folder,
            redo="video",
            motion_prompt=plot_motion,
            i2v_prompt=i2v_motion,
            dialogue=spoken,
            duration=dur,
            image_backend=backend,
            diffusers_model=model_key,
            video_model=vkey,
            voice=True,
            language=lang,
            voice_style=b_voice or None,
            ollama_model=ollama_model,
            climax=False,
            story_link="auto",
            turbo_steps=turbo_steps,
            clip_mode=clip_mode,
            voice_ref=b_ref,
            motion_clip=clip_name,
        )
        self.log(f"  段落完成 → {folder}")
        return {
            "pack_id": pack_id,
            "folder": folder,
            "segment_id": segment_id,
            "title": beat.get("title") or "",
        }

    def _write_editor_pack(
        self, draft: dict, story: dict, pack_id: str, folders: dict,
    ) -> None:
        segs = [s for s in (draft.get("segments") or []) if isinstance(s, dict)]
        clips = []
        for i, seg in enumerate(segs):
            sid = str(seg.get("id") or "")
            folder = str(folders.get(sid) or seg.get("folder") or "").strip()
            if not folder:
                continue
            title = str(seg.get("name") or i + 1)
            clips.append({
                "folder": folder,
                "step": i + 1,
                "title": title,
                "action": title,
                "duration": int(seg.get("duration") or 8),
                "link": "cut" if i == 0 else "reference",
            })
        blob = {
            "id": pack_id,
            "kind": "story",
            "editor": True,
            "story_id": story.get("id") or "",
            "story_title": story.get("title") or "",
            "story_mode": "r2v",
            "sets": [{
                "index": 1,
                "actions": [c["action"] for c in clips],
                "clips": clips,
            }],
        }
        dest = output_dir(self.cfg) / pack_id
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "story.json").write_text(
            json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")

    def _story_i2v_extra(
        self, male: str, extra: str, beat: dict, *,
        nude: bool, theme: str, story_clothing: str,
        male_theme: str = "",
    ) -> str:
        bits = []
        if not beat.get("solo"):
            m = (male or "").strip()
            if m:
                if "1boy" not in m.lower():
                    bits.append("1boy")
                bits.append(m)
            else:
                bits.append(DEFAULT_MALE)
            if not nude:
                mt = male_theme_of(male_theme) if male_theme else None
                if mt and mt.get("tags"):
                    bits.append(mt["tags"])
        if extra:
            bits.append(extra)
        if beat.get("extra"):
            bits.append(beat["extra"])
        look = beat_visual_look(beat)
        if look:
            bits.append(look)
        if not nude and story_clothing and not (theme or "").strip():
            bits.append(story_clothing)
        return ", ".join(bits)

    def _generate_story_i2v_stills(
        self,
        *,
        story_id: str,
        character: str,
        theme: str = "",
        male_theme: str = "",
        male: str = "",
        extra: str = "",
        seed: int | None = None,
        nsfw: bool = True,
        quality: bool = True,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        ollama_model: str | None = None,
        english_motion: bool | None = None,
        voice_style: str | None = None,
        language: str | None = None,
    ) -> dict:
        story = get_story(story_id, self.cfg.get("_root"))
        theme = (theme or "").strip()
        if theme:
            theme_of(theme)
        male_theme = (male_theme or "").strip()
        if male_theme.lower() == "original":
            male_theme = ""
        if male_theme:
            male_theme_of(male_theme)
        rng = random.Random(seed)
        names = self.catalog.action_names()
        male = (male or "").strip()
        extra = extra or ""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pack = f"story2_{ts}_{slug(character, 16)}_{slug(story['id'], 12)}"
        dest = output_dir(self.cfg) / pack
        n = 2
        while dest.exists():
            dest = output_dir(self.cfg) / f"{pack}_{n}"
            n += 1
        pack = dest.name
        dest.mkdir(parents=True, exist_ok=True)
        beats = story["fragments"]
        total = len(beats)
        clips = []
        nude_on = False
        prev_beat = None
        prev_frame = None
        backend = self.resolve_image_backend(image_backend)
        model_key, model_label, _ = self._model_info(diffusers_model)
        try:
            self._free_comfy()
            self.log(f"======== 短編2 {story['title']} {pack} ========")
            self.log("  I2V：每段出一張首幀，產動畫走 MiniMax H3 圖生影")
            self.log(f"  首幀後端: {backend}　模型: {model_label}")
            for ai, beat in enumerate(beats, 1):
                action = resolve_beat_action(beat, names, rng)
                beat_nsfw = beat_is_nsfw(beat)
                link = resolve_beat_link(prev_beat, beat)
                if beat.get("nude"):
                    nude_on = True
                if not nude_on and (looks_nude(action) or looks_nude(beat.get("tags") or "")):
                    nude_on = True
                    self.log(f"  此步起衣著改為 nude（{beat['title']}）")
                dur = int(beat["duration"])
                vkey, vlabel, _ = self._video_info(story_video_key(self.cfg, beat_nsfw))
                story_clothing = (
                    (beat.get("clothing") or story.get("clothing") or "").strip()
                )
                joined_extra = self._story_i2v_extra(
                    male, extra, beat, nude=nude_on, theme=theme,
                    story_clothing=story_clothing, male_theme=male_theme)
                plot_motion = compose_story_motion(
                    beat, character=character, duration=dur, nsfw=beat_nsfw,
                    link=link,
                    prev_plot=beat_plot_text(prev_beat) if prev_beat else "",
                    h3=False)
                mark = "NSFW" if beat_nsfw else "非NSFW"
                self._set_progress(
                    stage="frame",
                    progress=int(ai / total * 100),
                    message=f"短編2 {ai}/{total}　{beat['title']}　{dur}s　{mark}"
                    + ("　nude" if nude_on else ""),
                )
                self.log(
                    f"  {beat['title']}: {mark}　{vlabel}　{dur}s　圖生影")
                clip_seed = None if seed is None else seed + ai
                init = None
                if link == "reference" and prev_frame and Path(prev_frame).is_file():
                    init = prev_frame
                    self.log("  首幀參考上一段（img2img）")
                meta = self.generate_one(
                    character=character,
                    action=action,
                    theme=theme or None,
                    extra=joined_extra,
                    duration=dur,
                    seed=clip_seed,
                    nsfw=beat_nsfw,
                    quality=quality,
                    image_backend=backend,
                    diffusers_model=model_key,
                    video_model=vkey,
                    motion_prompt=plot_motion,
                    image_only=True,
                    keep_pipe=True,
                    english_motion=False,
                    voice_style=voice_style,
                    nude=nude_on,
                    theme_first=True,
                    init_image=init,
                    name=self._folder_name(
                        character, beat.get("title") or action, theme or None),
                    extra_meta={
                        "story": pack,
                        "story_id": story["id"],
                        "story_title": story["title"],
                        "story_set": 1,
                        "story_step": ai,
                        "story_beat": beat["title"],
                        "story_nude": nude_on,
                        "story_nsfw": beat_nsfw,
                        "story_link": link,
                        "story_mode": "i2v",
                        "story_clothing": story_clothing,
                        "scene_key": beat_scene_key(beat),
                        "clothing_key": beat_clothing_key(
                            nude_on, theme, story_clothing),
                        "male_theme": male_theme,
                        "male_clothing_key": beat_male_clothing_key(
                            nude_on, male_theme),
                        "story_plot": {
                            "title": beat.get("title") or "",
                            "tags": beat.get("tags") or "",
                            "action": beat.get("action") or "",
                            "extra": beat.get("extra") or "",
                            "plot": beat.get("plot") or beat_plot_text(beat),
                            "nude": bool(beat.get("nude")),
                            "solo": bool(beat.get("solo")),
                            "link": link,
                        },
                    },
                )
                clips.append({
                    "folder": meta["folder"],
                    "action": beat["title"],
                    "catalog_action": action,
                    "step": ai,
                    "duration": dur,
                    "title": beat["title"],
                    "nsfw": beat_nsfw,
                    "video_model": vkey,
                    "link": link,
                })
                prev_beat = beat
                clip_dir = output_dir(self.cfg) / meta["folder"]
                if (clip_dir / "first_frame.png").is_file():
                    prev_frame = clip_dir / "first_frame.png"
                blob = {
                    "id": pack,
                    "kind": "story",
                    "story_id": story["id"],
                    "story_title": story["title"],
                    "character": character,
                    "theme": theme,
                    "male_theme": male_theme,
                    "male": male,
                    "extra": extra,
                    "story_mode": "i2v",
                    "sets": [{
                        "index": 1,
                        "actions": [c["action"] for c in clips],
                        "clips": clips,
                    }],
                }
                (dest / "story.json").write_text(
                    json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if free_pipe():
                self.log("  短編2首幀結束，已卸載 Diffusers")
        self.log(f"  短編2完成 → {dest}")
        return json.loads((dest / "story.json").read_text(encoding="utf-8"))

    def _story_write_r2v_clip(
        self,
        *,
        character_title: str,
        character_prompt: str,
        character_label: str,
        action: str,
        beat: dict,
        theme: str | None,
        extra: str,
        duration: int,
        seed: int | None,
        nsfw: bool,
        quality: bool,
        image_backend: str,
        diffusers_model: str | None,
        video_model: str,
        scene_src: Path | None,
        clothing_key: str,
        scene_key: str,
        prev_char: Path | None,
        prev_partner: Path | None,
        prev_scene: Path | None,
        prev_clothing: str | None,
        prev_scene_key: str | None,
        nude_on: bool,
        male: str,
        has_partner: bool,
        motion_prompt: str,
        extra_meta: dict,
        partner_src: Path | None = None,
        male_theme: str | None = None,
        male_clothing_key: str = "original",
        prev_male_clothing: str | None = None,
        partner_slot: int | None = None,
        prev_partner_slot: int | None = None,
        language: str = "zh",
        voice_style: str | None = None,
        prev_char_title: str | None = None,
        char_src: Path | None = None,
        partner_card: Path | None = None,
        folder_name: str = "",
    ) -> dict:
        picked = (folder_name or "").strip()
        if picked:
            if "/" in picked or "\\" in picked or ".." in picked:
                raise ValueError("非法段落資料夾")
            folder = picked
        else:
            folder = self._folder_name(character_label, beat.get("title") or action, theme)
        dest = output_dir(self.cfg) / folder
        dest.mkdir(parents=True, exist_ok=True)
        char_path = dest / "character.png"
        partner_path = dest / "partner.png"
        scene_path = dest / "scene.png"
        wear = (beat.get("clothing") or extra_meta.get("story_clothing") or "").strip()
        scene_text = (beat.get("extra") or "").strip()
        keep_legs = ""
        if nude_on:
            prev_look = ""
            if prev_char:
                prev_look = (
                    self._clip_meta(prev_char.parent.name).get("still_prompt") or ""
                )
            keep_legs = extract_legwear(prev_look) if prev_look else extract_legwear(
                character_prompt, wear)
        char_still = compose_character_ref_prompt(
            self.cfg, character_prompt, theme, nsfw=nsfw, quality=quality,
            nude=nude_on, clothing=wear or None, keep_legwear=keep_legs or None)
        partner_still = ""
        scene_still = compose_scene_ref_prompt(
            self.cfg, scene_text, theme, nsfw=nsfw, quality=quality)
        reuse_char = (
            prev_char and prev_char.is_file()
            and prev_clothing == clothing_key
            and (prev_char_title is None or prev_char_title == character_title)
        )
        if char_src and char_src.is_file():
            shutil.copy2(char_src, char_path)
            self.log("  女角色圖用角色卡")
        elif reuse_char:
            shutil.copy2(prev_char, char_path)
            self.log("  女角色圖沿用（衣著未變）")
        else:
            note = f"（衣著: {clothing_key}"
            if nude_on and keep_legs:
                note += f"　留 {keep_legs}"
            elif nude_on:
                note += "　光腳"
            note += "）"
            self.log("  出女角色圖" + note)
            self._make_still(
                image_backend, char_still, char_path, seed, diffusers_model,
                negative=negative_ref_sheet(self.cfg))
        partner_from_default = False
        male_custom = (male or "").strip()
        male_outfit = (male_theme or "").strip()
        if male_outfit.lower() == "original":
            male_outfit = ""
        male_nude = bool(nude_on) or male_outfit.lower() == "nude"
        if has_partner:
            partner_still = compose_partner_ref_prompt(
                self.cfg, male, nsfw=nsfw, quality=quality, nude=male_nude,
                theme_key=male_outfit or None)
            use_default_male = (
                not male_custom and not male_nude and not male_outfit
            )
            if partner_card and partner_card.is_file():
                shutil.copy2(partner_card, partner_path)
                self.log("  男角色圖用角色卡")
            elif use_default_male and self._copy_default_male(partner_path):
                partner_from_default = True
                self.log(f"  男角色圖用預設參考圖（{default_male_image(self.cfg)}）")
            elif (
                prev_partner and prev_partner.is_file()
                and prev_male_clothing == male_clothing_key
                and prev_partner_slot == partner_slot
            ):
                shutil.copy2(prev_partner, partner_path)
                self.log("  男角色圖沿用（衣著未變）")
            elif partner_src and partner_src.is_file():
                shutil.copy2(partner_src, partner_path)
                self.log("  男角色圖沿用來源")
            else:
                if use_default_male:
                    self.log(f"  預設男圖不存在：{default_male_image(self.cfg)}，改為生圖")
                partner_seed = None if seed is None else int(seed) + 31
                self.log("  出男角色圖（衣著: " + male_clothing_key + "）")
                self._make_still(
                    image_backend, partner_still, partner_path, partner_seed,
                    diffusers_model, negative=negative_partner_sheet(self.cfg))
        if scene_src and scene_src.is_file():
            shutil.copy2(scene_src, scene_path)
            self.log(
                "  場景圖用場地卡" if "drafts" in scene_src.parts
                else "  場景圖沿用來源"
            )
        elif prev_scene and prev_scene.is_file() and prev_scene_key == scene_key:
            shutil.copy2(prev_scene, scene_path)
            self.log("  場景圖沿用（地點未變）")
        else:
            scene_seed = None if seed is None else int(seed) + 17
            self.log("  出場景圖（" + scene_key + "）")
            self._make_still(
                image_backend, scene_still, scene_path, scene_seed, diffusers_model,
                negative=negative_scene(self.cfg))
        vkey, vlabel, _ = self._video_info(video_model)
        model_key, model_label, _ = self._model_info(diffusers_model)
        meta = {
            "folder": folder,
            "character": character_title,
            "character_label": character_label,
            "character_prompt": character_prompt,
            "action": action,
            "action_tags": beat.get("tags") or action,
            "theme": theme,
            "male_theme": male_outfit,
            "extra": extra,
            "duration": duration,
            "main_duration": duration,
            "climax": False,
            "climax_seconds": 0,
            "seed": seed,
            "image_backend": image_backend,
            "diffusers_model": model_key,
            "diffusers_model_label": model_label,
            "video_model": vkey,
            "video_model_label": vlabel,
            "still_prompt": char_still,
            "visual_prompt": "",
            "partner_prompt": partner_still,
            "scene_prompt": scene_still,
            "motion_prompt": motion_prompt,
            "clothing_key": clothing_key,
            "male_clothing_key": male_clothing_key,
            "scene_key": scene_key,
            "voice": False,
            "language": language or "zh",
            "voice_style": voice_style or "",
            "first_frame": "",
            "visual_ref": "",
            "character_ref": "character.png",
            "partner_ref": "partner.png" if has_partner else "",
            "partner_from_default": bool(partner_from_default),
            "male_custom": male_custom,
            "scene_ref": "scene.png",
            "animation": None,
            "kind": "still",
            "story_mode": "r2v",
        }
        meta.update(extra_meta)
        (dest / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    @staticmethod
    def _story_beat_extra(male: str, extra: str, beat: dict) -> str:
        bits = []
        if not beat.get("solo"):
            m = (male or "").strip()
            if m:
                if "1boy" not in m.lower():
                    bits.append("1boy")
                bits.append(m)
            else:
                bits.append("1boy")
        if extra:
            bits.append(extra)
        if beat.get("extra"):
            bits.append(beat["extra"])
        return ", ".join(bits)

    def _clone_story_i2v_stills(
        self,
        pack_id: str,
        *,
        src: dict,
        character: str,
        voice_style: str | None = None,
        seed: int | None = None,
        nsfw: bool = True,
        quality: bool = True,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        ollama_model: str | None = None,
    ) -> dict:
        src_sets = src.get("sets") or []
        theme = (src.get("theme") or "").strip()
        if theme:
            theme_of(theme)
        male = (src.get("male") or "").strip()
        extra = src.get("extra") or ""
        _, new_prompt, new_label = self._resolve_character(
            character, False, False, theme, extra, seed, random.Random(seed))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pack = f"story2_{ts}_{slug(character, 16)}_{slug(src.get('story_id') or 'copy', 12)}"
        dest = output_dir(self.cfg) / pack
        n = 2
        while dest.exists():
            dest = output_dir(self.cfg) / f"{pack}_{n}"
            n += 1
        pack = dest.name
        dest.mkdir(parents=True, exist_ok=True)
        steps = []
        for s in src_sets:
            for c in s.get("clips") or []:
                folder = c.get("folder") or ""
                meta_path = output_dir(self.cfg) / folder / "meta.json"
                if not meta_path.exists():
                    continue
                info = json.loads(meta_path.read_text(encoding="utf-8"))
                steps.append((s.get("index") or 1, c, info))
        if not steps:
            shutil.rmtree(dest, ignore_errors=True)
            raise FileNotFoundError("來源步驟的 meta.json 都不在了")
        total = len(steps)
        sets_map: dict[int, dict] = {}
        try:
            self._free_comfy()
            self.log("  複製短編2：沿用構圖，換成新角色")
            for i, (si, src_clip, info) in enumerate(steps, 1):
                title = src_clip.get("title") or src_clip.get("action") or ""
                action = src_clip.get("catalog_action") or info.get("action") or title
                still = self._retarget_still(
                    info.get("still_prompt") or "",
                    (info.get("character_prompt") or "").strip(),
                    new_prompt)
                nude_on = bool(info.get("story_nude")) or looks_nude(still)
                beat_nsfw = self._story_clip_nsfw(info, src_clip)
                dur = int(src_clip.get("duration") or info.get("main_duration") or 8)
                vkey = story_video_key(
                    self.cfg, beat_nsfw, info.get("video_model") if beat_nsfw else None)
                plot = info.get("story_plot") or {}
                link = (
                    src_clip.get("link") or info.get("story_link")
                    or plot.get("link") or ("cut" if i == 1 else "reference")
                )
                beat = {
                    "title": plot.get("title") or title,
                    "tags": plot.get("tags") or info.get("action_tags") or "",
                    "action": plot.get("action") or action,
                    "extra": plot.get("extra") or "",
                    "plot": plot.get("plot") or "",
                    "nude": plot.get("nude") if "nude" in plot else nude_on,
                    "duration": dur,
                    "link": link,
                    "solo": bool(plot.get("solo")),
                }
                plot_motion = compose_story_motion(
                    beat, character=new_label, duration=dur, nsfw=beat_nsfw,
                    link=link, h3=False)
                self._set_progress(
                    stage="frame",
                    progress=int((i - 1) / total * 100),
                    message=f"複製短編2 {i}/{total}　{title}　{dur}s",
                )
                self.log(f"  複製步驟 {i}/{total}: {title} → {new_label}"
                         f"（{'NSFW' if beat_nsfw else '非NSFW'}）")
                clip_seed = None if seed is None else seed + i
                meta = self.generate_one(
                    character=character,
                    action=action,
                    theme=info.get("theme") or theme or None,
                    extra=info.get("extra") or extra,
                    duration=dur,
                    seed=clip_seed,
                    nsfw=beat_nsfw,
                    quality=quality,
                    image_backend=image_backend or info.get("image_backend"),
                    diffusers_model=diffusers_model or info.get("diffusers_model"),
                    video_model=vkey,
                    still_prompt=still or None,
                    motion_prompt=plot_motion,
                    image_only=True,
                    keep_pipe=True,
                    english_motion=False,
                    voice_style=voice_style,
                    nude=nude_on,
                    theme_first=True,
                    name=self._folder_name(
                        new_label, title or action, theme or None),
                    extra_meta={
                        "story": pack,
                        "story_id": src.get("story_id") or "",
                        "story_title": src.get("story_title") or "",
                        "story_set": si,
                        "story_step": src_clip.get("step") or i,
                        "story_beat": title,
                        "story_nude": nude_on,
                        "story_nsfw": beat_nsfw,
                        "story_link": link,
                        "story_mode": "i2v",
                        "story_clothing": info.get("story_clothing") or "",
                        "scene_key": info.get("scene_key") or beat_scene_key(beat),
                        "clothing_key": info.get("clothing_key") or "",
                        "story_plot": {**(plot or beat)},
                        "copied_from": pack_id,
                        "copied_clip": src_clip.get("folder") or "",
                    },
                )
                bucket = sets_map.setdefault(int(si), {
                    "index": int(si), "actions": [], "clips": [],
                })
                bucket["actions"].append(title)
                bucket["clips"].append({
                    "folder": meta["folder"],
                    "action": title,
                    "catalog_action": action,
                    "step": len(bucket["clips"]) + 1,
                    "duration": dur,
                    "title": title,
                    "nsfw": beat_nsfw,
                    "video_model": vkey,
                    "link": link,
                })
                blob = {
                    "id": pack,
                    "kind": "story",
                    "story_id": src.get("story_id") or "",
                    "story_title": src.get("story_title") or "",
                    "character": character,
                    "theme": theme,
                    "male_theme": src.get("male_theme") or "",
                    "male": male,
                    "extra": extra,
                    "copied_from": pack_id,
                    "voice_style": voice_style or "",
                    "story_mode": "i2v",
                    "sets": [sets_map[k] for k in sorted(sets_map)],
                }
                (dest / "story.json").write_text(
                    json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if free_pipe():
                self.log("  複製短編2結束，已卸載 Diffusers")
        self.log(f"  複製完成 → {dest}")
        return json.loads((dest / "story.json").read_text(encoding="utf-8"))

    def clone_story_stills(
        self,
        pack_id: str,
        *,
        character: str,
        voice_style: str | None = None,
        seed: int | None = None,
        nsfw: bool = True,
        quality: bool = True,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        ollama_model: str | None = None,
        english_motion: bool | None = None,
    ) -> dict:
        character = (character or "").strip()
        if not character:
            raise ValueError("複製短篇必須指定新角色")
        src, _src_dir = self._load_story(pack_id)
        src_sets = src.get("sets") or []
        if not src_sets:
            raise ValueError("來源短篇沒有步驟")
        if (src.get("story_mode") or "").strip().lower() == "i2v":
            return self._clone_story_i2v_stills(
                pack_id, src=src,
                character=character, voice_style=voice_style, seed=seed,
                nsfw=nsfw, quality=quality, image_backend=image_backend,
                diffusers_model=diffusers_model, ollama_model=ollama_model)
        theme = (src.get("theme") or "").strip()
        if theme:
            theme_of(theme)
        male_theme = (src.get("male_theme") or "").strip()
        if male_theme.lower() == "original":
            male_theme = ""
        if male_theme:
            male_theme_of(male_theme)
        male = (src.get("male") or "").strip()
        extra = src.get("extra") or ""
        lang = voice_language(self.cfg, src.get("language"))
        vstyle = self._cast_voice(character, voice_style)
        _, new_prompt, new_label = self._resolve_character(
            character, False, False, theme, extra, seed, random.Random(seed))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pack = f"story_{ts}_{slug(character, 16)}_{slug(src.get('story_id') or 'copy', 12)}"
        dest = output_dir(self.cfg) / pack
        n = 2
        while dest.exists():
            dest = output_dir(self.cfg) / f"{pack}_{n}"
            n += 1
        pack = dest.name
        dest.mkdir(parents=True, exist_ok=True)
        steps = []
        for s in src_sets:
            for c in s.get("clips") or []:
                folder = c.get("folder") or ""
                meta_path = output_dir(self.cfg) / folder / "meta.json"
                if not meta_path.exists():
                    continue
                info = json.loads(meta_path.read_text(encoding="utf-8"))
                steps.append((s.get("index") or 1, c, info))
        if not steps:
            shutil.rmtree(dest, ignore_errors=True)
            raise FileNotFoundError("來源步驟的 meta.json 都不在了")
        total = len(steps)
        sets_map: dict[int, dict] = {}
        prev_char = None
        prev_clothing = None
        prev_plot = ""
        backend = self.resolve_image_backend(image_backend)
        try:
            self._free_comfy()
            self.log("  複製短篇：新角色圖，場景圖沿用來源")
            for i, (si, src_clip, info) in enumerate(steps, 1):
                title = src_clip.get("title") or src_clip.get("action") or ""
                action = src_clip.get("catalog_action") or info.get("action") or title
                nude_on = bool(info.get("story_nude"))
                beat_nsfw = self._story_clip_nsfw(info, src_clip)
                dur = int(src_clip.get("duration") or info.get("main_duration") or 8)
                vkey = story_video_key(
                    self.cfg, beat_nsfw, info.get("video_model") if beat_nsfw else None)
                plot = info.get("story_plot") or {}
                link = (
                    src_clip.get("link") or info.get("story_link")
                    or plot.get("link") or ("cut" if i == 1 else "reference")
                )
                beat = {
                    "title": plot.get("title") or title,
                    "tags": plot.get("tags") or info.get("action_tags") or "",
                    "action": plot.get("action") or action,
                    "extra": plot.get("extra") or info.get("extra") or extra,
                    "plot": plot.get("plot") or "",
                    "nude": plot.get("nude") if "nude" in plot else nude_on,
                    "duration": dur,
                    "link": link,
                    "solo": bool(plot.get("solo")),
                    "motion_clip": beat_motion_clip(
                        plot, story_id=src.get("story_id") or info.get("story_id") or "",
                        title=plot.get("title") or title),
                }
                theme_key = info.get("theme") or theme or None
                male_theme_key = info.get("male_theme") or male_theme or None
                clothing_key = beat_clothing_key(
                    nude_on, theme_key,
                    info.get("story_clothing") or plot.get("clothing") or "")
                male_clothing_key = beat_male_clothing_key(nude_on, male_theme_key)
                scene_key = info.get("scene_key") or beat_scene_key(beat)
                clothing_changed = prev_clothing is not None and clothing_key != prev_clothing
                has_partner = not bool(beat.get("solo"))
                clip_name = beat.get("motion_clip") or ""
                plot_motion = compose_story_r2v(
                    beat, character=new_label, duration=dur, nsfw=beat_nsfw,
                    link=link, prev_plot=prev_plot, nude=nude_on, male=male,
                    has_partner=has_partner,
                    clothing_changed=clothing_changed, scene_changed=False,
                    has_pose_ref=False,
                    has_motion_clip=bool(clip_name),
                    language=lang, voice_style=vstyle)
                i2v_motion = compose_story_i2v(
                    beat, duration=dur, nsfw=beat_nsfw, prev_plot=prev_plot,
                    language=lang, voice_style=vstyle, continue_shot=i > 1)
                if clip_name:
                    plot_motion = attach_motion_clip(plot_motion, nsfw=beat_nsfw)
                    self.log(f"  動作參考 {clip_name}（只借動作）")
                self._set_progress(
                    stage="frame",
                    progress=int((i - 1) / total * 100),
                    message=f"複製短篇 {i}/{total}　{title}　{dur}s",
                )
                self.log(f"  複製步驟 {i}/{total}: {title} → {new_label}"
                         f"（{'NSFW' if beat_nsfw else '非NSFW'}）")
                clip_seed = None if seed is None else seed + i
                src_dir = output_dir(self.cfg) / (src_clip.get("folder") or "")
                src_scene = src_dir / "scene.png"
                src_partner = src_dir / "partner.png"
                meta = self._story_write_r2v_clip(
                    character_title=character,
                    character_prompt=new_prompt,
                    character_label=new_label,
                    action=action,
                    beat=beat,
                    theme=theme_key,
                    extra=info.get("extra") or extra,
                    duration=dur,
                    seed=clip_seed,
                    nsfw=beat_nsfw,
                    quality=quality,
                    image_backend=backend or info.get("image_backend") or "diffusers",
                    diffusers_model=diffusers_model or info.get("diffusers_model"),
                    video_model=vkey,
                    scene_src=src_scene if src_scene.is_file() else None,
                    clothing_key=clothing_key,
                    scene_key=scene_key,
                    prev_char=prev_char,
                    prev_partner=None,
                    prev_scene=None,
                    prev_clothing=prev_clothing,
                    prev_scene_key=None,
                    nude_on=nude_on,
                    male=male,
                    male_theme=male_theme_key,
                    male_clothing_key=male_clothing_key,
                    has_partner=has_partner,
                    partner_src=src_partner if src_partner.is_file() else None,
                    motion_prompt=plot_motion,
                    language=lang,
                    voice_style=vstyle,
                    extra_meta={
                        "story": pack,
                        "story_clothing": info.get("story_clothing") or "",
                        "story_id": src.get("story_id") or "",
                        "story_title": src.get("story_title") or "",
                        "story_set": si,
                        "story_step": src_clip.get("step") or i,
                        "story_beat": title,
                        "story_nude": nude_on,
                        "story_nsfw": beat_nsfw,
                        "story_link": link,
                        "story_mode": "r2v",
                        "motion_clip": clip_name,
                        "i2v_prompt": i2v_motion,
                        "story_plot": {**(plot or beat), "motion_clip": clip_name},
                        "copied_from": pack_id,
                        "copied_clip": src_clip.get("folder") or "",
                    },
                )
                bucket = sets_map.setdefault(int(si), {
                    "index": int(si), "actions": [], "clips": [],
                })
                clip = {
                    "folder": meta["folder"],
                    "action": title,
                    "catalog_action": action,
                    "step": len(bucket["clips"]) + 1,
                    "duration": dur,
                    "title": title,
                    "nsfw": beat_nsfw,
                    "video_model": vkey,
                    "link": link,
                    "motion_clip": clip_name,
                }
                clip_dir = output_dir(self.cfg) / meta["folder"]
                if (clip_dir / "character.png").exists():
                    prev_char = clip_dir / "character.png"
                prev_clothing = clothing_key
                prev_plot = beat_plot_text(beat)
                bucket["actions"].append(title)
                bucket["clips"].append(clip)
                blob = {
                    "id": pack,
                    "kind": "story",
                    "story_id": src.get("story_id") or "",
                    "story_title": src.get("story_title") or "",
                    "character": character,
                    "theme": theme,
                    "male_theme": male_theme,
                    "male": male,
                    "extra": extra,
                    "copied_from": pack_id,
                    "language": lang,
                    "voice_style": vstyle,
                    "story_mode": "r2v",
                    "sets": [sets_map[k] for k in sorted(sets_map)],
                }
                (dest / "story.json").write_text(
                    json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if free_pipe():
                self.log("  複製短篇結束，已卸載 Diffusers")
        self.log(f"  複製完成 → {dest}")
        return json.loads((dest / "story.json").read_text(encoding="utf-8"))

    def animate_story_set(
        self,
        pack_id: str,
        set_index: int,
        *,
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        video_model: str | None = None,
        voice: bool | None = None,
        language: str | None = None,
        english_motion: bool | None = None,
        ollama_model: str | None = None,
        voice_style: str | None = None,
        story_link: str | None = None,
        turbo_steps: int | None = None,
        clip_mode: str | None = None,
        voice_ref: str | None = None,
        clip_modes: dict | None = None,
    ) -> dict:
        blob, pack_dir = self._load_story(pack_id)
        target = None
        for s in blob.get("sets") or []:
            if int(s.get("index") or 0) == int(set_index):
                target = s
                break
        if not target:
            raise ValueError(f"沒有套 {set_index}")
        clips = target.get("clips") or []
        n = len(clips)
        if not n:
            raise ValueError("這套沒有首幀")
        force_link = (story_link or "").strip().lower()
        if force_link not in {"cut", "continue", "reference", "auto"}:
            force_link = None
        per_map = {}
        for key, val in list((clip_modes or {}).items())[:40]:
            folder = str(key or "").strip()
            if folder:
                per_map[folder] = self._normalize_clip_mode(val)
        clip_mode = self._normalize_clip_mode(clip_mode)
        mode_zh = {
            "r2v": "R2V",
            "i2v": "I2V 尾幀",
            "i2v_clone": "I2V 尾幀＋聲線克隆",
        }.get(clip_mode, clip_mode)
        self.log("  產片方式：各段自訂" if per_map else f"  產片方式：{mode_zh}")
        out = []
        fresh: list[str] = []
        prev_vkey = None
        try:
            if free_pipe():
                self.log("  已卸載 Diffusers，釋放 VRAM 給動畫")
            for i, item in enumerate(clips, 1):
                folder = item.get("folder") or ""
                video = output_dir(self.cfg) / folder / "animation.mp4"
                title = item.get("title") or item.get("action") or folder
                dur = item.get("duration")
                info = self._clip_meta(folder)
                beat_nsfw = self._story_clip_nsfw(info, item)
                vkey = story_video_key(
                    self.cfg, beat_nsfw, video_model if beat_nsfw else None)
                _, vlabel, _ = self._video_info(vkey)
                mark = "NSFW" if beat_nsfw else "非NSFW"
                self._set_progress(
                    stage="video",
                    progress=int((i - 1) / n * 100),
                    message=f"短篇動畫 {i}/{n}　{title}　{mark}　{vlabel}"
                    + (f"　{dur}s" if dur else ""),
                )
                if video.exists() and video.stat().st_size > 0:
                    self.log(f"  已有動畫，跳過 {folder}")
                    self._clip_last_frame(folder)
                    out.append(folder)
                    continue
                r2v = (
                    info.get("story_mode") == "r2v"
                    or (output_dir(self.cfg) / folder / "character.png").is_file()
                )
                link = force_link or (
                    "auto" if r2v else (item.get("link") or info.get("story_link") or "")
                )
                prev_last, prev_info = self._story_prev_last_frame(info)
                has_tail = bool(prev_last and prev_last.is_file())
                this_mode = per_map.get(folder, clip_mode)
                if this_mode in {"i2v", "i2v_clone"} and has_tail:
                    mode = "I2V 聲線克隆" if this_mode == "i2v_clone" else "I2V 尾幀"
                elif this_mode in {"i2v", "i2v_clone"}:
                    mode = "R2V（沒有尾幀）"
                else:
                    mode = "R2V" if r2v else "圖生影"
                self.log(f"  {title}: {mark}　{mode}　{vlabel}")
                if prev_vkey and prev_vkey != vkey:
                    self._free_comfy()
                prev_vkey = vkey
                stored = (info.get("motion_prompt") or "").strip()
                stored_i2v = (info.get("i2v_prompt") or "").strip()
                made = self.regenerate(
                    folder,
                    redo="video",
                    duration=int(dur) if dur else None,
                    image_backend=image_backend,
                    diffusers_model=diffusers_model,
                    video_model=vkey,
                    voice=voice,
                    language=language,
                    english_motion=False,
                    motion_prompt=stored or None,
                    i2v_prompt=stored_i2v or None,
                    ollama_model=ollama_model,
                    climax=False,
                    voice_style=voice_style,
                    story_link=link or force_link,
                    turbo_steps=turbo_steps,
                    clip_mode=this_mode,
                    voice_ref=voice_ref,
                    voice_clone=False,
                )
                out.append(folder)
                if made.get("clip_mode") == "i2v_clone":
                    fresh.append(folder)
        finally:
            self._free_comfy()
        if fresh and voice is not False:
            try:
                for i, folder in enumerate(fresh, 1):
                    self._set_progress(
                        stage="video",
                        progress=int((i - 1) / max(len(fresh), 1) * 100),
                        message=f"克隆聲線 {i}/{len(fresh)}",
                    )
                    dest = output_dir(self.cfg) / folder
                    video = dest / "animation.mp4"
                    info = self._clip_meta(folder)
                    self._apply_voxcpm_voice(
                        dest, video,
                        spoken=(info.get("dialogue") or "").strip(),
                        voice_ref=voice_ref or info.get("voice_ref"),
                        voice_style=voice_style or info.get("voice_style"),
                    )
            finally:
                if free_voxcpm():
                    self.log("  已卸載 VoxCPM")
        return {"id": pack_id, "set": set_index, "folders": out}

    def concat_story_set(self, pack_id: str, set_index: int) -> dict:
        blob, pack_dir = self._load_story(pack_id)
        target = None
        for s in blob.get("sets") or []:
            if int(s.get("index") or 0) == int(set_index):
                target = s
                break
        if not target:
            raise ValueError(f"沒有套 {set_index}")
        videos = []
        missing = []
        for item in target.get("clips") or []:
            folder = item.get("folder") or ""
            p = output_dir(self.cfg) / folder / "animation.mp4"
            if p.exists() and p.stat().st_size > 0:
                videos.append(p)
            else:
                missing.append(item.get("title") or item.get("action") or folder)
        if missing:
            raise ValueError("還有未產動畫的步驟：" + "、".join(missing[:8]))
        if len(videos) < 2:
            raise ValueError("至少要兩支動畫才能合併")
        out = pack_dir / f"set{int(set_index)}_full.mp4"
        self._set_progress(stage="video", progress=None, message="合併短篇…")
        if not self._concat_many(videos, out):
            raise RuntimeError("ffmpeg 合併失敗")
        target["joined"] = out.name
        (pack_dir / "story.json").write_text(
            json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"  已合併 → {out}")
        return {"id": pack_id, "set": set_index, "joined": out.name}

    def concat_editor_segments(self, draft: dict) -> dict:
        """編輯模式：依段落順序把各段動畫接成一支。"""
        draft_id = str((draft or {}).get("id") or "").strip()
        if not draft_id or "/" in draft_id or "\\" in draft_id or ".." in draft_id:
            raise ValueError("非法草稿")
        segs = [s for s in (draft.get("segments") or []) if isinstance(s, dict)]
        if len(segs) < 2:
            raise ValueError("至少要兩個段落才能合併")
        out_root = output_dir(self.cfg).resolve()
        videos = []
        missing = []
        for seg in segs:
            name = str(seg.get("name") or "").strip() or "未命名"
            folder = str(seg.get("folder") or "").strip()
            if not folder or "/" in folder or "\\" in folder or ".." in folder:
                missing.append(name)
                continue
            path = (out_root / folder / "animation.mp4").resolve()
            if (
                not str(path).startswith(str(out_root))
                or not path.is_file()
                or path.stat().st_size <= 0
            ):
                missing.append(name)
                continue
            videos.append(path)
        if missing:
            raise ValueError("這些段落還沒有動畫：" + "、".join(missing[:8]))
        if len(videos) < 2:
            raise ValueError("至少要兩段動畫才能合併")
        pack_id = "editpack_" + draft_id
        dest = out_root / pack_id
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / "joined.mp4"
        self._set_progress(stage="video", progress=None, message=f"合併 {len(videos)} 段…")
        self.log(f"  合併 {len(videos)} 段")
        if not self._concat_many(videos, out):
            raise RuntimeError("ffmpeg 合併失敗")
        self.log(f"  已合併 → {out}")
        return {"pack_id": pack_id, "joined": f"{pack_id}/joined.mp4"}

    def remove_story_clip(self, pack_id: str, folder: str) -> dict:
        blob, pack_dir = self._load_story(pack_id)
        folder = (folder or "").strip()
        if not folder:
            raise ValueError("沒有指定要刪的段落")
        found = False
        set_index = None
        for s in blob.get("sets") or []:
            clips = list(s.get("clips") or [])
            keep = [c for c in clips if (c.get("folder") or "") != folder]
            if len(keep) == len(clips):
                continue
            found = True
            set_index = s.get("index")
            for i, c in enumerate(keep, 1):
                c["step"] = i
            s["clips"] = keep
            s["actions"] = [c.get("action") for c in keep if c.get("action")]
            s.pop("joined", None)
            joined = pack_dir / f"set{int(set_index or 0)}_full.mp4"
            joined.unlink(missing_ok=True)
            break
        if not found:
            raise FileNotFoundError(f"短篇裡沒有這一段: {folder}")
        blob["sets"] = [s for s in (blob.get("sets") or []) if s.get("clips")]
        clip_dir = output_dir(self.cfg) / folder
        if clip_dir.is_dir() and str(clip_dir.resolve()).startswith(
                str(output_dir(self.cfg).resolve())):
            shutil.rmtree(clip_dir)
        if not blob["sets"]:
            shutil.rmtree(pack_dir)
            return {"id": pack_id, "deleted": folder, "pack_deleted": True}
        (pack_dir / "story.json").write_text(
            json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"id": pack_id, "deleted": folder, "set": set_index, "pack_deleted": False}

    def _load_story(self, pack_id: str) -> tuple[dict, Path]:
        return self._load_pack(pack_id, "story.json", "短篇")

    def _clip_meta(self, folder: str) -> dict:
        meta_path = output_dir(self.cfg) / folder / "meta.json"
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _story_beat_from_meta(self, meta: dict, item: dict | None = None) -> dict:
        plot = meta.get("story_plot") or {}
        item = item or {}
        title = plot.get("title") or meta.get("story_beat") or item.get("title") or ""
        return {
            "title": title,
            "tags": plot.get("tags") or meta.get("action_tags") or "",
            "action": plot.get("action") or item.get("catalog_action") or meta.get("action") or "",
            "extra": plot.get("extra") or meta.get("extra") or "",
            "plot": plot.get("plot") or "",
            "nude": plot.get("nude") if "nude" in plot else meta.get("story_nude"),
            "duration": item.get("duration") or meta.get("main_duration") or meta.get("duration") or 6,
            "link": plot.get("link") or meta.get("story_link") or item.get("link") or "",
            "motion_clip": meta_motion_clip(meta, {**item, "title": title}),
            "shots": plot.get("shots") or [],
            "dialogue": plot.get("dialogue") or meta.get("dialogue") or "",
        }

    @staticmethod
    def _is_generic_motion(text: str) -> bool:
        low = (text or "").lower()
        return (
            "camera stays locked" in low
            or "鏡頭固定" in (text or "")
            or "continuous rhythm" in low
            or "持續做「" in (text or "")
        )

    def _story_i2v_prompt(
        self, meta: dict, motion: str = "", *,
        spoken: str = "", lang: str = "zh", tone: str = "",
        use_voice: bool = False,
    ) -> str:
        """短篇圖生影：R2V 用 Ref2VA；舊包才走 I2VA。"""
        text = (motion or "").strip()
        if not text or self._is_generic_motion(text):
            text = (meta.get("motion_prompt") or "").strip()
        r2v = meta.get("story_mode") == "r2v" or looks_like_r2v_prompt(text)
        if r2v:
            beat = self._story_beat_from_meta(meta)
            if looks_like_r2v_prompt(text):
                out = text
            else:
                out = compose_story_r2v(
                    beat,
                    character=meta.get("character_label") or meta.get("character") or "",
                    duration=int(meta.get("main_duration") or meta.get("duration") or beat.get("duration") or 6),
                    nsfw=self._story_clip_nsfw(meta),
                    link=(meta.get("story_link") or beat.get("link") or "cut"),
                    nude=bool(meta.get("story_nude") or beat.get("nude")),
                    male="",
                    has_partner=bool(meta.get("partner_ref") or meta.get("partner_prompt")),
                    clothing_changed=False,
                    scene_changed=False,
                    has_pose_ref=False,
                    has_motion_clip=bool(beat.get("motion_clip")),
                    language=lang or meta.get("language") or "zh",
                    voice_style=meta.get("voice_style"),
                )
            if beat.get("motion_clip"):
                out = attach_motion_clip(out, nsfw=self._story_clip_nsfw(meta))
            else:
                out = detach_motion_clip(out)
            return lock_r2v_anime_style(out)
        if not text or self._is_generic_motion(text):
            text = beat_plot_text(self._story_beat_from_meta(meta))
        if not text:
            text = (meta.get("story_beat") or meta.get("action") or "").strip()
        if video_is_h3(self.cfg, meta.get("video_model")):
            return wrap_h3_i2va(
                text,
                dialogue=spoken if use_voice else "",
                language=lang,
                tone=h3_speaker_desc(meta.get("voice_style")),
                nsfw=self._story_clip_nsfw(meta),
                static_camera=False,
            )
        if use_voice and spoken and spoken not in text:
            from .voice import attach_voice
            text = attach_voice(text, spoken, language=lang, tone=tone, english=True)
        return text

    @staticmethod
    def _normalize_clip_mode(mode: str | None) -> str:
        key = (mode or "r2v").strip().lower()
        return {
            "1": "r2v", "r2v": "r2v",
            "2": "i2v", "i2v": "i2v", "i2v_tail": "i2v",
            "3": "i2v_clone", "i2v_clone": "i2v_clone", "clone": "i2v_clone",
            "r2v_audio": "i2v_clone", "mux": "i2v_clone",
        }.get(key, "r2v")

    @staticmethod
    def _is_continue_i2v(meta: dict, prev_info: dict | None, story_link: str) -> bool:
        link = (story_link or "").strip().lower()
        if link == "continue":
            return True
        if link == "auto" and prev_info:
            return (
                (meta.get("scene_key") or "") == (prev_info.get("scene_key") or "")
                and (meta.get("clothing_key") or "") == (prev_info.get("clothing_key") or "")
            )
        return False

    def _story_continue_i2v_prompt(
        self, meta: dict, *, spoken: str = "", lang: str = "zh",
        voice_style: str | None = None,
    ) -> str:
        beat = self._story_beat_from_meta(meta)
        return compose_story_i2v(
            beat,
            duration=int(meta.get("main_duration") or meta.get("duration") or beat.get("duration") or 6),
            nsfw=self._story_clip_nsfw(meta),
            language=lang,
            voice_style=voice_style or meta.get("voice_style"),
            dialogue=spoken,
            continue_shot=True,
        )

    def _resolve_i2v_motion(
        self, meta: dict, explicit: str | None, *,
        spoken: str, lang: str, voice_style: str | None, use_voice: bool,
    ) -> str:
        if explicit is not None:
            text = (explicit or "").strip()
            if looks_like_r2v_prompt(text):
                text = ""
        else:
            text = (meta.get("i2v_prompt") or "").strip()
            if looks_like_r2v_prompt(text):
                text = ""
        if text:
            self.log("  使用已存的 I2V 鏡頭稿")
            if not looks_like_h3_prompt(text):
                text = wrap_h3_i2va(
                    text,
                    dialogue=spoken if use_voice else "",
                    language=lang,
                    tone=h3_speaker_desc(voice_style),
                    soundscape=CONTINUE_I2V_SOUNDSCAPE,
                    nsfw=self._story_clip_nsfw(meta),
                    static_camera=True,
                )
            elif not use_voice:
                text = strip_spoken_dialogue(text)
            return text
        self.log("  依劇情寫 I2V 鏡頭稿")
        return self._story_continue_i2v_prompt(
            meta, spoken=spoken if use_voice else "",
            lang=lang, voice_style=voice_style)

    def _story_clip_nsfw(self, meta: dict, item: dict | None = None) -> bool:
        if meta.get("story_nsfw") is not None:
            return bool(meta["story_nsfw"])
        if item and item.get("nsfw") is not None:
            return bool(item["nsfw"])
        return beat_is_nsfw(self._story_beat_from_meta(meta, item))

    def _story_clip_motion(
        self, meta: dict, item: dict | None = None, *,
        duration: int | None, seed: int | None,
        spoken: str = "", lang: str = "zh", tone: str = "",
        link: str = "cut", prev_plot: str = "",
    ) -> str:
        beat = self._story_beat_from_meta(meta, item)
        nsfw = self._story_clip_nsfw(meta, item)
        char = meta.get("character_label") or meta.get("character") or ""
        dur = int(duration or beat.get("duration") or 6)
        try:
            text = ai_story_motion(
                self.cfg, beat=beat, character=char, duration=dur,
                nsfw=nsfw, seed=seed, link=link, prev_plot=prev_plot)
            self.log("  短篇動作稿: 依劇情（Ollama）")
        except OllamaError as e:
            self.log(f"  短篇動作稿改用劇情模板：{e}")
            text = compose_story_motion(
                beat, character=char, duration=dur, nsfw=nsfw,
                link=link, prev_plot=prev_plot, h3=True)
        return wrap_h3_i2va(
            text, dialogue=spoken, language=lang,
            tone=h3_speaker_desc(), nsfw=nsfw, static_camera=False)

    def _clip_last_frame(self, folder: str) -> Path | None:
        dest = output_dir(self.cfg) / folder
        last = dest / "last_frame.png"
        if last.exists() and last.stat().st_size > 0:
            return last
        video = dest / "animation.mp4"
        if video.exists() and video.stat().st_size > 0:
            if self._extract_last_frame(video, last):
                return last
        return None

    def _story_prev_last_frame(self, meta: dict) -> tuple[Path | None, dict | None]:
        pack = (meta.get("story") or "").strip()
        step = int(meta.get("story_step") or 0)
        set_i = int(meta.get("story_set") or 1)
        if not pack or step <= 1:
            return None, None
        try:
            blob, _ = self._load_story(pack)
        except FileNotFoundError:
            return None, None
        prev_item = None
        for s in blob.get("sets") or []:
            if int(s.get("index") or 0) != set_i:
                continue
            for c in s.get("clips") or []:
                if int(c.get("step") or 0) == step - 1:
                    prev_item = c
                    break
        if not prev_item:
            return None, None
        folder = prev_item.get("folder") or ""
        last = self._clip_last_frame(folder)
        return last, self._clip_meta(folder) if folder else None

    def _story_prev_video(self, meta: dict) -> Path | None:
        last, prev = self._story_prev_last_frame(meta)
        candidates = []
        if last:
            candidates.append(last.parent / "animation.mp4")
        folder = ((prev or {}).get("folder") or "").strip()
        if folder:
            candidates.append(output_dir(self.cfg) / folder / "animation.mp4")
        for p in candidates:
            if p.is_file() and p.stat().st_size > 0:
                return p
        return None

    def _story_prepare_start_frame(
        self, dest: Path, frame_path: Path, *,
        link: str, prev_last: Path | None,
        still_prompt: str, seed: int | None,
        backend: str, diffusers_model: str | None,
    ) -> Path:
        if not prev_last or not prev_last.is_file() or link not in {"continue", "reference"}:
            return frame_path
        start = dest / "start_frame.png"
        backup = dest / "still.png"
        if frame_path.exists() and not backup.exists():
            shutil.copy2(frame_path, backup)
        if link == "continue":
            shutil.copy2(prev_last, start)
            shutil.copy2(start, frame_path)
            self.log("  直接接上一段尾幀繼續")
            return start
        try:
            self._free_comfy()
            self.log("  用上一段尾幀當參考，重出本段首幀")
            self._make_still(
                backend, still_prompt, start, seed, diffusers_model,
                init_image=prev_last)
            if free_pipe():
                self.log("  已卸載 Diffusers")
            shutil.copy2(start, frame_path)
            return start
        except Exception as e:
            self.log(f"  參考生圖失敗，改用原首幀：{e}")
            if free_pipe():
                pass
            return frame_path

    def _load_pack(self, pack_id: str, filename: str, label: str) -> tuple[dict, Path]:
        dest = output_dir(self.cfg) / pack_id
        meta_path = dest / filename
        if not dest.is_dir() or not meta_path.exists():
            raise FileNotFoundError(f"找不到{label}: {pack_id}")
        return json.loads(meta_path.read_text(encoding="utf-8")), dest

    def regenerate(
        self,
        folder: str,
        *,
        still_prompt: str | None = None,
        motion_prompt: str | None = None,
        i2v_prompt: str | None = None,
        partner_prompt: str | None = None,
        scene_prompt: str | None = None,
        visual_prompt: str | None = None,
        redo: str = "both",
        image_backend: str | None = None,
        diffusers_model: str | None = None,
        video_model: str | None = None,
        seed: int | None = None,
        dialogue: str | None = None,
        voice: bool | None = None,
        language: str | None = None,
        duration: int | None = None,
        english_motion: bool | None = None,
        ollama_model: str | None = None,
        climax_motion: str | None = None,
        climax: bool | None = None,
        climax_seconds: int | None = None,
        voice_style: str | None = None,
        story_link: str | None = None,
        i2i: bool = False,
        turbo_steps: int | None = None,
        motion_clip: str | None = None,
        clip_mode: str | None = None,
        voice_ref: str | None = None,
        voice_clone: bool | None = None,
    ) -> dict:
        dest = output_dir(self.cfg) / folder
        meta_path = dest / "meta.json"
        if not dest.is_dir() or not meta_path.exists():
            raise FileNotFoundError(f"找不到動畫或 meta.json: {folder}")
        if ollama_model:
            self.cfg = apply_ollama_model(self.cfg, ollama_model)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if motion_clip is not None:
            name = (motion_clip or "").strip()
            meta["motion_clip"] = Path(name).stem if name else ""
            plot = dict(meta.get("story_plot") or {})
            plot["motion_clip"] = meta["motion_clip"]
            meta["story_plot"] = plot
        still = (still_prompt if still_prompt is not None else meta.get("still_prompt") or "").strip()
        partner_text = (
            partner_prompt if partner_prompt is not None else meta.get("partner_prompt") or ""
        ).strip()
        scene_text = (
            scene_prompt if scene_prompt is not None else meta.get("scene_prompt") or ""
        ).strip()
        visual_text = (
            visual_prompt if visual_prompt is not None else meta.get("visual_prompt") or ""
        ).strip()
        custom_motion = (motion_prompt if motion_prompt is not None else meta.get("motion_prompt") or "").strip()
        motion = custom_motion
        lang = voice_language(self.cfg, language or meta.get("language"))
        use_voice = voice_enabled(self.cfg, voice if voice is not None else meta.get("voice"))
        vstyle = resolve_voice_style(self.cfg, voice_style or meta.get("voice_style"))
        tone = voice_tone(lang, vstyle)
        spoken = (dialogue if dialogue is not None else meta.get("dialogue") or "").strip()
        use_en = bool(english_motion)
        use_climax = self._climax_on(climax)
        is_story = bool(meta.get("story") or meta.get("story_id"))
        caller_motion = (motion_prompt or "").strip() if motion_prompt is not None else ""
        beat_nsfw = self._story_clip_nsfw(meta) if is_story else False
        requested_link = (story_link or "").strip().lower()
        story_link = "cut"
        prev_last = None
        prev_info = None
        use_r2v = False
        cont_i2v = False
        mode_given = bool((clip_mode or "").strip()) if clip_mode is not None else False
        if not mode_given:
            clip_mode = meta.get("clip_mode") or "r2v"
        clip_mode = self._normalize_clip_mode(clip_mode)
        making_video = redo in {"video", "both"}
        if is_story:
            use_en = False
            use_climax = False
            use_r2v = (
                meta.get("story_mode") == "r2v"
                or ((dest / "character.png").is_file()
                    and (dest / "scene.png").is_file())
            )
            video_model = story_video_key(
                self.cfg, beat_nsfw, video_model if beat_nsfw else None)
            prev_last, prev_info = self._story_prev_last_frame(meta)
            if requested_link in {"cut", "continue", "reference", "auto"}:
                story_link = requested_link
            else:
                story_link = (meta.get("story_link") or "").strip().lower()
                if story_link not in {"cut", "continue", "reference", "auto"}:
                    story_link = "auto" if use_r2v else resolve_beat_link(
                        self._story_beat_from_meta(prev_info) if prev_info else None,
                        self._story_beat_from_meta(meta),
                    )
            has_tail = bool(prev_last and prev_last.is_file())
            want_tail = clip_mode in {"i2v", "i2v_clone"}
            if making_video and want_tail and has_tail:
                cont_i2v = True
                use_r2v = False
                label = "I2V 聲線克隆" if clip_mode == "i2v_clone" else "I2V 尾幀"
                self.log(f"  {label}：上一段 last_frame → 圖生影")
            elif making_video and want_tail and not has_tail:
                self.log("  沒有上一段尾幀，改 R2V")
                clip_mode = "r2v"
            elif making_video:
                clip_mode = "r2v"
        redo_ref = redo if redo in {"character", "partner", "scene", "visual"} else None
        if redo not in {"frame", "video", "both"} and not redo_ref:
            raise ValueError("redo 必須是 frame / video / both / visual / character / partner / scene")
        if redo in {"frame", "both", "character"} and not still:
            raise ValueError("女角色／首幀 prompt 不可為空")
        if redo == "visual" and not visual_text:
            raise ValueError("視覺圖 prompt 不可為空")
        if redo == "partner" and not partner_text:
            raise ValueError("男角色 prompt 不可為空")
        if redo == "scene" and not scene_text:
            raise ValueError("場景 prompt 不可為空")
        if redo in {"video", "both"}:
            if is_story:
                if not spoken:
                    spoken = beat_dialogue(self._story_beat_from_meta(meta))
                if cont_i2v:
                    motion = self._resolve_i2v_motion(
                        meta, i2v_prompt,
                        spoken=spoken, lang=lang, voice_style=vstyle,
                        use_voice=use_voice)
                else:
                    motion = self._story_i2v_prompt(
                        meta, caller_motion or custom_motion,
                        spoken=spoken, lang=lang, tone=tone, use_voice=use_voice)
                custom_motion = motion
            elif use_en and not custom_motion:
                motion = ""
            elif not motion:
                motion = compose_motion_prompt(
                    meta.get("character_label") or "",
                    meta.get("action") or "",
                    meta.get("action_tags") or "",
                    meta.get("theme"),
                    meta.get("extra") or "",
                    dialogue=spoken, language=lang, tone=tone,
                    scene_key=meta.get("scene") or None)
            elif use_voice and spoken and spoken not in motion:
                from .voice import attach_voice
                motion = attach_voice(motion, spoken, language=lang, tone=tone)
            if not use_en and not motion:
                raise ValueError("動作 prompt 不可為空")

        backend = self.resolve_image_backend(image_backend or meta.get("image_backend"))
        model_key = diffusers_model or meta.get("diffusers_model")
        model_key, model_label, _ = self._model_info(model_key)
        vkey, vlabel, vinfo = self._video_info(video_model or meta.get("video_model"))
        turbo_steps = self._turbo_steps(vkey, turbo_steps, meta)
        vmin = int(vinfo["duration_min"])
        vmax = int(vinfo["duration_max"])
        if duration is None:
            duration = int(meta.get("main_duration") or 0)
            if not duration:
                total = int(meta.get("duration") or self.cfg["video"]["duration_default"])
                prev = int(meta.get("climax_seconds") or 0)
                duration = total - prev if prev and total > prev else total
        duration = max(vmin, min(vmax, int(duration)))
        requested_seed = seed
        seed = seed if seed is not None else meta.get("seed")
        frame_path = dest / "first_frame.png"
        video_path = dest / "animation.mp4"

        redo_frame = redo in {"frame", "both"}
        redo_video = redo in {"video", "both"}
        if redo_ref:
            redo_frame = False
            redo_video = False
        requested_climax = (climax_motion or "").strip() or None
        climax_motion = None
        last_frame_name = None
        climax_secs = 0
        if use_climax:
            duration, climax_secs = self._climax_budget(
                duration, vinfo, climax_seconds)
            if not climax_secs:
                use_climax = False
        main_duration = duration

        self.log(f"🔄 重作 {folder}（{redo}）")
        if is_story:
            link_zh = {"continue": "接尾幀", "reference": "參考", "cut": "新開"}.get(
                story_link, story_link)
            how = "R2V 角色＋場景" if use_r2v else "照 prompt 圖生影"
            self.log(f"  短篇段落: {'NSFW' if beat_nsfw else '非NSFW'}　{link_zh}　{how}")
        self.log(f"  後端: {backend}　模型: {model_label}　圖生影: {vlabel}　{duration}s")
        if redo_video and use_climax:
            self.log(f"  高潮 [Shot 2] {climax_secs}s，總長 {duration + climax_secs}s")
        try:
            if redo_ref:
                if not use_r2v:
                    raise ValueError("獨立重出參考圖只適用於短篇 R2V")
                if requested_seed is None:
                    seed = random.randint(0, 2**31 - 1)
                self._free_comfy()
                prompt = {
                    "visual": visual_text,
                    "character": still,
                    "partner": partner_text,
                    "scene": scene_text,
                }[redo_ref]
                self._regen_story_ref(
                    dest, redo_ref, prompt,
                    backend=backend, seed=seed, diffusers_model=model_key)
                if backend == "diffusers" and free_pipe():
                    self.log("  已卸載 Diffusers")
            if redo_frame:
                self._free_comfy()
                init = None
                if is_story and i2i and not use_r2v:
                    init = prev_last
                    if init:
                        self.log("  i2i 參照上一段尾幀重出首幀")
                    else:
                        raise ValueError("沒有上一段尾幀可參考，請先產上一段動畫")
                self._set_progress(stage="frame", progress=0, message="生成參考圖…" if use_r2v else "生成首幀…")
                if use_r2v:
                    self._regen_story_ref(
                        dest, "character", still,
                        backend=backend, seed=seed, diffusers_model=model_key)
                    if partner_text:
                        self._regen_story_ref(
                            dest, "partner", partner_text,
                            backend=backend, seed=seed, diffusers_model=model_key)
                    if scene_text:
                        self._regen_story_ref(
                            dest, "scene", scene_text,
                            backend=backend, seed=seed, diffusers_model=model_key)
                else:
                    self._make_still(
                        backend, still, frame_path, seed, model_key, init_image=init)
                self._set_progress(stage="frame", progress=100, message="圖像完成")
                if is_story and i2i and not use_r2v:
                    video_path.unlink(missing_ok=True)
                    (dest / "last_frame.png").unlink(missing_ok=True)
                    (dest / "start_frame.png").unlink(missing_ok=True)
                if backend == "diffusers" and free_pipe():
                    self.log("  已卸載 Diffusers")
            if redo_video:
                frame_link = "continue" if cont_i2v else story_link
                if (not use_r2v and is_story and prev_last
                        and frame_link in {"continue", "reference"}
                        and not (i2i and redo_frame)):
                    frame_path = self._story_prepare_start_frame(
                        dest, frame_path, link=frame_link, prev_last=prev_last,
                        still_prompt=still, seed=seed, backend=backend,
                        diffusers_model=model_key)
                if use_r2v:
                    if not (dest / "character.png").exists() or not (dest / "scene.png").exists():
                        raise FileNotFoundError("短篇 R2V 需要 character.png 與 scene.png")
                elif not frame_path.exists():
                    raise FileNotFoundError("沒有首幀，請先重作首幀")
                if free_pipe():
                    self.log(f"  已卸載 Diffusers，釋放 VRAM 給 {vlabel}")
                if not is_story:
                    if use_en and not custom_motion:
                        motion = self._motion_from_frame(
                            frame_path, meta.get("action") or "",
                            meta.get("action_tags") or "", meta.get("extra") or "",
                            spoken, lang, tone, duration, seed,
                            h3=video_is_h3(self.cfg, vkey), voice_style=vstyle)
                    elif use_en and not video_is_h3(self.cfg, vkey):
                        motion = lock_camera_en(motion)
                if not use_r2v:
                    motion = self._finalize_motion(
                        motion, video_model=vkey,
                        spoken=spoken if use_voice else "",
                        lang=lang, tone=tone, use_en=use_en,
                        action=meta.get("action") or "",
                        tags=meta.get("action_tags") or "",
                        nsfw=not is_story or beat_nsfw,
                        static_camera=not is_story,
                        voice_style=vstyle)
                if not motion:
                    raise ValueError("動作 prompt 不可為空")
                video_motion = motion
                if use_climax:
                    video_motion, climax_motion = self._attach_climax_shot(
                        motion, meta.get("action") or "",
                        meta.get("action_tags") or "", lang, climax_secs,
                        custom=requested_climax, voice_style=vstyle,
                        video_model=vkey)
                    duration = main_duration + climax_secs
                self._free_vision()
                self._set_progress(stage="video", progress=None, message="生成動畫…")
                if use_r2v:
                    prev_vid = self._story_prev_video(meta)
                    use_prev_video = False
                    if prev_vid:
                        if story_link == "continue":
                            use_prev_video = True
                        elif story_link == "auto" and prev_info:
                            use_prev_video = (
                                (meta.get("scene_key") or "")
                                == (prev_info.get("scene_key") or "")
                                and (meta.get("clothing_key") or "")
                                == (prev_info.get("clothing_key") or "")
                            )
                    ref_clip = None
                    if use_prev_video:
                        tail = dest / "_prev_ref.mp4"
                        if self._extract_tail_video(prev_vid, tail):
                            ref_clip = tail
                            video_motion = shift_motion_video_tag(video_motion)
                            video_motion = attach_video_continue(video_motion)
                            self.log("  參考上一段動畫（<Video 1>）")
                        else:
                            self.log("  上一段影片擷取失敗，改為獨立生成")
                    motion_path = self._story_motion_clip_path(meta)
                    ref_videos = []
                    if ref_clip:
                        ref_videos.append(ref_clip)
                    if motion_path:
                        tag = "<Video 2>" if ref_clip else "<Video 1>"
                        video_motion = attach_motion_clip(
                            video_motion, tag=tag,
                            nsfw=beat_nsfw if is_story else bool(meta.get("nsfw", True)))
                        ref_videos.append(motion_path)
                        if str(meta.get("motion_mode") or "") == "audio":
                            self.log(f"  動作參考 {motion_path.stem}（{tag} 借動作，完成後複製音軌）")
                        else:
                            self.log(f"  動作參考 {motion_path.stem}（{tag} 只借動作）")
                    else:
                        stripped = detach_motion_clip(video_motion)
                        if stripped != video_motion:
                            self.log("  不使用動作庫參考影片")
                        video_motion = stripped
                    id_temps: list[Path] = []
                    try:
                        if motion_path:
                            refs, id_temps = self._story_r2v_identity_refs(dest)
                            woman_pic = man_pic = ""
                            for i, p in enumerate(refs, 1):
                                if p.name == "_id_char_face.png":
                                    woman_pic = f"<Picture {i}>"
                                elif p.name == "_id_partner_face.png":
                                    man_pic = f"<Picture {i}>"
                            if woman_pic or man_pic:
                                video_motion = attach_identity_closeups(
                                    video_motion, woman_pic=woman_pic, man_pic=man_pic)
                                self.log("  三視圖改傳正面全身＋臉部特寫（鎖髮色／體型）")
                        else:
                            refs = self._story_r2v_refs(dest)
                        video_motion = lock_r2v_anime_style(video_motion)
                        self._make_r2v(
                            refs,
                            video_motion, video_path, duration, seed,
                            video_model=vkey, ref_videos=ref_videos,
                            turbo_steps=turbo_steps,
                            ref_image_size="max" if motion_path else "match",
                            nsfw=beat_nsfw if is_story else bool(meta.get("nsfw", True)),
                            climax=use_climax,
                            action=meta.get("action") or "",
                            tags=meta.get("action_tags") or "",
                            extra=meta.get("extra") or "",
                            look=still)
                    finally:
                        if ref_clip:
                            ref_clip.unlink(missing_ok=True)
                        for p in id_temps:
                            p.unlink(missing_ok=True)
                    if (
                        video_path.is_file()
                        and motion_path
                        and str(meta.get("motion_mode") or "") == "audio"
                    ):
                        self._copy_ref_audio(video_path, motion_path)
                else:
                    self._make_video(frame_path, video_motion, video_path, duration, seed,
                                     video_model=vkey, turbo_steps=turbo_steps,
                                     nsfw=beat_nsfw if is_story else bool(meta.get("nsfw", True)),
                                     climax=use_climax,
                                     action=meta.get("action") or "",
                                     tags=meta.get("action_tags") or "",
                                     extra=meta.get("extra") or "",
                                     look=still)
                if is_story:
                    last = dest / "last_frame.png"
                    if self._extract_last_frame(video_path, last):
                        last_frame_name = last.name
                if redo_video and clip_mode != "i2v_clone":
                    (dest / "voice_clone.wav").unlink(missing_ok=True)
                do_clone = (
                    clip_mode == "i2v_clone" and use_voice and voice_clone is not False
                    and redo_video and video_path.is_file()
                )
                if do_clone:
                    self._free_comfy()
                    self._apply_voxcpm_voice(
                        dest, video_path,
                        spoken=spoken if use_voice else "",
                        voice_ref=voice_ref or meta.get("voice_ref"),
                        voice_style=vstyle,
                    )
                self._set_progress(stage="video", progress=100, message="動畫完成")
        except Exception:
            free_pipe()
            self._free_vision()
            raise

        if is_story:
            motion_clip_name = meta_motion_clip(meta)
            plot = dict(meta.get("story_plot") or {})
            plot["motion_clip"] = motion_clip_name
            meta["story_plot"] = plot
            meta["motion_clip"] = motion_clip_name
        saved_motion = motion
        saved_i2v = i2v_prompt if i2v_prompt is not None else (meta.get("i2v_prompt") or "")
        if is_story and making_video and clip_mode in {"i2v", "i2v_clone"}:
            saved_i2v = motion
            kept = motion_prompt if motion_prompt is not None else meta.get("motion_prompt")
            saved_motion = kept or ""
        elif is_story and making_video:
            saved_motion = motion
        saved_mode = (
            clip_mode if (mode_given or making_video)
            else self._normalize_clip_mode(meta.get("clip_mode") or "r2v")
        )
        meta.update({
            "still_prompt": still,
            "visual_prompt": visual_text,
            "partner_prompt": partner_text,
            "scene_prompt": scene_text,
            "motion_prompt": saved_motion,
            "i2v_prompt": saved_i2v,
            "image_backend": backend,
            "diffusers_model": model_key,
            "diffusers_model_label": model_label,
            "video_model": vkey,
            "video_model_label": vlabel,
            "turbo_steps": turbo_steps,
            "seed": seed,
            "voice": use_voice,
            "language": lang,
            "voice_style": vstyle,
            "dialogue": spoken,
            "clip_mode": saved_mode,
            "voice_ref": (voice_ref or meta.get("voice_ref") or ""),
            "voice_cloned": (dest / "voice_clone.wav").is_file(),
        })
        if is_story:
            meta["story_link"] = story_link
            if use_r2v:
                meta["story_mode"] = "r2v"
                if (dest / "partner.png").is_file():
                    meta["partner_ref"] = "partner.png"
                if (dest / "scene.png").is_file():
                    meta["scene_ref"] = "scene.png"
        if redo_frame and i2i and not redo_video:
            meta["kind"] = "still"
            meta["animation"] = None
            meta["last_frame"] = None
        if redo_video:
            meta["kind"] = "clip"
            meta["animation"] = "animation.mp4"
            meta["duration"] = duration
            meta["main_duration"] = main_duration
            meta["climax"] = bool(use_climax)
            meta["climax_seconds"] = climax_secs if climax_motion else 0
            meta["climax_motion"] = climax_motion
            meta["last_frame"] = last_frame_name
            self._clear_extend_files(dest)
            meta.pop("extend_pending", None)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"  完成 → {dest}")
        return meta

    # ---- resolve ----

    def _english_motion_on(self, override: bool | None) -> bool:
        if override is not None:
            return bool(override)
        return bool((self.cfg.get("video") or {}).get("english_motion", True))

    def _finalize_motion(
        self,
        motion: str,
        *,
        video_model: str | None,
        spoken: str = "",
        lang: str = "ja",
        tone: str = "",
        use_en: bool = True,
        action: str = "",
        tags: str = "",
        nsfw: bool = True,
        static_camera: bool = True,
        voice_style: str | None = None,
    ) -> str:
        if video_is_h3(self.cfg, video_model):
            desc = tone
            if not desc or re.search(r"[\u3000-\u9fff]", desc):
                desc = h3_speaker_desc(voice_style)
            return wrap_h3_i2va(
                motion,
                dialogue=spoken,
                language=lang,
                tone=desc,
                nsfw=nsfw,
                action=action,
                action_tags=tags,
                static_camera=static_camera,
            )
        if spoken and spoken not in (motion or ""):
            from .voice import attach_voice
            motion = attach_voice(
                motion, spoken, language=lang, tone=tone, english=use_en)
        if use_en:
            motion = lock_camera_en(motion)
        return motion

    def _climax_on(self, override: bool | None) -> bool:
        if override is not None:
            return bool(override)
        return bool((self.cfg.get("video") or {}).get("climax", False))

    def _extend_seconds(self, override: int | None, vinfo: dict) -> int:
        if override is not None:
            n = int(override)
        else:
            n = int((self.cfg.get("video") or {}).get("extend_seconds") or 6)
        if n <= 0:
            return 0
        vmin = int(vinfo.get("duration_min") or self.cfg["video"]["duration_min"])
        vmax = int(vinfo.get("duration_max") or self.cfg["video"]["duration_max"])
        return max(vmin, min(vmax, n))

    def _extend_mode(self, override: str | None, rng: random.Random | None = None) -> str:
        key = (override or (self.cfg.get("video") or {}).get("extend_mode") or "auto")
        key = str(key).strip().lower()
        if key in {"similar", "tweak", "rhythm"}:
            return key
        rng = rng or random.Random()
        return rng.choice(["similar", "tweak", "rhythm"])

    def _extend_paths(self, dest: Path) -> tuple[Path, Path]:
        return dest / "animation.mp4", dest / "animation_extend.mp4"

    def _clear_extend_files(self, dest: Path) -> None:
        (_, ext_path) = self._extend_paths(dest)
        ext_path.unlink(missing_ok=True)
        (dest / "_joined.mp4").unlink(missing_ok=True)
        (dest / "_animation_old.mp4").unlink(missing_ok=True)

    def _write_clip_meta(self, dest: Path, meta: dict) -> None:
        (dest / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def extend_clip(
        self,
        folder: str,
        *,
        seconds: int | None = None,
        mode: str | None = None,
        climax: bool | None = None,
        climax_seconds: int | None = None,
        climax_motion: str | None = None,
        video_model: str | None = None,
        turbo_steps: int | None = None,
        seed: int | None = None,
    ) -> dict:
        dest = output_dir(self.cfg) / folder
        meta_path = dest / "meta.json"
        if not dest.is_dir() or not meta_path.exists():
            raise FileNotFoundError(f"找不到動畫或 meta.json: {folder}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        video_path, ext_path = self._extend_paths(dest)
        if not video_path.is_file():
            raise FileNotFoundError("沒有動畫可加長，請先產生動畫")
        vkey, vlabel, vinfo = self._video_info(video_model or meta.get("video_model"))
        turbo_steps = self._turbo_steps(vkey, turbo_steps, meta)
        extend_secs = self._extend_seconds(seconds, vinfo)
        if not extend_secs:
            raise ValueError("加長秒數無效")
        rng = random.Random(seed if seed is not None else meta.get("seed"))
        ext_mode = self._extend_mode(mode, rng)
        use_climax = bool(climax)
        climax_secs = 0
        clip_secs = extend_secs
        if use_climax:
            clip_secs, climax_secs = self._climax_budget(
                extend_secs, vinfo, climax_seconds)
            if not climax_secs:
                use_climax = False
                clip_secs = extend_secs
        act_name = meta.get("action") or ""
        act_tags = meta.get("action_tags") or ""
        extra = meta.get("extra") or ""
        look = meta.get("still_prompt") or ""
        nsfw = bool(meta.get("nsfw", True))
        lang = voice_language(self.cfg, meta.get("language"))
        vstyle = resolve_voice_style(self.cfg, meta.get("voice_style"))
        n = int(meta.get("extend_count") or 0)
        base_seed = seed if seed is not None else meta.get("seed")
        ext_seed = (int(base_seed) + 17 * (n + 1)) if base_seed is not None else None
        last = dest / "last_frame.png"
        motion = compose_extend_motion(act_name, act_tags, ext_mode, clip_secs)
        shot = None
        if use_climax:
            motion, shot = self._attach_climax_shot(
                motion, act_name, act_tags, lang, climax_secs,
                custom=(climax_motion or "").strip() or None,
                voice_style=vstyle, video_model=vkey)
        total = clip_secs + (climax_secs if use_climax else 0)
        self.log(f"▶ 加長 {folder}")
        self.log(f"  圖生影: {vlabel}　{clip_secs}s（{ext_mode}）")
        if use_climax:
            self.log(f"  高潮 [Shot 2] {climax_secs}s，加長段總長 {total}s")
        try:
            if not self._extract_last_frame(video_path, last):
                raise RuntimeError("抽不到末幀，無法加長")
            self._free_comfy()
            if free_pipe():
                self.log(f"  已卸載 Diffusers，釋放 VRAM 給 {vlabel}")
            self._set_progress(stage="video", progress=None, message="生成加長段…")
            self._make_video(
                last, motion, ext_path, total, ext_seed,
                video_model=vkey, turbo_steps=turbo_steps,
                nsfw=nsfw, climax=use_climax, action=act_name, tags=act_tags,
                extra=extra, look=look)
            self._set_progress(stage="video", progress=100, message="加長段完成")
        except Exception:
            free_pipe()
            self._free_vision()
            raise
        pending = {
            "file": ext_path.name,
            "seconds": clip_secs,
            "mode": ext_mode,
            "climax": bool(use_climax),
            "climax_seconds": climax_secs if use_climax else 0,
            "climax_motion": shot,
            "motion": motion,
            "duration": total,
            "seed": ext_seed,
        }
        meta["extend_pending"] = pending
        meta["last_frame"] = last.name
        meta["video_model"] = vkey
        meta["video_model_label"] = vlabel
        meta["turbo_steps"] = turbo_steps
        self._write_clip_meta(dest, meta)
        self.log(f"  加長段未合併 → {ext_path.name}")
        return meta

    def commit_extend(self, folder: str) -> dict:
        dest = output_dir(self.cfg) / folder
        meta_path = dest / "meta.json"
        if not dest.is_dir() or not meta_path.exists():
            raise FileNotFoundError(f"找不到動畫或 meta.json: {folder}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        pending = meta.get("extend_pending") or {}
        video_path, ext_path = self._extend_paths(dest)
        if not pending or not ext_path.is_file():
            raise FileNotFoundError("沒有未合併的加長段")
        if not video_path.is_file():
            raise FileNotFoundError("沒有動畫可合併")
        joined = dest / "_joined.mp4"
        self.log(f"▶ 合併加長段 {folder}")
        if not self._concat_many([video_path, ext_path], joined):
            raise RuntimeError("合併失敗")
        backup = dest / "_animation_old.mp4"
        shutil.move(video_path, backup)
        try:
            shutil.move(joined, video_path)
        except Exception:
            if backup.exists() and not video_path.exists():
                shutil.move(backup, video_path)
            raise
        backup.unlink(missing_ok=True)
        ext_path.unlink(missing_ok=True)
        last = dest / "last_frame.png"
        if self._extract_last_frame(video_path, last):
            meta["last_frame"] = last.name
        added = int(pending.get("duration") or pending.get("seconds") or 0)
        meta["duration"] = int(meta.get("duration") or 0) + added
        hist = list(meta.get("extends") or [])
        hist.append({
            "seconds": pending.get("seconds"),
            "mode": pending.get("mode"),
            "climax": bool(pending.get("climax")),
            "climax_seconds": pending.get("climax_seconds") or 0,
            "duration": pending.get("duration") or added,
        })
        meta["extends"] = hist
        meta["extend_count"] = len(hist)
        meta.pop("extend_pending", None)
        self._write_clip_meta(dest, meta)
        self.log(f"  已合併，總長 {meta['duration']}s")
        return meta

    def discard_extend(self, folder: str) -> dict:
        dest = output_dir(self.cfg) / folder
        meta_path = dest / "meta.json"
        if not dest.is_dir() or not meta_path.exists():
            raise FileNotFoundError(f"找不到動畫或 meta.json: {folder}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self._clear_extend_files(dest)
        meta.pop("extend_pending", None)
        self._write_clip_meta(dest, meta)
        self.log(f"  已刪除加長段 {folder}")
        return meta

    def _motion_from_frame(
        self, frame_path: Path, act_name: str, act_tags: str, extra: str,
        spoken: str, lang: str, tone: str, duration: int, seed: int | None,
        h3: bool = False, voice_style: str | None = None,
    ) -> str:
        self._set_progress(stage="frame", progress=100, message="Qwen-VL 看圖寫動作稿…")
        desc = h3_speaker_desc(voice_style) if h3 else tone
        try:
            para = ai_motion_from_image(
                self.cfg, frame_path,
                action=act_name, action_tags=act_tags, extra=extra,
                duration=duration, seed=seed)
            self.log("  英文動作稿: Qwen-VL 看圖")
            motion = compose_motion_prompt(
                "", act_name, act_tags, None, extra, para,
                dialogue=spoken, language=lang, tone=desc, english=True, h3=h3)
            return motion if h3 else lock_camera_en(motion)
        except OllamaError as e:
            self.log(f"  看圖動作稿失敗，用英文模板：{e}")
            motion = compose_motion_prompt(
                "", act_name, act_tags, None, extra, None,
                dialogue=spoken, language=lang, tone=desc, english=True, h3=h3)
            return motion if h3 else lock_camera_en(motion)

    def _climax_seconds(self, override: int | None = None) -> int:
        if override is not None:
            n = int(override)
        else:
            n = int((self.cfg.get("video") or {}).get("climax_seconds") or 0)
        if n <= 0:
            return 0
        vmax = int(self.cfg["video"]["duration_max"])
        return max(3, min(vmax, n))

    def _climax_budget(
        self, duration: int, vinfo: dict, climax_seconds: int | None = None,
    ) -> tuple[int, int]:
        """回傳 (主片秒數, 高潮秒數)，總長不超過該 i2v 上限。"""
        secs = self._climax_seconds(climax_seconds)
        if secs <= 0:
            return int(duration), 0
        vmax = int(vinfo.get("duration_max") or self.cfg["video"]["duration_max"])
        vmin = int(vinfo.get("duration_min") or self.cfg["video"]["duration_min"])
        main = int(duration)
        if main + secs > vmax:
            main = max(vmin, vmax - secs)
        secs = min(secs, max(0, vmax - main))
        if secs < 3:
            return int(duration), 0
        return main, secs

    def _attach_climax_shot(
        self, motion: str, act_name: str, act_tags: str, lang: str, secs: int,
        *, custom: str | None = None, voice_style: str | None = None,
        video_model: str | None = None,
    ) -> tuple[str, str | None]:
        if secs <= 0:
            return motion, None
        h3 = video_is_h3(self.cfg, video_model)
        shot = as_climax_shot(
            (custom or "").strip() or compose_climax_motion(
                act_name, action_tags=act_tags, language=lang,
                voice_style=voice_style, h3=h3, seconds=secs),
            seconds=secs)
        return inject_climax_shot(motion, shot, seconds=secs), shot

    def _apply_voxcpm_voice(
        self, dest: Path, video_path: Path, *,
        spoken: str, voice_ref: str | None, voice_style: str | None,
    ) -> None:
        if not video_path.is_file():
            return
        vc = self.cfg.get("voice") or {}
        if str(vc.get("clone") or "voxcpm").strip().lower() in {"", "none", "off", "0", "false"}:
            return
        spoken = (spoken or "").strip().strip("「」『』\"'")
        if not spoken:
            self.log("  這段沒有對白，略過聲線克隆")
            return
        root = self.cfg.get("_root")
        item = resolve_clone_ref(voice_ref, voice_style, root)
        ref = voice_ref_path(item, root)
        if not ref:
            self.log("  找不到角色參考音，略過 VoxCPM 克隆")
            return
        clone_wav = dest / "voice_clone.wav"
        model_id = (vc.get("voxcpm_model") or "openbmb/VoxCPM2").strip()
        self.log(f"  VoxCPM 克隆聲線（{item.get('label') or item.get('id') or ref.stem}）")
        try:
            clone_dialogue(
                spoken, ref, clone_wav,
                model_id=model_id,
                prompt_text=(item.get("text") or "") if item else "",
                ffmpeg=self._ffmpeg(),
            )
        except VoxCPMError as e:
            self.log(f"  VoxCPM 克隆失敗：{e}")
            return
        except Exception as e:
            self.log(f"  VoxCPM 克隆失敗：{e}")
            return
        if self._mix_clone_onto_video(video_path, clone_wav, video_path):
            self.log("  已把克隆聲線疊上 I2V 音軌")
            try:
                meta_path = dest / "meta.json"
                if meta_path.is_file():
                    blob = json.loads(meta_path.read_text(encoding="utf-8"))
                    blob["voice_cloned"] = True
                    blob["voice_clone"] = clone_wav.name
                    blob["voice_ref"] = (item.get("id") if item else "") or (voice_ref or "")
                    meta_path.write_text(
                        json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
            except (OSError, json.JSONDecodeError):
                pass
        else:
            self.log("  疊聲線失敗，沿用原片音軌")

    def _has_audio(self, path: Path) -> bool:
        exe = shutil.which("ffprobe")
        if exe:
            r = subprocess.run(
                [exe, "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True)
            return bool((r.stdout or "").strip())
        ffmpeg = self._ffmpeg()
        if not ffmpeg:
            return True
        r = subprocess.run(
            [ffmpeg, "-i", str(path)], capture_output=True, text=True)
        return "Audio:" in (r.stderr or "")

    def _mix_clone_onto_video(self, video_src: Path, voice_wav: Path, out: Path) -> bool:
        exe = self._ffmpeg()
        if not exe:
            self.log("  找不到 ffmpeg，無法疊聲線")
            return False
        tmp = out.parent / "_voice_mix.mp4"
        if self._has_audio(video_src):
            fc = (
                "[0:a]volume=0.35[bg];"
                "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,apad[fg];"
                "[bg][fg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
            )
        else:
            fc = "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,apad[a]"
        cmd = [
            exe, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_src), "-i", str(voice_wav),
            "-filter_complex", fc,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-ar", "32000", "-ac", "2",
            "-shortest", "-movflags", "+faststart", str(tmp),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not tmp.is_file() or tmp.stat().st_size <= 0:
            self.log(f"  疊聲線失敗：{(r.stderr or '')[-300:]}")
            tmp.unlink(missing_ok=True)
            return False
        shutil.move(str(tmp), str(out))
        return True

    def _ffmpeg(self) -> str | None:
        return shutil.which("ffmpeg")

    def _copy_ref_audio(self, video: Path, ref: Path) -> None:
        """用參考片音軌換掉成片聲音。成片比參考片長就裁到一樣，較短就只接到成片結尾。"""
        exe = self._ffmpeg()
        if not exe:
            self.log("  找不到 ffmpeg，無法複製參考音軌")
            return
        if not video.is_file() or not ref.is_file():
            return
        ref_secs = probe_duration(ref)
        vid_secs = probe_duration(video)
        if not ref_secs:
            self.log("  參考片沒有可讀的長度，保留生成的聲音")
            return
        target = ref_secs
        if vid_secs and vid_secs + 0.05 < ref_secs:
            target = vid_secs
            self.log(
                f"  成片 {vid_secs:.2f}s 短於參考片 {ref_secs:.2f}s，音軌裁到成片結尾"
            )
        else:
            self.log(f"  複製參考音軌，長度 {target:.2f}s")
        tmp = video.with_name("_refaudio.mp4")
        cmd = [
            exe, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-i", str(ref),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-t", f"{target:.3f}",
            "-movflags", "+faststart", str(tmp),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size <= 0:
            cmd = [
                exe, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(video), "-i", str(ref),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "32000", "-ac", "2",
                "-t", f"{target:.3f}",
                "-movflags", "+faststart", str(tmp),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size <= 0:
            self.log(f"  複製音軌失敗：{(proc.stderr or '')[-300:]}")
            tmp.unlink(missing_ok=True)
            return
        shutil.move(str(tmp), str(video))

    def _extract_last_frame(self, video_path: Path, out_png: Path) -> bool:
        exe = self._ffmpeg()
        if not exe:
            self.log("  找不到 ffmpeg，無法抽末幀")
            return False
        cmd = [
            exe, "-y", "-hide_banner", "-loglevel", "error",
            "-sseof", "-0.2", "-i", str(video_path),
            "-frames:v", "1", "-q:v", "2", str(out_png),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = r.returncode == 0 and out_png.exists() and out_png.stat().st_size > 0
        if not ok:
            self.log(f"  抽末幀失敗：{(r.stderr or r.stdout or '')[-300:]}")
        return ok

    def _extract_tail_video(self, src: Path, out: Path, seconds: float = 3.0) -> bool:
        exe = self._ffmpeg()
        if not exe or not src.is_file():
            return False
        cmd = [
            exe, "-y", "-hide_banner", "-loglevel", "error",
            "-sseof", f"-{float(seconds)}", "-i", str(src),
            "-an", "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = r.returncode == 0 and out.exists() and out.stat().st_size > 0
        if not ok:
            self.log(f"  擷取上一段影片失敗：{(r.stderr or r.stdout or '')[-300:]}")
        return ok

    def _concat_many(self, clips: list[Path], out: Path) -> bool:
        exe = self._ffmpeg()
        if not exe or len(clips) < 2:
            if not exe:
                self.log("  找不到 ffmpeg，無法合併")
            return False
        lst = out.parent / "_concat.txt"
        lines = []
        for p in clips:
            path = p.resolve().as_posix().replace("'", r"'\''")
            lines.append(f"file '{path}'")
        lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [
            exe, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac", "-ar", "32000", "-ac", "2",
            "-movflags", "+faststart", str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        lst.unlink(missing_ok=True)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return True
        n = len(clips)
        inputs: list[str] = []
        for p in clips:
            inputs.extend(["-i", str(p)])
        vchain = "".join(f"[{i}:v]" for i in range(n))
        cmd = [
            exe, "-y", "-hide_banner", "-loglevel", "error",
            *inputs,
            "-filter_complex", f"{vchain}concat=n={n}:v=1:a=0[v]",
            "-map", "[v]", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-r", "24", "-movflags", "+faststart", str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            self.log(f"  合併失敗：{(r.stderr or '')[-400:]}")
        return r.returncode == 0 and out.exists() and out.stat().st_size > 0

    def _build_motion(
        self,
        char_label: str,
        act_name: str,
        act_tags: str,
        theme: str | None,
        extra: str,
        *,
        ai_motion: str | None,
        spoken: str,
        lang: str,
        tone: str,
        motion_prompt: str | None,
        use_en: bool,
        image_only: bool,
        duration: int,
        seed: int | None,
        skip_llm: bool = False,
        h3: bool = False,
        voice_style: str | None = None,
        scene: str | None = None,
    ) -> str:
        custom = (motion_prompt or "").strip()
        if custom:
            return custom
        paragraph = ai_motion
        if use_en:
            paragraph = None
            if not image_only and not skip_llm:
                try:
                    self._set_progress(
                        stage="frame", progress=0, message="Ollama 產英文動作稿…")
                    paragraph = ai_motion_paragraph(
                        self.cfg,
                        character=char_label,
                        action=act_name,
                        action_tags=act_tags,
                        theme=theme,
                        extra=extra,
                        duration=duration,
                        seed=seed,
                    )
                    self.log("  英文動作稿: Ollama")
                except OllamaError as e:
                    self.log(f"  英文動作稿失敗，改用英文模板：{e}")
        desc = h3_speaker_desc(voice_style) if h3 else tone
        return compose_motion_prompt(
            char_label, act_name, act_tags, theme, extra, paragraph,
            dialogue=spoken, language=lang, tone=desc,
            english=use_en, h3=h3, scene_key=scene)

    def _resolve_character(self, character, do_random, do_ai, theme, extra,
                           seed, rng) -> tuple[str, str, str]:
        if do_ai:
            data = ai_character(self.cfg, theme, extra, seed)
            self.log(f"  AI 角色: {data['name']}")
            return data["name"], data["prompt"], data["name"]
        if do_random or not character:
            c = self.catalog.random_character(rng)
            title = c["title"]
            self.log(f"  隨機角色: {self.catalog.display_name(title)}")
            return title, self.catalog.character_prompt(title), self.catalog.display_name(title)
        found = self.catalog.get_character(character)
        if found:
            title = found["title"]
            return title, self.catalog.character_prompt(title), self.catalog.display_name(title)
        # 使用者自訂描述當角色
        return character, character, character

    def _resolve_action(self, action, do_random, do_ai, theme, char_label, extra,
                        seed, rng) -> tuple[str, str, str | None, int | None]:
        if do_ai:
            data = ai_action(self.cfg, theme, char_label, extra, seed)
            self.log(f"  AI 動作: {data['name']}（{data['duration']}s）")
            return data["name"], data["tags"], data["motion"], data["duration"]
        if do_random or not action:
            name = self.catalog.random_action(rng)
            self.log(f"  隨機動作: {name}")
            return name, self.catalog.action_prompt(name), None, None
        if action in self.catalog.actions:
            return action, self.catalog.action_prompt(action), None, None
        return action, action, None, None

    def _resolve_dialogue(self, dialogue, action, character, theme, extra,
                          language, seed, rng, tags: str = "") -> tuple[str, str]:
        if dialogue and dialogue.strip():
            return dialogue.strip(), ""
        if voice_kind(action or "", tags or "") != "talk":
            return "", ""
        try:
            data = ai_dialogue(
                self.cfg, character=character or "", action=action or "",
                theme=theme, extra=extra, language=language, seed=seed)
            return data["dialogue"], data.get("tone") or ""
        except OllamaError as e:
            self.log(f"  AI 台詞失敗，改用詞庫：{e}")
            return fallback_dialogue(action, language, rng), ""

    def _folder_name(self, char_label: str, action: str, theme: str | None,
                     scene: str | None = None) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bits = [ts, slug(char_label, 24), slug(action, 20)]
        if theme:
            bits.append(slug(theme, 16))
        if scene:
            bits.append(slug(scene, 12))
        name = "_".join(bits)
        dest = output_dir(self.cfg) / name
        n = 2
        while dest.exists():
            dest = output_dir(self.cfg) / f"{name}_{n}"
            n += 1
        return dest.name

    # ---- backends ----

    def _free_comfy(self) -> None:
        if self.comfy.free_memory():
            self.log("  已卸載 ComfyUI 模型，釋放 VRAM")

    def _model_info(self, key: str | None) -> tuple[str, str, str]:
        return resolve_diffusers_model(self.cfg, key)

    def _video_info(self, key: str | None) -> tuple[str, str, dict]:
        info = resolve_video_model(self.cfg, key)
        return info["key"], info["label"], info

    def _turbo_steps(self, video_model: str | None, requested=None,
                     meta: dict | None = None) -> int | None:
        if not video_is_h3(self.cfg, video_model):
            return None
        if requested is not None:
            return h3_turbo_steps(requested)
        if meta and meta.get("turbo_steps") is not None:
            return h3_turbo_steps(meta.get("turbo_steps"))
        info = resolve_video_model(self.cfg, video_model)
        return h3_turbo_steps(info.get("turbo_steps"))

    def _free_vision(self) -> None:
        if free_vision(self.cfg):
            self.log("  已卸載 Ollama 看圖模型")

    @staticmethod
    def _existing_image(raw) -> Path | None:
        text = str(raw or "").strip()
        if not text:
            return None
        path = Path(text)
        return path if path.is_file() else None

    def generate_draft_card(
        self,
        *,
        kind: str,
        gender: str,
        prompt: str,
        theme: str,
        scene_text: str,
        out_path: Path,
        diffusers_model: str | None,
        nsfw: bool = True,
        quality: bool = True,
        seed: int | None = None,
    ) -> dict:
        """編輯模式：一張角色卡或場地卡的參考圖。"""
        backend = self.resolve_image_backend("diffusers")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "location":
            still = compose_scene_ref_prompt(
                self.cfg, scene_text, None, nsfw=nsfw, quality=quality)
            neg = negative_scene(self.cfg)
            label = "場地卡"
        elif gender == "male":
            still = compose_partner_ref_prompt(
                self.cfg, prompt, nsfw=nsfw, quality=quality,
                theme_key=theme or None)
            neg = negative_partner_sheet(self.cfg)
            label = "男角色卡"
        else:
            still = compose_character_ref_prompt(
                self.cfg, prompt, theme or None, nsfw=nsfw, quality=quality)
            neg = negative_ref_sheet(self.cfg)
            label = "女角色卡"
        self.log(f"  生成{label}")
        self._make_still(
            backend, still, out_path, seed, diffusers_model, negative=neg)
        return {"prompt": still, "path": str(out_path)}

    def _make_still(self, backend: str, prompt: str, out_path: Path,
                    seed: int | None, diffusers_model: str | None = None,
                    init_image: str | Path | None = None,
                    negative: str | None = None) -> Path:
        img = self.cfg["image"]
        w, h = img["width"], img["height"]
        neg = negative if negative is not None else negative_still(self.cfg)
        init_path = Path(init_image) if init_image else None
        if init_path and not init_path.is_file():
            init_path = None
        if init_path:
            self.log("  參考上一段生成首幀…")
        else:
            self.log("  生成首幀…")
        if backend == "mock":
            if init_path:
                shutil.copy2(init_path, out_path)
                return out_path
            return mock_image(prompt, out_path, w, h)
        if backend == "diffusers":
            try:
                _, label, path = self._model_info(diffusers_model)
                dcfg = dict(img["diffusers"])
                dcfg["model"] = path
                dcfg["sampler"] = img.get("sampler", "Euler a")
                self.log(f"  Diffusers 模型: {label}")
                lora = (dcfg.get("lora") or "").strip()
                if lora:
                    scale = dcfg.get("lora_scale")
                    scale = 1.0 if scale is None else scale
                    self.log(f"  LoRA: {Path(lora).name} ×{scale}")
                client = DiffusersClient(dcfg)

                def on_step(pct, step, total):
                    self._set_progress(
                        stage="frame", progress=pct,
                        message=f"生成首幀 {step}/{total}")

                if init_path:
                    strength = float(img.get("img2img_strength") or 0.58)
                    return client.img2img(
                        prompt, neg, init_path, out_path, w, h,
                        img["steps"], img["cfg"], strength, seed,
                        on_progress=on_step)
                return client.txt2img(
                    prompt, neg, out_path, w, h, img["steps"], img["cfg"], seed,
                    on_progress=on_step)
            except ImportError as e:
                raise DiffusersError(
                    "未安裝 diffusers。請 pip install -r requirements-diffusers.txt"
                ) from e
        if backend == "comfyui":
            if not self.comfy.ping():
                raise ComfyUIError(f"ComfyUI 未連上（{self.comfy.base_url}）")
            wf = build_image_workflow(self.cfg, prompt, w, h, seed,
                                      filename_prefix=f"anim/{out_path.parent.name}")
            files = self.comfy.run(wf, out_path.parent)
            pics = [p for p in files if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
            if not pics:
                raise ComfyUIError("ComfyUI 文生圖沒有圖片輸出")
            if pics[0] != out_path:
                shutil.copy2(pics[0], out_path)
            return out_path
        raise ValueError(f"未知首幀後端: {backend}")

    def _regen_story_ref(
        self, dest: Path, which: str, prompt: str, *,
        backend: str, seed: int | None, diffusers_model: str | None,
    ) -> None:
        names = {
            "visual": ("visual.png", "視覺圖"),
            "character": ("character.png", "女角色圖"),
            "partner": ("partner.png", "男角色圖"),
            "scene": ("scene.png", "場景圖"),
        }
        if which not in names:
            raise ValueError(f"未知參考圖: {which}")
        fname, label = names[which]
        path = dest / fname
        self.log(f"  重出{label}")
        self._set_progress(stage="frame", progress=0, message=f"生成{label}…")
        if which == "partner" and self._partner_should_use_default(dest, prompt):
            if self._copy_default_male(path):
                self.log(f"  男角色圖用預設參考圖（{default_male_image(self.cfg)}）")
                self._set_progress(stage="frame", progress=100, message=f"{label}完成")
                return
            self.log(f"  預設男圖不存在：{default_male_image(self.cfg)}，改為生圖")
        if which == "partner":
            sheet_neg = negative_partner_sheet(self.cfg)
        elif which == "character":
            sheet_neg = negative_ref_sheet(self.cfg)
        else:
            sheet_neg = None
        self._make_still(
            backend, prompt, path, seed, diffusers_model, negative=sheet_neg)
        if which == "visual":
            shutil.copy2(path, dest / "first_frame.png")
        if which == "partner":
            self._set_partner_from_default(dest, False)
        self._set_progress(stage="frame", progress=100, message=f"{label}完成")

    def _copy_default_male(self, dest: Path) -> bool:
        src = default_male_image(self.cfg)
        if not src.is_file():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return True

    def _set_partner_from_default(self, dest: Path, flag: bool) -> None:
        meta_path = dest / "meta.json"
        if not meta_path.exists():
            return
        try:
            blob = json.loads(meta_path.read_text(encoding="utf-8"))
            blob["partner_from_default"] = bool(flag)
            meta_path.write_text(
                json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass

    def _partner_should_use_default(self, dest: Path, prompt: str = "") -> bool:
        if not default_male_image(self.cfg).is_file():
            return False
        meta_path = dest / "meta.json"
        meta: dict = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        if (meta.get("male_custom") or "").strip():
            return False
        stored = (meta.get("partner_prompt") or "").strip()
        text = (prompt or "").strip()
        if text and stored and text != stored:
            return False
        return True

    def _extra_cast_meta(
        self, fem_slots: list[dict], mal_slots: list[dict], has_partner: bool,
    ) -> list[dict]:
        extras = []
        idx = 1 + (1 if has_partner else 0) + 1
        for slot in fem_slots[1:]:
            idx += 1
            extras.append({
                "pic": f"<Picture {idx}>",
                "gender": "female",
                "name": slot.get("label") or slot.get("title") or "",
            })
        if has_partner:
            for slot in mal_slots[1:]:
                idx += 1
                extras.append({
                    "pic": f"<Picture {idx}>",
                    "gender": "male",
                    "name": slot.get("label") or slot.get("title") or "",
                })
        return extras

    def _write_extra_cast_sheets(
        self, dest: Path, *, fem_slots: list[dict], mal_slots: list[dict],
        theme: str, male_theme: str, nude_on: bool, nsfw: bool, quality: bool,
        image_backend: str, diffusers_model: str | None, seed: int | None,
        reuse_char: bool, reuse_male: bool, prev_dir: Path | None,
    ) -> None:
        for i, slot in enumerate(fem_slots[1:], start=2):
            path = dest / f"character_{i}.png"
            prev = (prev_dir / f"character_{i}.png") if prev_dir else None
            ready = self._existing_image(slot.get("image"))
            if ready:
                shutil.copy2(ready, path)
                self.log(f"  女角{i}圖用角色卡")
                continue
            if reuse_char and prev and prev.is_file():
                shutil.copy2(prev, path)
                self.log(f"  女角{i}圖沿用（衣著未變）")
                continue
            slot_theme = slot.get("theme", None)
            use_theme = theme if slot_theme is None else (slot_theme or None)
            prompt = compose_character_ref_prompt(
                self.cfg, slot["prompt"], use_theme, nsfw=nsfw, quality=quality,
                nude=nude_on)
            self.log(f"  出女角{i}圖（{slot['label']}）")
            extra_seed = None if seed is None else int(seed) + 40 + i
            self._make_still(
                image_backend, prompt, path, extra_seed, diffusers_model,
                negative=negative_ref_sheet(self.cfg))
        for i, slot in enumerate(mal_slots[1:], start=2):
            path = dest / f"partner_{i}.png"
            prev = (prev_dir / f"partner_{i}.png") if prev_dir else None
            ready = self._existing_image(slot.get("image"))
            if ready:
                shutil.copy2(ready, path)
                self.log(f"  男角{i}圖用角色卡")
                continue
            if reuse_male and prev and prev.is_file():
                shutil.copy2(prev, path)
                self.log(f"  男角{i}圖沿用（衣著未變）")
                continue
            slot_theme = slot.get("theme", None)
            use_theme = male_theme if slot_theme is None else (slot_theme or None)
            prompt = compose_partner_ref_prompt(
                self.cfg, slot["prompt"], nsfw=nsfw, quality=quality,
                nude=nude_on, theme_key=use_theme or None)
            self.log(f"  出男角{i}圖（{slot['label']}）")
            extra_seed = None if seed is None else int(seed) + 70 + i
            self._make_still(
                image_backend, prompt, path, extra_seed, diffusers_model,
                negative=negative_partner_sheet(self.cfg))

    def _story_r2v_refs(self, dest: Path) -> list[Path]:
        char = dest / "character.png"
        partner = dest / "partner.png"
        scene = dest / "scene.png"
        refs = [char]
        if partner.is_file():
            refs.append(partner)
        refs.append(scene)
        _append_extra_cast_refs(refs, dest, partner.is_file())
        return refs

    def _story_r2v_identity_refs(self, dest: Path) -> tuple[list[Path], list[Path]]:
        """動作庫 R2V：三視圖改傳正面全身＋臉部特寫，避免影片人物蓋過身份。"""
        char = dest / "character.png"
        partner = dest / "partner.png"
        scene = dest / "scene.png"
        temps: list[Path] = []
        char_front = dest / "_id_char_front.png"
        char_face = dest / "_id_char_face.png"
        if crop_sheet_identity(char, char_front, char_face):
            refs = [char_front]
            temps.extend([char_front, char_face])
        else:
            refs = [char]
            char_face = None
        if partner.is_file():
            p_front = dest / "_id_partner_front.png"
            p_face = dest / "_id_partner_face.png"
            if crop_sheet_identity(partner, p_front, p_face):
                refs.append(p_front)
                temps.extend([p_front, p_face])
            else:
                refs.append(partner)
                p_face = None
        else:
            p_face = None
        refs.append(scene)
        _append_extra_cast_refs(refs, dest, partner.is_file())
        if char_face and char_face.is_file():
            refs.append(char_face)
        if p_face and p_face.is_file():
            refs.append(p_face)
        return refs, temps

    def _story_motion_clip_path(self, meta: dict) -> Path | None:
        beat = self._story_beat_from_meta(meta)
        name = beat.get("motion_clip") or ""
        if not name:
            return None
        path = resolve_motion_clip(name, self.cfg.get("_root") or "")
        if path:
            return path
        self.log(f"  動作參考找不到：data/{name}.mp4")
        return None

    def _make_r2v(self, refs: list[Path], motion: str,
                  out_path: Path, duration: int, seed: int | None,
                  video_model: str | None = None,
                  ref_video: Path | None = None,
                  ref_videos: list[Path] | None = None,
                  turbo_steps: int | None = None,
                  ref_image_size: str = "match",
                  nsfw: bool = False,
                  climax: bool = False,
                  action: str = "",
                  tags: str = "",
                  extra: str = "",
                  look: str = "") -> Path:
        model = resolve_video_model(self.cfg, video_model)
        if not model.get("r2v_workflow"):
            raise ComfyUIError(f"{model['label']} 沒有 r2v_workflow")
        if len(refs) < 2:
            raise ComfyUIError("R2V 需要角色圖與場景圖")
        missing = [str(p.name) for p in refs if not p.is_file()]
        if missing:
            raise FileNotFoundError("短篇 R2V 缺少：" + "、".join(missing))
        if not self.comfy.ping():
            raise ComfyUIError(
                f"ComfyUI 未連上（{self.comfy.base_url}），無法跑 {model['label']} R2V")
        name_zh = {
            "character.png": "女",
            "partner.png": "男",
            "scene.png": "場景",
            "visual.png": "姿勢",
            "_id_char_front.png": "女正面",
            "_id_char_face.png": "女臉",
            "_id_partner_front.png": "男正面",
            "_id_partner_face.png": "男臉",
        }
        labels = [name_zh.get(p.name, p.stem) for p in refs]
        steps = self._turbo_steps(model["key"], turbo_steps)
        fx = pick_h3_effect_loras(
            model, nsfw=nsfw, climax=climax, action=action, tags=tags,
            motion=motion, extra=extra, look=look)
        turbo_note = "　正常 20step" if steps == 0 else (f"　Turbo {steps}step" if steps else "")
        size_note = "　參考圖 max" if ref_image_size == "max" else ""
        self.log(f"  上傳參考圖並跑 {model['label']} R2V（{duration}s{turbo_note}{size_note}）…")
        if fx:
            self.log("  H3 LoRA: " + "　".join(
                f"{x['id']} {x['strength']}" for x in fx))
        uploaded = [
            self.comfy.upload_image(p, subfolder="anim_generator") for p in refs]
        self.log("  " + "　".join(f"{a} {b}" for a, b in zip(labels, uploaded)))
        clips = [Path(p) for p in (ref_videos or []) if p]
        if ref_video and Path(ref_video).is_file():
            p = Path(ref_video)
            if p not in clips:
                clips.insert(0, p)
        vid_up = []
        for p in clips:
            if not p.is_file():
                continue
            name = self.comfy.upload_image(p, subfolder="anim_generator")
            vid_up.append(name)
            self.log(f"  參考影片 {p.stem} → {name}")
        wf = build_r2v_workflow(
            self.cfg, uploaded, motion,
            model["width"], model["height"],
            duration, seed,
            filename_prefix=f"video/{out_path.parent.name}",
            video_model=model["key"],
            ref_videos=vid_up,
            turbo_steps=steps,
            ref_image_size=ref_image_size,
            effect_loras=fx)

        def on_wait(elapsed):
            self._set_progress(
                stage="video", progress=None, elapsed=elapsed,
                message=f"R2V 生成中… {int(elapsed)}s")

        files = self.comfy.run(wf, out_path.parent, on_progress=on_wait)
        vids = [p for p in files if p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]
        if not vids:
            raise ComfyUIError(f"{model['label']} R2V 完成但找不到影片")
        if vids[0] != out_path:
            shutil.move(vids[0], out_path)
        return out_path

    def _make_video(self, frame_path: Path, motion: str, out_path: Path,
                    duration: int, seed: int | None,
                    video_model: str | None = None,
                    turbo_steps: int | None = None,
                    nsfw: bool = False,
                    climax: bool = False,
                    action: str = "",
                    tags: str = "",
                    extra: str = "",
                    look: str = "") -> Path:
        model = resolve_video_model(self.cfg, video_model)
        if has_legwear(action, tags, motion, extra, look):
            motion = lock_legwear(motion)
        if video_is_h3(self.cfg, model["key"]):
            motion = wrap_h3_i2va(
                motion, nsfw=nsfw, action=action, action_tags=tags)
        if not self.comfy.ping():
            raise ComfyUIError(
                f"ComfyUI 未連上（{self.comfy.base_url}），無法跑 {model['label']}")
        steps = self._turbo_steps(model["key"], turbo_steps)
        fx = pick_h3_effect_loras(
            model, nsfw=nsfw, climax=climax, action=action, tags=tags,
            motion=motion, extra=extra, look=look)
        turbo_note = "　正常 20step" if steps == 0 else (f"　Turbo {steps}step" if steps else "")
        self.log(f"  上傳畫面並跑 {model['label']}（{duration}s{turbo_note}）…")
        if fx:
            self.log("  H3 LoRA: " + "　".join(
                f"{x['id']} {x['strength']}" for x in fx))
        uploaded = self.comfy.upload_image(frame_path, subfolder="anim_generator")
        self.log(f"  已上傳 {uploaded}")
        wf = build_i2v_workflow(
            self.cfg, uploaded, motion,
            model["width"], model["height"],
            duration, seed,
            filename_prefix=f"video/{out_path.parent.name}",
            video_model=model["key"],
            turbo_steps=steps,
            effect_loras=fx)

        def on_wait(elapsed):
            self._set_progress(
                stage="video", progress=None, elapsed=elapsed,
                message=f"生成動畫中… {int(elapsed)}s")

        files = self.comfy.run(wf, out_path.parent, on_progress=on_wait)
        vids = [p for p in files if p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]
        if not vids:
            raise ComfyUIError(f"{model['label']} workflow 完成但找不到影片")
        if vids[0] != out_path:
            shutil.move(vids[0], out_path)
        return out_path

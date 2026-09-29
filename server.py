"""MicroDramaGenerator 網頁伺服器。

啟動：python server.py  （本機與內網 http://<這台IP>:8620）
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from io import BytesIO
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from anim_creator.catalog import Catalog
from anim_creator.comfy_client import ComfyClient
from anim_creator.config import (
    load_config, output_dir, resolve_diffusers_model, diffusers_models,
    h3_turbo_steps, resolve_video_model, video_models,
)
from anim_creator.diffusers_client import free_pipe
from anim_creator.voxcpm_clone import free_voxcpm
from anim_creator.ollama_gen import (
    OllamaError, ai_story, apply_ollama_model, free_vision, list_ollama_models,
)
from anim_creator.pipeline import Pipeline
from anim_creator.stories import (
    card_image_key, card_theme_key, check_card_id, delete_draft,
    draft_cast_slots, draft_images_dir, draft_motion_file, draft_motions_dir,
    draft_joined_url, draft_preview, draft_segment_media, draft_to_story, get_story,
    list_drafts, list_motion_clips, list_stories, list_video_refs, load_draft,
    location_prompt_text, meta_motion_clip, resolve_motion_clip,
    save_draft, save_story,
)
from anim_creator.themes import male_theme_labels, scene_groups, scene_labels, theme_labels
from anim_creator.voice import list_voices, list_voice_refs

app = FastAPI(title="MicroDramaGenerator")
cfg = load_config()
OUT = output_dir(cfg)
print("載入 Danbooru 角色清單…")
catalog = Catalog(cfg)
n_f = sum(1 for c in catalog.characters if c.get("gender") == "female")
n_m = sum(1 for c in catalog.characters if c.get("gender") == "male")
print(f"  女 {n_f}、男 {n_m}、共 {len(catalog.characters)}")

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
_gpu_lock = threading.Lock()


def _release_gpu(*, interrupt: bool = False) -> None:
    try:
        free_pipe()
    except Exception:
        pass
    try:
        free_voxcpm()
    except Exception:
        pass
    try:
        free_vision(cfg)
    except Exception:
        pass
    try:
        url = (cfg.get("comfyui") or {}).get("url") or "http://127.0.0.1:8188"
        client = ComfyClient(url)
        if interrupt:
            client.interrupt()
        client.free_memory()
    except Exception:
        pass


class StoryInventRequest(BaseModel):
    female: str
    male: str = ""
    premise: str = ""
    nsfw: bool = True
    seed: int | None = None
    ollama_model: str | None = None


class CastSlot(BaseModel):
    character: str = ""
    voice_ref: str = ""
    prompt: str = ""
    theme: str | None = None
    image: str = ""


class StoryStillsRequest(BaseModel):
    story_id: str
    character: str = ""
    theme: str = ""
    male_theme: str = ""
    male: str = ""
    females: list[CastSlot] = []
    males: list[CastSlot] = []
    extra: str = ""
    seed: int | None = None
    nsfw: bool = True
    quality: bool = True
    image_backend: str | None = None
    diffusers_model: str | None = None
    ollama_model: str | None = None
    voice_style: str | None = None
    language: str | None = None
    story_mode: str = "r2v"


class StoryAnimateRequest(BaseModel):
    set_index: int = Field(1, ge=1, le=5)
    image_backend: str | None = None
    diffusers_model: str | None = None
    video_model: str | None = None
    voice: bool = True
    language: str = "zh"
    voice_style: str | None = None
    ollama_model: str | None = None
    story_link: str | None = None
    turbo_steps: int | None = Field(None, ge=0, le=20)
    clip_mode: str = "r2v"
    voice_ref: str | None = None
    clip_modes: dict[str, str] = Field(default_factory=dict)
    clip_motions: dict[str, str] = Field(default_factory=dict)


class StoryConcatRequest(BaseModel):
    set_index: int = Field(1, ge=1, le=5)


class StoryCopyRequest(BaseModel):
    character: str
    voice_style: str | None = None
    seed: int | None = None
    nsfw: bool = True
    quality: bool = True
    image_backend: str | None = None
    diffusers_model: str | None = None
    ollama_model: str | None = None


class RegenerateRequest(BaseModel):
    still_prompt: str | None = None
    motion_prompt: str | None = None
    i2v_prompt: str | None = None
    partner_prompt: str | None = None
    scene_prompt: str | None = None
    visual_prompt: str | None = None
    dialogue: str | None = None
    voice: bool | None = None
    language: str | None = None
    voice_style: str | None = None
    redo: str = "both"
    image_backend: str | None = None
    diffusers_model: str | None = None
    video_model: str | None = None
    seed: int | None = None
    duration: int | None = None
    ollama_model: str | None = None
    story_link: str | None = None
    turbo_steps: int | None = Field(None, ge=0, le=20)
    motion_clip: str | None = None
    clip_mode: str | None = None
    voice_ref: str | None = None


def _clip_dir(name: str) -> Path:
    d = (OUT / name).resolve()
    if not str(d).startswith(str(OUT.resolve())) or d == OUT.resolve():
        raise HTTPException(400, "非法名稱")
    if not d.is_dir():
        raise HTTPException(404, f"不存在: {name}")
    return d


def _llm_cfg(model: str | None = None) -> dict:
    return apply_ollama_model(cfg, model)


def _run_job(job_id: str, fn):
    job = jobs[job_id]

    def log(msg):
        with jobs_lock:
            job["log"].append(str(msg))

    def progress(**kw):
        with jobs_lock:
            job.update(kw)

    with jobs_lock:
        job["message"] = "排隊等待 GPU…"
    failed = False
    with _gpu_lock:
        try:
            pipe = Pipeline(cfg, catalog, log=log, progress=progress)
            results = fn(pipe)
            with jobs_lock:
                job["status"] = "done"
                job["progress"] = 100
                job["message"] = "完成"
                job["results"] = results
        except Exception as e:
            failed = True
            with jobs_lock:
                job["status"] = "error"
                job["error"] = str(e)
                job["message"] = str(e)
                job["log"].append(traceback.format_exc()[-3000:])
        finally:
            _release_gpu(interrupt=failed)


def _hydrate_sequence(info: dict) -> dict:
    for s in info.get("sets") or []:
        for c in s.get("clips") or []:
            folder = c.get("folder") or ""
            d = OUT / folder
            clip_info = {}
            meta_path = d / "meta.json"
            if meta_path.exists():
                try:
                    clip_info = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    clip_info = {}
            frame = d / "first_frame.png"
            video = d / "animation.mp4"
            c["info"] = clip_info
            c["exists"] = d.is_dir()
            last = d / "last_frame.png"
            c["has_video"] = video.exists()
            c["has_last"] = last.exists() or video.exists()
            c["thumb"] = (
                f"/output/{folder}/first_frame.png?v={int(frame.stat().st_mtime)}"
                if frame.exists() else ""
            )
            scene = d / "scene.png"
            c["scene"] = (
                f"/output/{folder}/scene.png?v={int(scene.stat().st_mtime)}"
                if scene.exists() else ""
            )
            partner = d / "partner.png"
            c["partner"] = (
                f"/output/{folder}/partner.png?v={int(partner.stat().st_mtime)}"
                if partner.exists() else ""
            )
            visual = d / "visual.png"
            c["visual"] = (
                f"/output/{folder}/visual.png?v={int(visual.stat().st_mtime)}"
                if visual.exists() else ""
            )
            char_ref = d / "character.png"
            c["character"] = (
                f"/output/{folder}/character.png?v={int(char_ref.stat().st_mtime)}"
                if char_ref.exists() else ""
            )
            c["video"] = (
                f"/output/{folder}/animation.mp4?v={int(video.stat().st_mtime)}"
                if video.exists() else ""
            )
            clip_motion = meta_motion_clip(
                clip_info,
                {
                    "title": c.get("title") or clip_info.get("story_beat") or "",
                    "story_id": clip_info.get("story_id") or info.get("story_id") or "",
                },
            )
            clip_info["motion_clip"] = clip_motion
            c["motion_clip"] = clip_motion
        joined = s.get("joined") or ""
        jp = OUT / info["id"] / joined if joined else None
        s["joined_url"] = (
            f"/output/{info['id']}/{joined}?v={int(jp.stat().st_mtime)}"
            if jp and jp.exists() else ""
        )
        s["ready"] = bool(s.get("clips")) and all(
            c.get("has_video") for c in s.get("clips") or []
        )
    return info


@app.get("/api/options")
def api_options():
    img = cfg["image"]
    models = {
        k: {"label": v.get("label") or k, "path": v.get("path", "")}
        for k, v in diffusers_models(cfg).items()
    }
    default_key = img.get("diffusers", {}).get("default") or next(iter(models), "")
    vmodels = {}
    for k in video_models(cfg):
        info = resolve_video_model(cfg, k)
        vmodels[k] = {
            "label": info["label"],
            "duration_max": info["duration_max"],
        }
    default_v = (cfg.get("video") or {}).get("default") or next(iter(vmodels), "minimax_h3")
    h3_info = resolve_video_model(cfg, default_v) if default_v else {}
    return {
        "themes": theme_labels(),
        "male_themes": male_theme_labels(),
        "stories": list_stories(cfg.get("_root")),
        "motion_clips": list_motion_clips(cfg.get("_root") or ""),
        "video_refs": list_video_refs(cfg.get("_root")),
        "character_count": len(catalog.characters),
        "female_count": n_f,
        "male_count": n_m,
        "image_backend": img.get("backend", "diffusers"),
        "diffusers_models": models,
        "diffusers_model": default_key,
        "video_models": vmodels,
        "video_model": default_v,
        "width": img["width"],
        "height": img["height"],
        "duration_min": cfg["video"]["duration_min"],
        "duration_max": cfg["video"]["duration_max"],
        "turbo_steps": h3_turbo_steps(
            (h3_info or {}).get("turbo_steps") or (cfg.get("video") or {}).get("turbo_steps")
        ),
        "nsfw": True,
        "quality": True,
        "voice": bool((cfg.get("voice") or {}).get("enabled", True)),
        "language": (cfg.get("voice") or {}).get("language") or "zh",
        "languages": {"ja": "日文", "zh": "中文", "en": "英文"},
        "voice_style": (cfg.get("voice") or {}).get("style") or "sweet",
        "voices": list_voices(),
        "voice_refs": list_voice_refs(cfg.get("_root")),
        "cast_max": 3,
        "series_female": catalog.list_series("female"),
        "series_male": catalog.list_series("male"),
        "scenes": scene_labels(),
        "scene_groups": scene_groups(),
        "ollama_model": cfg.get("ollama", {}).get("model") or "",
        "ollama_models": list_ollama_models(cfg),
    }


@app.get("/api/series")
def api_series(gender: str = ""):
    g = (gender or "").strip().lower()
    return {"series": catalog.list_series(g if g in {"female", "male", "ambiguous"} else None)}


@app.get("/api/characters")
def api_characters(q: str = "", gender: str = "", series: str = "", offset: int = 0, limit: int = 80):
    q = (q or "").strip().lower()
    g = (gender or "").strip().lower()
    series = (series or "").strip()
    items = catalog.list_characters(g if g in {"female", "male", "ambiguous"} else None)
    if series:
        items = [c for c in items if (c.get("series") or "其他") == series]
    if q:
        items = [
            c for c in items
            if q in c["title"].lower()
            or q in (c.get("zh") or "").lower()
            or q in (c.get("series") or "").lower()
        ]
    total = len(items)
    offset = max(0, offset)
    limit = max(1, min(400, limit))
    return {"total": total, "offset": offset, "items": items[offset:offset + limit]}


@app.get("/api/ollama/models")
def api_ollama_models():
    models = list_ollama_models(cfg)
    preferred = cfg.get("ollama", {}).get("model") or ""
    names = [m["name"] for m in models]
    current = preferred if preferred in names else (names[0] if names else preferred)
    return {"models": models, "current": current, "ok": bool(models)}


@app.get("/api/scripts")
def api_scripts():
    return {"stories": list_stories(cfg.get("_root"))}


@app.post("/api/story/invent")
def api_story_invent(req: StoryInventRequest):
    female = (req.female or "").strip()
    if not female:
        raise HTTPException(400, "請先選女角色")
    f = catalog.get_character(female)
    female_label = catalog.display_name(f["title"]) if f else female
    male = (req.male or "").strip()
    m = catalog.get_character(male) if male else None
    male_label = catalog.display_name(m["title"]) if m else male
    try:
        story = ai_story(
            _llm_cfg(req.ollama_model),
            female=female_label,
            male=male_label,
            premise=req.premise,
            nsfw=req.nsfw,
            seed=req.seed,
        )
    except OllamaError as e:
        raise HTTPException(400, str(e))
    saved = save_story(story, cfg.get("_root"))
    return {"story": get_story(saved["id"], cfg.get("_root")), "card": list_stories(cfg.get("_root"))}


@app.post("/api/story/stills")
def api_story_stills(req: StoryStillsRequest):
    if not (req.character or "").strip() and not any((s.character or "").strip() for s in req.females):
        raise HTTPException(400, "短劇至少選一名女角色")
    if not (req.story_id or "").strip():
        raise HTTPException(400, "請選一篇短劇")
    try:
        get_story(req.story_id.strip(), cfg.get("_root"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running", "log": [], "results": None, "error": None,
        "stage": "frame", "progress": 0, "message": "短劇參考圖排隊中…", "elapsed": 0,
    }
    threading.Thread(
        target=_run_job,
        args=(job_id, lambda pipe: pipe.generate_story_stills(
            story_id=req.story_id.strip(),
            character=req.character.strip(),
            theme=req.theme,
            male_theme=req.male_theme,
            male=req.male,
            females=[s.model_dump() for s in req.females],
            males=[s.model_dump() for s in req.males],
            extra=req.extra,
            seed=req.seed,
            nsfw=req.nsfw,
            quality=req.quality,
            image_backend=req.image_backend,
            diffusers_model=req.diffusers_model,
            ollama_model=req.ollama_model,
            voice_style=req.voice_style,
            language=req.language,
            story_mode=req.story_mode or "r2v",
        )),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/stories")
def api_stories():
    packs = []
    for d in sorted(OUT.iterdir(), reverse=True):
        p = d / "story.json"
        if not d.is_dir() or not p.exists():
            continue
        try:
            info = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        info.setdefault("id", d.name)
        story_id = str(info.get("story_id") or "")
        pack_name = str(info.get("id") or d.name)
        if info.get("editor") or story_id.startswith("edit_") or pack_name.startswith("editpack_"):
            continue
        packs.append(_hydrate_sequence(info))
    return {"stories": packs}


def _apply_clip_motions(pack_id: str, motions: dict[str, str]) -> None:
    """把編輯模式選的參考動畫寫進已有參考圖的 meta，不必重出靜幀。"""
    if not motions:
        return
    pack = _clip_dir(pack_id)
    story_path = pack / "story.json"
    folders: set[str] = set()
    if story_path.is_file():
        try:
            story = json.loads(story_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            story = {}
        for group in story.get("sets") or []:
            for clip in group.get("clips") or []:
                name = str(clip.get("folder") or "")
                if name:
                    folders.add(name)
    root = cfg.get("_root") or ""
    for folder, raw in motions.items():
        if folders and folder not in folders:
            continue
        try:
            dest = _clip_dir(folder)
        except HTTPException:
            continue
        meta_path = dest / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        stem = Path(str(raw or "")).stem
        if stem and not resolve_motion_clip(stem, root):
            continue
        meta["motion_clip"] = stem
        plot = meta.get("story_plot") if isinstance(meta.get("story_plot"), dict) else {}
        plot["motion_clip"] = stem
        meta["story_plot"] = plot
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


@app.post("/api/stories/{pack_id}/animate")
def api_story_animate(pack_id: str, req: StoryAnimateRequest):
    _clip_dir(pack_id)
    _apply_clip_motions(pack_id, req.clip_motions or {})
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running", "log": [f"短劇產動畫 {pack_id}"],
        "results": None, "error": None, "clip": pack_id,
        "stage": "video", "progress": 0, "message": "開始產動畫…", "elapsed": 0,
    }
    threading.Thread(
        target=_run_job,
        args=(job_id, lambda pipe: pipe.animate_story_set(
            pack_id, req.set_index,
            image_backend=req.image_backend,
            diffusers_model=req.diffusers_model,
            video_model=req.video_model,
            voice=req.voice,
            language=req.language,
            voice_style=req.voice_style,
            english_motion=False,
            ollama_model=req.ollama_model,
            story_link=req.story_link,
            turbo_steps=req.turbo_steps,
            clip_mode=req.clip_mode,
            voice_ref=req.voice_ref,
            clip_modes=req.clip_modes or None,
        )),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.post("/api/stories/{pack_id}/copy")
def api_story_copy(pack_id: str, req: StoryCopyRequest):
    _clip_dir(pack_id)
    if not (req.character or "").strip():
        raise HTTPException(400, "請先選新女角色")
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running", "log": [f"複製短劇 {pack_id} → {req.character}"],
        "results": None, "error": None, "clip": pack_id,
        "stage": "frame", "progress": 0, "message": "複製短劇…", "elapsed": 0,
    }
    threading.Thread(
        target=_run_job,
        args=(job_id, lambda pipe: pipe.clone_story_stills(
            pack_id,
            character=req.character.strip(),
            voice_style=req.voice_style,
            seed=req.seed,
            nsfw=req.nsfw,
            quality=req.quality,
            image_backend=req.image_backend,
            diffusers_model=req.diffusers_model,
            ollama_model=req.ollama_model,
        )),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.post("/api/stories/{pack_id}/concat")
def api_story_concat(pack_id: str, req: StoryConcatRequest):
    _clip_dir(pack_id)
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running", "log": [f"合併短劇 {pack_id}"],
        "results": None, "error": None, "clip": pack_id,
        "stage": "video", "progress": None, "message": "合併中…", "elapsed": 0,
    }
    threading.Thread(
        target=_run_job,
        args=(job_id, lambda pipe: pipe.concat_story_set(pack_id, req.set_index)),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.delete("/api/stories/{pack_id}/clips/{folder}")
def api_story_delete_clip(pack_id: str, folder: str):
    _clip_dir(pack_id)
    try:
        pipe = Pipeline(cfg, catalog, log=lambda *_a, **_k: None)
        return pipe.remove_story_clip(pack_id, folder)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/stories/{pack_id}")
def api_story_delete(pack_id: str):
    dest = _clip_dir(pack_id)
    meta_path = dest / "story.json"
    folders = []
    if meta_path.exists():
        try:
            info = json.loads(meta_path.read_text(encoding="utf-8"))
            for s in info.get("sets") or []:
                for c in s.get("clips") or []:
                    if c.get("folder"):
                        folders.append(c["folder"])
        except (OSError, json.JSONDecodeError):
            pass
    shutil.rmtree(dest)
    for name in folders:
        d = OUT / name
        try:
            if d.is_dir() and str(d.resolve()).startswith(str(OUT.resolve())):
                shutil.rmtree(d)
        except OSError:
            pass
    return {"deleted": pack_id}


@app.post("/api/clips/{name}/regenerate")
def api_regenerate(name: str, req: RegenerateRequest):
    _clip_dir(name)
    if req.diffusers_model:
        try:
            resolve_diffusers_model(cfg, req.diffusers_model)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if req.video_model:
        try:
            resolve_video_model(cfg, req.video_model)
        except ValueError as e:
            raise HTTPException(400, str(e))
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running", "log": [f"重新生成 {name}"],
        "results": None, "error": None, "clip": name,
        "stage": req.redo, "progress": 0, "message": "開始重作…", "elapsed": 0,
    }
    threading.Thread(
        target=_run_job,
        args=(job_id, lambda pipe: pipe.regenerate(
            name,
            still_prompt=req.still_prompt,
            motion_prompt=req.motion_prompt,
            i2v_prompt=req.i2v_prompt,
            partner_prompt=req.partner_prompt,
            scene_prompt=req.scene_prompt,
            visual_prompt=req.visual_prompt,
            redo=req.redo,
            image_backend=req.image_backend,
            diffusers_model=req.diffusers_model,
            video_model=req.video_model,
            seed=req.seed,
            dialogue=req.dialogue,
            voice=req.voice,
            language=req.language,
            voice_style=req.voice_style,
            duration=req.duration,
            english_motion=False,
            ollama_model=req.ollama_model,
            story_link=req.story_link,
            turbo_steps=req.turbo_steps,
            motion_clip=req.motion_clip,
            clip_mode=req.clip_mode,
            voice_ref=req.voice_ref,
        )),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    with jobs_lock:
        return dict(job)


@app.get("/api/voice-refs")
def api_voice_refs():
    return list_voice_refs(cfg.get("_root"))


@app.get("/sounds/{gender}/{name}")
def api_sound_file(gender: str, name: str):
    if gender not in {"female", "male"}:
        raise HTTPException(404, "無此聲線")
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "非法檔名")
    path = Path(cfg.get("_root") or Path(__file__).parent) / "data" / "sounds" / gender / name
    if not path.is_file():
        raise HTTPException(404, f"找不到參考音: {gender}/{name}")
    suffix = path.suffix.lower()
    media = "audio/mpeg" if suffix == ".mp3" else "audio/wav"
    return FileResponse(path, media_type=media)


@app.get("/api/motion-clips/{name}")
def api_motion_clip_file(name: str):
    path = resolve_motion_clip(name, cfg.get("_root") or "")
    if not path:
        raise HTTPException(404, "找不到參考影片")
    return FileResponse(path, media_type="video/mp4")


class EditorStillsRequest(BaseModel):
    theme: str = ""
    male_theme: str = ""
    extra: str = ""
    seed: int | None = None
    nsfw: bool = True
    quality: bool = True
    image_backend: str | None = None
    diffusers_model: str | None = None
    ollama_model: str | None = None
    voice_style: str | None = None
    language: str | None = None


def _draft_or_400(draft_id: str) -> dict:
    try:
        return load_draft(draft_id, cfg.get("_root"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/drafts")
def api_drafts():
    root = cfg.get("_root")
    rows = list_drafts(root)
    for row in rows:
        try:
            full = load_draft(row["id"], root)
        except ValueError:
            row["preview"] = {"kind": "", "url": ""}
            continue
        row["preview"] = draft_preview(full, root, OUT)
    return {"drafts": rows}


@app.get("/api/drafts/{draft_id}")
def api_draft_get(draft_id: str):
    data = _draft_or_400(draft_id)
    data["media"] = draft_segment_media(data, OUT)
    data["joined_url"] = draft_joined_url(data, OUT)
    return data


@app.put("/api/drafts/{draft_id}")
def api_draft_put(draft_id: str, raw: dict = Body(...)):
    try:
        return save_draft(raw, cfg.get("_root"), draft_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/drafts/{draft_id}")
def api_draft_delete(draft_id: str):
    try:
        delete_draft(draft_id, cfg.get("_root"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"deleted": draft_id}


@app.post("/api/drafts/{draft_id}/stills")
def api_draft_stills(draft_id: str, req: EditorStillsRequest):
    draft = _draft_or_400(draft_id)
    try:
        story = draft_to_story(draft, cfg.get("_root"))
        females, males = draft_cast_slots(draft, cfg.get("_root"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not females:
        raise HTTPException(400, "請至少一張女角色卡")
    saved = save_story(story, cfg.get("_root"))
    draft["story_id"] = saved["id"]
    save_draft(draft, cfg.get("_root"), draft_id)
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running", "log": [], "results": None, "error": None,
        "stage": "frame", "progress": 0, "message": "短劇參考圖排隊中…", "elapsed": 0,
    }
    fem = [CastSlot(**s).model_dump() for s in females]
    mal = [CastSlot(**s).model_dump() for s in males]
    threading.Thread(
        target=_run_job,
        args=(job_id, lambda pipe, sid=saved["id"], fem=fem, mal=mal: pipe.generate_story_stills(
            story_id=sid,
            character=fem[0]["character"],
            theme=req.theme,
            male_theme=req.male_theme,
            male=mal[0]["character"] if mal else "",
            females=fem,
            males=mal,
            extra=req.extra,
            seed=req.seed,
            nsfw=req.nsfw,
            quality=req.quality,
            image_backend=req.image_backend,
            diffusers_model=req.diffusers_model,
            ollama_model=req.ollama_model,
            voice_style=req.voice_style,
            language=req.language,
            story_mode="r2v",
        )),
        daemon=True,
    ).start()
    return {"job_id": job_id, "story_id": saved["id"]}


class SegmentAnimateRequest(BaseModel):
    diffusers_model: str | None = None
    ollama_model: str | None = None
    language: str | None = None
    turbo_steps: int | None = None


@app.post("/api/drafts/{draft_id}/segments/{seg_id}/animate")
def api_draft_segment_animate(draft_id: str, seg_id: str, req: SegmentAnimateRequest):
    try:
        seg_id = check_card_id(seg_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    draft = _draft_or_400(draft_id)
    if not any(
        isinstance(s, dict) and str(s.get("id") or "") == seg_id
        for s in (draft.get("segments") or [])
    ):
        raise HTTPException(404, "找不到這個段落")
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running", "log": [], "results": None, "error": None,
        "stage": "frame", "progress": 0, "message": "段落動畫排隊中…", "elapsed": 0,
    }

    def work(pipe, draft_id=draft_id, seg_id=seg_id, req=req):
        fresh = load_draft(draft_id, cfg.get("_root"))
        result = pipe.render_editor_segment(
            fresh, seg_id,
            diffusers_model=req.diffusers_model,
            ollama_model=req.ollama_model,
            language=req.language,
            turbo_steps=req.turbo_steps,
        )
        saved = load_draft(draft_id, cfg.get("_root"))
        for seg in saved.get("segments") or []:
            if isinstance(seg, dict) and str(seg.get("id") or "") == seg_id:
                seg["folder"] = result["folder"]
        saved["pack_id"] = result["pack_id"]
        saved["joined"] = ""
        save_draft(saved, cfg.get("_root"), draft_id)
        return result

    threading.Thread(target=_run_job, args=(job_id, work), daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/drafts/{draft_id}/concat")
def api_draft_concat(draft_id: str):
    _draft_or_400(draft_id)
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running", "log": [f"合併段落 {draft_id}"],
        "results": None, "error": None,
        "stage": "video", "progress": None, "message": "合併段落…", "elapsed": 0,
    }

    def work(pipe, draft_id=draft_id):
        fresh = load_draft(draft_id, cfg.get("_root"))
        result = pipe.concat_editor_segments(fresh)
        saved = load_draft(draft_id, cfg.get("_root"))
        saved["joined"] = result["joined"]
        saved["pack_id"] = result["pack_id"]
        save_draft(saved, cfg.get("_root"), draft_id)
        return result

    threading.Thread(target=_run_job, args=(job_id, work), daemon=True).start()
    return {"job_id": job_id}


class CardImageRequest(BaseModel):
    diffusers_model: str | None = None
    nsfw: bool = True
    quality: bool = True
    seed: int | None = None


def _draft_card(draft: dict, card_id: str) -> tuple[str, dict | None]:
    for card in draft.get("characters") or []:
        if isinstance(card, dict) and str(card.get("id") or "") == card_id:
            return "character", card
    for card in draft.get("locations") or []:
        if isinstance(card, dict) and str(card.get("id") or "") == card_id:
            return "location", card
    return "", None


@app.post("/api/drafts/{draft_id}/cards/{card_id}/image")
def api_draft_card_image(draft_id: str, card_id: str, req: CardImageRequest):
    try:
        card_id = check_card_id(card_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    draft = _draft_or_400(draft_id)
    kind, card = _draft_card(draft, card_id)
    if not card:
        raise HTTPException(404, "找不到這張卡")
    gender = "female"
    prompt = ""
    theme = ""
    scene_text = ""
    if kind == "location":
        scene_text = location_prompt_text(card)
        if not scene_text:
            raise HTTPException(400, "請先選場地項目或填描述")
    else:
        gender = "male" if str(card.get("gender") or "").lower() == "male" else "female"
        title = str(card.get("title") or card.get("name") or "").strip()
        if not title:
            raise HTTPException(400, "這張角色卡沒有名稱")
        theme = card_theme_key(card)
        if str(card.get("kind") or "") == "custom" or not catalog.get_character(title):
            prompt = str(card.get("prompt") or "").strip() or title
        else:
            prompt = catalog.character_prompt(title)
        tag = "1boy" if gender == "male" else "1girl"
        if tag not in prompt.lower():
            prompt = tag + ", " + prompt
    snapshot = card_image_key(card, kind)
    out = draft_images_dir(draft_id, cfg.get("_root")) / f"{card_id}.png"
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running", "log": [], "results": None, "error": None,
        "stage": "frame", "progress": 0, "message": "卡片參考圖排隊中…", "elapsed": 0,
    }

    def work(pipe, out=out, kind=kind, gender=gender, prompt=prompt, theme=theme,
             scene_text=scene_text, snapshot=snapshot, card_id=card_id, draft_id=draft_id):
        pipe.generate_draft_card(
            kind=kind, gender=gender, prompt=prompt, theme=theme,
            scene_text=scene_text, out_path=out,
            diffusers_model=req.diffusers_model, nsfw=req.nsfw,
            quality=req.quality, seed=req.seed,
        )
        fresh = load_draft(draft_id, cfg.get("_root"))
        found = False
        for key in ("characters", "locations"):
            for item in fresh.get(key) or []:
                if isinstance(item, dict) and str(item.get("id") or "") == card_id:
                    item["image"] = f"images/{card_id}.png"
                    item["image_key"] = snapshot
                    item["image_source"] = "generated"
                    item["image_at"] = time.time()
                    found = True
        if found:
            save_draft(fresh, cfg.get("_root"), draft_id)
        return {"card_id": card_id, "kind": kind, "image": f"images/{card_id}.png"}

    threading.Thread(target=_run_job, args=(job_id, work), daemon=True).start()
    return {"job_id": job_id}


_MAX_CARD_IMAGE = 20 * 1024 * 1024
_MAX_MOTION = 120 * 1024 * 1024
_VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}


def _write_ref_mp4(data: bytes, suffix: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if suffix == ".mp4" and not ffmpeg:
        dest.write_bytes(data)
        return
    if not ffmpeg:
        raise HTTPException(400, "請上傳 mp4，或先安裝 ffmpeg 再傳其他格式")
    src = dest.parent / f"_up{uuid.uuid4().hex[:8]}{suffix}"
    src.write_bytes(data)
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", str(src), "-an", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)],
            capture_output=True,
        )
        if proc.returncode != 0 or not dest.is_file():
            err = (proc.stderr or b"")[-300:].decode("utf-8", "replace")
            raise HTTPException(400, "這支影片轉不成參考動畫。" + err)
    finally:
        src.unlink(missing_ok=True)


@app.post("/api/drafts/{draft_id}/cards/{card_id}/upload")
def api_draft_card_upload(draft_id: str, card_id: str, file: UploadFile = File(...)):
    try:
        card_id = check_card_id(card_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    draft = _draft_or_400(draft_id)
    kind, card = _draft_card(draft, card_id)
    if not card or kind not in {"character", "location"}:
        raise HTTPException(404, "找不到這張卡")
    data = file.file.read(_MAX_CARD_IMAGE + 1)
    if not data:
        raise HTTPException(400, "沒有圖片")
    if len(data) > _MAX_CARD_IMAGE:
        raise HTTPException(400, "圖片超過 20MB")
    try:
        im = Image.open(BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "這不是可以讀的圖片")
    if im.mode in {"RGBA", "LA"} or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    out = draft_images_dir(draft_id, cfg.get("_root"))
    out.mkdir(parents=True, exist_ok=True)
    im.save(out / f"{card_id}.png", "png")
    fresh = load_draft(draft_id, cfg.get("_root"))
    found = False
    for key in ("characters", "locations"):
        for item in fresh.get(key) or []:
            if isinstance(item, dict) and str(item.get("id") or "") == card_id:
                item["image"] = f"images/{card_id}.png"
                item["image_key"] = "upload"
                item["image_source"] = "upload"
                item["image_at"] = time.time()
                found = True
    if not found:
        raise HTTPException(404, "找不到這張卡")
    save_draft(fresh, cfg.get("_root"), draft_id)
    return {"card_id": card_id, "image": f"images/{card_id}.png"}


@app.post("/api/drafts/{draft_id}/motions")
def api_draft_motion_upload(draft_id: str, file: UploadFile = File(...)):
    _draft_or_400(draft_id)
    name = Path(file.filename or "參考動畫").name
    suffix = Path(name).suffix.lower()
    if suffix not in _VIDEO_EXT:
        raise HTTPException(400, "請上傳 mp4、webm 或 mov")
    data = file.file.read(_MAX_MOTION + 1)
    if not data:
        raise HTTPException(400, "沒有影片")
    if len(data) > _MAX_MOTION:
        raise HTTPException(400, "參考動畫超過 120MB")
    motion_id = "m" + uuid.uuid4().hex[:10]
    dest = draft_motions_dir(draft_id, cfg.get("_root")) / f"{motion_id}.mp4"
    _write_ref_mp4(data, suffix, dest)
    label = Path(name).stem.strip()[:40] or "參考動畫"
    fresh = load_draft(draft_id, cfg.get("_root"))
    motions = [m for m in (fresh.get("motions") or []) if isinstance(m, dict)]
    motions.append({
        "id": motion_id,
        "name": label,
        "file": f"motions/{motion_id}.mp4",
    })
    fresh["motions"] = motions
    save_draft(fresh, cfg.get("_root"), draft_id)
    return {"motion": fresh["motions"][-1]}


@app.delete("/api/drafts/{draft_id}/motions/{motion_id}")
def api_draft_motion_delete(draft_id: str, motion_id: str):
    try:
        motion_id = check_card_id(motion_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    fresh = _draft_or_400(draft_id)
    fresh["motions"] = [
        m for m in (fresh.get("motions") or [])
        if not (isinstance(m, dict) and str(m.get("id") or "") == motion_id)
    ]
    for seg in fresh.get("segments") or []:
        if isinstance(seg, dict) and str(seg.get("motionId") or "") == motion_id:
            seg["motionId"] = ""
    save_draft(fresh, cfg.get("_root"), draft_id)
    path = draft_motion_file(draft_id, motion_id, cfg.get("_root"))
    if path and path.is_file():
        path.unlink()
    return {"deleted": motion_id}


@app.get("/api/drafts/{draft_id}/motions/{name}")
def api_draft_motion_file(draft_id: str, name: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}\.mp4", name):
        raise HTTPException(400, "非法檔名")
    try:
        folder = draft_motions_dir(draft_id, cfg.get("_root")).resolve()
    except ValueError as e:
        raise HTTPException(400, str(e))
    path = (folder / name).resolve()
    if not str(path).startswith(str(folder)) or not path.is_file():
        raise HTTPException(404, "還沒有這支參考動畫")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/drafts/{draft_id}/images/{name}")
def api_draft_image(draft_id: str, name: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}\.png", name):
        raise HTTPException(400, "非法檔名")
    try:
        folder = draft_images_dir(draft_id, cfg.get("_root")).resolve()
    except ValueError as e:
        raise HTTPException(400, str(e))
    path = (folder / name).resolve()
    if not str(path).startswith(str(folder)) or not path.is_file():
        raise HTTPException(404, "還沒有這張圖")
    return FileResponse(path, media_type="image/png")


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "web" / "index.html")


app.mount("/output", StaticFiles(directory=str(OUT)), name="output")


def _lan_urls(port: int) -> list[str]:
    import socket
    urls = [f"http://127.0.0.1:{port}"]
    seen = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in seen and not ip.startswith("169.254."):
                seen.add(ip)
                urls.append(f"http://{ip}:{port}")
    except OSError:
        pass
    return urls


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    PORT = 8620
    print("內網也可連：")
    for u in _lan_urls(PORT):
        print(f"  {u}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)

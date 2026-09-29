"""載入 config.yaml。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | os.PathLike | None = None) -> dict:
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = str(PROJECT_ROOT)
    return cfg


def _resolve(cfg: dict, key: str) -> Path:
    p = Path(cfg["paths"][key])
    if not p.is_absolute():
        p = Path(cfg["_root"]) / p
    return p


def output_dir(cfg: dict) -> Path:
    p = _resolve(cfg, "output_dir")
    p.mkdir(parents=True, exist_ok=True)
    return p


def workflows_dir(cfg: dict) -> Path:
    return _resolve(cfg, "workflows_dir")


def cache_dir(cfg: dict) -> Path:
    p = _resolve(cfg, "cache_dir")
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_male_image(cfg: dict) -> Path:
    raw = ((cfg.get("story") or {}).get("default_male_image")
           or "data/default_male.png")
    p = Path(raw)
    if not p.is_absolute():
        p = Path(cfg["_root"]) / p
    return p


def wai_dir(cfg: dict) -> Path:
    raw = ((cfg.get("wai") or {}).get("dir") or "wai")
    p = Path(raw)
    if not p.is_absolute():
        p = Path(cfg.get("_root") or PROJECT_ROOT) / p
    return p


def stories_dir(cfg: dict) -> Path:
    raw = ((cfg.get("story") or {}).get("stories_dir") or "data/stories")
    p = Path(raw)
    if not p.is_absolute():
        p = Path(cfg.get("_root") or PROJECT_ROOT) / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def diffusers_models(cfg: dict) -> dict[str, dict]:
    return cfg.get("image", {}).get("diffusers", {}).get("models") or {}


def _resolve_model_path(cfg: dict, path: str) -> str:
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str((Path(cfg.get("_root") or PROJECT_ROOT) / p).resolve())


def resolve_diffusers_model(cfg: dict, key: str | None = None) -> tuple[str, str, str]:
    """回傳 (key, 顯示名, 模型路徑)。"""
    dcfg = cfg.get("image", {}).get("diffusers", {})
    models = dcfg.get("models") or {}
    chosen = (key or dcfg.get("default") or "").strip()
    if chosen in models:
        entry = models[chosen]
        return chosen, entry.get("label") or chosen, _resolve_model_path(cfg, entry["path"])
    if chosen and Path(chosen).exists():
        return Path(chosen).stem, Path(chosen).stem, chosen
    if models:
        keys = ", ".join(models)
        raise ValueError(f"未知 Diffusers 模型: {chosen or '(空)'}（可用: {keys}）")
    legacy = dcfg.get("model") or ""
    if legacy:
        return "default", Path(legacy).stem, legacy
    raise ValueError("config.yaml 未設定 image.diffusers.models")


def video_models(cfg: dict) -> dict[str, dict]:
    vid = cfg.get("video") or {}
    models = vid.get("models")
    if models:
        return models
    return {
        "ltx23": {
            "label": "LTX 2.3",
            "workflow": vid.get("workflow") or "video_ltx2_3_i2v.json",
            "checkpoint": vid.get("checkpoint"),
            "upscaler": vid.get("upscaler"),
        }
    }


def resolve_video_model(cfg: dict, key: str | None = None) -> dict:
    """合併 video.models[key] 與 video 共用欄位。"""
    vid = cfg.get("video") or {}
    models = video_models(cfg)
    chosen = (key or vid.get("default") or "").strip()
    if chosen not in models:
        if chosen:
            keys = ", ".join(models)
            raise ValueError(f"未知圖生影模型: {chosen}（可用: {keys}）")
        chosen = next(iter(models))
    entry = models.get(chosen) or {}
    duration_min = int(vid.get("duration_min") or 3)
    duration_max = int(entry.get("duration_max") or vid.get("duration_max") or 30)
    if duration_max < duration_min:
        duration_max = duration_min
    return {
        "key": chosen,
        "label": entry.get("label") or chosen,
        "workflow": entry.get("workflow") or vid.get("workflow") or "video_ltx2_3_i2v.json",
        "checkpoint": entry.get("checkpoint") or vid.get("checkpoint") or "",
        "lora": entry.get("lora") or vid.get("lora") or "",
        "upscaler": entry.get("upscaler") or vid.get("upscaler") or "",
        "unet": entry.get("unet") or "",
        "clip": entry.get("clip") or "",
        "video_vae": entry.get("video_vae") or "",
        "audio_vae": entry.get("audio_vae") or "",
        "aspect_ratio": entry.get("aspect_ratio") or "",
        "megapixels": entry.get("megapixels"),
        "width": int(entry.get("width") or vid.get("width") or 1024),
        "height": int(entry.get("height") or vid.get("height") or 1024),
        "fps": int(entry.get("fps") or vid.get("fps") or 24),
        "duration_min": duration_min,
        "duration_max": duration_max,
        "prompt_enhance": (
            bool(entry["prompt_enhance"]) if "prompt_enhance" in entry
            else bool(vid.get("prompt_enhance"))
        ),
        "prompt_enhance_lora": (
            entry.get("prompt_enhance_lora") or vid.get("prompt_enhance_lora") or ""
        ),
        "negative": vid.get("negative") or "",
        "r2v_workflow": (
            entry.get("r2v_workflow") or vid.get("r2v_workflow") or ""
        ),
        "turbo_steps": h3_turbo_steps(
            entry["turbo_steps"] if "turbo_steps" in entry
            else vid.get("turbo_steps")
        ),
        "full_steps": int(entry.get("full_steps") or vid.get("full_steps") or 20),
        "turbo_lora": entry.get("turbo_lora") or vid.get("turbo_lora") or {},
        "sampler": entry.get("sampler") or vid.get("sampler") or "",
        "turbo_strength": entry.get("turbo_strength") if entry.get("turbo_strength") is not None
            else vid.get("turbo_strength"),
        "turbo_strength_nsfw": entry.get("turbo_strength_nsfw") if entry.get("turbo_strength_nsfw") is not None
            else vid.get("turbo_strength_nsfw"),
        "effect_loras": entry.get("effect_loras") or vid.get("effect_loras") or [],
    }


def video_is_h3(cfg: dict, key: str | None = None) -> bool:
    """是否 MiniMax H3 圖生影。"""
    try:
        info = resolve_video_model(cfg, key)
    except ValueError:
        k = (key or "").lower()
        return "h3" in k or "minimax" in k
    blob = f"{info.get('key') or ''} {info.get('workflow') or ''}".lower()
    return "h3" in blob or "minimax" in blob


def h3_turbo_steps(value, default: int = 8) -> int:
    """0 = 關閉 Turbo（走正常 20 step）；4 或 8 為 Turbo。"""
    if isinstance(value, str) and value.strip().lower() in {"off", "none", "full", "normal"}:
        return 0
    try:
        n = int(value)
    except (TypeError, ValueError):
        try:
            n = int(default)
        except (TypeError, ValueError):
            n = 8
    if n <= 0 or n >= 16:
        return 0
    return 4 if n <= 4 else 8


def _turbo_entry(mapping, steps: int) -> dict:
    if not isinstance(mapping, dict):
        return {}
    raw = mapping.get(steps)
    if raw is None:
        raw = mapping.get(str(steps))
    if isinstance(raw, str):
        return {"lora": raw}
    return raw if isinstance(raw, dict) else {}


def h3_turbo_spec(model: dict, kind: str, steps=None) -> dict | None:
    """H3 Turbo LoRA。kind 為 fl2v（圖生影）或 r2v（短篇參考）。"""
    blob = f"{model.get('key') or ''} {model.get('workflow') or ''}".lower()
    if "h3" not in blob and "minimax" not in blob:
        return None
    n = h3_turbo_steps(steps if steps is not None else model.get("turbo_steps"))
    if n == 0:
        try:
            full = int(model.get("full_steps") or 20)
        except (TypeError, ValueError):
            full = 20
        return {
            "off": True,
            "steps": max(1, full),
            "lora": "",
            "strength": 0,
            "strength_nsfw": 0,
            "sampler": "res_multistep",
            "shift_video": 12.0,
            "shift_audio": 3.0,
        }
    path = "r2v" if kind in {"r2v", "ref2v"} else "fl2v"
    loras = model.get("turbo_lora") or {}
    entry = _turbo_entry(loras.get(path) or {}, n)
    lora = (entry.get("lora") or "").strip()
    if not lora:
        raise ValueError(f"MiniMax H3 {path} {n}-step 未設定 turbo LoRA")
    shift_v = entry.get("shift_video")
    shift_a = entry.get("shift_audio")
    try:
        strength = float(
            entry.get("strength") if entry.get("strength") is not None
            else model.get("turbo_strength") if model.get("turbo_strength") is not None
            else 0.7
        )
    except (TypeError, ValueError):
        strength = 0.7
    try:
        strength_nsfw = float(
            model.get("turbo_strength_nsfw") if model.get("turbo_strength_nsfw") is not None
            else 0.5
        )
    except (TypeError, ValueError):
        strength_nsfw = 0.5
    return {
        "off": False,
        "steps": n,
        "lora": lora,
        "strength": strength,
        "strength_nsfw": strength_nsfw,
        "sampler": (entry.get("sampler") or model.get("sampler") or "euler").strip() or "euler",
        "shift_video": float(shift_v if shift_v is not None else (6 if "768p" in lora else 12)),
        "shift_audio": float(shift_a if shift_a is not None else 3),
    }


def pick_h3_effect_loras(
    model: dict,
    *,
    nsfw: bool = False,
    climax: bool = False,
    action: str = "",
    tags: str = "",
    motion: str = "",
    extra: str = "",
    look: str = "",
) -> list[dict]:
    """依 NSFW／動作／高潮挑 H3 效果 LoRA（不含 Turbo）。"""
    blob = f"{model.get('key') or ''} {model.get('workflow') or ''}".lower()
    if "h3" not in blob and "minimax" not in blob:
        return []
    from .prompts import (
        has_legwear, wants_bounce, wants_cumshot, wants_genitals,
        wants_intense, wants_penetration,
    )
    legwear = has_legwear(action, tags, motion, extra, look)
    intense = wants_intense(action, tags, motion, extra, climax=climax)
    ctx = {
        "always": True,
        "nsfw": bool(nsfw),
        "genitals": bool(nsfw) and wants_genitals(action, tags, motion, extra, look),
        # 激烈段不用 bounce，避免和抽插搶變形；有絲襪時會把腿部衣著吃掉
        "bounce": (
            bool(nsfw) and wants_bounce(action, tags)
            and not intense and not legwear
        ),
        "penetration": bool(nsfw) and wants_penetration(action, tags, motion, extra),
        "cumshot": bool(nsfw) and wants_cumshot(
            action, tags, motion, extra, climax=climax),
        "intense": intense,
    }
    out = []
    for raw in model.get("effect_loras") or []:
        if not isinstance(raw, dict):
            continue
        name = (raw.get("lora") or "").strip()
        if not name:
            continue
        if "." not in name:
            name = name + ".safetensors"
        when = (raw.get("when") or "always").strip().lower()
        if when not in ctx or not ctx[when]:
            continue
        try:
            strength = float(raw.get("strength") if raw.get("strength") is not None else 1)
        except (TypeError, ValueError):
            strength = 1.0
        if legwear and when in {"nsfw", "penetration"}:
            strength = round(strength * 0.6, 2)
        out.append({
            "id": raw.get("id") or name,
            "lora": name,
            "strength": strength,
            "when": when,
        })
    return out

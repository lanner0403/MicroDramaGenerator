"""Danbooru Top 500 角色清單，依性別分女／男。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import cache_dir
from .voice import character_voice_style, voice_label

_MINOR_RE = re.compile(
    r"\b(loli|shota|toddler|underage|child|kindergartener|baby|precure|pretty cure)\b",
    re.I,
)


def strip_lora(text: str) -> str:
    """Diffusers / H3 吃不了 A1111 LoRA 語法，拿掉。"""
    text = re.sub(r"<lora:[^>]+>", "", text or "", flags=re.I)
    parts = [p.strip() for p in text.replace("\n", " ").split(",") if p.strip()]
    return ", ".join(parts)


def characters_path(cfg: dict) -> Path:
    raw = ((cfg.get("characters") or {}).get("file") or "data/characters.json")
    p = Path(raw)
    if not p.is_absolute():
        p = Path(cfg.get("_root") or ".") / p
    return p


def _tag_readable(tag: str) -> str:
    core = re.sub(r"_\([^)]+\)", "", tag or "")
    return core.replace("_", " ").strip()


def _prompt_for(tag: str, gender: str) -> str:
    tag = (tag or "").strip()
    readable = _tag_readable(tag)
    parts = [tag]
    if readable and readable != tag:
        parts.append(readable)
    g = (gender or "").strip().lower()
    if g == "female":
        parts.append("1girl")
    elif g == "male":
        parts.append("1boy")
    return ", ".join(parts)


class Catalog:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.characters: list[dict] = []
        self.actions: dict[str, str] = {}
        self.zh_to_title: dict[str, str] = {}
        self.title_to_zh: dict[str, str] = {}
        self.custom_characters: dict[str, str] = {}
        self._images: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        src = characters_path(self.cfg)
        if not src.exists():
            raise FileNotFoundError(f"找不到角色檔: {src}")
        blob = json.loads(src.read_text(encoding="utf-8"))
        rows = blob.get("characters") or blob if isinstance(blob, dict) else blob
        characters = []
        zh_to_title = {}
        title_to_zh = {}
        for i, item in enumerate(rows):
            tag = (item.get("tag") or item.get("title") or "").strip()
            if not tag:
                continue
            gender = (item.get("gender") or item.get("g") or "ambiguous").strip().lower()
            if gender not in {"female", "male", "ambiguous"}:
                gender = "ambiguous"
            zh = (item.get("zh") or "").strip()
            series = (item.get("series") or item.get("s") or "").strip()
            voice = (item.get("voice") or "").strip() or character_voice_style(
                tag, gender, series, zh)
            characters.append({
                "title": tag,
                "zh": zh,
                "index": i,
                "gender": gender,
                "series": series,
                "rank": item.get("rank") or item.get("r") or i + 1,
                "posts": item.get("posts") or item.get("p") or "",
                "prompt": _prompt_for(tag, gender),
                "voice": voice,
                "voice_label": voice_label(voice),
            })
            if zh:
                zh_to_title.setdefault(zh, tag)
                title_to_zh.setdefault(tag, zh)
        self.characters = characters
        self.zh_to_title = zh_to_title
        self.title_to_zh = title_to_zh
        cache = cache_dir(self.cfg) / "catalog_cache.json"
        try:
            cache.write_text(json.dumps({
                "src": str(src),
                "count": len(characters),
            }, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def list_characters(self, gender: str | None = None) -> list[dict]:
        want = (gender or "").strip().lower()
        out = []
        for c in self.characters:
            if want in {"female", "male", "ambiguous"} and c.get("gender") != want:
                continue
            out.append({
                "title": c["title"],
                "zh": c.get("zh") or "",
                "index": c["index"],
                "gender": c.get("gender") or "",
                "series": (c.get("series") or "").strip() or "其他",
                "rank": c.get("rank") or 0,
                "voice": c.get("voice") or "",
                "voice_label": c.get("voice_label") or "",
            })
        return out

    def list_series(self, gender: str | None = None) -> list[dict]:
        counts: dict[str, int] = {}
        for c in self.list_characters(gender):
            s = c.get("series") or "其他"
            counts[s] = counts.get(s, 0) + 1
        return [
            {"label": k, "count": n}
            for k, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        ]

    def get_character(self, title: str | None = None, index: int | None = None) -> dict | None:
        if index is not None:
            if 0 <= index < len(self.characters):
                return self.characters[index]
            return None
        if not title:
            return None
        key = title.strip()
        for c in self.characters:
            if c["title"] == key:
                return c
        mapped = self.zh_to_title.get(key)
        if mapped:
            return self.get_character(mapped)
        low = key.lower()
        for c in self.characters:
            if c["title"].lower() == low:
                return c
            if (c.get("zh") or "").lower() == low:
                return c
        return None

    def character_prompt(self, title: str) -> str:
        extra = self.custom_characters.get(title)
        if extra:
            return extra if extra != title else title
        found = self.get_character(title)
        if found:
            return found.get("prompt") or _prompt_for(found["title"], found.get("gender") or "")
        return title

    def preview_data_url(self, title: str) -> str | None:
        return self._images.get(title)

    def preview_bytes(self, title: str) -> tuple[bytes, str] | None:
        return None

    def action_names(self) -> list[str]:
        return list(self.actions.keys())

    def action_prompt(self, name: str) -> str:
        if name not in self.actions:
            raise ValueError(f"未知動作: {name}")
        return strip_lora(self.actions[name])

    def random_character(self, rng, gender: str | None = None) -> dict:
        want = (gender or "female").strip().lower()
        pool = [
            c for c in self.characters
            if (not want or want == "all" or c.get("gender") == want)
            and not _MINOR_RE.search(c["title"])
        ]
        if not pool:
            pool = [c for c in self.characters if not want or want == "all" or c.get("gender") == want]
        if not pool:
            pool = self.characters
        if not pool:
            raise ValueError("角色清單是空的")
        return rng.choice(pool)

    def random_action(self, rng) -> str:
        names = self.action_names()
        if not names:
            raise ValueError("動作清單是空的")
        return rng.choice(names)

    def display_name(self, title: str) -> str:
        found = self.get_character(title)
        zh = (found or {}).get("zh") or self.title_to_zh.get(title)
        tag = (found or {}).get("title") or title
        return f"{zh}  ·  {tag}" if zh else tag

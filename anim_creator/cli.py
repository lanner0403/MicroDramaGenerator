"""命令列：python -m anim_creator invent|stills|options"""
from __future__ import annotations

import argparse
import json

from .catalog import Catalog
from .config import diffusers_models, load_config, video_models
from .ollama_gen import ai_story, apply_ollama_model
from .pipeline import Pipeline
from .stories import get_story, list_stories, save_story
from .themes import male_theme_labels, theme_labels


def main(argv=None):
    p = argparse.ArgumentParser(prog="anim_creator")
    sub = p.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("options", help="列出角色／劇本／模型")
    o.add_argument("--gender", default="", help="female / male")

    inv = sub.add_parser("invent", help="Ollama 寫一篇短劇")
    inv.add_argument("--character", required=True, help="女角色 danbooru tag 或中文名")
    inv.add_argument("--male", default="", help="男角色（可空）")
    inv.add_argument("--premise", default="")
    inv.add_argument("--sfw", action="store_true")
    inv.add_argument("--seed", type=int, default=None)
    inv.add_argument("--model", default=None, help="Ollama 模型")

    g = sub.add_parser("stills", help="依短劇產 R2V 參考圖")
    g.add_argument("--story", required=True, help="劇本 id")
    g.add_argument("--character", required=True)
    g.add_argument("--male", default="")
    g.add_argument("--theme", default="", help="女衣著")
    g.add_argument("--male-theme", default="", dest="male_theme", help="男衣著")
    g.add_argument("--voice", default="", dest="voice_style", help="女聲線（可空＝依角色自動）")
    g.add_argument("--language", default="", help="zh / ja / en（可空＝設定檔，預設中文）")
    g.add_argument("--extra", default="")
    g.add_argument("--seed", type=int, default=None)
    g.add_argument("--model", default=None, help="Diffusers 模型 key")

    a = sub.add_parser("animate", help="短劇包產動畫")
    a.add_argument("--pack", required=True)
    a.add_argument("--set", type=int, default=1)
    a.add_argument("--turbo-steps", type=int, choices=[0, 4, 8], default=None)
    a.add_argument("--clip-mode", choices=["r2v", "i2v", "i2v_clone"], default="r2v",
                   dest="clip_mode",
                   help="r2v、i2v（尾幀）、i2v_clone（尾幀＋聲線克隆）")

    args = p.parse_args(argv)
    cfg = load_config()
    catalog = Catalog(cfg)

    if args.cmd == "options":
        gender = (args.gender or "").strip().lower()
        chars = catalog.list_characters(gender if gender in {"female", "male"} else None)
        print(f"characters: female={sum(1 for c in catalog.characters if c.get('gender')=='female')} "
              f"male={sum(1 for c in catalog.characters if c.get('gender')=='male')}")
        for c in chars[:20]:
            print(f"  {c.get('zh') or ''}  {c['title']}  [{c.get('gender')}]")
        if len(chars) > 20:
            print(f"  … 共 {len(chars)}")
        print("stories:")
        for s in list_stories(cfg.get("_root")):
            print(f"  {s['id']}: {s['title']} ({s['count']} beats, {s['total']}s, {s.get('source')})")
        print("female outfits:")
        for k, v in theme_labels().items():
            print(f"  {k}: {v}")
        print("male outfits:")
        for k, v in male_theme_labels().items():
            print(f"  {k}: {v}")
        print("diffusers:")
        for k, v in diffusers_models(cfg).items():
            print(f"  {k}: {v.get('label') or k}")
        print("video:")
        for k, v in video_models(cfg).items():
            print(f"  {k}: {v.get('label') or k}")
        return

    if args.cmd == "invent":
        cfg = apply_ollama_model(cfg, args.model)
        f = catalog.get_character(args.character)
        female = catalog.display_name(f["title"]) if f else args.character
        m = catalog.get_character(args.male) if args.male else None
        male = catalog.display_name(m["title"]) if m else args.male
        story = ai_story(
            cfg, female=female, male=male, premise=args.premise,
            nsfw=not args.sfw, seed=args.seed)
        saved = save_story(story, cfg.get("_root"))
        print(json.dumps(saved, ensure_ascii=False, indent=2))
        return

    pipe = Pipeline(cfg, catalog)
    if args.cmd == "stills":
        get_story(args.story, cfg.get("_root"))
        meta = pipe.generate_story_stills(
            story_id=args.story,
            character=args.character,
            male=args.male,
            theme=args.theme,
            male_theme=args.male_theme,
            voice_style=args.voice_style or None,
            language=args.language or None,
            extra=args.extra,
            seed=args.seed,
            diffusers_model=args.model,
            story_mode="r2v",
        )
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return

    meta = pipe.animate_story_set(
        args.pack, args.set, turbo_steps=args.turbo_steps,
        clip_mode=args.clip_mode)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

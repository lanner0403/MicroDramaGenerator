"""固定角色／主題的有序動作串：8–10 步、一次 1 套。"""
from __future__ import annotations

import random

# 故事順序：先前戲／乳交／口交，再插入，最後 after sex。
STORY = [
    "hand job",
    "foot job",
    "breast sucking",
    "paizuri",
    "fellatio",
    "sex",
    "mating press",
    "girl on top",
    "doggy style",
    "standing sex",
    "carrying sex",
    "anal sex",
    "creampie",
    "after sex",
]
CORE = {
    "paizuri",
    "fellatio",
    "sex",
    "girl on top",
    "doggy style",
    "after sex",
}


def _is_variant(name: str, family: str) -> bool:
    n = (name or "").strip().lower()
    f = family.lower()
    if n == f:
        return True
    if n.startswith(f + " "):
        return n[len(f) + 1 :].isdigit()
    return False


def family_actions(catalog_names: list[str], family: str) -> list[str]:
    return [n for n in catalog_names if _is_variant(n, family)]


def build_sequence_plans(
    catalog_names: list[str],
    rng: random.Random,
    *,
    set_count: int = 1,
    steps_min: int = 8,
    steps_max: int = 10,
) -> list[list[str]]:
    """回傳 set_count 套動作名清單，每套 steps_min–steps_max 步、順序固定。"""
    available: dict[str, list[str]] = {}
    for fam in STORY:
        hits = family_actions(catalog_names, fam)
        if hits:
            available[fam] = hits
    core = [f for f in STORY if f in CORE and f in available]
    optional = [f for f in STORY if f not in CORE and f in available]
    if len(core) < 4:
        raise ValueError("動作庫不足，組不出動作串（需要乳交／口交／插入／after sex 等）")
    steps_min = max(len(core), min(10, int(steps_min)))
    steps_max = max(steps_min, min(len(core) + len(optional), int(steps_max)))
    set_count = max(1, min(5, int(set_count)))

    plans: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for _ in range(set_count * 8):
        if len(plans) >= set_count:
            break
        extra_n = rng.randint(steps_min - len(core), steps_max - len(core))
        extra_n = max(0, min(len(optional), extra_n))
        extras = set(rng.sample(optional, extra_n)) if extra_n else set()
        families = [f for f in STORY if f in core or f in extras]
        chosen = [rng.choice(available[f]) for f in families]
        key = tuple(chosen)
        if key in seen:
            continue
        seen.add(key)
        plans.append(chosen)
    if len(plans) < set_count:
        raise ValueError("無法排出足夠的不同動作組合，請再試一次")
    return plans

"""ComfyUI HTTP API client：送出 workflow、等待完成、下載輸出、上傳輸入圖。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import requests


class ComfyUIError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str, poll_interval: float = 1.5, timeout: float = 3600):
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex

    # ---- 基本 API ----

    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/system_stats", timeout=5)
            return r.ok
        except requests.RequestException:
            return False

    def upload_image(self, path: str | Path, subfolder: str = "sprite_creator") -> str:
        """上傳圖片到 ComfyUI input 資料夾，回傳可供 LoadImage 使用的名稱。

        檔名加短 hash，避免 LoadImage 快取同名舊圖（重作首幀後再重作動畫會吃到舊幀）。
        """
        path = Path(path)
        unique = f"{path.stem}_{uuid.uuid4().hex[:8]}{path.suffix}"
        mime = "video/mp4" if path.suffix.lower() == ".mp4" else "image/png"
        with open(path, "rb") as f:
            r = requests.post(
                f"{self.base_url}/upload/image",
                files={"image": (unique, f, mime)},
                data={"subfolder": subfolder, "overwrite": "true"},
                timeout=120,
            )
        r.raise_for_status()
        info = r.json()
        name = info["name"]
        sub = info.get("subfolder", "")
        return f"{sub}/{name}" if sub else name

    def queue_prompt(self, workflow: dict) -> str:
        payload = {"prompt": workflow, "client_id": self.client_id}
        r = requests.post(f"{self.base_url}/prompt", json=payload, timeout=60)
        if not r.ok:
            raise ComfyUIError(f"queue_prompt failed ({r.status_code}): {r.text[:2000]}")
        data = r.json()
        if "error" in data:
            raise ComfyUIError(f"queue_prompt rejected: {json.dumps(data, ensure_ascii=False)[:2000]}")
        return data["prompt_id"]

    def interrupt(self) -> bool:
        try:
            r = requests.post(f"{self.base_url}/interrupt", timeout=10)
            return r.ok
        except requests.RequestException:
            return False

    def free_memory(self) -> bool:
        """卸載 ComfyUI 已載入模型並清 VRAM（POST /free）。"""
        try:
            r = requests.post(
                f"{self.base_url}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=60,
            )
            return r.ok
        except requests.RequestException:
            return False

    def wait(self, prompt_id: str, on_progress=None) -> dict:
        """輪詢 /history 直到任務完成，回傳該任務的 history 條目。"""
        start = time.time()
        while True:
            if time.time() - start > self.timeout:
                self.interrupt()
                self.free_memory()
                raise ComfyUIError(f"timeout waiting for prompt {prompt_id}")
            r = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=30)
            if r.ok:
                hist = r.json()
                if prompt_id in hist:
                    entry = hist[prompt_id]
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                        raise ComfyUIError(f"execution error: {json.dumps(msgs, ensure_ascii=False)[:3000]}")
                    if status.get("completed") or entry.get("outputs"):
                        return entry
            if on_progress:
                on_progress(time.time() - start)
            time.sleep(self.poll_interval)

    def download_outputs(self, history_entry: dict, dest_dir: str | Path) -> list[Path]:
        """把 history 內所有帶 filename 的輸出檔（圖/影片）抓下來。"""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for node_output in history_entry.get("outputs", {}).values():
            for value in node_output.values():
                if not isinstance(value, list):
                    continue
                for item in value:
                    if not isinstance(item, dict) or "filename" not in item:
                        continue
                    if item.get("type") == "temp":  # 跳過 Preview 節點的暫存檔
                        continue
                    params = {
                        "filename": item["filename"],
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    }
                    r = requests.get(f"{self.base_url}/view", params=params, timeout=300)
                    r.raise_for_status()
                    out_path = dest_dir / item["filename"]
                    out_path.write_bytes(r.content)
                    saved.append(out_path)
        return saved

    # ---- 便利方法 ----

    def run(self, workflow: dict, dest_dir: str | Path, on_progress=None) -> list[Path]:
        pid = self.queue_prompt(workflow)
        entry = self.wait(pid, on_progress=on_progress)
        files = self.download_outputs(entry, dest_dir)
        if not files:
            raise ComfyUIError("workflow finished but produced no downloadable outputs")
        return files

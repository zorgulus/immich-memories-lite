#!/usr/bin/env python3
import os
import sys
import json
import shutil
import random
import subprocess
import tempfile
import urllib.request
from datetime import date

IMMICH_URL = os.environ.get("IMMICH_URL", "http://localhost:2283")
API_KEY = os.environ["IMMICH_API_KEY"]
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/app/output")
CLIP_DURATION = float(os.environ.get("CLIP_DURATION", "3.5"))
TRANSITION = os.environ.get("TRANSITION", "cut")  # "cut" or "fade"
XFADE_DURATION = float(os.environ.get("XFADE_DURATION", "1.0"))
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "18"))
MAX_PER_YEAR = int(os.environ.get("MAX_PER_YEAR", "2"))
WIDTH = int(os.environ.get("WIDTH", "1280"))
HEIGHT = int(os.environ.get("HEIGHT", "720"))
SHOW_YEAR = os.environ.get("SHOW_YEAR", "true").lower() == "true"


def api_get(path):
    req = urllib.request.Request(IMMICH_URL + path, headers={"x-api-key": API_KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def download_asset(asset_id, dest_path):
    req = urllib.request.Request(
        f"{IMMICH_URL}/api/assets/{asset_id}/original",
        headers={"x-api-key": API_KEY},
    )
    with urllib.request.urlopen(req, timeout=120) as r, open(dest_path, "wb") as f:
        shutil.copyfileobj(r, f)


def upload_asset(video_path):
    boundary = "----immichmemboundary"
    filename = os.path.basename(video_path)
    device_asset_id = f"immich-memories-lite-{filename}"

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    def field(name, value):
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()

    body = b""
    body += field("deviceAssetId", device_asset_id)
    body += field("deviceId", "immich-memories-lite")
    body += field("fileCreatedAt", date.today().isoformat() + "T00:00:00.000Z")
    body += field("fileModifiedAt", date.today().isoformat() + "T00:00:00.000Z")
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="assetData"; filename="{filename}"\r\n'
        f"Content-Type: video/mp4\r\n\r\n"
    ).encode()
    body += video_bytes
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{IMMICH_URL}/api/assets",
        data=body,
        method="POST",
        headers={
            "x-api-key": API_KEY,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def run_ffmpeg(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFMPEG ERROR:", " ".join(cmd), file=sys.stderr)
        print(result.stderr[-3000:], file=sys.stderr)
        raise RuntimeError("ffmpeg failed")


def build_clip(src_path, is_video, year, out_path):
    vf = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2"
    if SHOW_YEAR:
        vf += (
            f",drawtext=text='{year}':fontcolor=white@0.75:fontsize=26:"
            "x=w-tw-24:y=h-th-24:box=1:boxcolor=black@0.35:boxborderw=8"
        )
    if is_video:
        cmd = [
            "ffmpeg", "-y", "-i", src_path,
            "-t", str(CLIP_DURATION),
            "-vf", vf,
            "-r", "30", "-an", "-pix_fmt", "yuv420p",
            out_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", src_path,
            "-t", str(CLIP_DURATION),
            "-vf", vf,
            "-r", "30", "-pix_fmt", "yuv420p",
            out_path,
        ]
    run_ffmpeg(cmd)


def assemble_cut(clips, final_path, workdir):
    if len(clips) == 1:
        shutil.copy(clips[0], final_path)
        return

    concat_list = os.path.join(workdir, "concat_list.txt")
    with open(concat_list, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-r", "30", "-pix_fmt", "yuv420p",
        final_path,
    ]
    run_ffmpeg(cmd)


def assemble_fade(clips, final_path):
    if len(clips) == 1:
        shutil.copy(clips[0], final_path)
        return

    inputs = []
    for c in clips:
        inputs += ["-i", c]

    filter_parts = []
    prev = "0:v"
    offset = CLIP_DURATION - XFADE_DURATION
    for i in range(1, len(clips)):
        label = f"v{i}"
        filter_parts.append(
            f"[{prev}][{i}:v]xfade=transition=fade:duration={XFADE_DURATION}:offset={offset}[{label}]"
        )
        prev = label
        offset += CLIP_DURATION - XFADE_DURATION

    filter_complex = ";".join(filter_parts)
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{prev}]",
        "-r", "30", "-pix_fmt", "yuv420p",
        final_path,
    ]
    run_ffmpeg(cmd)


def main():
    today = date.today().isoformat()
    print(f"Generating memory video for {today}")

    memories = api_get("/api/memories")
    today_memories = [
        m for m in memories
        if m["type"] == "on_this_day" and m["showAt"][:10] == today
    ]
    if not today_memories:
        print("No memories for today, nothing to do.")
        return

    today_memories.sort(key=lambda m: -m["data"]["year"])

    items = []
    for m in today_memories:
        year = m["data"]["year"]
        for a in m["assets"][:MAX_PER_YEAR]:
            items.append((a, year))

    if len(items) > MAX_ITEMS:
        items = random.sample(items, MAX_ITEMS)
    items.sort(key=lambda t: t[1])

    print(f"{len(items)} media items selected, years: {sorted(set(y for _, y in items))}")

    workdir = tempfile.mkdtemp(prefix="memgen_", dir="/tmp")
    clips = []
    try:
        for i, (asset, year) in enumerate(items):
            is_video = asset["type"] == "VIDEO"
            ext = ".mp4" if is_video else ".jpg"
            src_path = os.path.join(workdir, f"src_{i}{ext}")
            print(f"  [{i+1}/{len(items)}] downloading {asset['id']} ({year})")
            download_asset(asset["id"], src_path)

            clip_path = os.path.join(workdir, f"clip_{i}.mp4")
            build_clip(src_path, is_video, year, clip_path)
            clips.append(clip_path)

        final_path = os.path.join(workdir, "final.mp4")
        print(f"Assembling ({TRANSITION})...")
        if TRANSITION == "fade":
            assemble_fade(clips, final_path)
        else:
            assemble_cut(clips, final_path, workdir)

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        dated_name = f"memory_{today}.mp4"
        dest_path = os.path.join(OUTPUT_DIR, dated_name)
        shutil.copy(final_path, dest_path)
        print(f"Video saved: {dest_path}")

        print("Uploading to Immich...")
        result = upload_asset(dest_path)
        asset_id = result.get("id") or result.get("assetId")
        print(f"Uploaded to Immich: asset={asset_id}")

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()

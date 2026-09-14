"""
곡 음역대 추출 파이프라인
음원 -> LALAL.AI 보컬 분리 -> CREPE 피치 추출 -> 백엔드(POST /songs) 등록

실행 전 준비:
  1. song_metadata.csv 를 이 파일과 같은 폴더에 준비 (generate_metadata.py로 생성)
  2. 아래 환경변수를 설정 (PowerShell 기준):
       $env:LALAL_API_KEY = "..."
       $env:FITCH_USERNAME = "..."
       $env:FITCH_PASSWORD = "..."
       $env:FITCH_API_BASE = "http://localhost:8080"   # 생략하면 기본값으로 localhost 사용
  3. INPUT_DIR 에 원본 음원(.wav/.mp3)을 넣어두기
"""

import re
import os
import time
import csv
import requests
import librosa
import crepe
import numpy as np

# ===== 설정 (환경변수로 관리, 코드에 직접 값 넣지 않기) =====
LALAL_API_KEY = os.environ["LALAL_API_KEY"]
FITCH_USERNAME = os.environ["FITCH_USERNAME"]
FITCH_PASSWORD = os.environ["FITCH_PASSWORD"]
API_BASE = os.environ.get("FITCH_API_BASE", "http://localhost:8080")
LALAL_BASE = "https://www.lalal.ai/api/v1"

INPUT_DIR = "./audio"
OUTPUT_DIR = "./output"
METADATA_CSV = "./song_metadata.csv"
RESULTS_CSV = "./song_results.csv"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ===== 1. LALAL.AI 보컬 분리 =====

def make_ascii_safe_filename(filename):
    """파일명에 한글 등이 섞여 있으면 HTTP 헤더 전송 시 에러가 나므로,
    확장자는 유지하고 나머지는 ASCII 문자만 남기도록 정리한다."""
    name, ext = filename.rsplit(".", 1)
    safe_name = re.sub(r"[^\x00-\x7f]", "", name)
    safe_name = re.sub(r"\s+", "_", safe_name).strip("_")
    if not safe_name:
        safe_name = "audio"
    return f"{safe_name}.{ext}"


def upload_file(filepath):
    filename = os.path.basename(filepath)
    safe_filename = make_ascii_safe_filename(filename)
    with open(filepath, "rb") as f:
        response = requests.post(
            f"{LALAL_BASE}/upload/",
            headers={
                "X-License-Key": LALAL_API_KEY,
                "Content-Disposition": f"attachment; filename={safe_filename}",
                "Content-Type": "application/octet-stream",
            },
            data=f.read(),
        )
    response.raise_for_status()
    return response.json()


def start_split(source_id):
    response = requests.post(
        f"{LALAL_BASE}/split/stem_separator/",
        headers={"X-License-Key": LALAL_API_KEY, "Content-Type": "application/json"},
        json={
            "source_id": source_id,
            "presets": {"stem": "vocals", "multivocal": "lead_back"},
        },
    )
    response.raise_for_status()
    return response.json()


def wait_for_split(task_id, interval=5, timeout=300):
    elapsed = 0
    while elapsed < timeout:
        response = requests.post(
            f"{LALAL_BASE}/check/",
            headers={"X-License-Key": LALAL_API_KEY, "Content-Type": "application/json"},
            json={"task_ids": [task_id]},
        )
        response.raise_for_status()
        result = response.json()["result"][task_id]

        status = result["status"]
        if status == "success":
            return result
        elif status in ("error", "server_error", "cancelled"):
            raise RuntimeError(f"분리 실패: {result}")

        time.sleep(interval)
        elapsed += interval

    raise TimeoutError(f"task {task_id} 처리 시간 초과 ({timeout}초)")


def download_result(url, save_path):
    response = requests.get(url)
    response.raise_for_status()
    with open(save_path, "wb") as f:
        f.write(response.content)


def separate_vocals(input_path, audio_name):
    """원곡을 LALAL.AI로 분리하고, 리드보컬 wav 파일 경로를 반환"""
    vocals_path = os.path.join(OUTPUT_DIR, f"{audio_name}_lead_vocals.wav")

    if os.path.exists(vocals_path):
        print(f"  [분리] 이미 있음, 건너뜀")
        return vocals_path

    upload_result = upload_file(input_path)
    source_id = upload_result["id"]

    split_result = start_split(source_id)
    task_id = split_result["task_id"]

    check_result = wait_for_split(task_id)
    tracks = check_result["result"]["tracks"]
    lead_vocals_url = next(t["url"] for t in tracks if t["label"] == "vocals@0")

    download_result(lead_vocals_url, vocals_path)
    return vocals_path


# ===== 2. CREPE 피치 추출 (colab_extract.py와 완전히 동일) =====

def extract_pitch_range(vocals_path):
    """보컬 wav에서 최저음/최고음 후보들(Hz)을 CREPE로 추출 (colab_extract.py와 동일)"""
    y, sr = librosa.load(vocals_path, sr=16000)

    time_arr, frequency, confidence, activation = crepe.predict(
        y, sr, viterbi=True, verbose=0
    )

    fmin = librosa.note_to_hz("C2")
    fmax = librosa.note_to_hz("C6")
    range_mask = (frequency >= fmin) & (frequency <= fmax)
    conf_mask = confidence > 0.9
    f0_clean = frequency[range_mask & conf_mask]

    if len(f0_clean) == 0:
        raise ValueError("유성음 구간을 찾지 못했습니다")

    return {
        "min_hz": float(np.min(f0_clean)),
        "max_hz_raw": float(np.max(f0_clean)),
        "max_hz_p98": float(np.percentile(f0_clean, 98)),
    }


# ===== 3. 백엔드 로그인 & 등록 =====

def login():
    response = requests.post(
        f"{API_BASE}/auth/login",
        json={"username": FITCH_USERNAME, "password": FITCH_PASSWORD},
    )
    response.raise_for_status()
    return response.json()["accessToken"]


def register_song(headers, title, artist, min_hz, max_hz, genre=None):
    if not title or not artist:
        raise ValueError(f"title 또는 artist가 비어있습니다: title={title}, artist={artist}")

    payload = {
        "title": title,
        "artist": artist,
        "minNote": round(librosa.hz_to_midi(min_hz)),
        "maxNote": round(librosa.hz_to_midi(max_hz)),
    }
    if genre:
        payload["genre"] = genre

    response = requests.post(f"{API_BASE}/songs", json=payload, headers=headers)
    response.raise_for_status()
    return response.json()


# ===== 4. 메인 파이프라인 =====

def load_metadata(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    metadata = load_metadata(METADATA_CSV)
    print(f"총 {len(metadata)}곡 대상")

    token = login()
    headers = {"Authorization": f"Bearer {token}"}
    print("로그인 성공")

    results = []

    for row in metadata:
        filename = row["filename"]
        audio_name = os.path.splitext(filename)[0]
        input_path = os.path.join(INPUT_DIR, filename)

        print(f"\n[{filename}] 처리 시작")

        if not os.path.exists(input_path):
            print(f"  원본 파일이 없습니다: {input_path}, 건너뜀")
            results.append({
                "filename": filename,
                "title": row.get("title"),
                "songId": None,
                "minNoteLabel": None,
                "maxNoteLabel": None,
                "status": "failed: 원본 파일 없음",
            })
            continue

        try:
            print("  1) 보컬 분리 중...")
            vocals_path = separate_vocals(input_path, audio_name)

            print("  2) 피치 추출 중...")
            pitch_result = extract_pitch_range(vocals_path)
            print(
                f"     최저음(raw)={pitch_result['min_hz']:.1f}Hz "
                f"최고음 raw={pitch_result['max_hz_raw']:.1f}Hz "
                f"p98={pitch_result['max_hz_p98']:.1f}Hz"
            )

            print("  3) 백엔드 등록 중...")
            result = register_song(
                headers,
                title=row["title"],
                artist=row["artist"],
                min_hz=pitch_result["min_hz"],
                max_hz=pitch_result["max_hz_p98"],
                genre=row.get("genre") or None,
            )

            print(f"  등록 완료: songId={result['songId']}")

            results.append({
                "filename": filename,
                "title": row["title"],
                "songId": result["songId"],
                "minNoteLabel": result.get("minNoteLabel"),
                "maxNoteLabel": result.get("maxNoteLabel"),
                "status": "success",
            })

        except Exception as e:
            print(f"  실패: {e}")
            results.append({
                "filename": filename,
                "title": row.get("title"),
                "songId": None,
                "minNoteLabel": None,
                "maxNoteLabel": None,
                "status": f"failed: {e}",
            })
            continue

    with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "title", "songId", "minNoteLabel", "maxNoteLabel", "status"])
        writer.writeheader()
        writer.writerows(results)

    success_count = sum(1 for r in results if r["status"] == "success")
    print(f"\n전체 완료: {success_count}/{len(results)}곡 성공. 결과는 {RESULTS_CSV}에 저장됨")


if __name__ == "__main__":
    main()
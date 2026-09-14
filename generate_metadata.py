"""
audio 폴더 안의 음원 파일들에서 ID3 등 내장 메타데이터(제목/아티스트/장르)를 자동으로 읽어와
song_metadata.csv를 생성한다.

태그가 없는 파일은 자동으로 채울 수 없으니, 그 파일들만 목록으로 알려주고
CSV에는 빈 칸으로 남겨둔다 (그 부분만 사람이 나중에 채우면 됨).

지원 포맷: mp3, m4a, flac, wav(태그가 있는 경우)
"""

import os
import csv

from mutagen import File as MutagenFile
from mutagen.easyid3 import EasyID3

INPUT_DIR = "./audio"
METADATA_CSV = "./song_metadata.csv"

SUPPORTED_EXT = (".mp3", ".m4a", ".flac", ".wav")


def read_tags(filepath):
    """파일에서 title/artist/genre를 읽어서 dict로 반환. 못 읽으면 빈 값들."""
    try:
        audio = MutagenFile(filepath, easy=True)
        if audio is None or not audio.tags:
            return {"title": "", "artist": "", "genre": ""}

        def first(key):
            values = audio.tags.get(key)
            return values[0] if values else ""

        return {
            "title": first("title"),
            "artist": first("artist"),
            "genre": first("genre"),
        }
    except Exception:
        return {"title": "", "artist": "", "genre": ""}


def main():
    files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(SUPPORTED_EXT)]
    print(f"총 {len(files)}개 음원 파일 발견")

    rows = []
    needs_manual = []

    for filename in sorted(files):
        filepath = os.path.join(INPUT_DIR, filename)
        tags = read_tags(filepath)

        rows.append({
            "filename": filename,
            "title": tags["title"],
            "artist": tags["artist"],
            "genre": tags["genre"],
        })

        if not tags["title"] or not tags["artist"]:
            needs_manual.append(filename)

    with open(METADATA_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "title", "artist", "genre"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{METADATA_CSV} 생성 완료 ({len(rows)}곡)")

    if needs_manual:
        print(f"\n⚠️  아래 {len(needs_manual)}개 파일은 태그가 없어서 제목/아티스트를 못 읽었습니다.")
        print(f"   {METADATA_CSV}를 열어서 이 파일들만 직접 채워주세요:")
        for f in needs_manual:
            print(f"   - {f}")
    else:
        print("모든 파일에서 태그를 정상적으로 읽었습니다. 수동 입력이 필요 없습니다!")


if __name__ == "__main__":
    main()
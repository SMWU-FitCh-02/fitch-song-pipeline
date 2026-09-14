# fitch-song-pipeline

곡 음원에서 보컬을 분리하고, 음역대(최저음/최고음)를 추출해서 백엔드에 등록하는 파이프라인입니다.

## 처리 흐름

generate_metadata.py (로컬)
    ↓ song_metadata.csv
colab_extract.py (Colab, GPU 필요)
    ↓ song_results_raw.csv
pipeline.py (로컬, 백엔드 등록)
    ↓ song_results.csv


## 사용 방법

### 1. 메타데이터 자동 생성
`audio/` 폴더에 원본 음원(.mp3/.wav)을 넣고:
```powershell
python generate_metadata.py
```
`song_metadata.csv`가 생성됩니다. ID3 태그가 없는 곡은 터미널에 표시되니 직접 채워주세요.

### 2. Colab에서 분리 + 피치 추출
- `song_metadata.csv`와 `audio/` 폴더를 Google Drive에 업로드
- Colab에서 `colab_extract.py` 실행 (LALAL_API_KEY 입력 필요)
- 결과로 `song_results_raw.csv`가 Drive에 생성됨 → 로컬로 다운로드

### 3. 백엔드에 등록
```powershell
$env:FITCH_USERNAME = "..."
$env:FITCH_PASSWORD = "..."
$env:FITCH_API_BASE = "http://localhost:8080"   # 또는 AWS 배포 주소
python pipeline.py
```

## 음역대 추출 방식

- 보컬 분리: LALAL.AI API (stem separator, lead/backing vocal 분리)
- 피치 추출: CREPE (librosa 기반, fmin=C2, fmax=C6, confidence>0.9)
- 최저음: raw 값 그대로 / 최고음: 95번째 백분위수 대신 **98번째 백분위수(p98)** 채택
  - 악보를 통해 실제 음역대를 알고 있는 9곡 실측 검증 결과 평균 오차(MAE) 3.13반음으로 raw/p90/p95/p99 대비 최적

## requirements

pip install requests librosa numpy crepe tensorflow mutagen

(crepe 설치 시 Windows에서 `pkg_resources` 에러가 나면 `pip install "setuptools<81" wheel` 먼저 설치 후 `pip install --no-build-isolation crepe`)

## 알려진 한계
- 코러스/화음이 두드러진 일부 곡은 여전히 부정확할 수 있음 (분리 품질 한계)
- 옥타브 에러가 완전히 해결된 것은 아니며, 음역대가 비정상적으로 넓게 나온 곡은 재확인 필요
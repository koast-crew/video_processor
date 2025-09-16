# RTSP Multithread Processor (uv 기반 운영 가이드)

이 디렉터리는 RTSP 스트림을 멀티 프로세스로 병렬 처리하여 YOLO 블러, 오버레이, MP4 저장, 자막(SRT) 작성, 최종 경로 자동 이동까지 수행합니다. 본 문서는 처음부터 uv를 사용하여 설치/운영하는 방법을 안내합니다.

## ✅ 빠른 시작 (uv 권장)

```bash
# 0) 필수 시스템 패키지
sudo apt-get update
sudo apt-get install -y ffmpeg build-essential cmake ninja-build git python3-dev screen jq
sudo apt install nvidia-driver-570

# 1) uv 설치 (1회)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2) 파이썬 의존성 설치 (requirements.txt 기반 정확히 동기화)
cd /home/koast-user/oper/video_processor
uv venv
uv pip sync --index-strategy unsafe-best-match requirements.txt
uv pip install "https://pypi.nvidia.com/tensorrt-cu12/tensorrt-cu12-10.0.1.tar.gz#sha256=ebb89f6f9b6d187265f3bc829e38cff6e27059508e9a160e229506e5d9b648a0"
# 주의: torch/torchvision은 CUDA 버전에 따라 설치 변형이 있을 수 있습니다.
# 현재 requirements.txt는 cu121 기반입니다.

# 3) mediaMTX 설치
wget https://github.com/bluenviron/mediamtx/releases/download/v1.9.1/mediamtx_v1.9.1_linux_amd64.tar.gz
tar -xzf mediamtx_v1.9.1_linux_amd64.tar.gz
chmod +x mediamtx
sudo mv mediamtx /usr/local/bin/

# 4) 환경파일(.env.streamN) 자동 생성
./generate_env.sh
# 스트림 개수는 고정이 아닙니다. 다음 우선순위로 결정됩니다:
# - generate_env.sh에서 설정한 NUM_STREAMS(기본 6)
# - 실행 시 NUM_STREAMS=N ./start_all_streams.sh 로 덮어쓰기 가능
# - 현재 디렉터리의 .env.stream* 파일 중 최대 인덱스도 자동 감지

# 5) 전체 스트림 + 파일 이동 서비스 실행 (MediaMTX 사전 설치 필요)
./start_all_streams.sh

# 6) 상태 확인 및 중지
./status_all_streams.sh
./stop_all_streams.sh
```

- 내부 실행은 `uv run python`으로 수행되므로, 별도 가상환경 활성화 없이도 실행됩니다.
- ultralytics는 필수입니다. 모델 파일(.pt) 경로는 `HEAD_BLUR_MODEL_PATH` 환경변수로 지정하세요. (미지정 시 `blur_module/models/best_re_final.pt`를 찾습니다.)

## 📦 구성 파일 개요

### Python 모듈
- `run.py`: 단일 스트림 런처. `.env`(혹은 프로세스 환경) 로드 → 수신/블러/오버레이/저장 파이프라인 실행. 날짜별 파일 로그 자동 회전.
- `config.py`: 환경변수 파싱과 설정(`RTSPConfig`, `FFmpegConfig`, `OverlayConfig`) 제공. 파일명 생성, GPS 포맷 유틸 포함.
- `stream_receiver.py`: RTSP 수신, 재연결, FPS 페이싱, 수신 통계.
- `frame_processor.py`: 블러 → 오버레이 → 비디오 저장 → SRT 갱신.
- `video_writer.py`: FFmpeg 파이프 저장. `temp_*.mp4` → 세그먼트 완료 시 최종명 rename. 날짜별 stderr 로깅.
- `subtitle_writer.py`: 세그먼트 생명주기에 맞춰 초 단위 SRT 작성/완료.
- `blackbox_manager.py`: 블랙박스 API 폴링, 오버레이/녹화 조건 결정.
- `api_client.py`: API 클라이언트. 영상 메타 전송(파일 크기 MB 문자열 전송).
- `monitor.py`: 시스템 리소스 수집(향후 Redis 연동 준비).
- `file_mover.py`: watchdog으로 임시 디렉터리 감시 → 최종 경로(`/YYYY/MM/DD/HH/`)로 이동 → MP4 이동 완료 시 API 전송.

### Shell 스크립트
- `generate_env.sh`: 다중 스트림용 `.env.streamN` 자동 생성(스트림 수/URL, 출력/로그/FFmpeg/API 등). NUM_STREAMS로 스트림 개수를 설정합니다.
- `start_all_streams.sh`: 각 `.env.streamN`을 기반으로 스트림을 개별 screen 세션으로 실행하고, 파일 이동 서비스 세션도 실행. 내부 호출은 `uv run python` 사용. 스트림 개수는 고정값이 아닌 NUM_STREAMS/`.env.stream*`에 따라 동적으로 결정됩니다.
- `status_all_streams.sh`: 실행 중 세션/로그 현황 요약 출력(날짜 디렉토리 경로 반영).
- `stop_all_streams.sh`: 실행 중 세션 종료, 임시 파일 정리.

## ⚙️ generate_env.sh가 설정하는 환경변수

- 스트림 수/URL
  - `NUM_STREAMS`: 생성할 스트림 수 (기본 6)
  - `RTSP_URLS`: 각 스트림의 RTSP URL 배열(부족분은 `rtsp://<BASE_IP>:<START_PORT+i-1>/live` 자동 채움)
- 출력/로깅/성능/블러/모니터링/API/녹화 조건
  - `TEMP_OUTPUT_PATH`(기본 `./output/temp/`), `FINAL_OUTPUT_PATH`(기본 `/mnt/nas/cam/`), `LOG_DIR`(기본 `/mnt/nas/logs`)
  - `DEFAULT_INPUT_FPS`(기본 `15.0`), `VIDEO_SEGMENT_DURATION`(기본 `300`초), `VIDEO_WIDTH`/`VIDEO_HEIGHT`
  - `FRAME_QUEUE_SIZE`, `CONNECTION_TIMEOUT`, `RECONNECT_INTERVAL`
  - `BLUR_MODULE_PATH`, `BLUR_ENABLED`, `BLUR_CONFIDENCE`
  - `BLACKBOX_API_URL`, `API_TIMEOUT`, `API_POLL_INTERVAL`, `BLACKBOX_ENABLED`
  - `RECORDING_SPEED_THRESHOLD`(knots)
- FFmpeg 비트레이트
  - `FFMPEG_TARGET_BITRATE`, `FFMPEG_MIN_BITRATE`, `FFMPEG_MAX_BITRATE`
- 로깅
  - `LOG_LEVEL=INFO`, `LOG_ROTATION=on`, `LOG_ROTATE_INTERVAL=1`, `LOG_BACKUP_COUNT=7`

## 🧰 start_all_streams.sh 동작 방식

- 스트림 수 감지: (1) 환경변수 `NUM_STREAMS` → (2) `.env.stream1` → (3) `.env.stream*` 최대 인덱스 → (4) 기본 6
- 로그 디렉토리: `.env.stream1`의 `LOG_DIR` → `.env.stream1`의 `FINAL_OUTPUT_PATH/logs` → `script_dir/logs`
- 각 스트림 실행(screen 세션명: `rtsp_stream{i}`)
  - `.env.stream{i}` → `.env.temp{i}` 복사 → DOTENV_PATH 지정 → `.env`로 복사 후 `uv run python -u run.py`
  - 표준출력 로그: `LOG_DIR/YYYY/MM/DD/rtsp_stream{i}_YYYYMMDD.log`
- 파일 이동 서비스(screen 세션명: `rtsp_file_mover`)
  - `.env.stream1`에서 로그 경로 결정 → `uv run python -u file_mover.py`
  - MP4 이동 완료 시 API 전송(파일 크기 MB 문자열)
- 시간 동기화(옵션, 주석 블록 제공)
  - `.env.stream1`의 `BLACKBOX_API_URL` 사용, 주기 `TIME_SYNC_INTERVAL_SEC`(환경변수 > `.env.stream1` > 기본 300초)

## 🔐 sudo 비밀번호 없이 시간 동기화 수행

1) 경로 확인
```bash
command -v timedatectl   # 예: /usr/bin/timedatectl
command -v hwclock       # 예: /sbin/hwclock 또는 /usr/sbin/hwclock
```
2) 편집
```bash
sudo visudo
```
3) 사용자(예: koast-user)에 대해 허용 추가
```text
koast-user ALL=(ALL) NOPASSWD: \
  /usr/bin/timedatectl set-ntp false, \
  /usr/bin/timedatectl set-time *, \
  /sbin/hwclock --systohc
```
4) 검증
```bash
sudo -l | grep -E 'timedatectl|hwclock' | cat
sudo timedatectl set-ntp false
sudo timedatectl set-time "2025-01-01 00:00:00"
sudo hwclock --systohc
```

## 🛠️ 트러블슈팅(uv)

- onnx/onnxsim 빌드 실패 → `cmake`/빌드 도구 설치 필요
  - 해결: `sudo apt-get install -y build-essential cmake ninja-build git python3-dev`
- PyTorch CUDA 등 특수 인덱스 필요 시
  ```bash
  uv pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision
  ```

## 🧠 ONNX 설치 가이드(필요 시)

- 언제 필요한가
  - PyTorch → ONNX 내보내기(export) 및 그래프 단순화(onnxsim)
  - ONNX 모델을 onnxruntime(CPU/GPU)로 직접 추론할 때
  - TensorRT 엔진(.engine/.plan)을 “생성”하기 전에 ONNX를 중간산출물로 사용할 때
  - 주의: 이미 빌드된 TensorRT 엔진을 “실행”만 할 때는 onnx/onnxsim/onnxruntime이 필요 없습니다

- 시스템 준비(권장)
  ```bash
  sudo apt-get install -y build-essential cmake ninja-build git python3-dev
  ```

- CPU용 ONNX/Runtime 설치
  ```bash
  uv pip install onnx onnxruntime onnxsim==0.4.33
  ```
  - onnxsim는 환경에 따라 휠이 없어 소스 빌드될 수 있습니다(cmake 필수)

- GPU용 onnxruntime 설치(선택)
  ```bash
  uv pip install onnx onnxruntime-gpu onnxsim==0.4.33
  ```
  - 로컬 CUDA/드라이버 호환성 확인 필요

- 예시: ONNX → TensorRT 엔진 생성
  ```bash
  # 1) PyTorch → ONNX export (모델/스크립트에 따라 상이)
  python export_to_onnx.py  # 예시

  # 2) onnxsim으로 그래프 단순화
  python -m onnxsim model.onnx model_simplified.onnx

  # 3) trtexec로 TensorRT 엔진 생성
  trtexec --onnx=model_simplified.onnx --saveEngine=model.engine --fp16
  ```

## 🧩 (선택) 레거시 가상환경(env-blur) 사용법 [[memory:3627098]]

uv가 제한된 환경에서는 아래 방식도 사용 가능합니다.
```bash
source ~/env-blur/bin/activate
uv pip sync requirements.txt
./generate_env.sh
./start_all_streams.sh
```

## 📄 라이선스

MIT License 
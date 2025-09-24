#!/bin/bash

# RTSP 스트림용 .env 파일 자동 생성 스크립트 (비인터랙티브 구성)
# 사용법: ./generate_env.sh
# 기본 규칙: RTSP_URL이 비어있으면 rtsp://<BASE_IP>:<PORT>/live 자동 생성

echo "📝 RTSP 스트림용 .env 파일 자동 생성"
echo "========================================"

# 기본 설정
BASE_IP="10.2.10.127"
START_PORT=1111
END_PORT=1116
VESSEL_NAME=${VESSEL_NAME:-vesselTest}

# 비트레이트 설정
TARGET_BITRATE=${TARGET_BITRATE:-2M}
MIN_BITRATE=${MIN_BITRATE:-1M}
MAX_BITRATE=${MAX_BITRATE:-3M}

# 블러 모듈 설정
export BLUR_MODULE_PATH=${BLUR_MODULE_PATH:-./blur_module/ipcamera_blur.py}
export BLUR_ENABLED=${BLUR_ENABLED:-true}
export BLUR_CONFIDENCE=${BLUR_CONFIDENCE:-0.5}

# 출력 설정
export TEMP_OUTPUT_PATH=${TEMP_OUTPUT_PATH:-./output/temp/}
export FINAL_OUTPUT_PATH=${FINAL_OUTPUT_PATH:-/mnt/nas/cam/}
export LOG_DIR=${LOG_DIR:-/mnt/nas/logs}
export DEFAULT_INPUT_FPS=${DEFAULT_INPUT_FPS:-15.0}
export VIDEO_SEGMENT_DURATION=${VIDEO_SEGMENT_DURATION:-300} # 영상 길이 설정
export VIDEO_WIDTH=${VIDEO_WIDTH:-1280}
export VIDEO_HEIGHT=${VIDEO_HEIGHT:-720}
export FRAME_QUEUE_SIZE=${FRAME_QUEUE_SIZE:-100}
export CONNECTION_TIMEOUT=${CONNECTION_TIMEOUT:-10}
export RECONNECT_INTERVAL=${RECONNECT_INTERVAL:-5}
export ENABLE_MONITORING=${ENABLE_MONITORING:-true}
export MONITORING_INTERVAL=${MONITORING_INTERVAL:-1.0}

# RTSP 송출 기본값
export RTSP_OUTPUT_ENABLED=${RTSP_OUTPUT_ENABLED:-true}
export RTSP_OUTPUT_TRANSPORT=${RTSP_OUTPUT_TRANSPORT:-tcp}
export RTSP_OUTPUT_BASE_URL=${RTSP_OUTPUT_BASE_URL:-rtsp://127.0.0.1:1111}
export RTSP_OUTPUT_PORT_START=${RTSP_OUTPUT_PORT_START:-1111}
export RTSP_OUTPUT_PER_STREAM_PORTS=${RTSP_OUTPUT_PER_STREAM_PORTS:-true}

# API 설정
export BLACKBOX_API_URL=${BLACKBOX_API_URL:-http://localhost}
export API_TIMEOUT=${API_TIMEOUT:-5}
export API_POLL_INTERVAL=${API_POLL_INTERVAL:-1.0}
export BLACKBOX_ENABLED=${BLACKBOX_ENABLED:-true}

# 녹화 조건 설정
export RECORDING_SPEED_THRESHOLD=${RECORDING_SPEED_THRESHOLD:-100}

# UPS 셧다운 대응: 파일 이동기 그레이스 종료 시간(초)
export FILE_MOVER_GRACE_SECONDS=${FILE_MOVER_GRACE_SECONDS:-15}

# ===================== 저지연/저부하 FFmpeg 기본값 =====================
export FFMPEG_OUTPUT_FPS=${FFMPEG_OUTPUT_FPS:-15}
export FFMPEG_KEYINT=${FFMPEG_KEYINT:-30}
export FFMPEG_PRESET=${FFMPEG_PRESET:-ultrafast}
export FFMPEG_TUNE=${FFMPEG_TUNE:-zerolatency}
# =====================================================================

# ===================== FFmpeg 로깅/디버깅 설정 =====================
# loglevel: quiet|panic|fatal|error|warning|info|verbose|debug|trace
export FFMPEG_LOGLEVEL=${FFMPEG_LOGLEVEL:-error}
# -report: ffmpeg 로그 리포트 파일 자동 생성 여부
export FFMPEG_REPORT=${FFMPEG_REPORT:-false}
# -stats: 진행 통계 출력 여부
export FFMPEG_STATS=${FFMPEG_STATS:-false}
# -debug 플래그 (예: ts,timestamp,mb_type). 비우면 적용 안함
export FFMPEG_DEBUG=${FFMPEG_DEBUG:-}
# -rtsp_flags 값 (예: prefer_tcp,listen,rtcp_to_source)
export FFMPEG_RTSP_FLAGS=${FFMPEG_RTSP_FLAGS:-}
# ==================================================================

# =============================================================================
# 사용자 설정: 스트림 개수 & RTSP URL 목록 (여기를 수정해서 사용)
# - NUM_STREAMS: 생성할 스트림 수 (기본 6)
# - RTSP_URLS: 각 스트림의 URL을 배열에 순서대로 기입
#   비워두거나 부족하면 BASE_IP/START_PORT 규칙으로 자동 채움
# =============================================================================
# 스트림 개수 설정  
NUM_STREAMS=${NUM_STREAMS:-6}

# 아래 URL을 원하는 URL로 교체하세요
RTSP_URLS=(
    "rtsp://root:root@192.168.1.101:554/cam0_0"
    "rtsp://root:root@192.168.1.102:554/cam0_0"
    "rtsp://root:root@192.168.1.103:554/cam0_0"
    "rtsp://root:root@192.168.1.104:554/cam0_0"
    "rtsp://10.2.10.158:1115/live"
    "rtsp://10.2.10.158:1116/live"
)

# 정수 유효성 체크
if ! [[ "$NUM_STREAMS" =~ ^[0-9]+$ ]] || [ "$NUM_STREAMS" -le 0 ]; then
    echo "❌ 유효하지 않은 스트림 개수: $NUM_STREAMS" >&2
    exit 1
fi

echo "🔧 스트림 개수: ${NUM_STREAMS}"

# URL 정규화 (부족분은 기본 규칙으로 채움, 초과분은 무시)
declare -a RTSP_URLS_NORMALIZED
for i in $(seq 1 ${NUM_STREAMS}); do
    if [ ${#RTSP_URLS[@]} -ge $i ] && [ -n "${RTSP_URLS[$((i-1))]}" ]; then
        url="${RTSP_URLS[$((i-1))]}"
    else
        DEFAULT_PORT=$((START_PORT + i - 1))
        url="rtsp://${BASE_IP}:${DEFAULT_PORT}/live"
    fi
    RTSP_URLS_NORMALIZED[$i]="$url"
    echo "   → 스트림 ${i}: ${RTSP_URLS_NORMALIZED[$i]}"
done

# 스트림용 .env 파일 생성
for i in $(seq 1 ${NUM_STREAMS}); do
    RTSP_URL="${RTSP_URLS_NORMALIZED[$i]}"
    STREAM_NUMBER=$i
    ENV_FILE=".env.stream${i}"

    echo ""
    echo "🔄 스트림 ${i} .env 파일 생성 중..."
    echo "   URL: $RTSP_URL"
    echo "   선박명: $VESSEL_NAME"
    echo "   파일: $ENV_FILE"
    

    # 산출 송출 호스트/포트 (BASE_URL의 포트 유무와 관계없이 host만 추출 후 포트 적용)
    RTSP_OUTPUT_HOST=127.0.0.1
    RTSP_OUTPUT_BASE_PORT=$(echo "${RTSP_OUTPUT_BASE_URL}" | sed -E 's#^rtsp://[^/:]+:([0-9]+).*$#\1#')
    if [[ "${RTSP_OUTPUT_BASE_PORT}" == "${RTSP_OUTPUT_BASE_URL}" ]]; then
        RTSP_OUTPUT_BASE_PORT=""
    fi
    if [ "${RTSP_OUTPUT_PER_STREAM_PORTS}" = "true" ]; then
        RTSP_OUTPUT_PORT=$((RTSP_OUTPUT_PORT_START + STREAM_NUMBER - 1))
    else
        if [ -n "${RTSP_OUTPUT_BASE_PORT}" ]; then
            RTSP_OUTPUT_PORT="${RTSP_OUTPUT_BASE_PORT}"
        else
            RTSP_OUTPUT_PORT="${RTSP_OUTPUT_PORT_START}"
        fi
    fi
    echo "   RTSP 송출 URL: rtsp://${RTSP_OUTPUT_HOST}:${RTSP_OUTPUT_PORT}/live"
    
    cat > "$ENV_FILE" << EOF
# RTSP Multithread Processor 환경변수 설정 - 스트림 ${i}
# 자동 생성: $(date)
# 생성 스크립트: generate_env.sh
# RTSP URL: $RTSP_URL

# =============================================================================
# 필수 설정 - 스트림 ${i}
# =============================================================================
RTSP_URL=$RTSP_URL
VESSEL_NAME=$VESSEL_NAME
STREAM_NUMBER=$STREAM_NUMBER
# 카메라 식별자 (필요에 맞게 수정해서 사용)
CAMERA_ID=
CAMERA_NAME=
 
 # =============================================================================
 # 블러 처리 설정
# =============================================================================
BLUR_MODULE_PATH=$BLUR_MODULE_PATH
BLUR_ENABLED=$BLUR_ENABLED
BLUR_CONFIDENCE=$BLUR_CONFIDENCE

# =============================================================================
# 출력 설정
# =============================================================================
TEMP_OUTPUT_PATH=$TEMP_OUTPUT_PATH
FINAL_OUTPUT_PATH=$FINAL_OUTPUT_PATH
LOG_DIR=$LOG_DIR
DEFAULT_INPUT_FPS=$DEFAULT_INPUT_FPS
VIDEO_SEGMENT_DURATION=$VIDEO_SEGMENT_DURATION

# 영상 해상도 설정
VIDEO_WIDTH=$VIDEO_WIDTH
VIDEO_HEIGHT=$VIDEO_HEIGHT

# =============================================================================
# 성능 설정
# =============================================================================
FRAME_QUEUE_SIZE=$FRAME_QUEUE_SIZE
CONNECTION_TIMEOUT=$CONNECTION_TIMEOUT
RECONNECT_INTERVAL=$RECONNECT_INTERVAL

# =============================================================================
# 모니터링 설정
# =============================================================================
ENABLE_MONITORING=$ENABLE_MONITORING
MONITORING_INTERVAL=$MONITORING_INTERVAL

# =============================================================================
# API 설정
# =============================================================================
BLACKBOX_ENABLED=$BLACKBOX_ENABLED
BLACKBOX_API_URL=$BLACKBOX_API_URL
API_TIMEOUT=$API_TIMEOUT
API_POLL_INTERVAL=$API_POLL_INTERVAL

# =============================================================================
# 녹화 조건 설정
# =============================================================================
RECORDING_SPEED_THRESHOLD=$RECORDING_SPEED_THRESHOLD

# =============================================================================
# 고급 설정 (필요시 주석 해제하여 사용)
# =============================================================================
LOG_LEVEL=INFO
LOG_ROTATION=on
LOG_ROTATE_INTERVAL=1
LOG_BACKUP_COUNT=7

# UPS 셧다운 대응: 파일 이동기 그레이스 종료 시간(초)
FILE_MOVER_GRACE_SECONDS=$FILE_MOVER_GRACE_SECONDS

# FFmpeg 저지연 설정
FFMPEG_PRESET=$FFMPEG_PRESET
FFMPEG_TUNE=$FFMPEG_TUNE
FFMPEG_TARGET_BITRATE=$TARGET_BITRATE
FFMPEG_MIN_BITRATE=$MIN_BITRATE
FFMPEG_MAX_BITRATE=$MAX_BITRATE
FFMPEG_OUTPUT_FPS=$FFMPEG_OUTPUT_FPS
FFMPEG_KEYINT=$FFMPEG_KEYINT

# FFmpeg 로깅/디버깅 설정
FFMPEG_LOGLEVEL=$FFMPEG_LOGLEVEL
FFMPEG_REPORT=$FFMPEG_REPORT
FFMPEG_STATS=$FFMPEG_STATS
FFMPEG_DEBUG=$FFMPEG_DEBUG
FFMPEG_RTSP_FLAGS=$FFMPEG_RTSP_FLAGS

# =============================================================================
# RTSP 송출 설정
# =============================================================================
RTSP_OUTPUT_ENABLED=$RTSP_OUTPUT_ENABLED
RTSP_OUTPUT_TRANSPORT=$RTSP_OUTPUT_TRANSPORT
# 스트림별 송출 URL (host는 BASE_URL에서 추출, 포트는 계산값)
RTSP_OUTPUT_URL=rtsp://${RTSP_OUTPUT_HOST}:${RTSP_OUTPUT_PORT}/live
EOF

    echo "   ✅ $ENV_FILE 생성 완료"
done

# 출력 디렉토리 생성
if [ ! -d "$TEMP_OUTPUT_PATH" ]; then
    mkdir -p "$TEMP_OUTPUT_PATH"
    echo "📁 임시 출력 디렉토리 생성: $TEMP_OUTPUT_PATH"
fi

if [ ! -d "$FINAL_OUTPUT_PATH" ]; then
    mkdir -p "$FINAL_OUTPUT_PATH"
    echo "📁 최종 출력 디렉토리 생성: $FINAL_OUTPUT_PATH"
fi

echo ""
echo "✅ ${NUM_STREAMS}개 스트림용 .env 파일 생성 완료!"
echo ""
echo "📄 생성된 파일들:"
for i in $(seq 1 ${NUM_STREAMS}); do
    ENV_FILE=".env.stream${i}"
    FILE_SIZE=$(wc -c < "$ENV_FILE")
    URL_PRINT="${RTSP_URLS_NORMALIZED[$i]}"
    echo "   $ENV_FILE (${FILE_SIZE} bytes) - $URL_PRINT"
done

# 블러 모듈 확인
echo ""
if [ -f "$BLUR_MODULE_PATH" ]; then
    echo "블러 모듈: ✅ 존재 ($BLUR_MODULE_PATH)"
else
    echo "블러 모듈: ⚠️  없음 - 기본 블러 사용 ($BLUR_MODULE_PATH)"
fi

echo ""
echo "📋 현재 설정:"
echo "   선박명: $VESSEL_NAME"
echo "   비디오 저장 간격: ${VIDEO_SEGMENT_DURATION}초"
echo "   해상도: ${VIDEO_WIDTH}x${VIDEO_HEIGHT}"
echo "   타겟 비트레이트: $TARGET_BITRATE"
echo "   최소 비트레이트: $MIN_BITRATE"
echo "   최대 비트레이트: $MAX_BITRATE"

echo ""
echo "💡 비트레이트 변경 방법:"
echo "   환경변수 설정: TARGET_BITRATE=8M MIN_BITRATE=2M MAX_BITRATE=15M ./generate_env.sh"
echo "   또는 스크립트 상단의 비트레이트 설정 부분 직접 수정"

echo ""
echo "🚀 실행 준비 완료!"
echo "   개별 실행: uv run python run.py (.env.streamX 파일을 .env로 복사 후)"
echo "   전체 실행: ./start_all_streams.sh" 

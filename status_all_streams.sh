#!/bin/bash

# RTSP 스트림 상태 확인 스크립트
# 사용법: ./status_all_streams.sh

BASE_SESSION_NAME="rtsp_stream"
FILE_MOVER_SESSION="rtsp_file_mover"
BASE_IP="10.2.10.158"      # Fallback 용
START_PORT=1111             # Fallback 용

# 스크립트/로그 경로
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_BASE_DIR="$SCRIPT_DIR"
ENV_REF="$ENV_BASE_DIR/.env.stream1"

# 로그 디렉터리: .env.stream1의 LOG_DIR > .env.stream1의 FINAL_OUTPUT_PATH/logs > SCRIPT_DIR/logs
env_log_dir=""
env_final_output=""
if [ -f "$ENV_REF" ]; then
  env_log_dir=$(grep -E '^LOG_DIR=' "$ENV_REF" | tail -n1 | cut -d= -f2-)
  env_final_output=$(grep -E '^FINAL_OUTPUT_PATH=' "$ENV_REF" | tail -n1 | cut -d= -f2-)
fi
if [ -n "$env_log_dir" ]; then
  LOGS_DIR="$env_log_dir"
elif [ -n "$env_final_output" ]; then
  LOGS_DIR="$env_final_output/logs"
else
  LOGS_DIR="$SCRIPT_DIR/logs"
fi

# 스트림 개수 결정: ENV > .env.stream1(NUM_STREAMS) > 디렉토리 내 파일 개수 추론 > 기본 6
NUM_STREAMS_CANDIDATE="${NUM_STREAMS:-}"
if [ -z "$NUM_STREAMS_CANDIDATE" ] && [ -f "$ENV_REF" ]; then
  NUM_STREAMS_CANDIDATE=$(grep -E '^NUM_STREAMS=' "$ENV_REF" | tail -n1 | cut -d= -f2-)
fi
if ! [[ "$NUM_STREAMS_CANDIDATE" =~ ^[0-9]+$ ]] || [ "$NUM_STREAMS_CANDIDATE" -le 0 ]; then
  NUM_STREAMS_CANDIDATE=$(ls -1 "$ENV_BASE_DIR"/.env.stream* 2>/dev/null | sed -n 's/.*\.env\.stream\([0-9]\+\)$/\1/p' | sort -n | tail -n1)
fi
if ! [[ "$NUM_STREAMS_CANDIDATE" =~ ^[0-9]+$ ]] || [ "$NUM_STREAMS_CANDIDATE" -le 0 ]; then
  NUM_STREAMS=6
else
  NUM_STREAMS=$NUM_STREAMS_CANDIDATE
fi

# 현재 시간
echo "📊 ${NUM_STREAMS}개 RTSP 스트림 상태 확인"
echo "=========================="
echo "확인 시간(UTC): $(date -u)"
echo ""

# Screen 세션 상태
echo "🖥️  Screen 세션 상태:"
running_streams=$(screen -list | grep "${BASE_SESSION_NAME}" | wc -l)
running_mover=$(screen -list | grep "${FILE_MOVER_SESSION}" | wc -l)
echo "   RTSP 스트림 세션: $running_streams / ${NUM_STREAMS}"
echo "   파일 이동 세션: $running_mover / 1"

if [ "$running_streams" -gt 0 ] || [ "$running_mover" -gt 0 ]; then
    screen -list | grep -E "${BASE_SESSION_NAME}|${FILE_MOVER_SESSION}" | sed 's/^/   /'
else
    echo "   ❌ 실행 중인 세션이 없습니다"
fi

echo ""

# 외부 접속용 IP (첫 번째 인터페이스 IP)
LOCAL_IP=$(hostname -I | awk '{print $1}')
if [ -z "$LOCAL_IP" ]; then
  LOCAL_IP="$BASE_IP"
fi

# 개별 스트림 상태
echo "🎬 개별 스트림 상태:"
for i in $(seq 1 ${NUM_STREAMS}); do
    session_name="${BASE_SESSION_NAME}${i}"
    env_file="$ENV_BASE_DIR/.env.stream${i}"

    # 송출 URL: 환경파일의 RTSP_OUTPUT_URL에서 host를 LOCAL_IP로 치환
    rtsp_output_url=""
    if [ -f "$env_file" ]; then
        raw_out=$(grep -E '^RTSP_OUTPUT_URL=' "$env_file" | tail -n1 | cut -d= -f2- | tr -d '"')
        if [ -n "$raw_out" ]; then
            port=$(echo "$raw_out" | sed -E 's#^rtsp://[^/:]+:([0-9]+).*#\1#')
            path=$(echo "$raw_out" | sed -E 's#^rtsp://[^/]+(/.*)$#\1#')
            if [ -z "$port" ]; then port=$((START_PORT + i - 1)); fi
            if [ -z "$path" ]; then path="/live"; fi
            rtsp_output_url="rtsp://${LOCAL_IP}:${port}${path}"
        fi
    fi
    if [ -z "$rtsp_output_url" ]; then
        port=$((START_PORT + i - 1))
        rtsp_output_url="rtsp://${LOCAL_IP}:${port}/live"
    fi

    current_date=$(date -u +%Y%m%d)
    date_dir=$(date -u +%Y/%m/%d)
    log_file="$LOGS_DIR/$date_dir/rtsp_stream${i}_${current_date}.log"
    
    echo ""
    echo "   📡 스트림 ${i}:"
    echo "      외부 접속 URL: $rtsp_output_url"
    
    # 세션 상태
    if screen -list | grep -q "$session_name"; then
        echo "      세션: ✅ 실행 중 ($session_name)"
    else
        echo "      세션: ❌ 중지됨"
    fi
    
    # 설정 파일 상태
    if [ -f "$env_file" ]; then
        echo "      설정: ✅ $env_file 존재"
    else
        echo "      설정: ❌ $env_file 없음"
    fi
    
    # 로그 파일 상태
    if [ -f "$log_file" ]; then
        file_size=$(wc -c < "$log_file" 2>/dev/null || echo "0")
        line_count=$(wc -l < "$log_file" 2>/dev/null || echo "0")
        last_modified=$(stat -c %y "$log_file" 2>/dev/null || echo "알 수 없음")
        echo "      로그: ✅ $(basename "$log_file") (${file_size} bytes, ${line_count} lines)"
        echo "            최종 수정: $last_modified"
        # 최근 에러
        if [ -s "$log_file" ]; then
            last_line=$(tail -n 1 "$log_file" 2>/dev/null || echo "")
            if echo "$last_line" | grep -i "error\|fail\|exception" > /dev/null; then
                echo "      ⚠️  최근 에러 감지: $last_line"
            fi
        fi
    else
        echo "      로그: ❌ $(basename "$log_file") 없음 (LOGS_DIR=$LOGS_DIR)"
    fi

done

echo ""

# 시스템 리소스 상태
echo "🖥️  시스템 리소스:"

# Python 프로세스 확인
python_processes=$(pgrep -f "python.*run.py" | wc -l)
echo "   Python 프로세스: $python_processes 개"

# CPU 사용률
if command -v top &> /dev/null; then
    cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | sed 's/%us,//')
    echo "   CPU 사용률: ${cpu_usage}%"
fi

# 메모리 사용률
if command -v free &> /dev/null; then
    memory_info=$(free | grep Mem | awk '{printf "%.1f%%", $3/$2 * 100}')
    echo "   메모리 사용률: $memory_info"
fi

# 디스크 사용률 (로그/출력 디렉터리)
if command -v du &> /dev/null; then
    if [ -d "$LOGS_DIR" ]; then
        logs_size=$(du -sh "$LOGS_DIR" 2>/dev/null | awk '{print $1}')
        echo "   로그 폴더 용량($LOGS_DIR): $logs_size"
    fi
fi

echo ""

# 출력 디렉토리 상태
echo "📁 출력 디렉토리 상태:"
output_dir="$env_final_output"
if [ -d "$output_dir" ]; then
    video_count=$(find "$output_dir" -name "*.mp4" | wc -l)
    temp_count=$(find "$output_dir" -name "temp_*.mp4" | wc -l)
    total_size=$(du -sh "$output_dir" 2>/dev/null | awk '{print $1}')
    
    echo "   디렉토리: ✅ $output_dir"
    echo "   완료된 영상: $video_count 개"
    echo "   진행 중 영상: $temp_count 개"
    echo "   총 용량: $total_size"
    
    # 최근 생성된 파일
    if [ "$video_count" -gt 0 ]; then
        echo "   최근 파일:"
        find "$output_dir" -name "*.mp4" -not -name "temp_*" -printf "      %TY-%Tm-%Td %TH:%TM %f\n" | sort -r | head -${NUM_STREAMS}
    fi
else
    echo "   디렉토리: ❌ $output_dir 없음"
fi

echo ""

# 빠른 액션 가이드
echo "🔧 빠른 액션:"
echo "   전체 시작: ./start_all_streams.sh"
echo "   전체 중지: ./stop_all_streams.sh"
echo "   특정 세션 접속: screen -r rtsp_stream1 (1~${NUM_STREAMS})"
echo "   실시간 로그: tail -f "$LOGS_DIR/$(date -u +%Y/%m/%d)/rtsp_stream1_$(date -u +%Y%m%d).log" (1~${NUM_STREAMS})"

# 파일 이동 서비스 제어
running_mover=$(screen -list | grep "${FILE_MOVER_SESSION}" | wc -l)
if [ "$running_mover" -gt 0 ]; then
    echo ""
    echo "📦 파일 이동 서비스 제어:"
    echo "   접속: screen -r $FILE_MOVER_SESSION"
    echo "   로그: tail -f "$LOGS_DIR/$(date -u +%Y/%m/%d)/file_mover_$(date -u +%Y%m%d).log""
fi 

#!/bin/bash

# 6개 RTSP 스트림 중지 스크립트
# 사용법: ./stop_all_streams.sh

echo "🛑 6개 RTSP 스트림 + 파일 이동 서비스 중지"
echo "========================================="

BASE_SESSION_NAME="rtsp_stream"
FILE_MOVER_SESSION="rtsp_file_mover"
# 프로필 기반 설정 (sim/camera 등)
PROFILE="${PROFILE:-sim}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_BASE_DIR="$SCRIPT_DIR/profiles/$PROFILE"
ALT_ENV_DIR="$SCRIPT_DIR"

# 실행 중인 세션 확인
echo "📋 실행 중인 세션 확인..."
running_streams=$(screen -list | grep "${BASE_SESSION_NAME}" | wc -l)
running_mover=$(screen -list | grep "${FILE_MOVER_SESSION}" | wc -l)
total_sessions=$((running_streams + running_mover))

if [ "$total_sessions" -eq 0 ]; then
    echo "❌ 실행 중인 세션이 없습니다"
    # MediaMTX 종료 시도는 계속 수행
else
    echo "   RTSP 스트림 세션: $running_streams 개"
    echo "   파일 이동 세션: $running_mover 개"
    screen -list | grep -E "${BASE_SESSION_NAME}|${FILE_MOVER_SESSION}" | sed 's/^/   /'

    echo ""
    echo "🔄 세션 중지 중..."

    # 6개 스트림 세션 중지
    stopped_count=0
    for i in {1..6}; do
        session_name="${BASE_SESSION_NAME}${i}"
        
        if screen -list | grep -q "$session_name"; then
            echo "   중지 중: $session_name"
            screen -S "$session_name" -X quit 2>/dev/null
            
            # 중지 확인
            sleep 1
            if ! screen -list | grep -q "$session_name"; then
                echo "   ✅ $session_name 중지됨"
                stopped_count=$((stopped_count + 1))
            else
                echo "   ❌ $session_name 중지 실패"
            fi
        fi
    done

    # 저장 중이던 temp_ 파일 이름 변경 (finalize) 처리 - 파일 이동기가 아직 살아있는 동안 수행
    echo ""
    echo "📦 저장 중 파일 정리(이름 변경) 진행..."

    get_env_val() {
	# 사용: get_env_val KEY FILE
	local key="$1"; local file="$2"
	local val
	val=$(grep -E "^${key}=" "$file" 2>/dev/null | tail -n1 | cut -d= -f2-)
	echo "$val"
}

    for i in {1..6}; do
	env_file="$ENV_BASE_DIR/.env.stream${i}"
	if [ ! -f "$env_file" ]; then
		# 프로필 디렉터리에 없으면 현재 디렉터리(.env.streamX)로 폴백
		env_file="$ALT_ENV_DIR/.env.stream${i}"
	fi
	# 경로 추출 (기본값 보정)
	if [ -f "$env_file" ]; then
		temp_output_path=$(get_env_val TEMP_OUTPUT_PATH "$env_file"); [ -n "$temp_output_path" ] || temp_output_path="./output/temp/"
	else
		echo "   ℹ️  스트림 ${i}: env 파일 없음, 기본 경로로 처리"
		temp_output_path="./output/temp/"
	fi
	# temp_ mp4만 대상 (우선)
	shopt -s nullglob
	pending_files=("$temp_output_path"/temp_*.mp4)
	shopt -u nullglob
	if [ ${#pending_files[@]} -gt 0 ]; then
		echo "   스트림 ${i}: $temp_output_path 내 temp_ MP4 처리 ${#pending_files[@]}개"
		for f in "${pending_files[@]}"; do
			base=$(basename "$f")
			final_name="${base#temp_}"
			if mv -f -- "$f" "$temp_output_path/$final_name"; then
				echo "      ▶ ${base} → ${final_name}"
			else
				echo "      ⚠️  이름 변경 실패: ${base}"
			fi
		done
	fi
	# temp_ srt도 함께 처리 (watcher가 srt 단독 rename도 감지 가능)
	shopt -s nullglob
	pending_srt=("$temp_output_path"/temp_*.srt)
	shopt -u nullglob
	if [ ${#pending_srt[@]} -gt 0 ]; then
		echo "   스트림 ${i}: $temp_output_path 내 temp_ SRT 처리 ${#pending_srt[@]}개"
		for f in "${pending_srt[@]}"; do
			base=$(basename "$f")
			final_name="${base#temp_}"
			if mv -f -- "$f" "$temp_output_path/$final_name"; then
				echo "      ▶ ${base} → ${final_name}"
			else
				echo "      ⚠️  이름 변경 실패: ${base}"
			fi
		done
	fi
    done

    # 파일 이동기(Watcher)가 변경을 처리할 시간 대기
    echo "   파일 이동기 처리 대기..."
    sleep 3

    echo ""
    echo "🧹 임시 파일 정리 중..."

    # 임시 .env 파일 정리
    temp_files_removed=0
    for i in {1..6}; do
        temp_file=".env.temp${i}"
        if [ -f "$temp_file" ]; then
            rm -f "$temp_file"
            echo "   삭제: $temp_file"
            temp_files_removed=$((temp_files_removed + 1))
        fi
    done

    # .env 파일 정리 (임시로 생성된 것)
    if [ -f ".env" ]; then
        echo "   정리: .env (임시 파일)"
        rm -f ".env"
    fi

    echo ""
    echo "📊 중지 결과:"
    echo "   중지된 세션: $stopped_count / 6"
    echo "   정리된 임시 파일: $temp_files_removed 개"

    # 남은 세션 확인
    remaining_sessions=$(screen -list | grep "${BASE_SESSION_NAME}" | wc -l)
    if [ "$remaining_sessions" -gt 0 ]; then
        echo ""
        echo "⚠️  아직 남은 세션이 있습니다:"
        screen -list | grep "${BASE_SESSION_NAME}" | sed 's/^/   /'
        echo ""
        echo "강제 종료하려면:"
        echo "   screen -wipe  # 죽은 세션 정리"
        echo "   pkill -f 'run.py'  # Python 프로세스 강제 종료"
    else
        echo ""
        echo "✅ 모든 RTSP 스트림이 성공적으로 중지되었습니다!"
    fi

    echo ""
    echo "🔄 파일 이동 서비스 중지 중..."

    # 파일 이동 서비스 중지
    if screen -list | grep -q "$FILE_MOVER_SESSION"; then
        echo "   ${FILE_MOVER_SESSION} 세션 중지 중..."
        screen -S "$FILE_MOVER_SESSION" -X quit 2>/dev/null
        sleep 2
        
        if screen -list | grep -q "$FILE_MOVER_SESSION"; then
            echo "   ⚠️  ${FILE_MOVER_SESSION} 세션이 아직 실행 중입니다"
        else
            echo "   ✅ ${FILE_MOVER_SESSION} 세션 중지 완료"
        fi
    else
        echo "   ℹ️  파일 이동 서비스가 실행되지 않음"
    fi

    echo ""
    echo "📁 로그 파일들은 보존됩니다:"
    for i in {1..6}; do
        log_file="rtsp_stream${i}.log"
        if [ -f "$log_file" ]; then
            file_size=$(wc -c < "$log_file")
            echo "   $log_file (${file_size} bytes)"
        fi
    done

    echo ""
    echo "💡 로그 파일 관리:"
    echo "   전체 로그 확인: tail -f rtsp_stream*.log"
    echo "   로그 파일 삭제: rm -f rtsp_stream*.log"
    echo "   로그 파일 압축: tar -czf logs_$(date +%Y%m%d_%H%M%S).tar.gz rtsp_stream*.log" 
fi

# ---------------------- MediaMTX 인스턴스 종료 ----------------------
echo ""
echo "🛑 MediaMTX 인스턴스 중지"
if pgrep -f mediamtx > /dev/null; then
    pkill -f mediamtx
    sleep 3
    if pgrep -f mediamtx > /dev/null; then
        pkill -9 -f mediamtx
        echo "   강제 종료되었습니다."
    else
        echo "   정상 종료되었습니다."
    fi
else
    echo "   실행 중인 MediaMTX 인스턴스가 없습니다."
fi
# ------------------------------------------------------------------ 
pkill start_all_streams.sh
pkill run_daemon.py

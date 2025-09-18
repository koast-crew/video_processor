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
    echo "🔔 run.py 프로세스에 SIGTERM 전송(그레이스풀 종료 유도)..."
    # uv 파이프라인/직접 실행 모두 대비하여 두 패턴에 신호 전송
    pkill -TERM -f "python -u run.py" 2>/dev/null || true
    pkill -TERM -f "uv run python -u run.py" 2>/dev/null || true
    # 최대 10초 대기(FFmpeg finalize 및 파일 rename 시간)
    for sec in $(seq 1 10); do
        if pgrep -f "run.py" >/dev/null 2>&1; then
            echo "   ⏳ finalize 대기 ${sec}/10초..."
            sleep 1
        else
            break
        fi
    done

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

    # 저장 중이던 temp_ 파일 이름 변경 (finalize) 처리 - 파일 이동기가 살아있는 동안 on_moved 이벤트로 이동됨
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
            # 크기 안정화 대기: 3회 연속 동일 크기이면 rename 진행
            stable=false
            prev_size=-1
            same_count=0
            for t in {1..15}; do
                if [ ! -f "$f" ]; then break; fi
                sz=$(stat -c %s "$f" 2>/dev/null || echo 0)
                if [ "$sz" -eq "$prev_size" ] && [ "$prev_size" -ge 0 ]; then
                    same_count=$((same_count+1))
                    if [ "$same_count" -ge 3 ]; then
                        stable=true; break
                    fi
                else
                    same_count=0
                    prev_size="$sz"
                fi
                sleep 1
            done
            # lsof로 열림 여부 확인(열려 있으면 보류)
            if command -v lsof >/dev/null 2>&1; then
                if lsof "$f" >/dev/null 2>&1; then
                    echo "      ⚠️  파일 핸들 열림 상태: ${base} (rename 보류)"
                    continue
                fi
            fi
            if [ "$stable" != true ]; then
                echo "      ⚠️  크기 불안정: ${base} (rename 보류)"
                continue
            fi
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
            if command -v lsof >/dev/null 2>&1; then
                if lsof "$f" >/dev/null 2>&1; then
                    echo "      ⚠️  파일 핸들 열림 상태: ${base} (rename 보류)"
                    continue
                fi
            fi
            if mv -f -- "$f" "$temp_output_path/$final_name"; then
				echo "      ▶ ${base} → ${final_name}"
                # 완료 마커 사용하지 않음 (이벤트/안정화 기반 이동)
			else
				echo "      ⚠️  이름 변경 실패: ${base}"
			fi
		done
	fi
    done

    # 파일 이동기(Watcher)가 변경을 처리할 시간 대기
    echo "   파일 이동기 처리 대기..."
    sleep 3

    # 최종 반복 스윕: temp 내 최종명(mp4/srt) 파일을 패턴 기반으로 최종 경로로 이동
    echo ""
    echo "🔁 최종 스윕 반복 수행..."
    final_sweep_max=${FINAL_SWEEP_SECONDS:-20}
    for pass in $(seq 1 $final_sweep_max); do
        moved_count=0
        for i in {1..6}; do
            env_file="$ENV_BASE_DIR/.env.stream${i}"
            [ -f "$env_file" ] || env_file="$ALT_ENV_DIR/.env.stream${i}"
            if [ -f "$env_file" ]; then
                temp_output_path=$(get_env_val TEMP_OUTPUT_PATH "$env_file"); [ -n "$temp_output_path" ] || temp_output_path="./output/temp/"
                final_output_path=$(get_env_val FINAL_OUTPUT_PATH "$env_file"); [ -n "$final_output_path" ] || final_output_path="/mnt/raid5"
            else
                temp_output_path="./output/temp/"; final_output_path="/mnt/raid5"
            fi
            shopt -s nullglob
            for f in "$temp_output_path"/*.mp4 "$temp_output_path"/*.srt; do
                [ -e "$f" ] || continue
                bn=$(basename "$f")
                [[ "$bn" == temp_* ]] && continue
                if [[ "$bn" =~ _([0-9]{6})_([0-9]{6})\.(mp4|srt)$ ]]; then
                    date_part="${BASH_REMATCH[1]}"; time_part="${BASH_REMATCH[2]}"
                    year=$((10#${date_part:0:2} + 2000))
                    month=${date_part:2:2}; day=${date_part:4:2}; hour=${time_part:0:2}
                    target_dir="$final_output_path/$year/$month/$day/$hour"
                    mkdir -p "$target_dir"
                    if mv -f -- "$f" "$target_dir/$bn"; then
                        echo "   ▶ 스윕 이동: $bn → $target_dir/"
                        moved_count=$((moved_count+1))
                    fi
                fi
            done
            shopt -u nullglob
        done
        if [ "$moved_count" -eq 0 ]; then
            echo "   (pass $pass/$final_sweep_max) 추가 이동 없음"
            break
        else
            echo "   (pass $pass/$final_sweep_max) 이동 처리: $moved_count"
            sleep 1
        fi
    done

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

    # 파일 이동기는 스트림 종료 이후 남은 파일을 처리할 시간을 가진 뒤 종료
    if pgrep -f "file_mover.py" >/dev/null 2>&1; then
        echo "   ▶ file_mover.py에 SIGTERM 전송 (그레이스 5초)"
        pkill -TERM -f "python -u file_mover.py" 2>/dev/null || true
        pkill -TERM -f "uv run python -u file_mover.py" 2>/dev/null || true
        for sec in $(seq 1 5); do
            if pgrep -f "file_mover.py" >/dev/null 2>&1; then
                echo "      ⏳ 파일 이동기 그레이스 종료 대기 ${sec}/5초..."
                sleep 1
            else
                break
            fi
        done
    fi
    # 남아있으면 screen 레벨에서 종료 시도
    if screen -list | grep -q "$FILE_MOVER_SESSION"; then
        screen -S "$FILE_MOVER_SESSION" -X quit 2>/dev/null
        sleep 1
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

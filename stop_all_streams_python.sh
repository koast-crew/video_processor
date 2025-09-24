#!/bin/bash

# Python 버전 스트림 중지 스크립트 (기존 stop_all_streams.sh의 Python 버전)
# 사용법: ./stop_all_streams_python.sh

echo "🐍 Python 버전 스트림 중지 스크립트 실행"
echo "========================================"

# 스크립트 디렉토리 설정
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE="${PROFILE:-sim}"

# Python 스크립트 실행
python3 "$SCRIPT_DIR/stop_streams.py" \
    --profile "$PROFILE" \
    --script-dir "$SCRIPT_DIR" \
    --num-streams 6 \
    --debug

echo ""
echo "✅ Python 스크립트 실행 완료"

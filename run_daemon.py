#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import signal
import subprocess
import sys
import time
import logging
from logging.handlers import SysLogHandler
import os

# syslog 로깅 설정
logger = logging.getLogger('stream_daemon')
logger.setLevel(logging.INFO)

# syslog 핸들러 설정. /dev/log가 없으면 UDP로 전송
if os.path.exists('/dev/log'):
    handler = SysLogHandler(address='/dev/log')
else:
    handler = SysLogHandler()  # 기본값: localhost:514
formatter = logging.Formatter('%(name)s[%(process)d]: %(levelname)s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# 스크립트 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
START_SCRIPT = os.path.join(SCRIPT_DIR, 'start_all_streams.sh')
STOP_SCRIPT = os.path.join(SCRIPT_DIR, 'stop_all_streams.sh')

def signal_handler(signum, frame):
    """SIGTERM, SIGINT 신호 처리기"""
    logger.info(f"신호 {signum} 수신. 데몬을 종료합니다.")
    
    try:
        logger.info("SIGTERM/SIGINT 수신. stop_all_streams.sh 실행 시작...")
    except Exception:
        pass
    try:
        # 종료시 journald/syslog가 먼저 내려갈 수 있으므로 출력 캡처 없이 실행
        subprocess.run([STOP_SCRIPT], timeout=180)
    except Exception as e:
        try:
            logger.error(f"stop_all_streams.sh 실행 중 예외: {e}")
        except Exception:
            pass
    finally:
        try:
            logger.info("데몬 종료 완료.")
        except Exception:
            pass
    sys.exit(0)

def main():
    """데몬을 시작하는 메인 함수"""
    logger.info("RTSP 스트림 데몬 시작.")

    # 신호 처리기 등록
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info(f"{START_SCRIPT} 실행 중...")
    try:
        # Popen으로 백그라운드에서 실행. start 스크립트는 screen 세션을 시작하고 종료됩니다.
        start_process = subprocess.Popen([START_SCRIPT], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        
        # 시작 스크립트의 출력을 로깅하는 것이 좋습니다.
        stdout, stderr = start_process.communicate()
        
        if start_process.returncode == 0:
            logger.info(f"{START_SCRIPT} 실행 완료.")
            if stdout:
                logger.info(f"시작 스크립트 stdout:\n{stdout}")
            if stderr:
                logger.warning(f"시작 스크립트 stderr:\n{stderr}")
        else:
            logger.error(f"{START_SCRIPT} 실행 실패. 종료 코드: {start_process.returncode}")
            if stdout:
                logger.info(f"시작 스크립트 stdout:\n{stdout}")
            if stderr:
                logger.error(f"시작 스크립트 stderr:\n{stderr}")
            # 시작 실패 시 데몬도 종료
            sys.exit(1)

    except FileNotFoundError:
        logger.error(f"시작 스크립트를 찾을 수 없습니다: {START_SCRIPT}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"스트림 시작 중 예외 발생: {e}")
        sys.exit(1)

    logger.info("데몬이 백그라운드에서 실행 중이며 신호를 기다립니다.")
    
    # 신호 대기: signal.pause()는 신호 처리 후 반환합니다.
    while True:
        signal.pause()

if __name__ == "__main__":
    main() 

#!/usr/bin/env python3
"""
RTSP Multithread Processor 실행 스크립트

실제 운영용 실행 파일
- 환경변수 기반 설정
- 안정적인 에러 처리
- 신호 처리
- 로깅 설정
"""

import os
import sys
import signal
import logging
from pathlib import Path
from dotenv import load_dotenv
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from syslog import syslog, openlog, closelog, LOG_INFO, LOG_WARNING, LOG_ERR, LOG_PID, LOG_DAEMON

# DOTENV_PATH가 지정된 경우 해당 파일을 우선 로드하여 각 세션별 환경 격리
try:
    dotenv_path = os.getenv("DOTENV_PATH")
    if dotenv_path and os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path, override=True)
    else:
        load_dotenv()
except Exception:
    # dotenv 로드 실패 시에도 진행 (필수 변수는 validate_environment에서 점검)
    pass
# 패키지 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

class DailyDateFileHandler(logging.Handler):
	"""날짜가 바뀌면 파일명을 오늘 날짜로 바꿔가며 기록하는 핸들러."""
	def __init__(self, logs_dir: Path, prefix: str, level=logging.NOTSET):
		super().__init__(level)
		self.logs_dir = Path(logs_dir)
		self.prefix = prefix
		self.current_date = datetime.now().strftime('%Y%m%d')
		self._inner = None
		self._open_for_today()
	
	def _filepath_for(self, datestr: str) -> Path:
		y, m, d = datestr[:4], datestr[4:6], datestr[6:8]
		return (self.logs_dir / y / m / d) / f"{self.prefix}_{datestr}.log"
	
	def _open_for_today(self):
		path = self._filepath_for(self.current_date)
		# 날짜 디렉터리까지 생성
		path.parent.mkdir(parents=True, exist_ok=True)
		# 기존 핸들러 닫기
		if self._inner:
			try:
				self._inner.close()
			except Exception:
				pass
		self._inner = logging.FileHandler(str(path), encoding='utf-8')
		# 포매터/레벨은 외부에서 setFormatter/setLevel로 설정됨
		self._inner.setLevel(self.level)
		if self.formatter:
			self._inner.setFormatter(self.formatter)
	
	def emit(self, record: logging.LogRecord) -> None:
		new_date = datetime.now().strftime('%Y%m%d')
		if new_date != self.current_date:
			self.current_date = new_date
			self._open_for_today()
		self._inner.emit(record)
	
	def setLevel(self, level):
		super().setLevel(level)
		if self._inner:
			self._inner.setLevel(level)
	
	def setFormatter(self, fmt):
		super().setFormatter(fmt)
		if self._inner:
			self._inner.setFormatter(fmt)

def setup_logging():
	"""로깅 설정"""
	log_level = os.getenv('LOG_LEVEL', 'DEBUG').upper()
	# 로그 디렉터리 설정 (환경변수 LOG_DIR 우선, 없으면 SCRIPT_DIR/logs)
	script_dir = Path(__file__).parent
	# 우선순위: LOG_DIR > FINAL_OUTPUT_PATH/logs > SCRIPT_DIR/logs
	log_dir_env = os.getenv('LOG_DIR')
	final_output_base = os.getenv('FINAL_OUTPUT_PATH')
	if log_dir_env:
		default_logs_dir = log_dir_env
	elif final_output_base:
		default_logs_dir = str(Path(final_output_base) / 'logs')
	else:
		default_logs_dir = str(script_dir / 'logs')
	Path(default_logs_dir).mkdir(parents=True, exist_ok=True)
	# 파일명 프리픽스/디렉터리 파싱 (LOG_FILE이 지정되면 경로/이름을 반영하되 날짜는 핸들러가 부여)
	log_file_env = os.getenv('LOG_FILE', '')
	logs_dir_path = Path(default_logs_dir)
	prefix = 'video_processor'
	if log_file_env:
		p = Path(log_file_env)
		if p.suffix == '.log':
			prefix = p.stem if p.stem else prefix
			if str(p.parent) not in ('', '.'):
				logs_dir_path = p.parent
		else:
			# 확장자 없으면 이름만으로 간주
			prefix = p.name or prefix
	
	# 로그 레벨 검증
	numeric_level = getattr(logging, log_level, logging.DEBUG)
	
	handlers = [logging.StreamHandler(sys.stdout)]
	handlers[0].setLevel(numeric_level)
	
	# 파일 핸들러 레벨은 환경변수로 조정 (기본 INFO), 날짜 바뀌면 파일명 교체
	file_log_level = os.getenv('FILE_LOG_LEVEL', 'INFO').upper()
	file_handler = DailyDateFileHandler(logs_dir_path, prefix)
	file_handler.setLevel(getattr(logging, file_log_level, logging.INFO))
	handlers.append(file_handler)
	
	logging.basicConfig(
		level=logging.DEBUG,  # 루트는 넉넉히 두고 개별 핸들러로 제어
		format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
		handlers=handlers
	)
	
	return logging.getLogger(__name__)

def validate_environment():
    """환경변수 검증"""
    logger = logging.getLogger(__name__)
    
    # 필수 환경변수 확인
    rtsp_url = os.getenv('RTSP_URL')
    if not rtsp_url:
        logger.error("❌ RTSP_URL 환경변수가 설정되지 않았습니다")
        logger.info("다음 중 하나의 방법으로 설정하세요:")
        logger.info("1. export RTSP_URL='rtsp://your-camera-ip:554/stream'")
        logger.info("2. source setup_env.sh")
        logger.info("3. .env 파일 생성")
        return False
    
    # 블러 모듈 확인 (선택사항)
    blur_module_path = os.getenv('BLUR_MODULE_PATH')
    if blur_module_path and not os.path.exists(blur_module_path):
        logger.warning(f"⚠️  블러 모듈을 찾을 수 없습니다: {blur_module_path}")
        logger.info("기본 블러를 사용합니다")
    
    # 출력 경로 확인
    temp_output_path = os.getenv('TEMP_OUTPUT_PATH', './output/temp/')
    final_output_path = os.getenv('FINAL_OUTPUT_PATH', '/mnt/raid5')
    try:
        os.makedirs(temp_output_path, exist_ok=True)
    except Exception as e:
        logger.error(f"❌ 임시 출력 경로 생성 실패: {temp_output_path} - {e}")
        return False
    
    logger.info("✅ 환경변수 검증 완료")
    return True

def main():
    """메인 실행 함수"""
    # 로깅 설정
    logger = setup_logging()
    
    logger.info("=" * 60)
    logger.info("🚀 RTSP Multithread Processor 시작")
    logger.info("=" * 60)
    
    try:
        # 환경변수 검증
        if not validate_environment():
            sys.exit(1)
        
        # 설정 로드
        from video_processor import RTSPProcessor, RTSPConfig
        
        rtsp_url = os.getenv('RTSP_URL')
        config = RTSPConfig.from_env(rtsp_url)
        
        # 설정 검증
        if not config.validate():
            logger.error("❌ 설정 검증 실패")
            sys.exit(1)
        
        # 현재 설정 출력
        logger.info("현재 설정:")
        logger.info(f"  📺 RTSP URL: {config.rtsp_url}")
        logger.info(f"  🚢 선박명: {config.overlay_config.vessel_name}")
        logger.info(f"  🔢 스트림 번호: {config.overlay_config.stream_number}")
        logger.info(f"  📁 임시 출력 경로: {config.temp_output_path}")
        logger.info(f"  📁 최종 출력 경로: {config.final_output_path}")
        logger.info(f"  🎯 해상도: {config.target_resolution[0]}x{config.target_resolution[1]}")
        logger.info(f"  🎬 FPS: {config.input_fps}")
        logger.info(f"  🌀 블러 활성화: {config.blur_enabled}")
        if config.blur_module_path:
            module_status = "✅ 존재" if os.path.exists(config.blur_module_path) else "❌ 없음"
            logger.info(f"  🤖 YOLO 모듈: {module_status}")
        logger.info(f"  📊 모니터링: {config.enable_monitoring}")
        
        # 프로세서 생성
        processor = RTSPProcessor(config)
        
        # 신호 처리 설정
        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            logger.info(f"🛑 {signal_name} 신호 수신, 정상 종료 시작")            
            syslog(LOG_INFO, f"🛑 {signal_name} Received")
            processor.stop()
            logger.info("👋 프로그램 종료")
            sys.exit(0)
        
        #signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # terminate
        
        # 처리 시작
        logger.info("🎬 스트림 처리 시작...")
        processor.start()
        
        # 상태 모니터링 루프
        import time
        last_stats_time = 0
        # 상태 출력 주기 (환경변수로 조정 가능, 기본 30초)
        try:
            stats_interval = int(os.getenv('STATS_INTERVAL', '30'))
        except Exception:
            stats_interval = 30
        
        logger.info("📡 처리 중... (Ctrl+C로 중지)")
        
        while processor.is_running():
            try:
                current_time = time.time()
                
                # 주기적 상태 출력
                if current_time - last_stats_time >= stats_interval:
                    stats = processor.get_statistics()
                    # 최근 구간 지표 포함 상태 로그 (INFO)
                    recv = stats.get('stream_receiver', {})
                    proc = stats.get('frame_processor', {})
                    queue_size = stats.get('queue_status', {}).get('queue_size', 0)
                    logger.info(
                        f"📊 상태 - 수신누적:{recv.get('received_frames',0)} 손실누적:{recv.get('lost_frames',0)} "
                        f"최근수신FPS:{recv.get('recent_received_fps',0):.2f} 최근큐드롭:{recv.get('recent_queue_full_drops',0)} | "
                        f"처리누적:{proc.get('processed_frames',0)} 저장누적:{proc.get('saved_frames',0)} "
                        f"최근처리FPS:{proc.get('recent_processed_fps',0):.2f} 최근저장FPS:{proc.get('recent_saved_fps',0):.2f} | "
                        f"큐:{queue_size}"
                    )
                    # 시스템 리소스 요약은 DEBUG로 유지
                    sys_stats = stats.get('system_stats', {})
                    cpu_percent = sys_stats.get('cpu_percent', 0)
                    memory_percent = sys_stats.get('memory_percent', 0)
                    logger.debug(f"🖥️  리소스 - CPU:{cpu_percent:.1f}% 메모리:{memory_percent:.1f}%")
                    
                    last_stats_time = current_time
                
                # 최대 시간 체크
                if config.max_duration_seconds:
                    elapsed = time.time() - processor.start_time
                    if elapsed >= config.max_duration_seconds:
                        logger.info("⏰ 최대 처리 시간 도달, 자동 종료")
                        break
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("⌨️  키보드 인터럽트")
                break
            except Exception as e:
                logger.error(f"❌ 메인 루프 오류: {e}")
                time.sleep(5)  # 5초 대기 후 재시도
        
        # 정상 종료
        logger.info("🛑 처리 중지 중...")
        processor.stop()
        logger.info("✅ 정상 종료 완료")
        
    except KeyboardInterrupt:
        logger.info("⌨️  키보드 인터럽트로 종료")
    except ImportError as e:
        logger.error(f"❌ 모듈 import 오류: {e}")
        logger.info("필요한 패키지를 설치했는지 확인하세요:")
        logger.info("pip install opencv-python numpy psutil python-dotenv")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 예상치 못한 오류: {e}")
        import traceback
        logger.error(f"상세 오류: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
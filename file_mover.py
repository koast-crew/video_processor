#!/usr/bin/env python3
"""
RTSP 영상 파일 자동 이동 스크립트
watchdog를 사용하여 temp_ 접두사가 제거된 완료된 영상 파일을
최종 저장 경로(/mnt/raid5/YYYY/MM/DD/HH/)로 자동 이동
"""

import os
import sys
import shutil
import logging
import signal
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import threading
from logging.handlers import TimedRotatingFileHandler

try:
	from watchdog.observers import Observer
	from watchdog.events import FileSystemEventHandler
except ImportError:
	print("❌ watchdog 패키지가 설치되지 않았습니다. pip install watchdog로 설치하세요.")
	sys.exit(1)

from config import get_env_value
from api_client import BlackboxAPIClient, create_camera_video_data

# 날짜별 파일명으로 기록하는 핸들러 (YYYYMMDD 단위로 파일 교체)
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

# 로깅 설정
log_level_env = os.getenv('LOG_LEVEL', 'DEBUG').upper()
file_log_level_env = os.getenv('FILE_LOG_LEVEL', 'INFO').upper()
rotation_enabled = os.getenv('LOG_ROTATION', 'on').lower() in ('1','true','yes','on')
rotate_interval = int(os.getenv('LOG_ROTATE_INTERVAL', '1'))  # 일 단위
backup_count = int(os.getenv('LOG_BACKUP_COUNT', '7'))

# 로그 디렉터리: LOG_DIR만 사용 (없으면 파일 로깅 비활성화)
log_dir_env = os.getenv('LOG_DIR')
logs_dir_path = None
if log_dir_env and str(log_dir_env).strip():
	logs_dir_path = Path(log_dir_env)
	logs_dir_path.mkdir(parents=True, exist_ok=True)

# 로그 파일 prefix: LOG_FILE의 이름만 사용(경로는 무시)
log_file_env = os.getenv('LOG_FILE', 'file_mover.log')
p = Path(log_file_env)
if p.suffix == '.log':
	prefix = p.stem if p.stem else 'file_mover'
else:
	prefix = p.name or 'file_mover'

numeric_level = getattr(logging, log_level_env, logging.DEBUG)

handlers = [logging.StreamHandler(sys.stdout)]
handlers[0].setLevel(numeric_level)

log_to_file = os.getenv('PY_LOG_TO_FILE', 'on').lower() in ('1','true','yes','on')
if log_to_file and logs_dir_path is not None:
	# 파일 핸들러는 날짜 기반 파일명(prefix_YYYYMMDD.log)을 사용하고 LOG_DIR만 대상으로 함
	file_handler = DailyDateFileHandler(logs_dir_path, prefix)
	file_handler.setLevel(getattr(logging, file_log_level_env, logging.INFO))
	handlers.append(file_handler)

logging.basicConfig(
	level=logging.DEBUG,  # 루트는 넉넉히 두고 개별 핸들러로 제어
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
	handlers=handlers
)
logger = logging.getLogger(__name__)

def _is_interesting_file(path: str) -> bool:
	name = os.path.basename(path)
	return (name.endswith('.mp4') or name.endswith('.srt')) and True

class VideoFileMoveHandler(FileSystemEventHandler):
	"""영상/자막 파일 이동 처리 핸들러"""
	
	def __init__(self, temp_path: str, final_path: str):
		self.temp_path = Path(temp_path)
		self.final_path = Path(final_path)
		self.processing_files = set()  # 처리 중인 파일들 추적
		
		logger.info(f"파일 모니터링 시작:")
		logger.info(f"  📁 임시 경로: {self.temp_path}")
		logger.info(f"  📁 최종 경로: {self.final_path}")
		
		# 최종 경로 생성
		self.final_path.mkdir(parents=True, exist_ok=True)
		
				# API 설정
		self.blackbox_enabled = get_env_value('BLACKBOX_ENABLED', True, bool)
		self.blackbox_api_url = get_env_value('BLACKBOX_API_URL', 'http://localhost')
		self.api_timeout = get_env_value('API_TIMEOUT', 5, int)
		self.video_segment_duration = get_env_value('VIDEO_SEGMENT_DURATION', 300, int)

	def _parse_start_time_and_stream(self, filename: str):
		"""파일명에서 시작시간 및 스트림 번호를 추출"""
		try:
			m = re.search(r'_stream(\d{1,2})_', filename)
			stream_num = int(m.group(1)) if m else 1
			m2 = re.search(r'_(\d{6})_(\d{6})\.(mp4|srt)$', filename)
			if not m2:
				return None, stream_num
			date_str = m2.group(1)
			time_str = m2.group(2)
			year = 2000 + int(date_str[:2])
			month = int(date_str[2:4])
			day = int(date_str[4:6])
			hour = int(time_str[:2])
			minute = int(time_str[2:4])
			second = int(time_str[4:6])
			start_dt = datetime(year, month, day, hour, minute, second)
			return start_dt, stream_num
		except Exception:
			return None, 1
	
	def _send_video_info(self, final_file_path: Path):
		"""최종 경로로 이동 완료 후 API 전송"""
		if not self.blackbox_enabled:
			return
		try:
			client = BlackboxAPIClient(base_url=self.blackbox_api_url, timeout=self.api_timeout)
			blackbox_data = client.get_latest_gps()
			file_name = final_file_path.name
			start_dt, stream_num = self._parse_start_time_and_stream(file_name)
			if start_dt is None:
				start_dt = datetime.now()
			end_dt = start_dt + timedelta(seconds=self.video_segment_duration)
			video_data = create_camera_video_data(
				file_path=str(final_file_path),
				file_name=file_name,
				record_start_time=start_dt,
				record_end_time=end_dt,
				blackbox_data=blackbox_data,
				stream_number=stream_num
			)
			ok = client.send_camera_video_info(video_data)
			if ok:
				logger.info(f"📤 API 전송 성공: {final_file_path}")
			else:
				logger.error(f"�� API 전송 실패: {final_file_path}")
		except Exception as e:
			logger.error(f"API 전송 중 오류: {e}")
	
	def on_moved(self, event):
		"""파일 이름 변경(temp_ 제거) 감지"""
		if event.is_directory:
			return
		
		# temp_ -> 일반 파일명으로 변경된 경우만 처리 (mp4, srt)
		if (_is_interesting_file(event.src_path) and 
			'temp_' in os.path.basename(event.src_path) and
			not os.path.basename(event.dest_path).startswith('temp_')):
			self._process_completed_file(event.dest_path)
	
	def on_created(self, event):
		"""새 파일 생성 감지 (temp_ 접두사 없는 경우)"""
		if event.is_directory:
			return
		
		if (_is_interesting_file(event.src_path) and 
			not os.path.basename(event.src_path).startswith('temp_')):
			# 파일이 완전히 생성될 때까지 잠시 대기
			threading.Timer(2.0, self._process_completed_file, args=[event.src_path]).start()
	
	def _process_completed_file(self, file_path: str):
		"""완료된 영상/자막 파일 처리"""
		file_path = Path(file_path)
		
		# 중복 처리 방지
		if str(file_path) in self.processing_files:
			return
		
		# 파일이 실제로 존재하는지 확인
		if not file_path.exists():
			# .srt가 다른 이벤트 흐름에서 이미 이동된 경우: 정상 동작이므로 경고를 낮춤
			if str(file_path).lower().endswith('.srt'):
				logger.debug(f"자막 파일이 이미 이동되어 temp에 없음(정상): {file_path}")
			else:
				logger.warning(f"파일이 존재하지 않음: {file_path}")
			return
		
		self.processing_files.add(str(file_path))
		
		try:
			logger.info(f"📄 완료된 파일 발견: {file_path.name}")
			
			# 파일명에서 시간 정보 추출
			target_dir = self._extract_time_based_directory(file_path.name)
			if not target_dir:
				logger.error(f"파일명에서 시간 정보를 추출할 수 없음: {file_path.name}")
				return
			
			# 최종 저장 경로 생성
			final_dir = self.final_path / target_dir
			final_dir.mkdir(parents=True, exist_ok=True)
			
			# 파일 이동
			final_file_path = final_dir / file_path.name
			
			logger.debug(f"📦 파일 이동 중...")
			logger.debug(f"  원본: {file_path}")
			logger.debug(f"  대상: {final_file_path}")
			
			# 파일 이동 (shutil.move는 원자적 작업)
			shutil.move(str(file_path), str(final_file_path))
			# 파일 권한 설정 (선택사항)
			os.chmod(final_file_path, 0o644)
			logger.info(f"✅ 파일 이동 완료: {final_file_path}")
			# 이동 완료 후 API 전송 (mp4 파일에 한함)
			try:
				if str(final_file_path).lower().endswith('.mp4'):
					self._send_video_info(final_file_path)
			except Exception as e:
				logger.warning(f"API 전송 단계에서 경고: {e}")
			
			# 짝 파일(.mp4 <-> .srt) 동시 이동 처리
			try:
				name = file_path.name
				if name.endswith('.mp4'):
					base = name[:-4]
					srt_final_name = base + '.srt'
					temp_srt_name = 'temp_' + srt_final_name
					srt_final_path_in_temp = self.temp_path / srt_final_name
					srt_temp_path_in_temp = self.temp_path / temp_srt_name
					# temp에 남아있는 자막이 있으면 최종명으로 rename
					if srt_temp_path_in_temp.exists() and not srt_final_path_in_temp.exists():
						try:
							os.rename(srt_temp_path_in_temp, srt_final_path_in_temp)
							logger.info(f"🔁 자막 rename(temp->final): {srt_final_path_in_temp.name}")
						except Exception as e:
							logger.warning(f"자막 rename 실패: {e}")
					# 최종명이 temp 디렉토리에 존재하면 같이 이동
					if srt_final_path_in_temp.exists():
						dst_srt = final_dir / srt_final_name
						try:
							shutil.move(str(srt_final_path_in_temp), str(dst_srt))
							os.chmod(dst_srt, 0o644)
							logger.info(f"📎 짝 자막 이동 완료: {dst_srt}")
						except Exception as e:
							logger.warning(f"짝 자막 이동 실패: {e}")
			except Exception as e:
				logger.debug(f"짝 파일 처리 중 경고: {e}")
			
		except Exception as e:
			logger.error(f"❌ 파일 이동 실패: {file_path.name} - {e}")
		finally:
			self.processing_files.discard(str(file_path))
		
	def _extract_time_based_directory(self, filename: str) -> Optional[str]:
		"""파일명에서 시간 정보를 추출하여 YYYY/MM/DD/HH 경로 생성"""
		try:
			# 파일명 패턴: {vessel_name}_stream{number}_{YYMMDD}_{HHMMSS}.(mp4|srt)
			# 예: vesselTest_stream01_241212_143052.mp4
			pattern = r'_(\d{6})_(\d{6})\.(mp4|srt)$'
			match = re.search(pattern, filename)
			if not match:
				logger.warning(f"파일명 패턴이 맞지 않음: {filename}")
				return None
			date_str = match.group(1)  # YYMMDD
			time_str = match.group(2)  # HHMMSS
			# 날짜 파싱 (YY -> 20YY로 변환)
			year = 2000 + int(date_str[:2])
			month = int(date_str[2:4])
			day = int(date_str[4:6])
			hour = int(time_str[:2])
			# YYYY/MM/DD/HH 형식으로 경로 생성
			time_dir = f"{year:04d}/{month:02d}/{day:02d}/{hour:02d}"
			logger.debug(f"시간 기반 경로 생성: {filename} -> {time_dir}")
			return time_dir
		except Exception as e:
			logger.error(f"시간 정보 추출 실패: {filename} - {e}")
			return None

class FileMoverService:
	"""파일 이동 서비스 메인 클래스"""
	
	def __init__(self):
		self.temp_path = get_env_value('TEMP_OUTPUT_PATH', './output/temp/')
		self.final_path = get_env_value('FINAL_OUTPUT_PATH', '/mnt/raid5')
		self.observer = None
		self.running = False
		
		# 신호 핸들러 등록
		signal.signal(signal.SIGINT, self._signal_handler)
		signal.signal(signal.SIGTERM, self._signal_handler)
		# 그레이스풀 셧다운 지원
		self.shutdown_event = threading.Event()
		self.grace_seconds = get_env_value('FILE_MOVER_GRACE_SECONDS', 15, int)
		self.event_handler = None
	
	def _signal_handler(self, signum, frame):
		"""종료 신호 처리"""
		logger.info(f"종료 신호 수신: {signum} - 그레이스풀 셧다운 대기 {self.grace_seconds}s")
		self.shutdown_event.set()
	
	def _sweep_final_named_files(self):
		"""temp_ 접두사가 없는 완료 파일을 한 번 더 스캔하여 이동 처리"""
		try:
			if not self.event_handler:
				return
			for name in os.listdir(self.temp_path):
				full_path = str(Path(self.temp_path) / name)
				# mp4/srt 이면서 temp_ 가 아닌 경우만 대상
				if _is_interesting_file(full_path) and not name.startswith('temp_'):
					try:
						self.event_handler._process_completed_file(full_path)
					except Exception as e:
						logger.debug(f"스윕 처리 중 경고: {e}")
		except Exception as e:
			logger.warning(f"스윕 중 오류: {e}")
	
	def start(self):
		"""파일 모니터링 시작"""
		try:
			logger.info("🚀 RTSP 영상 파일 이동 서비스 시작")
			
			# 임시 경로 존재 확인
			temp_path_obj = Path(self.temp_path)
			if not temp_path_obj.exists():
				logger.info(f"임시 경로 생성: {self.temp_path}")
				temp_path_obj.mkdir(parents=True, exist_ok=True)
			
			# 최종 경로 확인/생성
			final_path_obj = Path(self.final_path)
			try:
				final_path_obj.mkdir(parents=True, exist_ok=True)
				logger.info(f"최종 저장 경로 확인: {self.final_path}")
			except PermissionError:
				logger.warning(f"최종 경로 권한 없음: {self.final_path} (파일 이동 시 생성 시도)")
			
			# 파일 시스템 이벤트 핸들러 설정
			self.event_handler = VideoFileMoveHandler(self.temp_path, self.final_path)
			
			# Observer 설정 및 시작
			self.observer = Observer()
			self.observer.schedule(self.event_handler, self.temp_path, recursive=False)
			self.observer.start()
			self.running = True
			
			logger.info("📡 파일 모니터링 활성화됨")
			logger.info("Press Ctrl+C to stop...")
			
			# 시작 시 한 번 스윕(서비스 시작 전 생성된 완료 파일 이동)
			self._sweep_final_named_files()
			
			# 메인 루프
			try:
				while self.running:
					# SIGTERM 수신 시 그레이스 기간 동안 최종 파일 이동 기회를 제공
					if self.shutdown_event.is_set():
						deadline = time.time() + max(0, int(self.grace_seconds))
						logger.info("그레이스풀 셧다운 시작: 잔여 완료 파일 이동 시도")
						while time.time() < deadline:
							self._sweep_final_named_files()
							time.sleep(1)
						break
					time.sleep(1)
			except KeyboardInterrupt:
				pass
			
		except Exception as e:
			logger.error(f"❌ 서비스 시작 실패: {e}")
			return False
		finally:
			self.stop()
			# 종료 직전 한 번 더 스윕
			self._sweep_final_named_files()
		
		return True
	
	def stop(self):
		"""파일 모니터링 중지"""
		if self.running:
			logger.info("🛑 파일 이동 서비스 중지 중...")
			self.running = False
			
			if self.observer:
				self.observer.stop()
				self.observer.join()
				logger.info("✅ 파일 모니터링 종료됨")

def main():
	"""메인 함수"""
	logger.info("=" * 50)
	logger.info("RTSP 영상 파일 자동 이동 서비스")
	logger.info("=" * 50)
	
	# 환경변수 로드
	try:
		from dotenv import load_dotenv
		load_dotenv()
		logger.info("환경변수 로드 완료")
	except ImportError:
		logger.warning("python-dotenv 패키지가 설치되지 않음. 시스템 환경변수만 사용")
	except Exception as e:
		logger.warning(f"환경변수 로드 실패: {e}")
	
	# 서비스 실행
	service = FileMoverService()
	
	try:
		success = service.start()
		if not success:
			sys.exit(1)
	except Exception as e:
		logger.error(f"예상치 못한 오류: {e}")
		sys.exit(1)
	
	logger.info("서비스가 정상적으로 종료되었습니다.")

if __name__ == "__main__":
	main() 
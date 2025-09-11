"""
RTSP 퍼블리셔 모듈

블러 처리된 프레임을 FFmpeg stdin 파이프로 전달하여 RTSP 서버로 송출한다.
- config.ffmpeg_config.get_ffmpeg_rtsp_command 사용
- start/stop, write 인터페이스 제공
- 에러 시 자동 재시도 최소화
"""

import os
import subprocess
import logging
import cv2
import numpy as np
from typing import Optional
from datetime import datetime

try:
	from .config import RTSPConfig
except ImportError:
	from config import RTSPConfig

logger = logging.getLogger(__name__)

class RtspPublisher:
	"""FFmpeg 기반 RTSP 송출기"""
	def __init__(self, config: RTSPConfig):
		self.config = config
		self.process: Optional[subprocess.Popen] = None
		self._stderr_file = None
		self.is_opened: bool = False
		self.frame_count: int = 0

	def _resolve_log_file(self) -> str:
		log_dir = os.getenv('LOG_DIR') or os.path.join(self.config.final_output_path or '.', 'logs')
		date_str = datetime.now().strftime('%Y%m%d')
		y, m, d = date_str[:4], date_str[4:6], date_str[6:8]
		path = os.path.join(log_dir, y, m, d)
		os.makedirs(path, exist_ok=True)
		try:
			stream_number = self.config.overlay_config.stream_number
		except Exception:
			stream_number = 'unknown'
		return os.path.join(path, f"ffmpeg_rtsp_stream{stream_number}_{date_str}.stderr.log")

	def start(self) -> bool:
		"""FFmpeg 프로세스 시작"""
		if not self.config.rtsp_output_enabled:
			logger.info("RTSP 송출 비활성화 상태로 퍼블리셔 시작 생략")
			return False
		if not self.config.rtsp_output_url:
			logger.error("RTSP_OUTPUT_URL 미지정")
			return False
		if self.process and self.is_opened:
			return True
		try:
			width, height = self.config.target_resolution
			fps = self.config.input_fps
			cmd = self.config.ffmpeg_config.get_ffmpeg_rtsp_command(
				{'width': width, 'height': height, 'fps': fps},
				self.config.rtsp_output_url,
				self.config.rtsp_output_transport
			)
			stderr_path = self._resolve_log_file()
			self._stderr_file = open(stderr_path, 'ab', buffering=0)
			self.process = subprocess.Popen(
				cmd,
				stdin=subprocess.PIPE,
				stdout=subprocess.DEVNULL,
				stderr=self._stderr_file,
				bufsize=1
			)
			if self.process.poll() is not None:
				logger.error(f"FFmpeg RTSP 프로세스 즉시 종료: 코드 {self.process.poll()}")
				self.is_opened = False
				return False
			self.is_opened = True
			logger.info(f"RTSP 퍼블리셔 시작: {self.config.rtsp_output_url}")
			return True
		except Exception as e:
			logger.error(f"RTSP 퍼블리셔 시작 실패: {e}")
			self.is_opened = False
			return False

	def write(self, frame: np.ndarray) -> bool:
		"""프레임 송출"""
		if not self.is_opened or not self.process:
			return False
		try:
			if self.process.poll() is not None:
				logger.error(f"RTSP 퍼블리셔 프로세스 종료됨: {self.process.poll()}")
				self.is_opened = False
				return False
			if frame is None or frame.size == 0:
				return False
			height, width = frame.shape[:2]
			exp_w, exp_h = self.config.target_resolution
			if width != exp_w or height != exp_h:
				frame = cv2.resize(frame, (exp_w, exp_h))
			self.process.stdin.write(frame.tobytes())
			self.frame_count += 1
			return True
		except BrokenPipeError as e:
			logger.error(f"RTSP 퍼블리셔 파이프 오류: {e}")
			self.is_opened = False
			return False
		except Exception as e:
			logger.error(f"RTSP 퍼블리셔 write 실패: {e}")
			return False

	def stop(self):
		"""프로세스 종료"""
		try:
			if self.process:
				try:
					self.process.stdin.close()
					self.process.wait(timeout=5)
				except subprocess.TimeoutExpired:
					self.process.kill()
				finally:
					self.process = None
		finally:
			self.is_opened = False
			try:
				if self._stderr_file:
					self._stderr_file.close()
			except Exception:
				pass

	def isOpened(self) -> bool:
		return self.is_opened and self.process is not None 
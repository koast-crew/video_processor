import os
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any

try:
	from .config import RTSPConfig
except ImportError:
	from config import RTSPConfig

logger = logging.getLogger(__name__)

class SubtitleWriter:
	"""SRT 자막 작성기: 영상 세그먼트 라이프사이클과 동기화
	- temp_{basename}.srt 로 작성 시작
	- 세그먼트 완료 시 temp_ 제거하여 최종 파일명으로 rename
	- 매 초마다 1초 길이 cue 생성
	- 멀티 세그먼트 동시 관리 (비동기 finalize 대응)
	"""

	def __init__(self, config: RTSPConfig):
		self.config = config
		# 세그먼트별 컨텍스트: key = temp_video_path
		self.segments: Dict[str, Dict[str, Any]] = {}
		self.current_key: Optional[str] = None

	def on_segment_started(self, temp_video_path: str, final_video_path: str, planned_start_time: datetime):
		"""비디오 세그먼트 시작 시점에 호출됨"""
		try:
			temp_srt = temp_video_path[:-4] + '.srt' if temp_video_path.endswith('.mp4') else temp_video_path + '.srt'
			final_srt = final_video_path[:-4] + '.srt' if final_video_path.endswith('.mp4') else final_video_path + '.srt'
			# 폴더 보장
			os.makedirs(os.path.dirname(temp_srt), exist_ok=True)
			# 새 파일 오픈 (덮어쓰기)
			fh = open(temp_srt, 'w', encoding='utf-8')
			ctx = {
				'temp_srt': temp_srt,
				'final_srt': final_srt,
				'file_handle': fh,
				'start_epoch': time.time(),
				'cue_index': 0,
				'last_second': -1,
				'active': True
			}
			self.segments[temp_video_path] = ctx
			self.current_key = temp_video_path
			logger.info(f"SRT 자막 시작: {os.path.basename(temp_srt)}")
		except Exception as e:
			logger.error(f"SRT 시작 오류: {e}")

	def _format_srt_time(self, seconds_float: float) -> str:
		if seconds_float < 0:
			seconds_float = 0.0
		total_ms = int(round(seconds_float * 1000))
		hours = total_ms // 3600000
		rem = total_ms % 3600000
		minutes = rem // 60000
		rem = rem % 60000
		seconds = rem // 1000
		millis = rem % 1000
		return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

	def _write_one_second_cue(self, ctx: Dict[str, Any], second_index: int, text: str):
		ctx['cue_index'] += 1
		start_t = self._format_srt_time(second_index)
		end_t = self._format_srt_time(second_index + 1)
		block = f"{ctx['cue_index']}\n{start_t} --> {end_t}\n{text}\n\n"
		fh = ctx['file_handle']
		fh.write(block)
		fh.flush()
		try:
			os.fsync(fh.fileno())
		except Exception:
			pass
		ctx['last_second'] = second_index

	def update(self, frame_timestamp_epoch: float, overlay_text: str):
		"""프레임 타임스탬프 기준으로 새 초가 지날 때마다 cue 작성 (현재 진행 중 세그먼트에만 기록)"""
		key = self.current_key
		if not key or key not in self.segments:
			return
		ctx = self.segments[key]
		if not ctx.get('active'):
			return
		try:
			current_second = int(frame_timestamp_epoch - ctx['start_epoch'])
			while ctx['last_second'] < current_second - 1:
				self._write_one_second_cue(ctx, ctx['last_second'] + 1, overlay_text)
			if current_second > ctx['last_second']:
				self._write_one_second_cue(ctx, current_second, overlay_text)
		except Exception as e:
			logger.warning(f"SRT 업데이트 오류: {e}")

	def on_segment_finalizing(self, temp_video_path: str, final_video_path: str, start_dt: datetime, frame_count: int):
		"""비디오 세그먼트 finalize 시점에 호출됨: 파일 닫고 rename (해당 세그먼트 컨텍스트 기준)"""
		ctx = self.segments.get(temp_video_path)
		if not ctx:
			# 이미 정리되었거나 시작 정보가 없을 수 있음
			logger.debug(f"SRT finalize: 컨텍스트 없음 (skip) {temp_video_path}")
			return
		try:
			if ctx.get('active') and ctx.get('file_handle') is not None and ctx.get('start_epoch') is not None:
				elapsed = time.time() - ctx['start_epoch']
				final_second = int(elapsed)
				if final_second > ctx['last_second']:
					self._write_one_second_cue(ctx, final_second, '')
				# flush 후 닫기
				fh = ctx['file_handle']
				try:
					fh.flush()
					os.fsync(fh.fileno())
				except Exception:
					pass
				fh.close()
				ctx['file_handle'] = None
			# rename temp_*.srt -> *.srt
			temp_srt = ctx['temp_srt']
			final_srt = ctx['final_srt']
			if temp_srt and os.path.exists(temp_srt):
				os.rename(temp_srt, final_srt)
				logger.info(f"SRT 자막 완료: {os.path.basename(final_srt)}")
		except Exception as e:
			logger.error(f"SRT finalize 오류: {e}")
		finally:
			ctx['active'] = False
			# 현재 키가 이 세그먼트면 해제
			if self.current_key == temp_video_path:
				self.current_key = None
			# 컨텍스트 제거
			try:
				del self.segments[temp_video_path]
			except Exception:
				pass

	def cleanup(self):
		"""모든 세그먼트 정리: 열린 파일 닫고 temp를 final로 rename"""
		try:
			for key, ctx in list(self.segments.items()):
				try:
					fh = ctx.get('file_handle')
					if fh:
						try:
							fh.flush()
							os.fsync(fh.fileno())
						except Exception:
							pass
						fh.close()
						ctx['file_handle'] = None
					# rename temp -> final
					temp_srt = ctx.get('temp_srt')
					final_srt = ctx.get('final_srt')
					if temp_srt and final_srt and os.path.exists(temp_srt):
						try:
							os.rename(temp_srt, final_srt)
							logger.info(f"SRT 자막 finalize(종료시): {final_srt}")
						except Exception as e:
							logger.warning(f"SRT 종료시 finalize 실패: {e}")
				except Exception as e:
					logger.debug(f"SRT cleanup segment 오류: {e}")
			# 전체 초기화
			self.segments.clear()
			self.current_key = None
		except Exception as e:
			logger.warning(f"SRT cleanup 오류: {e}") 
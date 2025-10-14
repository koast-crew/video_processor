#!/usr/bin/env python3
"""
블랙박스 API 클라이언트 모듈
블랙박스 데이터 조회 및 카메라 영상 정보 전송
"""

import requests
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import os

logger = logging.getLogger(__name__)

@dataclass
class BlackboxData:
	"""블랙박스 데이터 클래스"""
	vessel_id: Optional[int] = None
	vessel_name: Optional[str] = None
	gear_code: Optional[str] = None
	gear_name: Optional[str] = None
	gear_name_ko: Optional[str] = None
	longitude: Optional[float] = None
	latitude: Optional[float] = None
	speed: Optional[float] = None
	roll: Optional[float] = None
	pitch: Optional[float] = None
	temperature: Optional[float] = None
	status: Optional[int] = None
	net_opt: Optional[int] = None
	recorded_date: Optional[datetime] = None

@dataclass
class CameraDevice:
	"""카메라 디바이스 정보 클래스"""
	device_name: str
	device_key: str
	view_order: int
	vessel_id: Optional[int] = None
	vessel_name: Optional[str] = None

@dataclass
class CameraVideoData:
	"""카메라 영상 데이터 클래스"""
	camera_id: int
	camera_name: str
	camera_key: str  # 카메라 키 추가
	vessel_id: int
	vessel_name: str
	gear_code: str
	gear_name: str
	gear_name_ko: str
	file_name: str
	file_real_name: str
	file_path: str
	file_size: str  # MB 문자열 (예: "12.34")
	file_ext: str
	record_start_time: datetime
	record_end_time: datetime

class BlackboxAPIClient:
	"""블랙박스 API 클라이언트"""
	
	# 클래스 레벨 카메라 정보 캐시 (시작 시 한 번만 로드)
	_camera_devices: Optional[List[CameraDevice]] = None
	_camera_devices_loaded: bool = False
	
	def __init__(self, base_url: str = "http://localhost", timeout: int = 5):
		self.base_url = base_url.rstrip('/')
		self.timeout = timeout
		self.session = requests.Session()
		
		# 공통 헤더 설정
		self.session.headers.update({
			'Content-Type': 'application/json',
			'Accept': 'application/json'
		})
		
		logger.info(f"BlackboxAPIClient 초기화: {self.base_url}")
		
		# 처음 초기화 시 카메라 디바이스 정보 로드
		if not BlackboxAPIClient._camera_devices_loaded:
			self._load_camera_devices()
			BlackboxAPIClient._camera_devices_loaded = True
	
	def _load_camera_devices(self):
		"""카메라 디바이스 정보를 API에서 로드 (시작 시 한 번만 호출)"""
		url = f"{self.base_url}/api/devices?deviceType=CAMERA"
		
		try:
			logger.info(f"카메라 디바이스 정보 로드 중: {url}")
			response = self.session.get(url, timeout=self.timeout)
			response.raise_for_status()
			
			data = response.json()
			payload = data.get('payload', [])
			
			if not isinstance(payload, list):
				logger.warning(f"카메라 디바이스 응답이 리스트가 아닙니다: {type(payload)}")
				BlackboxAPIClient._camera_devices = None
				return
			
			# deviceName, deviceKey, viewOrder, vesselId, vesselName 추출하여 정렬
			camera_list = []
			for device in payload:
				device_name = device.get('deviceName')
				device_key = device.get('deviceKey')
				view_order = device.get('viewOrder', 999)
				vessel_id = device.get('vesselId')
				vessel_name = device.get('vesselName')
				
				if device_name and device_key:
					camera_list.append(CameraDevice(
						device_name=device_name,
						device_key=device_key,
						view_order=view_order,
						vessel_id=vessel_id,
						vessel_name=vessel_name
					))
			
			# viewOrder로 정렬
			camera_list.sort(key=lambda x: x.view_order)
			
			BlackboxAPIClient._camera_devices = camera_list
			logger.info(f"카메라 디바이스 {len(camera_list)}개 로드 완료")
			for idx, cam in enumerate(camera_list, 1):
				logger.info(f"  [{idx}] cameraName: {cam.device_name}")
				logger.info(f"      cameraKey: {cam.device_key}")
				logger.info(f"      vesselId: {cam.vessel_id}")
				logger.info(f"      vesselName: {cam.vessel_name}")
				logger.info(f"      viewOrder: {cam.view_order}")
			
		except requests.exceptions.Timeout:
			logger.error(f"카메라 디바이스 API 타임아웃: {url}")
			BlackboxAPIClient._camera_devices = None
		except requests.exceptions.ConnectionError:
			logger.error(f"카메라 디바이스 API 연결 실패: {url}")
			BlackboxAPIClient._camera_devices = None
		except requests.exceptions.HTTPError as e:
			body = e.response.text if getattr(e, 'response', None) is not None else 'No response body'
			status = e.response.status_code if getattr(e, 'response', None) is not None else 'Unknown'
			logger.error(f"카메라 디바이스 API HTTP 오류: {status} - {body}")
			BlackboxAPIClient._camera_devices = None
		except Exception as e:
			logger.error(f"카메라 디바이스 로드 예상치 못한 오류: {e}")
			BlackboxAPIClient._camera_devices = None
	
	def get_camera_device(self, stream_number: int) -> Optional[CameraDevice]:
		"""스트림 번호에 해당하는 카메라 디바이스 정보 반환 (1-based)"""
		if BlackboxAPIClient._camera_devices is None or len(BlackboxAPIClient._camera_devices) == 0:
			return None
		
		# 스트림 번호는 1-based, 리스트 인덱스는 0-based
		idx = stream_number - 1
		if 0 <= idx < len(BlackboxAPIClient._camera_devices):
			return BlackboxAPIClient._camera_devices[idx]
		
		# 범위를 벗어나면 마지막 카메라 반환
		return BlackboxAPIClient._camera_devices[-1]
	
	def get_latest_gps(self) -> Optional[BlackboxData]:
		"""최신 블랙박스 GPS 정보 조회"""
		url = f"{self.base_url}/api/blackbox-logs/latest-gps"
		
		try:
			# logger.debug(f"블랙박스 데이터 요청: {url}")
			response = self.session.get(url, timeout=self.timeout)
			response.raise_for_status()
			
			data = response.json()
			payload = data.get('payload', {})
			
			# logger.debug(f"블랙박스 응답 데이터: {payload}")
			
			# recorded_date 파싱
			recorded_date = None
			if payload.get('recordedDate'):
				try:
					# yyyy-MM-dd HH:mm:ss 형식 파싱
					recorded_date = datetime.strptime(
						payload['recordedDate'], 
						"%Y-%m-%d %H:%M:%S"
					)
				except ValueError as e:
					logger.warning(f"recorded_date 파싱 실패: {e}")
			
			blackbox_data = BlackboxData(
				vessel_id=payload.get('vesselId'),
				vessel_name=payload.get('vesselName'),
				gear_code=payload.get('gearCode'),
				gear_name=payload.get('gearName'),
				gear_name_ko=payload.get('gearNameKo'),
				longitude=payload.get('longitude'),
				latitude=payload.get('latitude'),
				speed=payload.get('speed'),
				roll=payload.get('roll'),
				pitch=payload.get('pitch'),
				temperature=payload.get('temperature'),
				status=payload.get('status'),
				net_opt=payload.get('netOpt'),
				recorded_date=recorded_date
			)
			
			# logger.debug(f"블랙박스 데이터 수신 성공: speed={blackbox_data.speed}, "
			# 	   f"vessel={blackbox_data.vessel_name}, "
			# 	   f"position=({blackbox_data.latitude}, {blackbox_data.longitude})")
			
			return blackbox_data
			
		except requests.exceptions.Timeout:
			logger.error(f"블랙박스 API 타임아웃: {url}")
			return None
		except requests.exceptions.ConnectionError:
			logger.error(f"블랙박스 API 연결 실패: {url}")
			return None
		except requests.exceptions.HTTPError as e:
			body = e.response.text if getattr(e, 'response', None) is not None else 'No response body'
			status = e.response.status_code if getattr(e, 'response', None) is not None else 'Unknown'
			logger.error(f"블랙박스 API HTTP 오류: {status} - {body}")
			return None
		except Exception as e:
			logger.error(f"블랙박스 API 예상치 못한 오류: {e}")
			return None
	
	def send_camera_video_info(self, video_data: CameraVideoData) -> bool:
		"""카메라 영상 정보 전송"""
		url = f"{self.base_url}/api/camera-videos"
		
		try:
			# 데이터 직렬화 (서버 스펙에 맞춤)
			payload = {
				"cameraId": video_data.camera_id,
				"cameraName": video_data.camera_name,
				"cameraKey": video_data.camera_key,  # 카메라 키 추가
				"vesselId": video_data.vessel_id,
				"vesselName": video_data.vessel_name,
				"gearCode": video_data.gear_code,
				"gearName": video_data.gear_name,
				"gearNameKo": video_data.gear_name_ko,
				"fileName": video_data.file_name,
				"fileRealName": video_data.file_real_name,
				"filePath": video_data.file_path,
				"fileSize": video_data.file_size,  # MB 문자열
				"fileExt": video_data.file_ext,
				"recordStartTime": video_data.record_start_time.isoformat(timespec='seconds'),
				"recordEndTime": video_data.record_end_time.isoformat(timespec='seconds')
			}
			
			logger.debug(f"영상 정보 전송: {url}")
			logger.debug(f"전송 데이터: {payload}")
			
			response = self.session.post(url, json=payload, timeout=self.timeout)
			response.raise_for_status()
			
			logger.debug(f"영상 정보 전송 성공: {video_data.file_name}")
			return True
			
		except requests.exceptions.Timeout:
			logger.error(f"영상 정보 전송 타임아웃: {url}")
			return False
		except requests.exceptions.ConnectionError:
			logger.error(f"영상 정보 전송 연결 실패: {url}")
			return False
		except requests.exceptions.HTTPError as e:
			body = e.response.text if getattr(e, 'response', None) is not None else 'No response body'
			status = e.response.status_code if getattr(e, 'response', None) is not None else 'Unknown'
			logger.error(f"영상 정보 전송 HTTP 오류: {status} - {body}")
			return False
		except Exception as e:
			logger.error(f"영상 정보 전송 예상치 못한 오류: {e}")
			return False
	
	def test_connection(self) -> bool:
		"""API 연결 테스트"""
		try:
			data = self.get_latest_gps()
			return data is not None
		except Exception as e:
			logger.error(f"API 연결 테스트 실패: {e}")
			return False


def create_camera_video_data(
	file_path: str,
	file_name: str,
	record_start_time: datetime,
	record_end_time: datetime,
	blackbox_data: Optional[BlackboxData] = None,
	stream_number: Optional[int] = None,
	api_client: Optional[BlackboxAPIClient] = None
) -> CameraVideoData:
	"""CameraVideoData 객체 생성 헬퍼 함수
	
	카메라 정보 우선순위:
	1. API에서 로드한 카메라 디바이스 정보 (deviceName, deviceKey)
	2. API 실패 시 기본값 (스트림 번호: 1, 2, 3, 4, 5, 6)
	
	선박(vessel) 정보 우선순위:
	1. API 카메라 디바이스에서 로드한 선박 정보 (vesselId, vesselName)
	2. blackbox_data의 선박 정보
	3. 기본값 (vesselId: 1, vesselName: "vesselTest")
	"""
	
	# 파일 정보 추출
	file_size_int = os.path.getsize(file_path) if os.path.exists(file_path) else 0
	file_size_mb = file_size_int / (1024 * 1024) if file_size_int > 0 else 0
	file_size = f"{file_size_mb:.2f}"
	file_ext = os.path.splitext(file_name)[1].lstrip('.')
	
	# 스트림 번호 결정 (우선순위: 인자 -> ENV -> 1)
	try:
		stream_num = int(stream_number) if stream_number is not None else int(os.getenv('STREAM_NUMBER', '1'))
	except ValueError:
		stream_num = 1
	
	# 카메라 정보 결정
	camera_name = None
	camera_key = None
	
	# 1. API에서 카메라 디바이스 정보 가져오기 시도
	camera_device = None
	if api_client is not None:
		camera_device = api_client.get_camera_device(stream_num)
		if camera_device is not None:
			camera_name = camera_device.device_name
			camera_key = camera_device.device_key
			logger.debug(f"스트림 {stream_num}: API 카메라 정보 사용 - {camera_name} ({camera_key})")
	
	# 2. API 실패 시 기본값 사용
	if camera_name is None or camera_key is None:
		camera_name = str(stream_num)
		camera_key = str(stream_num)
		logger.debug(f"스트림 {stream_num}: 기본 카메라 정보 사용 - {camera_name} ({camera_key})")
	
	camera_id = stream_num
	
	# vessel 정보 우선순위: API 카메라 디바이스 정보 -> blackbox_data -> 기본값
	if camera_device is not None and camera_device.vessel_id is not None:
		vessel_id = camera_device.vessel_id
		vessel_name = camera_device.vessel_name or "vesselTest"
		logger.debug(f"스트림 {stream_num}: API vessel 정보 사용 - {vessel_name} ({vessel_id})")
	elif blackbox_data:
		vessel_id = blackbox_data.vessel_id or 1
		vessel_name = blackbox_data.vessel_name or "vesselTest"
		logger.debug(f"스트림 {stream_num}: Blackbox vessel 정보 사용 - {vessel_name} ({vessel_id})")
	else:
		vessel_id = 1
		vessel_name = "vesselTest"
		logger.debug(f"스트림 {stream_num}: 기본 vessel 정보 사용 - {vessel_name} ({vessel_id})")
	
	# gear 정보는 blackbox_data에서 가져오거나 기본값 사용
	if blackbox_data:
		gear_code = blackbox_data.gear_code or "PS"
		gear_name = blackbox_data.gear_name or "Purse Seine"
		gear_name_ko = blackbox_data.gear_name_ko or "선망"
	else:
		gear_code = "PS"
		gear_name = "Purse Seine"
		gear_name_ko = "선망"
	
	return CameraVideoData(
		camera_id=camera_id,
		camera_name=camera_name,
		camera_key=camera_key,
		vessel_id=vessel_id,
		vessel_name=vessel_name,
		gear_code=gear_code,
		gear_name=gear_name,
		gear_name_ko=gear_name_ko,
		file_name=file_name,
		file_real_name=file_name,
		file_path=os.path.dirname(file_path),
		file_size=file_size,
		file_ext=file_ext,
		record_start_time=record_start_time,
		record_end_time=record_end_time
	)

if __name__ == "__main__":
	# 테스트 코드
	logging.basicConfig(level=logging.DEBUG)
	
	client = BlackboxAPIClient()
	
	print("=== 블랙박스 API 테스트 ===")
	data = client.get_latest_gps()
	if data:
		print(f"선박명: {data.vessel_name}")
		print(f"위치: {data.latitude}, {data.longitude}")
		print(f"속도: {data.speed}")
		print(f"상태: {data.status}")
	else:
		print("데이터 수신 실패") 
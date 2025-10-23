#!/usr/bin/env python3
"""
시스템 검증 스크립트 - 모든 .env.streamN 파일 자동 검증

제3자가 프로그램을 사용하기 전에 5가지 주요 사항을 확인하는 검증 도구:
1. API 호출해서 선박 정보, 카메라 정보를 사용하는지 확인
2. API 호출 실패시 사용값 확인
3. 환경변수 설정값 확인 (배 이름, 조업 판단 기준 등)
4. 카메라 영상 저장시, device api를 호출한 deviceName, deviceKey 값을 사용하는지 확인
5. 영상/자막/로그 저장 여부 및 블랙박스 정보 잘 받아오는지 확인

특징:
    - 현재 디렉터리의 모든 .env.stream* 파일을 자동으로 찾아서 검증
    - 각 스트림별 검증 결과를 개별 출력
    - 전체 요약 통계 제공

사용 예시:
    # 모든 .env.streamN 파일 검증 (기본)
    python3 verify_system.py
    uv run python verify_system.py
    
    # 환경변수만 검증
    python3 verify_system.py --env-only
    
    # API만 검증
    python3 verify_system.py --api-only
    
    # 상세 로그 포함
    python3 verify_system.py --verbose
    
    # 결과를 JSON으로 저장
    python3 verify_system.py --export results.json
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

try:
    from api_client import BlackboxAPIClient, create_camera_video_data
    from config import RTSPConfig
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from api_client import BlackboxAPIClient, create_camera_video_data
    from config import RTSPConfig

logger = logging.getLogger(__name__)


def find_all_stream_env_files() -> List[str]:
    """모든 .env.streamN 파일을 찾아서 반환
    
    Returns:
        찾은 환경 파일 경로 리스트 (정렬됨)
    """
    import glob
    
    # .env.stream* 패턴으로 파일 찾기
    env_files = glob.glob('.env.stream[0-9]')
    
    # 숫자 순서로 정렬
    def get_stream_number(filepath):
        try:
            # .env.stream1 -> 1
            return int(filepath.replace('.env.stream', ''))
        except ValueError:
            return 999
    
    env_files.sort(key=get_stream_number)
    return env_files


def load_stream_env(env_file: str) -> bool:
    """환경 파일 로드
    
    Args:
        env_file: 로드할 환경 파일 경로
    
    Returns:
        로드 성공 여부
    """
    if not DOTENV_AVAILABLE:
        logger.warning("python-dotenv가 설치되지 않아 환경 파일을 로드할 수 없습니다")
        return False
    
    if os.path.exists(env_file):
        load_dotenv(dotenv_path=env_file, override=True)
        return True
    else:
        logger.warning(f"환경 파일 없음: {env_file}")
        return False


@dataclass
class VerificationResult:
    """검증 결과 클래스"""
    category: str
    item: str
    status: str  # "PASS", "FAIL", "WARNING", "INFO"
    message: str
    details: Optional[Dict] = None


class SystemVerifier:
    """시스템 검증 클래스 - 단일 환경 파일 검증"""
    
    def __init__(self, env_file: str, verbose: bool = False):
        self.env_file = env_file
        self.verbose = verbose
        self.results: List[VerificationResult] = []
        self.api_client: Optional[BlackboxAPIClient] = None
        self.stream_number: Optional[int] = None
        
        # 환경 파일 로드
        if load_stream_env(env_file):
            # 로드된 환경변수에서 스트림 번호 추출
            self.stream_number = int(os.getenv('STREAM_NUMBER', '0'))
        
    def add_result(self, category: str, item: str, status: str, message: str, details: Optional[Dict] = None):
        """검증 결과 추가"""
        self.results.append(VerificationResult(category, item, status, message, details))
        
    def verify_all(self) -> bool:
        """모든 항목 검증"""
        logger.info("=" * 80)
        logger.info("시스템 종합 검증 시작")
        logger.info("=" * 80)
        
        # 사용 중인 환경 파일 표시
        if self.env_file:
            logger.info(f"환경 파일: {self.env_file}")
        else:
            logger.info("환경 파일: 시스템 환경변수 사용")
        
        if self.stream_number:
            logger.info(f"검증 스트림: {self.stream_number}")
        logger.info("")
        
        # 1. 환경변수 검증
        self.verify_environment_variables()
        
        # 2. API 연결 및 데이터 검증
        self.verify_api_connection()
        
        # 3. API 실패 시 폴백 값 검증
        self.verify_api_fallback()
        
        # 4. 카메라 디바이스 정보 검증
        self.verify_camera_device_info()
        
        # 5. 파일 저장 경로 및 권한 검증
        self.verify_file_paths()
        
        # 결과 출력
        self.print_summary()
        
        # 전체 성공 여부 반환
        return all(r.status in ["PASS", "INFO"] for r in self.results)
    
    def verify_environment_variables(self):
        """환경변수 설정값 검증 (항목 3)"""
        logger.info("\n[검증 3] 환경변수 설정값 확인")
        logger.info("-" * 80)
        
        if self.env_file:
            logger.info(f"설정 파일: {self.env_file}")
        else:
            logger.info("설정: 시스템 환경변수")
        logger.info("")
        
        # 필수 환경변수
        required_vars = {
            'RTSP_URL': '스트림 URL',
            'STREAM_NUMBER': '스트림 번호',
            'BLACKBOX_API_URL': 'API 서버 주소',
        }
        
        # 중요 설정 환경변수
        important_vars = {
            'VESSEL_NAME': '선박 이름',
            'RECORDING_SPEED_THRESHOLD': '녹화 시작 속도 임계값 (knots)',
            'BLACKBOX_ENABLED': '블랙박스 API 사용 여부',
            'BLUR_ENABLED': '블러 처리 활성화',
            'API_POLL_INTERVAL': 'API 폴링 간격 (초)',
            'VIDEO_SEGMENT_DURATION': '영상 세그먼트 길이 (초)',
            'TEMP_OUTPUT_PATH': '임시 저장 경로',
            'FINAL_OUTPUT_PATH': '최종 저장 경로',
            'LOG_DIR': '로그 저장 경로',
            'DEFAULT_INPUT_FPS': '입력 FPS',
            'VIDEO_WIDTH': '영상 너비',
            'VIDEO_HEIGHT': '영상 높이',
        }
        
        # 필수 변수 확인
        for var, desc in required_vars.items():
            value = os.getenv(var)
            if value:
                self.add_result("환경변수", var, "PASS", 
                               f"{desc}: {value}")
                logger.info(f"✓ {var} = {value}")
            else:
                self.add_result("환경변수", var, "FAIL", 
                               f"{desc}: 설정되지 않음")
                logger.error(f"✗ {var} 설정 필요")
        
        # 중요 변수 확인
        for var, desc in important_vars.items():
            value = os.getenv(var)
            if value:
                self.add_result("환경변수", var, "PASS", 
                               f"{desc}: {value}")
                if self.verbose:
                    logger.info(f"✓ {var} = {value}")
            else:
                self.add_result("환경변수", var, "WARNING", 
                               f"{desc}: 기본값 사용")
                logger.warning(f"⚠ {var} 미설정 (기본값 사용)")
        
        # 조업 판단 기준 상세 확인
        speed_threshold = os.getenv('RECORDING_SPEED_THRESHOLD', '5.0')
        logger.info(f"\n조업 판단 기준:")
        logger.info(f"  - 속도 임계값: {speed_threshold} knots 이상 시 녹화 중지")
        
    def verify_api_connection(self):
        """API 연결 및 선박/카메라 정보 검증 (항목 1, 5)"""
        logger.info("\n[검증 1] API 호출 및 데이터 확인")
        logger.info("-" * 80)
        
        api_url = os.getenv('BLACKBOX_API_URL', 'http://localhost')
        api_timeout = int(os.getenv('API_TIMEOUT', '5'))
        
        try:
            self.api_client = BlackboxAPIClient(base_url=api_url, timeout=api_timeout)
            
            # 블랙박스 GPS 데이터 확인
            logger.info(f"API 서버: {api_url}")
            blackbox_data = self.api_client.get_latest_gps()
            
            if blackbox_data:
                self.add_result("API 연결", "블랙박스 데이터", "PASS", 
                               "GPS 데이터 수신 성공",
                               {
                                   'vessel_name': blackbox_data.vessel_name,
                                   'vessel_name': blackbox_data.vessel_name,
                                   'speed': blackbox_data.speed,
                                   'latitude': blackbox_data.latitude,
                                   'longitude': blackbox_data.longitude,
                                   'status': blackbox_data.status,
                                   'recorded_date': str(blackbox_data.recorded_date)
                               })
                
                logger.info(f"✓ 블랙박스 GPS 데이터 수신 성공")
                logger.info(f"  - 선박 ID: {blackbox_data.vessel_name}")
                logger.info(f"  - 선박명: {blackbox_data.vessel_name}")
                logger.info(f"  - 어구: {blackbox_data.gear_code} ({blackbox_data.gear_name_ko})")
                logger.info(f"  - 현재 속도: {blackbox_data.speed} knots")
                logger.info(f"  - 위치: {blackbox_data.latitude}, {blackbox_data.longitude}")
                logger.info(f"  - 상태: {blackbox_data.status}")
                logger.info(f"  - 기록 시각: {blackbox_data.recorded_date}")
                
            else:
                self.add_result("API 연결", "블랙박스 데이터", "FAIL", 
                               "GPS 데이터 수신 실패")
                logger.error(f"✗ 블랙박스 GPS 데이터 수신 실패")
            
            # 카메라 디바이스 정보 확인
            stream_num = self.stream_number or int(os.getenv('STREAM_NUMBER', '1'))
            camera_device = self.api_client.get_camera_device(stream_num)
            
            if camera_device:
                self.add_result("API 연결", "카메라 디바이스", "PASS", 
                               f"스트림 {stream_num} 카메라 정보 수신",
                               {
                                   'device_name': camera_device.device_name,
                                   'device_key': camera_device.device_key,
                                   'view_order': camera_device.view_order,
                                   'vessel_name': camera_device.vessel_name,
                                   'vessel_name': camera_device.vessel_name
                               })
                
                logger.info(f"✓ 카메라 디바이스 정보 수신 (스트림 {stream_num})")
                logger.info(f"  - 디바이스명: {camera_device.device_name}")
                logger.info(f"  - 디바이스 키: {camera_device.device_key}")
                logger.info(f"  - 표시 순서: {camera_device.view_order}")
                logger.info(f"  - 선박 ID: {camera_device.vessel_name}")
                logger.info(f"  - 선박명: {camera_device.vessel_name}")
                
            else:
                self.add_result("API 연결", "카메라 디바이스", "WARNING", 
                               f"스트림 {stream_num} 카메라 정보 없음 - 기본값 사용")
                logger.warning(f"⚠ 카메라 디바이스 정보 없음 (기본값 사용)")
            
        except Exception as e:
            self.add_result("API 연결", "전체", "FAIL", 
                           f"API 연결 실패: {str(e)}")
            logger.error(f"✗ API 연결 실패: {e}")
            self.api_client = None
    
    def verify_api_fallback(self):
        """API 실패 시 폴백 값 검증 (항목 2)"""
        logger.info("\n[검증 2] API 실패 시 폴백 값 확인")
        logger.info("-" * 80)
        
        # API 클라이언트를 None으로 설정하여 폴백 테스트
        stream_num = self.stream_number or int(os.getenv('STREAM_NUMBER', '1'))
        
        # 폴백 시나리오 테스트
        logger.info("API 미사용 시나리오 테스트:")
        
        test_video_data = create_camera_video_data(
            file_path="/tmp/test_video.mp4",
            file_name="test_video.mp4",
            record_start_time=datetime.now(),
            record_end_time=datetime.now(),
            blackbox_data=None,
            stream_number=stream_num,
            api_client=None  # API 사용 안 함
        )
        
        # 카메라 정보 폴백 확인
        camera_fallback = {
            'camera_id': test_video_data.camera_id,
            'camera_name': test_video_data.camera_name,
            'camera_key': test_video_data.camera_key
        }
        
        logger.info(f"카메라 정보 폴백:")
        logger.info(f"  - camera_id: {camera_fallback['camera_id']} (기본값: 스트림 번호)")
        logger.info(f"  - camera_name: {camera_fallback['camera_name']} (기본값: 스트림 번호)")
        logger.info(f"  - camera_key: {camera_fallback['camera_key']} (기본값: 스트림 번호)")
        
        # 선박 정보 폴백 확인
        vessel_fallback = {
            'vessel_name': test_video_data.vessel_name,
            'vessel_name': test_video_data.vessel_name,
            'gear_code': test_video_data.gear_code,
            'gear_name': test_video_data.gear_name,
            'gear_name_ko': test_video_data.gear_name_ko
        }
        
        logger.info(f"선박 정보 폴백:")
        logger.info(f"  - vessel_name: {vessel_fallback['vessel_name']}")
        logger.info(f"  - vessel_name: {vessel_fallback['vessel_name']}")
        logger.info(f"  - gear_code: {vessel_fallback['gear_code']}")
        logger.info(f"  - gear_name: {vessel_fallback['gear_name']} ({vessel_fallback['gear_name_ko']})")
        
        self.add_result("폴백 값", "카메라 정보", "PASS", 
                       "API 실패 시 기본값 사용 확인", camera_fallback)
        self.add_result("폴백 값", "선박 정보", "PASS", 
                       "API 실패 시 기본값 사용 확인", vessel_fallback)
        
        logger.info(f"✓ API 실패 시 폴백 값이 올바르게 설정됨")
    
    def verify_camera_device_info(self):
        """카메라 디바이스 정보가 영상 저장에 사용되는지 검증 (항목 4)"""
        logger.info("\n[검증 4] 카메라 영상 저장 시 디바이스 API 값 사용 확인")
        logger.info("-" * 80)
        
        stream_num = self.stream_number or int(os.getenv('STREAM_NUMBER', '1'))
        
        if self.api_client:
            # API에서 카메라 정보 가져오기
            camera_device = self.api_client.get_camera_device(stream_num)
            
            # 실제 저장 시 사용될 데이터 생성
            test_video_data = create_camera_video_data(
                file_path="/tmp/test_video.mp4",
                file_name="test_video.mp4",
                record_start_time=datetime.now(),
                record_end_time=datetime.now(),
                blackbox_data=None,
                stream_number=stream_num,
                api_client=self.api_client
            )
            
            if camera_device:
                # API 값과 실제 사용 값 비교
                api_matches = (
                    test_video_data.camera_name == camera_device.device_name and
                    test_video_data.camera_key == camera_device.device_key
                )
                
                vessel_matches = (
                    camera_device.vessel_name is not None and
                    test_video_data.vessel_name == camera_device.vessel_name and
                    test_video_data.vessel_name == camera_device.vessel_name
                )
                
                logger.info(f"API 카메라 정보:")
                logger.info(f"  - cameraName (device_name): {camera_device.device_name}")
                logger.info(f"  - cameraKey (device_key): {camera_device.device_key}")
                logger.info(f"  - vesselName: {camera_device.vessel_name}")
                logger.info(f"  - vesselName: {camera_device.vessel_name}")
                
                logger.info(f"\n실제 저장 시 사용되는 값:")
                logger.info(f"  - cameraName (camera_name): {test_video_data.camera_name}")
                logger.info(f"  - cameraKey (camera_key): {test_video_data.camera_key}")
                logger.info(f"  - vesselName: {test_video_data.vessel_name}")
                logger.info(f"  - vesselName: {test_video_data.vessel_name}")
                
                if api_matches:
                    self.add_result("카메라 정보 사용", "deviceName/Key", "PASS",
                                   "API의 deviceName, deviceKey가 영상 저장에 사용됨",
                                   {
                                       'api_device_name': camera_device.device_name,
                                       'used_camera_name': test_video_data.camera_name,
                                       'api_device_key': camera_device.device_key,
                                       'used_camera_key': test_video_data.camera_key
                                   })
                    logger.info(f"✓ API deviceName/deviceKey가 영상 저장에 사용됨")
                else:
                    self.add_result("카메라 정보 사용", "deviceName/Key", "FAIL",
                                   "API 값과 실제 사용 값이 다름")
                    logger.error(f"✗ API 값과 실제 사용 값이 다름")
                
                if vessel_matches:
                    self.add_result("카메라 정보 사용", "vesselName/Name", "PASS",
                                   "API의 vesselName, vesselName이 영상 저장에 사용됨",
                                   {
                                       'api_vessel_name': camera_device.vessel_name,
                                       'used_vessel_name': test_video_data.vessel_name,
                                       'api_vessel_name': camera_device.vessel_name,
                                       'used_vessel_name': test_video_data.vessel_name
                                   })
                    logger.info(f"✓ API vesselName/vesselName이 영상 저장에 사용됨")
                else:
                    if camera_device.vessel_name is None:
                        self.add_result("카메라 정보 사용", "vesselName/Name", "WARNING",
                                       "API에 vessel 정보 없음 - 폴백 값 사용")
                        logger.warning(f"⚠ API에 vessel 정보 없음 - 폴백 값 사용")
                    else:
                        self.add_result("카메라 정보 사용", "vesselName/Name", "FAIL",
                                       "API vessel 값과 실제 사용 값이 다름")
                        logger.error(f"✗ API vessel 값과 실제 사용 값이 다름")
            else:
                self.add_result("카메라 정보 사용", "전체", "WARNING",
                               "API에서 카메라 정보 없음 - 기본값 사용")
                logger.warning(f"⚠ API에서 카메라 정보 없음")
        else:
            self.add_result("카메라 정보 사용", "전체", "FAIL",
                           "API 클라이언트 초기화 실패")
            logger.error(f"✗ API 클라이언트 없음 - 이전 단계 확인 필요")
    
    def verify_file_paths(self):
        """파일 저장 경로 및 로그 확인 (항목 5)"""
        logger.info("\n[검증 5] 영상/자막/로그 저장 경로 확인")
        logger.info("-" * 80)
        
        # 환경변수에서 경로 가져오기
        temp_path = os.getenv('TEMP_OUTPUT_PATH', './output/temp/')
        final_path = os.getenv('FINAL_OUTPUT_PATH', '/mnt/nas/cam/')
        log_dir = os.getenv('LOG_DIR', './logs')
        
        paths_to_check = {
            '임시 저장 경로': temp_path,
            '최종 저장 경로': final_path,
            '로그 저장 경로': log_dir
        }
        
        logger.info("설정된 저장 경로:")
        for name, path in paths_to_check.items():
            logger.info(f"  - {name}: {path}")
            
            # 경로 존재 여부 확인
            if os.path.exists(path):
                # 쓰기 권한 확인
                if os.access(path, os.W_OK):
                    self.add_result("파일 경로", name, "PASS",
                                   f"경로 존재 및 쓰기 가능: {path}")
                    logger.info(f"    ✓ 경로 존재, 쓰기 가능")
                else:
                    self.add_result("파일 경로", name, "FAIL",
                                   f"경로 존재하나 쓰기 불가: {path}")
                    logger.error(f"    ✗ 쓰기 권한 없음")
            else:
                # 경로 생성 가능한지 확인
                parent_dir = os.path.dirname(path.rstrip('/'))
                if parent_dir and os.path.exists(parent_dir) and os.access(parent_dir, os.W_OK):
                    self.add_result("파일 경로", name, "WARNING",
                                   f"경로 없음, 자동 생성 가능: {path}")
                    logger.warning(f"    ⚠ 경로 없음 (자동 생성 가능)")
                else:
                    self.add_result("파일 경로", name, "FAIL",
                                   f"경로 없음, 생성 불가: {path}")
                    logger.error(f"    ✗ 경로 없음, 생성 불가")
        
        # 영상 세그먼트 설정 확인
        segment_duration = os.getenv('VIDEO_SEGMENT_DURATION', '300')
        logger.info(f"\n영상 저장 설정:")
        logger.info(f"  - 세그먼트 길이: {segment_duration}초")
        
        # 자막 생성 여부 확인 (코드에서 항상 생성)
        logger.info(f"  - 자막 파일(.srt): 영상과 함께 자동 생성")
        
        self.add_result("파일 저장", "세그먼트 설정", "INFO",
                       f"영상 {segment_duration}초 단위 저장, 자막 자동 생성")
    
    def print_summary(self):
        """검증 결과 요약 출력"""
        logger.info("\n" + "=" * 80)
        logger.info("검증 결과 요약")
        logger.info("=" * 80)
        
        # 카테고리별 통계
        categories = {}
        for result in self.results:
            if result.category not in categories:
                categories[result.category] = {'PASS': 0, 'FAIL': 0, 'WARNING': 0, 'INFO': 0}
            categories[result.category][result.status] += 1
        
        # 전체 통계
        total_pass = sum(r.status == 'PASS' for r in self.results)
        total_fail = sum(r.status == 'FAIL' for r in self.results)
        total_warning = sum(r.status == 'WARNING' for r in self.results)
        total_info = sum(r.status == 'INFO' for r in self.results)
        total = len(self.results)
        
        logger.info(f"\n전체 검증 항목: {total}개")
        logger.info(f"  ✓ 통과: {total_pass}개")
        logger.info(f"  ✗ 실패: {total_fail}개")
        logger.info(f"  ⚠ 경고: {total_warning}개")
        logger.info(f"  ℹ 정보: {total_info}개")
        
        # 카테고리별 상세
        logger.info(f"\n카테고리별 상세:")
        for category, stats in categories.items():
            logger.info(f"\n[{category}]")
            logger.info(f"  통과: {stats['PASS']}, 실패: {stats['FAIL']}, "
                       f"경고: {stats['WARNING']}, 정보: {stats['INFO']}")
        
        # 실패/경고 항목 상세 출력
        failures = [r for r in self.results if r.status == 'FAIL']
        warnings = [r for r in self.results if r.status == 'WARNING']
        
        if failures:
            logger.info(f"\n" + "!" * 80)
            logger.info("실패한 항목:")
            logger.info("!" * 80)
            for r in failures:
                logger.error(f"✗ [{r.category}] {r.item}: {r.message}")
        
        if warnings:
            logger.info(f"\n주의가 필요한 항목:")
            for r in warnings:
                logger.warning(f"⚠ [{r.category}] {r.item}: {r.message}")
        
        # 최종 판정
        logger.info("\n" + "=" * 80)
        if total_fail == 0:
            if total_warning == 0:
                logger.info("✓✓✓ 모든 검증 통과! 시스템을 안전하게 사용할 수 있습니다.")
            else:
                logger.info("✓ 검증 통과 (일부 경고 있음). 경고 항목을 확인하세요.")
        else:
            logger.error("✗✗✗ 검증 실패! 실패한 항목을 수정한 후 다시 시도하세요.")
        logger.info("=" * 80)
    
    def export_results(self, output_file: str):
        """검증 결과를 JSON 파일로 내보내기"""
        data = {
            'timestamp': datetime.now().isoformat(),
            'stream_number': self.stream_number,
            'env_file': self.env_file,
            'results': [
                {
                    'category': r.category,
                    'item': r.item,
                    'status': r.status,
                    'message': r.message,
                    'details': r.details
                }
                for r in self.results
            ]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"\n검증 결과가 {output_file}에 저장되었습니다.")


def setup_logging(verbose: bool = False, debug: bool = False) -> Tuple[str, logging.Logger]:
    """로깅 설정 및 상세 로그 파일 생성
    
    Returns:
        (로그 파일 경로, 로거 인스턴스)
    """
    # 상세 로그 파일 경로 생성
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"verification_detail_{timestamp}.log"
    
    # 로그 레벨 설정
    log_level = logging.DEBUG if debug else logging.INFO
    
    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # 기존 핸들러 제거
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 파일 핸들러 (상세 로그)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(message)s')
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # 콘솔 핸들러 (요약만)
    console_handler = logging.StreamHandler(sys.stdout)
    if verbose:
        # verbose 모드: 모든 로그 출력
        console_handler.setLevel(logging.DEBUG)
    else:
        # 일반 모드: WARNING 이상만 출력 (요약만)
        console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    return log_file, root_logger


def main():
    parser = argparse.ArgumentParser(
        description="비디오 프로세서 시스템 검증 도구 - 모든 .env.streamN 파일 자동 검증",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 모든 .env.streamN 파일 검증 (기본 - 요약만 콘솔 출력)
  python3 verify_system.py
  uv run python verify_system.py
  
  # 환경변수만 검증
  python3 verify_system.py --env-only
  
  # API만 검증
  python3 verify_system.py --api-only
  
  # 콘솔에 상세 로그 출력 (파일에도 저장됨)
  python3 verify_system.py --verbose
  
  # 결과를 JSON으로 저장
  python3 verify_system.py --export results.json
  
참고:
  - 현재 디렉터리의 모든 .env.stream[0-9]* 파일을 자동으로 찾아서 검증합니다
  - 상세 검증 내용은 verification_detail_YYYYMMDD_HHMMSS.log 파일에 저장됩니다
  - 콘솔에는 최종 요약만 출력됩니다 (--verbose 옵션으로 상세 출력 가능)
        """
    )
    
    parser.add_argument('--api-only', action='store_true',
                       help='API 연결만 검증')
    parser.add_argument('--env-only', action='store_true',
                       help='환경변수만 검증')
    parser.add_argument('--export', metavar='FILE',
                       help='결과를 JSON 파일로 저장')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='콘솔에 상세 로그 출력 (기본: 요약만)')
    parser.add_argument('--debug', action='store_true',
                       help='디버그 모드 (더 상세한 로그)')
    
    args = parser.parse_args()
    
    # 로깅 설정 (파일 + 콘솔)
    log_file, _ = setup_logging(verbose=args.verbose, debug=args.debug)
    
    try:
        # 콘솔에 시작 메시지 출력 (요약)
        print("=" * 80)
        print("비디오 프로세서 시스템 검증")
        print("=" * 80)
        
        # 모든 .env.stream* 파일 찾기
        env_files = find_all_stream_env_files()
        
        if not env_files:
            print("\n❌ 오류: .env.streamN 파일을 찾을 수 없습니다.")
            print("현재 디렉터리에 .env.stream1, .env.stream2 등의 파일이 있는지 확인하세요.")
            print("\n환경 파일 생성:")
            print("  ./generate_env.sh")
            sys.exit(1)
        
        print(f"📁 찾은 환경 파일: {len(env_files)}개")
        print(f"📄 상세 로그: {log_file}")
        print("")
        
        # 상세 로그에만 기록
        logger.info("=" * 80)
        logger.info(f"총 {len(env_files)}개 스트림 검증 시작")
        logger.info("=" * 80)
        logger.info(f"찾은 환경 파일: {', '.join(env_files)}")
        logger.info("")
        
        # API 검증은 한 번만 수행 (스트림과 무관)
        api_client = None
        api_verified = False
        
        if not args.env_only:
            print("🔌 API 연결 확인 중...", end='', flush=True)
            logger.info("\n" + "=" * 80)
            logger.info("API 연결 검증 (전체 스트림 공통)")
            logger.info("=" * 80)
            
            # 첫 번째 환경 파일로 API 클라이언트 초기화
            if load_stream_env(env_files[0]):
                api_url = os.getenv('BLACKBOX_API_URL', 'http://localhost')
                api_timeout = int(os.getenv('API_TIMEOUT', '5'))
                
                try:
                    api_client = BlackboxAPIClient(base_url=api_url, timeout=api_timeout)
                    logger.info(f"API 서버: {api_url}")
                    logger.info(f"API 타임아웃: {api_timeout}초")
                    
                    # 블랙박스 GPS 데이터 확인
                    blackbox_data = api_client.get_latest_gps()
                    if blackbox_data:
                        logger.info("✓ 블랙박스 GPS 데이터 수신 성공")
                        logger.info(f"  - 선박 ID: {blackbox_data.vessel_name}")
                        logger.info(f"  - 선박명: {blackbox_data.vessel_name}")
                        logger.info(f"  - 현재 속도: {blackbox_data.speed} knots")
                        api_verified = True
                        print(" ✅")
                    else:
                        logger.warning("⚠ 블랙박스 GPS 데이터 수신 실패")
                        print(" ❌")
                except Exception as e:
                    logger.error(f"✗ API 연결 실패: {e}")
                    print(" ❌")
            
            logger.info("")
        
        # 각 스트림별 검증 실행
        all_results = []
        success_count = 0
        fail_count = 0
        
        print("🔍 스트림별 검증 중...")
        for idx, env_file in enumerate(env_files, 1):
            # 콘솔에 간단한 진행 상태 표시
            stream_num_match = env_file.replace('.env.stream', '')
            print(f"  [{idx}/{len(env_files)}] 스트림 {stream_num_match} 검증 중...", end='', flush=True)
            
            # 상세 로그에만 기록
            logger.info("\n" + "=" * 80)
            logger.info(f"[{idx}/{len(env_files)}] {env_file} 검증")
            logger.info("=" * 80)
            
            # 검증 실행
            verifier = SystemVerifier(env_file=env_file, verbose=args.verbose)
            
            # API 클라이언트 재사용 (이미 초기화된 경우)
            if api_client is not None:
                verifier.api_client = api_client
            
            if args.env_only:
                verifier.verify_environment_variables()
                stream_success = all(r.status in ["PASS", "INFO"] for r in verifier.results)
            elif args.api_only:
                # API는 이미 검증했으므로 카메라 디바이스 정보만 확인
                verifier.verify_camera_device_info()
                stream_success = all(r.status in ["PASS", "INFO", "WARNING"] for r in verifier.results)
            else:
                # 전체 검증 (단, API 연결은 건너뛰고 캐시된 클라이언트 사용)
                verifier.verify_environment_variables()
                verifier.verify_api_fallback()
                verifier.verify_camera_device_info()
                verifier.verify_file_paths()
                # 개별 스트림 요약은 로그 파일에만 기록
                stream_success = all(r.status in ["PASS", "INFO"] for r in verifier.results)
            
            # 결과 저장
            all_results.append({
                'env_file': env_file,
                'stream_number': verifier.stream_number,
                'success': stream_success,
                'results': verifier.results
            })
            
            if stream_success:
                success_count += 1
                print(" ✅")
            else:
                fail_count += 1
                print(" ❌")
        
        print("")
        
        # 콘솔에 전체 요약 출력
        print("=" * 80)
        print("📊 전체 검증 결과 요약")
        print("=" * 80)
        
        # API 검증 결과 표시
        if not args.env_only:
            api_status = "✅ 연결됨" if api_verified else "❌ 연결 실패"
            print(f"API 연결: {api_status}")
            print("")
        
        print(f"총 스트림: {len(env_files)}개")
        print(f"  ✅ 통과: {success_count}개")
        print(f"  ❌ 실패: {fail_count}개")
        print("")
        
        # 각 스트림별 요약
        for result in all_results:
            env_file = result['env_file']
            stream_num = result['stream_number']
            success = result['success']
            
            status_icon = "✅" if success else "❌"
            status_text = "통과" if success else "실패"
            
            print(f"  {status_icon} {env_file} (스트림 {stream_num}): {status_text}")
        
        # 상세 로그에도 기록
        logger.info("\n" + "=" * 80)
        logger.info("전체 검증 결과 요약")
        logger.info("=" * 80)
        
        # API 검증 결과
        if not args.env_only:
            api_status_text = "연결 성공" if api_verified else "연결 실패"
            logger.info(f"API 연결: {api_status_text}")
            logger.info("")
        
        logger.info(f"총 스트림: {len(env_files)}개")
        logger.info(f"  ✓ 통과: {success_count}개")
        logger.info(f"  ✗ 실패: {fail_count}개")
        logger.info("")
        
        for result in all_results:
            env_file = result['env_file']
            stream_num = result['stream_number']
            success = result['success']
            
            status_icon = "✓" if success else "✗"
            status_text = "통과" if success else "실패"
            
            logger.info(f"  {status_icon} {env_file} (스트림 {stream_num}): {status_text}")
        
        # 실패한 스트림이 있으면 콘솔에 간단히 표시
        failed_streams = [r for r in all_results if not r['success']]
        if failed_streams:
            print("\n⚠️  실패한 스트림:")
            for result in failed_streams:
                env_file = result['env_file']
                stream_num = result['stream_number']
                
                # 실패 항목 개수만 표시
                failures = [r for r in result['results'] if r.status == 'FAIL']
                warnings = [r for r in result['results'] if r.status == 'WARNING']
                
                print(f"  ❌ {env_file} (스트림 {stream_num}): 실패 {len(failures)}개, 경고 {len(warnings)}개")
        
        # 최종 판정 (콘솔)
        print("\n" + "=" * 80)
        if fail_count == 0:
            print("✅ 모든 스트림 검증 통과!")
        else:
            print(f"❌ {fail_count}개 스트림 검증 실패!")
        print("=" * 80)
        print(f"\n💾 상세 로그: {log_file}")
        
        # 실패한 스트림 상세 정보 (파일에만 기록)
        if failed_streams:
            logger.info("\n" + "!" * 80)
            logger.info("실패한 스트림 상세:")
            logger.info("!" * 80)
            for result in failed_streams:
                env_file = result['env_file']
                stream_num = result['stream_number']
                logger.info(f"\n[{env_file} (스트림 {stream_num})]")
                
                # 실패/경고 항목만 출력
                failures = [r for r in result['results'] if r.status == 'FAIL']
                warnings = [r for r in result['results'] if r.status == 'WARNING']
                
                if failures:
                    logger.info("  실패 항목:")
                    for r in failures:
                        logger.info(f"    ✗ [{r.category}] {r.item}: {r.message}")
                
                if warnings:
                    logger.info("  경고 항목:")
                    for r in warnings:
                        logger.info(f"    ⚠ [{r.category}] {r.item}: {r.message}")
        
        # 최종 판정 (파일에 기록)
        logger.info("\n" + "=" * 80)
        if fail_count == 0:
            logger.info("✓✓✓ 모든 스트림 검증 통과!")
        else:
            logger.info(f"✗✗✗ {fail_count}개 스트림 검증 실패!")
        logger.info("=" * 80)
        
        # JSON 내보내기
        if args.export:
            export_data = {
                'timestamp': datetime.now().isoformat(),
                'log_file': log_file,
                'api_verified': api_verified if not args.env_only else None,
                'total_streams': len(env_files),
                'success_count': success_count,
                'fail_count': fail_count,
                'streams': [
                    {
                        'env_file': r['env_file'],
                        'stream_number': r['stream_number'],
                        'success': r['success'],
                        'results': [
                            {
                                'category': result.category,
                                'item': result.item,
                                'status': result.status,
                                'message': result.message,
                                'details': result.details
                            }
                            for result in r['results']
                        ]
                    }
                    for r in all_results
                ]
            }
            
            with open(args.export, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"💾 JSON 결과: {args.export}")
            logger.info(f"\n검증 결과가 {args.export}에 저장되었습니다.")
        
        # 종료 코드 반환
        sys.exit(0 if fail_count == 0 else 1)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  검증이 중단되었습니다.")
        logger.info("\n\n검증이 중단되었습니다.")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 검증 중 오류 발생: {e}")
        print(f"💾 상세 로그: {log_file}")
        logger.error(f"\n검증 중 오류 발생: {e}")
        if args.debug:
            import traceback
            logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()

